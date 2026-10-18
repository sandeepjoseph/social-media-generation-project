"""Prepare readable English caption candidates without changing actor timing.

This is a local editorial suggestion, not a language/visual review or permission
to publish. Sources and every spoken word remain unchanged.
"""

import copy
import math
import textwrap

from app.services import studio_native_movie as movie


def prepare_caption_plan(board, plan, *, chars_per_second=16, minimum_seconds=2):
    """Merge orphan cards and extend them into existing pauses; hold if cramped."""
    for value in (chars_per_second, minimum_seconds):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(
                "Caption readability targets must be positive finite numbers"
            )
    if plan.get("locale") != "en":
        raise ValueError(
            "Localized captions require fluent-reviewed line breaks and timing"
        )
    issues = movie.validate_plan(board, plan, require_sequence_review=False)
    if issues:
        raise ValueError("; ".join(issues))
    result = copy.deepcopy(plan)
    changes, held = [], []
    for entry in result["shots"]:
        if not entry.get("dialogue"):
            continue
        movie.reviewed_caption_cues(entry, locale="en")
        original = copy.deepcopy(
            entry.get("caption_cues")
            or [
                {
                    "start": entry["caption_start"],
                    "end": entry["caption_end"],
                    "text": entry["dialogue"],
                }
            ]
        )
        cues = copy.deepcopy(original)
        if (
            len(
                textwrap.wrap(
                    entry["dialogue"],
                    width=42,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
            <= 2
        ):
            cues = [
                {
                    "start": cues[0]["start"],
                    "end": cues[-1]["end"],
                    "text": entry["dialogue"],
                }
            ]
        for index, cue in enumerate(cues):
            limit = (
                cues[index + 1]["start"] - 0.01
                if index + 1 < len(cues)
                else entry["duration_seconds"] - 0.05
            )
            desired = cue["start"] + max(
                minimum_seconds, len(cue["text"]) / chars_per_second
            )
            cue["end"] = round(max(cue["end"], min(limit, desired)), 6)
            if cue["end"] + 0.001 < desired:
                held.append(
                    {
                        "shot_id": entry["shot_id"],
                        "text": cue["text"],
                        "reason": "Insufficient existing pause for readability; explicitly replan the caption/shot, never stretch actor speech",
                    }
                )
        entry.update(
            caption_cues=cues,
            caption_start=cues[0]["start"],
            caption_end=cues[-1]["end"],
        )
        movie.reviewed_caption_cues(entry, locale="en")
        if cues != original:
            changes.append(
                {
                    "shot_id": entry["shot_id"],
                    "before": original,
                    "after": copy.deepcopy(cues),
                }
            )
    result.update(
        status="caption_readability_candidate_pending_actual_review",
        publication_allowed=False,
        sequence_review_path=None,
    )
    result.pop("sequence_review_sha256", None)
    result["caption_readability"] = {
        "chars_per_second_target": chars_per_second,
        "minimum_display_seconds": minimum_seconds,
        "changes": changes,
        "held": held,
        "actual_review_required": True,
        "voice_replaced": False,
        "shot_retimed": False,
    }
    remaining = movie.validate_plan(board, result, require_sequence_review=False)
    assert remaining == (
        ["Caption readability requires explicit editorial replanning"] if held else []
    )
    return result
