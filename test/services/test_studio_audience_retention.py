import hashlib

import pytest

from app.services.studio_audience import audience_distribution_plan, release_window
from app.services.studio_retention import cleanup_plan, validate_owner_confirmation


def test_market_preferences_do_not_claim_geo_restriction_or_ad_purchase():
    plan = audience_distribution_plan({"primary_country": "IN", "release_timezone": "Asia/Kolkata"})
    assert plan["primary_country"] == "IN"
    assert plan["country_performance"] is None
    assert not plan["organic_geographic_guarantee"]
    assert not plan["paid_campaign_created"]
    assert not plan["account_residence_change"]
    assert not plan["exclude_existing_viewers"]


def test_india_window_conversion_handles_canadian_dst():
    policy = {"primary_country": "IN", "release_timezone": "Asia/Kolkata", "release_window": {"start": "18:00", "end": "20:00"}}
    assert release_window("2026-11-22", policy)["operator_start"] == "2026-11-22T07:30:00-05:00"
    assert release_window("2026-06-22", policy)["operator_start"] == "2026-06-22T08:30:00-04:00"


@pytest.mark.parametrize("policy", [{"primary_country": "Africa"}, {"release_window": {"start": "25:00", "end": "20:00"}}, {"release_window": {"start": "18:00", "end": "18:00"}}])
def test_invalid_market_configuration_is_rejected(policy):
    with pytest.raises(ValueError):
        audience_distribution_plan(policy)


def _plan(tmp_path, *, complete=True, path=None, expected=None):
    media = path or tmp_path / "episode.mp4"
    if path is None:
        media.write_bytes(b"fixture video bytes")
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    master = "a" * 64
    receipt = {"release_id": "episode-v1", "master_sha256": master, "platform": "youtube_long", "status": "public_verified", "public_url": "https://youtu.be/example", "observed_at": "2026-11-22T15:00:00Z"}
    return cleanup_plan(release_id="episode-v1", master_sha256=master, media=[{"path": str(media), "sha256": expected or sha}], allowed_roots=[tmp_path], required_platforms=["youtube_long", "rumble"] if not complete else ["youtube_long"], receipts=[receipt])


def test_missing_platform_holds_cleanup_and_does_not_delete(tmp_path):
    plan = _plan(tmp_path, complete=False)
    assert plan["missing_publication_receipts"] == ["rumble"]
    assert not plan["ready_to_ask_owner"]
    assert (tmp_path / "episode.mp4").exists()


def test_owner_approval_must_bind_exact_unchanged_plan(tmp_path):
    plan = _plan(tmp_path)
    confirmation = {"approved": True, "plan_sha256": plan["plan_sha256"], "owner_message_reference": "actual owner message"}
    assert plan["ready_to_ask_owner"]
    assert not plan["automatic_deletion_allowed"]
    assert validate_owner_confirmation(plan, confirmation)
    plan["candidates"][0]["path"] = "/unrelated.mp4"
    assert not validate_owner_confirmation(plan, confirmation)
    assert (tmp_path / "episode.mp4").exists()


def test_changed_media_holds_cleanup(tmp_path):
    assert _plan(tmp_path, expected="b" * 64)["issues"][0]["issue"] == "hash_mismatch"


def test_document_and_symlink_are_never_cleanup_candidates(tmp_path):
    document = tmp_path / "preferences.json"
    document.write_text("{}")
    assert _plan(tmp_path, path=document)["issues"][0]["issue"] == "unsafe_or_non_media_path"
    link = tmp_path / "linked.mp4"
    link.symlink_to(document)
    assert _plan(tmp_path, path=link)["issues"][0]["issue"] == "unsafe_or_non_media_path"
