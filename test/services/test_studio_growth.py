import hashlib
import json
from pathlib import Path

import pytest

from app.services.studio_growth import (
    ANALYTICS_CSV_COLUMNS,
    DEFAULT_PLATFORMS,
    package_story,
)


def _asset(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _facts(tmp_path):
    master = tmp_path / "master.mp4"
    master.write_bytes(b"approved-video")
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nA short story.\n", encoding="utf-8"
    )
    script = "A potter keeps a promise to a neighbor and learns to ask for help."
    master_asset = _asset(master)
    platform_assets = {}
    platform_captions = {}
    for platform in DEFAULT_PLATFORMS:
        variant = tmp_path / f"{platform}.mp4"
        variant.write_bytes(f"approved-{platform}".encode())
        platform_assets[platform] = {
            **_asset(variant),
            "variant_reviewed": True,
            "audience_reviewed": True,
        }
        platform_captions[platform] = {
            **_asset(captions),
            "locale_match": True,
            "language_reviewed": True,
            "media_sha256": platform_assets[platform]["sha256"],
        }
    return {
        "story_id": "story-01",
        "title": "The Potter's Promise",
        "script_text": script,
        "synopsis": "A potter and a neighbor solve a problem together.",
        "audience": {
            "age_min": 6,
            "age_max": 10,
            "language": "en",
            "made_for_kids": True,
            "reviewed": True,
        },
        "fiction_taxonomy": ["folktale", "cooperation"],
        "moral_or_learning_intent": "cooperation",
        "topics": ["promise", "cooperation", "viral"],
        "source_evidence": [
            {
                "category": "source",
                "source": "Original script",
                "rights_status": "original",
            },
            {
                "category": "visual",
                "source": "Original animation",
                "rights_status": "original",
            },
            {
                "category": "voice",
                "source": "Original narration",
                "rights_status": "original",
            },
            {
                "category": "music_ambience",
                "source": "No music",
                "rights_status": "not_used",
            },
        ],
        "qa_report": {
            "status": "passed",
            "story_id": "story-01",
            "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
            "master_sha256": master_asset["sha256"],
        },
        "captions": _asset(captions),
        "captions_locale_match": True,
        "master": master_asset,
        "duration_seconds": 60,
        "duration_verified": True,
        "platform_assets": platform_assets,
        "platform_captions": platform_captions,
        "thumbnail_brief": "Show the potter and neighbor beside the repaired clay pot.",
        "chapters": [
            {"seconds": 0, "title": "The broken pot", "timing_verified": True},
            {"seconds": 10, "title": "The first clue", "timing_verified": True},
            {"seconds": 48, "title": "A promise kept", "timing_verified": True},
        ],
        "ai_realistic_content": "reviewed_not_required",
    }


def test_package_is_truthful_and_uses_documented_platform_limits(tmp_path):
    package = package_story(_facts(tmp_path))

    assert tuple(package["platforms"]) == DEFAULT_PLATFORMS
    assert package["metadata_only"] is True
    assert package["publishing"] == "manual_handoff_only"
    assert package["platforms"]["youtube_long"]["title"] == "The Potter's Promise"
    assert (
        "original story"
        not in package["platforms"]["youtube_long"]["description"].casefold()
    )
    assert package["platforms"]["youtube_long"]["chapters"][1] == {
        "seconds": 10,
        "title": "The first clue",
    }
    assert package["platforms"]["youtube_short"]["chapters"] == []
    assert package["platforms"]["youtube_long"]["chapters"][2] == {
        "seconds": 48,
        "title": "A promise kept",
    }
    assert package["platforms"]["youtube_long"]["hashtags"] == [
        "#Promise",
        "#Cooperation",
        "#Folktale",
    ]
    assert all(
        "viral" not in tag.casefold()
        for tag in package["platforms"]["tiktok"]["hashtags"]
    )
    assert package["required_approval"]["asset_sha256_verified"] is True
    assert package["required_approval"]["captions_sha256_verified"] is True
    assert package["audience"]["made_for_kids"] is True
    assert package["required_approval"]["made_for_kids_reviewed"] is True
    assert (
        package["required_approval"]["platform_assets_and_audiences_reviewed"] is True
    )
    assert package["approval"]["status"] == "approval_required"
    assert package["readiness"]["ready_for_publication"] is False


def test_explicit_brand_tag_precedes_four_story_supported_topics(tmp_path):
    facts = _facts(tmp_path)
    facts["brand_hashtags"] = ["ExampleStoryCo"]
    package = package_story(facts, platforms=("youtube_long",))

    tags = package["platforms"]["youtube_long"]["hashtags"]
    assert tags == [
        "#ExampleStoryCo",
        "#Promise",
        "#Cooperation",
        "#Folktale",
    ]


