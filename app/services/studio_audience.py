"""Portable editorial market preferences, distinct from measured distribution."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo


def audience_distribution_plan(policy=None):
    """Describe an organic release experiment without promising geo targeting.

    This does not change account residence, buy ads, exclude viewers or infer
    countries from names, likes, language or ethnicity. Unknown metrics stay null.
    """
    policy = policy or {}
    country = policy.get("primary_country")
    if country is not None and not re.fullmatch(r"[A-Z]{2}", str(country)):
        raise ValueError("primary_country requires a two-letter country code")
    timezone = policy.get("release_timezone", "UTC")
    ZoneInfo(timezone)
    window = policy.get("release_window", {"start": "18:00", "end": "20:00"})
    for key in ("start", "end"):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(window.get(key, ""))):
            raise ValueError("release window requires valid HH:MM times")
    if window["start"] == window["end"]:
        raise ValueError("release window cannot be empty")
    return {
        "primary_country": country,
        "spoken_language": policy.get("spoken_language", "en"),
        "separate_localizations": list(policy.get("separate_localizations", [])),
        "release_timezone": timezone,
        "release_window": dict(window),
        "timing_status": "editorial_test_not_proven_optimum",
        "organic_geographic_guarantee": False,
        "paid_campaign_created": False,
        "paid_campaign_requires_separate_budget": True,
        "account_residence_change": False,
        "exclude_existing_viewers": False,
        "country_performance": None,
        "review_metrics": [
            "country_views", "country_watch_time", "average_view_duration",
            "completion_rate", "returning_viewers", "traffic_source",
        ],
        "review_rule": "Use actual platform country reports; likes alone do not establish poor targeting or inauthentic traffic.",
    }


def release_window(day: str, policy, *, operator_timezone="America/Toronto"):
    """Convert a proposed market-local window, preserving date and DST."""
    plan = audience_distribution_plan(policy)
    zone = ZoneInfo(plan["release_timezone"])
    start = datetime.combine(date.fromisoformat(day), time.fromisoformat(plan["release_window"]["start"]), zone)
    end = datetime.combine(date.fromisoformat(day), time.fromisoformat(plan["release_window"]["end"]), zone)
    if end <= start:
        end += timedelta(days=1)
    return {
        "market_start": start.isoformat(), "market_end": end.isoformat(),
        "operator_start": start.astimezone(ZoneInfo(operator_timezone)).isoformat(),
        "operator_end": end.astimezone(ZoneInfo(operator_timezone)).isoformat(),
        "scheduled_on_platform": False,
    }
