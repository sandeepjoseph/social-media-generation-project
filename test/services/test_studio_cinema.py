"""Regression contracts for performed films, duration and reusable improvements."""

import json

import pytest

from app.services import story_studio as studio
from app.services import studio_cinema as cinema


def film():
    script = {
        "schema_version": 1,
        "roles": [
            {
                "role_id": "a",
                "kind": "character",
                "voice_id": "original-a",
                "name": "A",
            },
            {
                "role_id": "b",
                "kind": "character",
                "voice_id": "original-b",
                "name": "B",
            },
        ],
        "scenes": [],
    }
    board = {"schema_version": 1, "shots": []}
    for s, beat in enumerate(["setup", "problem", "attempt", "turn", "resolution"]):
        scene = {
            "scene_id": f"scene-{s}",
            "setting": "garden",
            "story_beat": beat,
            "estimated_duration_seconds": 80,
            "action": "They examine and test an idea.",
            "dramatic_purpose": "Change what they understand.",
            "lines": [],
        }
        for n in range(10):
            role = "a" if n % 2 == 0 else "b"
            line = {
                "line_id": f"line-{s}-{n}",
                "role_id": role,
                "text": "Can we try this together?",
                "delivery": "curious",
            }
            scene["lines"].append(line)
            board["shots"].append(
                {
                    "shot_id": f"shot-{s}-{n}",
                    "scene_id": scene["scene_id"],
                    "duration_seconds": 8,
                    "roles": [role],
                    "reference_assets": [],
                    "speech_mode": "native_dialogue",
                    "visible_speaker_id": role,
                    "dialogue": {
                        "line_id": line["line_id"],
                        "speaker_id": role,
                        "text": line["text"],
                        "voice_id": f"original-{role}",
                    },
                    "audio_pipeline": "preserve_native_av",
                    "capabilities": ["native_speech", "lip_sync"],
                    "prompt": "The single visible actor asks the exact line and reacts.",
                    "camera": "eye level medium shot",
                    "lighting": "soft daylight",
                    "weather": "clear",
                    "action_start": "Examine the pot",
                    "action_end": "Offer it to the partner",
                    "emotional_direction": "curious to hopeful",
                    "eyeline": "partner off screen right",
                    "costume_state": "same green tunic",
                    "continuity": "pot in left hand, same daylight",
                    "transition": "motivated cut",
                }
            )
        script["scenes"].append(scene)
    return script, board


@pytest.fixture
def configured(tmp_path, monkeypatch):
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps({"role_briefs": {"director": "Characters act and speak."}})
    )
    assets = tmp_path / "assets.json"
    assets.write_text('{"assets": {}}')
    learning = tmp_path / "learning.json"
    learning.write_text('{"revision":1,"entries":[]}')
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "profile_id": "private-test",
                "profile_visibility": "private",
                "template_revision": "test-v2",
                "private_director_template": str(template),
                "private_asset_registry": str(assets),
                "private_learning_log": str(learning),
                "creative_defaults": {
                    "target_duration_seconds": 420,
                    "initial_audience": {"age_min": 6, "age_max": 10},
                },
                "cinema_policy": {"enabled": True},
            }
        )
    )
    monkeypatch.setenv("STORY_STUDIO_PROFILE_PATH", str(profile))
    store = studio.StudioStore(tmp_path / "studio.sqlite3")
    return store, learning


def ready_story(configured):
    store, _ = configured
    story = store.create_story({"title": "Sample film", "premise": "Try together"})
    sid = story["story_id"]
    store.add_evidence(
        sid,
        {
            "source": "Original fiction",
            "category": "source_script_adaptation",
            "claim": "Invented",
            "rights_status": "original",
            "confidence": "high",
        },
    )
    script, board = film()
    studio.ingest_screenplay_document(store, sid, script)
    studio.ingest_storyboard_document(store, sid, board)
    return store, sid, script, board


