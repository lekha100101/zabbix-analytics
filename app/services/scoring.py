from datetime import datetime, timezone


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


def calculate_impact(problem: dict, tag_rules: dict | None = None) -> tuple[int, dict]:
    rules = tag_rules if tag_rules is not None else DEFAULT_TAG_RULES
    severity = int(problem.get("severity", 0))
    severity_points = SEVERITY_POINTS.get(severity, 2)

    breakdown = {
        "severity": severity_points,
        "tags": [],
        "duration": 0,
        "unacknowledged": 0,
    }
    score = severity_points

    # Apply each exact tag rule once. Multiple different tags may contribute.
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
        started = datetime.fromtimestamp(int(problem["clock"]), tz=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - started).total_seconds() / 3600)
    except (KeyError, TypeError, ValueError, OSError):
        age_hours = 0

    if age_hours >= 168:
        duration_points = 5
    elif age_hours >= 24:
        duration_points = 4
    elif age_hours >= 4:
        duration_points = 2
    elif age_hours >= 1:
        duration_points = 1
    else:
        duration_points = 0
    score += duration_points
    breakdown["duration"] = duration_points
    breakdown["age_hours"] = round(age_hours, 1)

    if str(problem.get("acknowledged", "0")) == "0":
        score += 3
        breakdown["unacknowledged"] = 3

    final_score = min(max(score, 0), 100)
    breakdown["total"] = final_score
    return final_score, breakdown


def calculate_impact_score(problem: dict) -> int:
    return calculate_impact(problem)[0]
