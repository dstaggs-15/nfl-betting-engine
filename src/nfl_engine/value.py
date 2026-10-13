"""Read-only paper economics; real quotes and verified fee metadata required."""

import math


def contract_value(probability, price, fee_type, fee_multiplier, budget=10):
    if fee_type != "quadratic" or fee_multiplier is None or not 0 < price < 1:
        return None
    # Official general taker formula. Round upward to cents conservatively; the
    # current schedule permits finer centicent precision for some products.
    rate = 0.07 * fee_multiplier * price * (1 - price)
    contracts = math.floor(budget / (price + rate))
    while contracts:
        fee = math.ceil((rate * contracts - 1e-12) * 100) / 100
        cost = contracts * price + fee
        if cost <= budget + 1e-9:
            break
        contracts -= 1
    if not contracts:
        return None
    return {
        "budget": budget,
        "contracts": contracts,
        "cost": round(cost, 4),
        "estimated_fee": fee,
        "win_profit": round(contracts - cost, 4),
        "expected_profit": round(contracts * probability - cost, 4),
        "break_even": cost / contracts,
        "gross_multiplier": contracts / cost,
        "sensitivity_profit": round(contracts * max(0, probability - 0.05) - cost, 4),
        "method": "Observed ask plus official general taker fee, conservatively rounded up to cents.",
        "limitations": "Assumes enough liquidity at the ask and ordinary settlement; no orders are submitted.",
    }


def qualifying_value(prediction, economics, minimum_probability=0.75, minimum_win_profit=5):
    return bool(
        economics
        and prediction.status not in ("STALE_LINE", "INSUFFICIENT_DATA")
        and prediction.probability >= minimum_probability
        and prediction.line.market != "first_touchdown"
        and prediction.confidence >= 0.65
        and economics["win_profit"] >= minimum_win_profit
        and economics["expected_profit"] > 0
        and economics["sensitivity_profit"] > 0
    )


def parlay_value(probability, multiplier, stake=10, minimum_multiplier=2):
    if multiplier is None or multiplier < minimum_multiplier:
        return None
    expected_profit = stake * (probability * multiplier - 1)
    conservative_profit = stake * (max(0, probability - 0.05) * multiplier - 1)
    return {
        "stake": stake,
        "win_profit": stake * (multiplier - 1),
        "expected_profit": expected_profit,
        "break_even": 1 / multiplier,
        "sensitivity_profit": conservative_profit,
        "qualifies": expected_profit > 0 and conservative_profit > 0,
    }
