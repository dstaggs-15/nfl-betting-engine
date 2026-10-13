"""Read-only collectors. No account/order endpoints, login, or browser evasion."""

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from .normalize import market
from .schemas import Line, Market
from .storage import digest


class LineProvider(Protocol):
    name: str

    def fetch_markets(self) -> dict: ...
    def normalize(self, raw: dict, context, now) -> list[Line]: ...


def get_json(url, params=None):
    for attempt in range(3):
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("request exhausted")


def read_export(path):
    raw = json.loads(Path(path).read_text())
    timestamp = datetime.fromisoformat(raw.get("exported_at", ""))
    if timestamp.tzinfo is None or timestamp > datetime.now(UTC):
        raise ValueError("exports need a real, non-future, timezone-aware exported_at")
    return raw


class Context:
    def __init__(self, games, identity, bindings=None):
        self.games = {g.event_id: g for g in games}
        self.identity = identity
        self.bindings = bindings or {}

    def resolve(self, provider, raw_id, name, team, event_id=None):
        binding = self.bindings.get(f"{provider}:{raw_id}", {})
        game = self.games.get(binding.get("event_id", event_id))
        player_id = binding.get("player_id") or self.identity.match(name, team)
        player = self.identity.players.get(player_id)
        if not game or not player or player["team"] not in (game.home, game.away):
            return None
        return game, player


def line(
    provider,
    raw_id,
    resolved,
    canonical,
    threshold,
    direction,
    now,
    raw_hash,
    price=None,
    price_type="unknown",
):
    game, player = resolved
    return Line(
        line_id=digest([provider, str(raw_id), direction, threshold])[:24],
        provider=provider,
        provider_market_id=str(raw_id),
        event_id=game.event_id,
        player_id=player["player_id"],
        player_name=player["player_name"],
        team=player["team"],
        opponent=game.away if player["team"] == game.home else game.home,
        market=canonical,
        threshold=threshold,
        direction=direction,
        display_line=f"{direction.title()} {threshold}",
        price=price,
        price_type=price_type,
        collected_at=now,
        raw_source_hash=raw_hash,
    )


class Underdog:
    name = "underdog"
    endpoint = "https://api.underdogfantasy.com/beta/v5/over_under_lines"

    def fetch_markets(self):
        export = os.getenv("UNDERDOG_EXPORT_PATH")
        return read_export(export) if export else get_json(self.endpoint)

    def normalize(self, raw, context, now):
        if raw.get("exported_at"):
            now = datetime.fromisoformat(raw["exported_at"])
        players = {str(p["id"]): p for p in raw.get("players", [])}
        appearances = {str(a["id"]): a for a in raw.get("appearances", [])}
        games = {str(g["id"]): g for g in raw.get("games", [])}
        teams = {str(t["id"]): t.get("abbr", t.get("abbreviation")) for t in raw.get("teams", [])}
        output = []
        raw_hash = digest(raw)
        for item in raw.get("over_under_lines", []):
            try:
                if item.get("status", "active") != "active":
                    continue
                stat = item["over_under"]["appearance_stat"]
                appearance = appearances.get(str(stat["appearance_id"]), {})
                player = players.get(str(appearance.get("player_id")), {})
                canonical = market(stat.get("display_stat", stat.get("stat", "")))
                if not canonical or not player or player.get("sport_id", "NFL") not in ("NFL", "nfl", 2):
                    continue
                name = (
                    player.get("full_name") or f"{player.get('first_name', '')} {player.get('last_name', '')}"
                )
                team = teams.get(str(appearance.get("team_id"))) or player.get("team")
                source_game = games.get(str(appearance.get("match_id")), {})
                event_id = source_game.get("nflverse_game_id")
                # Automatic association requires exact teams and kickoff date.
                if not event_id and source_game:
                    home = teams.get(str(source_game.get("home_team_id")))
                    away = teams.get(str(source_game.get("away_team_id")))
                    date = str(source_game.get("scheduled_at", ""))[:10]
                    candidates = [
                        g
                        for g in context.games.values()
                        if g.home == home and g.away == away and g.kickoff.date().isoformat() == date
                    ]
                    if len(candidates) == 1:
                        event_id = candidates[0].event_id
                resolved = context.resolve(self.name, item["id"], name.strip(), team, event_id)
                if not resolved:
                    continue
                for option in item.get("options", []):
                    choice = str(option.get("choice", "")).lower()
                    direction = {"higher": "over", "lower": "under", "over": "over", "under": "under"}.get(
                        choice
                    )
                    if direction:
                        # Option boost/payout is NOT a verified ticket multiplier.
                        output.append(
                            line(
                                self.name,
                                item["id"],
                                resolved,
                                canonical,
                                float(item["stat_value"]),
                                direction,
                                now,
                                raw_hash,
                            )
                        )
            except (KeyError, TypeError, ValueError):
                continue
        return output


