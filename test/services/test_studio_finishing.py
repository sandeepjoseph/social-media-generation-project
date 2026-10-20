"""Failure-focused release contracts; fixture bytes never claim real media QA."""

import json
from pathlib import Path

import pytest

from app.services import studio_cinema as cinema
from app.services import studio_finishing as finishing
from app.services import studio_native_movie as movie
from app.services import story_studio as studio
from test.services.test_studio_cinema import (
    configured as cinema_configured,
    ready_story,
)
from test.services.test_studio_native_movie import selection as native_selection


@pytest.fixture(name="configured")
def configured_fixture(tmp_path, monkeypatch):
    return cinema_configured.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture(name="selection")
def selection_fixture(tmp_path):
    return native_selection.__wrapped__(tmp_path)


@pytest.fixture
def final_review(tmp_path):
    evidence = tmp_path / "actual-review-evidence.fixture.txt"
    evidence.write_text("Test fixture only; no audiovisual viewing claim.")
    context = {
        "story_id": "independent-story-a",
        "master_sha256": "a" * 64,
        "caption_sha256": "b" * 64,
        "storyboard_sha256": "c" * 64,
        "policy_sha256": cinema.digest(
            cinema.policy_for({"cinema_policy": {"enabled": True}})
        ),
        "locale": "en",
        "duration_seconds": 360,
        "board": {
            "shots": [
                {"shot_id": "a", "duration_seconds": 180},
                {"shot_id": "b", "duration_seconds": 180},
            ]
        },
    }
    review = {
        k: v for k, v in context.items() if k not in {"board", "duration_seconds"}
    }
    review.update(
        contract_version=finishing.VERSION,
        status="passed",
        method="actual_complete_movie_audio_video",
        media_access_confirmed=True,
        reviewer="Fixture reviewer",
        reviewer_kind="ai",
        limitations="Synthetic test fixture, not evidence of real viewing.",
        unresolved_issues=[],
        checks={key: True for key in finishing.CHECKS},
        evidence_files=[{"path": str(evidence), "sha256": movie.sha(evidence)}],
        observations=[
            {
                "start_seconds": t,
                "end_seconds": t + 1,
                "visible_and_audible_event": "Fixture audiovisual observation",
            }
            for t in (1, 180, 357)
        ],
        boundary_reviews=[
            {
                "shot_id": sid,
                "start_seconds": start,
                "end_seconds": start + 180,
                "opening_pass": True,
                "ending_pass": True,
                "join_pass": True,
                "unintended_speech_absent": True,
                "clicks_and_truncation_absent": True,
                "observed_boundary_detail": "Fixture complete line and clean cut",
            }
            for sid, start in (("a", 0), ("b", 180))
        ],
    )
    return review, context


def test_cinema_always_enables_finishing_without_optional_override():
    policy = cinema.policy_for(
        {"cinema_policy": {"enabled": True, "finishing_contract": False}}
    )
    assert policy["finishing_contract"] == finishing.contract()
    assert cinema.policy_for({}) == {}


def test_complete_explicit_final_review_passes(final_review):
    review, context = final_review
    assert finishing.review_issues(review, **context) == []


@pytest.mark.parametrize("key", finishing.CHECKS)
def test_every_learned_creative_correction_is_required(final_review, key):
    review, context = final_review
    del review["checks"][key]
    assert "finishing:mandatory_creative_checks_incomplete" in finishing.review_issues(
        review, **context
    )


@pytest.mark.parametrize(
    "key",
    [
        "story_id",
        "master_sha256",
        "caption_sha256",
        "storyboard_sha256",
        "policy_sha256",
        "locale",
        "contract_version",
    ],
)
def test_other_story_or_changed_media_policy_cannot_reuse_review(final_review, key):
    review, context = final_review
    review[key] = "different"
    assert (
        "finishing:review_stale_or_wrong_story_media_locale_policy"
        in finishing.review_issues(review, **context)
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(method="asr_and_still_frames"),
        lambda r: r.update(media_access_confirmed=False),
        lambda r: r.update(reviewer_kind="unknown"),
        lambda r: r.update(limitations=""),
        lambda r: r.update(unresolved_issues=["Unwanted syllable before actor speaks"]),
        lambda r: r["observations"][0].update(start_seconds=422, end_seconds=423),
        lambda r: r["observations"][0].update(start_seconds=True),
        lambda r: r["boundary_reviews"].pop(),
        lambda r: r["boundary_reviews"].reverse(),
        lambda r: r["boundary_reviews"][0].update(unintended_speech_absent=False),
        lambda r: r["boundary_reviews"][1].update(start_seconds=179),
        lambda r: r.update(evidence_files=[]),
    ],
)
def test_review_shortcuts_and_bad_timestamps_hold_release(final_review, change):
    review, context = final_review
    change(review)
    assert finishing.review_issues(review, **context)


def test_evidence_tampering_revokes_finishing_review(final_review):
    review, context = final_review
    Path(review["evidence_files"][0]["path"]).write_text("changed")
    assert "finishing:review_evidence_missing_or_changed" in finishing.review_issues(
        review, **context
    )


