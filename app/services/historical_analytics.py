"""Historical availability and capacity forecasts sourced from Zabbix API."""
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Host
from app.services.sites import site_groups, AVAILABILITY_PATTERNS
from app.services.zabbix import ZabbixClient

def _site_hosts(db:Session):
    mapping=defaultdict(set)
    for host in db.scalars(select(Host).where(Host.status==0)).all():
        for group in site_groups(host):mapping[int(host.zabbix_hostid)].add(group["site_key"])
    return mapping

async def reliability_report(db:Session,days:int=30)->dict:
    now=int(datetime.now(timezone.utc).timestamp());start=now-days*86400
    host_sites=_site_hosts(db);site_ids=defaultdict(set)
    for hid,sites in host_sites.items():
        for site in sites:site_ids[site].add(hid)
    client=ZabbixClient();events=await client.call("event.get",{
        "output":["eventid","objectid","name","clock","r_eventid"],
        "source":0,"object":0,"value":1,"time_from":start,
        "sortfield":"eventid","sortorder":"DESC","limit":10000})
    ids=list({str(e["objectid"]) for e in events if e.get("objectid")})
    context=await client.trigger_context(ids) if ids else {}
    recovery_ids=list({str(e.get("r_eventid")) for e in events if str(e.get("r_eventid") or "0") not in ("0","")})
    recovered_at={}
    for offset in range(0,len(recovery_ids),100):
        batch=await client.call("event.get",{"output":["eventid","clock"],"eventids":recovery_ids[offset:offset+100]})
        for event in batch:recovered_at[str(event["eventid"])]=int(event["clock"])
    outages=defaultdict(list);seen=set()
    for e in events:
        name=str(e.get("name") or "").lower()
        if not any(p in name for p in AVAILABILITY_PATTERNS):continue
        began=int(e["clock"]);recovered=recovered_at.get(str(e.get("r_eventid") or ""),0)
        if recovered<=began:recovered=now
        duration=max(0,min(now,recovered)-max(start,began))
        for h in context.get(str(e.get("objectid")),[]):
            try:hid=int(h["hostid"])
            except (KeyError,ValueError,TypeError):continue
            for site in host_sites.get(hid,()):
                key=(site,str(e["eventid"]))
                if key in seen:continue
                seen.add(key);outages[site].append((began,duration))
    items=[]
    for site,hids in site_ids.items():
        incidents=outages.get(site,[]);seconds=sum(x[1] for x in incidents)
        # Sum of incident durations is an event-time metric, not site downtime:
        # concurrent host outages must not be counted as sequential site outages.
        mean=round(seconds/len(incidents)/60,1) if incidents else None
        items.append({"site_key":site,"hosts":len(hids),"incidents":len(incidents),
            "event_minutes":round(seconds/60,1),"mttr_minutes":mean,
            "last_incident":datetime.fromtimestamp(max(x[0] for x in incidents),timezone.utc).isoformat() if incidents else None})
    items.sort(key=lambda x:(-x["incidents"],-x["event_minutes"],x["site_key"]))
    return {"days":days,"count":len(items),"events_scanned":len(events),"truncated":len(events)>=10000,
        "note":"Количество событий недоступности и сумма их длительностей; это не SLA и не время простоя объекта. История ограничена 10000 событий и временем хранения Zabbix.",
        "items":items}

def _series_forecast(points:list[tuple[int,float]],total:float,now:int)->dict:
    if len(points)<3:return {"growth_gb_day":None,"days_to_85":None,"days_to_95":None,"confidence":"insufficient"}
    points=sorted(points);daily=[]
    for (t0,v0),(t1,v1) in zip(points,points[1:]):
        if t1>t0 and v1>=v0:daily.append((v1-v0)*86400/(t1-t0))
    if not daily:return {"growth_gb_day":0,"days_to_85":None,"days_to_95":None,"confidence":"insufficient"}
    growth=median(daily)
    current=points[-1][1]
    def eta(pct):
        if current>=total*pct:return 0
        if growth<=0:return None
        return round((total*pct-current)/growth/86400,1)
    return {"growth_gb_day":round(growth/1024**3,2),"days_to_85":eta(.85),"days_to_95":eta(.95),"confidence":"estimate"}

# Process-local TTL cache; avoids repeating a costly Zabbix scan on each page load.
import asyncio
import time

_CAPACITY_CACHE = {}
_CAPACITY_LOCK = asyncio.Lock()
_CAPACITY_TTL = 900


