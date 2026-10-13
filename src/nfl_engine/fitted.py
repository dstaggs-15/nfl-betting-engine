"""Chronological distribution fitting: train, calibrate, then evaluate on later games."""

import bisect
import hashlib
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from threadpoolctl import threadpool_limits

from .history import binary_metrics
from .model import actual
from .schemas import Market
from .storage import immutable, read_json, write_json

logger = logging.getLogger(__name__)
QUANTILES = np.array([0.01, 0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95, 0.99])
MARKETS = [
    Market.PASSING,
    Market.RECEIVING,
    Market.RUSHING,
    Market.SCRIMMAGE,
    Market.RECEPTIONS,
    Market.CARRIES,
    Market.TARGETS,
    Market.PASS_TD,
]
FIELDS = [
    "attempts",
    "completions",
    "targets",
    "receptions",
    "carries",
    "passing_yards",
    "receiving_yards",
    "rushing_yards",
    "passing_tds",
    "redzone_targets",
    "redzone_carries",
]
POSITIONS = ["QB", "RB", "WR", "TE"]


class Features:
    def __init__(self, history):
        self.players = defaultdict(list)
        self.defense = defaultdict(list)
        for row in sorted(history, key=lambda r: r["available_at"]):
            self.players[row["player_id"]].append(row)
            self.defense[(row["opponent"], row.get("position"))].append(row)
        self.times = {key: [r["available_at"] for r in rows] for key, rows in self.players.items()}
        self.def_times = {key: [r["available_at"] for r in rows] for key, rows in self.defense.items()}

    def build(self, player, opponent, cutoff):
        cutoff = cutoff.isoformat()
        all_rows = self.players.get(player, [])
        index = bisect.bisect_left(self.times.get(player, []), cutoff)
        rows = all_rows[max(0, index - 24) : index]
        if len(rows) < 8:
            return None, rows
        position = rows[-1].get("position")
        if position not in POSITIONS:
            return None, rows
        features = [float(position == p) for p in POSITIONS]
        features += [
            len(rows),
            min(90, (datetime.fromisoformat(cutoff) - datetime.fromisoformat(rows[-1]["kickoff"])).days),
        ]
        for field in FIELDS:
            values = np.array([float(r.get(field, 0) or 0) for r in rows])
            features.extend(
                [
                    float(np.mean(values[-4:])),
                    float(np.mean(values[-8:])),
                    float(np.median(values)),
                    float(np.std(values)),
                    float(np.mean(values[-4:]) - np.mean(values[-12:])),
                ]
            )
        key = (opponent, position)
        stop = bisect.bisect_left(self.def_times.get(key, []), cutoff)
        defenders = self.defense.get(key, [])[:stop][-120:]
        for market in MARKETS:
            vals = [actual(r, market) for r in defenders]
            vals = [v for v in vals if v is not None]
            features.append(float(np.mean(vals)) if vals else 0)
        return np.array(features, dtype=np.float64), rows


def cdf_at(threshold, quantiles):
    """CDF interpolation with explicit tails; zero outcomes retain a zero atom."""
    values = np.maximum.accumulate(np.maximum(0, np.asarray(quantiles)))
    unique = np.unique(values)
    probabilities = np.array([QUANTILES[values == v][-1] for v in unique])
    if threshold < 0:
        return 0.0
    if threshold < unique[0]:
        return float(QUANTILES[0] * threshold / unique[0]) if unique[0] else 0.0
    if threshold >= unique[-1]:
        return float(min(0.999, probabilities[-1] + 0.01 * (threshold - unique[-1]) / (unique[-1] + 1)))
    return float(np.interp(threshold, unique, probabilities))


def wilson(wins, count):
    if not count:
        return None
    z = 1.96
    p = wins / count
    denominator = 1 + z * z / count
    midpoint = (p + z * z / (2 * count)) / denominator
    delta = z * np.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [float(midpoint - delta), float(midpoint + delta)]


