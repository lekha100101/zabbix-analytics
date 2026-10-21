from datetime import datetime, timezone
from fnmatch import fnmatchcase

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Host, Problem, ScoringRule

SEVERITY_POINTS={0:2,1:5,2:12,3:22,4:35,5:50}
DEFAULT_TAG_RULES={("scope","availability"):18,("scope","capacity"):7,("scope","performance"):6,("scope","security"):15,("class","hardware"):10,("class","network"):8,("component","system"):8,("component","storage"):6,("component","database"):12}

def ensure_default_rules(db:Session)->None:
    if db.scalar(select(ScoringRule.id).limit(1)) is not None:return
    for (key,value),points in DEFAULT_TAG_RULES.items():db.add(ScoringRule(name=f"tag:{key}={value}",rule_type="tag",key=key,value=value,points=points,enabled=True))
    db.commit()

def load_scoring_rules(db:Session)->list[ScoringRule]:
    ensure_default_rules(db)
    return db.scalars(select(ScoringRule).where(ScoringRule.enabled.is_(True)).order_by(ScoringRule.priority,ScoringRule.id)).all()

def load_tag_rules(db:Session)->dict:
    return {(str(r.key).lower(),str(r.value).lower()):r.points for r in load_scoring_rules(db) if r.rule_type=="tag" and r.key and r.value}

def host_context_for_problem(db:Session,hosts:list[dict]|None)->tuple[list[dict],list[str]]:
    ids=[]
    for h in hosts or []:
        try: ids.append(int(h.get("hostid")))
        except (TypeError,ValueError): pass
    if not ids:return [],[]
    rows=db.scalars(select(Host).where(Host.zabbix_hostid.in_(set(ids)))).all();tags=[];names=[];seen=set()
    for h in rows:
        for name in (h.technical_name,h.visible_name):
            if name and name not in names:names.append(name)
        for tag in h.tags or []:
            pair=(str(tag.get("tag","")).lower(),str(tag.get("value","")).lower())
            if pair[0] and pair not in seen:
                seen.add(pair);tags.append({"tag":tag.get("tag",""),"value":tag.get("value","")})
    return tags,names

def host_tags_for_problem(db:Session,hosts:list[dict]|None)->list[dict]:
    return host_context_for_problem(db,hosts)[0]

def calculate_impact(problem:dict,tag_rules:dict|None=None,host_mask_rules:list|None=None)->tuple[int,dict]:
    rules=tag_rules if tag_rules is not None else DEFAULT_TAG_RULES;severity=int(problem.get("severity",0));severity_points=SEVERITY_POINTS.get(severity,2)
    breakdown={"severity":severity_points,"tags":[],"host_masks":[],"duration":0,"unacknowledged":0};score=severity_points;seen=set()
    for source,tags in (("problem",problem.get("tags",[]) or []),("host",problem.get("host_tags",[]) or [])):
        for tag in tags:
            pair=(str(tag.get("tag","")).lower(),str(tag.get("value","")).lower())
            if pair in seen:continue
            seen.add(pair);points=rules.get(pair)
            if points:
                score+=points;breakdown["tags"].append({"tag":pair[0],"value":pair[1],"points":points,"source":source})
    names=[str(x) for x in problem.get("host_names",[]) if x]
    for rule in host_mask_rules or []:
        mask=str(rule.value or "").strip()
        if mask and any(fnmatchcase(name.lower(),mask.lower()) for name in names):
            score+=rule.points;breakdown["host_masks"].append({"name":rule.name,"mask":mask,"points":rule.points,"hosts":[n for n in names if fnmatchcase(n.lower(),mask.lower())]})
    try:
        clock=problem.get("clock");started=datetime.fromtimestamp(int(clock),tz=timezone.utc) if clock is not None else problem.get("started_at")
        if started and started.tzinfo is None:started=started.replace(tzinfo=timezone.utc)
        age_hours=max(0.0,(datetime.now(timezone.utc)-started).total_seconds()/3600) if started else 0
    except (TypeError,ValueError,OSError):age_hours=0
    duration_points=5 if age_hours>=168 else 4 if age_hours>=24 else 2 if age_hours>=4 else 1 if age_hours>=1 else 0
    score+=duration_points;breakdown["duration"]=duration_points;breakdown["age_hours"]=round(age_hours,1)
    acknowledged=problem.get("acknowledged",False);is_ack=acknowledged is True or str(acknowledged)=="1"
    if not is_ack:score+=3;breakdown["unacknowledged"]=3
    final_score=min(max(score,0),100);breakdown["total"]=final_score;return final_score,breakdown

def recalculate_all(db:Session)->int:
    all_rules=load_scoring_rules(db);tag_rules={(str(r.key).lower(),str(r.value).lower()):r.points for r in all_rules if r.rule_type=="tag" and r.key and r.value};mask_rules=[r for r in all_rules if r.rule_type=="host_mask"]
    problems=db.scalars(select(Problem).where(Problem.active.is_(True))).all()
    for item in problems:
        tags,names=host_context_for_problem(db,item.hosts)
        score,breakdown=calculate_impact({"severity":item.severity,"tags":item.tags,"host_tags":tags,"host_names":names,"started_at":item.started_at,"acknowledged":item.acknowledged},tag_rules,mask_rules)
        item.impact_score=score;item.score_breakdown=breakdown
    db.commit();return len(problems)
