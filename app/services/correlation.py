from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CorrelationRule, Host, Problem, ProblemEvent

SITE_PREFIX="SITE-"


def _host_site_keys(host):
    keys=[]
    for group in host.groups or []:
        name=str(group.get("name") or "").strip()
        if name.upper().startswith(SITE_PREFIX):
            key=name[len(SITE_PREFIX):].strip().upper()
            if key: keys.append(key)
    return keys


def _event_site_keys(event,host_sites):
    keys=set()
    for h in event.hosts or []:
        try: hid=int(h.get("hostid"))
        except (TypeError,ValueError): continue
        keys.update(host_sites.get(hid,()))
    return keys


def _step_matches(event,step):
    pattern=(step.get("pattern") or step.get("name") or "").strip().lower()
    actual=(event.name or "").strip().lower()
    return bool(pattern and pattern in actual)


def _evaluate_rules(rules,site_events):
    matches=[]
    for rule in rules:
        steps=rule.steps or []
        if len(steps)<2: continue
        for first_index,event in enumerate(site_events):
            if not _step_matches(event,steps[0]): continue
            evidence=[{"eventid":str(event.zabbix_eventid),"triggerid":str(event.zabbix_triggerid) if event.zabbix_triggerid else None,"name":event.name,"started_at":event.started_at}]
            pos=1; deadline=event.started_at+timedelta(minutes=rule.window_minutes)
            for candidate in site_events[first_index+1:]:
                if candidate.started_at>deadline: break
                if pos<len(steps) and _step_matches(candidate,steps[pos]):
                    evidence.append({"eventid":str(candidate.zabbix_eventid),"triggerid":str(candidate.zabbix_triggerid) if candidate.zabbix_triggerid else None,"name":candidate.name,"started_at":candidate.started_at})
                    pos+=1
                    if pos==len(steps): break
            if pos==len(steps):
                span=round((evidence[-1]["started_at"]-evidence[0]["started_at"]).total_seconds()/60,1)
                matches.append({"type":"user_rule","rule_id":rule.id,"probable_cause":rule.name,"description":rule.description,"confidence":"configured","window_minutes":rule.window_minutes,"matched_steps":len(steps),"span_minutes":span,"evidence":evidence,"summary":f"Совпала цепочка {len(steps)} событий за {span} мин."})
                break
    if not matches: return None
    return sorted(matches,key=lambda x:(-x["matched_steps"],x["span_minutes"],x["rule_id"]))[0]


def user_correlations(db:Session,site_keys:set[str]|None=None,reference_at:datetime|None=None):
    rules=db.scalars(select(CorrelationRule).where(CorrelationRule.enabled.is_(True)).order_by(CorrelationRule.id)).all()
    if not rules: return {}
    reference_at=reference_at or datetime.now(timezone.utc)
    if reference_at.tzinfo is None: reference_at=reference_at.replace(tzinfo=timezone.utc)
    hosts=db.scalars(select(Host).where(Host.status==0)).all(); host_sites={}
    for host in hosts:
        keys=_host_site_keys(host)
        if site_keys is not None: keys=[k for k in keys if k in site_keys]
        if keys: host_sites[int(host.zabbix_hostid)]=keys
    history_from=reference_at-timedelta(days=7)
    history=db.scalars(select(ProblemEvent).where(ProblemEvent.started_at>=history_from,ProblemEvent.started_at<=reference_at).order_by(ProblemEvent.started_at.asc())).all()
    active=db.scalars(select(Problem).where(Problem.active.is_(True),Problem.started_at<=reference_at).order_by(Problem.started_at.asc())).all()
    merged={}
    for event in [*history,*active]: merged[str(event.zabbix_eventid)]=event
    events_by_site=defaultdict(list)
    for event in sorted(merged.values(),key=lambda e:e.started_at):
        for key in _event_site_keys(event,host_sites): events_by_site[key].append(event)
    wanted=site_keys if site_keys is not None else set(events_by_site)
    return {key:match for key in wanted if (match:=_evaluate_rules(rules,events_by_site.get(key,[]))) is not None}


def user_correlation(db:Session,site_key:str,reference_at:datetime|None=None):
    return user_correlations(db,{site_key},reference_at).get(site_key)
