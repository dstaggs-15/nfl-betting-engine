# Provider access and normalization

## Kalshi

Read-only GETs to `https://api.elections.kalshi.com/trade-api/v2/markets`, filtered to current NFL player-prop series, with cursor pagination, timeouts and bounded retries. Discovered series: KXNFLPASSYDS, KXNFLRSHYDS, KXNFLRECYDS, KXNFLREC, KXNFLPASSTDS, KXNFLANYTD and KXNFLFIRSTTD. Collections are isolated from Underdog failures. There are no trading endpoints in this codebase.

Automatic numeric normalization requires: exact series, exact matchup/date ticker, exact player name within that game's roster, matching team ticker prefix, greater strike type, an integer-plus title, and floor_strike exactly integer minus 0.5. First/anytime TD requires a structured strike, exact title suffix and corresponding rule language. Known team aliases are explicit; fuzzy names are not used. Manual bindings may resolve reviewed remaining records. Unknown labels and protected/special-settlement markets are excluded. Receptions/yard contracts may still have active-but-no-snap settlement rules; absent official participation/settlement information remains pending.

Yes/no ask quotes are stored as prices in (0,1). They are not gross ticket multipliers. Series fee metadata and the official general taker formula support conservative paper single-contract value estimates. Unknown fee types receive no estimate. Slippage, liquidity and nonstandard settlement remain limitations. Cross-contract combinations are theoretical, regardless of whether individual contracts are offered.

Public requests worked in this environment. Each current collection displays accepted/raw counts and timestamp; rejected records are not hidden behind a fabricated OK. Last-known-good observations remain unavailable/stale after collection failure. Native Kalshi settlement/result endpoints and special no-snap outcomes are future work; grading currently compares observed final NFL stats and leaves missing stats pending.

## Underdog

The isolated read-only adapter targets `/beta/v5/over_under_lines`, with player/appearance/game relations and exact identities. Public endpoint versions v3/v5/v6 returned HTTP 426 (upgrade required) in live probes. No authentication challenge was bypassed and no account credentials are requested on that evidence. The live state is DOWN, not a fabricated success.

A trusted existing export can be provided through UNDERDOG_EXPORT_PATH. Include a root `exported_at` with the true collection time as a timezone-aware ISO timestamp; stale exports stay stale and never receive a fresh timestamp. Use the original public provider shape and audited bindings for markets that lack a reliable event association. Aliases, client-version/API schema changes, and ticket eligibility require provider verification. An option's boost is not assumed to be a full-ticket payout. Unknown rules mean theoretical combinations and no paper ROI. This export fixture path has been tested; live Underdog collection is blocked by the endpoint's required client upgrade.

## PrizePicks and third-party DFS

PrizePicks direct `/projections?league_id=9` currently returns HTTP 403. The adapter accepts exact player/team/game/stat matches and skips nonstandard demon/goblin odds types. `PRIZEPICKS_EXPORT_PATH` supports original-schema trusted exports with a real timezone-aware `exported_at`; fixtures are not live evidence.

The Odds API officially documents `underdog` and `prizepicks` US DFS bookmaker keys and NFL player props. Set `ODDS_API_KEY` in the execution environment and GitHub Actions secrets. The read-only event adapter requests both sources, caches responses for 30 minutes, preserves book/market timestamps, and rejects missing/future timestamps or ambiguous matches. API requests consume subscription credits; coverage depends on the account. No key is supplied here, so real DFS collection remains unverified. Failed direct sources can recover through normalized aggregator lines; stale aggregator lines stay stale.

Indicative DFS odds are not actual complete-ticket payout multipliers. Modified lines, correlation/eligibility constraints, Power/Flex choices, promotions, void/push treatment and actual ticket quotes must be verified separately. Unknown complete-ticket payouts mean no priced parlay recommendation. See [RESEARCH.md](RESEARCH.md) for official sources.

## NFL data and logos

nflreadpy 0.1.5 loads current and two prior seasons of schedules, player stats, current rosters and play-by-play. Polars caches reduce repeated downloads; current data has a one-hour TTL. Play-by-play enrichment adds red-zone/goal-line opportunities, observed team touchdowns, first-touchdown scorer and longest plays. Feature availability is conservatively set to kickoff plus one day for completed games. This availability approximation is documented; precise historical source publication timestamps are not available.

Team metadata comes from nflverse/nflverse-pbp/teams_colors_logos.csv at runtime. The frontend loads a generated local mapping and uses ESPN-hosted maintained logo URLs, falling back to abbreviation text. Stat files and source provenance remain separate from compact public JSON. Missing historical provider lines are never backfilled with synthetic markets.
