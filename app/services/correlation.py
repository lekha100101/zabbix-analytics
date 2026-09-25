from datetime import timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Host, ProblemEvent

POWER_PATTERNS = (
    "on battery", "battery mode", "running on battery", "ups is on battery",
    "utility power failure", "utility power is down", "utility power lost",
    "input power lost", "input power failure", "mains failure", "mains lost",
    "line power failure", "ac input failure",
)


def _parse_site(name):
    value = (name or "").strip()
    parts = value.split("-")
    if len(parts) < 3:
        return None
    return {"equipment": "-".join(parts[:-2]).upper(), "site_key": f"{parts[-2].upper()}-{parts[-1].upper()}"}

BATTERY_LOW_PATTERNS = (
    "battery low", "low battery", "battery charge is low",
    "battery capacity is low", "remaining battery",
)

def _matches(name, patterns):
    value = (name or "").lower()
    return any(p in value for p in patterns)

def power_correlation(db: Session, site_key: str, outage_started_at, window_minutes: int = 60):
    if not outage_started_at:
        return None
    if outage_started_at.tzinfo is None:
        outage_started_at = outage_started_at.replace(tzinfo=timezone.utc)
    since = outage_started_at - timedelta(minutes=window_minutes)
    hosts = db.scalars(select(Host).where(Host.status == 0)).all()
    site_hostids = set()
    ups_hostids = set()
    for host in hosts:
        parsed = _parse_site(host.technical_name or host.visible_name)
        if not parsed or parsed["site_key"] != site_key:
            continue
        hid = int(host.zabbix_hostid)
        site_hostids.add(hid)
        equipment = parsed["equipment"].upper()
        if equipment.startswith(("UPS", "APC", "EATON")):
            ups_hostids.add(hid)
    if not site_hostids:
        return None
    events = db.scalars(select(ProblemEvent).where(
        ProblemEvent.started_at >= since,
        ProblemEvent.started_at <= outage_started_at,
    ).order_by(ProblemEvent.started_at.desc())).all()
    evidence = []
    battery_low = False
    for event in events:
        event_hostids = set()
        for h in event.hosts or []:
            try:
                event_hostids.add(int(h.get("hostid")))
            except (TypeError, ValueError):
                pass
        if not (event_hostids & site_hostids):
            continue
        is_power = _matches(event.name, POWER_PATTERNS)
        is_low = _matches(event.name, BATTERY_LOW_PATTERNS)
        if not (is_power or is_low):
            continue
        if ups_hostids and not (event_hostids & ups_hostids):
            continue
        battery_low = battery_low or is_low
        evidence.append({
            "eventid": str(event.zabbix_eventid),
            "name": event.name,
            "started_at": event.started_at,
            "minutes_before_outage": max(0, round((outage_started_at - event.started_at).total_seconds() / 60)),
        })
    if not evidence:
        return None
    latest = evidence[0]
    return {
        "type": "power_outage",
        "probable_cause": "Вероятное отсутствие электропитания",
        "confidence": "very_high" if battery_low and len(evidence) >= 2 else "high",
        "window_minutes": window_minutes,
        "evidence": evidence[:5],
        "summary": f"Событие UPS за {latest['minutes_before_outage']} мин. до недоступности оборудования",
    }