def review_for(board, receipts, board_hash, *, pilot=False):
    selected = (
        cinema.pilot_ids(board) if pilot else [s["shot_id"] for s in board["shots"]]
    )
    actual = {r["shot_id"]: r for r in receipts}
    return {
        "status": "passed",
        "storyboard_sha256": board_hash,
        "policy_sha256": cinema.digest(
            cinema.policy_for({"cinema_policy": {"enabled": True}})
        ),
        "reviewer": "Fixture reviewer",
        "full_scene_playback_pass": True,
        "acting_review_pass": True,
        "continuity_review_pass": True,
        "age_fit_pass": True,
        "shots": [
            {
                "shot_id": sid,
                "asset_sha256": actual[sid]["asset_sha256"],
                "performance_pass": True,
                "exact_words_pass": True,
                "correct_speaker_pass": True,
                "lip_sync_pass": True,
                "original_av_timing_preserved": True,
                "voice_consistency_pass": True,
                "review_method": "full_utterance_normal_and_half_speed",
                "sync_observations": [
                    {
                        "seconds": t,
                        "visible_and_audible_event": "Observed vowel opening and sound agree",
                    }
                    for t in (1, 2, 3)
                ],
            }
            for sid in selected
        ],
    }


def test_complete_performed_film_contract_passes():
    script, board = film()
    policy = cinema.policy_for({"cinema_policy": {"enabled": True}})
    assert cinema.screenplay_issues(script, policy) == []
    assert cinema.storyboard_issues(board, script, policy) == []
    assert cinema.pilot_ids(board) == ["shot-0-0", "shot-0-1"]


def test_native_export_preserves_provider_take_length_and_exact_prompt(
    configured, tmp_path, monkeypatch
):
    store, sid, script, board = ready_story(configured)
    shot = board["shots"][0]
    original_prompt = shot["prompt"]
    shot.update(
        duration_seconds=5.375,
        provider_take_duration_seconds=8,
        native_editorial_plan={
            "original_av_timing_preserved": True,
            "retiming": False,
            "voice_replacement": False,
            "provenance_sha256": "a" * 64,
        },
    )
    studio.ingest_storyboard_document(store, sid, board)
    exported = studio.export_flow_bundle(store, sid)["shots"][0]
    assert exported["duration_seconds"] == 8
    assert exported["timeline_duration_seconds"] == 5.375
    assert exported["prompt"] == original_prompt
    media = tmp_path / "native-edit-contract.mp4"
    media.write_bytes(
        b"Hash fixture only; duration measurement is mocked, no media-quality claim."
    )
    receipt = {
        "shot_id": exported["shot_id"],
        "prompt_sha256": exported["prompt_sha256"],
        "asset_path": str(media),
        "provider": "test",
    }
    monkeypatch.setattr(studio, "video_duration_seconds", lambda p: 8.0)
    with pytest.raises(ValueError, match="duration must match"):
        store.import_flow_receipt(sid, receipt)
    monkeypatch.setattr(studio, "video_duration_seconds", lambda p: 5.375)
    assert store.import_flow_receipt(sid, receipt)["shot_id"] == exported["shot_id"]


def test_reuse_only_export_never_authorizes_a_duplicate_cloud_request(configured):
    store, sid, _, board = ready_story(configured)
    board["shots"][0]["new_generation_required"] = False
    studio.ingest_storyboard_document(store, sid, board)
    bundle = studio.export_flow_bundle(store, sid)
    assert bundle["shots"][0]["generation_allowed"] is False
    assert bundle["shots"][1]["generation_allowed"] is True
    assert bundle["dialogue_pilot"]["accepted"] is False


@pytest.mark.parametrize("seconds", [56, 170, 256, 359, 481, float("nan"), True, None])
def test_short_or_unverified_full_episode_rejected(seconds):
    assert cinema.duration_issues(seconds, cinema.DEFAULTS, "master")


def test_a_short_never_substitutes_for_full_episode_intake(configured):
    store, _ = configured
    with pytest.raises(ValueError, match="outside_full_episode"):
        store.create_story(
            {"title": "Short", "premise": "Test", "target_duration_seconds": 56}
        )
    story = store.create_story({"title": "Full", "premise": "Test"})
    assert story["requested_duration_seconds"] == 420
    assert story["request"]["audience"]["age_max"] == 10


