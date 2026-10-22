import pytest

from app.services.studio_delivery_tracker import Tracker, digest


@pytest.fixture
def tracker(tmp_path):
    t = Tracker.create(tmp_path / "private" / "tracker", "sample-channel")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "movie.mp4").write_bytes(b"original-movie")
    (assets / "movie_v2.mp4").write_bytes(b"corrected-movie")
    (assets / "login-screenshot.png").write_bytes(b"private")
    t.bind_root("media", assets)
    t.add_release(
        {
            "release_id": "story.en.v2",
            "story_id": "story",
            "title": "Sample story",
            "version": "v2",
            "locale": "en",
            "quality": "accepted_ai_review",
            "targets": ["youtube_long", "rumble"],
            "master": {"root": "media", "relative_path": "movie_v2.mp4"},
            "master_sha256": digest(assets / "movie_v2.mp4"),
        }
    )
    return t


def event(t, **changes):
    return {
        "event_id": "receipt-1",
        "release_id": "story.en.v2",
        "platform": "youtube_long",
        "status": "public_verified",
        "master_sha256": t.catalog["releases"]["story.en.v2"]["master_sha256"],
        "observed_at": "2026-10-22T14:00:00+00:00",
        "url": "https://www.youtube.com/watch?v=example",
        "evidence": {
            "kind": "native_library",
            "public_visibility_observed": True,
            "note": "Correct title and Public in official channel library",
        },
        **changes,
    }


def test_relocate_and_hash_verify_without_old_laptop_paths(tracker, tmp_path):
    t = tracker
    assert t.scan("media", story_id="story") == 2
    catalog = t.catalog_path.read_text()
    assert str(tmp_path) not in catalog
    new = tmp_path / "new-laptop"
    new.mkdir()
    old = t.resolve({"root": "media", "relative_path": "."})
    for p in old.iterdir():
        (new / p.name).write_bytes(p.read_bytes())
    t.bind_root("media", new)
    assert t.verify_files() == []
    (new / "movie.mp4").write_bytes(b"corrupt")
    assert t.verify_files()[0]["issue"] == "hash_mismatch"


def test_versions_and_modified_bytes_retained(tracker):
    t = tracker
    t.scan("media")
    p = t.resolve({"root": "media", "relative_path": "movie.mp4"})
    p.write_bytes(b"changed")
    t.scan("media")
    t._reload()
    assert len(t.catalog["files"]) == 2
    changed = next(
        x for x in t.catalog["files"].values() if x["relative_path"] == "movie.mp4"
    )
    assert (
        changed["previous_bytes"]
        and changed["sha256"] != changed["previous_bytes"][0]["sha256"]
    )


def test_upload_processing_and_owner_report_are_not_all_published(tracker):
    t = tracker
    t.record(
        event(
            t,
            status="processing",
            evidence={"kind": "upload_complete", "note": "Processing only"},
        )
    )
    t.record(
        event(
            t,
            event_id="owner-rumble",
            platform="rumble",
            status="owner_reported",
            evidence={"kind": "owner_message", "note": "Owner reports upload complete"},
        )
    )
    assert not t.report()["releases"][0]["all_targets_public_verified"]


def test_verification_provenance_and_exact_master_required(tracker):
    t = tracker
    with pytest.raises(ValueError, match="native visibility"):
        t.record(
            event(t, evidence={"kind": "upload_complete", "note": "Clicked publish"})
        )
    with pytest.raises(ValueError, match="different master"):
        t.record(event(t, master_sha256="a" * 64))
    with pytest.raises(ValueError, match="URL"):
        t.record(event(t, url=None))


def test_idempotent_append_and_mutation_detection(tracker):
    t = tracker
    first = t.record(event(t))
    assert t.record(event(t)) == first
    assert len(t.events()) == 1
    with pytest.raises(ValueError, match="Idempotency"):
        t.record(event(t, status="private"))
    t.events_path.write_text(
        t.events_path.read_text().replace("Correct title", "Forged title")
    )
    with pytest.raises(ValueError, match="integrity"):
        t.events()


def test_old_receipt_does_not_override_recent_private(tracker):
    t = tracker
    t.record(event(t, status="private", event_id="private-now"))
    t.record(
        event(
            t,
            event_id="late-history",
            observed_at="2026-10-20T14:00:00+00:00",
            status="historical_published",
        )
    )
    assert t.report()["releases"][0]["platforms"]["youtube_long"]["status"] == "private"