def test_brand_tags_reject_urls_trends_and_claims_and_never_exceed_five(tmp_path):
    facts = _facts(tmp_path)
    facts["brand_hashtags"] = [
        "https://example.com",
        "#viral",
        "guaranteed",
        "ExampleStoryCo",
        "AnotherBrand",
    ]
    package = package_story(facts, platforms=("tiktok",))

    tags = package["platforms"]["tiktok"]["hashtags"]
    assert tags == ["#ExampleStoryCo", "#Promise", "#Cooperation", "#Folktale"]
    assert len(tags) <= 5
    assert all("viral" not in tag.casefold() for tag in tags)
    assert all("guaranteed" not in tag.casefold() for tag in tags)


def test_explicit_folktale_genres_make_compound_tags_without_broad_kids_tag(tmp_path):
    facts = _facts(tmp_path)
    facts["brand_hashtags"] = ["GenericBrand"]
    facts["script_text"] = "A village storyteller learns to listen with patience."
    facts["title"] = "The Patient Listener"
    facts["moral_or_learning_intent"] = ""
    facts["topics"] = [
        "Tenali Raman",
        "Indian Folktales",
        "Moral Stories",
        "Stories For Kids",
        "Kids",
    ]
    facts["keywords"] = list(facts["topics"])
    facts["fiction_taxonomy"] = [
        "Indian Folktales",
        "Moral Stories",
        "Stories For Kids",
    ]
    facts["audience"] = {
        **facts["audience"],
        "age_min": 6,
        "age_max": 10,
    }
    facts["qa_report"]["script_sha256"] = hashlib.sha256(
        facts["script_text"].encode()
    ).hexdigest()

    package = package_story(facts, platforms=("youtube_long",))
    tags = package["platforms"]["youtube_long"]["hashtags"]

    assert tags == [
        "#GenericBrand",
        "#IndianFolktales",
        "#MoralStories",
        "#StoriesForKids",
    ]
    assert "#Kids" not in tags
    assert "#MoralKids" not in tags


def test_unverified_or_missing_evidence_stays_in_review_queue(tmp_path):
    facts = _facts(tmp_path)
    facts["source_evidence"][1]["rights_status"] = "unknown"
    facts["ai_realistic_content"] = "unknown"
    facts["qa_report"] = {"status": "pending"}
    facts["chapters"][1]["timing_verified"] = False
    facts["master"]["sha256"] = "0" * 64

    package = package_story(facts, platforms=("youtube_long",))

    assert package["master"]["verified"] is False
    assert package["platforms"]["youtube_long"]["chapters"] == []
    assert any("rights status" in item for item in package["review_queue"])
    assert any("final creative QA" in item for item in package["review_queue"])
    assert any("realistic AI-generated" in item for item in package["review_queue"])


def test_caption_tracks_require_fluent_locale_match_and_variant_binding(tmp_path):
    facts = _facts(tmp_path)
    facts["captions_locale_match"] = False
    facts["platform_captions"]["youtube_long"]["locale_match"] = False
    facts["platform_captions"]["youtube_long"]["media_sha256"] = "0" * 64

    package = package_story(facts, platforms=("youtube_long",))

    assert (
        package["required_approval"]["captions_locale_matches_story_and_audio"] is False
    )
    assert package["required_approval"]["platform_caption_tracks_verified"] is False
    assert package["required_approval"]["captions_sha256_verified"] is True
    assert package["readiness"]["required_checks_passed"] is False
    assert any(
        "fluent-reviewed" in item
        for item in package["platforms"]["youtube_long"]["review_queue"]
    )


def test_flagged_title_hook_and_platform_length_are_not_silently_rewritten(tmp_path):
    facts = _facts(tmp_path)
    facts["title"] = "A guaranteed secret that will make you a millionaire " + "x" * 60

    package = package_story(facts, platforms=("youtube_long", "dailymotion"))

    youtube = package["platforms"]["youtube_long"]
    dailymotion = package["platforms"]["dailymotion"]
    assert youtube["title"] == facts["title"]
    assert youtube["title_hook_promise_check"]["status"] == "review_required"
    assert any("high-risk promise" in item for item in youtube["review_queue"])
    assert any("100-character limit" in item for item in youtube["review_queue"])
    assert any(
        "255-character limit" not in item for item in dailymotion["review_queue"]
    )


