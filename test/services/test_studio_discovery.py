import copy

import pytest

from app.services.studio_discovery import (
    DEFAULT_POLICY,
    search_brief,
    youtube_preflight,
    youtube_keywords,
    search_observation,
    keyword_size,
)
from app.services.story_studio import _publication_metadata, _profile_snapshot
from app.services.studio_channel_setup import initialize_channel
import json


def _facts():
    return {
        "title": "The Weaver and the Lost Thread",
        "script_text": "Mira the weaver finds a lost thread and helps her neighbour.",
        "synopsis": "Mira the weaver follows a lost thread to help her neighbour.",
        "audience": {"language": "en"},
        "search_policy": {
            **copy.deepcopy(DEFAULT_POLICY),
            "subject_aliases": [{"subject": "Mira", "aliases": ["Meera"]}],
        },
        "search_brief": {"primary_query": "Mira", "episode_query": "Lost Thread"},
    }


def _preflight(facts=None):
    facts = facts or _facts()
    return youtube_preflight(
        facts, "Mira and the Lost Thread", facts["synopsis"], ["Mira", "Meera"]
    )


def test_story_queries_and_aliases_require_story_or_explicit_editorial_support():
    facts = _facts()
    assert search_brief(facts)["aliases"] == ["Meera"]
    assert search_brief(facts)["search_volume"] is None
    for field, value in [
        ("primary_query", "Famous Princess"),
        ("episode_query", "Moon Race"),
        ("aliases", ["Other Famous Hero"]),
    ]:
        bad = copy.deepcopy(facts)
        bad["search_brief"][field] = value
        with pytest.raises(ValueError, match="supported"):
            search_brief(bad)
    facts["search_brief"]["indexed"] = True
    with pytest.raises(ValueError, match="accepts"):
        search_brief(facts)


def test_searchability_is_unknown_until_exact_video_observation():
    result = _preflight()
    assert result["passed"] is True
    assert result["index_status"] == "not_observed"
    observation = {
        "video_id": "abcdefghijk",
        "metadata_sha256": result["metadata_sha256"],
        "observed_at": "2026-10-18T12:00:00-04:00",
        "query": "Mira Lost Thread",
        "context": "Signed in browser, Canada; personalized results possible",
        "evidence_reference": "operator-AX-observation-01.txt",
        "found": True,
        "result_urls": ["https://www.youtube.com/watch?v=abcdefghijk"],
    }
    receipt = search_observation(result, observation)
    assert receipt["index_status"] == "observed_searchable_for_query"
    assert receipt["ranking_status"] == "not_measured"
    with pytest.raises(ValueError, match="exact video"):
        search_observation(
            result, {**observation, "result_urls": ["https://example.com/abcdefghijk"]}
        )
    with pytest.raises(ValueError, match="timezone"):
        search_observation(
            result, {**observation, "observed_at": "2026-10-18T12:00:00"}
        )
    changed = youtube_preflight(
        _facts(), "Mira: The Lost Thread", _facts()["synopsis"], []
    )
    with pytest.raises(ValueError, match="current metadata"):
        search_observation(changed, observation)
    negative = search_observation(
        result, {**observation, "found": False, "result_urls": []}
    )
    assert negative["index_status"] == "not_found_in_observed_results"


def test_relevance_lead_utf8_limits_and_tags_fail_closed():
    facts = _facts()
    result = youtube_preflight(
        facts,
        "A Wonderful Story",
        "Company info.\n\nMira and the Lost Thread",
        ["Mira"],
    )
    assert result["passed"] is False
    assert result["checks"]["main_topic_in_opening_description"] is False
    assert result["checks"]["main_topic_in_title"] is False
    oversized = youtube_preflight(
        facts, "Mira and the Lost Thread", facts["synopsis"] + "界" * 2000, ["x" * 501]
    )
    assert oversized["checks"]["description_within_5000_utf8_bytes"] is False
    assert oversized["checks"]["tags_within_500_character_budget"] is False
    assert _preflight()["brief"]["language"] == "en"


def test_keyword_budget_keeps_company_names_and_spelling_variants():
    words = youtube_keywords(
        search_brief(_facts()),
        ["weaving " + "x" * 70 + str(i) for i in range(12)],
        ["Example Media", "Example Inc."],
    )
    assert "Meera" in words
    assert words[-2:] == ["Example Media", "Example Inc."]
    assert keyword_size(words) <= 500


def test_search_policy_is_frozen_and_portable_not_account_state(tmp_path):
    source = tmp_path / "source"
    initialize_channel(source, channel_id="old", channel_name="Old")
    profile_path = source / "brand-profile.json"
    profile = json.loads(profile_path.read_text())
    profile["search_policy"] = _facts()["search_policy"]
    profile["accounts"] = {"youtube": "must-not-copy"}
    profile_path.write_text(json.dumps(profile))
    assert _profile_snapshot(profile)["search_policy"]["required"] is True
    new = tmp_path / "new"
    initialize_channel(
        new, channel_id="new", channel_name="New", source_profile=profile_path
    )
    copied = json.loads((new / "brand-profile.json").read_text())
    assert copied["search_policy"] == profile["search_policy"]
    assert "must-not-copy" not in json.dumps(copied)
    metadata = _publication_metadata({}, {"search_brief": _facts()["search_brief"]})
    assert metadata["search_brief"]["primary_query"] == "Mira"
    with pytest.raises(ValueError, match="unsupported"):
        _publication_metadata({}, {"search_policy": {"required": False}})
