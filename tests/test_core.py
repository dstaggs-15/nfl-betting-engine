from datetime import timedelta

import numpy as np
import pytest
from pydantic import ValidationError

from nfl_engine.history import (
    binary_metrics,
    grade_line,
    grade_snapshot,
    save_official,
    snapshot_path,
    tracker,
)
from nfl_engine.model import Simulator, player_rows, predict
from nfl_engine.normalize import Identity, market
from nfl_engine.optimizer import economics, joint_probability, optimize
from nfl_engine.scheduler import due_checkpoints, due_games
from nfl_engine.schemas import Market, Snapshot
from nfl_engine.storage import immutable


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Rush + Rec Yards", Market.SCRIMMAGE),
        ("Passing TDs", Market.PASS_TD),
        ("First TD", Market.FIRST_TD),
        ("Receptions", Market.RECEPTIONS),
    ],
)
def test_market(label, expected):
    assert market(label) == expected


def test_identity_ambiguity():
    players = [
        {"player_id": "a", "player_name": "John Smith", "team": "HOU"},
        {"player_id": "b", "player_name": "John Smith", "team": "HOU"},
        {"player_id": "c", "player_name": "John Smyth", "team": "JAX"},
    ]
    identity = Identity(players)
    assert identity.match("John Smith", "HOU") is None
    assert identity.match("John Smith", "JAX") is None
    assert identity.match("John Smyth", "JAX") == "c"


@pytest.mark.parametrize("multiplier,expected", [(3.08, 0.3246753247), (5.02, 0.1992031873)])
def test_economics(multiplier, expected):
    breakeven, ev = economics(0.4, multiplier)
    assert breakeven == pytest.approx(expected)
    assert ev == pytest.approx(0.4 * multiplier - 1)
    assert economics(0.4, None) == (None, None)


def test_same_game_joint_not_naive(prediction):
    second = prediction.model_copy(update={"prediction_id": "p2"})
    masks = {"p1": np.array([1, 1, 0, 0], bool), "p2": np.array([1, 1, 0, 0], bool)}
    assert joint_probability([prediction, second], masks) == 0.5
    assert 0.5 * 0.5 != 0.5
    other = second.model_copy(update={"line": second.line.model_copy(update={"event_id": "other"})})
    assert joint_probability([prediction, other], masks) == 0.25


def test_independent_fixture(prediction):
    second = prediction.model_copy(update={"prediction_id": "p2"})
    masks = {"p1": np.array([1, 1, 0, 0], bool), "p2": np.array([1, 0, 1, 0], bool)}
    assert joint_probability([prediction, second], masks) == 0.25


def test_eligibility_and_weakest(prediction):
    predictions = [
        prediction.model_copy(
            update={
                "prediction_id": f"p{i}",
                "probability": 0.8 - i * 0.05,
                "line": prediction.line.model_copy(update={"player_id": f"player{i}"}),
            }
        )
        for i in range(4)
    ]
    masks = {p.prediction_id: np.ones(100, bool) for p in predictions}
    for count in (3, 4):
        tickets = optimize(predictions, masks, count, True)
        assert tickets
        assert tickets[0].eligibility == "theoretical"
        assert tickets[0].multiplier is None
        selected = [p for p in predictions if p.prediction_id in tickets[0].legs]
        assert tickets[0].weakest_leg == min(selected, key=lambda p: p.probability).prediction_id
        assert not optimize(predictions, masks, count, False)
        assert not optimize(predictions, masks, count, True, official=True)


def test_time_causal(history, now, line):
    future = {**history[0], "available_at": (now + timedelta(days=1)).isoformat(), "passing_yards": 99999}
    assert future not in player_rows(history + [future], line.player_id, now)
    a = Simulator(history, now, count=1000, seed=3).samples(line)[0]
    b = Simulator(history + [future], now, count=1000, seed=3).samples(line)[0]
    np.testing.assert_array_equal(a, b)


def test_unsupported_abstains(history, now, line):
    td = line.model_copy(update={"market": Market.FIRST_TD})
    p, mask = predict(
        td,
        Simulator(history, now),
        now,
        {
            "freshness_seconds": 1800,
            "minimum_sample": 12,
            "minimum_confidence": 0.65,
            "model_version": "test",
        },
    )
    assert p.status == "INSUFFICIENT_DATA"
    assert mask is None


