from itertools import count
from typing import Any

import httpx

from app.config import get_settings


class ZabbixAPIError(RuntimeError):
    pass


class ZabbixClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_url = f"{settings.zabbix_url.rstrip('/')}/api_jsonrpc.php"
        self.token = settings.zabbix_token
        self.verify_ssl = settings.zabbix_verify_ssl
        self.timeout = settings.zabbix_timeout
        self._ids = count(1)

    async def call(self, method: str, params: dict[str, Any] | None = None, *, authenticated: bool = True) -> Any:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": next(self._ids)}
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.timeout) as client:
                response = await client.post(self.api_url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise ZabbixAPIError(f"Zabbix request failed: method={method}, url={self.api_url}, error={exc}") from exc

        if response.status_code >= 400:
            body = response.text.strip().replace("\n", " ")
            if len(body) > 1000:
                body = body[:1000] + "..."
            raise ZabbixAPIError(
                f"Zabbix HTTP error: method={method}, status={response.status_code}, "
                f"url={self.api_url}, response={body or '<empty>'}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            body = response.text.strip().replace("\n", " ")[:1000]
            raise ZabbixAPIError(
                f"Zabbix returned non-JSON response: method={method}, status={response.status_code}, response={body}"
            ) from exc

        if "error" in data:
            error = data["error"]
            raise ZabbixAPIError(
                f"Zabbix API error: method={method}, code={error.get('code')}, "
                f"message={error.get('message')}, data={error.get('data')}"
            )
        return data.get("result")

    @staticmethod
    def _chunks(values: list[str], size: int = 100):
        for i in range(0, len(values), size):
            yield values[i:i + size]

    async def version(self) -> str:
        return await self.call("apiinfo.version", authenticated=False)

    async def host_groups(self) -> list[dict[str, Any]]:
        return await self.call("hostgroup.get", {"output": ["groupid", "name"], "sortfield": "name"})

    async def hosts(self) -> list[dict[str, Any]]:
        return await self.call("host.get", {
            "output": ["hostid", "host", "name", "status"],
            "selectHostGroups": ["groupid", "name"],
            "selectTags": "extend",
        })

    async def triggers(self) -> list[dict[str, Any]]:
        triggers = await self.call("trigger.get", {
            "output": ["triggerid", "description", "priority", "status"],
            "filter": {"status": 0},
        })
        for trigger in triggers:
            trigger["hosts"] = []
            trigger["tags"] = []
        return triggers

    async def _active_trigger_context(self, trigger_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Return hosts only for enabled triggers that belong to enabled hosts."""
        active: dict[str, list[dict[str, Any]]] = {}
        for batch in self._chunks(trigger_ids, 100):
            triggers = await self.call("trigger.get", {
                "output": ["triggerid", "status"],
                "triggerids": batch,
                "filter": {"status": 0},
                "selectHosts": ["hostid", "host", "name", "status"],
            })
            for trigger in triggers:
                enabled_hosts = [
                    host for host in (trigger.get("hosts") or [])
                    if str(host.get("status", "0")) == "0"
                ]
                if enabled_hosts:
                    active[str(trigger["triggerid"])] = enabled_hosts
        return active

    async def trigger_context(self, trigger_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Return hosts for triggers, including disabled ones, for historical analytics."""
        context: dict[str, list[dict[str, Any]]] = {}
        for batch in self._chunks(trigger_ids, 100):
            triggers = await self.call("trigger.get", {
                "output": ["triggerid", "status"],
                "triggerids": batch,
                "selectHosts": ["hostid", "host", "name", "status"],
            })
            for trigger in triggers:
                context[str(trigger["triggerid"])] = trigger.get("hosts") or []
        return context

    async def problem_history(self, time_from: int, limit: int = 10000) -> list[dict[str, Any]]:
        events = await self.call("event.get", {
            "output": ["eventid", "objectid", "name", "severity", "clock", "r_eventid"],
            "source": 0,
            "object": 0,
            "value": 1,
            "time_from": time_from,
            "selectTags": "extend",
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": limit,
        })
        trigger_ids = list({str(e["objectid"]) for e in events if e.get("objectid")})
        context = await self.trigger_context(trigger_ids) if trigger_ids else {}
        for event in events:
            event["hosts"] = context.get(str(event.get("objectid", "")), [])
        return events

    async def problems(self, limit: int = 1000) -> list[dict[str, Any]]:
        problems = await self.call("problem.get", {
            "output": [
                "eventid", "objectid", "name", "severity", "clock",
                "acknowledged", "r_eventid",
            ],
            "selectTags": "extend",
            "recent": False,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": limit,
        })

        # Keep only unresolved events first.
        problems = [p for p in problems if str(p.get("r_eventid", "0")) in ("0", "", "None")]

        trigger_ids = list({str(p["objectid"]) for p in problems if p.get("objectid")})
        active_triggers = await self._active_trigger_context(trigger_ids) if trigger_ids else {}

        # An operational problem must belong to an enabled trigger and at least
        # one enabled host. Disabled trigger/host events remain in our database
        # history, but are not returned as current active problems.
        active_problems: list[dict[str, Any]] = []
        for problem in problems:
            trigger_id = str(problem.get("objectid", ""))
            hosts = active_triggers.get(trigger_id)
            if not hosts:
                continue
            problem["hosts"] = hosts
            active_problems.append(problem)

        return active_problems