def test_narrator_only_story_is_rejected(configured):
    store, _ = configured
    sid = store.create_story({"title": "Test", "premise": "Test"})["story_id"]
    script, _ = film()
    for r in script["roles"]:
        r["kind"] = "narrator"
    with pytest.raises(ValueError, match="narration_dominates"):
        studio.ingest_screenplay_document(store, sid, script)


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (
            lambda s: s.update(audio_pipeline="mute_and_add_narrator"),
            "native_av_must_be_preserved",
        ),
        (
            lambda s: s.update(capabilities=["silent_video"]),
            "speech_capable_route_required",
        ),
        (
            lambda s: s.update(visible_speaker_id="b"),
            "speaker_or_voice_identity_mismatch",
        ),
        (
            lambda s: s["dialogue"].update(text="A changed line"),
            "dialogue_must_match_screenplay",
        ),
        (
            lambda s: s["dialogue"].update(voice_id="wrong"),
            "speaker_or_voice_identity_mismatch",
        ),
        (lambda s: s.update(action_end=""), "action_end_required"),
        (
            lambda s: s.update(speech_mode="narration"),
            "character_dialogue_cannot_be_narration",
        ),
    ],
)
def test_bad_performance_plan_cannot_export(configured, mutation, expected):
    store, sid, script, board = ready_story(configured)
    mutation(board["shots"][0])
    with pytest.raises(ValueError, match=expected):
        studio.ingest_storyboard_document(store, sid, board)


def test_native_dialogue_must_fit_the_take():
    script, board = film()
    script["scenes"][0]["lines"][0]["text"] = "word " * 40
    board["shots"][0]["dialogue"]["text"] = "word " * 40
    assert any(
        "dialogue_too_long" in s
        for s in cinema.storyboard_issues(board, script, cinema.DEFAULTS)
    )


def test_omitted_dialogue_and_picture_only_plan_fail():
    script, board = film()
    for shot in board["shots"]:
        shot["speech_mode"] = "establishing"
        shot.pop("dialogue")
    issues = cinema.storyboard_issues(board, script, cinema.DEFAULTS)
    assert "cinema:all_screenplay_lines_must_be_delivered_once" in issues
    assert "cinema:insufficient_character_performance_runtime" in issues


def test_bulk_receipts_are_held_until_bound_two_speaker_pilot(
    configured, tmp_path, monkeypatch
):
    store, sid, _, board = ready_story(configured)
    bundle = studio.export_flow_bundle(store, sid)
    assert [
        s["shot_id"] for s in bundle["shots"] if s["generation_allowed"]
    ] == cinema.pilot_ids(board)
    monkeypatch.setattr(studio, "video_duration_seconds", lambda p: 8.0)
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"This is a hash fixture; no media quality claim.")

    def receipt(index):
        shot = bundle["shots"][index]
        return {
            "shot_id": shot["shot_id"],
            "prompt_sha256": shot["prompt_sha256"],
            "asset_path": str(media),
            "provider": "test",
        }

    with pytest.raises(ValueError, match="pilot before bulk"):
        store.import_flow_receipt(sid, receipt(2))
    store.import_flow_receipt(sid, receipt(0))
    store.import_flow_receipt(sid, receipt(1))
    review = review_for(
        board,
        store.flow_receipts(sid),
        store.latest_artifact(sid, "storyboard")["sha256"],
        pilot=True,
    )
    review["story_id"] = sid
    studio.import_performance_pilot_review(store, sid, review)
    assert studio.export_flow_bundle(store, sid)["dialogue_pilot"]["accepted"] is True
    store.import_flow_receipt(sid, receipt(2))
    media.write_bytes(b"A replaced take must revoke the pilot implicitly.")
    assert studio.export_flow_bundle(store, sid)["dialogue_pilot"]["accepted"] is False