def test_stale_excluded(history, now, line):
    stale = line.model_copy(update={"collected_at": now - timedelta(hours=2)})
    p, mask = predict(
        stale,
        Simulator(history, now, count=1000),
        now,
        {
            "freshness_seconds": 1800,
            "minimum_sample": 12,
            "minimum_confidence": 0.65,
            "model_version": "test",
        },
    )
    assert p.status == "STALE_LINE"
    assert not optimize([p], {p.prediction_id: mask}, 2, True)


def test_immutable_atomic(tmp_path):
    path = tmp_path / "record.json"
    assert immutable(path, {"a": 1})
    assert not immutable(path, {"a": 1})
    with pytest.raises(FileExistsError):
        immutable(path, {"a": 2})
    assert path.read_text() == '{"a":1}'


def test_snapshot_idempotent_and_pregame(tmp_path, game, now, prediction):
    assert save_official(tmp_path, game, [prediction], [], now, "test")
    original = snapshot_path(tmp_path, game).read_bytes()
    assert not save_official(
        tmp_path, game, [prediction.model_copy(update={"probability": 0.1})], [], now, "test"
    )
    assert snapshot_path(tmp_path, game).read_bytes() == original
    with pytest.raises(ValueError):
        save_official(tmp_path, game.model_copy(update={"event_id": "other"}), [], [], game.kickoff, "test")
    snapshot = Snapshot.model_validate_json(original)
    assert snapshot.minutes_to_kickoff == 30


def test_grade_requires_final(tmp_path, game, now, prediction):
    save_official(tmp_path, game, [prediction], [], now, "test")
    snap = Snapshot.model_validate_json(snapshot_path(tmp_path, game).read_text())
    stats = [{"event_id": game.event_id, "player_id": "player1", "passing_yards": 300}]
    assert grade_snapshot(snap, {game.event_id: game}, stats, now) is None
    assert (
        grade_snapshot(snap, {game.event_id: game.model_copy(update={"status": "postponed"})}, stats, now)
        is None
    )
    final = game.model_copy(update={"status": "final"})
    assert grade_snapshot(snap, {game.event_id: final}, [], now) is None
    result = grade_snapshot(snap, {game.event_id: final}, stats, game.kickoff + timedelta(hours=4))
    assert result.legs[0].result == "win"
    assert result.legs[0].actual == 300
    immutable(tmp_path / f"data/results/2026/week-06/{snap.run_id}.json", result)
    report = tracker(tmp_path)
    assert report["metrics"]["count"] == 1
    assert report["metrics"]["brier"] == pytest.approx(0.0625)
    assert report["weekly"][0]["wins"] == 1
    assert report["paper"]["roi"] is None


def test_push_and_under(prediction):
    p = prediction.model_copy(update={"line": prediction.line.model_copy(update={"threshold": 250.0})})
    assert grade_line(p, {"passing_yards": 250}).result == "push"
    under = p.model_copy(update={"line": p.line.model_copy(update={"direction": "under"})})
    assert grade_line(under, {"passing_yards": 249}).result == "win"


def test_probabilities_metrics():
    metrics = binary_metrics(
        [
            {"probability": 0.8, "result": "win"},
            {"probability": 0.6, "result": "loss"},
            {"probability": 0.9, "result": "pending"},
        ]
    )
    assert metrics["count"] == 2
    assert metrics["brier"] == pytest.approx(0.2)
    assert metrics["log_loss"] == pytest.approx(-(0.5 * np.log(0.8) + 0.5 * np.log(0.4)))


def test_timezone_validation(line):
    raw = line.model_dump()
    raw["collected_at"] = line.collected_at.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        type(line).model_validate(raw)


def test_dispatcher(game, now):
    config = {"minimum_minutes_before_kickoff": 15, "window_before_minutes": 35}
    assert due_games([game], now, config) == [game]
    assert not due_games([game], game.kickoff, config)
    assert not due_games([game], now - timedelta(minutes=90), config)


def test_checkpoints_dst():
    from datetime import UTC, datetime

    config = {"timezone": "America/Chicago"}
    # 08:00 local is 13:00 UTC during daylight time and 14:00 during standard time.
    assert ("2026-10-09", "friday_morning") in due_checkpoints(
        datetime(2026, 10, 9, 13, 0, tzinfo=UTC), config
    )
    assert not due_checkpoints(datetime(2026, 12, 4, 13, 59, tzinfo=UTC), config)
    assert ("2026-12-04", "friday_morning") in due_checkpoints(
        datetime(2026, 12, 4, 14, 0, tzinfo=UTC), config
    )


