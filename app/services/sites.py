from collections import defaultdict
from datetime import datetime, timezone
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Host, Problem


# Expected convention: <equipment>-<region>-<site>, e.g. ILO5-ZHET-MB.
# Equipment may itself contain dashes; the last two tokens define the site.
SITE_RE = re.compile(r"^(?P<equipment>.+)-(?P<region>[A-Za-z0-9]+)-(?P<site>[A-Za-z0-9]+)$")

ROLE_PREFIXES = {
    "gateway": ("GW", "RTR", "ROUTER", "FW", "FGT"),
    "switch": ("SW", "SWT", "ARUBA", "FORTISWITCH"),
    "server_mgmt": ("ILO", "IDRAC", "IPMI"),
    "pacs": ("PACS",),
    "database": ("DB", "PG", "POSTGRES", "MSSQL", "SQL"),
    "storage": ("STORAGE", "NAS", "SAN", "NETAPP"),
    "server": ("SRV", "SERVER", "VM"),
}


def equipment_role(equipment: str) -> str:
    value = (equipment or "").upper()
    for role, prefixes in ROLE_PREFIXES.items():
        if any(value.startswith(prefix) for prefix in prefixes):
            return role
    return "other"


def parse_host_name(name: str) -> dict | None:
    value = (name or "").strip()
    match = SITE_RE.match(value)
    if not match:
        return None
    region = match.group("region").upper()
    site = match.group("site").upper()
    return {
        "equipment": match.group("equipment").upper(),
        "region": region,
        "site": site,
        "site_key": f"{region}-{site}",
    }


def _problem_hostids(problem: Problem) -> set[int]:
    result: set[int] = set()
    for host in problem.hosts or []:
        try:
            result.add(int(host.get("hostid")))
        except (TypeError, ValueError):
            pass
    return result


def site_analytics(db: Session) -> list[dict]:
    hosts = db.scalars(select(Host).where(Host.status == 0)).all()
    problems = db.scalars(select(Problem).where(Problem.active.is_(True))).all()

    host_map: dict[int, tuple[Host, dict]] = {}
    sites: dict[str, dict] = {}
    for host in hosts:
        parsed = parse_host_name(host.technical_name or host.visible_name)
        if not parsed:
            continue
        host_map[host.zabbix_hostid] = (host, parsed)
        site = sites.setdefault(parsed["site_key"], {
            "site_key": parsed["site_key"],
            "region": parsed["region"],
            "site": parsed["site"],
            "hosts_total": 0,
            "affected_hostids": set(),
            "equipment": defaultdict(int),
            "roles": defaultdict(int),
            "problems": [],
        })
        site["hosts_total"] += 1
        site["equipment"][parsed["equipment"]] += 1
        site["roles"][equipment_role(parsed["equipment"])] += 1

    for problem in problems:
        site_keys: set[str] = set()
        matched_hosts: list[dict] = []
        for hostid in _problem_hostids(problem):
            item = host_map.get(hostid)
            if not item:
                continue
            host, parsed = item
            site_keys.add(parsed["site_key"])
            sites[parsed["site_key"]]["affected_hostids"].add(hostid)
            matched_hosts.append({
                "hostid": str(hostid),
                "name": host.visible_name,
                "equipment": parsed["equipment"],
                "role": equipment_role(parsed["equipment"]),
                "site_key": parsed["site_key"],
            })
        for key in site_keys:
            sites[key]["problems"].append({
                "eventid": str(problem.zabbix_eventid),
                "name": problem.name,
                "severity": problem.severity,
                "impact_score": problem.impact_score,
                "started_at": problem.started_at,
                "hosts": [h for h in matched_hosts if h["site_key"] == key],
            })

    result = []
    for site in sites.values():
        problems_for_site = sorted(site["problems"], key=lambda p: (-p["impact_score"], p["started_at"]))
        if not problems_for_site:
            continue
        max_score = max(p["impact_score"] for p in problems_for_site)
        affected = len(site["affected_hostids"])
        affected_ratio = round((affected / site["hosts_total"]) * 100, 1) if site["hosts_total"] else 0.0

        now = datetime.now(timezone.utc)
        burst_5m = sum(1 for p in problems_for_site if (now - p["started_at"]).total_seconds() <= 300)
        burst_15m = sum(1 for p in problems_for_site if (now - p["started_at"]).total_seconds() <= 900)

        affected_roles = {
            h["role"]
            for p in problems_for_site
            for h in p["hosts"]
        }
        gateway_affected = "gateway" in affected_roles
        critical_service_affected = bool({"pacs", "database", "storage"} & affected_roles)

        multi_device_bonus = min(15, max(0, affected - 1) * 3)
        problem_volume_bonus = min(10, max(0, len(problems_for_site) - 1))
        outage_ratio_bonus = 15 if affected_ratio >= 75 else 10 if affected_ratio >= 50 else 5 if affected_ratio >= 25 else 0
        burst_bonus = 10 if burst_5m >= 5 else 6 if burst_15m >= 5 else 3 if burst_15m >= 3 else 0
        gateway_bonus = 10 if gateway_affected and affected >= 2 else 0
        critical_service_bonus = 5 if critical_service_affected else 0

        probable_cause = None
        if gateway_affected and affected_ratio >= 50:
            probable_cause = "Вероятная проблема связи/GW объекта"
        elif gateway_affected and affected >= 2:
            probable_cause = "Возможная проблема шлюза или WAN"
        elif burst_5m >= 5:
            probable_cause = "Массовый всплеск проблем на объекте"
        elif affected_ratio >= 75:
            probable_cause = "Большая часть оборудования объекта недоступна"
        elif critical_service_affected:
            probable_cause = "Затронут критичный сервис объекта"

        risk_score = min(
            100,
            max_score + multi_device_bonus + problem_volume_bonus
            + outage_ratio_bonus + burst_bonus + gateway_bonus + critical_service_bonus,
        )
        result.append({
            "site_key": site["site_key"],
            "region": site["region"],
            "site": site["site"],
            "risk_score": risk_score,
            "max_problem_score": max_score,
            "active_problems": len(problems_for_site),
            "affected_hosts": affected,
            "hosts_total": site["hosts_total"],
            "affected_ratio": affected_ratio,
            "burst_5m": burst_5m,
            "burst_15m": burst_15m,
            "gateway_affected": gateway_affected,
            "critical_service_affected": critical_service_affected,
            "probable_cause": probable_cause,
            "risk_breakdown": {
                "max_problem": max_score,
                "multi_device": multi_device_bonus,
                "problem_volume": problem_volume_bonus,
                "affected_ratio": outage_ratio_bonus,
                "burst": burst_bonus,
                "gateway": gateway_bonus,
                "critical_service": critical_service_bonus,
            },
            "equipment": dict(sorted(site["equipment"].items())),
            "roles": dict(sorted(site["roles"].items())),
            "top_problems": problems_for_site[:10],
        })

    return sorted(result, key=lambda x: (-x["risk_score"], -x["affected_hosts"], x["site_key"]))
