import csv
import io
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import nflreadpy as nfl
import polars as pl

from .schemas import Game
from .storage import write_json

TEAM_URL = "https://raw.githubusercontent.com/nflverse/nflverse-pbp/master/teams_colors_logos.csv"


def cached_frame(root: Path, name, loader, max_age=3600):
    path = root / ".cache" / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", str(root / ".cache"))
    if path.exists() and datetime.now(UTC).timestamp() - path.stat().st_mtime < max_age:
        return pl.read_parquet(path)
    frame = loader()
    frame.write_parquet(path)
    return frame


def load(root, season):
    schedules = cached_frame(root, "schedules", lambda: nfl.load_schedules([season - 2, season - 1, season]))
    stats = cached_frame(
        root, f"stats-{season}", lambda: nfl.load_player_stats([season - 2, season - 1, season])
    )
    roster = cached_frame(root, f"rosters-{season}", lambda: nfl.load_rosters(season))
    games = []
    for row in schedules.to_dicts():
        if row.get("gametime") is None or row.get("gameday") is None:
            continue
        kickoff = (
            datetime.fromisoformat(f"{row['gameday']}T{row['gametime']}")
            .replace(tzinfo=ZoneInfo("America/New_York"))
            .astimezone(UTC)
        )
        # Scores are evidence of an official completed schedule row, not a timer.
        final = row.get("home_score") is not None and row.get("away_score") is not None
        games.append(
            Game(
                event_id=row["game_id"],
                season=row["season"],
                week=row["week"],
                home=row["home_team"],
                away=row["away_team"],
                kickoff=kickoff,
                status="final" if final else "scheduled",
            )
        )
    indexed = {(g.season, g.week, team): g for g in games for team in (g.home, g.away)}
    history = []
    for row in stats.to_dicts():
        team = row.get("team", row.get("recent_team"))
        game = indexed.get((row["season"], row["week"], team))
        if game is None or game.status != "final":
            continue
        row.update(
            event_id=game.event_id,
            team=team,
            opponent=game.away if team == game.home else game.home,
            kickoff=game.kickoff.isoformat(),
            available_at=(game.kickoff + timedelta(days=1)).isoformat(),
        )
        history.append(row)
    players = []
    for row in roster.to_dicts():
        if row.get("gsis_id") and row.get("team"):
            players.append(
                {"player_id": row["gsis_id"], "player_name": row.get("full_name", ""), "team": row["team"]}
            )
    from .opportunities import enrich

    try:
        history = enrich(root, history, season)
    except Exception:
        # Optional opportunity inputs never replace known stats with invented values.
        import logging

        logging.getLogger("nfl_engine").warning("play_by_play_opportunities_unavailable")
    return games, history, players


def teams(root):
    response = httpx.get(TEAM_URL, timeout=30, follow_redirects=True)
    response.raise_for_status()
    output = {}
    for row in csv.DictReader(io.StringIO(response.text)):
        output[row["team_abbr"]] = {
            "abbreviation": row["team_abbr"],
            "name": row["team_name"],
            "conference": row.get("team_conf"),
            "division": row.get("team_division"),
            "primary": row.get("team_color"),
            "secondary": row.get("team_color2"),
            "logo": row.get("team_logo_espn"),
            "fallback_logo": row.get("team_logo_wikipedia"),
        }
    write_json(root / "site/data/teams.json", output)
    return output