def train(root: Path, history, games):
    future = sorted([g for g in games if g.kickoff > datetime.now(UTC)], key=lambda g: g.kickoff)
    if future:
        registered = (
            root / f"data/model_registry/{future[0].season}/week-{future[0].week:02}-distribution-v2.json"
        )
        if registered.exists():
            metadata = read_json(registered)
            artifact = root / metadata["artifact"]
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != metadata["artifact_sha256"]:
                raise ValueError("Registered model artifact checksum mismatch")
            report = read_json(root / "site/data/model_evaluation.json", {})
            if report.get("version") != metadata["model_version"]:
                report = {
                    "version": metadata["model_version"],
                    "markets": metadata["validation"],
                    "scope": "Prior-data statistical thresholds, not historical provider quotes.",
                }
                write_json(root / "site/data/model_evaluation.json", report)
            return report
    engine = Features(history)
    completed_season = max(r["season"] for r in history if r["season"] < datetime.now(UTC).year)
    # The final test period is untouched by fitting or calibration.
    evaluation_season = max(r["season"] for r in history)
    fit_end = f"{completed_season}-11-01"
    calibration_end = f"{evaluation_season}-08-01"
    rows = []
    for row in history:
        if row.get("position") not in POSITIONS:
            continue
        cutoff = datetime.fromisoformat(row["kickoff"])
        features, prior = engine.build(row["player_id"], row["opponent"], cutoff)
        if features is None:
            continue
        # Select participation/usage based only on prior games, never current result.
        recent = prior[-4:]
        usage = sum(
            sum(float(r.get(k, 0) or 0) for k in ["attempts", "targets", "carries"]) for r in recent
        ) / len(recent)
        if usage < 3:
            continue
        period = (
            "fit"
            if row["kickoff"][:10] < fit_end
            else "calibrate"
            if row["kickoff"][:10] < calibration_end
            else "test"
        )
        if row["season"] > evaluation_season:
            continue
        rows.append((row, features, prior, period))
    models, calibrators, residuals, reports = {}, {}, {}, {}
    with threadpool_limits(limits=4):
        for market in MARKETS:
            subset = []
            for row, features, prior, period in rows:
                y = actual(row, market)
                if y is None:
                    continue
                position = prior[-1].get("position")
                if market in (Market.PASSING, Market.PASS_TD) and position != "QB":
                    continue
                if market in (Market.RECEIVING, Market.RECEPTIONS, Market.TARGETS) and position == "QB":
                    continue
                if market in (Market.RUSHING, Market.CARRIES) and position not in ("QB", "RB"):
                    continue
                subset.append((row, features, prior, period, max(0, y)))
            training = [r for r in subset if r[3] == "fit"]
            calibration = [r for r in subset if r[3] == "calibrate"]
            testing = [r for r in subset if r[3] == "test"]
            if len(training) < 150 or len(calibration) < 80 or len(testing) < 80:
                continue
            X = np.array([r[1] for r in training])
            y = np.array([r[4] for r in training])
            fitted = []
            for q in QUANTILES:
                estimator = HistGradientBoostingRegressor(
                    loss="quantile",
                    quantile=float(q),
                    max_iter=80,
                    max_leaf_nodes=15,
                    min_samples_leaf=35,
                    l2_regularization=3,
                    learning_rate=0.07,
                    early_stopping=False,
                    random_state=12,
                )
                estimator.fit(X, y)
                fitted.append(estimator)
            models[str(market)] = fitted

            def evaluate(cases):
                estimates = np.array([m.predict(np.array([r[1] for r in cases])) for m in fitted]).T
                points = []
                for item, quantiles in zip(cases, estimates):
                    row, _, prior, _, value = item
                    previous = [actual(r, market) for r in prior]
                    previous = [v for v in previous if v is not None]
                    if len(previous) < 8:
                        continue
                    # A broad threshold range, not median-only fitting. Both sides count.
                    thresholds = sorted(
                        {float(np.floor(np.quantile(previous, q)) + 0.5) for q in [0.1, 0.25, 0.5, 0.75, 0.9]}
                    )
                    for threshold in thresholds:
                        raw = cdf_at(threshold, quantiles)
                        points.append(
                            {
                                "probability": raw,
                                "result": "win" if value < threshold else "loss",
                                "event_id": row["event_id"],
                                "player_id": row["player_id"],
                                "threshold": threshold,
                                "direction": "under",
                            }
                        )
                    residuals.setdefault(str(market), []).append(
                        {
                            "event_id": row["event_id"],
                            "player_id": row["player_id"],
                            "team": row["team"],
                            "position": row.get("position"),
                            "pit": cdf_at(value, quantiles),
                        }
                    )
                return points

            fit_points = evaluate(calibration)
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
            iso.fit([r["probability"] for r in fit_points], [r["result"] == "win" for r in fit_points])
            calibrators[str(market)] = iso
            before = len(residuals.get(str(market), []))
            evaluation = evaluate(testing)
            # Holdout residuals are not used to fit dependencies.
            residuals[str(market)] = residuals[str(market)][:before]
            points = []
            for r in evaluation:
                p = float(iso.predict([r["probability"]])[0])
                points.append({**r, "probability": p})
                points.append(
                    {
                        **r,
                        "direction": "over",
                        "probability": 1 - p,
                        "result": "loss" if r["result"] == "win" else "win",
                    }
                )
            selected = [p for p in points if p["probability"] >= 0.75]
            selected_metrics = binary_metrics(selected)
            # Cluster-level statistics supplement line-level counts (alternates are dependent).
            one_per_game = {}
            for p in selected:
                one_per_game.setdefault((p["event_id"], p["player_id"]), p)
            unique_metrics = binary_metrics(list(one_per_game.values()))
            reports[str(market)] = {
                "all": binary_metrics(points),
                "target_75": selected_metrics,
                "unique_player_games": unique_metrics,
                "hit_rate_interval": wilson(unique_metrics["wins"], unique_metrics["count"]),
                "coverage": len(selected) / len(points) if points else 0,
                "fit_games": len(training),
                "calibration_games": len(calibration),
                "test_games": len(testing),
            }
            logger.info(
                "fitted market=%s train=%s calibration=%s test=%s selected75=%s hit_rate=%s",
                market,
                len(training),
                len(calibration),
                len(testing),
                len(selected),
                selected_metrics["hit_rate"],
            )
    future = sorted([g for g in games if g.kickoff > datetime.now(UTC)], key=lambda g: g.kickoff)
    season, week = (future[0].season, future[0].week) if future else (completed_season + 1, 1)
    version = f"distribution-{season}.{week}.2"
    folder = root / f"data/model_registry/{season}"
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / f"week-{week:02}-distribution-v2.joblib"
    if artifact.exists():
        raise FileExistsError(
            "A fitted weekly artifact already exists; create an explicit new model revision."
        )
    joblib.dump({"models": models, "calibrators": calibrators, "residuals": residuals}, artifact, compress=3)
    report = {
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "train_before": fit_end,
        "calibration_before": calibration_end,
        "evaluation_after": calibration_end,
        "evaluation_season": evaluation_season,
        "markets": reports,
        "scope": "Statistical thresholds from prior outcomes, not historical provider quotes; no historical EV claims.",
        "caveats": [
            "Active-stat-row selection omits some DNPs",
            "Alternates are correlated; unique player-game counts shown",
            "75% is selective accuracy, not accuracy for all offered lines",
            "Provider-line prospective validation required",
        ],
    }
    metadata = {
        "model_version": version,
        "created_at": report["generated_at"],
        "trained_through": calibration_end,
        "artifact": str(artifact.relative_to(root)),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "validation": reports,
        "production_validated": False,
        "fitted_distribution": True,
    }
    immutable(folder / f"week-{week:02}-distribution-v2.json", metadata)
    write_json(root / "site/data/model_evaluation.json", report)
    return report