def test_early_excerpt_cannot_claim_whole_movie_observations(final_review):
    review, context = final_review
    for index, item in enumerate(review["observations"]):
        item.update(start_seconds=index + 1, end_seconds=index + 2)
    assert (
        "finishing:beginning_middle_and_ending_observations_required"
        in finishing.review_issues(review, **context)
    )


@pytest.mark.parametrize(
    "cues, expected",
    [
        (
            [{"start_seconds": 0, "end_seconds": 1.31, "text": "work together."}],
            "too_brief",
        ),
        ([{"start_seconds": 0, "end_seconds": 2, "text": "A" * 40}], "too_fast"),
        ([{"start_seconds": 0, "end_seconds": 4, "text": "A" * 43}], "layout"),
        (
            [
                {"start_seconds": 0, "end_seconds": 4, "text": "A"},
                {"start_seconds": 3, "end_seconds": 6, "text": "B"},
            ],
            "overlap",
        ),
    ],
)
def test_actual_caption_cards_are_checked_not_cached_pass(cues, expected):
    assert any(
        expected in issue for issue in finishing.caption_issues(cues, locale="en")
    )


def test_captions_require_exact_order_and_keep_localization_explicit():
    cues = [{"start_seconds": 0, "end_seconds": 3, "text": "Try together."}]
    assert (
        finishing.caption_issues(cues, locale="en", expected_text="Try together.") == []
    )
    assert finishing.caption_issues(cues, locale="en", expected_text="Together try.")
    cues[0].update(text="മ" * 43)
    assert finishing.caption_issues(cues, locale="ml") == []


def test_caption_readability_cannot_be_bypassed_by_deleting_cached_hold(selection):
    board, plan, _, _ = selection
    plan["shots"][0].update(caption_start=4.8, caption_end=5.9)
    plan["caption_readability"] = {"held": [], "actual_review_required": False}
    assert any(
        "too_brief" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_quality_and_import_require_finishing_even_with_passing_outer_flags(
    configured, tmp_path, monkeypatch
):
    store, sid, _, _ = ready_story(configured)
    master = tmp_path / "candidate.mp4"
    master.write_bytes(
        b"Hash fixture only; decoder mocked, no actual media quality claim"
    )
    monkeypatch.setattr(studio, "sample_decode_video", lambda path: (True, "fixture"))
    monkeypatch.setattr(studio, "video_duration_seconds", lambda path: 400.0)
    qa = studio.quality_report(store, sid, master_path=master)
    assert "finishing:actual_final_movie_review_required" in qa["issues"]
    report = {
        "status": "passed",
        "story_id": sid,
        "script_sha256": qa["script_sha256"],
        "master_sha256": movie.sha(master),
        "reviewer": "Fixture reviewer",
        "technical_decode_pass": True,
        "visual_review_pass": True,
        "audio_review_pass": True,
    }
    with pytest.raises(
        ValueError, match="finishing:actual_final_movie_review_required"
    ):
        studio.import_quality_review(store, sid, report, master_path=master)
    template = studio.finishing_review_template(store, sid, master)
    assert template["status"] == "pending_actual_review"
    assert not any(template["checks"].values())
    assert len(template["boundary_reviews"]) == 50


def test_finishing_implementation_change_invalidates_saved_jobs(tmp_path):
    root = tmp_path / "repo"
    source = root / "app/services/studio_finishing.py"
    source.parent.mkdir(parents=True)
    source.write_text("first contract")
    before = cinema.implementation_identity(root)
    source.write_text("stricter learned contract")
    assert before != cinema.implementation_identity(root)


def test_required_channel_cannot_disable_cinema(configured):
    import os

    path = Path(os.environ["STORY_STUDIO_PROFILE_PATH"])
    profile = json.loads(path.read_text())
    profile.update(mandatory_cinema=True, cinema_policy={"enabled": False})
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="channel requires"):
        studio.load_director_profile()


def test_publication_metadata_cannot_forge_approval_fields():
    assert studio._publication_metadata(
        {}, {"platform_titles": {"youtube_long": "A real question?"}}
    )
    with pytest.raises(ValueError, match="unsupported"):
        studio._publication_metadata({}, {"qa_report": {"passed": True}})
    with pytest.raises(ValueError, match="mappings"):
        studio._publication_metadata({}, {"platform_descriptions": ["wrong shape"]})