def test_no_escape_or_symlink_read(tracker, tmp_path):
    t = tracker
    for relative in ("../other.mp4", "/etc/passwd", "..\\secret"):
        with pytest.raises(ValueError):
            t.resolve({"root": "media", "relative_path": relative})
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"secret")
    root = t.resolve({"root": "media", "relative_path": "."})
    (root / "link.mp4").symlink_to(secret)
    assert t.scan("media") == 2
    with pytest.raises(ValueError, match="symlink"):
        t.resolve({"root": "media", "relative_path": "link.mp4"})


def test_release_immutable_and_no_automatic_approval(tracker):
    t = tracker
    release = t.catalog["releases"]["story.en.v2"]
    with pytest.raises(ValueError, match="immutable"):
        t.add_release({**release, "title": "New title"})
    assert not t.report()["releases"][0]["all_targets_public_verified"]


def test_observation_times_compare_actual_instants_and_reject_naive(tracker):
    t = tracker
    t.record(event(t, status="private", observed_at="2026-10-22T10:00:00-04:00"))
    t.record(
        event(
            t,
            event_id="older-utc",
            status="historical_published",
            observed_at="2026-10-22T13:30:00+00:00",
        )
    )
    assert t.report()["releases"][0]["platforms"]["youtube_long"]["status"] == "private"
    with pytest.raises(ValueError, match="timezone"):
        t.record(event(t, event_id="naive", observed_at="2026-10-22T16:00:00"))


def test_research_citations_do_not_clear_reused_asset_rights():
    from app.services.studio_growth import _rights_status

    assets = [
        {"source": category, "category": category, "rights_status": "original"}
        for category in (
            "source_script_adaptation",
            "visual",
            "voice",
            "music_ambience",
        )
    ]
    reference = {
        "source": "https://example.org/retelling",
        "category": "research_plot_comparison",
        "rights_status": "reference_only_not_reused",
        "claim": "Compare traditional plot; modern text not copied",
        "notes": "No source wording/art/audio reused",
    }
    assert _rights_status([*assets, reference])[0]
    assert not _rights_status([reference])[0]
    assert not _rights_status([*assets, {**reference, "category": "visual"}])[0]
    assert not _rights_status([*assets, {**reference, "notes": ""}])[0]


def test_studio_file_registration_updates_opt_in_tracker(
    tracker, tmp_path, monkeypatch
):
    from app.services.story_studio import StudioStore

    t = tracker
    monkeypatch.setenv("STORY_STUDIO_DELIVERY_TRACKER_PATH", str(t.root))
    store = StudioStore(tmp_path / "studio.sqlite3")
    story = store.create_story(
        {
            "title": "Sample",
            "premise": "A child learns to share",
            "profile_id": "generic_public_starter",
        }
    )
    path = t.resolve({"root": "media", "relative_path": "movie_v2.mp4"})
    artifact = store.add_artifact(story["story_id"], "review_document", path=path)
    assert artifact["provenance"]["delivery_tracker"]["sha256"] == digest(path)
    assert t.report()["file_count"] == 1
    outside = tmp_path / "external.json"
    outside.write_text("{}")
    with pytest.raises(ValueError, match="bind its working folder"):
        store.add_artifact(story["story_id"], "research_document", path=outside)


def test_legacy_public_visibility_cannot_imply_upload_byte_identity(tracker):
    t = tracker
    release = {
        **t.catalog["releases"]["story.en.v2"],
        "release_id": "legacy.en.v1",
        "quality": "legacy_not_current_contract",
        "targets": ["youtube_long"],
    }
    t.add_release(release)
    observation = event(
        t,
        event_id="legacy-unbound",
        release_id="legacy.en.v1",
        evidence={
            "kind": "native_library",
            "public_visibility_observed": True,
            "upload_source_binding": "unverified_historical_variant",
            "note": "Visible Public; uploaded historical source variant unknown",
        },
    )
    observation.pop("master_sha256")
    t.record(observation)
    row = next(r for r in t.report()["releases"] if r["release_id"] == "legacy.en.v1")
    assert row["all_targets_public_verified"]
    assert not row["all_targets_exact_master_bound"]
    with pytest.raises(ValueError, match="bound upload master"):
        t.record(
            {
                **observation,
                "event_id": "new-cannot-be-unbound",
                "release_id": "story.en.v2",
            }
        )
