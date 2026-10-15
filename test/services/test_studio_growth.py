import hashlib
import json

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
    return {
        "story_id": "story-01",
        "title": "The Potter's Promise",
        "script_text": "A potter keeps a promise to a neighbor and learns to ask for help.",
        "synopsis": "A potter and a neighbor solve a problem together.",
        "audience": {
            "age_min": 6,
            "age_max": 10,
            "language": "English",
            "made_for_kids": True,
        },
        "fiction_taxonomy": ["folktale", "cooperation"],
        "moral_or_learning_intent": "cooperation",
        "topics": ["pottery", "cooperation", "viral"],
        "source_evidence": [
            {"source": "Original script", "rights_status": "original"},
            {"source": "Licensed score", "rights_status": "licensed"},
        ],
        "qa_report": {"status": "passed"},
        "captions": _asset(captions),
        "master": _asset(master),
        "thumbnail_brief": "Show the potter and neighbor beside the repaired clay pot.",
        "chapters": [
            {"seconds": 0, "title": "The broken pot", "timing_verified": True},
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
    assert package["platforms"]["youtube_long"]["chapters"][1] == {
        "seconds": 48,
        "title": "A promise kept",
    }
    assert package["platforms"]["youtube_long"]["hashtags"] == [
        "#Pottery",
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
    assert "Confirm child-directed platform settings" in " ".join(
        package["review_queue"]
    )
    assert package["approval"]["status"] == "approval_required"


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
    assert tampered["approval"]["verified_for_exact_master_and_package"] is False
    assert approved["package_sha256"] == preliminary["package_sha256"]


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