def test_exact_package_and_master_approval_matches_only_after_hashing(tmp_path):
    facts = _facts(tmp_path)
    preliminary = package_story(facts, platforms=("youtube_long",))
    approval = {
        "master_sha256": preliminary["master"]["sha256"],
        "package_sha256": preliminary["package_sha256"],
    }

    approved = package_story(facts, platforms=("youtube_long",), approval=approval)
    tampered = package_story(
        facts,
        platforms=("youtube_long",),
        approval={**approval, "package_sha256": "bad"},
    )

    assert approved["approval"]["verified_for_exact_master_and_package"] is True
    assert approved["approval"]["approval_record_matches_exact_package"] is True
    assert approved["metadata_copy_review_status"] == "owner_approved_for_exact_package"
    assert approved["readiness"]["ready_for_manual_handoff"] is True
    assert approved["readiness"]["ready_for_publication"] is False
    assert tampered["approval"]["verified_for_exact_master_and_package"] is False
    assert approved["package_sha256"] == preliminary["package_sha256"]


def test_title_or_synopsis_change_invalidates_exact_copy_approval(tmp_path):
    facts = _facts(tmp_path)
    draft = package_story(facts, platforms=("youtube_long",))
    approval = {
        "master_sha256": draft["master"]["sha256"],
        "package_sha256": draft["package_sha256"],
    }
    changed = dict(facts)
    changed["title"] = "A Different Tale"
    changed["synopsis"] = "An unrelated mystery about a lost palace key."

    package = package_story(changed, platforms=("youtube_long",), approval=approval)

    assert package["package_sha256"] != draft["package_sha256"]
    assert package["metadata_copy_review_status"] == "review_required"
    assert package["approval"]["verified_for_exact_master_and_package"] is False


def test_analytics_contract_keeps_unknown_values_uncoerced():
    assert "impressions" in ANALYTICS_CSV_COLUMNS
    assert "click_through_rate" in ANALYTICS_CSV_COLUMNS
    assert "watch_time_seconds" in ANALYTICS_CSV_COLUMNS
    assert "completions" in ANALYTICS_CSV_COLUMNS
    assert "production_credits" in ANALYTICS_CSV_COLUMNS
    assert "accepted_minutes" in ANALYTICS_CSV_COLUMNS
    # Missing measurements belong as blank CSV cells, never synthesized zeroes.
    row = {column: "" for column in ANALYTICS_CSV_COLUMNS}
    assert json.dumps(row).count('"0"') == 0


def test_invalid_facts_and_platforms_fail_closed():
    with pytest.raises(ValueError, match="story_id, title, and script_text"):
        package_story({"title": "Missing script"})
    with pytest.raises(ValueError, match="Unsupported platform"):
        package_story(
            {"story_id": "x", "title": "t", "script_text": "s"}, platforms=("unknown",)
        )


@pytest.mark.parametrize("failure", ["qa", "rights", "captions"])
def test_exact_hash_approval_cannot_override_failed_readiness_checks(tmp_path, failure):
    facts = _facts(tmp_path)
    if failure == "qa":
        facts["qa_report"]["status"] = "pending"
    elif failure == "rights":
        facts["source_evidence"] = facts["source_evidence"][:-1]
    elif failure == "captions":
        facts["captions"]["sha256"] = "0" * 64
    draft = package_story(facts, platforms=("youtube_long",))
    approval = {
        "master_sha256": draft["master"]["sha256"],
        "package_sha256": draft["package_sha256"],
    }

    result = package_story(facts, platforms=("youtube_long",), approval=approval)

    assert result["approval"]["verified_for_exact_master_and_package"] is False
    assert result["approval"]["approval_record_matches_exact_package"] is True
    assert result["approval"]["status"] == "recorded_but_blocked"
    assert result["readiness"]["ready_for_manual_handoff"] is False


def test_qa_binding_and_package_hash_change_when_script_changes(tmp_path):
    facts = _facts(tmp_path)
    original = package_story(facts, platforms=("youtube_long",))
    approval = {
        "master_sha256": original["master"]["sha256"],
        "package_sha256": original["package_sha256"],
    }
    changed = dict(facts)
    changed["script_text"] = facts["script_text"] + " The ending changes."

    stale = package_story(changed, platforms=("youtube_long",), approval=approval)

    assert stale["script_sha256"] != original["script_sha256"]
    assert stale["package_sha256"] != original["package_sha256"]
    assert stale["required_approval"]["qa_bound_to_story_script_and_master"] is False
    assert stale["approval"]["verified_for_exact_master_and_package"] is False


@pytest.mark.parametrize(
    "chapters",
    [
        [
            {"seconds": 0, "title": "Start", "timing_verified": True},
            {"seconds": True, "title": "Bad bool", "timing_verified": True},
        ],
        [
            {"seconds": 0, "title": "Start", "timing_verified": True},
            {"seconds": float("nan"), "title": "Bad NaN", "timing_verified": True},
        ],
        [
            {"seconds": 0, "title": "Start", "timing_verified": True},
            {"seconds": 20, "title": "Later", "timing_verified": True},
            {"seconds": 10, "title": "Earlier", "timing_verified": True},
        ],
        [
            {"seconds": 0, "title": "Start", "timing_verified": True},
            {"seconds": 10, "title": "Duplicate", "timing_verified": True},
            {"seconds": 10, "title": "Duplicate", "timing_verified": True},
        ],
    ],
)
def test_invalid_chapter_timings_are_omitted_and_queued(tmp_path, chapters):
    facts = _facts(tmp_path)
    facts["chapters"] = chapters

    package = package_story(facts, platforms=("youtube_long",))

    assert package["platforms"]["youtube_long"]["chapters"] == []
    assert any("Chapter timings" in item for item in package["review_queue"])