async def capacity_report(db: Session, days: int = 30) -> dict:
    now_mono = time.monotonic()
    cached = _CAPACITY_CACHE.get(days)
    if cached and now_mono - cached[0] < _CAPACITY_TTL:
        return {**cached[1], "cached": True}

    async with _CAPACITY_LOCK:
        cached = _CAPACITY_CACHE.get(days)
        if cached and time.monotonic() - cached[0] < _CAPACITY_TTL:
            return {**cached[1], "cached": True}

        client = ZabbixClient()
        host_sites = _site_hosts(db)
        ids = [str(hostid) for hostid in host_sites]
        now = int(datetime.now(timezone.utc).timestamp())
        start = now - days * 86400
        diagnostics = {
            "hosts": len(ids), "candidate_items": 0, "used_items": 0,
            "item_requests": 0, "item_errors": 0, "hosts_skipped": 0,
            "missing_total": 0, "empty_values": 0,
            "missing_trends": 0, "trend_requests": 0, "trend_errors": 0,
        }
        disks = []
        # Small host batches avoid expensive item.get queries on large Zabbix installations.
        for offset in range(0, len(ids), 10):
            host_batch = ids[offset:offset + 10]
            diagnostics["item_requests"] += 1
            try:
                raw = await client.call("item.get", {
                "output": ["itemid", "hostid", "name", "key_", "lastvalue", "value_type", "units"],
                "hostids": host_batch,
                "filter": {"status": 0},
                "search": {"key_": "vfs.fs."},
            })
            except Exception as exc:
                diagnostics["item_errors"] += 1
                diagnostics["hosts_skipped"] += len(host_batch)
                import logging
                logging.getLogger(__name__).warning("Capacity item.get failed for host batch: %s", exc)
                continue
            diagnostics["candidate_items"] += len(raw)
            by_key = {(str(item["hostid"]), str(item["key_"])): item for item in raw}
            for item in raw:
                key = str(item.get("key_") or "")
                if not (key.startswith("vfs.fs.size[") or key.startswith("vfs.fs.dependent.size[")):
                    continue
                if not key.endswith(",used]"):
                    continue
                diagnostics["used_items"] += 1
                total_item = by_key.get((str(item["hostid"]), key[:-6] + ",total]"))
                if total_item is None:
                    diagnostics["missing_total"] += 1
                    continue
                try:
                    used = float(item["lastvalue"])
                    total = float(total_item["lastvalue"])
                except (ValueError, TypeError, KeyError):
                    diagnostics["empty_values"] += 1
                    continue
                if used <= 0 or total <= 0:
                    diagnostics["empty_values"] += 1
                    continue
                disks.append((item, key, used, total))

        # Query only the first and last 24h windows. Each trend.get is bounded
        # to 50 itemids x 24 hourly rows, rather than days*24 per disk.
        series = defaultdict(lambda: {"first": [], "last": []})
        numeric_ids = [
            str(item["itemid"]) for item, _, _, _ in disks
            if str(item.get("value_type")) in ("0", "3")
        ]
        for offset in range(0, len(numeric_ids), 50):
            batch = numeric_ids[offset:offset + 50]
            for label, t_from, t_till in (
                ("first", start, start + 86400),
                ("last", now - 86400, now),
            ):
                diagnostics["trend_requests"] += 1
                try:
                    rows = await client.call("trend.get", {
                        "output": ["itemid", "clock", "value_avg"],
                        "itemids": batch, "time_from": t_from, "time_till": t_till,
                        "limit": 5000,
                    })
                except Exception:
                    diagnostics["trend_errors"] += 1
                    continue
                for row in rows:
                    try:
                        series[str(row["itemid"])][label].append(
                            (int(row["clock"]), float(row["value_avg"]))
                        )
                    except (KeyError, ValueError, TypeError):
                        continue

        items = []
        for item, key, used, total in disks:
            history = series[str(item["itemid"])]
            first = history["first"]
            last = history["last"]
            if first and last:
                t0 = sum(p[0] for p in first) / len(first)
                t1 = sum(p[0] for p in last) / len(last)
                v0 = sum(p[1] for p in first) / len(first)
                v1 = sum(p[1] for p in last) / len(last)
                growth_bytes_day = max(0.0, (v1 - v0) * 86400 / (t1 - t0)) if t1 > t0 else 0.0
                def eta(threshold):
                    if used >= total * threshold:
                        return 0
                    if growth_bytes_day <= 0:
                        return None
                    return round((total * threshold - used) / growth_bytes_day, 1)
                forecast = {
                    "growth_gb_day": round(growth_bytes_day / 1024**3, 2),
                    "days_to_85": eta(0.85),
                    "days_to_95": eta(0.95),
                    "confidence": "estimate",
                }
            else:
                diagnostics["missing_trends"] += 1
                forecast = {
                    "growth_gb_day": None, "days_to_85": None,
                    "days_to_95": None, "confidence": "insufficient",
                }
            for site in host_sites.get(int(item["hostid"]), ()):
                items.append({
                    "site_key": site, "hostid": str(item["hostid"]),
                    "itemid": str(item["itemid"]),
                    "filesystem": key[key.index("[") + 1:-6],
                    "used_percent": round(used / total * 100, 1),
                    "used_tb": round(used / 1024**4, 2),
                    "total_tb": round(total / 1024**4, 2),
                    "samples": len(first) + len(last), **forecast,
                })

        items.sort(key=lambda x: (
            x["days_to_95"] is None,
            x["days_to_95"] if x["days_to_95"] is not None else 999999,
            -x["used_percent"],
        ))
        result = {
            "days": days, "count": len(items), "diagnostics": diagnostics,
            "cached": False,
            "note": "Оценка по средним hourly trends в начале и конце периода. "
                    "Если данных недостаточно, прогноз не рассчитывается. "
                    "Результат кэшируется на 15 минут в памяти процесса.",
            "items": items,
        }
        _CAPACITY_CACHE[days] = (time.monotonic(), result)
        return result
