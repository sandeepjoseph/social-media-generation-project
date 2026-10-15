import json
import subprocess
from pathlib import Path

import pytest

from app.services.story_studio import (
    StudioStore,
    approve_package,
    build_platform_package,
    export_flow_bundle,
    import_analytics,
    import_legacy_benchmark,
    import_quality_review,
    quality_report,
    snapshot_job_config,
    load_director_profile,
    ingest_screenplay_document,
    ingest_storyboard_document,
    request_storyboard_draft,
)
from app.services.studio_captions import register_localized_variant


def _make_av(path):
    import imageio_ffmpeg

    executable = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=2:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _story(store):
    return store.create_story(
        {
            "title": "Sample",
            "premise": "A child learns to share",
            "target_duration_seconds": 420,
            "audience": {
                "age_min": 6,
                "age_max": 10,
                "language": "en",
                "made_for_kids": True,
                "reviewed": True,
            },
            "moral_or_learning_intent": "sharing",
            "profile_id": "generic_public_starter",
            "platform_targets": ["youtube_long"],
        }
    )


def _evidence(store, story_id):
    for category, right in (
        ("source_script_adaptation", "public_domain"),
        ("visual", "original"),
        ("voice", "not_used"),
        ("music_ambience", "not_used"),
    ):
        store.add_evidence(
            story_id,
            {
                "source": category,
                "category": category,
                "claim": "Reviewed",
                "rights_status": right,
                "confidence": "high" if right != "not_used" else "not_applicable",
            },
        )


def _creative(store, story_id):
    screenplay = {
        "schema_version": 1,
        "roles": [
            {
                "role_id": "narrator",
                "name": "Narrator",
                "function": "guide",
                "voice_direction": "warm",
            }
        ],
        "scenes": [
            {
                "scene_id": "s1",
                "setting": "garden",
                "visual_intent": "children share fruit",
                "lines": [
                    {
                        "role_id": "narrator",
                        "text": "They shared the fruit.",
                        "delivery": "gentle",
                    }
                ],
            }
        ],
    }
    board = {
        "shots": [
            {
                "shot_id": "shot-01",
                "duration_seconds": 8,
                "prompt": "A gentle storybook garden with children sharing fruit.",
                "roles": ["narrator"],
                "capabilities": ["text-to-video"],
            }
        ]
    }
    ingest_screenplay_document(store, story_id, screenplay, source="test fixture")
    ingest_storyboard_document(store, story_id, board, source="test fixture")


def _complete_flow_receipts(store, story_id, tmp_path):
    bundle = export_flow_bundle(store, story_id)
    store.add_artifact(story_id, "flow_bundle", document=bundle)
    media = tmp_path / "shot.mp4"
    _make_av(media)
    shot = bundle["shots"][0]
    return store.import_flow_receipt(
        story_id,
        {
            "shot_id": shot["shot_id"],
            "prompt_sha256": shot["prompt_sha256"],
            "asset_path": str(media),
            "provider": "manual Flow",
            "billing": {"status": "unknown"},
        },
    )


def _register_variant(store, story_id, media, captions, variant_id):
    return register_localized_variant(
        store,
        story_id,
        media_path=media,
        caption_path=captions,
        variant_id=variant_id,
        audio_locale="en",
        caption_locale="en",
        fluent_reviewer="Test fluent reviewer",
        voice_record={
            "locale": "en",
            "status": "reviewed",
            "voice_id": "test-narrator-en",
            "provider": "mock",
            "reviewer": "Test voice reviewer",
        },
        burn_in_reviewed=True,
        burn_in_reviewer="Test burn-in reviewer",
    )


