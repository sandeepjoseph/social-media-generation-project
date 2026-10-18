"""Cost savings must not replay paid work or manufacture creative approval."""

import copy
import hashlib
import json

import pytest

from app.services import studio_efficiency as efficiency
from app.services import story_studio as studio
from test.services.test_studio_cinema import (
    configured as cinema_configured,
    ready_story,
)


def test_saved_take_blocks_duplicate_even_while_creative_review_is_pending(tmp_path):
    source = tmp_path / "native.mp4"
    source.write_bytes(b"Native hash fixture")
    shot = {"shot_id": "a", "prompt": "One actor asks the exact question."}
    receipt = {
        "shot_id": "a",
        "prompt_sha256": hashlib.sha256(shot["prompt"].encode()).hexdigest(),
        "asset_path": str(source),
        "asset_sha256": efficiency.file_sha(source),
    }
    result = efficiency.saved_take(shot, [receipt])
    assert not result["generation_allowed"]
    assert not result["creative_approval_implied"]
    source.write_bytes(b"Changed source")
    assert (
        efficiency.saved_take(shot, [receipt])["status"]
        == "saved_take_changed_or_missing_hold"
    )
    assert not efficiency.saved_take(shot, [receipt])["generation_allowed"]
    shot["prompt"] += " A newly replanned performance."
    assert efficiency.saved_take(shot, [receipt])["generation_allowed"]


def test_decode_cache_reuses_actual_identical_bytes_and_rejects_changes(tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"first")
    cache = efficiency.VerifiedDecodeCache()
    calls = []

    def decoder(path):
        calls.append(path)
        return True, "actual fixture decode"

    assert cache.check(source, decoder)[0]
    assert cache.check(source, decoder)[1].startswith("reused_actual_decode")
    assert len(calls) == 1
    source.write_bytes(b"other")
    assert cache.check(source, decoder)[0]
    assert len(calls) == 2

    def changed_decoder(path):
        path.write_bytes(b"during decode")
        return True, "must never be cached"

    assert cache.check(source, changed_decoder) == (
        False,
        "media_changed_during_decode",
    )


def test_failed_decode_is_not_promoted_or_cached(tmp_path):
    source = tmp_path / "bad.mp4"
    source.write_bytes(b"bad")
    cache = efficiency.VerifiedDecodeCache()
    calls = []

    def decoder(path):
        calls.append(path)
        return False, "failed"

    assert not cache.check(source, decoder)[0]
    assert not cache.check(source, decoder)[0]
    assert len(calls) == 2


def test_prompt_reordering_is_lossless_and_deduplicates_only_identical_rules():
    prompt = {
        "task": "Draft",
        "story": {"title": "Dynamic story"},
        "evidence": ["Source A"],
        "production_profile": {
            "role_briefs": {"director": "Act and speak"},
            "full_director_template": {
                "role_briefs": {"director": "Act and speak"},
                "unique_rule": "Keep this too",
            },
        },
        "constraints": ["Exact words unchanged"],
    }
    old = copy.deepcopy(prompt)
    result = json.loads(efficiency.cache_friendly_prompt(prompt))
    assert prompt == old
    assert list(result)[0] == "production_profile"
    assert (
        result["story"] == prompt["story"] and result["evidence"] == prompt["evidence"]
    )
    assert (
        result["production_profile"]["role_briefs"]
        == prompt["production_profile"]["role_briefs"]
    )
    assert result["production_profile"]["full_director_template"] == {
        "unique_rule": "Keep this too"
    }
    assert result["constraints"] == prompt["constraints"]


def test_reusable_image_requires_exact_context_media_rights_and_review(tmp_path):
    spec = {
        "kind": "image",
        "reference_hashes": ["a" * 64],
        "scene": "court",
        "style": "3D",
        "wardrobe": "cream",
        "lighting": "day",
        "composition": "single",
        "output_spec": "1280x720",
    }
    source = tmp_path / "image.png"
    source.write_bytes(b"image fixture")
    review = tmp_path / "review.txt"
    review.write_text("Actual-review hash fixture")
    record = {
        "recipe_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "path": str(source),
        "sha256": efficiency.file_sha(source),
        "review_path": str(review),
        "review_sha256": efficiency.file_sha(review),
        "review_status": "passed",
        "rights_status": "original",
    }
    assert (
        efficiency.reusable_asset(spec, [record])["status"]
        == "verified_reuse_candidate"
    )
    changed = {**spec, "lighting": "night"}
    assert (
        efficiency.reusable_asset(changed, [record])["status"]
        == "no_verified_exact_match"
    )
    record["rights_status"] = "unknown"
    assert (
        efficiency.reusable_asset(spec, [record])["status"] == "no_verified_exact_match"
    )
    with pytest.raises(ValueError, match="native character speech"):
        efficiency.reusable_asset({"kind": "character_tts", "text": "Hello"}, [])


@pytest.fixture(name="configured")
def configured_fixture(tmp_path, monkeypatch):
    return cinema_configured.__wrapped__(tmp_path, monkeypatch)


def test_flow_export_defaults_to_reuse_saved_take_instead_of_spending_again(
    configured, tmp_path, monkeypatch
):
    store, sid, _, _ = ready_story(configured)
    bundle = studio.export_flow_bundle(store, sid)
    source = tmp_path / "native.mp4"
    source.write_bytes(b"Hash fixture only, no real performance claim")
    monkeypatch.setattr(studio, "video_duration_seconds", lambda p: 8)
    shot = bundle["shots"][0]
    store.import_flow_receipt(
        sid,
        {
            "shot_id": shot["shot_id"],
            "prompt_sha256": shot["prompt_sha256"],
            "asset_path": str(source),
            "provider": "test",
        },
    )
    repeated = studio.export_flow_bundle(store, sid)
    assert repeated["shots"][0]["generation_allowed"] is False
    assert repeated["shots"][0]["max_outputs_per_request"] == 1
    assert repeated["efficiency"]["saved_matching_takes"] == 1
    assert repeated["efficiency"]["quality_gates_unchanged"] is True
