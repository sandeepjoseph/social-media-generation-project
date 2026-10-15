import json
from pathlib import Path

import pytest

from app.services import media_delivery


def _policy(destination: Path, **overrides):
    values = {
        "destination": destination,
        "timezone": "America/Toronto",
        "enabled": True,
        "archive_on_generation": True,
        "preserve_versions": True,
    }
    values.update(overrides)
    return media_delivery.MediaArchivePolicy(**values)


def _artifact(source: Path, **overrides):
    values = {
        "source_path": source,
        "story_title": "Garden Story",
        "kind": "generated_video",
        "provenance": "generated",
        "created_at": "2026-10-16T01:30:00Z",
    }
    values.update(overrides)
    return media_delivery.MediaArtifact(**values)


def test_unconfigured_policy_returns_explicit_unconfigured_without_writing(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"sample video")

    result = media_delivery.add_artifact(
        _artifact(source), media_delivery.MediaArchivePolicy()
    )

    assert result["status"] == "unconfigured"
    assert result["copy_verified"] is False
    assert result["archive_path"] is None
    assert result["sha256"] is None
    assert list(tmp_path.iterdir()) == [source]


def test_archive_uses_timezone_story_locale_and_variant_and_records_absolute_paths(
    tmp_path,
):
    source = tmp_path / "quiet-evening.mp4"
    source.write_bytes(b"version one media")
    destination = tmp_path / "deliveries"
    policy = _policy(destination)
    artifact = _artifact(
        source,
        story_title="മലയാള കഥ",
        kind="generated_caption",
        source_path=tmp_path / "story.vtt",
        locale="ML",
        variant_id="v1",
    )
    caption = Path(artifact.source_path)
    caption.write_text("WEBVTT\n", encoding="utf-8")

    result = media_delivery.archive_media_artifact(artifact, policy)

    assert result["status"] == "archived"
    assert result["date"] == "2026-10-15"
    assert result["locale"] == "ml"
    assert result["variant_id"] == "v1"
    assert result["copy_verified"] is True
    assert result["source_preserved"] is True
    assert Path(result["source_path"]).is_absolute()
    assert Path(result["archive_path"]).is_absolute()
    assert Path(result["manifest_path"]).is_absolute()
    assert ".ml" in Path(result["archive_path"]).name
    assert "മലയാള-കഥ" in Path(result["archive_path"]).parent.name
    assert "2026-10-15" in Path(result["archive_path"]).name
    assert "v1" in Path(result["archive_path"]).name
    assert Path(result["archive_path"]).read_bytes() == b"WEBVTT\n"
    assert caption.read_text(encoding="utf-8") == "WEBVTT\n"
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["count"] == 1
    record = manifest["files"][0]
    assert record["source_path"] == str(caption.resolve())
    assert record["archive_path"] == str(Path(result["archive_path"]).resolve())
    assert record["sha256"] == result["sha256"]
    assert record["copy_verified"] is True


def test_long_unicode_filename_stays_within_byte_limit_and_keeps_malayalam_marks(
    tmp_path,
):
    # Stay below the filesystem's per-component byte limit while exercising a
    # long Unicode source basename and a separately bounded archive filename.
    source = tmp_path / ("കഥ" * 30 + ".mp4")
    source.write_bytes(b"sample")
    result = media_delivery.add_artifact(
        _artifact(source, story_title="ശാന്തമായ കഥ " * 80, locale="ml"),
        _policy(tmp_path / "deliveries"),
    )

    archive_name = Path(result["archive_path"]).name
    assert len(archive_name.encode("utf-8")) <= 255
    assert "ml" in archive_name
    assert "\u0d3e" in archive_name or "\u0d3f" in archive_name


