from zoneinfo import ZoneInfo

CHECKPOINTS = {
    4: [(8, 0, "friday_morning")],
    6: [(15, 15, "sunday_early"), (18, 30, "sunday_late"), (23, 0, "sunday_night")],
    1: [(8, 0, "tuesday_morning")],
}


def due_games(games, now, config):
    return [
        g
        for g in games
        if g.status == "scheduled"
        and config["minimum_minutes_before_kickoff"]
        <= (g.kickoff - now).total_seconds() / 60
        <= config["window_before_minutes"]
    ]


def due_checkpoints(now, config):
    local = now.astimezone(ZoneInfo(config["timezone"]))
    due = []
    for hour, minute, name in CHECKPOINTS.get(local.weekday(), []):
        configured = config.get("checkpoints", {}).get(name, f"{hour:02}:{minute:02}")
        hour, minute = map(int, configured.split(":"))
        scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local >= scheduled:
            due.append((local.date().isoformat(), name))
    return due