def test_phase_resume_cache_invalidation_and_failure(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    story = _story(store)
    sid = story["story_id"]
    calls = []
    first = store.run_phase(
        sid,
        "research",
        {"question": "q1"},
        lambda: calls.append(1) or {"status": "needs_research"},
    )
    assert first["status"] == "complete"
    assert (
        store.run_phase(sid, "research", {"question": "q1"}, lambda: calls.append(2))[
            "status"
        ]
        == "cached"
    )
    second = store.run_phase(
        sid,
        "research",
        {"question": "q2"},
        lambda: calls.append(3) or {"status": "needs_research"},
    )
    assert second["status"] == "complete"
    assert calls == [1, 3]
    with pytest.raises(RuntimeError, match="requires completed creative"):
        store.run_phase(sid, "screenplay", {"new": True}, lambda: {})
    with pytest.raises(ValueError, match="expected failure"):
        store.run_phase(
            sid,
            "creative",
            {"new": True},
            lambda: (_ for _ in ()).throw(ValueError("expected failure")),
        )
    assert store.story(sid)["phases"]["creative"]["status"] == "failed"


def test_quality_gates_and_flow_receipt_prompt_asset_hash_binding(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    blocked = quality_report(store, sid)
    assert not blocked["passed"]
    assert any("missing rights record" in issue for issue in blocked["issues"])
    _evidence(store, sid)
    _creative(store, sid)
    _complete_flow_receipts(store, sid, tmp_path)
    assert any(
        "assembled_master_not_imported" in issue
        for issue in quality_report(store, sid)["issues"]
    )
    bundle = store.latest_artifact(sid, "flow_bundle")["document"]
    assert bundle["shots"][0]["estimated_cost"]["status"] == "unknown"
    asset = tmp_path / "render.mp4"
    _make_av(asset)
    base = {
        "shot_id": "shot-01",
        "prompt_sha256": bundle["shots"][0]["prompt_sha256"],
        "asset_path": str(asset),
        "provider": "manual Flow",
        "billing": {"status": "unknown"},
    }
    result = store.import_flow_receipt(sid, base)
    assert result["asset_sha256"]
    assert store.import_flow_receipt(sid, base)["idempotent"] is True
    with pytest.raises(ValueError, match="does not match"):
        store.import_flow_receipt(sid, {**base, "expected_asset_sha256": "0" * 64})
    with pytest.raises(ValueError, match="prompt does not match"):
        store.import_flow_receipt(sid, {**base, "prompt_sha256": "f" * 64})


def test_package_approval_is_bound_to_current_assets_and_analytics_cost_unknown(
    tmp_path,
):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    _evidence(store, sid)
    _creative(store, sid)
    _complete_flow_receipts(store, sid, tmp_path)
    master = tmp_path / "master.mp4"
    _make_av(master)
    captions = tmp_path / "captions.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    platform_media = tmp_path / "youtube-long.mp4"
    _make_av(platform_media)
    _register_variant(store, sid, master, captions, "master-en")
    _register_variant(store, sid, platform_media, captions, "youtube-long-en")
    review = {
        "audience_reviewed": True,
        "made_for_kids_reviewed": True,
        "ai_realistic_content": "reviewed_not_required",
        "platform_assets": {
            "youtube_long": {
                "path": str(platform_media),
                "variant_reviewed": True,
                "audience_reviewed": True,
            }
        },
    }
    first_package = build_platform_package(
        store,
        sid,
        master_path=master,
        captions_path=captions,
        platforms=("youtube_long",),
    )
    saved_master = store.latest_artifact(sid, "master")
    report = store.latest_artifact(sid, "quality_report")["document"]
    assert report["master_sha256"] == saved_master["sha256"]
    assert not first_package["readiness"]["required_checks_passed"]
    pending_facts = store.latest_artifact(sid, "package_facts")["document"]["facts"]
    assert pending_facts["audience"]["made_for_kids"] is None
    assert pending_facts["audience"]["reviewed"] is False
    assert pending_facts["ai_realistic_content"] is None
    qa_report = {
        "status": "passed",
        "story_id": sid,
        "script_sha256": report["script_sha256"],
        "master_sha256": report["master_sha256"],
        "reviewer": "human reviewer",
        "technical_decode_pass": True,
        "visual_review_pass": True,
        "audio_review_pass": True,
    }
    assert import_quality_review(store, sid, qa_report, master_path=master)["passed"]
    asset = build_platform_package(
        store,
        sid,
        master_path=master,
        captions_path=captions,
        platforms=("youtube_long",),
        human_review=review,
    )
    assert asset["publishing"] == "manual_handoff_only"
    approval_id = approve_package(
        store, sid, saved_master["sha256"], asset["package_sha256"], "local reviewer"
    )
    assert approval_id
    variant_bytes = platform_media.read_bytes()
    platform_media.write_bytes(variant_bytes + b"changed after review")
    with pytest.raises(ValueError, match="changed after review"):
        approve_package(
            store,
            sid,
            saved_master["sha256"],
            asset["package_sha256"],
            "local reviewer",
        )
    platform_media.write_bytes(variant_bytes)
    source = tmp_path / "analytics.csv"
    source.write_text("views,watch_time_seconds\n10,120\n", encoding="utf-8")
    analytic = import_analytics(
        store,
        sid,
        source,
        source="manual export",
        metrics={
            "views": 10,
            "watch_time_seconds": 120,
            "accepted_video_duration_seconds": 360,
        },
        cost={"flow_credits": {"amount": 12}},
    )
    assert analytic["credits_per_minute"] == 2
    assert analytic["cost"]["flow_credits"]["amount"] == 12
    updated_script = {
        "schema_version": 1,
        "roles": [
            {
                "role_id": "narrator",
                "name": "Narrator",
                "function": "guide",
                "voice_direction": "warm",
            }
        ],
        "scenes": [
            {
                "scene_id": "s1",
                "setting": "garden",
                "visual_intent": "children share fruit",
                "lines": [
                    {
                        "role_id": "narrator",
                        "text": "They shared the fruit gladly.",
                        "delivery": "gentle",
                    }
                ],
            }
        ],
    }
    ingest_screenplay_document(store, sid, updated_script, source="updated script")
    assert store.phase(sid, "approval")["status"] == "queued"
    with pytest.raises(ValueError, match="QA evidence is stale"):
        approve_package(
            store,
            sid,
            saved_master["sha256"],
            asset["package_sha256"],
            "local reviewer",
        )
    with pytest.raises(ValueError, match="current package and master"):
        approve_package(store, sid, "0" * 64, asset["package_sha256"], "local reviewer")


def test_legacy_import_preserves_source_duration_and_hash(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    plan = tmp_path / "legacy.json"
    plan.write_text(
        json.dumps(
            {"title": "Legacy benchmark", "final_duration_seconds": 170, "shots": []}
        ),
        encoding="utf-8",
    )
    before = plan.read_bytes()
    imported = import_legacy_benchmark(store, plan)
    assert imported["duration_seconds"] == 170
    assert imported["source_modified"] is False
    assert plan.read_bytes() == before
    assert store.story(imported["story_id"])["requested_duration_seconds"] == 170


def test_media_artifact_uses_external_policy_and_records_verified_archive_copy(
    tmp_path,
):
    store = StudioStore(tmp_path / "studio.sqlite3")
    story = _story(store)
    sid = story["story_id"]
    request = story["request"]
    request["profile_snapshot"]["media_delivery"] = {
        "enabled": True,
        "destination": str(tmp_path / "Social"),
        "timezone": "America/Toronto",
        "archive_on_generation": True,
        "preserve_versions": True,
    }
    with store.transaction() as conn:
        conn.execute(
            "UPDATE stories SET request_json=? WHERE story_id=?",
            (json.dumps(request), sid),
        )
    media = tmp_path / "master.mp4"
    media.write_bytes(b"safe local media placeholder")
    artifact = store.add_artifact(
        sid, "master", path=media, provenance={"source": "manual_import"}
    )
    archive = artifact["provenance"]["delivery_archive"]
    assert archive["status"] == "archived"
    assert archive["copy_verified"] is True
    assert archive["sha256"] == artifact["sha256"]
    assert Path(archive["archive_path"]).read_bytes() == media.read_bytes()
    assert Path(archive["manifest_path"]).is_file()


def test_manual_flow_receipt_is_archived_with_hash_and_locale_free_version_id(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    story = store.story(sid)
    request = story["request"]
    request["profile_snapshot"]["media_delivery"] = {
        "enabled": True,
        "destination": str(tmp_path / "Social"),
        "timezone": "America/Toronto",
        "archive_on_generation": True,
        "preserve_versions": True,
    }
    with store.transaction() as conn:
        conn.execute(
            "UPDATE stories SET request_json=? WHERE story_id=?",
            (json.dumps(request), sid),
        )
    _evidence(store, sid)
    _creative(store, sid)
    bundle = export_flow_bundle(store, sid)
    media = _make_av(tmp_path / "shot.mp4")
    shot = bundle["shots"][0]
    result = store.import_flow_receipt(
        sid,
        {
            "shot_id": shot["shot_id"],
            "prompt_sha256": shot["prompt_sha256"],
            "asset_path": str(media),
            "provider": "manual Flow",
        },
    )
    archive = result["delivery_archive"]
    assert archive["status"] == "archived"
    assert archive["copy_verified"] is True
    assert archive["sha256"] == result["asset_sha256"]
    assert archive["variant_id"] == shot["shot_id"]


def test_new_job_config_reads_allowlisted_flags_once_and_binds_job_id(
    tmp_path, monkeypatch
):
    import app.services.story_studio as studio

    override = tmp_path / "cost-router-overrides.json"
    override.write_text(
        json.dumps(
            {
                "enabled": True,
                "cache_enabled": True,
                "api_key": "must-not-be-read",
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(studio.utils, "root_dir", lambda: str(tmp_path))
    base = {
        "openai_api_key": "preserve-existing-secret-in-memory",
        "llm_provider": "openai",
    }
    snapshot = snapshot_job_config("task-123", base)
    assert snapshot["_cost_router_job_id"] == "task-123"
    assert snapshot["cost_router_enabled"] is True
    assert snapshot["cost_router_cache_enabled"] is True
    assert snapshot["openai_api_key"] == base["openai_api_key"]
    assert "api_key" not in snapshot
    override.write_text('{"enabled": false}', encoding="utf-8")
    assert snapshot["cost_router_enabled"] is True
    assert snapshot_job_config("task-456", base)["cost_router_enabled"] is False


def test_public_generic_profile_is_explicit_and_contains_no_private_asset_paths():
    profile = load_director_profile("generic_public_starter")
    assert profile["profile_visibility"] == "public_generic"
    assert profile["external"] is False
    assert profile["approved_assets"] == []
    assert all("/Users/" not in str(value) for value in profile.values())


def test_external_profile_defaults_are_snapshotted_without_approving_audience(
    tmp_path, monkeypatch
):
    template = tmp_path / "template.json"
    registry = tmp_path / "registry.json"
    profile_file = tmp_path / "brand.json"
    template.write_text(
        json.dumps(
            {
                "role_briefs": ["researcher", "director"],
                "cast_culture_policy": "research each story's setting",
            }
        ),
        encoding="utf-8",
    )
    registry.write_text(json.dumps({"assets": {}}), encoding="utf-8")
    profile_file.write_text(
        json.dumps(
            {
                "profile_id": "external_test_profile",
                "profile_visibility": "private",
                "private_director_template": str(template),
                "private_asset_registry": str(registry),
                "creative_defaults": {
                    "target_duration_seconds": 600,
                    "initial_audience": {
                        "age_min": 6,
                        "age_max": 10,
                        "language": "en",
                        "made_for_kids": True,
                    },
                },
                "packaging_defaults": {
                    "platform_targets": ["youtube_long"],
                    "brand_hashtag": "ExampleBrand",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STORY_STUDIO_PROFILE_PATH", str(profile_file))
    store = StudioStore(tmp_path / "studio.sqlite3")
    story = store.create_story({"title": "Profile defaults", "premise": "A story idea"})
    assert story["requested_duration_seconds"] == 600
    assert story["request"]["platform_targets"] == ["youtube_long"]
    assert story["request"]["audience"] == {
        "age_min": 6,
        "age_max": 10,
        "language": "en",
        "intended_made_for_kids": True,
        "made_for_kids": None,
        "reviewed": False,
    }
    assert (
        story["request"]["profile_snapshot"]["packaging_defaults"]["brand_hashtag"]
        == "ExampleBrand"
    )
    assert (
        "cast_culture_policy"
        in story["request"]["profile_snapshot"]["director_template"]
    )
    _evidence(store, story["story_id"])
    _creative(store, story["story_id"])
    _complete_flow_receipts(store, story["story_id"], tmp_path)
    master = _make_av(tmp_path / "profile-master.mp4")
    captions = tmp_path / "profile.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nA short reviewed caption.\n",
        encoding="utf-8",
    )
    _register_variant(store, story["story_id"], master, captions, "master-en")
    package = build_platform_package(
        store, story["story_id"], master_path=master, platforms=("youtube_long",)
    )
    assert package["platforms"]["youtube_long"]["hashtags"][0] == "#ExampleBrand"


def test_routed_storyboard_draft_validates_ids_and_exports_full_director_contract(
    tmp_path, monkeypatch
):
    import app.services.llm as llm

    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    _evidence(store, sid)
    screenplay = {
        "schema_version": 1,
        "roles": [
            {
                "role_id": "narrator",
                "name": "Narrator",
                "function": "guide",
                "voice_direction": "warm",
            }
        ],
        "scenes": [
            {
                "scene_id": "s1",
                "setting": "garden",
                "visual_intent": "sharing",
                "lines": [
                    {
                        "role_id": "narrator",
                        "text": "They shared the fruit.",
                        "delivery": "gentle",
                    }
                ],
            }
        ],
    }
    ingest_screenplay_document(store, sid, screenplay, source="mocked test screenplay")
    shot = {
        "shot_id": "shot-01",
        "scene_id": "s1",
        "duration_seconds": 8,
        "treatment": "soft storybook realism",
        "camera": "slow dolly in",
        "lighting": "warm morning",
        "weather": "clear",
        "props": ["basket"],
        "audio": "narrator only; no synthesized voice requested",
        "transition": "gentle dissolve",
        "roles": ["narrator"],
        "reference_assets": [],
        "capabilities": ["text-to-video"],
        "prompt": "A gentle garden sharing scene.",
    }
    captured = {}

    def fake_generate(prompt, *, app_config, stage, task_type):
        captured.update(
            {
                "prompt": json.loads(prompt),
                "app_config": app_config,
                "stage": stage,
                "task_type": task_type,
            }
        )
        return json.dumps({"schema_version": 1, "shots": [shot]})

    monkeypatch.setattr(llm, "_call_generate_response", fake_generate)
    artifact = request_storyboard_draft(store, sid, app_config={"llm_provider": "mock"})
    assert artifact["document"]["shots"][0]["camera"] == "slow dolly in"
    assert captured["stage"] == "storyboard"
    assert captured["task_type"] == "storyboarding"
    assert captured["app_config"]["_cost_router_job_id"] == sid
    assert (
        captured["prompt"]["output_contract"]["shots"][0]["weather"]
        == "weather or null"
    )
    assert store.phase(sid, "storyboard")["status"] == "complete"
    bundle = export_flow_bundle(store, sid)
    exported = bundle["shots"][0]
    for field in (
        "treatment",
        "camera",
        "lighting",
        "weather",
        "props",
        "audio",
        "transition",
    ):
        assert exported[field] == shot[field]


@pytest.mark.parametrize(
    "bad_shots,match",
    [
        (
            [
                {"shot_id": "same", "duration_seconds": 8, "prompt": "one"},
                {"shot_id": "same", "duration_seconds": 8, "prompt": "two"},
            ],
            "unique shot_id",
        ),
        (
            [
                {
                    "shot_id": "bad-duration",
                    "duration_seconds": float("inf"),
                    "prompt": "one",
                }
            ],
            "finite positive",
        ),
        (
            [
                {
                    "shot_id": "unknown-ref",
                    "duration_seconds": 8,
                    "prompt": "one",
                    "reference_assets": ["not-approved"],
                }
            ],
            "unknown approved asset",
        ),
        (
            [
                {
                    "shot_id": "unknown-scene",
                    "duration_seconds": 8,
                    "prompt": "one",
                    "scene_id": "not-in-screenplay",
                }
            ],
            "unknown scene_id",
        ),
    ],
)
def test_storyboard_ingest_rejects_invalid_closed_contract_ids(
    tmp_path, bad_shots, match
):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    _evidence(store, sid)
    screenplay = {
        "schema_version": 1,
        "roles": [
            {
                "role_id": "narrator",
                "name": "Narrator",
                "function": "guide",
                "voice_direction": "warm",
            }
        ],
        "scenes": [
            {
                "scene_id": "s1",
                "setting": "garden",
                "visual_intent": "sharing",
                "lines": [
                    {
                        "role_id": "narrator",
                        "text": "They shared fruit.",
                        "delivery": "gentle",
                    }
                ],
            }
        ],
    }
    ingest_screenplay_document(store, sid, screenplay, source="test screenplay")
    with pytest.raises(ValueError, match=match):
        ingest_storyboard_document(
            store, sid, {"schema_version": 1, "shots": bad_shots}
        )


def test_running_phase_is_single_worker_and_crash_recovery_holds_external_call(
    tmp_path,
):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    store.run_phase(sid, "research", {"q": 1}, lambda: {"status": "complete"})
    with store.transaction() as conn:
        conn.execute(
            "UPDATE story_phases SET status='running' WHERE story_id=? AND phase='creative'",
            (sid,),
        )
    with pytest.raises(RuntimeError, match="active worker"):
        store.run_phase(
            sid,
            "creative",
            {"prompt": "same"},
            lambda: pytest.fail("must not launch a second worker"),
        )
    assert store.recover_stale_phase(sid, "creative") == "needs_manual"
    assert (
        store.recover_stale_phase(sid, "creative", external_call_may_have_started=False)
        == "needs_manual"
    )
    assert (
        store.resolve_manual_phase(
            sid, "creative", verified_no_duplicate_submission=False
        )
        == "needs_manual"
    )
    assert (
        store.resolve_manual_phase(
            sid, "creative", verified_no_duplicate_submission=True
        )
        == "failed"
    )
    with pytest.raises(RuntimeError, match="expected failure"):
        store.run_phase(
            sid,
            "creative",
            {"prompt": "uncertain"},
            lambda: (_ for _ in ()).throw(RuntimeError("expected failure")),
            external_call_may_have_started=True,
        )
    assert store.phase(sid, "creative")["status"] == "needs_manual"
    with pytest.raises(RuntimeError, match="held for human review"):
        store.run_phase(
            sid,
            "creative",
            {"prompt": "uncertain"},
            lambda: pytest.fail("must not retry automatically"),
        )


def test_research_change_invalidates_downstream_and_stale_flow_export_is_rejected(
    tmp_path,
):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    _evidence(store, sid)
    _creative(store, sid)
    bundle = export_flow_bundle(store, sid)
    media = _make_av(tmp_path / "shot.mp4")
    store.import_flow_receipt(
        sid,
        {
            "shot_id": "shot-01",
            "prompt_sha256": bundle["shots"][0]["prompt_sha256"],
            "asset_path": str(media),
        },
    )
    assert store.phase(sid, "flow")["status"] == "complete"
    store.add_evidence(
        sid,
        {
            "source": "new source",
            "category": "source_script_adaptation",
            "rights_status": "public_domain",
            "confidence": "high",
        },
    )
    assert store.phase(sid, "storyboard")["status"] == "queued"
    with pytest.raises(ValueError, match="stale"):
        store.import_flow_receipt(
            sid,
            {
                "shot_id": "shot-01",
                "prompt_sha256": bundle["shots"][0]["prompt_sha256"],
                "asset_path": str(media),
            },
        )


def test_quality_rejects_text_file_even_with_claimed_reviewer_pass(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    _evidence(store, sid)
    _creative(store, sid)
    _complete_flow_receipts(store, sid, tmp_path)
    bad_master = tmp_path / "not-a-video.mp4"
    bad_master.write_text("this is not a video", encoding="utf-8")
    build_platform_package(store, sid, master_path=bad_master)
    report = quality_report(store, sid, master_path=bad_master)
    assert any("decode_failed" in issue for issue in report["issues"])
    fake_review = {
        "status": "passed",
        "story_id": sid,
        "script_sha256": report["script_sha256"],
        "master_sha256": report["master_sha256"],
        "reviewer": "test",
        "technical_decode_pass": True,
        "visual_review_pass": True,
        "audio_review_pass": True,
    }
    with pytest.raises(ValueError, match="decode check"):
        import_quality_review(store, sid, fake_review, master_path=bad_master)


def test_account_check_receipt_is_a_hold_and_does_not_create_a_receipt(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)["story_id"]
    _evidence(store, sid)
    _creative(store, sid)
    result = store.import_flow_receipt(
        sid, {"provider_account_check_required": True, "status": "account_check"}
    )
    assert result == {
        "status": "requires_human",
        "automatic_retry": False,
        "provider_account_check_required": True,
    }
    assert store.phase(sid, "flow")["status"] == "needs_manual"
    assert store.flow_receipts(sid) == []