@pytest.mark.parametrize(
    "bad",
    [
        "hash",
        "asr_only",
        "no_samples",
        "no_sync",
        "missing_shot",
        "policy",
        "duplicate_sample",
    ],
)
def test_asr_assertions_or_unbound_reviews_cannot_pass(bad):
    _, board = film()
    policy = cinema.policy_for({"cinema_policy": {"enabled": True}})
    receipts = [
        {"shot_id": s["shot_id"], "asset_sha256": "a" * 64} for s in board["shots"]
    ]
    review = review_for(board, receipts, "b" * 64)
    first = review["shots"][0]
    if bad == "hash":
        first["asset_sha256"] = "c" * 64
    if bad == "asr_only":
        first["review_method"] = "asr_text_match"
    if bad == "no_samples":
        first["sync_observations"] = []
    if bad == "no_sync":
        first["lip_sync_pass"] = False
    if bad == "missing_shot":
        review["shots"].pop()
    if bad == "policy":
        review["policy_sha256"] = "c" * 64
    if bad == "duplicate_sample":
        first["sync_observations"] = [first["sync_observations"][0]] * 3
    assert cinema.performance_review_issues(
        review, board, receipts, policy=policy, storyboard_sha256="b" * 64
    )


def test_applied_learning_is_reused_but_experiments_are_not(configured):
    store, _ = configured
    old = store.create_story({"title": "First", "premise": "Test"})
    studio.record_learning_rule(
        criterion_id="acting", text="Let the listening partner react", status="applied"
    )
    studio.record_learning_rule(
        criterion_id="experiment", text="Try a new lens", status="experiment"
    )
    new = store.create_story({"title": "Second", "premise": "Test"})
    applied = new["request"]["profile_snapshot"]["learning_rules"]["applied"]
    assert len(applied) == 1 and applied[0]["criterion_id"] == "acting"
    assert studio.profile_status(store, old["story_id"])["needs_replan"] is True
    assert studio.profile_status(store, new["story_id"])["needs_replan"] is False


def test_explicit_refresh_revokes_approvals_and_preserves_old_artifacts(configured):
    store, sid, _, _ = ready_story(configured)
    previous = store.latest_artifact(sid, "screenplay")
    studio.record_learning_rule(
        criterion_id="sync", text="Review the whole utterance", status="applied"
    )
    with pytest.raises(ValueError, match="replan"):
        studio.export_flow_bundle(store, sid)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO approvals VALUES(?,?,?,?,?,?,?)",
            ("a", sid, "media", "package", "owner", 1.0, None),
        )
    studio.refresh_story_profile(store, sid)
    assert store.phase(sid, "creative")["status"] == "queued"
    assert store.latest_artifact(sid, "screenplay")["sha256"] == previous["sha256"]
    with store.connect() as conn:
        assert (
            conn.execute(
                "SELECT revoked_at FROM approvals WHERE approval_id='a'"
            ).fetchone()[0]
            is not None
        )
    assert studio.profile_status(store, sid)["needs_replan"] is False


def test_legacy_import_keeps_duration_but_new_release_cannot_pass(configured, tmp_path):
    store, _ = configured
    source = tmp_path / "old.json"
    source.write_text('{"title":"Old","duration_seconds":170}')
    before = source.read_bytes()
    result = studio.import_legacy_benchmark(store, source)
    sid = result["story_id"]
    assert store.story(sid)["requested_duration_seconds"] == 170
    assert source.read_bytes() == before
    assert cinema.duration_issues(170, cinema.DEFAULTS, "master")


def test_build_identity_detects_content_change(tmp_path):
    for name in (
        "app/services/studio_cinema.py",
        "app/services/story_studio.py",
        "webui/pages/2_Director_Studio.py",
    ):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("original")
    before = cinema.implementation_identity(tmp_path)
    (tmp_path / "app/services/studio_cinema.py").write_text("new rule")
    after = cinema.implementation_identity(tmp_path)
    assert before["implementation_sha256"] != after["implementation_sha256"]


@pytest.mark.parametrize("value", [float("nan"), -1, 1.2, True])
def test_bad_policy_is_not_loaded(value):
    with pytest.raises(ValueError):
        cinema.policy_for(
            {"cinema_policy": {"enabled": True, "max_narrator_word_fraction": value}}
        )
