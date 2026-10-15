"""Read allowlisted cost-router settings once, at the start of each new job."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from loguru import logger


_SCALAR_KEYS = {
    "enabled": "cost_router_enabled",
    "cache_enabled": "cost_router_cache_enabled",
    "exceptional_authorized": "cost_router_exceptional_authorized",
    "budget_api_project": "cost_router_budget_api_project",
    "budget_api_per_video": "cost_router_budget_api_per_video",
}
_CANDIDATE_KEYS = {
    "provider",
    "model",
    "tier",
    "estimated_cost",
    "max_difficulty",
    "qualities",
    "price_source",
    "price_checked_on",
    "billing_unit",
    "lower_tier_failed",
    "economic_justification",
    "capability_bypass",
}


def read_new_job_overrides(
    base_config: Mapping[str, Any],
    path: str | Path,
) -> dict[str, Any]:
    """Return a sanitized overlay; credentials and arbitrary config keys are ignored."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning(f"cost-router override file ignored: {type(exc).__name__}")
        return {}
    if not isinstance(document, dict):
        logger.warning("cost-router override file ignored: expected a JSON object")
        return {}

    overlay = {}
    for source_key, config_key in _SCALAR_KEYS.items():
        if source_key not in document:
            continue
        value = document[source_key]
        if source_key in {"enabled", "cache_enabled", "exceptional_authorized"}:
            if isinstance(value, bool):
                overlay[config_key] = value
        else:
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
                and math.isfinite(value)
            ):
                overlay[config_key] = float(value)

    raw_candidates = document.get("candidates", [])
    if isinstance(raw_candidates, list):
        candidates = []
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
            candidate = {key: raw[key] for key in _CANDIDATE_KEYS if key in raw}
            if isinstance(candidate.get("estimated_cost"), bool) or not isinstance(
                candidate.get("estimated_cost"), (int, float)
            ) or not math.isfinite(candidate["estimated_cost"]):
                candidate.pop("estimated_cost")
            candidates.append(candidate)
        overlay["cost_router_candidates"] = candidates
    return overlay


def apply_new_job_overrides(
    base_config: Mapping[str, Any],
    path: str | Path,
) -> dict[str, Any]:
    """Create the immutable-by-convention settings snapshot for a new job."""
    snapshot = dict(base_config)
    snapshot.update(read_new_job_overrides(base_config, path))
    return snapshot
