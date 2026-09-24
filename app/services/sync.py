from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Host, HostGroup, Problem, ProblemEvent, SyncRun
from app.services.scoring import calculate_impact
from app.services.zabbix import ZabbixClient


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def from_epoch(value: str | int) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def upsert(db: Session, model, lookup: dict, values: dict):
    obj = db.scalar(select(model).filter_by(**lookup))
    if obj is None:
        obj = model(**lookup, **values)
        db.add(obj)
    else:
        for key, value in values.items():
            setattr(obj, key, value)
    return obj


async def sync_all(db: Session) -> dict:
    run = SyncRun(started_at=utcnow(), status="running", details={})
    db.add(run)
    db.commit()
    db.refresh(run)

    client = ZabbixClient()
    counts = {}
    try:
        groups = await client.host_groups()
        for item in groups:
            upsert(db, HostGroup, {"zabbix_groupid": int(item["groupid"])}, {
                "name": item["name"], "updated_at": utcnow(),
            })
        counts["host_groups"] = len(groups)

        hosts = await client.hosts()
        for item in hosts:
            upsert(db, Host, {"zabbix_hostid": int(item["hostid"])}, {
                "technical_name": item["host"],
                "visible_name": item.get("name") or item["host"],
                "status": int(item.get("status", 0)),
                "groups": item.get("hostgroups", []),
                "tags": item.get("tags", []),
                "updated_at": utcnow(),
            })
        counts["hosts"] = len(hosts)
        counts["triggers"] = "deferred"

        db.execute(update(Problem).where(Problem.active.is_(True)).values(active=False, recovered_at=utcnow()))

        problems = await client.problems(limit=1000)
        for item in problems:
            impact_score, breakdown = calculate_impact(item)
            values = {
                "zabbix_triggerid": int(item["objectid"]) if item.get("objectid") else None,
                "name": item["name"],
                "severity": int(item.get("severity", 0)),
                "acknowledged": str(item.get("acknowledged", "0")) == "1",
                "started_at": from_epoch(item["clock"]),
                "recovered_at": None,
                "active": True,
                "hosts": item.get("hosts", []),
                "tags": item.get("tags", []),
                "impact_score": impact_score,
                "score_breakdown": breakdown,
                "updated_at": utcnow(),
            }
            upsert(db, Problem, {"zabbix_eventid": int(item["eventid"])}, values)
        counts["active_problems"] = len(problems)

        history_from = utcnow() - timedelta(days=7)
        history = await client.problem_history(int(history_from.timestamp()), limit=10000)
        for item in history:
            upsert(db, ProblemEvent, {"zabbix_eventid": int(item["eventid"])}, {
                "zabbix_triggerid": int(item["objectid"]) if item.get("objectid") else None,
                "name": item.get("name") or "",
                "severity": int(item.get("severity", 0)),
                "started_at": from_epoch(item["clock"]),
                "recovered": str(item.get("r_eventid", "0")) not in ("0", "", "None"),
                "hosts": item.get("hosts", []),
                "tags": item.get("tags", []),
                "updated_at": utcnow(),
            })
        counts["history_events_7d"] = len(history)

        run.status = "success"
        run.finished_at = utcnow()
        run.details = counts
        db.commit()
        return {"status": "ok", **counts}
    except Exception as exc:
        db.rollback()
        run = db.get(SyncRun, run.id)
        if run:
            run.status = "failed"
            run.finished_at = utcnow()
            run.error = str(exc)
            db.commit()
        raise
