import argparse
import logging
import os
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from . import nfl
from .backtest import run_backtest
from .history import reconcile, save_official, snapshot_path, tracker
from .model import Simulator, predict
from .normalize import Identity
from .optimizer import optimize
from .providers import Context, Kalshi, Underdog
from .scheduler import due_checkpoints, due_games
from .schemas import Line, Prediction, Snapshot, Ticket
from .storage import digest, immutable, read_json, write_json

logger = logging.getLogger("nfl_engine")


def load_config(root):
    return tomllib.loads((root / "config/app.toml").read_text())


def registry_for(root, games, now):
    upcoming = sorted([g for g in games if g.kickoff > now], key=lambda g: g.kickoff)
    if not upcoming:
        return None
    game = upcoming[0]
    return read_json(root / f"data/model_registry/{game.season}/week-{game.week:02}.json")


def collect(root, context, now, config):
    old_status = read_json(root / "site/data/status.json", {}).get("providers", {})
    old_lines = read_json(root / "site/data/current_lines.json", [])
    output, health = [], {}
    for provider in (Underdog(), Kalshi()):
        previous = old_status.get(provider.name, {})
        last_success = previous.get("last_success")
        try:
            raw = provider.fetch_markets()
            lines = provider.normalize(raw, context, now)
            raw_count = len(raw.get("over_under_lines" if provider.name == "underdog" else "markets", []))
            current_hash = digest(raw)
            # Archives are create-only and deduplicated by exact payload hash.
            archive = root / f"data/lines/{now.year}/{provider.name}/{current_hash}.json"
            if not archive.exists():
                immutable(
                    archive,
                    {
                        "collected_at": now.isoformat(),
                        "provider": provider.name,
                        "source_hash": current_hash,
                        "source": provider.endpoint,
                        "normalized": [p.model_dump(mode="json") for p in lines],
                    },
                )
            newest = max((p.collected_at for p in lines), default=None)
            stale = newest is not None and (now - newest).total_seconds() > config["freshness_seconds"]
            state = "STALE" if stale else "OK" if lines else "DEGRADED"
            last_success = newest.isoformat() if newest else last_success
            health[provider.name] = {
                "status": state,
                "last_success": last_success,
                "last_attempt": now.isoformat(),
                "raw_records": raw_count,
                "accepted_records": len(lines),
                "message": "Public read-only data collected"
                if lines
                else "No validated NFL lines; event/player bindings or schema may need review.",
            }
            output.extend(lines)
        except Exception as exc:
            state = (
                "AUTH_REQUIRED"
                if getattr(getattr(exc, "response", None), "status_code", None) == 401
                else "DOWN"
            )
            retained = [Line.model_validate(p) for p in old_lines if p["provider"] == provider.name]
            # Failure cannot make old data fresh or available for new recommendations.
            for p in retained:
                output.append(p.model_copy(update={"available": False}))
            health[provider.name] = {
                "status": "STALE" if retained else state,
                "last_success": last_success,
                "last_attempt": now.isoformat(),
                "message": f"Read-only collection failed ({type(exc).__name__}); previous lines unavailable.",
                "accepted_records": 0,
            }
            logger.warning("provider=%s failure_type=%s", provider.name, type(exc).__name__)
        timestamp = health[provider.name]["last_success"]
        health[provider.name]["age_seconds"] = (
            (now - datetime.fromisoformat(timestamp)).total_seconds() if timestamp else None
        )
    unique = {p.line_id: p for p in output}
    write_json(root / "site/data/current_lines.json", [p.model_dump(mode="json") for p in unique.values()])
    return list(unique.values()), health


