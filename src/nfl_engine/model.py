"""Time-causal workload research model; unsupported opportunity markets abstain."""

from datetime import datetime

import numpy as np
from scipy.special import expit

from .schemas import Market, Prediction
from .storage import digest

COLUMNS = {
    Market.RECEPTIONS: "receptions",
    Market.RECEIVING: "receiving_yards",
    Market.RUSHING: "rushing_yards",
    Market.PASSING: "passing_yards",
    Market.PASS_TD: "passing_tds",
    Market.CARRIES: "carries",
    Market.TARGETS: "targets",
    Market.LONG_REC: "longest_reception",
    Market.LONG_RUSH: "longest_rush",
    Market.FIRST_TD: "first_touchdown",
}
SUPPORTED = {
    Market.RECEPTIONS,
    Market.RECEIVING,
    Market.RUSHING,
    Market.SCRIMMAGE,
    Market.PASSING,
    Market.CARRIES,
    Market.TARGETS,
    Market.ANYTIME_TD,
    Market.FIRST_TD,
    Market.PASS_TD,
    Market.LONG_REC,
    Market.LONG_RUSH,
}


def actual(row, market):
    if market == Market.SCRIMMAGE:
        return float(row.get("rushing_yards", 0) or 0) + float(row.get("receiving_yards", 0) or 0)
    if market == Market.ANYTIME_TD:
        return sum(float(row.get(k, 0) or 0) for k in ("rushing_tds", "receiving_tds", "special_teams_tds"))
    column = COLUMNS.get(market)
    return float(row[column]) if column and row.get(column) is not None else None


def prior_rows(history, cutoff):
    return [r for r in history if datetime.fromisoformat(r["available_at"]) < cutoff]


def player_rows(history, player_id, cutoff):
    return sorted(
        [r for r in prior_rows(history, cutoff) if r["player_id"] == player_id], key=lambda r: r["kickoff"]
    )[-24:]


def opponent_factor(history, rows, line, cutoff):
    column = COLUMNS.get(line.market)
    if column is None or not rows:
        return 1.0
    position = rows[-1].get("position")
    # Compare per-game allowance to players in the same position; shrink toward league baseline.
    totals = {}
    for r in prior_rows(history, cutoff):
        if r.get("position") != position or r.get(column) is None:
            continue
        totals[(r["event_id"], r["opponent"])] = totals.get((r["event_id"], r["opponent"]), 0) + r[column]
    league = list(totals.values())
    opponent = [v for (_, team), v in totals.items() if team == line.opponent][-16:]
    if not opponent or not league or np.mean(league) <= 0:
        return 1.0
    ratio = np.mean(opponent) / np.mean(league)
    return float(np.clip(1 + (ratio - 1) * len(opponent) / (len(opponent) + 12), 0.8, 1.2))


class Simulator:
    """All legs of a game share pace/script draws; a player's markets share workloads."""

    def __init__(self, history, cutoff, count=20000, seed=17):
        self.history, self.cutoff, self.count = prior_rows(history, cutoff), cutoff, count
        self.row_cache, self.factor_cache = {}, {}
        self.rng = np.random.default_rng(seed)
        self.games, self.players = {}, {}
        from .touchdowns import Touchdowns

        self.touchdowns = Touchdowns(history, cutoff, self.rng, count, self.games)

    def samples(self, line):
        if line.player_id not in self.row_cache:
            self.row_cache[line.player_id] = player_rows(self.history, line.player_id, self.cutoff)
        rows = self.row_cache[line.player_id]
        if not rows or line.market not in SUPPORTED:
            return None, rows, 1.0
        event = self.games.get(line.event_id)
        if event is None:
            event = (self.rng.normal(0, 1, self.count), self.rng.normal(0, 1, self.count))
            self.games[line.event_id] = event
        if line.market in (Market.ANYTIME_TD, Market.FIRST_TD, Market.PASS_TD):
            return self.touchdowns.simulate(line), rows, 1.0
        if line.market in (Market.LONG_REC, Market.LONG_RUSH):
            column = COLUMNS[line.market]
            if not all(r.get("opportunities_available") for r in rows):
                return None, rows, 1.0
            values = np.array([r.get(column, 0) for r in rows], dtype=float)
            return self.rng.choice(values, self.count), rows, 1.0
        cache_key = (line.event_id, line.player_id)
        if cache_key not in self.players:
            n = len(rows)
            weights = np.exp(np.linspace(-1.8, 0, n))
            weights /= weights.sum()
            indices = self.rng.choice(n, self.count, p=weights)

            def field(name):
                return np.array([float(r.get(name, 0) or 0) for r in rows])[indices]

            pace, script = event
            side = 1 if line.team < line.opponent else -1
            pass_environment = np.exp(0.10 * pace + 0.12 * side * script - 0.0122)
            rush_environment = np.exp(0.10 * pace - 0.12 * side * script - 0.0122)
            target_base = field("targets")
            carry_base = field("carries")
            attempt_base = field("attempts")
            targets = self.rng.poisson(np.maximum(0, target_base * pass_environment))
            carries = self.rng.poisson(np.maximum(0, carry_base * rush_environment))
            attempts = self.rng.poisson(np.maximum(0, attempt_base * pass_environment))
            total_targets = sum(float(r.get("targets", 0) or 0) for r in rows)
            total_catches = sum(float(r.get("receptions", 0) or 0) for r in rows)
            catch_rate = self.rng.beta(
                2 + total_catches, 2 + max(0, total_targets - total_catches), self.count
            )
            receptions = self.rng.binomial(targets, catch_rate)
            total_attempts = sum(float(r.get("attempts", 0) or 0) for r in rows)
            total_completions = sum(float(r.get("completions", 0) or 0) for r in rows)
            completions = self.rng.binomial(
                attempts,
                self.rng.beta(
                    2 + total_completions, 2 + max(0, total_attempts - total_completions), self.count
                ),
            )

            def yards(volume, yards_column, volume_column):
                efficiency = np.divide(
                    field(yards_column),
                    field(volume_column),
                    out=np.zeros(self.count),
                    where=field(volume_column) > 0,
                )
                # Compound gamma retains an explosive tail and workload dependence.
                return self.rng.gamma(np.maximum(0.001, volume * 2), np.maximum(0, efficiency) / 2) * (
                    volume > 0
                )

            receiving = yards(receptions, "receiving_yards", "receptions")
            rushing = yards(carries, "rushing_yards", "carries")
            passing = yards(completions, "passing_yards", "completions")
            self.players[cache_key] = {
                Market.RECEPTIONS: receptions,
                Market.RECEIVING: receiving,
                Market.RUSHING: rushing,
                Market.SCRIMMAGE: rushing + receiving,
                Market.PASSING: passing,
                Market.CARRIES: carries,
                Market.TARGETS: targets,
            }
        factor_key = (line.market, line.opponent, rows[-1].get("position"))
        if factor_key not in self.factor_cache:
            self.factor_cache[factor_key] = opponent_factor(self.history, rows, line, self.cutoff)
        factor = self.factor_cache[factor_key]
        values = self.players[cache_key][line.market] * factor
        if line.market in (Market.RECEPTIONS, Market.CARRIES, Market.TARGETS):
            values = np.floor(values)
        return values, rows, factor


