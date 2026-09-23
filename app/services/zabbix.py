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

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": next(self._ids),
        }
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=self.timeout,
        ) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            error = data["error"]
            raise ZabbixAPIError(
                f"Zabbix API error {error.get('code')}: {error.get('message')} - {error.get('data')}"
            )

        return data.get("result")

    async def version(self) -> str:
        # Zabbix requires apiinfo.version to be called without authorization.
        return await self.call("apiinfo.version", authenticated=False)

    async def problems(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.call(
            "problem.get",
            {
                "output": [
                    "eventid",
                    "objectid",
                    "name",
                    "severity",
                    "clock",
                    "acknowledged",
                ],
                "selectHosts": ["hostid", "host", "name"],
                "selectTags": "extend",
                "recent": False,
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": limit,
            },
        )
