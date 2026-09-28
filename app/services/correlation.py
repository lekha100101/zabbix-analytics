from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CorrelationRule, Host, ProblemEvent

def _parse_site(name):
    value=(name or "").strip(); parts=value.split("-")
    if len(parts)<3: return None
    return {"equipment":"-".join(parts[:-2]).upper(),"site_key":f"{parts[-2].upper()}-{parts[-1].upper()}"}

def _event_site_keys(event, host_sites):
    keys=set()
    for h in event.hosts or []:
        try: hid=int(h.get("hostid"))
        except (TypeError,ValueError): continue
        if hid in host_sites: keys.add(host_sites[hid])
    return keys

def _step_matches(event, step):
    triggerid=step.get("triggerid")
    if triggerid and event.zabbix_triggerid and str(event.zabbix_triggerid)==str(triggerid): return True
    expected=(step.get("name") or "").strip().lower()
    return bool(expected and expected==(event.name or "").strip().lower())

def user_correlation(db: Session, site_key: str, reference_at: datetime | None = None):
    rules=db.scalars(select(CorrelationRule).where(CorrelationRule.enabled.is_(True)).order_by(CorrelationRule.id)).all()
    if not rules: return None
    reference_at=reference_at or datetime.now(timezone.utc)
    if reference_at.tzinfo is None: reference_at=reference_at.replace(tzinfo=timezone.utc)
    max_window=max((r.window_minutes for r in rules),default=120)
    hosts=db.scalars(select(Host).where(Host.status==0)).all()
    host_sites={}
    for host in hosts:
        parsed=_parse_site(host.technical_name or host.visible_name)
        if parsed: host_sites[int(host.zabbix_hostid)]=parsed["site_key"]
    events=db.scalars(select(ProblemEvent).where(
        ProblemEvent.started_at>=reference_at-timedelta(minutes=max_window),
        ProblemEvent.started_at<=reference_at,
    ).order_by(ProblemEvent.started_at.asc())).all()
    site_events=[e for e in events if site_key in _event_site_keys(e,host_sites)]
    matches=[]
    for rule in rules:
        steps=rule.steps or []
        if len(steps)<2: continue
        start=reference_at-timedelta(minutes=rule.window_minutes)
        candidates=[e for e in site_events if e.started_at>=start]
        evidence=[]; pos=0
        for event in candidates:
            if _step_matches(event,steps[pos]):
                evidence.append({"eventid":str(event.zabbix_eventid),"triggerid":str(event.zabbix_triggerid) if event.zabbix_triggerid else None,"name":event.name,"started_at":event.started_at})
                pos+=1
                if pos==len(steps): break
        if pos==len(steps):
            span=round((evidence[-1]["started_at"]-evidence[0]["started_at"]).total_seconds()/60,1)
            matches.append({"type":"user_rule","rule_id":rule.id,"probable_cause":rule.name,"description":rule.description,"confidence":"configured","window_minutes":rule.window_minutes,"matched_steps":len(steps),"span_minutes":span,"evidence":evidence,"summary":f"Совпала цепочка {len(steps)} событий за {span} мин."})
    if not matches: return None
    return sorted(matches,key=lambda x:(-x["matched_steps"],x["span_minutes"],x["rule_id"]))[0]
