"""Manual Google Flow recommendations for browser-only generation workflows.

MoneyPrinter has no supported Google Flow API integration. This module produces
shot recommendations from a dated credit table and never submits browser work.
Credit quotes are supplied by the caller so stale prices cannot silently route.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class FlowCandidate:
    model: str
    duration_seconds: int
    resolution: str
    credits: int
    plan_eligibility: tuple[str, ...]
    capabilities: frozenset[str] = frozenset()
    quote_date: str = ""
    source: str = ""
    ui_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class FlowRecommendation:
    shot_key: str
    model: str | None
    credits: int | None
    reason: str
    manual_action_required: bool = True


def load_flow_quotes(path: str | Path) -> list[FlowCandidate]:
    """Load dated credit quotes; never promotes an unconfirmed quote to UI-ready."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("quotes"), list):
        raise ValueError("Flow quote catalog must contain a quotes array")
    result = []
    for item in document["quotes"]:
        if not isinstance(item, dict):
            continue
        result.append(
            FlowCandidate(
                model=str(item.get("model", "")),
                duration_seconds=int(item.get("duration_seconds", 0)),
                resolution=str(item.get("resolution", "")),
                credits=int(item.get("credits", -1)),
                plan_eligibility=tuple(item.get("plan_eligibility", ())),
                capabilities=frozenset(item.get("capabilities", ())),
                quote_date=str(item.get("quote_date", "")),
                source=str(item.get("source", "")),
                ui_confirmed=bool(item.get("ui_confirmed", False)),
            )
        )
    return result


def recommend_shot(
    *,
    prompt: str,
    duration_seconds: int,
    resolution: str,
    required_capabilities: Iterable[str] = (),
    subscription_plan: str,
    candidates: Iterable[FlowCandidate],
    reference_identity: str = "",
    max_quote_age_days: int = 30,
    today: str,
    provider_account_check_required: bool = False,
) -> FlowRecommendation:
    """Return cheapest currently eligible browser choice; never call Google."""
    identity = json.dumps(
        {
            "prompt": prompt.strip(),
            "duration": int(duration_seconds),
            "resolution": resolution.lower(),
            "features": sorted(set(required_capabilities)),
            "references": reference_identity,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    shot_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    if provider_account_check_required:
        return FlowRecommendation(
            shot_key=shot_key,
            model=None,
            credits=None,
            reason=(
                "provider_account_check_required: hold generation for the owner to "
                "complete the provider's account check; do not retry, switch accounts, "
                "or bypass the check."
            ),
        )
    required = set(required_capabilities)
    eligible = []
    for item in candidates:
        if item.duration_seconds != duration_seconds:
            continue
        if item.resolution.lower() != resolution.lower():
            continue
        if (
            item.credits < 0
            or not item.quote_date
            or not item.source
            or not item.ui_confirmed
        ):
            continue
        if subscription_plan.lower() not in {
            plan.lower() for plan in item.plan_eligibility
        }:
            continue
        quote_age = _days_between(item.quote_date, today)
        if quote_age is None or quote_age < 0 or quote_age > max_quote_age_days:
            continue
        if not required.issubset(item.capabilities):
            continue
        eligible.append(item)
    if not eligible:
        return FlowRecommendation(
            shot_key=shot_key,
            model=None,
            credits=None,
            reason=(
                "No current, plan-eligible quote matches this shot's duration, "
                "resolution, and reference/edit requirements; choose manually in Flow."
            ),
        )
    winner = min(eligible, key=lambda item: (item.credits, item.model))
    return FlowRecommendation(
        shot_key=shot_key,
        model=winner.model,
        credits=winner.credits,
        reason=(
            f"Lowest compatible quote for {subscription_plan}; verified "
            f"{winner.quote_date} from {winner.source}. Select this model manually in Flow."
        ),
    )


def _days_between(quoted: str, today: str) -> int | None:
    try:
        from datetime import date

        return (date.fromisoformat(today) - date.fromisoformat(quoted)).days
    except (TypeError, ValueError):
        return None
