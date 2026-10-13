from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .model import actual
from .schemas import Grade, Results, Snapshot
from .storage import digest, immutable, read_json, write_json


def snapshot_path(root, game, scope="game"):
    filename = "official.json" if scope == "game" else "slate-official.json"
    return root / f"data/predictions/{game.season}/week-{game.week:02}/{game.event_id}/{filename}"


def save_official(root, game, predictions, tickets, now, version, scope="game", games=None):
    path = snapshot_path(root, game, scope)
    if path.exists():
        return False
    if now >= game.kickoff:
        raise ValueError("cannot create an official prediction after kickoff")
    if scope == "game" and any(p.line.event_id != game.event_id for p in predictions):
        raise ValueError("game snapshot contains a different game")
    if scope == "slate":
        by_event = {g.event_id: g for g in (games or [])}
        if any(
            p.line.event_id not in by_event or by_event[p.line.event_id].kickoff <= now for p in predictions
        ):
            raise ValueError("slate contains an unknown or started game")
    record = Snapshot(
        scope=scope,
        event_ids=sorted({p.line.event_id for p in predictions} or {game.event_id}),
        run_id=digest([game.event_id, "official", scope])[:24],
        created_at=now,
        season=game.season,
        week=game.week,
        game_id=game.event_id,
        kickoff=game.kickoff,
        minutes_to_kickoff=(game.kickoff - now).total_seconds() / 60,
        model_version=version,
        data_cutoff=now,
        provider_snapshot_ids=sorted({p.line.raw_source_hash for p in predictions}),
        individual_predictions=predictions,
        recommended_3_leg=[t for t in tickets if len(t.legs) == 3],
        recommended_4_leg=[t for t in tickets if len(t.legs) == 4],
    )
    try:
        return immutable(path, record)
    except FileExistsError:
        return False  # Another dispatcher already won; preserve its complete record.


def grade_line(prediction, row):
    value = actual(row, prediction.line.market) if row else None
    if value is None:
        return Grade(prediction_id=prediction.prediction_id, actual=None, result="pending")
    threshold = prediction.line.threshold
    if value == threshold:
        result = "push"
    else:
        win = value > threshold if prediction.line.direction == "over" else value < threshold
        result = "win" if win else "loss"
    return Grade(prediction_id=prediction.prediction_id, actual=value, result=result)


def grade_snapshot(snapshot, games, stats, now):
    game = games.get(snapshot.game_id)
    events = snapshot.event_ids or [snapshot.game_id]
    if not game or any(not games.get(event) or games[event].status != "final" for event in events):
        return None
    indexed = {(r["event_id"], r["player_id"]): r for r in stats}
    grades = [
        grade_line(p, indexed.get((p.line.event_id, p.line.player_id)))
        for p in snapshot.individual_predictions
    ]
    # Missing stats do not mean zero, DNP, or void. Reconcile later.
    if any(g.result == "pending" for g in grades):
        return None
    by_id = {g.prediction_id: g for g in grades}
    tickets = []
    for ticket in snapshot.recommended_3_leg + snapshot.recommended_4_leg:
        outcomes = [by_id[i].result for i in ticket.legs]
        result = "loss" if "loss" in outcomes else "win" if all(o == "win" for o in outcomes) else "pending"
        # Unknown push/rescue rules cannot be paper-settled as a full win.
        tickets.append({"ticket_id": ticket.ticket_id, "result": result})
    return Results(
        run_id=snapshot.run_id,
        created_at=now,
        source_hash=digest([game.model_dump(mode="json"), stats]),
        legs=grades,
        tickets=tickets,
    )


def reconcile(root, games, stats, now):
    count = 0
    for path in sorted((root / "data/predictions").rglob("*official.json")):
        snapshot = Snapshot.model_validate_json(path.read_text())
        output = root / f"data/results/{snapshot.season}/week-{snapshot.week:02}/{snapshot.run_id}.json"
        if output.exists():
            continue
        result = grade_snapshot(snapshot, {g.event_id: g for g in games}, stats, now)
        if result is not None:
            immutable(output, result)
            count += 1
    return count


def binary_metrics(records):
    settled = [r for r in records if r["result"] in ("win", "loss")]
    if not settled:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "hit_rate": None,
            "average_probability": None,
            "brier": None,
            "log_loss": None,
        }
    p = np.array([r["probability"] for r in settled])
    y = np.array([r["result"] == "win" for r in settled])
    safe = np.clip(p, 1e-9, 1 - 1e-9)
    return {
        "count": len(settled),
        "wins": int(y.sum()),
        "losses": int((~y).sum()),
        "hit_rate": float(y.mean()),
        "average_probability": float(p.mean()),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(np.mean(-y.astype(float) * np.log(safe) - (~y) * np.log(1 - safe))),
    }


