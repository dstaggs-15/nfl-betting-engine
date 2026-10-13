"""Observed play-by-play opportunity summaries with causal availability inherited from final stats."""

from collections import defaultdict

import nflreadpy as nfl

from .nfl import cached_frame

FIELDS = [
    "game_id",
    "posteam",
    "defteam",
    "play_id",
    "yardline_100",
    "rush_attempt",
    "pass_attempt",
    "rusher_player_id",
    "receiver_player_id",
    "passer_player_id",
    "touchdown",
    "pass_touchdown",
    "rush_touchdown",
    "td_player_id",
    "yards_gained",
    "receiving_yards",
    "rushing_yards",
    "drive",
]


def enrich(root, history, season):
    players, teams, first = (
        defaultdict(lambda: defaultdict(float)),
        defaultdict(lambda: defaultdict(float)),
        {},
    )
    for year in [season - 2, season - 1, season]:

        def loader(year=year):
            frame = nfl.load_pbp(year)
            return frame.select([f for f in FIELDS if f in frame.columns])

        frame = cached_frame(root, f"pbp-{year}", loader, max_age=3600 if year == season else 86400 * 30)
        for play in frame.sort("game_id", "play_id").to_dicts():
            game, team = play["game_id"], play["posteam"]
            if not team:
                continue
            yardline = play.get("yardline_100")
            rz = yardline is not None and yardline <= 20
            gl = yardline is not None and yardline <= 5
            if play.get("rush_attempt") == 1 and play.get("rusher_player_id"):
                player = players[(game, play["rusher_player_id"])]
                player["redzone_carries"] += rz
                player["goal_line_carries"] += gl
                player["longest_rush"] = max(player["longest_rush"], play.get("rushing_yards") or 0)
            if play.get("pass_attempt") == 1 and play.get("receiver_player_id"):
                player = players[(game, play["receiver_player_id"])]
                player["redzone_targets"] += rz
                player["goal_line_targets"] += gl
                player["longest_reception"] = max(
                    player["longest_reception"], play.get("receiving_yards") or 0
                )
            if play.get("touchdown") == 1:
                teams[(game, team)]["team_tds"] += 1
                teams[(game, team)]["team_pass_tds"] += play.get("pass_touchdown") or 0
                if play.get("td_player_id"):
                    players[(game, play["td_player_id"])]["scored_tds"] += 1
                first.setdefault(game, play.get("td_player_id"))
    for row in history:
        row.update(players[(row["event_id"], row["player_id"])])
        row.update(teams[(row["event_id"], row["team"])])
        row["first_touchdown"] = float(first.get(row["event_id"]) == row["player_id"])
        row["opportunities_available"] = True
    return history