class Kalshi:
    name = "kalshi"
    endpoint = "https://api.elections.kalshi.com/trade-api/v2/markets"
    series = (
        "KXNFLPASSYDS",
        "KXNFLRSHYDS",
        "KXNFLRECYDS",
        "KXNFLANYTD",
        "KXNFLFIRSTTD",
        "KXNFLREC",
        "KXNFLPASSTDS",
    )

    def fetch_markets(self):
        export = os.getenv("KALSHI_EXPORT_PATH")
        if export:
            return read_export(export)
        markets = []
        for series in self.series:
            cursor = None
            for _ in range(20):
                payload = get_json(
                    self.endpoint,
                    {
                        "series_ticker": series,
                        "status": "open",
                        "limit": 200,
                        **({"cursor": cursor} if cursor else {}),
                    },
                )
                markets.extend(payload.get("markets", []))
                cursor = payload.get("cursor")
                if not cursor:
                    break
            else:
                raise ValueError("pagination cap reached; collection incomplete")
        return {"markets": markets}

    def automatic_binding(self, item, context):
        series = item.get("event_ticker", "").split("-")[0]
        canonical = {
            "KXNFLPASSYDS": Market.PASSING,
            "KXNFLRSHYDS": Market.RUSHING,
            "KXNFLRECYDS": Market.RECEIVING,
            "KXNFLREC": Market.RECEPTIONS,
            "KXNFLPASSTDS": Market.PASS_TD,
            "KXNFLANYTD": Market.ANYTIME_TD,
            "KXNFLFIRSTTD": Market.FIRST_TD,
        }.get(series)
        touchdown = canonical in (Market.ANYTIME_TD, Market.FIRST_TD)
        if not canonical or (not touchdown and item.get("strike_type") != "greater"):
            return None
        aliases = {"LA": "LAR", "WAS": "WSH", "JAX": "JAC"}
        matches = []
        for game in context.games.values():
            date = game.kickoff.astimezone(ZoneInfo("America/New_York")).strftime("%y%b%d").upper()
            away, home = aliases.get(game.away, game.away), aliases.get(game.home, game.home)
            expected = f"{series}-{date}{away}{home}"
            if item.get("event_ticker") == expected:
                matches.append(game)
        if len(matches) != 1:
            return None
        game = matches[0]
        title = item.get("title", "")
        if touchdown:
            suffix = "1st Touchdown" if canonical == Market.FIRST_TD else "Anytime Touchdown"
            parsed = re.fullmatch(r"(.+): " + re.escape(suffix), title)
            if not parsed or item.get("strike_type") != "structured":
                return None
            threshold = 0.5
            rule = item.get("rules_primary", "").lower()
            if ("first touchdown" if canonical == Market.FIRST_TD else "touchdown") not in rule:
                return None
        else:
            parsed = re.fullmatch(
                r"(.+): (\d+)\+ (passing yards|rushing yards|receiving yards|receptions|passing touchdowns)",
                title,
            )
            if not parsed or (market(parsed[3]) != canonical):
                return None
            threshold = float(item.get("floor_strike", -1))
            if threshold != int(parsed[2]) - 0.5:
                return None
        matches = []
        for team in (game.home, game.away):
            player_id = context.identity.match(parsed[1], team)
            ticker_team = aliases.get(team, team)
            if player_id and item["ticker"].split("-")[2].startswith(ticker_team):
                matches.append((player_id, team))
        if len(matches) != 1:
            return None
        return {
            "event_id": game.event_id,
            "player_id": matches[0][0],
            "market": str(canonical),
            "threshold": threshold,
            "yes_direction": "over",
        }

    def normalize(self, raw, context, now):
        if raw.get("exported_at"):
            now = datetime.fromisoformat(raw["exported_at"])
        output = []
        raw_hash = digest(raw)
        for item in raw.get("markets", []):
            try:
                if item.get("status") not in ("active", "open"):
                    continue
                # Provider-specific semantics must be audited; ticker/title similarity is not identity.
                binding = (
                    context.bindings.get(f"kalshi:{item['ticker']}")
                    or self.automatic_binding(item, context)
                    or {}
                )
                if binding:
                    context.bindings[f"kalshi:{item['ticker']}"] = binding
                resolved = context.resolve(self.name, item["ticker"], "", "")
                if not resolved or not binding.get("market") or "threshold" not in binding:
                    continue
                canonical = Market(binding["market"])
                yes_direction = binding.get("yes_direction", "over")
                for side in ("yes", "no"):
                    ask = item.get(f"{side}_ask_dollars")
                    if ask is None and item.get(f"{side}_ask") is not None:
                        ask = float(item[f"{side}_ask"]) / 100
                    if ask is None or not 0 < float(ask) < 1:
                        continue
                    direction = (
                        yes_direction if side == "yes" else ("under" if yes_direction == "over" else "over")
                    )
                    output.append(
                        line(
                            self.name,
                            item["ticker"],
                            resolved,
                            canonical,
                            float(binding["threshold"]),
                            direction,
                            now,
                            raw_hash,
                            float(ask),
                            "contract",
                        )
                    )
            except (KeyError, TypeError, ValueError):
                continue
        return output
