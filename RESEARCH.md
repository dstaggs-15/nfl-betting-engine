# Pricing and model research — October 13, 2026

## What line setting requires

A player prop requires a conditional distribution of the final statistic, not merely a projected average. Workload (snaps, routes, targets, carries and attempts), efficiency, opponent, game script, injury/role and uncertainty determine the distribution. The fair probability at threshold L is P(X > L); a roughly even-money two-sided line is usually near a distribution's median, which can differ substantially from its mean in skewed yardage distributions. Alternative thresholds trade win probability against payout. Public material does not reveal a complete proprietary sportsbook algorithm; this implementation does not claim to reproduce one or share every input available to a trading desk.

Prices add margin and respond to market information and liability. Decimal odds d imply break-even probability 1/d, not necessarily a fair forecast. For a complete mutually exclusive market, a simple margin-removal approximation divides each inverse price by their sum. Power and Shin methods allocate margin differently; none proves the underlying probabilities. Do not de-vig unrelated props, separate alternative thresholds, or two ask quotes as though they were executable complementary sportsbook odds. Kalshi is an exchange: its quotes reflect orders, and costs depend on spread, available quantity and the applicable fee schedule.

For example, both sides at -110 have raw break-even 52.38% and proportional fair probabilities 50%/50%. A model with 75% accuracy on selected alternative thresholds is solving a different task from predicting 75% of ordinary approximately 50/50 lines. Merely selecting an extreme under can make accuracy high while producing little return. Injury/DNP rules can also change what is actually settled.

## Decisions implemented

1. Fit **11 conditional quantiles per market** with gradient boosting, using causal recent workload, trend, variation, position and prior opponent allowances. Eight numeric markets have fitted distributions. Sort crossing quantiles before constructing the CDF, then calibrate that CDF using a separate later period. Derive over and under coherently from the same distribution. Numeric integer thresholds retain push mass.
2. Use train → calibration → later-game test chronology. Features for a test game may use earlier completed games that were already available, while the model weights and calibrator remain frozen. No random time-mixed split. Calibration tests include broad prior-only thresholds, rather than fitting only median lines and extrapolating to tails.
3. Score probability quality with Brier loss and log loss as well as selected hit rate and coverage. Accuracy without coverage, probability calibration or the actual price cannot establish value. The latest frozen artifact is `distribution-2026.6.2`; previous research and fitted artifacts remain preserved.
4. Estimate within-game dependence from **calibration-period residual ranks**, grouped by markets, positions and team/player relationships. Shrink sparse estimates and project to a positive-semidefinite correlation matrix before Gaussian-copula sampling. Same-player alternate thresholds share the same sampled percentile. Separate games are assumed independent. This is a learned approximation, not a verified same-game pricing model.
5. Require 75% predicted chance, sufficient data, fresh quotes, market-level validation and a worthwhile return for ranked individual lines. Default paper win profit must exceed $5 on a $10 budget. Require positive estimated profit even after reducing predicted probability by five percentage points. Large model/market discrepancies above 20 percentage points are withheld from the default ranking because missing role/injury inputs can create misleading edges. This is a guardrail, not an optimized or statistically proven cutoff.
6. Rank Safest by hit chance **within those value checks**. Rank Best value by estimated net dollar return. First-touchdown and anytime-touchdown opportunity models stay experimental and out of ranked views. First-touchdown outcomes are unconditionally excluded from combinations.
7. Never multiply indicative DFS leg prices to invent a native ticket payout. Require the actual complete-ticket multiplier and eligibility, then compare joint probability with 1/multiplier. Default minimum total payout is 2×, with positive expected return and a five-point probability sensitivity check. Current research groups have unknown payouts and are not recommendations.

A three-leg ticket with independent 75% legs wins only 0.75³ = **42.19%** of the time; a four-leg ticket wins **31.64%**. Their fair gross multipliers are approximately 2.37× and 3.16× before costs. Positive expected value still permits frequent losses. Higher payouts generally require more risk; no statistically guaranteed profit or 75% ticket accuracy is claimed.

## Latest later-game evaluation

Fit: games before November 1, 2025. Calibration: subsequent games before August 1, 2026. Test: completed 2026 games available at training on October 13. Prior-only empirical quantiles generate half-point thresholds; these are **not archived provider lines**. Rows require at least eight prior games and prior average usage of at least three opportunities. Selection never uses the current game's realized yardage or count.

| Market | Selected threshold outcomes | Selected hit rate | Unique player-games | One-per-player-game hit rate | Approximate 95% Wilson interval | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| passing touchdowns | 343 | 86.0% | 158 | 84.2% | 77.7%–89.0% | 31.1% |
| passing yards | 348 | 80.2% | 160 | 80.0% | 73.1%–85.5% | 20.8% |
| receiving yards | 2,000 | 81.8% | 823 | 82.3% | 79.5%–84.7% | 25.3% |
| receptions | 1,662 | 84.2% | 816 | 81.0% | 78.2%–83.5% | 24.7% |
| rushing attempts | 1,315 | 81.0% | 469 | 79.3% | 75.4%–82.7% | 30.5% |
| rushing receiving yards | 2,532 | 83.0% | 1,003 | 83.6% | 81.2%–85.8% | 25.4% |
| rushing yards | 1,133 | 83.3% | 459 | 82.8% | 79.1%–86.0% | 24.9% |
| targets | 1,951 | 83.2% | 815 | 81.0% | 78.1%–83.5% | 26.9% |

