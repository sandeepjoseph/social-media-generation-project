"""Truthful, deterministic social packaging for Director Studio projects.

This module drafts metadata only. It never uploads or publishes content.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

DEFAULT_PLATFORMS = (
    "youtube_long",
    "youtube_short",
    "facebook_reels",
    "instagram_reels",
    "tiktok",
    "dailymotion",
    "rumble",
)

PLATFORM_LIMITS = {
    # API-documented limits only. Other platform limits remain unspecified here.
    "youtube_long": {
        "title_chars": 100,
        "description_utf8_bytes": 5000,
        "keyword_chars": 500,
    },
    "youtube_short": {
        "title_chars": 100,
        "description_utf8_bytes": 5000,
        "keyword_chars": 500,
    },
    "dailymotion": {"title_chars": 255, "description_chars": 3000},
}

_UNSUPPORTED_PROMISES = re.compile(
    r"\b(guaranteed?|shocking|unbelievable|secret(?:s)?|true story|real story|"
    r"make money|earn money|millionaire|billionaire|viral|instant(?:ly)?)\b",
    re.IGNORECASE,
)
_HASHTAG_WORDS = re.compile(r"[^\w]+", re.UNICODE)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "story",
    "stories",
}
_TREND_WORDS = {
    "viral",
    "fyp",
    "foryou",
    "trending",
    "explore",
    "follow",
    "like",
    "subscribe",
}
_VALID_RIGHTS = {"original", "licensed", "public_domain", "cleared"}
_PLATFORM_STRATEGY = {
    "youtube_long": "Use a truthful title and thumbnail that match the story; include chapters only when timings are verified.",
    "youtube_short": "Keep the story premise legible in the opening and ensure the title describes the actual Short.",
    "facebook_reels": "Review the audience selector and description in the Facebook composer before posting.",
    "instagram_reels": "Review the current composer limits and confirm music is licensed for this account and use.",
    "tiktok": "Complete the draft in TikTok and apply any required AI or commercial-content disclosures there.",
    "dailymotion": "Confirm category, visibility, and the explicit child-directed setting in the upload flow.",
    "rumble": "Use a human upload handoff and verify caption/subtitle support and metadata in the current interface.",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _items(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return list(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


def _normal_topics(facts: dict[str, Any]) -> list[str]:
    taxonomy = facts.get("fiction_taxonomy")
    if isinstance(taxonomy, dict):
        taxonomy_items = [
            str(value) for value in taxonomy.values() if isinstance(value, str)
        ]
    else:
        taxonomy_items = _items(taxonomy)
    return _items(
        [
            *_items(facts.get("topics")),
            *_items(facts.get("keywords")),
            *taxonomy_items,
            _text(facts.get("moral_or_learning_intent")),
        ]
    )


def _hashtags(facts: dict[str, Any]) -> list[str]:
    """Make up to five narrow tags from facts; never inject trending tags."""
    result: list[str] = []
    seen: set[str] = set()
    for topic in _normal_topics(facts):
        words = [word for word in _HASHTAG_WORDS.split(topic.casefold()) if word]
        words = [word for word in words if word not in _STOP_WORDS]
        if not words or any(word in _TREND_WORDS for word in words):
            continue
        tag = "#" + "".join(word[:1].upper() + word[1:] for word in words)
        if tag.casefold() not in seen:
            result.append(tag)
            seen.add(tag.casefold())
        if len(result) == 5:
            break
    return result


def _asset_status(asset: Any) -> dict[str, Any]:
    if not isinstance(asset, dict):
        return {"path": None, "sha256": None, "verified": False}
    path = _text(asset.get("path"))
    claimed = _text(asset.get("sha256")).lower()
    if not path or not re.fullmatch(r"[a-f0-9]{64}", claimed):
        return {"path": path or None, "sha256": claimed or None, "verified": False}
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return {"path": path, "sha256": claimed, "verified": False}
    return {"path": path, "sha256": claimed, "verified": digest == claimed}


def _rights_status(evidence: Any) -> tuple[bool, list[str]]:
    queue: list[str] = []
    if not isinstance(evidence, (list, dict)) or not evidence:
        return False, ["Document source, copyright, and music rights evidence."]
    entries = evidence.values() if isinstance(evidence, dict) else evidence
    found = False
    for entry in entries:
        if not isinstance(entry, dict):
            queue.append(
                "Review source evidence entry; expected a structured rights status."
            )
            continue
        found = True
        status = _text(entry.get("rights_status") or entry.get("status")).casefold()
        if status not in _VALID_RIGHTS:
            queue.append(
                f"Resolve rights status for {_text(entry.get('source') or entry.get('label')) or 'an asset/source'}."
            )
    if not found:
        queue.append("Document source, copyright, and music rights evidence.")
    return not queue, queue


def _qa_passed(report: Any) -> bool:
    return isinstance(report, dict) and (
        report.get("passed") is True
        or str(report.get("status", "")).casefold() in {"passed", "pass", "approved"}
    )


def _verified_chapters(facts: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = facts.get("chapters")
    if not isinstance(chapters, list):
        return []
    verified: list[dict[str, Any]] = []
    for chapter in chapters:
        if not isinstance(chapter, dict) or chapter.get("timing_verified") is not True:
            return []
        seconds = chapter.get("seconds")
        title = _text(chapter.get("title"))
        if not isinstance(seconds, (int, float)) or seconds < 0 or not title:
            return []
        verified.append({"seconds": int(seconds), "title": title})
    return verified


def _description(facts: dict[str, Any], platform: str, hashtags: list[str]) -> str:
    supplied = (
        _text(facts.get("platform_descriptions", {}).get(platform))
        if isinstance(facts.get("platform_descriptions"), dict)
        else ""
    )
    if supplied:
        return supplied
    title = _text(facts.get("title"))
    intent = _text(facts.get("moral_or_learning_intent"))
    synopsis = _text(facts.get("synopsis") or facts.get("story_summary"))
    # Source status is often unavailable at packaging time, so do not imply
    # that a folklore adaptation is newly original; use neutral wording.
    parts = [synopsis] if synopsis else [f"Story: {title}."]
    if intent:
        parts.append(f"Story theme: {intent}.")
    if hashtags:
        parts.append(" ".join(hashtags))
    return "\n\n".join(parts)


def _title(facts: dict[str, Any], platform: str) -> str:
    overrides = facts.get("platform_titles")
    if isinstance(overrides, dict) and _text(overrides.get(platform)):
        return _text(overrides[platform])
    title = _text(facts.get("title"))
    if platform == "youtube_short":
        return title
    return title


def _metadata_limits(
    platform: str, title: str, description: str, keywords: list[str]
) -> list[str]:
    limits = PLATFORM_LIMITS.get(platform, {})
    issues: list[str] = []
    if limits.get("title_chars") and len(title) > limits["title_chars"]:
        issues.append(
            f"Title exceeds documented {limits['title_chars']}-character limit."
        )
    if (
        limits.get("description_utf8_bytes")
        and len(description.encode("utf-8")) > limits["description_utf8_bytes"]
    ):
        issues.append(
            f"Description exceeds documented {limits['description_utf8_bytes']}-byte limit."
        )
    if (
        limits.get("description_chars")
        and len(description) > limits["description_chars"]
    ):
        issues.append(
            f"Description exceeds documented {limits['description_chars']}-character limit."
        )
    if limits.get("keyword_chars"):
        # YouTube counts comma separators and treats whitespace-containing tags as quoted.
        size = sum(len(word) + (2 if " " in word else 0) for word in keywords) + max(
            0, len(keywords) - 1
        )
        if size > limits["keyword_chars"]:
            issues.append(
                f"Keywords exceed documented {limits['keyword_chars']}-character total."
            )
    return issues


def package_story(
    story_facts: dict[str, Any],
    platforms: Sequence[str] = DEFAULT_PLATFORMS,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, reviewable metadata package; never publish it.

    ``approval`` must carry ``master_sha256`` and ``package_sha256`` matching the
    current verified master and this package's canonical hash. The hash excludes
    approval fields so the approval itself does not make the package hash circular.
    """
    if not isinstance(story_facts, dict):
        raise TypeError("story_facts must be a dictionary")
    story_id = _text(story_facts.get("story_id"))
    title = _text(story_facts.get("title"))
    script = _text(story_facts.get("script_text"))
    if not story_id or not title or not script:
        raise ValueError("story_id, title, and script_text are required")

    master = _asset_status(story_facts.get("master"))
    captions = _asset_status(story_facts.get("captions"))
    rights_ok, rights_queue = _rights_status(story_facts.get("source_evidence"))
    qa_ok = _qa_passed(story_facts.get("qa_report"))
    audience = (
        story_facts.get("audience")
        if isinstance(story_facts.get("audience"), dict)
        else {}
    )
    made_for_kids = audience.get("made_for_kids")
    if not isinstance(made_for_kids, bool):
        audience_queue = [
            "Human review: determine the accurate made-for-kids audience setting."
        ]
    else:
        audience_queue = []
    if made_for_kids is True:
        audience_queue.append(
            "Confirm child-directed platform settings and age-appropriate metadata."
        )

    ai_status = story_facts.get("ai_realistic_content")
    ai_reviewed = isinstance(ai_status, str) and ai_status in {
        "not_applicable",
        "disclosed",
        "reviewed_not_required",
    }
    ai_queue = (
        []
        if ai_reviewed
        else [
            "Human review: assess whether realistic AI-generated or altered media requires platform disclosure."
        ]
    )
    queue: list[str] = []
    if not master["verified"]:
        queue.append(
            "Provide a master asset path and matching SHA-256 before final approval."
        )
    if not captions["verified"]:
        queue.append(
            "Provide a captions artifact path and matching SHA-256, or record a reviewed reason captions are unavailable."
        )
    if not qa_ok:
        queue.append("Complete and pass final creative QA.")
    queue.extend(rights_queue)
    queue.extend(audience_queue)
    queue.extend(ai_queue)

    tags = _hashtags(story_facts)
    keywords = _normal_topics(story_facts)
    platforms_out: dict[str, Any] = {}
    for platform in dict.fromkeys(platforms):
        if platform not in DEFAULT_PLATFORMS:
            raise ValueError(f"Unsupported platform: {platform}")
        rendered_title = _title(story_facts, platform)
        description = _description(story_facts, platform, tags)
        platform_queue = list(queue)
        if _UNSUPPORTED_PROMISES.search(rendered_title) and not any(
            term.casefold() in script.casefold()
            for term in _UNSUPPORTED_PROMISES.findall(rendered_title)
        ):
            platform_queue.append(
                "Review title: it contains a high-risk promise or factual hook not evidenced by the script."
            )
        platform_queue.extend(
            _metadata_limits(platform, rendered_title, description, keywords)
        )
        platform_queue.append(
            "Review captions, thumbnail, copyright/music evidence, and platform-native audience/disclosure controls."
        )
        platforms_out[platform] = {
            "title": rendered_title,
            "description": description,
            "hashtags": tags,
            "keywords": keywords,
            "chapters": _verified_chapters(story_facts),
            "thumbnail_brief": _text(story_facts.get("thumbnail_brief")) or None,
            "title_hook_promise_check": {
                "status": "review_required"
                if _UNSUPPORTED_PROMISES.search(rendered_title)
                else "no_flagged_promise",
                "title": rendered_title,
                "script_evidence_available": bool(script),
                "note": "This check flags wording for human review; it does not certify factual accuracy.",
            },
            "captions_path": captions["path"],
            "platform_strategy": _PLATFORM_STRATEGY[platform],
            "review_queue": list(dict.fromkeys(platform_queue)),
            "documented_limits": PLATFORM_LIMITS.get(platform, {}),
        }

    package = {
        "schema_version": 1,
        "story_id": story_id,
        "title": title,
        "metadata_only": True,
        "publishing": "manual_handoff_only",
        "master": master,
        "captions": captions,
        "audience": {
            "made_for_kids": made_for_kids,
            "language": _text(audience.get("language")) or None,
        },
        "ai_realistic_content_review": ai_status or "human_review_required",
        "platforms": platforms_out,
        "required_approval": {
            "final_creative_qa_passed": qa_ok,
            "asset_sha256_verified": master["verified"],
            "captions_sha256_verified": captions["verified"],
            "source_and_music_rights_resolved": rights_ok,
            "made_for_kids_reviewed": isinstance(made_for_kids, bool),
            "realistic_ai_disclosure_reviewed": ai_reviewed,
        },
        "review_queue": list(dict.fromkeys(queue)),
        "strategy": {
            "basis": "story facts and platform documentation; no reach or monetization guarantee",
            "experiments": [
                "Compare two truthful title/thumbnail treatments while holding the story and audience constant.",
                "Record impressions, click-through rate, watch time, completions, and production credits per accepted minute.",
            ],
            "no_fake_engagement": True,
            "no_duplicate_backup_uploads": True,
            "no_forced_child_engagement": True,
        },
    }
    canonical = json.dumps(
        package, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    package_hash = hashlib.sha256(canonical).hexdigest()
    package["package_sha256"] = package_hash

    approval_valid = bool(
        isinstance(approval, dict)
        and approval.get("master_sha256") == master["sha256"]
        and approval.get("package_sha256") == package_hash
        and master["verified"]
    )
    package["approval"] = {
        "verified_for_exact_master_and_package": approval_valid,
        "status": "approved_for_manual_handoff"
        if approval_valid
        else "approval_required",
    }
    if not approval_valid:
        package["review_queue"].append(
            "Owner approval must match this exact package SHA-256 and master SHA-256."
        )
    return package


ANALYTICS_CSV_COLUMNS = (
    "story_id",
    "platform",
    "variant",
    "published_at",
    "impressions",
    "click_through_rate",
    "watch_time_seconds",
    "completions",
    "production_credits",
    "accepted_minutes",
    "source",
    "notes",
)