def tracker(root: Path, stake=10):
    records, tickets = [], []
    for path in sorted((root / "data/predictions").rglob("*official.json")):
        snapshot = Snapshot.model_validate_json(path.read_text())
        result_path = root / f"data/results/{snapshot.season}/week-{snapshot.week:02}/{snapshot.run_id}.json"
        raw = read_json(result_path)
        result = Results.model_validate(raw) if raw else None
        grades = {g.prediction_id: g for g in result.legs} if result else {}
        ticket_grades = {g["ticket_id"]: g["result"] for g in result.tickets} if result else {}
        for p in snapshot.individual_predictions:
            g = grades.get(p.prediction_id)
            records.append(
                {
                    "run_id": snapshot.run_id,
                    "prediction_id": p.prediction_id,
                    "created_at": snapshot.created_at.isoformat(),
                    "season": snapshot.season,
                    "week": snapshot.week,
                    "game": snapshot.game_id,
                    "player": p.line.player_name,
                    "player_id": p.line.player_id,
                    "team": p.line.team,
                    "market": p.line.market.value,
                    "provider": p.line.provider,
                    "threshold": p.line.threshold,
                    "direction": p.line.direction,
                    "price": p.line.price,
                    "price_type": p.line.price_type,
                    "probability": p.probability,
                    "confidence": p.confidence,
                    "model_version": p.model_version,
                    "collected_at": p.line.collected_at.isoformat(),
                    "result": g.result if g else "pending",
                    "actual": g.actual if g else None,
                    "risk_codes": p.risk_codes,
                    "reason_codes": p.reason_codes,
                    "line_movement": None,
                }
            )
        for t in snapshot.recommended_3_leg + snapshot.recommended_4_leg:
            outcome = ticket_grades.get(t.ticket_id, "pending")
            # Paper ROI requires a real recorded payout and verified settlement semantics.
            settled = outcome in ("win", "loss") and t.multiplier is not None and t.eligibility == "verified"
            pnl = stake * (t.multiplier - 1) if settled and outcome == "win" else -stake if settled else None
            failed = [i for i in t.legs if i in grades and grades[i].result == "loss"]
            tickets.append(
                {
                    **t.model_dump(mode="json"),
                    "run_id": snapshot.run_id,
                    "created_at": snapshot.created_at.isoformat(),
                    "season": snapshot.season,
                    "week": snapshot.week,
                    "result": outcome,
                    "probability": t.joint_probability,
                    "stake": stake if settled else None,
                    "pnl": pnl,
                    "failed_legs": failed,
                    "weakest_leg_failed": t.weakest_leg in failed,
                    "explanation": "Observed failed legs only; cause is not established." if failed else None,
                }
            )
    weekly = []
    for season, week in sorted({(r["season"], r["week"]) for r in records}):
        rs = [r for r in records if r["season"] == season and r["week"] == week]
        ts = [t for t in tickets if t["season"] == season and t["week"] == week]
        weekly.append(
            {
                "season": season,
                "week": week,
                "predictions": len(rs),
                **binary_metrics(rs),
                "three_leg": binary_metrics([t for t in ts if len(t["legs"]) == 3]),
                "four_leg": binary_metrics([t for t in ts if len(t["legs"]) == 4]),
                "same_game": sum(t["same_game"] for t in ts),
                "cross_game": sum(not t["same_game"] for t in ts),
                "paper_pnl": sum(t["pnl"] for t in ts if t["pnl"] is not None),
            }
        )
    calibration = []
    for lower, upper in [(0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]:
        selected = [r for r in records if lower <= r["probability"] < upper]
        calibration.append({"bucket": f"{lower:.0%}–{min(upper, 1):.0%}", **binary_metrics(selected)})
    breakdown = {}
    for field in ("market", "team", "provider", "model_version", "player"):
        breakdown[field] = {
            str(v): binary_metrics([r for r in records if r[field] == v])
            for v in sorted({r[field] for r in records})
            if field != "player" or sum(r[field] == v for r in records) >= 20
        }
    for record in records:
        value = record["confidence"]
        record["confidence_bucket"] = "80%+" if value >= 0.8 else "65–79%" if value >= 0.65 else "Below 65%"
        record["source_age_seconds"] = (
            datetime.fromisoformat(record["created_at"]) - datetime.fromisoformat(record["collected_at"])
        ).total_seconds()
    breakdown["confidence"] = {
        bucket: binary_metrics([r for r in records if r["confidence_bucket"] == bucket])
        for bucket in ["Below 65%", "65–79%", "80%+"]
    }
    ticket_breakdown = {}
    for ticket in tickets:
        ticket["scope"] = "same_game" if ticket["same_game"] else "cross_game"
        ticket["leg_count"] = str(len(ticket["legs"]))
        weak = next(
            (
                r
                for r in records
                if r["run_id"] == ticket["run_id"] and r["prediction_id"] == ticket["weakest_leg"]
            ),
            None,
        )
        ticket["weakest_probability_bucket"] = f"{int(weak['probability'] * 10) * 10}%" if weak else "unknown"
    for field in ("scope", "leg_count", "provider", "model_version", "weakest_probability_bucket"):
        ticket_breakdown[field] = {
            str(v): binary_metrics([t for t in tickets if t[field] == v])
            for v in sorted({t[field] for t in tickets})
        }
    risked = sum(t["stake"] for t in tickets if t["stake"] is not None)
    pnl = sum(t["pnl"] for t in tickets if t["pnl"] is not None)
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": binary_metrics(records),
        "three_leg": binary_metrics([t for t in tickets if len(t["legs"]) == 3]),
        "four_leg": binary_metrics([t for t in tickets if len(t["legs"]) == 4]),
        "paper": {
            "stake": stake,
            "risked": risked,
            "returned": risked + pnl if risked else None,
            "pnl": pnl if risked else None,
            "roi": pnl / risked if risked else None,
        },
        "weekly": weekly,
        "calibration": calibration,
        "breakdown": breakdown,
        "ticket_breakdown": ticket_breakdown,
        "records": records,
        "tickets": tickets,
    }
    write_json(root / "site/data/tracker.json", output)
    return output
