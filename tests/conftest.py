from datetime import UTC, datetime, timedelta

import pytest

from nfl_engine.schemas import Game, Line, Market, Prediction


@pytest.fixture
def now():
    return datetime(2026, 10, 18, 16, 30, tzinfo=UTC)


@pytest.fixture
def game(now):
    return Game(
        event_id="2026_06_HOU_JAX",
        season=2026,
        week=6,
        home="JAX",
        away="HOU",
        kickoff=now + timedelta(minutes=30),
    )


@pytest.fixture
def line(now, game):
    return Line(
        line_id="line1",
        provider="kalshi",
        provider_market_id="raw1",
        event_id=game.event_id,
        player_id="player1",
        player_name="Trevor Lawrence",
        team="JAX",
        opponent="HOU",
        market=Market.PASSING,
        threshold=249.5,
        direction="over",
        display_line="Over 249.5",
        price_type="contract",
        price=0.5,
        collected_at=now,
        raw_source_hash="hash1",
    )


@pytest.fixture
def prediction(line):
    return Prediction(
        prediction_id="p1",
        line=line,
        probability=0.75,
        confidence=0.8,
        sample_size=24,
        mean=270,
        median=260,
        recent_hit_rate=0.6,
        historical_hit_rate=0.7,
        opponent_factor=1,
        status="WATCH",
        model_version="test",
    )


@pytest.fixture
def history(game):
    rows = []
    for index in range(24):
        kickoff = game.kickoff - timedelta(days=7 * (24 - index))
        rows.append(
            {
                "player_id": "player1",
                "player_display_name": "Trevor Lawrence",
                "team": "JAX",
                "opponent": "HOU",
                "event_id": f"old-{index}",
                "kickoff": kickoff.isoformat(),
                "available_at": (kickoff + timedelta(days=1)).isoformat(),
                "season": 2025,
                "week": index + 1,
                "position": "QB",
                "attempts": 30 + index % 10,
                "completions": 20 + index % 5,
                "passing_yards": 220 + index * 5,
                "targets": 5,
                "receptions": 3,
                "receiving_yards": 30,
                "carries": 5,
                "rushing_yards": 20,
            }
        )
    return rows