class FittedSimulator:
    def __init__(self, history, cutoff, root, registry, count=20000, seed=17):
        path = root / registry["artifact"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != registry["artifact_sha256"]:
            raise ValueError("Model artifact checksum mismatch")
        self.bundle = joblib.load(path)
        self.engine = Features(history)
        self.cutoff = cutoff
        self.count = count
        self.rng = np.random.default_rng(seed)
        self.cache = {}
        self.uniforms = {}
        self.correlation_cache = {}
        self.positions = {}
        self.history = history
        self.registry = registry

    def probability(self, line):
        key = (line.event_id, line.player_id, str(line.market))
        features, rows = self.engine.build(line.player_id, line.opponent, self.cutoff)
        fitted = self.bundle["models"].get(str(line.market))
        if rows:
            self.positions[line.player_id] = rows[-1].get("position")
        if features is None or not fitted:
            return None, rows
        position = rows[-1].get("position")
        if line.market in (Market.PASSING, Market.PASS_TD) and position != "QB":
            return None, rows
        if line.market in (Market.RECEIVING, Market.RECEPTIONS, Market.TARGETS) and position == "QB":
            return None, rows
        if line.market in (Market.RUSHING, Market.CARRIES) and position not in ("RB", "QB"):
            return None, rows
        if key not in self.cache:
            with threadpool_limits(limits=4):
                self.cache[key] = np.array([m.predict(features.reshape(1, -1))[0] for m in fitted])
        # NFL count/yard totals are integer-valued. At an integer line the
        # interval [L-.5,L+.5] is push mass, not a winning under or over.
        boundary = line.threshold
        if line.threshold.is_integer():
            boundary += -0.5 if line.direction == "under" else 0.5
        cdf = cdf_at(boundary, self.cache[key])
        p = float(self.bundle["calibrators"][str(line.market)].predict([cdf])[0])
        return p if line.direction == "under" else 1 - p, rows

    def masks(self, predictions):
        # Empirical Gaussian copula: fit dependencies from prior calibration-period PITs.
        groups = defaultdict(list)
        for p in predictions:
            groups[p.line.event_id].append(p)
        masks = {}
        for event, legs in groups.items():
            variables = list(dict.fromkeys((p.line.player_id, str(p.line.market)) for p in legs))
            representatives = {
                key: next(p for p in legs if (p.line.player_id, str(p.line.market)) == key)
                for key in variables
            }
            residuals = self.bundle["residuals"]
            correlation = np.eye(len(variables))
            for i, a in enumerate(variables):
                for j in range(i):
                    b = variables[j]
                    left = representatives[a].line
                    right = representatives[b].line
                    ra = residuals.get(a[1], [])
                    rb = residuals.get(b[1], [])
                    same_team = left.team == right.team
                    same_player = left.player_id == right.player_id
                    matched = []
                    index = defaultdict(list)
                    for row in rb:
                        index[row["event_id"]].append(row)
                    pos_a = self.positions.get(left.player_id)
                    pos_b = self.positions.get(right.player_id)
                    cache_key = (a[1], b[1], pos_a, pos_b, same_team, same_player)
                    if cache_key in self.correlation_cache:
                        correlation[i, j] = correlation[j, i] = self.correlation_cache[cache_key]
                        continue
                    for row in ra:
                        if row["position"] != pos_a:
                            continue
                        for other in index[row["event_id"]]:
                            if other["position"] != pos_b:
                                continue
                            if (row["team"] == other["team"]) != same_team:
                                continue
                            if (row["player_id"] == other["player_id"]) != same_player:
                                continue
                            matched.append((row["pit"], other["pit"]))
                    if len(matched) >= 40:
                        ranks = norm.ppf(np.clip(np.array(matched), 0.01, 0.99))
                        value = float(np.corrcoef(ranks.T)[0, 1])
                        if np.isfinite(value):
                            correlation[i, j] = correlation[j, i] = (
                                np.clip(value, -0.8, 0.8) * len(matched) / (len(matched) + 100)
                            )
                    self.correlation_cache[cache_key] = float(correlation[i, j])
            eig, vec = np.linalg.eigh(correlation)
            correlation = (vec * np.maximum(eig, 0.001)) @ vec.T
            scale = np.sqrt(np.diag(correlation))
            correlation /= np.outer(scale, scale)
            uniforms = norm.cdf(
                self.rng.multivariate_normal(np.zeros(len(variables)), correlation, size=self.count)
            )
            lookup = {key: i for i, key in enumerate(variables)}
            for p in legs:
                u = uniforms[:, lookup[(p.line.player_id, str(p.line.market))]]
                masks[p.prediction_id] = (
                    u < p.probability if p.line.direction == "under" else u >= 1 - p.probability
                )
        return masks
