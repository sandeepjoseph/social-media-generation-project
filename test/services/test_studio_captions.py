import json

import pytest

from app.services.story_studio import StudioStore
from app.services.studio_captions import (
    find_localized_variant,
    normalize_bcp47,
    parse_caption_file,
    register_localized_variant,
)


def _make_av(path):
    import imageio_ffmpeg

    executable = imageio_ffmpeg.get_ffmpeg_exe()
    import subprocess

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


def _story(store, language="en"):
    return store.create_story(
        {
            "title": "Caption contract",
            "premise": "A small story.",
            "audience": {"language": language},
        }
    )["story_id"]


def test_bcp47_normalization_and_caption_timestamps(tmp_path):
    assert normalize_bcp47("EN-us") == "en-US"
    assert normalize_bcp47("ml") == "ml"
    with pytest.raises(ValueError, match="invalid BCP-47"):
        normalize_bcp47("Malayalam")
    captions = tmp_path / "valid.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:00,700\nHello.\n\n2\n00:00:00,700 --> 00:00:01,000\nGoodbye.\n",
        encoding="utf-8",
    )
    parsed = parse_caption_file(captions, duration_seconds=1.0)
    assert parsed["cue_count"] == 2
    assert parsed["last_cue_end_seconds"] == 1.0


@pytest.mark.parametrize(
    "contents,match",
    [
        ("", "at least one non-empty cue"),
        (
            "1\n00:00:00,000 --> 00:00:01,200\nLate cue.\n",
            "after verified media duration",
        ),
        ("1\n00:00:01,000 --> 00:00:00,500\nBackwards.\n", "positive, chronological"),
        ("1\n00:00:00,000 --> 00:00:01,000\n   \n", "cannot be empty"),
    ],
)
def test_caption_parser_rejects_empty_invalid_or_overlong_cues(
    tmp_path, contents, match
):
    captions = tmp_path / "invalid.srt"
    captions.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        parse_caption_file(captions, duration_seconds=1.0)


def test_malayalam_story_cannot_accept_english_captions_or_voice(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store, language="ml")
    media = _make_av(tmp_path / "media.mp4")
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:00,800\nEnglish words.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"locales must match \(ml\)"):
        register_localized_variant(
            store,
            sid,
            media_path=media,
            caption_path=captions,
            variant_id="ml-v1",
            audio_locale="ml",
            caption_locale="en",
            fluent_reviewer="Reviewer",
            voice_record={
                "locale": "ml",
                "status": "reviewed",
                "reviewer": "Voice reviewer",
            },
        )
    with pytest.raises(ValueError, match="voice record locale"):
        register_localized_variant(
            store,
            sid,
            media_path=media,
            caption_path=captions,
            variant_id="ml-v1",
            audio_locale="ml",
            caption_locale="ml",
            fluent_reviewer="Reviewer",
            voice_record={
                "locale": "en",
                "status": "reviewed",
                "reviewer": "Voice reviewer",
            },
        )


def test_localized_variant_binds_separate_voice_caption_and_video_hashes(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)
    media = _make_av(tmp_path / "media.mp4")
    captions = tmp_path / "captions.vtt"
    captions.write_text(
        "WEBVTT\n\n00:00.000 --> 00:00.800\nA reviewed line.\n", encoding="utf-8"
    )
    registered = register_localized_variant(
        store,
        sid,
        media_path=media,
        caption_path=captions,
        variant_id="youtube-long-en-v1",
        audio_locale="EN",
        caption_locale="en",
        fluent_reviewer="Fluent reviewer",
        voice_record={
            "locale": "en",
            "status": "reviewed",
            "voice_id": "narrator-en",
            "provider": "local",
            "reviewer": "Voice reviewer",
        },
        burn_in_reviewed=True,
        burn_in_reviewer="Burn-in reviewer",
    )
    found = find_localized_variant(store, sid, media)
    assert found["caption_sha256"] == registered["caption_artifact"]["sha256"]
    assert found["voice_track_sha256"] == registered["voice_artifact"]["sha256"]
    with store.connect() as conn:
        artifact_kinds = {
            row[0]
            for row in conn.execute(
                "SELECT kind FROM artifacts WHERE story_id=?", (sid,)
            )
        }
    assert {
        "localized_media",
        "voice_track",
        "caption_track",
        "localized_variant",
    } <= artifact_kinds
    captions.write_text(
        "WEBVTT\n\n00:00.000 --> 00:00.800\nChanged text.\n", encoding="utf-8"
    )
    assert find_localized_variant(store, sid, media) is None


def test_required_burn_in_needs_a_named_human_review(tmp_path):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)
    media = _make_av(tmp_path / "media.mp4")
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:00,800\nReviewed line.\n", encoding="utf-8"
    )

    registered = register_localized_variant(
        store,
        sid,
        media_path=media,
        caption_path=captions,
        variant_id="master-en-v1",
        audio_locale="en",
        caption_locale="en",
        fluent_reviewer="Fluent reviewer",
        voice_record={
            "locale": "en",
            "status": "reviewed",
            "reviewer": "Voice reviewer",
        },
    )

    assert registered["variant"]["status"] == "awaiting_burn_in_review"
    assert find_localized_variant(store, sid, media) is None


def test_caption_and_voice_artifacts_archive_under_private_policy_and_revalidate_copies(
    tmp_path,
):
    store = StudioStore(tmp_path / "studio.sqlite3")
    sid = _story(store)
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
    media = _make_av(tmp_path / "media.mp4")
    voice_audio = tmp_path / "voice.wav"
    voice_audio.write_bytes(b"voice audio bytes")
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:00,800\nReviewed line.\n", encoding="utf-8"
    )
    registered = register_localized_variant(
        store,
        sid,
        media_path=media,
        caption_path=captions,
        variant_id="master-en-v1",
        audio_locale="en",
        caption_locale="en",
        fluent_reviewer="Fluent reviewer",
        voice_record={
            "locale": "en",
            "status": "reviewed",
            "voice_id": "narrator-en",
            "provider": "local",
            "reviewer": "Voice reviewer",
            "audio_path": voice_audio,
        },
        burn_in_reviewed=True,
        burn_in_reviewer="Burn-in reviewer",
    )
    found = find_localized_variant(store, sid, media)
    assert found is not None
    for artifact in (registered["media_artifact"], registered["caption_artifact"]):
        archive = artifact["provenance"]["delivery_archive"]
        assert archive["status"] == "archived"
        assert archive["copy_verified"] is True
        assert archive["sha256"] == artifact["sha256"]
    voice = store.latest_artifact(sid, "voice_track")["document"]
    assert voice["audio_artifact_id"]
    with store.connect() as conn:
        audio_provenance = conn.execute(
            "SELECT provenance_json FROM artifacts WHERE artifact_id=?",
            (voice["audio_artifact_id"],),
        ).fetchone()[0]
    assert json.loads(audio_provenance)["delivery_archive"]["status"] == "archived"
