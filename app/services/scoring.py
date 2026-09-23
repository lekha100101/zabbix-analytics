from datetime import datetime, timezone


SEVERITY_POINTS = {
    0: 5,   # Not classified
    1: 10,  # Information
    2: 25,  # Warning
    3: 45,  # Average
    4: 70,  # High
    5: 90,  # Disaster
}


def calculate_impact_score(problem: dict) -> int:
    """Initial explainable score. It will evolve as topology and history are added."""
    severity = int(problem.get("severity", 0))
    score = SEVERITY_POINTS.get(severity, 5)

    try:
        started = datetime.fromtimestamp(int(problem["clock"]), tz=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - started).total_seconds() / 3600)
    except (KeyError, TypeError, ValueError, OSError):
        age_hours = 0

    if age_hours >= 24:
        score += 10
    elif age_hours >= 4:
        score += 5
    elif age_hours >= 1:
        score += 2

    if str(problem.get("acknowledged", "0")) == "0":
        score += 3

    return min(score, 100)
