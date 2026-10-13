# Line Watcher model card

Research only; `production_validated` remains false and official high-confidence ticket recommendations are withheld. No automatic wagering.

## Current fitted model

`distribution-2026.6.2` replaces numeric probability calculations with 11 quantile gradient-boosting regressors per supported market, separately calibrated on later games. Features include causal prior workload, recency, variability, trend, position and opponent positional allowances. At least eight previous games are required. Passing yards/TD use QB models, receiving/receptions/targets exclude QBs, rushing/carries support QB/RB, and combined yards supports the represented eligible positions. Unsupported numeric domains abstain. Legacy empirical simulations still supply descriptive summaries; those means/medians are not the fitted forecast.

Train before November 2025, calibrate before August 2026, test completed 2026 games. Quantile crossing is corrected monotonically; over/under use the same calibrated CDF with push mass for integer thresholds. Weights/calibration are frozen per registered week; features can incorporate newly available prior results. Serialized artifacts are checksum-verified, never downloaded from untrusted user input and never included in Pages. Repeated weekly training reuses the immutable artifact.

Selected generated thresholds reached 80–86% hit rates at predicted probability ≥75%, with 21–31% coverage. This is not 75% accuracy on all lines, actual provider-line accuracy or profitable betting. One-per-player-game intervals are approximate and do not account for all clustering; passing yards currently fails the default lower-interval ≥75% gate. Active-stat-row/DNP bias, few seasons, tail support, roster/role changes and missing injury/weather information remain material limitations. See [RESEARCH.md](RESEARCH.md) for market counts, loss scores, caveats and sources; machine-readable results are in `site/data/model_evaluation.json`.

## Dependence and experiments

Calibration-period percentile residuals estimate Gaussian-copula dependencies by market/position and team/player relation. Correlations are shrunk and projected to a positive-semidefinite matrix. Same-player alternative lines share a percentile; distinct games are assumed independent. The copula is an approximation and joint hit rates are not independently validated. Monte Carlo intervals represent simulation error, not total predictive uncertainty.

Anytime/first-touchdown and longest-play models retain experimental play-by-play opportunity logic and need separate validation. First-touchdown outcomes compete for one first scorer and are excluded from all combinations. Experimental touchdown outcomes are excluded from default individual rankings. Data quality is a sample/coverage measure, never the outcome's probability.

## Economics and records

Best value and Safest require fresh sufficiently supported probabilities and worthwhile quoted returns after known fees, plus a five-percentage-point probability sensitivity check. Exact complete-ticket eligibility and payout are required for parlay value; independent single-leg quotes and indicative DFS odds cannot establish them. Current groups with unknown payout are research only. Three independent 75% legs have about 42% joint chance, not 75%.

Only recorded pregame observations enter official paper history. Final NFL stats grade original thresholds; missing stats stay pending and unknown settlement rules do not become invented ROI. Original forecasts and results remain separate immutable records. Earlier r1/r2/r3 and fitted v1 registries are preserved for provenance, not silently rewritten. Full readiness needs successive prospective provider-line validation and real payout/settlement evidence.
