"""Truthful, deterministic social packaging for Director Studio projects.

This module drafts metadata only. It never uploads or publishes content.
"""

from __future__ import annotations

import hashlib
import json
import math
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
_BROAD_SINGLE_WORD_TOPICS = {
    "child",
    "children",
    "kid",
    "kids",
    "moral",
    "story",
    "stories",
}
_VALID_RIGHTS = {"original", "licensed", "public_domain", "cleared", "not_used"}
_RIGHTS_CATEGORIES = {
    "source": {
        "source",
        "source_script_adaptation",
        "source_adaptation",
        "script",
        "story",
        "adaptation",
    },
    "visual": {"visual", "image", "video", "character_art"},
    "voice": {"voice", "narration", "dialogue"},
    "music_ambience": {"music_ambience", "music", "ambience", "sound", "sfx"},
}
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
    script_context = " ".join(
        _text(facts.get(field))
        for field in (
            "title",
            "script_text",
            "synopsis",
            "story_summary",
            "moral_or_learning_intent",
        )
    ).casefold()
    audience = facts.get("audience")
    audience_words: set[str] = set()
    if isinstance(audience, dict):
        age_max = audience.get("age_max")
        if audience.get("made_for_kids") is True or (
            isinstance(age_max, (int, float))
            and not isinstance(age_max, bool)
            and 0 < age_max <= 12
        ):
            audience_words.update({"child", "children", "kid", "kids"})
    candidates = [*_items(facts.get("topics")), *_items(facts.get("keywords"))]
    taxonomy_norm = {_normalize_words(value) for value in taxonomy_items}
    candidates.extend(taxonomy_items)
    candidates.append(_text(facts.get("moral_or_learning_intent")))
    accepted: list[str] = []
    for candidate in _items(candidates):
        words = _normalize_words(candidate)
        if not words or len(candidate) > 80 or len(words) > 6:
            continue
        if any(word in _TREND_WORDS for word in words):
            continue
        # Topic/keyword suggestions need at least one meaningful word supported
        # by the story text; taxonomy values are structured project facts.
        if _normalize_words(candidate) not in taxonomy_norm:
            meaningful_words = [word for word in words if word not in _STOP_WORDS]
            if not any(
                word in audience_words
                or (
                    len(word) >= 3
                    and re.search(rf"\b{re.escape(word)}\b", script_context)
                )
                for word in meaningful_words
            ):
                continue
        meaningful_words = [word for word in words if word not in _STOP_WORDS]
        if len(words) == 1 and words[0] in _BROAD_SINGLE_WORD_TOPICS:
            continue
        accepted.append(candidate)
        if len(accepted) >= 10:
            break
    return accepted


def _normalize_words(value: str) -> tuple[str, ...]:
    return tuple(word for word in _HASHTAG_WORDS.split(value.casefold()) if word)


def _hashtags(facts: dict[str, Any]) -> list[str]:
    """Make up to five narrow tags; explicit brand tokens precede story topics."""
    result: list[str] = []
    seen: set[str] = set()

    # Brand tags are accepted only when the caller supplies a literal short
    # token. This deliberately excludes phrases, URLs, calls to action, and
    # trend or performance claims.
    for raw_brand in _items(facts.get("brand_hashtags")):
        token = raw_brand[1:] if raw_brand.startswith("#") else raw_brand
        if (
            not re.fullmatch(r"[A-Za-z0-9_]{1,32}", token)
            or token.casefold() in _TREND_WORDS
            or _UNSUPPORTED_PROMISES.search(token)
        ):
            continue
        tag = f"#{token}"
        if tag.casefold() not in seen:
            result.append(tag)
            seen.add(tag.casefold())
        if len(result) == 1:
            # Keep the supplied brand identity while reserving four slots for
            # story-supported topics, even if several aliases were supplied.
            break

    taxonomy = facts.get("fiction_taxonomy")
    taxonomy_items = (
        [str(value) for value in taxonomy.values() if isinstance(value, str)]
        if isinstance(taxonomy, dict)
        else _items(taxonomy)
    )
    taxonomy_norm = {_normalize_words(value) for value in taxonomy_items}
    for topic in _normal_topics(facts):
        raw_words = [word for word in _HASHTAG_WORDS.split(topic.casefold()) if word]
        meaningful_words = [word for word in raw_words if word not in _STOP_WORDS]
        # Preserve story/stories in a meaningful genre phrase; stripping it
        # turns labels such as "Moral Stories" into invented tags like #Moral.
        preserve_story_word = len(raw_words) >= 2 and bool(meaningful_words)
        words = [
            word
            for word in raw_words
            if word not in _STOP_WORDS
            or (preserve_story_word and word in {"story", "stories"})
            or (_normalize_words(topic) in taxonomy_norm and word == "for")
        ]
        if not words or any(word in _TREND_WORDS for word in words):
            continue
        if len(words) == 1 and words[0] in _BROAD_SINGLE_WORD_TOPICS:
            continue
        tag = "#" + "".join(word[:1].upper() + word[1:] for word in words)
        if tag.casefold() not in seen:
            result.append(tag)
            seen.add(tag.casefold())
        if len(result) == 5:
            break
    return result