def calibration_supported(p, market, registry):
    coefficients = (registry or {}).get("calibration", {}).get(str(market))
    support = (registry or {}).get("calibration_support", {}).get(str(market))
    return bool(coefficients and support and support[0] <= p <= support[1])


def calibrate(p, market, registry):
    if not calibration_supported(p, market, registry):
        return p
    coefficients = registry["calibration"][str(market)]
    bounded = float(np.clip(p, 1e-9, 1 - 1e-9))
    return float(expit(coefficients[0] * np.log(bounded / (1 - bounded)) + coefficients[1]))


def predict(line, simulator, now, config, registry=None):
    samples, rows, factor = simulator.samples(line)
    values = [actual(r, line.market) for r in rows]
    values = [v for v in values if v is not None]
    stale = (now - line.collected_at).total_seconds() > config["freshness_seconds"] or not line.available
    insufficient = samples is None or len(rows) < config["minimum_sample"]
    push_mass = float(np.mean(samples == line.threshold)) if samples is not None else 0.0
    raw_over = float(np.mean(samples > line.threshold)) if samples is not None else 0.5
    conditional_over = raw_over / (1 - push_mass) if push_mass < 1 else 0.0
    calibrated = line.market != Market.FIRST_TD and calibration_supported(
        conditional_over, line.market, registry
    )
    over = calibrate(conditional_over, line.market, registry) * (1 - push_mass) if calibrated else raw_over
    p = over if line.direction == "over" else max(0.0, 1 - push_mass - over)
    confidence = min(0.85, len(rows) / (len(rows) + 8))
    risks = ["RESEARCH_MODEL", "INJURY_CONTEXT_UNAVAILABLE", "HEURISTIC_GAME_FACTORS"]
    if not calibrated:
        risks.append("UNCALIBRATED_MARKET")
    if line.market == Market.FIRST_TD:
        risks.append("FIRST_TD_NOT_VALIDATED_FOR_RANKING")
        confidence = min(confidence, 0.5)
    if values and sum(max(0, v) for v in values) > 0 and max(values) / sum(max(0, v) for v in values) > 0.3:
        risks.append("OUTLIER_CONCENTRATION")
        confidence *= 0.8
    if insufficient:
        risks.append("INSUFFICIENT_SAMPLE_OR_OPPORTUNITY_DATA")
    status = "STALE_LINE" if stale else "INSUFFICIENT_DATA" if insufficient else "WATCH"
    # Unvalidated models never publish high-confidence official recommendations.
    if not stale and not insufficient and confidence >= config["minimum_confidence"] and p >= 0.6:
        if registry and registry.get("production_validated"):
            status = "RECOMMENDED"

    def hit(v):
        return v > line.threshold if line.direction == "over" else v < line.threshold

    prediction = Prediction(
        prediction_id=digest([line.model_dump(mode="json"), config["model_version"]])[:24],
        line=line,
        probability=p,
        confidence=confidence,
        sample_size=len(rows),
        mean=float(np.mean(values)) if values else 0,
        median=float(np.median(values)) if values else 0,
        recent_hit_rate=float(np.mean([hit(v) for v in values[-5:]])) if values else 0,
        historical_hit_rate=float(np.mean([hit(v) for v in values])) if values else 0,
        opponent_factor=factor,
        status=status,
        reason_codes=["TIME_CAUSAL_INPUTS", "WORKLOAD_DISTRIBUTION"],
        risk_codes=risks,
        model_version=config["model_version"],
    )
    mask = None
    if samples is not None:
        # Rank-coupled calibrated probabilities preserve shared sample dependence.
        if not calibrated:
            mask = samples > line.threshold if line.direction == "over" else samples < line.threshold
            return prediction, mask
        ranks = np.argsort(np.argsort(samples, kind="stable"), kind="stable") / len(samples)
        mask = ranks >= (1 - p) if line.direction == "over" else ranks < p
    return prediction, mask
