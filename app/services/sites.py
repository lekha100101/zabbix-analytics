from collections import defaultdict
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Host, Problem


# Expected convention: <equipment>-<region>-<site>, e.g. ILO5-ZHET-MB.
# Equipment may itself contain dashes; the last two tokens define the site.
SITE_RE = re.compile(r"^(?P<equipment>.+)-(?P<region>[A-Za-z0-9]+)-(?P<site>[A-Za-z0-9]+)$")


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
            "problems": [],
        })
        site["hosts_total"] += 1
        site["equipment"][parsed["equipment"]] += 1

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
            })
        for key in site_keys:
            sites[key]["problems"].append({
                "eventid": str(problem.zabbix_eventid),
                "name": problem.name,
                "severity": problem.severity,
                "impact_score": problem.impact_score,
                "started_at": problem.started_at,
                "hosts": [h for h in matched_hosts if parse_host_name(h["name"]) and parse_host_name(h["name"])["site_key"] == key],
            })

    result = []
    for site in sites.values():
        problems_for_site = sorted(site["problems"], key=lambda p: (-p["impact_score"], p["started_at"]))
        if not problems_for_site:
            continue
        max_score = max(p["impact_score"] for p in problems_for_site)
        affected = len(site["affected_hostids"])
        # Site risk is anchored to the worst problem, with a modest multi-device
        # bonus. This avoids simply summing many low-value warnings.
        multi_device_bonus = min(15, max(0, affected - 1) * 3)
        problem_volume_bonus = min(10, max(0, len(problems_for_site) - 1))
        risk_score = min(100, max_score + multi_device_bonus + problem_volume_bonus)
        result.append({
            "site_key": site["site_key"],
            "region": site["region"],
            "site": site["site"],
            "risk_score": risk_score,
            "max_problem_score": max_score,
            "active_problems": len(problems_for_site),
            "affected_hosts": affected,
            "hosts_total": site["hosts_total"],
            "equipment": dict(sorted(site["equipment"].items())),
            "top_problems": problems_for_site[:10],
        })

    return sorted(result, key=lambda x: (-x["risk_score"], -x["affected_hosts"], x["site_key"]))
