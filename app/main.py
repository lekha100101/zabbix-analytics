from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import Host, HostGroup, Problem, Trigger
from app.services.scoring import calculate_impact_score
from app.services.sync import sync_all
from app.services.zabbix import ZabbixClient

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        database = f"error: {exc}"
    return {"status": "ok" if database == "ok" else "degraded", "service": settings.app_name, "version": "0.2.0", "database": database}


@app.get("/api/v1/zabbix/status")
async def zabbix_status() -> dict:
    try:
        version = await ZabbixClient().version()
        return {"status": "ok", "zabbix_version": version}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/sync")
async def run_sync(db: Session = Depends(get_db)) -> dict:
    try:
        return await sync_all(db)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    return {
        "host_groups": db.scalar(select(func.count()).select_from(HostGroup)),
        "hosts": db.scalar(select(func.count()).select_from(Host)),
        "triggers": db.scalar(select(func.count()).select_from(Trigger)),
        "active_problems": db.scalar(select(func.count()).select_from(Problem).where(Problem.active.is_(True))),
    }


@app.get("/api/v1/problems")
def problems(limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(
        select(Problem).where(Problem.active.is_(True)).order_by(Problem.impact_score.desc(), Problem.started_at.asc()).limit(limit)
    ).all()
    result = [
        {
            "eventid": str(item.zabbix_eventid),
            "objectid": str(item.zabbix_triggerid) if item.zabbix_triggerid else None,
            "name": item.name,
            "severity": item.severity,
            "acknowledged": item.acknowledged,
            "started_at": item.started_at,
            "hosts": item.hosts,
            "tags": item.tags,
            "impact_score": item.impact_score,
        }
        for item in items
    ]
    return {"count": len(result), "items": result}
