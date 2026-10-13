# Research model card

## Intended use and readiness

Exploratory NFL prop probability research and auditable paper forecasts. Not a promise of profit, a validated production prediction engine, or an automated betting system. Current registry artifacts have `production_validated: false`; high-confidence official recommendations remain withheld until model and provider economics have independent validation.

## Markets

Receptions/targets/carries use recency-weighted historical workload draws, Poisson overdispersed workload and beta-binomial catch uncertainty. Receiving/rushing/passing yards use shared volume and compound-gamma per-opportunity efficiency, retaining an explosive tail. Rush-plus-receiving uses the same sampled components. Opponent allowances for the same position shrink toward league baseline with bounded adjustment. Mean, median, recent/full hit rates and outlier concentration are exposed separately from model probability.

Anytime TD, first TD and passing TD use prior play-by-play opportunities. A shrunk team touchdown rate drives shared Poisson-process arrivals. Red-zone and goal-line carry/target shares allocate scorers with an explicit other-scorer category. Receiving opportunity share classifies pass touchdowns and prior QB attempts allocate passers. First TD is the first arrival in a two-team competition with at most one first scorer per simulation; it is not an arbitrary fraction of anytime probability. Longest-play markets use prior observed play-by-play maxima and require that data. Opportunity models abstain if requisite team/player coverage is missing.

## Correlation and uncertainty

Players share game pace and opposing pass/rush script factors. Each player's numeric markets share sampled workload/efficiency. TD legs share arrivals/scorers; first-TD outcomes are mutually exclusive. Different games are assumed independent. Script/pace factor coefficients are heuristic; they are not learned causal effects. Target shares do not yet enforce a complete team-volume allocation across all receivers, and current roster departures/injuries are not fully modeled. These are production validation blockers. Longest-play draws currently do not share workload factors.

Default Monte Carlo count is 20,000. Displayed confidence intervals describe Monte Carlo sampling error only, not total model error. Confidence is a sample/quality indicator, not a calibrated confidence level. Minimum sample is 12 games, maximum recent window 24. Outlier concentration reduces confidence. The optimizer considers at most 24 legs, at most two alternatives per player, then enumerates combinations with one provider and distinct players. Research ranking is by joint probability. No actual payout is invented for value/EV rankings.

## Causal evaluation and calibration

Only rows whose conservative availability timestamp precedes the prediction cutoff enter features. No random time-mixing split. Backtesting uses prior-only median + 0.5 statistical thresholds, with the earlier 60% of dates used to fit a regularized logistic calibrator and later dates held out for evaluation. These thresholds are test targets, never represented as historical provider lines. No historical EV is inferred.

The sample is deliberately bounded and favors players with sufficient prior usage and an observed current game stat row; report this selection bias. Some markets cannot support enough calibration observations and remain uncalibrated. Negative-slope or undersampled fits are excluded. First-TD probabilities retain the coherent raw simulation to preserve exclusivity. Statistical calibration and provider-line evaluation are different tasks. Full rolling retraining, opponent-strength validation, role/injury/weather integration and large independent correlation validation remain unfinished.

Generated site/data/backtest.json contains current counts, held-out Brier/log loss and per-market metrics. Empty or failing evaluation cannot establish readiness. Registries record training cutoff, input/schema hashes, calibration coefficients and validation results. One artifact is frozen per week; Tuesday updates create the next artifact rather than rewriting an official prediction.

## Grading and audit

Only NFL schedule rows with recorded official final scores are eligible for grading. The original threshold/direction is preserved. Missing player results stay pending; missing stats are never inferred as zero. Numeric equalities are pushes. Special rescue/no-snap/provider settlement requires explicit support before paper P/L. Original predictions and final results are separate immutable records; losing weeks are retained.

The r2 research registry supersedes the initial r1 artifact because evaluation sampling now selects on prior usage rather than the future stat value. The r1 record remains preserved for provenance and must not be used for new forecasts. The runner selects the latest week-specific artifact; published historical predictions retain their recorded version. This correction does not establish production validation.
