from fastapi import FastAPI, HTTPException, Query

from app.config import get_settings
from app.services.scoring import calculate_impact_score
from app.services.zabbix import ZabbixAPIError, ZabbixClient

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "version": "0.1.0"}


@app.get("/api/v1/zabbix/status")
async def zabbix_status() -> dict:
    try:
        version = await ZabbixClient().version()
        return {"status": "ok", "zabbix_version": version}
    except (ZabbixAPIError, Exception) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/problems")
async def problems(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    try:
        items = await ZabbixClient().problems(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = []
    for problem in items:
        item = dict(problem)
        item["impact_score"] = calculate_impact_score(problem)
        result.append(item)

    result.sort(key=lambda item: item["impact_score"], reverse=True)
    return {"count": len(result), "items": result}
