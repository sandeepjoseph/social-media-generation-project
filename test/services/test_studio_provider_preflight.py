"""Guard actual failure modes seen in manual provider handoffs."""

import copy
import hashlib

import pytest

from app.services.studio_provider_preflight import (
    attest_submission,
    attestation_issues,
    submission_issues,
)


@pytest.fixture
def pair():
    shot = {
        "shot_id": "one",
        "prompt": 'Say only "A kind idea."',
        "generation_allowed": True,
        "visible_speaker_id": "a",
        "reference_assets": [{"sha256": "a" * 64}],
        "dialogue": {"voice_id": "voice-a"},
        "duration_seconds": 8,
    }
    shot["prompt_sha256"] = hashlib.sha256(shot["prompt"].encode()).hexdigest()
    observed = {
        "shot_id": "one",
        "prompt_text": shot["prompt"],
        "reference_sha256": ["a" * 64],
        "visible_speaker_id": "a",
        "voice_id": "voice-a",
        "native_audio": True,
        "output_count": 1,
        "duration_seconds": 8,
        "model": "fixture",
        "quoted_credits": 12,
        "observed_by": "synthetic UI fixture; no actual-media QA claim",
    }
    return shot, observed


def test_exact_observation_passes_without_creative_approval(pair):
    shot, observed = pair
    attestation = attest_submission(shot, observed, story_id="s", storyboard_sha256="b")
    assert not attestation_issues(
        attestation, shot, story_id="s", storyboard_sha256="b"
    )
    assert "creative-approval" in attestation["payload"]["scope"]
    observed["prompt_text"] = "a later edit"
    assert attestation["payload"]["observed"]["prompt_text"] == shot["prompt"]


@pytest.mark.parametrize(
    "field,value,error",
    [
        (
            "prompt_text",
            'Old line.Say only "A kind idea."',
            "provider_exact_prompt_readback_mismatch",
        ),
        ("reference_sha256", ["c" * 64], "provider_reference_binding_mismatch"),
        ("reference_sha256", None, "provider_reference_binding_mismatch"),
        ("visible_speaker_id", "b", "provider_actor_binding_mismatch"),
        ("voice_id", "voice-b", "provider_saved_voice_binding_mismatch"),
        ("native_audio", False, "provider_native_audio_required"),
        ("output_count", 2, "provider_single_output_required"),
        ("duration_seconds", 6, "provider_take_duration_mismatch"),
        ("quoted_credits", float("nan"), "provider_live_credit_quote_required"),
    ],
)
def test_wrong_actual_composer_is_blocked(pair, field, value, error):
    shot, observed = pair
    observed[field] = value
    assert error in submission_issues(shot, observed)
    with pytest.raises(ValueError, match=error):
        attest_submission(shot, observed, story_id="s", storyboard_sha256="b")


def test_pilot_hold_cannot_be_attested_away(pair):
    shot, observed = pair
    shot["generation_allowed"] = False
    assert "canonical_generation_hold" in submission_issues(shot, observed)


def test_stale_or_tampered_attestation_is_rejected(pair):
    shot, observed = pair
    attestation = attest_submission(shot, observed, story_id="s", storyboard_sha256="b")
    assert "provider_submission_attestation_stale" in attestation_issues(
        attestation, shot, story_id="other", storyboard_sha256="b"
    )
    edited = copy.deepcopy(attestation)
    edited["payload"]["observed"]["voice_id"] = "wrong"
    issues = attestation_issues(edited, shot, story_id="s", storyboard_sha256="b")
    assert "provider_submission_attestation_changed" in issues
    assert "provider_saved_voice_binding_mismatch" in issues
