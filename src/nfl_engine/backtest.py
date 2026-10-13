"""Chronological calibration/evaluation on statistical thresholds, never historical EV."""

from datetime import UTC, datetime

import numpy as np
from sklearn.linear_model import LogisticRegression

from .history import binary_metrics
from .model import SUPPORTED, Simulator, actual, player_rows, predict
from .schemas import Line
from .storage import digest, immutable, write_json


def run_backtest(root, history, games, config, maximum=1200):
    # Fixed past season is selected dynamically from completed seasons before the present one.
    by_id = {g.event_id: g for g in games}
    observations = sorted([r for r in history if r["event_id"] in by_id], key=lambda r: r["kickoff"])
    recent_season = max(r["season"] for r in observations if r["season"] < datetime.now(UTC).year)
    observations = [r for r in observations if r["season"] == recent_season and r.get("week", 0) >= 6]
    selected = []
    for market in sorted(SUPPORTED):
        count = 0
        seen = set()
        for row in observations:
            value = actual(row, market)
            if value is None or row.get("position") not in ("QB", "RB", "WR", "TE"):
                continue
            group = (row["week"], row["position"])
            if group in seen:
                continue
            cutoff = datetime.fromisoformat(row["kickoff"])
            rows = player_rows(history, row["player_id"], cutoff)
            values = [actual(r, market) for r in rows]
            values = [v for v in values if v is not None]
            binary = market in ("anytime_touchdown", "first_touchdown")
            if len(values) < config["minimum_sample"] or (not binary and np.median(values) <= 0):
                continue
            seen.add(group)
            threshold = 0.5 if binary else float(np.floor(np.median(values)) + 0.5)
            game = by_id[row["event_id"]]
            sample_line = Line(
                line_id=digest([row["event_id"], row["player_id"], market])[:24],
                provider="underdog",
                provider_market_id="statistical-threshold-not-provider-line",
                event_id=game.event_id,
                player_id=row["player_id"],
                player_name=row.get("player_display_name", row.get("player_name", "")),
                team=row["team"],
                opponent=row["opponent"],
                market=market,
                threshold=threshold,
                direction="over",
                display_line=f"Statistical test threshold {threshold}",
                collected_at=cutoff,
                raw_source_hash="historical-statistical-test",
            )
            sim = Simulator(history, cutoff, count=1500, seed=count + 71)
            pred, _ = predict(sample_line, sim, cutoff, config)
            selected.append(
                {
                    "market": str(market),
                    "kickoff": row["kickoff"],
                    "probability": pred.probability,
                    "result": "win" if value > threshold else "loss",
                    "threshold": threshold,
                    "event_id": game.event_id,
                    "player_id": row["player_id"],
                }
            )
            count += 1
            if count >= maximum // len(SUPPORTED):
                break
    selected.sort(key=lambda r: r["kickoff"])
    split = sorted({r["kickoff"][:10] for r in selected})
    boundary = split[max(0, int(len(split) * 0.6) - 1)] if split else ""
    fit = [r for r in selected if r["kickoff"][:10] <= boundary]
    evaluation = [r.copy() for r in selected if r["kickoff"][:10] > boundary]
    coefficients = {}
    for market in sorted(SUPPORTED):
        if market == "first_touchdown":
            continue
        rows = [r for r in fit if r["market"] == market]
        if len(rows) < 20 or len({r["result"] for r in rows}) < 2:
            continue
        p = np.clip([r["probability"] for r in rows], 0.001, 0.999)
        model = LogisticRegression(C=0.5).fit(
            np.log(p / (1 - p)).reshape(-1, 1), [r["result"] == "win" for r in rows]
        )
        if model.coef_[0, 0] <= 0:
            continue  # A reversed calibration is evidence to abstain, not ship it.
        coefficients[str(market)] = [float(model.coef_[0, 0]), float(model.intercept_[0])]
    from .model import calibrate

    for row in evaluation:
        row["probability"] = calibrate(row["probability"], row["market"], {"calibration": coefficients})
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "source": "nflreadpy player game stats",
        "line_provenance": "Prior-only median + 0.5 statistical thresholds; no historical provider lines or EV.",
        "fit_count": len(fit),
        "evaluation_count": len(evaluation),
        "calibration_cutoff": boundary,
        "overall": binary_metrics(evaluation),
        "markets": {
            str(m): binary_metrics([r for r in evaluation if r["market"] == m]) for m in sorted(SUPPORTED)
        },
        "records": evaluation,
    }
    write_json(root / "site/data/backtest.json", report)
    future = [g for g in games if g.kickoff > datetime.now(UTC)]
    season = min(future, key=lambda g: g.kickoff).season if future else recent_season + 1
    week = min(future, key=lambda g: g.kickoff).week if future else 1
    registry = {
        "model_version": f"research-{season}.{week}.1",
        "created_at": report["created_at"],
        "trained_through": boundary,
        "training_data_hash": digest(history),
        "feature_schema_hash": digest(sorted(SUPPORTED)),
        "calibration": coefficients,
        "validation": report["markets"],
        "production_validated": False,
        "limitations": [
            "statistical thresholds are not provider-line validation",
            "joint probabilities require empirical dependency validation",
            "selection favors players with sufficient positive usage",
        ],
    }
    registry_path = root / f"data/model_registry/{season}/week-{week:02}.json"
    if not registry_path.exists():
        immutable(registry_path, registry)
    return report
