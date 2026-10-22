"""Validate an operator's actual provider composer before one paid activation.

This records UI observations, not a claim to inspect provider internals, cap
billing, or approve generated acting. Media still needs independent A/V review.
"""

from __future__ import annotations

import hashlib
import json
import math
import copy

VERSION = 1


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def submission_issues(shot, observed):
    if not isinstance(observed, dict):
        return ["provider_composer_observation_required"]
    issues = []
    if shot.get("generation_allowed") is not True:
        issues.append("canonical_generation_hold")
    if observed.get("shot_id") != shot.get("shot_id"):
        issues.append("provider_shot_binding_mismatch")
    # Contenteditable fill can append while looking like a replacement. A
    # contains() check would approve two scripts in a single provider request.
    if observed.get("prompt_text") != shot.get("prompt"):
        issues.append("provider_exact_prompt_readback_mismatch")
    references = sorted(a["sha256"] for a in shot.get("reference_assets", []))
    observed_references = observed.get("reference_sha256")
    if (
        not isinstance(observed_references, list)
        or any(not isinstance(h, str) for h in observed_references)
        or sorted(observed_references) != references
    ):
        issues.append("provider_reference_binding_mismatch")
    speaker = shot.get("visible_speaker_id")
    voice = (shot.get("dialogue") or {}).get("voice_id")
    if observed.get("visible_speaker_id") != speaker:
        issues.append("provider_actor_binding_mismatch")
    if observed.get("voice_id") != voice:
        issues.append("provider_saved_voice_binding_mismatch")
    if observed.get("native_audio") is not True:
        issues.append("provider_native_audio_required")
    if observed.get("output_count") != 1 or isinstance(
        observed.get("output_count"), bool
    ):
        issues.append("provider_single_output_required")
    if observed.get("duration_seconds") != shot.get("duration_seconds"):
        issues.append("provider_take_duration_mismatch")
    if not str(observed.get("model", "")).strip():
        issues.append("provider_model_observation_required")
    credits = observed.get("quoted_credits")
    if (
        isinstance(credits, bool)
        or not isinstance(credits, (int, float))
        or not math.isfinite(credits)
        or credits < 0
    ):
        issues.append("provider_live_credit_quote_required")
    if not str(observed.get("observed_by", "")).strip():
        issues.append("provider_observer_required")
    return sorted(set(issues))


def attest_submission(shot, observed, *, story_id, storyboard_sha256):
    issues = submission_issues(shot, observed)
    if issues:
        raise ValueError("; ".join(issues))
    payload = {
        "version": VERSION,
        "story_id": story_id,
        "storyboard_sha256": storyboard_sha256,
        "shot_id": shot["shot_id"],
        "prompt_sha256": hashlib.sha256(shot["prompt"].encode()).hexdigest(),
        "observed": copy.deepcopy(observed),
        "scope": "Operator UI readback; no provider-internal, billing-cap or creative-approval claim.",
    }
    return {"payload": payload, "sha256": fingerprint(payload)}


def attestation_issues(attestation, shot, *, story_id, storyboard_sha256):
    if not isinstance(attestation, dict) or not isinstance(
        attestation.get("payload"), dict
    ):
        return ["provider_submission_attestation_required"]
    payload = attestation["payload"]
    issues = []
    if attestation.get("sha256") != fingerprint(payload):
        issues.append("provider_submission_attestation_changed")
    if (
        payload.get("version") != VERSION
        or payload.get("story_id") != story_id
        or payload.get("storyboard_sha256") != storyboard_sha256
    ):
        issues.append("provider_submission_attestation_stale")
    if payload.get("shot_id") != shot.get("shot_id") or payload.get(
        "prompt_sha256"
    ) != shot.get("prompt_sha256"):
        issues.append("provider_submission_recipe_mismatch")
    return sorted(set(issues + submission_issues(shot, payload.get("observed"))))


def _cli():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Validate actual provider UI readback; never generates media"
    )
    parser.add_argument("bundle_json")
    parser.add_argument("shot_id")
    parser.add_argument("observation_json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    bundle = json.loads(Path(args.bundle_json).read_text(encoding="utf-8"))
    shot = next(s for s in bundle["shots"] if s["shot_id"] == args.shot_id)
    observed = json.loads(Path(args.observation_json).read_text(encoding="utf-8"))
    attestation = attest_submission(
        shot,
        observed,
        story_id=bundle["story_id"],
        storyboard_sha256=bundle["storyboard_sha256"],
    )
    output = Path(args.out).expanduser().resolve()
    output.write_text(
        json.dumps(attestation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "readback_validated_no_generation",
                "shot_id": args.shot_id,
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    _cli()
