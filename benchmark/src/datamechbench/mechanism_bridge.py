"""Apply a common valuation vector to fixed downstream decision rules."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from .models import ValuationMechanismDecision
from .settings.valuation_mechanisms import ValuationMechanismSetting


def _rank(scores: Mapping[str, float]) -> tuple[str, ...]:
    return tuple(sorted(scores, key=lambda owner: (-float(scores[owner]), owner)))


def _proportional_payments(
    owners: tuple[str, ...], scores: Mapping[str, float], pool: Decimal
) -> dict[str, Decimal]:
    weights = [max(0.0, float(scores[owner])) for owner in owners]
    total = sum(weights)
    if not owners or total <= 0:
        return {}
    payments: dict[str, Decimal] = {}
    remaining = pool
    for owner, weight in zip(owners[:-1], weights[:-1], strict=True):
        amount = pool * Decimal(str(weight)) / Decimal(str(total))
        payments[owner] = amount
        remaining -= amount
    payments[owners[-1]] = remaining
    return payments


def bridge_valuation_scores(
    setting: ValuationMechanismSetting,
    scores: Mapping[str, float],
) -> ValuationMechanismDecision:
    if set(scores) != set(setting.owner_ids):
        raise ValueError("score owner IDs must exactly match the mechanism setting")
    ranking = _rank(scores)
    mechanism = setting.mechanism
    payments: dict[str, Decimal] = {}
    stop_index: int | None = None
    if mechanism in {"top_k_acquisition", "corruption_exclusion", "split_attack"}:
        selected = ranking[: setting.top_k]
    elif mechanism == "budgeted_procurement":
        density = sorted(
            setting.owner_ids,
            key=lambda owner: (
                -float(scores[owner]) / max(float(setting.costs[owner]), 1e-12),
                owner,
            ),
        )
        chosen: list[str] = []
        spent = Decimal("0")
        for owner in density:
            cost = setting.costs[owner]
            if float(scores[owner]) > 0 and spent + cost <= setting.budget:
                chosen.append(owner)
                payments[owner] = cost
                spent += cost
        selected = tuple(chosen)
    elif mechanism in {"revenue_allocation", "replication_attack"}:
        selected = tuple(owner for owner in setting.owner_ids if float(scores[owner]) > 0)
        payments = _proportional_payments(selected, scores, setting.budget)
    elif mechanism == "reserve_admission":
        selected = tuple(owner for owner in ranking if float(scores[owner]) >= setting.reserve)
    elif mechanism == "sequential_acquisition":
        chosen = []
        cumulative = 0.0
        for index, owner in enumerate(setting.owner_ids, start=1):
            chosen.append(owner)
            cumulative += max(0.0, float(scores[owner]))
            if cumulative >= setting.target_utility:
                stop_index = index
                break
        selected = tuple(chosen)
        stop_index = stop_index or len(setting.owner_ids)
    else:
        raise ValueError(f"unsupported valuation mechanism: {mechanism}")
    return ValuationMechanismDecision(
        selected_ids=selected,
        payments=payments,
        welfare=sum(float(scores[owner]) for owner in selected),
        stop_index=stop_index,
        diagnostics={"mechanism": mechanism},
    )


__all__ = ["bridge_valuation_scores"]
