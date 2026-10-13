# Gridiron Lab — NFL Betting Engine

A read-only NFL prop research dashboard with live Kalshi contract quotes, nflverse statistics, workload and touchdown simulations, theoretical 2/3/4-leg research combinations, immutable pregame observations, final-result reconciliation, and a JSON-backed historical tracker. It never places bets or orders.

**Current maturity: research application, not a validated production recommendation model.** Live Kalshi collection and the local workflow have been exercised. Underdog's public endpoint returns HTTP 426. Paper history begins with actual recorded pregame observations; historical provider lines and payouts are never invented. Deployment and account settings must be verified separately.

## Local setup

Use Python 3.12 and uv. From the existing checkout:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
export XDG_CACHE_HOME="$PWD/.cache"
uv sync --frozen
uv run python -m nfl_engine.pipeline refresh
uv run python -m nfl_engine.pipeline backtest
uv run python -m nfl_engine.pipeline build
uv run python -m http.server 8000 --directory dist --bind 127.0.0.1
```

Open index.html from the server; tracker.html loads site/data/tracker.json. All kickoff labels use America/Chicago with daylight-saving rules. Cloud onboarding validates with local HTTP requests; it does not provide a web preview link.

## Validation

```sh
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run python -m nfl_engine.pipeline validate
uv run python -m nfl_engine.pipeline build
BROWSER_EXECUTABLE=/usr/bin/chromium uv run python tests/browser_smoke.py
```

If Chromium is unavailable, install Playwright Chromium using `uv run playwright install chromium` (CI installs its system dependencies too). Browser smoke tests cover loading, navigation, provider health, game cards, controls, mobile width and broken logos. Tests use isolated temporary history and fixture payloads; fixtures never become live predictions.

## Commands

- `refresh`: current public lines, player projections, research combinations, NFL schedule, team mapping and tracker.
- `dispatch`: refresh plus one official snapshot for each scheduled game within 15–35 minutes of kickoff. Target is T-30. Never creates a pregame snapshot at or after kickoff.
- `reconcile`: refresh and reconcile only officially final games, then rebuild tracker. Missing player stats stay pending.
- `backtest`: chronological statistical-threshold evaluation and weekly research calibration registry. This is not historical provider EV.
- `validate`: check generated JSON and official records against their schemas.
- `build`: validate and copy only HTML, frontend assets and compact JSON to dist/.

The default season is the UTC year, or the previous year in January/February. Use `--season YYYY` for an explicit season. Paths are relative to the checkout; `--root` can override it.

## Providers and variables

Public endpoints need no account keys. Optional `UNDERDOG_EXPORT_PATH` or `KALSHI_EXPORT_PATH` points to a trusted local export in the original provider schema. Exports must contain actual lines and require the same normalization; they are never automatic evidence of freshness. See [PROVIDERS.md](PROVIDERS.md). Do not put secrets or session cookies in exported payloads, frontend files, or source control. `.env` is ignored; variables must be exported explicitly.

config/provider_bindings.json can map an exact provider market ID to an nflverse event and player ID with audited threshold semantics. Unknown/ambiguous records are rejected. Underdog options are not assumed to be ticket multipliers. Kalshi quotes are contract prices and never native parlay multipliers.

## Scheduling

config/app.toml holds timezone, pregame window, freshness, quality thresholds and checkpoints. GitHub Actions dispatches every ten minutes; GitHub cron delivery can be delayed and cannot guarantee T-30 execution. The Python runner discovers games from the schedule, including Thursday, international, holiday and Monday games. It preserves one official record per game. Lines are collected on each dispatch (a ten-minute cadence) and unchanged payloads share a content-addressed archive.

The runner reconciles finals on every run and performs idempotent Central-time summary checkpoints Friday 08:00, Sunday 15:15/18:30/23:00, and Tuesday 08:00. A separate Tuesday workflow updates research calibration with DST gating. Weekly artifacts remain frozen; newly available context can change current forecasts. T-90 uses ordinary current refreshes, which do not replace the official record.

## History and deployment

`data/lines` preserves content-addressed normalized source observations. `data/predictions/<season>/week-NN/<game>/official.json` is create-only. `data/results` contains separate create-only results. `tracker.json` is a rebuildable join. Failed legs remain visible; unexplained losses are not attributed to fabricated causes. Push/rescue outcomes with unknown provider rules are left unresolved for paper settlement. Only verified payouts enable flat-$10 paper ROI.

The serialized Actions workflows restore generated history from the `data` branch, append evidence, and deploy a Pages artifact. The code branch is main. No generated commit triggers a code workflow. The first published version includes the current compact site data as a fallback; raw statistics and provider archives do not enter the Pages artifact.

To activate deployment once this change is on main: repository **Settings → Pages → Build and deployment → Source: GitHub Actions**. Enable Actions and read/write workflow permissions for the data branch. Allow the github-pages deployment environment to deploy main. Run **Deploy dashboard** or **Live data and T-30 dispatcher**. Use the URL returned by the Pages job; no public URL is claimed until a deployment succeeds. If an organization disallows automated data-branch writes, grant the workflow that specific permission rather than adding a broad personal token.

## Model limitations

See [MODEL_CARD.md](MODEL_CARD.md). Data coverage, correlated probabilities, injury context, role changes, selection bias and calibration remain important research limitations. `production_validated` is false in generated registries. Consequently official snapshots may contain an individual research board, but official high-confidence ticket recommendations are withheld. Statistical tests prove implementation behavior, not predictive profitability.
