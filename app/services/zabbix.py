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

        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.timeout) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            error = data["error"]
            raise ZabbixAPIError(f"Zabbix API error {error.get('code')}: {error.get('message')} - {error.get('data')}")
        return data.get("result")

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
        return await self.call("trigger.get", {
            "output": ["triggerid", "description", "priority", "status"],
            "filter": {"status": 0},
            "selectHosts": ["hostid", "host", "name"],
            "selectTags": "extend",
        })

    async def problems(self, limit: int = 1000) -> list[dict[str, Any]]:
        problems = await self.call("problem.get", {
            "output": ["eventid", "objectid", "name", "severity", "clock", "acknowledged"],
            "selectTags": "extend",
            "recent": False,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": limit,
        })
        trigger_ids = list({str(p["objectid"]) for p in problems if p.get("objectid")})
        hosts_by_trigger: dict[str, list[dict[str, Any]]] = {}
        if trigger_ids:
            triggers = await self.call("trigger.get", {
                "output": ["triggerid"],
                "triggerids": trigger_ids,
                "selectHosts": ["hostid", "host", "name"],
            })
            hosts_by_trigger = {str(t["triggerid"]): t.get("hosts", []) for t in triggers}
        for problem in problems:
            problem["hosts"] = hosts_by_trigger.get(str(problem.get("objectid", "")), [])
        return problems
