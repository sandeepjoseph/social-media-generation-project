"""Bound paid rollout exposure; fixture bytes never assert real A/V quality."""

import copy
import pytest
from app.services import story_studio as studio
from app.services import studio_cinema as cinema
from test.services.test_studio_cinema import (
    configured as base_fixture,
    ready_story,
    review_for,
    submission_fixture,
)


@pytest.fixture
def production(tmp_path, monkeypatch):
    configured = base_fixture.__wrapped__(tmp_path, monkeypatch)
    store, sid, _, board = ready_story(configured)
    monkeypatch.setattr(studio, "video_duration_seconds", lambda p: 8.0)

    def deliver(shot):
        media = tmp_path / (shot["shot_id"] + ".mp4")
        media.write_bytes(("Synthetic hash fixture " + shot["shot_id"]).encode())
        store.import_flow_receipt(
            sid,
            {
                "shot_id": shot["shot_id"],
                "prompt_sha256": shot["prompt_sha256"],
                "asset_path": str(media),
                "submission_attestation": submission_fixture(shot, store, sid),
            },
        )
        return media

    initial = studio.export_flow_bundle(store, sid)
    for shot in initial["shots"][:2]:
        deliver(shot)
    sha = store.latest_artifact(sid, "storyboard")["sha256"]
    pilot = review_for(board, store.flow_receipts(sid), sha, pilot=True)
    pilot["story_id"] = sid
    studio.import_performance_pilot_review(store, sid, pilot)
    bundle = studio.export_flow_bundle(store, sid)
    ids = bundle["generation_batch"]["allowed_shot_ids"]
    paths = [deliver(s) for s in bundle["shots"] if s["shot_id"] in ids]
    subset = {"shots": [s for s in board["shots"] if s["shot_id"] in ids]}
    review = review_for(subset, store.flow_receipts(sid), sha)
    review.update(story_id=sid, batch_shot_ids=ids)
    return store, sid, board, bundle, paths, review


def test_only_four_shots_release_then_pending_review_blocks_next_batch(production):
    store, sid, _, bundle, _, review = production
    assert len(bundle["generation_batch"]["allowed_shot_ids"]) == 4
    held = studio.export_flow_bundle(store, sid)
    assert not any(s["generation_allowed"] for s in held["shots"])
    assert len(held["generation_batch"]["pending_source_review_ids"]) == 4
    form = studio.performance_batch_review_template(store, sid)
    assert form["status"] == "needs_review"
    assert all(s["performance_pass"] is False for s in form["shots"])
    assert studio.import_performance_batch_review(store, sid, review)["accepted"]
    released = studio.export_flow_bundle(store, sid)
    assert len(released["generation_batch"]["allowed_shot_ids"]) == 4
    assert not set(released["generation_batch"]["allowed_shot_ids"]).intersection(
        review["batch_shot_ids"]
    )
    assert not released["generation_batch"]["full_film_approval"]


@pytest.mark.parametrize(
    "defect",
    [
        "observed_issues",
        "curation_issues",
        "unresolved_issues",
        "tracking",
        "props",
        "normal",
        "half",
        "scope",
        "stale",
        "hash",
    ],
)
def test_positive_booleans_do_not_release_defective_or_unbound_batch(
    production, defect
):
    store, sid, _, _, _, review = production
    first = review["shots"][0]
    if defect in {"observed_issues", "curation_issues", "unresolved_issues"}:
        first[defect] = ["Visible unexpected actor despite positive flags"]
    if defect == "tracking":
        first["head_eye_hand_tracking_pass"] = False
    if defect == "props":
        first["single_actor_and_prop_state_pass"] = False
    if defect == "normal":
        first["normal_full_utterance_reviewed"] = False
    if defect == "half":
        first["half_speed_full_utterance_reviewed"] = False
    if defect == "scope":
        review["shots"].pop()
    if defect == "stale":
        review["storyboard_sha256"] = "0" * 64
    if defect == "hash":
        first["asset_sha256"] = "0" * 64
    assert not studio.import_performance_batch_review(store, sid, review)["accepted"]
    assert not any(
        s["generation_allowed"] for s in studio.export_flow_bundle(store, sid)["shots"]
    )
    assert len(store.artifact_history(sid, "performance_batch_review")) == 1


def test_later_negative_on_same_source_supersedes_positive(production):
    store, sid, _, _, _, review = production
    assert studio.import_performance_batch_review(store, sid, review)["accepted"]
    with store.transaction() as conn:
        conn.execute(
            "UPDATE story_phases SET status='complete' WHERE story_id=? AND phase IN ('assembly','quality','package')",
            (sid,),
        )
    negative = copy.deepcopy(review)
    negative["shots"][0]["observed_issues"] = [
        "Corrupt text was missed in first review"
    ]
    assert not studio.import_performance_batch_review(store, sid, negative)["accepted"]
    assert (
        studio.export_flow_bundle(store, sid)["generation_batch"]["status"]
        == "review_required"
    )
    assert len(store.artifact_history(sid, "performance_batch_review")) == 2
    assert store.phase(sid, "quality")["status"] == "queued"


def test_changed_or_missing_source_cannot_keep_old_acceptance(production):
    store, sid, _, _, paths, review = production
    assert studio.import_performance_batch_review(store, sid, review)["accepted"]
    paths[0].write_bytes(b"Changed fixture, not reviewed media")
    assert studio.export_flow_bundle(store, sid)["generation_batch"][
        "pending_source_review_ids"
    ]


@pytest.mark.parametrize(
    "flag", ["provider_account_check_required", "provider_content_policy_rejected"]
)
def test_reexport_does_not_erase_provider_hold(production, flag):
    store, sid, _, _, _, _ = production
    assert store.import_flow_receipt(sid, {flag: True})["automatic_retry"] is False
    with pytest.raises(ValueError, match="recorded provider hold"):
        studio.export_flow_bundle(store, sid)
    assert store.phase(sid, "flow")["status"] == "needs_manual"


@pytest.mark.parametrize("value", [0, 5, 4.5, True, False])
def test_private_policy_cannot_disable_or_expand_batch_cap(value):
    with pytest.raises(ValueError):
        cinema.policy_for(
            {
                "cinema_policy": {
                    "enabled": True,
                    "max_unreviewed_generation_batch_shots": value,
                }
            }
        )
