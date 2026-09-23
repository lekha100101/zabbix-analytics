from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Host, HostGroup, Problem, ScoringRule


SEVERITY_POINTS = {0: 2, 1: 5, 2: 12, 3: 22, 4: 35, 5: 50}
DEFAULT_TAG_RULES = {
    ("scope", "availability"): 18,
    ("scope", "capacity"): 7,
    ("scope", "performance"): 6,
    ("scope", "security"): 15,
    ("class", "hardware"): 10,
    ("class", "network"): 8,
    ("component", "system"): 8,
    ("component", "storage"): 6,
    ("component", "database"): 12,
}


def ensure_default_rules(db: Session) -> None:
    if db.scalar(select(ScoringRule.id).limit(1)) is not None:
        return
    for (key, value), points in DEFAULT_TAG_RULES.items():
        db.add(ScoringRule(name=f"tag:{key}={value}", rule_type="tag", key=key, value=value, points=points, enabled=True))
    db.commit()


def load_tag_rules(db: Session) -> dict[tuple[str, str], int]:
    ensure_default_rules(db)
    rules = db.scalars(select(ScoringRule).where(ScoringRule.enabled.is_(True), ScoringRule.rule_type == "tag")).all()
    return {(str(r.key).lower(), str(r.value).lower()): r.points for r in rules if r.key and r.value}


def calculate_impact(problem: dict, tag_rules: dict | None = None, host_points: int = 0, group_points: int = 0) -> tuple[int, dict]:
    rules = tag_rules if tag_rules is not None else DEFAULT_TAG_RULES
    severity = int(problem.get("severity", 0))
    severity_points = SEVERITY_POINTS.get(severity, 2)
    breakdown = {"severity": severity_points, "tags": [], "duration": 0, "unacknowledged": 0, "host_criticality": host_points, "group_criticality": group_points}
    score = severity_points + host_points + group_points

    seen = set()
    for tag in problem.get("tags", []) or []:
        pair = (str(tag.get("tag", "")).lower(), str(tag.get("value", "")).lower())
        if pair in seen:
            continue
        seen.add(pair)
        points = rules.get(pair)
        if points:
            score += points
            breakdown["tags"].append({"tag": pair[0], "value": pair[1], "points": points})

    try:
        clock = problem.get("clock")
        if clock is not None:
            started = datetime.fromtimestamp(int(clock), tz=timezone.utc)
        else:
            started = problem.get("started_at")
            if started and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - started).total_seconds() / 3600) if started else 0
    except (TypeError, ValueError, OSError):
        age_hours = 0

    duration_points = 5 if age_hours >= 168 else 4 if age_hours >= 24 else 2 if age_hours >= 4 else 1 if age_hours >= 1 else 0
    score += duration_points
    breakdown["duration"] = duration_points
    breakdown["age_hours"] = round(age_hours, 1)

    acknowledged = problem.get("acknowledged", False)
    is_ack = acknowledged is True or str(acknowledged) == "1"
    if not is_ack:
        score += 3
        breakdown["unacknowledged"] = 3

    final_score = min(max(score, 0), 100)
    breakdown["total"] = final_score
    return final_score, breakdown


def criticality_for_problem(db: Session, hosts: list[dict]) -> tuple[int, int]:
    host_points = 0
    group_points = 0
    for ref in hosts or []:
        hostid = ref.get("hostid")
        if not hostid:
            continue
        host = db.scalar(select(Host).where(Host.zabbix_hostid == int(hostid)))
        if not host:
            continue
        host_points = max(host_points, host.criticality or 0)
        group_ids = [int(g["groupid"]) for g in (host.groups or []) if g.get("groupid")]
        if group_ids:
            value = db.scalar(select(HostGroup.criticality).where(HostGroup.zabbix_groupid.in_(group_ids)).order_by(HostGroup.criticality.desc()).limit(1))
            group_points = max(group_points, value or 0)
    return host_points, group_points


def recalculate_all(db: Session) -> int:
    rules = load_tag_rules(db)
    problems = db.scalars(select(Problem).where(Problem.active.is_(True))).all()
    for item in problems:
        host_points, group_points = criticality_for_problem(db, item.hosts)
        score, breakdown = calculate_impact({"severity": item.severity, "tags": item.tags, "started_at": item.started_at, "acknowledged": item.acknowledged}, rules, host_points, group_points)
        item.impact_score = score
        item.score_breakdown = breakdown
    db.commit()
    return len(problems)