def test_rearchive_is_idempotent_but_new_content_and_variants_get_new_names(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"version one")
    policy = _policy(tmp_path / "deliveries")
    first_artifact = _artifact(source, variant_id="v1")
    first = media_delivery.add_artifact(first_artifact, policy)
    repeated = media_delivery.add_artifact(first_artifact, policy)

    assert repeated["archive_path"] == first["archive_path"]
    manifest = json.loads(Path(first["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["count"] == 1

    second_variant = media_delivery.add_artifact(
        _artifact(source, variant_id="v2"), policy
    )
    source.write_bytes(b"version two, revised contents")
    revised = media_delivery.add_artifact(_artifact(source, variant_id="v2"), policy)

    assert second_variant["archive_path"] != first["archive_path"]
    assert revised["archive_path"] != second_variant["archive_path"]
    assert revised["sha256"] != first["sha256"]
    assert Path(first["archive_path"]).read_bytes() == b"version one"


def test_archive_is_disabled_for_generation_when_policy_says_so(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"sample")
    destination = tmp_path / "deliveries"

    result = media_delivery.add_artifact(
        _artifact(source), _policy(destination, archive_on_generation=False)
    )

    assert result["status"] == "disabled"
    assert not destination.exists()


def test_flow_receipt_provenance_can_archive_an_imported_caption(tmp_path):
    source = tmp_path / "captions.vtt"
    source.write_text("WEBVTT\n", encoding="utf-8")
    destination = tmp_path / "deliveries"

    result = media_delivery.add_artifact(
        _artifact(
            source,
            kind="imported_caption",
            provenance="flow_receipt",
            locale="en",
        ),
        _policy(destination),
    )

    assert result["status"] == "archived"
    assert result["provenance"] == "flow_receipt"
    assert ".en" in Path(result["archive_path"]).name


@pytest.mark.parametrize(
    ("filename", "kind", "provenance"),
    [
        ("login-screenshot.png", "generated_image", "generated"),
        ("private-account-details.png", "generated_image", "generated"),
        ("billing.png", "generated_image", "generated"),
        ("private.png", "not-a-kind", "generated"),
        ("clip.mp4", "generated_video", "unknown_source"),
        ("config.toml", "generated_caption", "generated"),
        ("voice.wav", "generated_video", "generated"),
    ],
)
def test_unsafe_or_mismatched_artifacts_are_rejected(
    tmp_path, filename, kind, provenance
):
    source = tmp_path / filename
    source.write_bytes(b"do not archive")

    with pytest.raises(media_delivery.MediaArchiveError):
        media_delivery.add_artifact(
            _artifact(source, kind=kind, provenance=provenance),
            _policy(tmp_path / "deliveries"),
        )


def test_archive_rejects_story_path_traversal(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"sample")
    artifact = _artifact(source, story_title="../../")

    with pytest.raises(media_delivery.MediaArchiveError):
        media_delivery.add_artifact(artifact, _policy(tmp_path / "deliveries"))


def test_hash_mismatch_removes_partial_copy_and_does_not_write_manifest(
    tmp_path, monkeypatch
):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"trusted bytes")
    destination = tmp_path / "deliveries"
    original_hash = media_delivery._hash_file

    def mismatch_only_for_copy(path):
        if path.suffix == ".partial":
            return "0" * 64
        return original_hash(path)

    monkeypatch.setattr(media_delivery, "_hash_file", mismatch_only_for_copy)
    with pytest.raises(media_delivery.MediaArchiveError, match="does not match"):
        media_delivery.add_artifact(_artifact(source), _policy(destination))

    assert list(destination.rglob("*.partial")) == []
    assert list(destination.rglob("media-delivery-manifest.json")) == []
    assert source.read_bytes() == b"trusted bytes"


def test_colliding_archive_name_with_wrong_hash_is_never_overwritten(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    policy = _policy(tmp_path / "deliveries")
    original = media_delivery.add_artifact(_artifact(source), policy)
    archive_path = Path(original["archive_path"])
    archive_path.write_bytes(b"unexpected replacement")

    with pytest.raises(media_delivery.MediaArchiveError, match="existing archive"):
        media_delivery.add_artifact(_artifact(source), policy)

    assert archive_path.read_bytes() == b"unexpected replacement"


def test_racing_wrong_hash_target_is_never_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source bytes")
    destination = tmp_path / "deliveries"
    expected_target = destination / "2026-10-15_Garden-Story"
    expected_target.mkdir(parents=True)
    policy = _policy(destination)
    original_link = media_delivery.os.link

    def race_link(source_path, target_path):
        Path(target_path).write_bytes(b"racing content")
        return original_link(source_path, target_path)

    monkeypatch.setattr(media_delivery.os, "link", race_link)
    with pytest.raises(media_delivery.MediaArchiveError, match="existing archive"):
        media_delivery.add_artifact(_artifact(source), policy)

    remaining = list(expected_target.iterdir())
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == b"racing content"


def test_policy_mapping_uses_only_explicit_external_configuration():
    policy = media_delivery.MediaArchivePolicy.from_mapping(
        {
            "enabled": True,
            "destination": "/tmp/story-delivery",
            "timezone": "America/Toronto",
            "archive_on_generation": True,
            "preserve_versions": True,
            "ignored_setting": "not copied",
        }
    )

    assert policy.enabled is True
    assert policy.destination == "/tmp/story-delivery"
    assert policy.timezone == "America/Toronto"
    assert not hasattr(policy, "ignored_setting")
