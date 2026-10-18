"""Mandatory finishing evidence for cinema profiles; never an automatic review.

Deterministic checks can reject bad timing or stale evidence. They cannot hear
an unwanted syllable, judge acting or certify lip sync. Those require an honest
review of the actual final audiovisual file, with preserved source evidence.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

VERSION = "1.0.0"
CHECKS = (
    "source_story_fidelity",
    "complete_story_and_ending",
    "acting_dialogue_and_listening",
    "likeness_proportions_and_cast_count",
    "wardrobe_sets_and_props",
    "camera_eyelines_and_physical_action",
    "chronology_weather_and_lighting",
    "native_voice_and_av_timing",
    "pleasant_age_appropriate_music_and_ambience",
    "speech_intelligibility_and_mix",
    "clean_boundaries_no_extra_speech",
    "captions_readability_locale_and_safe_placement",
    "no_loops_stills_or_retiming_padding",
    "independent_complete_story_delivery",
)


def contract():
    """Non-optional defaults whenever the cinema contract is enabled."""
    return {
        "version": VERSION,
        "required_checks": list(CHECKS),
        "english_caption_max_chars_per_second": 16,
        "caption_minimum_seconds": 2,
        "caption_max_lines": 2,
        "english_caption_max_chars_per_line": 42,
        "actual_final_av_review_required": True,
        "every_shot_boundary_review_required": True,
    }


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def caption_issues(cues, *, locale, expected_text=None):
    """Check actual caption cards, not a cached 'readable' flag.

    Locale-specific typography still needs fluent review. English character
    limits must never be misrepresented as Malayalam reading-speed evidence.
    """
    issues, words, previous_end = [], [], 0
    english = str(locale).split("-")[0] == "en"
    if not cues:
        return ["finishing:captions_required"]
    for index, cue in enumerate(cues):
        label = f"finishing:caption_{index + 1}"
        start, end = cue.get("start_seconds"), cue.get("end_seconds")
        if not _finite(start) or not _finite(end) or not 0 <= start < end:
            issues.append(label + ":invalid_interval")
            continue
        if start < previous_end - 0.001:
            issues.append(label + ":overlap")
        previous_end = end
        text = str(cue.get("text", ""))
        lines = cue.get("lines") or text.splitlines()
        words.extend(text.split())
        if len(lines) > 2 or (english and any(len(line) > 42 for line in lines)):
            issues.append(label + ":layout")
        if end - start + 0.001 < 2:
            issues.append(label + ":too_brief")
        if english and len(" ".join(text.split())) / (end - start) > 16.01:
            issues.append(label + ":too_fast")
    if expected_text is not None and words != str(expected_text).split():
        issues.append("finishing:caption_words_must_match_ordered_screenplay_once")
    return issues


def review_issues(
    review,
    *,
    story_id,
    master_sha256,
    caption_sha256,
    board,
    storyboard_sha256,
    policy_sha256,
    locale,
    duration_seconds,
):
    """Validate explicit review evidence against this independent final film."""
    if not isinstance(review, dict):
        return ["finishing:actual_final_movie_review_required"]
    issues = []
    bindings = {
        "story_id": story_id,
        "master_sha256": master_sha256,
        "caption_sha256": caption_sha256,
        "storyboard_sha256": storyboard_sha256,
        "policy_sha256": policy_sha256,
        "locale": locale,
        "contract_version": VERSION,
    }
    if any(not value or review.get(key) != value for key, value in bindings.items()):
        issues.append("finishing:review_stale_or_wrong_story_media_locale_policy")
    if (
        review.get("status") != "passed"
        or review.get("method") != "actual_complete_movie_audio_video"
        or review.get("media_access_confirmed") is not True
        or not str(review.get("reviewer", "")).strip()
        or review.get("reviewer_kind") not in {"human", "ai", "assisted"}
        or not str(review.get("limitations", "")).strip()
        or review.get("unresolved_issues") != []
    ):
        issues.append(
            "finishing:honest_complete_av_review_and_issue_resolution_required"
        )
    checks = review.get("checks") or {}
    if not isinstance(checks, dict) or any(checks.get(k) is not True for k in CHECKS):
        issues.append("finishing:mandatory_creative_checks_incomplete")
    evidence = review.get("evidence_files")
    if not isinstance(evidence, list) or not evidence:
        issues.append("finishing:preserved_actual_review_evidence_required")
    else:
        for item in evidence:
            if not isinstance(item, dict):
                issues.append("finishing:review_evidence_missing_or_changed")
                continue
            path = Path(item.get("path") or "")
            if not path.is_file() or _sha(path) != item.get("sha256"):
                issues.append("finishing:review_evidence_missing_or_changed")
    observations = review.get("observations")
    if not isinstance(observations, list) or len(observations) < 3:
        issues.append("finishing:timed_actual_movie_observations_required")
    else:
        starts = []
        for item in observations:
            if not isinstance(item, dict):
                issues.append("finishing:invalid_observation_timestamp_or_event")
                continue
            start, end = item.get("start_seconds"), item.get("end_seconds")
            if (
                not _finite(start)
                or not _finite(end)
                or not _finite(duration_seconds)
                or not 0 <= start < end <= duration_seconds
                or not str(item.get("visible_and_audible_event", "")).strip()
            ):
                issues.append("finishing:invalid_observation_timestamp_or_event")
            else:
                starts.append(start)
        if len(set(starts)) < 3:
            issues.append("finishing:distinct_movie_observations_required")
        if _finite(duration_seconds) and (
            not any(t <= duration_seconds * 0.1 for t in starts)
            or not any(
                duration_seconds * 0.25 <= t <= duration_seconds * 0.75 for t in starts
            )
            or not any(t >= duration_seconds * 0.9 for t in starts)
        ):
            issues.append("finishing:beginning_middle_and_ending_observations_required")
    boundaries = review.get("boundary_reviews")
    shots = board.get("shots", [])
    if (
        not isinstance(boundaries, list)
        or any(not isinstance(r, dict) for r in boundaries)
        or [r.get("shot_id") for r in boundaries] != [s["shot_id"] for s in shots]
    ):
        return sorted(
            set(issues + ["finishing:every_ordered_shot_boundary_review_required"])
        )
    offset = 0
    for shot, item in zip(shots, boundaries):
        start, end = offset, offset + shot["duration_seconds"]
        offset = end
        if (
            not _finite(item.get("start_seconds"))
            or not _finite(item.get("end_seconds"))
            or abs(item["start_seconds"] - start) > 0.025
            or abs(item["end_seconds"] - end) > 0.025
            or not str(item.get("observed_boundary_detail", "")).strip()
            or any(
                item.get(k) is not True
                for k in (
                    "opening_pass",
                    "ending_pass",
                    "join_pass",
                    "unintended_speech_absent",
                    "clicks_and_truncation_absent",
                )
            )
        ):
            issues.append(f"finishing:{shot['shot_id']}:boundary_av_review_incomplete")
    if not _finite(duration_seconds) or abs(offset - duration_seconds) > 0.25:
        issues.append("finishing:reviewed_board_and_actual_master_duration_differ")
    return sorted(set(issues))


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