def test_source_plan_stays_independent_of_other_story(selection):
    board, plan, folder, _ = selection
    bundle = json.loads((folder / "bundle.json").read_text())
    bundle["story_id"] = "story-a"
    (folder / "bundle.json").write_text(json.dumps(bundle))
    plan.update(
        flow_bundle_file_sha256=movie.sha(folder / "bundle.json"), story_id="story-b"
    )
    assert any(
        "independent story ID" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_full_cinema_release_rechecks_finishing_evidence_at_owner_approval(
    configured, tmp_path, monkeypatch
):
    from test.services.test_studio_cinema import film, review_for, submission_fixture
    from test.services.test_story_studio import _register_variant

    store, _ = configured
    sid = store.create_story(
        {"title": "A shared idea", "premise": "They try together"}
    )["story_id"]
    for category in ("source_script_adaptation", "visual", "voice", "music_ambience"):
        store.add_evidence(
            sid,
            {
                "source": "Original fixture",
                "category": category,
                "claim": "Synthetic test only",
                "rights_status": "original",
                "confidence": "high",
            },
        )
    script, board = film()
    studio.ingest_screenplay_document(store, sid, script)
    studio.ingest_storyboard_document(store, sid, board)
    monkeypatch.setattr(
        studio,
        "sample_decode_video",
        lambda path: (True, "fixture decode, no real QA claim"),
    )
    monkeypatch.setattr(
        studio,
        "video_duration_seconds",
        lambda path: 400 if Path(path).name == "candidate.mp4" else 8,
    )
    bundle = studio.export_flow_bundle(store, sid)
    board_sha = store.latest_artifact(sid, "storyboard")["sha256"]
    for index, shot in enumerate(bundle["shots"]):
        clip = tmp_path / f"fixture-{index}.mp4"
        clip.write_bytes(f"Unique native-media hash fixture {index}".encode())
        store.import_flow_receipt(
            sid,
            {
                "shot_id": shot["shot_id"],
                "prompt_sha256": shot["prompt_sha256"],
                "asset_path": str(clip),
                "provider": "test",
                "submission_attestation": submission_fixture(shot, store, sid),
            },
        )
        if index == 1:
            pilot = review_for(board, store.flow_receipts(sid), board_sha, pilot=True)
            pilot["story_id"] = sid
            studio.import_performance_pilot_review(store, sid, pilot)
            studio.export_flow_bundle(store, sid)
    master = tmp_path / "candidate.mp4"
    master.write_bytes(b"Final movie hash fixture; technical decoder mocked explicitly")
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "\n\n".join(
            f"{index + 1}\n{movie.timestamp(index * 8 + 0.3)} --> {movie.timestamp(index * 8 + 4)}\nCan we try this together?"
            for index in range(50)
        )
        + "\n"
    )
    _register_variant(store, sid, master, captions, "final-en")
    studio.build_platform_package(
        store, sid, master_path=master, platforms=("youtube_long",)
    )
    qa = studio.quality_report(store, sid, master_path=master)
    finishing_report = studio.finishing_review_template(store, sid, master)
    evidence = tmp_path / "review.fixture.txt"
    evidence.write_text("Synthetic acceptance fixture; no human or AI viewing claim")
    finishing_report.update(
        status="passed",
        reviewer="Fixture reviewer",
        reviewer_kind="ai",
        media_access_confirmed=True,
        limitations="Synthetic fixture only",
        unresolved_issues=[],
        checks={key: True for key in finishing.CHECKS},
        evidence_files=[{"path": str(evidence), "sha256": movie.sha(evidence)}],
        observations=[
            {
                "start_seconds": t,
                "end_seconds": t + 1,
                "visible_and_audible_event": "Fixture observed event",
            }
            for t in (1, 200, 397)
        ],
    )
    for item in finishing_report["boundary_reviews"]:
        item.update(
            opening_pass=True,
            ending_pass=True,
            join_pass=True,
            unintended_speech_absent=True,
            clicks_and_truncation_absent=True,
            observed_boundary_detail="Fixture clean opening, complete last word, silent rest and motivated join",
        )
    report = {
        "status": "passed",
        "story_id": sid,
        "script_sha256": qa["script_sha256"],
        "master_sha256": movie.sha(master),
        "reviewer": "Fixture reviewer",
        "technical_decode_pass": True,
        "visual_review_pass": True,
        "audio_review_pass": True,
        "performance_review": review_for(board, store.flow_receipts(sid), board_sha),
        "finishing_review": finishing_report,
    }
    accepted = studio.import_quality_review(store, sid, report, master_path=master)
    assert accepted["passed"], accepted["issues"]
    package = studio.build_platform_package(
        store,
        sid,
        master_path=master,
        platforms=("youtube_long",),
        metadata={
            "platform_titles": {"youtube_long": "Can we try this together?"},
            "platform_descriptions": {
                "youtube_long": "They try an idea together. #Together"
            },
            "topics": ["together"],
            "keywords": ["idea"],
        },
        human_review={
            "audience_reviewed": True,
            "made_for_kids_reviewed": True,
            "ai_realistic_content": "disclosed",
            "platform_assets": {
                "youtube_long": {
                    "path": str(master),
                    "variant_reviewed": True,
                    "audience_reviewed": True,
                }
            },
        },
    )
    assert package["readiness"]["required_checks_passed"], package
    assert studio.approve_package(
        store, sid, movie.sha(master), package["package_sha256"], "Fixture owner"
    )
    evidence.write_text("Changed after approval")
    with pytest.raises(ValueError, match="QA evidence is stale"):
        studio.approve_package(
            store, sid, movie.sha(master), package["package_sha256"], "Fixture owner"
        )
