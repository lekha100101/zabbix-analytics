from pathlib import Path
from datetime import datetime, timezone

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import Host, HostGroup, Problem, ScoringRule, Trigger
from app.services.scoring import ensure_default_rules, recalculate_all
from app.services.instability import instability_analytics
from app.services.sites import site_analytics
from app.services.sync import sync_all
from app.services.zabbix import ZabbixClient

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.9.0")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1")); database = "ok"
    except Exception as exc:
        database = f"error: {exc}"
    return {"status": "ok" if database == "ok" else "degraded", "service": settings.app_name, "version": "0.9.0", "database": database}


@app.get("/api/v1/zabbix/status")
async def zabbix_status() -> dict:
    try:
        return {"status": "ok", "zabbix_version": await ZabbixClient().version()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/sync")
async def run_sync(db: Session = Depends(get_db)) -> dict:
    try:
        result = await sync_all(db)
        recalculate_all(db)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/scoring/recalculate")
def recalculate(db: Session = Depends(get_db)) -> dict:
    return {"status": "ok", "recalculated": recalculate_all(db)}


@app.get("/api/v1/scoring/rules")
def scoring_rules(db: Session = Depends(get_db)) -> list[dict]:
    ensure_default_rules(db)
    rules = db.scalars(select(ScoringRule).order_by(ScoringRule.priority, ScoringRule.id)).all()
    return [{"id": r.id, "name": r.name, "rule_type": r.rule_type, "key": r.key, "value": r.value, "points": r.points, "enabled": r.enabled, "priority": r.priority} for r in rules]


@app.patch("/api/v1/scoring/rules/{rule_id}")
def update_rule(rule_id: int, payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    rule = db.get(ScoringRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Scoring rule not found")
    for field in ("points", "enabled", "priority"):
        if field in payload:
            setattr(rule, field, payload[field])
    db.commit()
    return {"status": "ok", "id": rule.id}


@app.get("/api/v1/hosts")
def hosts(q: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Host)
    if q:
        stmt = stmt.where(Host.visible_name.ilike(f"%{q}%"))
    items = db.scalars(stmt.order_by(Host.visible_name).limit(limit)).all()
    return [{"hostid": str(h.zabbix_hostid), "name": h.visible_name, "host": h.technical_name, "criticality": h.criticality, "groups": h.groups} for h in items]


@app.patch("/api/v1/hosts/{hostid}/criticality")
def host_criticality(hostid: int, payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    host = db.scalar(select(Host).where(Host.zabbix_hostid == hostid))
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    host.criticality = max(-50, min(50, int(payload.get("points", 0))))
    db.commit()
    return {"status": "ok", "hostid": str(hostid), "criticality": host.criticality}


@app.get("/api/v1/host-groups")
def host_groups(db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(HostGroup).order_by(HostGroup.name)).all()
    return [{"groupid": str(g.zabbix_groupid), "name": g.name, "criticality": g.criticality} for g in items]


@app.patch("/api/v1/host-groups/{groupid}/criticality")
def group_criticality(groupid: int, payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    group = db.scalar(select(HostGroup).where(HostGroup.zabbix_groupid == groupid))
    if not group:
        raise HTTPException(status_code=404, detail="Host group not found")
    group.criticality = max(-50, min(50, int(payload.get("points", 0))))
    db.commit()
    return {"status": "ok", "groupid": str(groupid), "criticality": group.criticality}


@app.get("/api/v1/sites")
def sites(db: Session = Depends(get_db)) -> dict:
    items = site_analytics(db)
    return {"count": len(items), "items": items}


@app.get("/api/v1/attention")
def attention(db: Session = Depends(get_db)) -> dict:
    items = site_analytics(db)
    important = [
        item for item in items
        if item["risk_score"] >= 70
        or item["unavailable_ratio"] >= 50
        or item["burst_15m"] >= 5
        or item["probable_cause"]
    ]
    return {"count": len(important), "items": important[:20]}


@app.get("/api/v1/instability")
def instability(db: Session = Depends(get_db)) -> dict:
    items = instability_analytics(db)
    return {"count": len(items), "items": items[:100]}


@app.get("/api/v1/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    return {"host_groups": db.scalar(select(func.count()).select_from(HostGroup)), "hosts": db.scalar(select(func.count()).select_from(Host)), "triggers": db.scalar(select(func.count()).select_from(Trigger)), "active_problems": db.scalar(select(func.count()).select_from(Problem).where(Problem.active.is_(True)))}


@app.patch("/api/v1/problems/{eventid}/defer")
def defer_problem(eventid: int, payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    problem = db.scalar(select(Problem).where(Problem.zabbix_eventid == eventid))
    if not problem or not problem.active:
        raise HTTPException(status_code=404, detail="Active problem not found")
    raw_until = payload.get("until")
    if not raw_until:
        raise HTTPException(status_code=400, detail="until is required")
    try:
        until = datetime.fromisoformat(str(raw_until).replace("Z", "+00:00"))
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid until datetime") from exc
    if until <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="until must be in the future")
    problem.deferred_until = until
    problem.deferred_reason = str(payload.get("reason") or "").strip() or None
    problem.deferred_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok", "eventid": str(eventid), "deferred_until": problem.deferred_until}


@app.delete("/api/v1/problems/{eventid}/defer")
def undefer_problem(eventid: int, db: Session = Depends(get_db)) -> dict:
    problem = db.scalar(select(Problem).where(Problem.zabbix_eventid == eventid))
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    problem.deferred_until = None
    problem.deferred_reason = None
    problem.deferred_at = None
    db.commit()
    return {"status": "ok", "eventid": str(eventid)}


@app.get("/api/v1/deferred-problems")
def deferred_problems(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    items = db.scalars(
        select(Problem)
        .where(Problem.active.is_(True), Problem.deferred_until > now)
        .order_by(Problem.deferred_until.asc(), Problem.impact_score.desc())
    ).all()
    result = [{"eventid": str(i.zabbix_eventid), "name": i.name, "severity": i.severity,
               "started_at": i.started_at, "hosts": i.hosts, "impact_score": i.impact_score,
               "deferred_until": i.deferred_until, "deferred_reason": i.deferred_reason,
               "deferred_at": i.deferred_at} for i in items]
    return {"count": len(result), "items": result}


@app.get("/api/v1/problems")
def problems(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(select(Problem).where(Problem.active.is_(True), ((Problem.deferred_until.is_(None)) | (Problem.deferred_until <= datetime.now(timezone.utc)))).order_by(Problem.impact_score.desc(), Problem.started_at.asc()).limit(limit)).all()
    result = [{"eventid": str(i.zabbix_eventid), "objectid": str(i.zabbix_triggerid) if i.zabbix_triggerid else None, "name": i.name, "severity": i.severity, "acknowledged": i.acknowledged, "started_at": i.started_at, "hosts": i.hosts, "tags": i.tags, "impact_score": i.impact_score, "score_breakdown": i.score_breakdown} for i in items]
    return {"count": len(result), "items": result}