Alternate thresholds repeat the same outcomes. The one-per-player-game summary chooses the first qualifying generated threshold in a fixed order; it is not a new independent sample. Players across the same game and repeated weeks remain dependent, so the binomial Wilson intervals are descriptive and can understate uncertainty. A lower interval below 75% excludes that market from default ranked individual picks; **passing yards currently fails this stronger gate**, despite its 80% selected point estimate. Test rows omit some DNPs because they require an observed player-stat row. Missing historical injury/role changes and precise data publication timestamps remain limitations. Some positions and extreme lines have weak support. The test has been inspected during development and requires a genuinely new prospective provider-line test before production claims.

The aggregate 50% hit rate for all paired over/under test outcomes is tautological: each non-push pair has one winner. Brier/log loss and selective coverage are useful there; the paired accuracy itself is not evidence of skill. This report contains no historical provider EV, return or realized trading performance.

## Prices, fees and providers

Kalshi's July 7, 2026 official general taker schedule uses fee = multiplier × 0.07 × contracts × price × (1 − price). The adapter reads each series' fee type and multiplier; unknown fee types get no value estimate. Paper calculations use integer contracts within a $10 budget and conservatively round the fee upward to cents (the actual schedule describes finer centicent precision). Reported cost may be below $10 because fractional contracts are not bought. Win profit = contracts − cost; expected profit = contracts × modeled probability − cost. Available quantity, execution slippage and nonstandard settlement are not verified, so these are paper estimates, not executable offers.

The Odds API documentation explicitly lists US DFS bookmaker keys `underdog` and `prizepicks` and NFL player-prop markets. Its DFS odds are **indicative**; alternate/goblin/demon pricing and complete-ticket rules must be handled separately. The read-only adapter requests standard markets by event, matches exact teams/player/kickoff, preserves original source timestamps, rejects missing/future timestamps and never treats indicative odds as a ticket quote. Requests are cached for 30 minutes to limit usage; event-odds requests consume subscription credits. Availability and coverage still depend on the subscription and actual response.

Live direct probes: Underdog HTTP 426; PrizePicks HTTP 403. No challenges are bypassed. The aggregator endpoint requires a key and returned 401 without one. `ODDS_API_KEY` is not present here, so **live Underdog/PrizePicks integration is not yet verified**. Trusted timestamped exports are another supported input. Kalshi has multivariate infrastructure, but the individual quotes collected here do not establish current native NFL combo prices or DFS payouts.

## Sources read and applied

- [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html): reliability, proper scoring rules, independent calibration data and isotonic sample/overfitting limits. Official source text also read from the project repository.
- [scikit-learn quantile regression example](https://scikit-learn.org/stable/auto_examples/ensemble/plot_gradient_boosting_quantile.html): conditional median/quantiles, skew and varying uncertainty. Applied to full threshold distributions, rather than a mean-only prediction.
- [nflfastR](https://github.com/nflverse/nflfastR): public NFL play-by-play data and contextual CP/xYAC/EPA models. Contextual football models illustrate why raw season averages alone are insufficient; their outputs are not bookmaker prop probabilities.
- [nfl4th](https://github.com/nflverse/nfl4th): distributional decisions and assumptions. A useful distinction between probability and the value of a decision, not evidence that this prop engine matches its quality.
- [Yurko, Ventura and Horowitz, nflWAR](https://arxiv.org/abs/1802.00998): contextual and multilevel football models, uncertainty and football resampling. Supports caution about player/game dependence and attribution; it does not disclose sportsbook algorithms.
- [Penaltyblog implied probability implementation](https://github.com/martineastwood/penaltyblog/blob/master/penaltyblog/implied/implied.py): inverse-odds margin, proportional normalization, power and Shin alternatives. The open-source methods are public modeling references, not a claim about a specific trading desk.
- [Kalshi official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf): actual fee formula, rounding and execution caveats. Used alongside live series fee metadata rather than ignoring fees.
- [The Odds API bookmaker coverage](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html): confirms both DFS sources and cautions about indicative DFS odds.
- [The Odds API markets](https://the-odds-api.com/sports-odds-data/betting-markets.html): supported NFL market keys.
- [The Odds API event-odds documentation](https://the-odds-api.com/liveapi/guides/v4/#get-event-odds): event discovery, bookmaker filters, timestamps, API authentication and usage credits.

## Evidence still needed

Prospective immutable forecasts and settlements on real provider lines; calibration specifically in the 75%+ band; comparable market-implied baselines and closing-line comparisons; observed complete-ticket quotes and settlement rules; no-snap/DNP handling; injury/depth-chart/role/weather inputs; broader game-cluster uncertainty and successive forward periods; executed liquidity/cost validation before claiming financial results. Training more quantiles or having the same public sports data does not remove those requirements.
