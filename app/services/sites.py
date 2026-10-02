from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Host, Problem
from app.services.correlation import user_correlations

SITE_PREFIX = "SITE-"

ROLE_PREFIXES = {
    "gateway": ("GW", "RTR", "ROUTER", "FW", "FGT"),
    "switch": ("SW", "SWT", "ARUBA", "FORTISWITCH"),
    "server_mgmt": ("ILO", "IDRAC", "IPMI"),
    "pacs": ("PACS",),
    "database": ("DB", "PG", "POSTGRES", "MSSQL", "SQL"),
    "storage": ("STORAGE", "NAS", "SAN", "NETAPP"),
    "server": ("SRV", "SERVER", "VM"),
    "ups": ("UPS",),
}


def equipment_from_host(host: Host) -> str:
    value=(host.technical_name or host.visible_name or "").strip().upper()
    return value.split("-",1)[0] if value else "OTHER"


def equipment_role(equipment: str) -> str:
    value=(equipment or "").upper()
    for role,prefixes in ROLE_PREFIXES.items():
        if any(value.startswith(prefix) for prefix in prefixes): return role
    return "other"


def site_groups(host: Host) -> list[dict]:
    result=[]
    for group in host.groups or []:
        name=str(group.get("name") or "").strip()
        if not name.upper().startswith(SITE_PREFIX): continue
        key=name[len(SITE_PREFIX):].strip()
        if not key: continue
        parts=key.split("-",1)
        result.append({"groupid":str(group.get("groupid") or ""),"group_name":name,"site_key":key.upper(),"region":parts[0].upper() if parts else "","site":parts[1].upper() if len(parts)>1 else key.upper()})
    return result


AVAILABILITY_PATTERNS=("unavailable by icmp","icmp ping is unavailable","icmp ping unavailable","host is unreachable","host unreachable","is unreachable","not reachable","no ping","agent is not available","agent is unavailable","snmp agent is not available","snmp unavailable","interface is down","link is down","link down","host is down")
CATEGORY_PATTERNS={"backup":("backup failed","no backup","backup job","backup error"),"capacity":("space is low","space is critically low","disk space","filesystem space","free space"),"hardware":("raid","physical disk","power supply","fan","temperature","system status is in critical state","hardware health"),"performance":("cpu load","high cpu","memory utilization","latency","i/o latency","response time"),"network":("vpn tunnel","tunnel is down","wan","packet loss","interface error"),"service":("service is down","service unavailable","tcp service","tcp port")}


def classify_problem(problem: Problem) -> str:
    name=(problem.name or "").strip().lower()
    if any(p in name for p in AVAILABILITY_PATTERNS): return "availability"
    for category,patterns in CATEGORY_PATTERNS.items():
        if any(p in name for p in patterns): return category
    scopes={str(t.get("value","")).strip().lower() for t in problem.tags or [] if str(t.get("tag","")).strip().lower()=="scope"}
    if "capacity" in scopes: return "capacity"
    if "performance" in scopes: return "performance"
    return "other"


def is_availability_problem(problem: Problem) -> bool: return classify_problem(problem)=="availability"

def _problem_hostids(problem: Problem) -> set[int]:
    result=set()
    for host in problem.hosts or []:
        try: result.add(int(host.get("hostid")))
        except (TypeError,ValueError): pass
    return result