def test_cross_game_requires_all_final(tmp_path, game, now, prediction):
    second_game = game.model_copy(
        update={
            "event_id": "2026_06_BAL_CLE",
            "home": "CLE",
            "away": "BAL",
            "kickoff": game.kickoff + timedelta(hours=4),
        }
    )
    second = prediction.model_copy(
        update={
            "prediction_id": "p2",
            "line": prediction.line.model_copy(
                update={
                    "event_id": second_game.event_id,
                    "player_id": "player2",
                    "team": "BAL",
                    "opponent": "CLE",
                }
            ),
        }
    )
    assert save_official(
        tmp_path, game, [prediction, second], [], now, "test", scope="slate", games=[game, second_game]
    )
    snap = Snapshot.model_validate_json(snapshot_path(tmp_path, game, "slate").read_text())
    stats = [
        {"event_id": game.event_id, "player_id": "player1", "passing_yards": 300},
        {"event_id": second_game.event_id, "player_id": "player2", "passing_yards": 200},
    ]
    games = {game.event_id: game.model_copy(update={"status": "final"}), second_game.event_id: second_game}
    assert grade_snapshot(snap, games, stats, second_game.kickoff) is None
    games[second_game.event_id] = second_game.model_copy(update={"status": "final"})
    results = grade_snapshot(snap, games, stats, second_game.kickoff + timedelta(hours=4))
    assert [g.result for g in results.legs] == ["win", "loss"]


def test_registry_selects_latest_revision(tmp_path, game, now):
    from nfl_engine.pipeline import registry_for
    from nfl_engine.storage import write_json

    write_json(
        tmp_path / "data/model_registry/2026/week-06.json",
        {"model_version": "r1", "created_at": now.isoformat()},
    )
    write_json(
        tmp_path / "data/model_registry/2026/week-06-r2.json",
        {"model_version": "r2", "created_at": (now + timedelta(seconds=1)).isoformat()},
    )
    assert registry_for(tmp_path, [game], now)["model_version"] == "r2"


def test_opposite_sides_and_pushes_remain_consistent(line, now, history):
    class Fixed:
        def samples(self, line):
            return np.array([200, 250, 300, 300], dtype=float), history, 1.0

    config = {
        "freshness_seconds": 1800,
        "minimum_sample": 12,
        "minimum_confidence": 0.65,
        "model_version": "test",
    }
    registry = {
        "calibration": {"passing_yards": [0.5, 0.4]},
        "calibration_support": {"passing_yards": [0.01, 0.99]},
    }
    over = line.model_copy(update={"threshold": 250.0})
    under = over.model_copy(update={"direction": "under"})
    a, _ = predict(over, Fixed(), now, config, registry)
    b, _ = predict(under, Fixed(), now, config, registry)
    assert a.probability + b.probability == pytest.approx(0.75)
    over = over.model_copy(update={"threshold": 249.5})
    under = over.model_copy(update={"direction": "under"})
    a, _ = predict(over, Fixed(), now, config, registry)
    b, _ = predict(under, Fixed(), now, config, registry)
    assert a.probability + b.probability == pytest.approx(1)


def test_calibration_does_not_extrapolate_into_tails():
    from nfl_engine.model import calibrate

    registry = {
        "calibration": {"receiving_yards": [0.1, -0.5]},
        "calibration_support": {"receiving_yards": [0.3, 0.6]},
    }
    assert calibrate(0.01, Market.RECEIVING, registry) == 0.01
    assert calibrate(0.99, Market.RECEIVING, registry) == 0.99
    assert calibrate(0.4, Market.RECEIVING, registry) != 0.4
    assert calibrate(0.4, Market.RECEIVING, {"calibration": registry["calibration"]}) == 0.4


def test_unvalidated_first_td_never_in_combinations(prediction):
    legs = [
        prediction.model_copy(
            update={
                "prediction_id": str(i),
                "status": "RECOMMENDED",
                "line": prediction.line.model_copy(update={"player_id": str(i), "market": Market.FIRST_TD}),
            }
        )
        for i in range(3)
    ]
    masks = {p.prediction_id: np.ones(100, bool) for p in legs}
    assert not optimize(legs, masks, 3, True)
    assert not optimize(legs, masks, 3, True, official=True)
