from datetime import timedelta

import numpy as np
import pytest

from nfl_engine.dfs import OddsAPI, PrizePicks
from nfl_engine.fitted import Features, cdf_at
from nfl_engine.normalize import Identity
from nfl_engine.providers import Context
from nfl_engine.value import contract_value, parlay_value, qualifying_value


def test_features_cannot_see_future(history, now):
    future = {**history[-1], "available_at": (now + timedelta(days=1)).isoformat(), "attempts": 10000}
    a, _ = Features(history).build("player1", "HOU", now)
    b, _ = Features(history + [future]).build("player1", "HOU", now)
    np.testing.assert_array_equal(a, b)


def test_distribution_monotone_and_bounded():
    values = np.array([0, 0, 1, 3, 5, 8, 12, 16, 20, 25, 30])
    ps = [cdf_at(x, values) for x in np.arange(0, 40, 0.5)]
    assert all(0 <= p <= 1 for p in ps)
    assert np.all(np.diff(ps) >= 0)


def test_real_cost_fees_and_profit():
    v = contract_value(0.8, 0.5, "quadratic", 1, 10)
    assert v["contracts"] == 19
    assert v["estimated_fee"] == 0.34
    assert v["cost"] == 9.84
    assert v["win_profit"] == 9.16
    assert v["expected_profit"] == pytest.approx(5.36)
    assert v["break_even"] == pytest.approx(9.84 / 19)
    assert contract_value(0.99, 0.97, "unknown", None) is None
    assert parlay_value(0.95, 1.2) is None
    assert not parlay_value(0.4, 2)["qualifies"]
    assert parlay_value(0.5, 3)["qualifies"]


def test_expensive_no_is_not_value(prediction):
    p = prediction.model_copy(update={"probability": 0.99})
    v = contract_value(0.99, 0.97, "quadratic", 1)
    assert v["win_profit"] < 5
    assert not qualifying_value(p, v)


def context(game):
    return Context(
        [game], Identity([{"player_id": "player1", "player_name": "Trevor Lawrence", "team": "JAX"}])
    )


def test_supported_third_party_dfs_schema(game, now):
    event = {
        "id": "external-game",
        "home_team": "Jacksonville Jaguars",
        "away_team": "Houston Texans",
        "commence_time": game.kickoff.isoformat(),
        "bookmakers": [
            {
                "key": "prizepicks",
                "last_update": now.isoformat(),
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "outcomes": [
                            {"name": "Over", "description": "Trevor Lawrence", "point": 249.5, "price": 1.9},
                            {"name": "Under", "description": "Trevor Lawrence", "point": 249.5, "price": 1.9},
                        ],
                    }
                ],
            }
        ],
    }
    teams = {"JAX": {"name": "Jacksonville Jaguars"}, "HOU": {"name": "Houston Texans"}}
    lines = OddsAPI().normalize([event], context(game), teams, now)
    assert len(lines) == 2
    assert lines[0].provider == "prizepicks"
    assert lines[0].price is None  # Indicative individual DFS prices do not establish a ticket payout.
    assert lines[0].collected_at == now


def test_prizepicks_fixture_rejects_modified_payout_lines(game, now):
    raw = {
        "included": [
            {"type": "new_player", "id": "p", "attributes": {"name": "Trevor Lawrence", "team": "JAC"}}
        ],
        "data": [
            {
                "id": "projection",
                "attributes": {
                    "stat_type": "Passing Yards",
                    "line_score": 249.5,
                    "start_time": game.kickoff.isoformat(),
                    "odds_type": "standard",
                },
                "relationships": {"new_player": {"data": {"type": "new_player", "id": "p"}}},
            }
        ],
    }
    lines = PrizePicks().normalize(raw, context(game), now)
    assert len(lines) == 2
    raw["data"][0]["attributes"]["odds_type"] = "demon"
    assert not PrizePicks().normalize(raw, context(game), now)


def test_empirical_copula_preserves_opposite_sides_and_dependence(prediction):
    from nfl_engine.fitted import FittedSimulator
    from nfl_engine.schemas import Market

    a = prediction.model_copy(
        update={
            "prediction_id": "a",
            "probability": 0.5,
            "line": prediction.line.model_copy(update={"market": Market.RECEIVING, "player_id": "a"}),
        }
    )
    b = a.model_copy(update={"prediction_id": "b", "line": a.line.model_copy(update={"player_id": "b"})})
    no_a = a.model_copy(
        update={"prediction_id": "no-a", "line": a.line.model_copy(update={"direction": "under"})}
    )
    sim = FittedSimulator.__new__(FittedSimulator)
    sim.count = 20000
    sim.rng = np.random.default_rng(12)
    sim.positions = {"a": "WR", "b": "WR"}
    sim.correlation_cache = {}
    residuals = []
    for i in range(100):
        for player in ("a", "b"):
            residuals.append(
                {
                    "event_id": str(i),
                    "player_id": player,
                    "team": "JAX",
                    "position": "WR",
                    "pit": (i + 0.5) / 100,
                }
            )
    sim.bundle = {"residuals": {"receiving_yards": residuals}}
    masks = sim.masks([a, b, no_a])
    assert np.all(masks["a"] != masks["no-a"])
    assert np.mean(masks["a"] & masks["b"]) > 0.30


def test_integer_line_keeps_push_mass(prediction):
    from nfl_engine.fitted import FittedSimulator
    from nfl_engine.schemas import Market

    class IdentityCalibration:
        def predict(self, values):
            return values

    sim = FittedSimulator.__new__(FittedSimulator)
    sim.engine = type(
        "FeatureFixture", (), {"build": lambda self, *args: (np.zeros(1), [{"position": "WR"}])}
    )()
    sim.cutoff = prediction.line.collected_at
    sim.bundle = {"models": {"receptions": [True]}, "calibrators": {"receptions": IdentityCalibration()}}
    sim.positions = {}
    line = prediction.line.model_copy(update={"market": Market.RECEPTIONS, "threshold": 3.0})
    sim.cache = {(line.event_id, line.player_id, "receptions"): np.array([0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 10])}
    under, _ = sim.probability(line.model_copy(update={"direction": "under"}))
    over, _ = sim.probability(line.model_copy(update={"direction": "over"}))
    assert under + over < 1
    assert 1 - under - over == pytest.approx(
        cdf_at(3.5, sim.cache[(line.event_id, line.player_id, "receptions")])
        - cdf_at(2.5, sim.cache[(line.event_id, line.player_id, "receptions")])
    )