def site_analytics(db: Session) -> list[dict]:
    hosts=db.scalars(select(Host).where(Host.status==0)).all(); problems=db.scalars(select(Problem).where(Problem.active.is_(True))).all()
    host_map={}; sites={}
    for host in hosts:
        groups=site_groups(host)
        if not groups: continue
        host_map[int(host.zabbix_hostid)]=(host,groups); equipment=equipment_from_host(host); role=equipment_role(equipment)
        for parsed in groups:
            site=sites.setdefault(parsed["site_key"],{"site_key":parsed["site_key"],"zabbix_groupid":parsed["groupid"],"zabbix_group_name":parsed["group_name"],"region":parsed["region"],"site":parsed["site"],"hosts_total":0,"affected_hostids":set(),"unavailable_hostids":set(),"gateway_hostids":set(),"gateway_hosts":[],"equipment":defaultdict(int),"roles":defaultdict(int),"problems":[]})
            site["hosts_total"]+=1; site["equipment"][equipment]+=1; site["roles"][role]+=1
            if role=="gateway":
                hid=int(host.zabbix_hostid); site["gateway_hostids"].add(hid)
                site["gateway_hosts"].append({"hostid":str(hid),"name":host.visible_name or host.technical_name,"host":host.technical_name})

    for problem in problems:
        category=classify_problem(problem); availability=category=="availability"; matched_by_site=defaultdict(list)
        for hostid in _problem_hostids(problem):
            item=host_map.get(hostid)
            if not item: continue
            host,groups=item; equipment=equipment_from_host(host); role=equipment_role(equipment)
            for parsed in groups:
                key=parsed["site_key"]; sites[key]["affected_hostids"].add(hostid)
                if availability: sites[key]["unavailable_hostids"].add(hostid)
                matched_by_site[key].append({"hostid":str(hostid),"name":host.visible_name,"equipment":equipment,"role":role,"site_key":key})
        for key,matched in matched_by_site.items(): sites[key]["problems"].append({"eventid":str(problem.zabbix_eventid),"name":problem.name,"severity":problem.severity,"impact_score":problem.impact_score,"availability":availability,"category":category,"started_at":problem.started_at,"hosts":matched})

    now=datetime.now(timezone.utc); correlation_by_site=user_correlations(db,set(sites.keys()),now); result=[]
    for site in sites.values():
        ps=sorted(site["problems"],key=lambda p:(-p["impact_score"],p["started_at"])); max_score=max((p["impact_score"] for p in ps),default=0)
        affected=len(site["affected_hostids"]); unavailable=len(site["unavailable_hostids"]); affected_ratio=round(affected/site["hosts_total"]*100,1) if site["hosts_total"] else 0.0; unavailable_ratio=round(unavailable/site["hosts_total"]*100,1) if site["hosts_total"] else 0.0
        burst_5m=sum(1 for p in ps if (now-p["started_at"]).total_seconds()<=300); burst_15m=sum(1 for p in ps if (now-p["started_at"]).total_seconds()<=900)
        affected_roles={h["role"] for p in ps for h in p["hosts"]}; unavailable_roles={h["role"] for p in ps if p["availability"] for h in p["hosts"]}
        gateway_affected=bool(site["gateway_hostids"] & site["unavailable_hostids"]); gateway_found=bool(site["gateway_hostids"]); internet_status="down" if gateway_affected else "up" if gateway_found else "unknown"
        critical_service_affected=bool({"pacs","database","storage"}&affected_roles); multi=min(15,max(0,affected-1)*3); volume=min(10,max(0,len(ps)-1)); outage=15 if unavailable_ratio>=75 else 10 if unavailable_ratio>=50 else 5 if unavailable_ratio>=25 else 0; burst=10 if burst_5m>=5 else 6 if burst_15m>=5 else 3 if burst_15m>=3 else 0; gateway=10 if gateway_affected and unavailable>=2 else 0; critical=5 if critical_service_affected else 0
        categories=defaultdict(int)
        for p in ps: categories[p["category"]]+=1
        root=correlation_by_site.get(site["site_key"]); cause=root["probable_cause"] if root else None
        if not cause:
            if gateway_affected: cause="Интернет-канал / gateway объекта недоступен"
            elif burst_5m>=5: cause="Массовый всплеск проблем на объекте"
            elif unavailable_ratio>=75: cause="Большая часть оборудования объекта недоступна"
            elif critical_service_affected: cause="Затронут критичный сервис объекта"
            elif categories.get("capacity"): cause="Проблема емкости дискового пространства/хранилища"
            elif categories.get("backup"): cause="Проблема резервного копирования"
            elif categories.get("hardware"): cause="Аппаратная проблема оборудования"
            elif categories.get("network"): cause="Сетевая проблема"
            elif categories.get("performance"): cause="Проблема производительности"
            elif categories.get("service"): cause="Проблема доступности сервиса"
        risk=min(100,max_score+multi+volume+outage+burst+gateway+critical) if ps else 0
        result.append({"site_key":site["site_key"],"zabbix_groupid":site["zabbix_groupid"],"zabbix_group_name":site["zabbix_group_name"],"region":site["region"],"site":site["site"],"risk_score":risk,"max_problem_score":max_score,"active_problems":len(ps),"affected_hosts":affected,"hosts_total":site["hosts_total"],"affected_ratio":affected_ratio,"unavailable_hosts":unavailable,"unavailable_ratio":unavailable_ratio,"burst_5m":burst_5m,"burst_15m":burst_15m,"gateway_found":gateway_found,"gateway_affected":gateway_affected,"gateway_hosts":site["gateway_hosts"],"internet_status":internet_status,"critical_service_affected":critical_service_affected,"probable_cause":cause,"root_cause":root,"categories":dict(sorted(categories.items())),"risk_breakdown":{"max_problem":max_score,"multi_device":multi,"problem_volume":volume,"unavailable_ratio":outage,"burst":burst,"gateway":gateway,"critical_service":critical},"equipment":dict(sorted(site["equipment"].items())),"roles":dict(sorted(site["roles"].items())),"top_problems":ps[:10]})
    return sorted(result,key=lambda x:(-x["risk_score"],-x["affected_hosts"],x["site_key"]))
