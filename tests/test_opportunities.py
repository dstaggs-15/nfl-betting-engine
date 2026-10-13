import numpy as np

from nfl_engine.model import Simulator
from nfl_engine.schemas import Market


def enriched(history):
    rows = []
    for row in history:
        for team in ("JAX", "HOU"):
            for player, index in [("player1", 1), ("player2", 2)]:
                rows.append(
                    {
                        **row,
                        "team": team,
                        "player_id": player + team,
                        "position": "RB",
                        "opportunities_available": True,
                        "redzone_carries": 4 + index,
                        "goal_line_carries": 2,
                        "redzone_targets": 2,
                        "goal_line_targets": 1,
                        "team_tds": 3,
                        "team_pass_tds": 2,
                        "scored_tds": index,
                        "longest_reception": 20,
                        "longest_rush": 15,
                    }
                )
    return rows


def test_first_td_is_exclusive(history, line, now):
    sim = Simulator(enriched(history), now, count=5000, seed=11)
    samples = []
    for team in ("JAX", "HOU"):
        for player in ("player1", "player2"):
            candidate = line.model_copy(
                update={
                    "market": Market.FIRST_TD,
                    "player_id": player + team,
                    "team": team,
                    "opponent": "HOU" if team == "JAX" else "JAX",
                }
            )
            values, _, _ = sim.samples(candidate)
            assert values is not None
            samples.append(values)
    assert np.all(np.sum(samples, axis=0) <= 1)
    assert 0.01 < np.mean(samples[0]) < 0.5


def test_anytime_and_first_consistent(history, line, now):
    sim = Simulator(enriched(history), now, count=2000, seed=12)
    td = line.model_copy(update={"market": Market.ANYTIME_TD, "player_id": "player1JAX"})
    first = td.model_copy(update={"market": Market.FIRST_TD})
    anytime = sim.samples(td)[0]
    first_samples = sim.samples(first)[0]
    assert np.all(anytime[first_samples == 1] >= 1)


def test_longest_requires_pbp(history, line, now):
    longest = line.model_copy(update={"market": Market.LONG_REC})
    assert Simulator(history, now).samples(longest)[0] is None