def _asset_status(
    asset: Any,
    verification_cache: dict[tuple[str, str, int, int, int], bool] | None = None,
) -> dict[str, Any]:
    if not isinstance(asset, dict):
        return {"path": None, "sha256": None, "verified": False}
    path = _text(asset.get("path"))
    claimed = _text(asset.get("sha256")).lower()
    if not path or not re.fullmatch(r"[a-f0-9]{64}", claimed):
        return {"path": path or None, "sha256": claimed or None, "verified": False}
    try:
        media_path = Path(path)
        stat_before = media_path.stat()
        cache_key = (
            str(media_path.resolve()),
            claimed,
            stat_before.st_ino,
            stat_before.st_size,
            stat_before.st_mtime_ns,
        )
        if verification_cache is not None and cache_key in verification_cache:
            return {
                "path": path,
                "sha256": claimed,
                "verified": verification_cache[cache_key],
            }
        digest_builder = hashlib.sha256()
        with media_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest_builder.update(chunk)
        digest = digest_builder.hexdigest()
        stat_after = media_path.stat()
        if (stat_before.st_ino, stat_before.st_size, stat_before.st_mtime_ns) != (
            stat_after.st_ino,
            stat_after.st_size,
            stat_after.st_mtime_ns,
        ):
            return {"path": path, "sha256": claimed, "verified": False}
    except OSError:
        return {"path": path, "sha256": claimed, "verified": False}
    verified = digest == claimed
    if verification_cache is not None:
        verification_cache[cache_key] = verified
    return {"path": path, "sha256": claimed, "verified": verified}


def _rights_status(evidence: Any) -> tuple[bool, list[str], dict[str, list[str]]]:
    queue: list[str] = []
    coverage = {category: [] for category in _RIGHTS_CATEGORIES}
    if not isinstance(evidence, (list, dict)) or not evidence:
        return (
            False,
            [
                "Document source/adaptation, visual, voice, and music/ambience rights evidence."
            ],
            coverage,
        )
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
        category_value = re.sub(
            r"[^a-z0-9]+",
            "_",
            _text(
                entry.get("category") or entry.get("asset_type") or entry.get("type")
            ).casefold(),
        ).strip("_")
        category = next(
            (
                name
                for name, aliases in _RIGHTS_CATEGORIES.items()
                if category_value in aliases
            ),
            None,
        )
        if category is None:
            queue.append(
                "Classify rights evidence as source/adaptation, visual, voice, or music/ambience."
            )
        else:
            coverage[category].append(status)
        if status not in _VALID_RIGHTS:
            queue.append(
                f"Resolve rights status for {_text(entry.get('source') or entry.get('label')) or 'an asset/source'}."
            )
        if not _text(entry.get("source") or entry.get("label") or entry.get("summary")):
            queue.append("Add a source or summary to each rights evidence entry.")
    if not found:
        queue.append(
            "Document source/adaptation, visual, voice, and music/ambience rights evidence."
        )
    for category, statuses in coverage.items():
        if not statuses:
            queue.append(
                f"Add a rights evidence entry for {category.replace('_', '/')} (use not_used only when explicitly applicable)."
            )
        elif any(status not in _VALID_RIGHTS for status in statuses):
            continue
    return not queue, queue, coverage