def refresh(root, now, season, mode="refresh"):
    config = load_config(root)
    games, history, players = nfl.load(root, season)
    future = sorted(
        [g for g in games if g.season == season and g.kickoff > now and g.status != "final"],
        key=lambda g: g.kickoff,
    )
    upcoming = [g for g in future if (g.kickoff - now).days <= 10]
    write_json(root / "site/data/schedule.json", [g.model_dump(mode="json") for g in upcoming])
    nfl.teams(root)
    context = Context(upcoming, Identity(players), read_json(root / "config/provider_bindings.json", {}))
    lines, health = collect(root, context, now, config)
    registry = registry_for(root, games, now)
    if registry:
        config["model_version"] = registry["model_version"]
    simulator = Simulator(history, now, config["simulation_count"])
    predictions, masks = [], {}
    for line in lines:
        game = context.games.get(line.event_id)
        if game is None or line.team not in (game.home, game.away):
            continue
        p, mask = predict(line, simulator, now, config, registry)
        predictions.append(p)
        if mask is not None:
            masks[p.prediction_id] = mask
    tickets = []
    for provider_name in ("underdog", "kalshi"):
        provider_board = [p for p in predictions if p.line.provider == provider_name]
        for count in (2, 3, 4):
            tickets.extend(
                optimize(
                    provider_board,
                    masks,
                    count,
                    False,
                    config["minimum_confidence"],
                    config["minimum_joint_probability"],
                )
            )
            for game in upcoming:
                game_board = [p for p in provider_board if p.line.event_id == game.event_id]
                tickets.extend(
                    optimize(
                        game_board,
                        masks,
                        count,
                        True,
                        config["minimum_confidence"],
                        config["minimum_joint_probability"],
                    )
                )
    official_count = 0
    if mode == "dispatch":
        for game in due_games(upcoming, now, config["pregame"]):
            if snapshot_path(root, game).exists():
                continue
            board = [
                p
                for p in predictions
                if p.line.event_id == game.event_id and p.status not in ("STALE_LINE", "INSUFFICIENT_DATA")
            ]
            official_tickets = []
            for count in (3, 4):
                official_tickets.extend(optimize(board, masks, count, True, official=True))
            official_count += save_official(root, game, board, official_tickets, now, config["model_version"])
    if mode == "dispatch":
        for anchor in due_games(upcoming, now, config["pregame"]):
            if snapshot_path(root, anchor, "slate").exists():
                continue
            slate = [g for g in upcoming if g.week == anchor.week and g.kickoff >= anchor.kickoff]
            slate_ids = {g.event_id for g in slate}
            board = [
                p
                for p in predictions
                if p.line.event_id in slate_ids and p.status not in ("STALE_LINE", "INSUFFICIENT_DATA")
            ]
            recommendations = []
            for count in (3, 4):
                recommendations.extend(optimize(board, masks, count, False, official=True))
            # No slate evidence is created without an actual cross-game recommendation.
            if recommendations:
                official_count += save_official(
                    root,
                    anchor,
                    board,
                    recommendations,
                    now,
                    config["model_version"],
                    scope="slate",
                    games=slate,
                )
    graded_count = reconcile(root, games, history, now)
    summary = tracker(root, config["paper_stake"])
    checkpoints = []
    for date, name in due_checkpoints(now, config):
        marker = root / f"data/checkpoints/{date}/{name}.json"
        if not marker.exists():
            immutable(marker, {"at": now.isoformat(), "name": name, "graded": graded_count})
            checkpoints.append(name)
    write_json(root / "site/data/current_predictions.json", [p.model_dump(mode="json") for p in predictions])
    write_json(root / "site/data/current_parlays.json", [t.model_dump(mode="json") for t in tickets])
    write_json(
        root / "site/data/status.json",
        {
            "generated_at": now.isoformat(),
            "last_successful_refresh": now.isoformat(),
            "current_week": upcoming[0].week if upcoming else None,
            "season": season,
            "model_version": config["model_version"],
            "model_status": "Research / validation required",
            "providers": health,
            "official_snapshots_created": official_count,
            "results_reconciled": graded_count,
            "checkpoints": checkpoints,
            "history_records": len(summary["records"]),
            "nfl_data": "OK",
            "limitations": [
                "Unverified payouts and ticket eligibility remain theoretical.",
                "Touchdown and longest-play models require play-by-play inputs and separate validation.",
            ],
        },
    )
    print(
        f"NFL games={len(upcoming)} lines={len(lines)} predictions={len(predictions)} "
        f"research_combinations={len(tickets)} official_snapshots={official_count} graded={graded_count}"
    )
    return games, history, config


def validate(root):
    for name, cls in [
        ("schedule", __import__("nfl_engine.schemas", fromlist=["Game"]).Game),
        ("current_lines", Line),
        ("current_predictions", Prediction),
        ("current_parlays", Ticket),
    ]:
        values = read_json(root / f"site/data/{name}.json")
        if not isinstance(values, list):
            raise ValueError(f"{name} must be an array")
        for record in values:
            cls.model_validate(record)
    for path in (root / "data/predictions").rglob("*official.json"):
        Snapshot.model_validate_json(path.read_text())
    required = ("status", "teams", "tracker")
    for name in required:
        if not isinstance(read_json(root / f"site/data/{name}.json"), dict):
            raise ValueError(f"{name} must be an object")
    print("Generated JSON and official snapshot schemas validated")


def build(root):
    validate(root)
    target = root / "dist"
    target.mkdir(exist_ok=True)
    for name in ("index.html", "tracker.html"):
        shutil.copy2(root / name, target / name)
    for name in ("assets", "site"):
        shutil.copytree(root / name, target / name, dirs_exist_ok=True)
    print("Static Pages artifact built at dist/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["refresh", "dispatch", "reconcile", "backtest", "build", "validate"]
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--season", type=int, default=datetime.now(UTC).year - (datetime.now(UTC).month < 3))
    args = parser.parse_args()
    root = args.root.resolve()
    os.environ.setdefault("XDG_CACHE_HOME", str(root / ".cache"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "build":
        build(root)
    elif args.command == "validate":
        validate(root)
    elif args.command == "backtest":
        games, history, _ = nfl.load(root, args.season)
        report = run_backtest(root, history, games, load_config(root))
        print(
            f"Backtest fit={report['fit_count']} evaluation={report['evaluation_count']} metrics={report['overall']}"
        )
    else:
        refresh(root, datetime.now(UTC), args.season, args.command)


if __name__ == "__main__":
    main()
