"""Local, evidence-bound YouTube discovery preparation; no ranking promises.

No provider calls, scraping, uploads or automatic monitoring. Search observations
are separate from creative approvals and must describe what was actually seen.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

SOURCES = {
    "search_visibility": "https://support.google.com/youtube/answer/58097?hl=en",
    "descriptions": "https://support.google.com/youtube/answer/12948449?hl=en",
    "tags": "https://support.google.com/youtube/answer/146402?hl=en",
    "ranking": "https://support.google.com/youtube/answer/141805?hl=en",
}
DEFAULT_POLICY = {
    "required": True,
    "lead_characters": 300,
    "subject_aliases": [],
    "basis": "Relevant title, unique story description and accurate content; no forced indexing or guaranteed ranking.",
    "sources": SOURCES,
}
_FORBIDDEN = re.compile(
    r"\b(viral|fyp|trending|guaranteed|rank\s*1|number\s*one|millionaire)\b", re.I
)


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _norm(value):
    return " ".join(re.findall(r"\w+", _text(value).casefold()))


def _contains(text, phrase):
    return bool(_norm(phrase)) and f" {_norm(phrase)} " in f" {_norm(text)} "


def _phrase(value):
    value = _text(value)
    if (
        not value
        or len(value) > 100
        or len(value.split()) > 16
        or not re.fullmatch(r"[\w\s'’&:,.?()–—-]+", value)
        or _FORBIDDEN.search(value)
    ):
        raise ValueError(
            "Search phrases must be short, relevant text without promotion or URLs"
        )
    return value


def search_brief(facts):
    """Bind one main topic and an episode phrase to actual story text.

    Alias groups are trusted private editorial configuration, activated only
    when their subject or a declared variant occurs in this story. Request-level
    aliases cannot introduce unrelated characters or popular queries.
    """
    policy = facts.get("search_policy") or {}
    supplied = facts.get("search_brief") or {}
    if not isinstance(policy, dict) or not isinstance(supplied, dict):
        raise ValueError("Search policy and brief require objects")
    if set(supplied) - {"primary_query", "episode_query", "aliases"}:
        raise ValueError(
            "Search brief accepts primary_query, episode_query and aliases only"
        )
    context = " ".join(
        _text(facts.get(key))
        for key in ("title", "script_text", "synopsis", "story_summary")
    )
    groups = policy.get("subject_aliases") or []
    if not isinstance(groups, list):
        raise ValueError("subject_aliases requires a list")
    matched = None
    for group in groups:
        if not isinstance(group, dict) or not isinstance(
            group.get("aliases", []), list
        ):
            raise ValueError("Subject alias groups require a subject and aliases list")
        subject = _phrase(group.get("subject"))
        aliases = [_phrase(item) for item in group.get("aliases", [])]
        if any(_contains(context, item) for item in [subject, *aliases]):
            matched = (subject, aliases)
            break
    primary = _phrase(
        supplied.get("primary_query") or (matched[0] if matched else facts.get("title"))
    )
    episode = _phrase(supplied.get("episode_query") or facts.get("title"))
    allowed = matched[1] if matched and _norm(primary) == _norm(matched[0]) else []
    if not _contains(context, primary) and not (
        matched and _norm(primary) == _norm(matched[0])
    ):
        raise ValueError("Primary search query is not supported by this story")
    if not _contains(context, episode):
        raise ValueError("Episode search query is not supported by this story")
    aliases = supplied.get("aliases", allowed)
    if not isinstance(aliases, list) or len(aliases) > 6:
        raise ValueError("Use at most six story-relevant spelling aliases")
    aliases = list(dict.fromkeys(_phrase(item) for item in aliases))
    if any(
        not _contains(context, item) and _norm(item) not in {_norm(a) for a in allowed}
        for item in aliases
    ):
        raise ValueError(
            "Search alias is not supported by the story or its configured subject"
        )
    return {
        "primary_query": primary,
        "episode_query": episode,
        "aliases": aliases,
        "language": _text((facts.get("audience") or {}).get("language")) or None,
        "basis": "story text and explicit editorial alias policy; search volume is unknown",
        "search_volume": None,
    }


def youtube_keywords(brief, topics, producer_keywords):
    """Reserve required company tags, then add relevant subject/story variants.

    Tags mainly help spelling variants. Title, description and actual viewer
    response matter more. Never truncate a tag or silently omit required credits.
    """
    required = list(dict.fromkeys(producer_keywords))
    candidates = [
        brief["primary_query"],
        brief["episode_query"],
        *brief["aliases"],
        *topics,
    ]
    result = list(required)
    for item in candidates:
        if _norm(item) in {_norm(x) for x in result}:
            continue
        proposed = [*result, item]
        if keyword_size(proposed) <= 500:
            result.append(item)
    required_norm = {_norm(x) for x in required}
    return [x for x in result if _norm(x) not in required_norm] + required


def keyword_size(keywords):
    return sum(len(item) + (2 if " " in item else 0) for item in keywords) + max(
        0, len(keywords) - 1
    )


def youtube_preflight(facts, title, description, keywords, *, brief=None):
    brief = brief or search_brief(facts)
    policy = facts.get("search_policy") or {}
    lead_chars = policy.get("lead_characters", 300)
    if (
        isinstance(lead_chars, bool)
        or not isinstance(lead_chars, int)
        or not 100 <= lead_chars <= 500
    ):
        raise ValueError("Search lead_characters must be between 100 and 500")
    lead = description[:lead_chars].split("\n\n")[0]
    # Require the story's own episode phrase in the title or descriptive body,
    # excluding the corporate credit/hashtags. A generic channel footer cannot
    # satisfy episode relevance.
    story_body = description.split(_text(facts.get("production_credit_line")) or "\0")[
        0
    ]
    checks = {
        "main_topic_in_title": _contains(title, brief["primary_query"]),
        "main_topic_in_opening_description": _contains(lead, brief["primary_query"]),
        "episode_context_present": _contains(
            title + " " + story_body, brief["episode_query"]
        ),
        "title_within_100_characters": 0 < len(title) <= 100,
        "description_within_5000_utf8_bytes": 0
        < len(description.encode("utf-8"))
        <= 5000,
        "tags_within_500_character_budget": keyword_size(keywords) <= 500,
        "no_search_or_reach_promise": not bool(_FORBIDDEN.search(title + " " + lead)),
    }
    query = brief["primary_query"] + " " + brief["episode_query"]
    metadata_hash = hashlib.sha256(
        json.dumps(
            {"title": title, "description": description, "keywords": keywords},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "required": policy.get("required") is True,
        "passed": all(checks.values()),
        "checks": checks,
        "brief": brief,
        "metadata_sha256": metadata_hash,
        "index_status": "not_observed",
        "ranking_status": "not_measured",
        "search_test_url": "https://www.youtube.com/results?"
        + urlencode({"search_query": query}),
        "post_publication_checks": [
            "Verify the exact video ID, Public visibility, completed processing, and Studio restrictions/errors.",
            "Test the exact video ID, channel plus episode, then broader subject/story queries; record actual results and context separately.",
            "Allow a few days for new uploads or metadata changes to appear; YouTube controls indexing and ranking.",
            "Use Studio Analytics YouTube Search terms, impressions, CTR and retention to guide a measured title/thumbnail experiment; unavailable data stays unknown.",
        ],
        "sources": SOURCES,
        "limitations": "Metadata checks cannot prove indexing, position, thumbnail appeal, watch satisfaction or creative quality. Never change accurate child-directed/AI controls to seek reach.",
    }


def _video_id(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
    }:
        return None
    if parsed.hostname == "youtu.be":
        value = parsed.path.strip("/")
    elif parsed.path in {"/watch", "/watch/"}:
        value = parse_qs(parsed.query).get("v", [""])[0]
    else:
        value = (
            parsed.path.removeprefix("/shorts/")
            if parsed.path.startswith("/shorts/")
            else ""
        )
    return value if re.fullmatch(r"[\w-]{11}", value) else None


def search_observation(preflight, observation):
    """Validate an owner/operator's evidence receipt; never infer broad ranking.

    This is an observation record, not independent authentication of a screenshot
    or a publication/creative approval. Metadata hashes prevent stale attribution.
    """
    if observation.get("metadata_sha256") != preflight.get("metadata_sha256"):
        raise ValueError("Observation must bind to the exact current metadata hash")
    video_id = _text(observation.get("video_id"))
    if not re.fullmatch(r"[\w-]{11}", video_id):
        raise ValueError("A valid YouTube video ID is required")
    observed_at = _text(observation.get("observed_at"))
    try:
        timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "Record the actual observation timestamp with timezone"
        ) from exc
    if timestamp.tzinfo is None:
        raise ValueError("Observation timestamp needs a timezone")
    query = _text(observation.get("query"))
    context = _text(observation.get("context"))
    evidence = _text(observation.get("evidence_reference"))
    found = observation.get("found")
    urls = observation.get("result_urls", [])
    if (
        not query
        or not context
        or not evidence
        or not isinstance(found, bool)
        or not isinstance(urls, list)
    ):
        raise ValueError(
            "Record query, browser/sign-in/region context, evidence, found and result URLs"
        )
    ids = [_video_id(url) for url in urls if isinstance(url, str)]
    if found and video_id not in ids:
        raise ValueError("A found observation needs the exact video result URL")
    if not found and video_id in ids:
        raise ValueError("Observation contradicts its exact video result URL")
    return {
        "video_id": video_id,
        "metadata_sha256": preflight["metadata_sha256"],
        "observed_at": observed_at,
        "query": query,
        "context": context,
        "evidence_reference": evidence,
        "result_urls": urls,
        "found": found,
        "index_status": "observed_searchable_for_query"
        if found
        else "not_found_in_observed_results",
        "ranking_status": "not_measured",
        "limitations": "One observed query is not a universal rank or proof of non-indexing; results vary by context. Operator-supplied evidence, not an independent media review.",
    }