def _qa_passed(
    report: Any, story_id: str, script_sha256: str, master_sha256: str
) -> bool:
    if not isinstance(report, dict):
        return False
    passed = report.get("passed") is True or str(
        report.get("status", "")
    ).casefold() in {"passed", "pass", "approved"}
    return bool(
        passed
        and report.get("story_id") == story_id
        and report.get("script_sha256") == script_sha256
        and report.get("master_sha256") == master_sha256
    )


def _verified_chapters(
    facts: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    chapters = facts.get("chapters")
    if not isinstance(chapters, list):
        return [], None
    if not chapters:
        return [], None
    verified: list[dict[str, Any]] = []
    previous = -1.0
    duration = facts.get("duration_seconds")
    duration_verified = facts.get("duration_verified") is True
    if duration is None and isinstance(facts.get("master"), dict):
        duration = facts["master"].get("duration_seconds")
        duration_verified = facts["master"].get("duration_verified") is True
    if duration is not None and not duration_verified:
        return (
            [],
            "Duration is not verified; chapter timings within the video need review.",
        )
    if duration is not None and (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        return [], "Duration is invalid; chapter timings need review."
    for chapter in chapters:
        if not isinstance(chapter, dict) or chapter.get("timing_verified") is not True:
            return [], "Chapter timings are not verified; chapters were omitted."
        seconds = chapter.get("seconds")
        title = _text(chapter.get("title"))
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
            or seconds <= previous
            or not title
            or (duration is not None and seconds >= duration)
        ):
            return (
                [],
                "Chapter timings must be finite, strictly increasing, unique, and within the verified duration.",
            )
        verified.append({"seconds": seconds, "title": title})
        previous = seconds
    return verified, None


def _youtube_chapters(
    chapters: list[dict[str, Any]], duration_seconds: int | float | None
) -> tuple[list[dict[str, Any]], str | None]:
    if not chapters:
        return [], None
    if duration_seconds is None:
        return [], "YouTube chapter segment lengths need a verified video duration."
    seconds = [item["seconds"] for item in chapters]
    if (
        seconds[0] != 0
        or len(seconds) < 3
        or any(right - left < 10 for left, right in zip(seconds, seconds[1:]))
        or duration_seconds - seconds[-1] < 10
    ):
        return (
            [],
            "YouTube chapters need a 0:00 start, at least three entries, and at least 10 seconds per segment.",
        )
    return chapters, None


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
    selected_platforms = tuple(dict.fromkeys(platforms))
    if not selected_platforms:
        raise ValueError("At least one platform is required")
    story_id = _text(story_facts.get("story_id"))
    title = _text(story_facts.get("title"))
    raw_script = story_facts.get("script_text")
    script = _text(raw_script)
    if not story_id or not title or not script:
        raise ValueError("story_id, title, and script_text are required")

    script_sha256 = hashlib.sha256(raw_script.encode("utf-8")).hexdigest()
    asset_verification_cache: dict[tuple[str, str, int, int, int], bool] = {}
    master = _asset_status(story_facts.get("master"), asset_verification_cache)
    captions = _asset_status(story_facts.get("captions"), asset_verification_cache)
    captions_locale_match = story_facts.get("captions_locale_match") is True
    rights_ok, rights_queue, rights_coverage = _rights_status(
        story_facts.get("source_evidence")
    )
    qa_ok = _qa_passed(
        story_facts.get("qa_report"), story_id, script_sha256, master["sha256"] or ""
    )
    audience = (
        story_facts.get("audience")
        if isinstance(story_facts.get("audience"), dict)
        else {}
    )
    made_for_kids = audience.get("made_for_kids")
    audience_reviewed = audience.get("reviewed") is True and isinstance(
        made_for_kids, bool
    )
    if not audience_reviewed:
        audience_queue = [
            "Human review: determine the accurate made-for-kids audience setting and record audience.reviewed=true."
        ]
    else:
        audience_queue = []

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
    chapters, chapter_issue = _verified_chapters(story_facts)
    chapter_duration = None
    if story_facts.get("duration_verified") is True:
        chapter_duration = story_facts.get("duration_seconds")
    elif (
        isinstance(story_facts.get("master"), dict)
        and story_facts["master"].get("duration_verified") is True
    ):
        chapter_duration = story_facts["master"].get("duration_seconds")
    if chapter_issue:
        queue_chapter = [chapter_issue]
    else:
        queue_chapter = []
    platform_assets_input = story_facts.get("platform_assets")
    if not isinstance(platform_assets_input, dict):
        platform_assets_input = {}
    platform_captions_input = story_facts.get("platform_captions")
    if not isinstance(platform_captions_input, dict):
        platform_captions_input = {}
    platform_asset_status: dict[str, dict[str, Any]] = {}
    platform_caption_status: dict[str, dict[str, Any]] = {}
    for platform in selected_platforms:
        if platform not in DEFAULT_PLATFORMS:
            raise ValueError(f"Unsupported platform: {platform}")
        asset = _asset_status(
            platform_assets_input.get(platform), asset_verification_cache
        )
        asset["variant_reviewed"] = (
            platform_assets_input.get(platform, {}).get("variant_reviewed") is True
            if isinstance(platform_assets_input.get(platform), dict)
            else False
        )
        asset["audience_reviewed"] = (
            platform_assets_input.get(platform, {}).get("audience_reviewed") is True
            if isinstance(platform_assets_input.get(platform), dict)
            else False
        )
        platform_asset_status[platform] = asset
        caption = _asset_status(
            platform_captions_input.get(platform), asset_verification_cache
        )
        caption_data = platform_captions_input.get(platform)
        caption["locale_match"] = (
            isinstance(caption_data, dict) and caption_data.get("locale_match") is True
        )
        caption["language_reviewed"] = (
            isinstance(caption_data, dict)
            and caption_data.get("language_reviewed") is True
        )
        caption["media_sha256"] = (
            caption_data.get("media_sha256") if isinstance(caption_data, dict) else None
        )
        caption["bound_to_variant"] = caption["media_sha256"] == asset.get(
            "sha256"
        ) and bool(asset.get("sha256"))
        platform_caption_status[platform] = caption
    queue: list[str] = []
    if not master["verified"]:
        queue.append(
            "Provide a master asset path and matching SHA-256 before final approval."
        )
    if not captions["verified"]:
        queue.append(
            "Provide a captions artifact path and matching SHA-256, or record a reviewed reason captions are unavailable."
        )
    if not captions_locale_match:
        queue.append(
            "Caption locale must be fluent-reviewed and match the story target and audio locale."
        )
    if not all(
        item["verified"]
        and item["locale_match"]
        and item["language_reviewed"]
        and item["bound_to_variant"]
        for item in platform_caption_status.values()
    ):
        queue.append(
            "Provide a fluent-reviewed caption track with matching locale for every selected localized media variant."
        )
    if not qa_ok:
        queue.append(
            "Complete final creative QA bound to this story_id, script SHA-256, and master SHA-256."
        )
    queue.extend(rights_queue)
    queue.extend(audience_queue)
    queue.extend(ai_queue)
    queue.extend(queue_chapter)
    if not audience_reviewed:
        queue.append("Audience setting is not reviewed for this package.")
    if not all(
        asset["verified"] and asset["variant_reviewed"] and asset["audience_reviewed"]
        for asset in platform_asset_status.values()
    ):
        queue.append(
            "Review a matching platform-specific media asset and audience settings for every selected platform."
        )

    tags = _hashtags(story_facts)
    keywords = _normal_topics(story_facts)
    platforms_out: dict[str, Any] = {}
    for platform in selected_platforms:
        rendered_title = _title(story_facts, platform)
        description = _description(story_facts, platform, tags)
        platform_queue = list(queue)
        media_asset = platform_asset_status[platform]
        caption_asset = platform_caption_status[platform]
        if not media_asset["verified"]:
            platform_queue.append(
                f"Provide a verified platform-specific media asset for {platform}."
            )
        if not media_asset["variant_reviewed"]:
            platform_queue.append(
                f"Review the {platform} media variant against its format and story continuity."
            )
        if not media_asset["audience_reviewed"]:
            platform_queue.append(
                f"Review audience and child-directed settings for {platform}."
            )
        if not (
            caption_asset["verified"]
            and caption_asset["locale_match"]
            and caption_asset["language_reviewed"]
            and caption_asset["bound_to_variant"]
        ):
            platform_queue.append(
                f"Provide fluent-reviewed captions matching the story/audio locale and exact {platform} variant."
            )
        if _UNSUPPORTED_PROMISES.search(rendered_title) and not any(
            term.casefold() in script.casefold()
            for term in _UNSUPPORTED_PROMISES.findall(rendered_title)
        ):
            platform_queue.append(
                "Review title: it contains a high-risk promise or factual hook not evidenced by the script."
            )
        platform_chapters = chapters
        platform_chapter_issue = None
        if platform == "youtube_long":
            platform_chapters, platform_chapter_issue = _youtube_chapters(
                chapters, chapter_duration
            )
        elif platform == "youtube_short":
            platform_chapters = []
        if platform_chapter_issue:
            platform_queue.append(platform_chapter_issue)
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
            "chapters": platform_chapters,
            "media_asset": media_asset,
            "caption_asset": caption_asset,
            "ready_for_manual_handoff": False,
            "thumbnail_brief": _text(story_facts.get("thumbnail_brief")) or None,
            "title_hook_promise_check": {
                "status": "review_required"
                if _UNSUPPORTED_PROMISES.search(rendered_title)
                else "no_flagged_promise",
                "title": rendered_title,
                "script_evidence_available": bool(script),
                "note": "This check flags wording for human review; it does not certify factual accuracy.",
            },
            "captions_path": caption_asset["path"],
            "platform_strategy": _PLATFORM_STRATEGY[platform],
            "review_queue": list(dict.fromkeys(platform_queue)),
            "documented_limits": PLATFORM_LIMITS.get(platform, {}),
        }

    package = {
        "schema_version": 1,
        "story_id": story_id,
        "title": title,
        "script_sha256": script_sha256,
        "metadata_only": True,
        "publishing": "manual_handoff_only",
        "master": master,
        "captions": captions,
        "audience": {
            "made_for_kids": made_for_kids,
            "language": _text(audience.get("language")) or None,
        },
        "ai_realistic_content_review": ai_status
        if isinstance(ai_status, str)
        else "human_review_required",
        "platforms": platforms_out,
        "required_approval": {
            "final_creative_qa_passed": qa_ok,
            "qa_bound_to_story_script_and_master": qa_ok,
            "asset_sha256_verified": master["verified"],
            "captions_sha256_verified": captions["verified"],
            "captions_locale_matches_story_and_audio": captions_locale_match,
            "platform_caption_tracks_verified": all(
                item["verified"]
                and item["locale_match"]
                and item["language_reviewed"]
                and item["bound_to_variant"]
                for item in platform_caption_status.values()
            ),
            "source_and_music_rights_resolved": rights_ok,
            "rights_coverage": rights_coverage,
            "made_for_kids_reviewed": audience_reviewed,
            "realistic_ai_disclosure_reviewed": ai_reviewed,
            "platform_assets_and_audiences_reviewed": all(
                asset["verified"]
                and asset["variant_reviewed"]
                and asset["audience_reviewed"]
                for asset in platform_asset_status.values()
            ),
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

    readiness_checks = package["required_approval"]
    readiness_checks_passed = (
        all(
            value is True
            for key, value in readiness_checks.items()
            if key != "rights_coverage"
        )
        and rights_ok
    )
    approval_record_matches = bool(
        isinstance(approval, dict)
        and approval.get("master_sha256") == master["sha256"]
        and approval.get("package_sha256") == package_hash
        and master["verified"]
    )
    approval_valid = approval_record_matches and readiness_checks_passed
    package["approval"] = {
        "approval_record_matches_exact_package": approval_record_matches,
        "verified_for_exact_master_and_package": approval_valid,
        "status": (
            "approved_for_manual_handoff"
            if approval_valid
            else "recorded_but_blocked"
            if approval_record_matches
            else "approval_required"
        ),
    }
    package["metadata_copy_review_status"] = (
        "owner_approved_for_exact_package"
        if approval_record_matches
        else "review_required"
    )
    if not approval_record_matches:
        package["review_queue"].append(
            "Owner approval must match this exact package SHA-256 and master SHA-256."
        )
    package["readiness"] = {
        "required_checks_passed": readiness_checks_passed,
        "owner_approval_matches": approval_valid,
        "ready_for_manual_handoff": approval_valid and readiness_checks_passed,
        "ready_for_publication": False,
        "status": "ready_for_manual_handoff"
        if approval_valid and readiness_checks_passed
        else "review_required",
    }
    package["review_status"] = (
        "approved" if approval_record_matches else "owner_approval_required"
    )
    for item in package["platforms"].values():
        item["ready_for_manual_handoff"] = bool(approval_valid)
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
