from itertools import combinations

import numpy as np

from .schemas import Market, Ticket
from .storage import digest


def economics(probability, multiplier):
    if multiplier is None:
        return None, None
    if multiplier <= 1:
        raise ValueError("gross multiplier must exceed one")
    return 1 / multiplier, probability * multiplier - 1


def joint_probability(legs, masks):
    groups = {}
    for leg in legs:
        groups.setdefault(leg.line.event_id, []).append(masks[leg.prediction_id])
    # Independent games, correlated samples inside each game.
    return float(np.prod([np.mean(np.logical_and.reduce(group)) for group in groups.values()]))


def optimize(
    predictions,
    masks,
    count,
    same_game,
    minimum_confidence=0.65,
    minimum_joint=0.12,
    official=False,
    limit=10,
):
    eligible = [
        p
        for p in predictions
        if p.status in (("RECOMMENDED",) if official else ("WATCH", "RECOMMENDED"))
        and p.line.market != Market.FIRST_TD
        and p.probability >= 0.55
        and p.confidence >= minimum_confidence
        and p.prediction_id in masks
    ]
    ranked = sorted(eligible, key=lambda p: p.probability, reverse=True)
    per_player = {}
    eligible = []
    for prediction in ranked:
        count_for_player = per_player.get(prediction.line.player_id, 0)
        if count_for_player < 2:
            eligible.append(prediction)
            per_player[prediction.line.player_id] = count_for_player + 1
        if len(eligible) >= 24:
            break
    tickets = []
    for legs in combinations(eligible, count):
        # Different players, one provider, no repeated/opposite markets, and explicit game mode.
        if len({p.line.player_id for p in legs}) != count or len({p.line.provider for p in legs}) != 1:
            continue
        events = sorted({p.line.event_id for p in legs})
        if same_game != (len(events) == 1):
            continue
        joint = joint_probability(legs, masks)
        if joint < minimum_joint:
            continue
        ids = [p.prediction_id for p in legs]
        tickets.append(
            Ticket(
                ticket_id=digest(ids)[:24],
                provider=legs[0].line.provider,
                legs=ids,
                event_ids=events,
                joint_probability=joint,
                naive_probability=float(np.prod([p.probability for p in legs])),
                uncertainty=float(1.96 * np.sqrt(joint * (1 - joint) / len(masks[ids[0]]))),
                fair_multiplier=1 / joint if joint else None,
                weakest_leg=min(legs, key=lambda p: p.probability).prediction_id,
                lowest_confidence_leg=min(legs, key=lambda p: p.confidence).prediction_id,
                same_game=same_game,
                model_version=legs[0].model_version,
                correlation_notes="Shared pace/script and player workloads; heuristic dependencies require validation. "
                "Different games assumed independent. Payout and ticket eligibility unverified.",
            )
        )
    return sorted(tickets, key=lambda t: t.joint_probability, reverse=True)[:limit]
