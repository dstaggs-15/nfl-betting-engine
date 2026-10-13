"""Public PrizePicks and supported third-party DFS collection; read-only, no orders."""

import logging
import os
from datetime import UTC, datetime, timedelta

from .normalize import key, market
from .providers import get_json, line, read_export
from .schemas import Market
from .storage import digest

logger = logging.getLogger(__name__)
ODDS_MARKETS = {
    "player_pass_yds": Market.PASSING,
    "player_pass_tds": Market.PASS_TD,
    "player_rush_yds": Market.RUSHING,
    "player_reception_yds": Market.RECEIVING,
    "player_receptions": Market.RECEPTIONS,
    "player_rush_reception_yds": Market.SCRIMMAGE,
    "player_rush_attempts": Market.CARRIES,
}


class PrizePicks:
    name = "prizepicks"
    endpoint = "https://api.prizepicks.com/projections"

    def fetch_markets(self):
        export = os.getenv("PRIZEPICKS_EXPORT_PATH")
        return (
            read_export(export)
            if export
            else get_json(self.endpoint, {"league_id": 9, "per_page": 250, "single_stat": "true"})
        )

    def normalize(self, raw, context, now):
        if raw.get("exported_at"):
            now = datetime.fromisoformat(raw["exported_at"])
        included = {(str(p["type"]), str(p["id"])): p.get("attributes", {}) for p in raw.get("included", [])}
        result = []
        source = digest(raw)
        for item in raw.get("data", []):
            try:
                attrs = item["attributes"]
                relation = item["relationships"]["new_player"]["data"]
                player = included.get((relation["type"], str(relation["id"])), {})
                if attrs.get("odds_type", "standard") != "standard":
                    continue
                canonical = market(attrs.get("stat_type", ""))
                name = player.get("display_name", player.get("name", ""))
                team = player.get("team")
                team = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}.get(team, team)
                pid = context.identity.match(name, team)
                if not canonical or not pid:
                    continue
                kickoff = datetime.fromisoformat(attrs["start_time"].replace("Z", "+00:00"))
                candidates = [
                    g
                    for g in context.games.values()
                    if team in (g.home, g.away) and abs((g.kickoff - kickoff).total_seconds()) < 300
                ]
                if len(candidates) != 1:
                    continue
                resolved = context.resolve(self.name, item["id"], name, team, candidates[0].event_id)
                if not resolved:
                    continue
                # Demon/goblin/discount payouts cannot be assumed to equal standard tickets.
                for direction in ("over", "under"):
                    result.append(
                        line(
                            self.name,
                            item["id"],
                            resolved,
                            canonical,
                            float(attrs["line_score"]),
                            direction,
                            now,
                            source,
                        )
                    )
            except (KeyError, TypeError, ValueError):
                continue
        return result


class OddsAPI:
    endpoint = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"

    def fetch(self):
        token = os.getenv("ODDS_API_KEY")
        if not token:
            raise ValueError("ODDS_API_KEY is missing")
        # Suppress third-party request URLs: authentication is a query parameter.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        events = get_json(self.endpoint + "/events", {"apiKey": token})
        result = []
        for event in events:
            kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            if not datetime.now(UTC) < kickoff < datetime.now(UTC) + timedelta(days=10):
                continue
            result.append(
                get_json(
                    self.endpoint + f"/events/{event['id']}/odds",
                    {
                        "apiKey": token,
                        "bookmakers": "underdog,prizepicks",
                        "markets": ",".join(ODDS_MARKETS),
                        "oddsFormat": "decimal",
                        "dateFormat": "iso",
                    },
                )
            )
        return result

    def normalize(self, events, context, teams, now):
        names = {key(v["name"]): abbr for abbr, v in teams.items()}
        result = []
        for event in events:
            try:
                home = names.get(key(event["home_team"]))
                away = names.get(key(event["away_team"]))
                kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
                games = [
                    g
                    for g in context.games.values()
                    if g.home == home and g.away == away and abs((g.kickoff - kickoff).total_seconds()) < 300
                ]
                if len(games) != 1:
                    continue
                game = games[0]
                for book in event.get("bookmakers", []):
                    provider = book["key"]
                    if provider not in ("underdog", "prizepicks"):
                        continue
                    for raw_market in book.get("markets", []):
                        canonical = ODDS_MARKETS.get(raw_market["key"])
                        if not canonical:
                            continue
                        updated = datetime.fromisoformat(
                            raw_market.get("last_update", book.get("last_update", "")).replace("Z", "+00:00")
                        )
                        if updated > now:
                            continue
                        for outcome in raw_market.get("outcomes", []):
                            name = outcome.get("description", "")
                            candidates = [(team, context.identity.match(name, team)) for team in (home, away)]
                            candidates = [c for c in candidates if c[1]]
                            direction = {"Over": "over", "Under": "under"}.get(outcome.get("name"))
                            if len(candidates) != 1 or not direction:
                                continue
                            team, pid = candidates[0]
                            resolved = context.resolve(provider, "", name, team, game.event_id)
                            if not resolved:
                                continue
                            raw_id = digest(
                                [event["id"], provider, raw_market["key"], pid, outcome["point"]]
                            )[:24]
                            # Individual decimal prices do not establish DFS full-ticket payout rules.
                            result.append(
                                line(
                                    provider,
                                    raw_id,
                                    resolved,
                                    canonical,
                                    float(outcome["point"]),
                                    direction,
                                    updated,
                                    digest(event),
                                )
                            )
            except (KeyError, TypeError, ValueError):
                continue
        return result