def test_youtube_chapters_follow_youtube_specific_requirements(tmp_path):
    facts = _facts(tmp_path)
    facts["chapters"] = [
        {"seconds": 1, "title": "Starts too late", "timing_verified": True},
        {"seconds": 15, "title": "Next", "timing_verified": True},
        {"seconds": 30, "title": "Last", "timing_verified": True},
    ]

    package = package_story(facts, platforms=("youtube_long", "dailymotion"))

    assert package["platforms"]["youtube_long"]["chapters"] == []
    assert any(
        "YouTube chapters need" in item
        for item in package["platforms"]["youtube_long"]["review_queue"]
    )
    assert package["platforms"]["dailymotion"]["chapters"] == [
        {"seconds": 1, "title": "Starts too late"},
        {"seconds": 15, "title": "Next"},
        {"seconds": 30, "title": "Last"},
    ]


def test_platform_variant_must_be_verified_and_reviewed_before_handoff(tmp_path):
    facts = _facts(tmp_path)
    facts["platform_assets"]["youtube_short"]["variant_reviewed"] = False
    draft = package_story(facts, platforms=("youtube_short",))
    approval = {
        "master_sha256": draft["master"]["sha256"],
        "package_sha256": draft["package_sha256"],
    }

    package = package_story(facts, platforms=("youtube_short",), approval=approval)

    assert package["platforms"]["youtube_short"]["ready_for_manual_handoff"] is False
    assert package["readiness"]["ready_for_manual_handoff"] is False
    assert any(
        "media variant" in item
        for item in package["platforms"]["youtube_short"]["review_queue"]
    )


def test_rights_require_each_evidence_category(tmp_path):
    facts = _facts(tmp_path)
    facts["source_evidence"] = facts["source_evidence"][:-1]
    draft = package_story(facts, platforms=("youtube_long",))
    approval = {
        "master_sha256": draft["master"]["sha256"],
        "package_sha256": draft["package_sha256"],
    }

    package = package_story(facts, platforms=("youtube_long",), approval=approval)

    assert package["required_approval"]["source_and_music_rights_resolved"] is False
    assert package["required_approval"]["rights_coverage"]["music_ambience"] == []
    assert package["approval"]["status"] == "recorded_but_blocked"
    assert any("music/ambience" in item for item in package["review_queue"])


def test_asset_hashing_does_not_read_entire_file_into_memory(tmp_path, monkeypatch):
    facts = _facts(tmp_path)

    def forbid_read_bytes(_self):
        raise AssertionError("asset verification must stream files")

    monkeypatch.setattr(Path, "read_bytes", forbid_read_bytes)
    package = package_story(facts, platforms=("youtube_long",))

    assert package["master"]["verified"] is True
    assert package["platforms"]["youtube_long"]["media_asset"]["verified"] is True


def test_shared_platform_asset_is_hashed_once_per_package(tmp_path, monkeypatch):
    facts = _facts(tmp_path)
    shared = {
        **facts["master"],
        "variant_reviewed": True,
        "audience_reviewed": True,
    }
    facts["platform_assets"] = {platform: shared for platform in DEFAULT_PLATFORMS}
    original_open = Path.open
    reads = 0

    def count_master_open(path, *args, **kwargs):
        nonlocal reads
        if path.resolve() == Path(facts["master"]["path"]).resolve():
            reads += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", count_master_open)
    package = package_story(facts)

    assert all(
        item["media_asset"]["verified"] for item in package["platforms"].values()
    )
    assert reads == 1


def test_chapter_timings_must_fit_verified_duration(tmp_path):
    facts = _facts(tmp_path)
    facts["duration_seconds"] = 40

    package = package_story(facts, platforms=("youtube_long",))

    assert package["platforms"]["youtube_long"]["chapters"] == []
    assert any(
        "within the verified duration" in item for item in package["review_queue"]
    )


def test_no_verified_duration_means_youtube_chapters_are_omitted(tmp_path):
    facts = _facts(tmp_path)
    facts.pop("duration_seconds")
    facts.pop("duration_verified")

    package = package_story(facts, platforms=("youtube_long",))

    assert package["platforms"]["youtube_long"]["chapters"] == []
    assert any(
        "verified video duration" in item
        for item in package["platforms"]["youtube_long"]["review_queue"]
    )
