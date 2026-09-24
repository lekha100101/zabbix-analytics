from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProblemEvent


def instability_analytics(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)
    since_24h = now - timedelta(hours=24)

    events = db.scalars(
        select(ProblemEvent)
        .where(ProblemEvent.started_at >= since_7d)
        .order_by(ProblemEvent.started_at.desc())
    ).all()

    buckets: dict[tuple[int, str], dict] = {}
    for event in events:
        for host in event.hosts or []:
            try:
                hostid = int(host.get("hostid"))
            except (TypeError, ValueError):
                continue
            host_name = host.get("name") or host.get("host") or str(hostid)
            key = (hostid, event.name)
            item = buckets.setdefault(key, {
                "hostid": str(hostid),
                "host": host_name,
                "problem": event.name,
                "severity": event.severity,
                "events_24h": 0,
                "events_7d": 0,
                "recovered_7d": 0,
                "last_event_at": event.started_at,
            })
            item["events_7d"] += 1
            if event.started_at >= since_24h:
                item["events_24h"] += 1
            if event.recovered:
                item["recovered_7d"] += 1
            if event.started_at > item["last_event_at"]:
                item["last_event_at"] = event.started_at
            item["severity"] = max(item["severity"], event.severity)

    result = []
    for item in buckets.values():
        count = item["events_7d"]
        if count < 2:
            continue
        # Repeated problem openings are used as the first practical flapping
        # signal. Recovery-aware duration can be added once recovery timestamps
        # are persisted as well.
        instability_score = min(
            100,
            count * 6
            + item["events_24h"] * 5
            + item["severity"] * 5,
        )
        level = "critical" if instability_score >= 80 else "high" if instability_score >= 60 else "warning"
        result.append({
            **item,
            "instability_score": instability_score,
            "level": level,
        })

    return sorted(
        result,
        key=lambda x: (-x["instability_score"], -x["events_24h"], -x["events_7d"], x["host"]),
    )
