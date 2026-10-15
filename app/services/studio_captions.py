"""Language-bound captions and localized media records for Director Studio.

Caption files are never treated as translations merely because they exist. A
human fluent-review attestation, matching BCP-47 locales, a verified media
duration, and a hash-bound media variant are required before a caption track is
eligible for QA or a platform package.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_TAG = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_TIME = re.compile(r"^(?:(\d{2,}):)?([0-5]?\d):([0-5]?\d)[,.](\d{1,3})$")
_VTT_TIME = re.compile(r"^(?:(\d{2,}):)?([0-5]?\d):([0-5]?\d)\.(\d{1,3})$")
_VTT_SHORT_TIME = re.compile(r"^([0-5]?\d):([0-5]?\d)\.(\d{1,3})$")


def normalize_bcp47(value: Any) -> str:
    """Canonicalize common BCP-47 casing and reject malformed locale tags."""
    tag = str(value or "").strip().replace("_", "-")
    if not _TAG.fullmatch(tag):
        raise ValueError(f"invalid BCP-47 locale: {value!r}")
    parts = tag.split("-")
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            canonical.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            canonical.append(part.upper())
        else:
            canonical.append(part.lower())
    return "-".join(canonical)


def _time_seconds(value: str, *, webvtt: bool = False) -> float:
    raw = value.strip()
    match = (_VTT_TIME if webvtt else _TIME).fullmatch(raw)
    if webvtt and match is None:
        short_match = _VTT_SHORT_TIME.fullmatch(raw)
        if short_match:
            minutes, seconds, millis = short_match.groups()
            return int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000
    if not match:
        raise ValueError(f"invalid caption timestamp: {value!r}")
    hours, minutes, seconds, millis = match.groups()
    return (
        (int(hours or 0) * 3600)
        + (int(minutes) * 60)
        + int(seconds)
        + int(millis.ljust(3, "0")) / 1000
    )


def parse_caption_file(path: str | Path, *, duration_seconds: float) -> dict[str, Any]:
    """Parse SRT or WebVTT cues and reject malformed, empty, or overlong files."""
    caption_path = Path(path).expanduser().resolve()
    if not caption_path.is_file():
        raise FileNotFoundError("caption path must identify an existing file")
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0
    ):
        raise ValueError("captions require a finite positive verified media duration")
    suffix = caption_path.suffix.casefold()
    if suffix not in {".srt", ".vtt"}:
        raise ValueError("caption file must be .srt or .vtt")
    raw = caption_path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\s*\r?\n", raw.strip()) if raw.strip() else []
    if suffix == ".vtt":
        if not blocks or not blocks[0].lstrip().startswith("WEBVTT"):
            raise ValueError("WebVTT file must begin with WEBVTT")
        blocks = blocks[1:]
    cues = []
    previous_start = -1.0
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines()]
        if not lines or (
            suffix == ".vtt" and (lines[0].startswith(("NOTE", "STYLE", "REGION")))
        ):
            continue
        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line), None
        )
        if timing_index is None:
            if suffix == ".vtt" and lines[0].startswith("WEBVTT"):
                continue
            raise ValueError("caption block has no timestamp line")
        timing = lines[timing_index].split("-->", 1)
        if len(timing) != 2:
            raise ValueError("caption timestamp range is malformed")
        start_raw = timing[0].strip().split()[0]
        end_raw = timing[1].strip().split()[0]
        start = _time_seconds(start_raw, webvtt=suffix == ".vtt")
        end = _time_seconds(end_raw, webvtt=suffix == ".vtt")
        text = " ".join(
            line.strip() for line in lines[timing_index + 1 :] if line.strip()
        )
        text = re.sub(r"<[^>]*>|\{[^}]*\}", "", text).strip()
        if end <= start or start < previous_start:
            raise ValueError("caption cues need positive, chronological timestamps")
        if not text:
            raise ValueError("caption cue text cannot be empty")
        if end > duration_seconds + 0.02:
            raise ValueError(
                f"caption cue ends after verified media duration ({end:.3f}s > {duration_seconds:.3f}s)"
            )
        cues.append({"start_seconds": start, "end_seconds": end, "text": text})
        previous_start = start
    if not cues:
        raise ValueError("caption file must contain at least one non-empty cue")
    return {
        "format": suffix[1:],
        "cue_count": len(cues),
        "duration_seconds": duration_seconds,
        "last_cue_end_seconds": cues[-1]["end_seconds"],
        "cues": cues,
    }


def register_localized_variant(
    store: Any,
    story_id: str,
    *,
    media_path: str | Path,
    caption_path: str | Path,
    variant_id: str,
    audio_locale: str,
    caption_locale: str,
    fluent_reviewer: str,
    voice_record: dict[str, Any],
    burn_in_reviewed: bool = False,
    burn_in_reviewer: str = "",
) -> dict[str, Any]:
    """Record separate media, voice, and fluent-reviewed caption artifacts."""
    from app.services.story_studio import (
        _story_profile,
        digest_file,
        sample_decode_video,
        video_duration_seconds,
    )

    story = store.story(story_id)
    story_locale = normalize_bcp47(
        story["request"].get("audience", {}).get("language", "en")
    )
    audio_tag = normalize_bcp47(audio_locale)
    caption_tag = normalize_bcp47(caption_locale)
    if audio_tag != story_locale or caption_tag != story_locale:
        raise ValueError(
            f"caption, audio, and story target locales must match ({story_locale})"
        )
    reviewer = str(fluent_reviewer or "").strip()
    if not reviewer:
        raise ValueError(
            "caption language requires a named fluent reviewer attestation"
        )
    if not isinstance(burn_in_reviewed, bool):
        raise ValueError("burn_in_reviewed must be an explicit boolean attestation")
    burn_in_reviewed_by = str(burn_in_reviewer or "").strip()
    if burn_in_reviewed and not burn_in_reviewed_by:
        raise ValueError("burn-in review requires a named reviewer")
    media = Path(media_path).expanduser().resolve()
    caption = Path(caption_path).expanduser().resolve()
    if not media.is_file():
        raise FileNotFoundError("localized media path must identify an existing file")
    media_hash = digest_file(media)
    decoded, detail = sample_decode_video(media)
    if not decoded:
        raise ValueError(
            f"localized media failed a real video/audio decode check: {detail}"
        )
    duration = video_duration_seconds(media)
    parsed = parse_caption_file(caption, duration_seconds=duration)
    if not isinstance(voice_record, dict):
        raise ValueError(
            "a separate voice record is required for each localized audio variant"
        )
    voice_locale = normalize_bcp47(voice_record.get("locale", ""))
    voice_reviewer = str(voice_record.get("reviewer", "")).strip()
    voice_status = str(voice_record.get("status", ""))
    if voice_locale != audio_tag:
        raise ValueError("voice record locale must match the localized audio locale")
    if voice_status not in {"reviewed", "not_used"} or not voice_reviewer:
        raise ValueError(
            "voice record needs status reviewed/not_used and a named reviewer"
        )
    variant_id = str(variant_id or "").strip()
    if not variant_id:
        raise ValueError(
            "variant_id is required to keep localized media versions separate"
        )
    media_artifact = store.add_artifact(
        story_id,
        "localized_media",
        path=media,
        provenance={
            "variant_id": variant_id,
            "locale": audio_tag,
            "story_locale": story_locale,
            "audio_locale": audio_tag,
            "reviewed_by": voice_reviewer,
            "source": "manual_import",
        },
    )
    voice_audio_artifact = None
    voice_audio_path = voice_record.get("audio_path")
    if voice_audio_path:
        audio_path = Path(voice_audio_path).expanduser().resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(
                "voice audio_path must identify an existing local audio file"
            )
        voice_audio_artifact = store.add_artifact(
            story_id,
            "voice_audio",
            path=audio_path,
            provenance={
                "source": "manual_import",
                "variant_id": variant_id,
                "locale": audio_tag,
            },
        )
    voice_doc = {
        "schema_version": 1,
        "story_id": story_id,
        "variant_id": variant_id,
        "media_sha256": media_hash,
        "locale": audio_tag,
        "status": voice_status,
        "voice_id": voice_record.get("voice_id"),
        "provider": voice_record.get("provider", "unknown"),
        "reviewer": voice_reviewer,
        "audio_artifact_id": voice_audio_artifact["artifact_id"]
        if voice_audio_artifact
        else None,
        "audio_sha256": voice_audio_artifact["sha256"]
        if voice_audio_artifact
        else None,
    }
    voice_artifact = store.add_artifact(
        story_id,
        "voice_track",
        document=voice_doc,
        provenance={"manual_voice_review": True, "media_sha256": media_hash},
    )
    caption_provenance = {
        "schema_version": 1,
        "story_id": story_id,
        "variant_id": variant_id,
        "story_locale": story_locale,
        "audio_locale": audio_tag,
        "caption_locale": caption_tag,
        "language_review": {"status": "fluent_reviewed", "reviewer": reviewer},
        "media_path": str(media),
        "media_sha256": media_hash,
        "media_duration_seconds": duration,
        "cue_count": parsed["cue_count"],
        "format": parsed["format"],
        "voice_track_artifact_id": voice_artifact["artifact_id"],
        "voice_track_sha256": voice_artifact["sha256"],
    }
    caption_artifact = store.add_artifact(
        story_id, "caption_track", path=caption, provenance=caption_provenance
    )
    profile = _story_profile(story["request"])
    caption_policy = profile.get("caption_policy") or {}
    burn_in_required = caption_policy.get("burn_in") is True
    variant_status = (
        "language_and_media_reviewed"
        if not burn_in_required or burn_in_reviewed
        else "awaiting_burn_in_review"
    )
    variant = {
        "schema_version": 1,
        "story_id": story_id,
        "variant_id": variant_id,
        "story_locale": story_locale,
        "audio_locale": audio_tag,
        "media_path": str(media),
        "media_sha256": media_hash,
        "media_artifact_id": media_artifact["artifact_id"],
        "media_duration_seconds": duration,
        "caption_path": str(caption),
        "caption_sha256": caption_artifact["sha256"],
        "caption_artifact_id": caption_artifact["artifact_id"],
        "caption_locale": caption_tag,
        "caption_cue_count": parsed["cue_count"],
        "language_review": {"status": "fluent_reviewed", "reviewer": reviewer},
        "burn_in_review": {
            "required": burn_in_required,
            "reviewed": burn_in_reviewed,
            "reviewer": burn_in_reviewed_by or None,
        },
        "voice_track_artifact_id": voice_artifact["artifact_id"],
        "voice_track_sha256": voice_artifact["sha256"],
        "status": variant_status,
    }
    variant_artifact = store.add_artifact(
        story_id,
        "localized_variant",
        document=variant,
        provenance={
            "media_sha256": media_hash,
            "caption_sha256": caption_artifact["sha256"],
            "voice_track_sha256": voice_artifact["sha256"],
            "media_artifact_id": media_artifact["artifact_id"],
        },
    )
    return {
        "variant": variant,
        "variant_artifact": variant_artifact,
        "media_artifact": media_artifact,
        "caption_artifact": caption_artifact,
        "voice_artifact": voice_artifact,
        "caption_parse": parsed,
    }


def find_localized_variant(
    store: Any, story_id: str, media_path: str | Path
) -> dict[str, Any] | None:
    """Return a current variant only if all three files/hashes and locale claims validate."""
    from app.services.story_studio import (
        _archive_copy_verified,
        _story_profile,
        digest_file,
        video_duration_seconds,
    )

    media = Path(media_path).expanduser().resolve()
    if not media.is_file():
        return None
    media_hash = digest_file(media)
    story = store.story(story_id)
    try:
        target_locale = normalize_bcp47(
            story["request"].get("audience", {}).get("language", "en")
        )
    except ValueError:
        return None
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT document_json FROM artifacts WHERE story_id=? AND kind='localized_variant' ORDER BY created_at DESC",
            (story_id,),
        ).fetchall()
    for row in rows:
        variant = json.loads(row["document_json"] or "{}")
        if (
            variant.get("media_sha256") != media_hash
            or variant.get("status") != "language_and_media_reviewed"
        ):
            continue
        try:
            locales = [
                normalize_bcp47(variant.get(key))
                for key in ("story_locale", "audio_locale", "caption_locale")
            ]
            voice_ref = variant.get("voice_track_artifact_id")
            with store.connect() as conn:
                voice_row = conn.execute(
                    "SELECT sha256,document_json FROM artifacts WHERE artifact_id=? AND story_id=? AND kind='voice_track'",
                    (voice_ref, story_id),
                ).fetchone()
                caption_row = conn.execute(
                    "SELECT path,sha256,provenance_json FROM artifacts WHERE artifact_id=? AND story_id=? AND kind='caption_track'",
                    (variant.get("caption_artifact_id"), story_id),
                ).fetchone()
                media_row = conn.execute(
                    "SELECT path,sha256,provenance_json FROM artifacts WHERE artifact_id=? AND story_id=? AND kind='localized_media'",
                    (variant.get("media_artifact_id"), story_id),
                ).fetchone()
            voice = json.loads(voice_row["document_json"] or "{}") if voice_row else {}
            caption_provenance = (
                json.loads(caption_row["provenance_json"] or "{}")
                if caption_row
                else {}
            )
            media_provenance = (
                json.loads(media_row["provenance_json"] or "{}") if media_row else {}
            )
            caption_path = Path(variant.get("caption_path", ""))
            if not caption_path.is_file() or digest_file(caption_path) != variant.get(
                "caption_sha256"
            ):
                continue
            if (
                digest_file(media) != variant.get("media_sha256")
                or locales != [target_locale] * 3
            ):
                continue
            if (
                not voice_row
                or voice_row["sha256"] != variant.get("voice_track_sha256")
                or voice.get("media_sha256") != media_hash
                or normalize_bcp47(voice.get("locale")) != target_locale
                or voice.get("status") not in {"reviewed", "not_used"}
                or not voice.get("reviewer")
            ):
                continue
            if voice.get("audio_artifact_id"):
                with store.connect() as conn:
                    audio_row = conn.execute(
                        "SELECT path,sha256,provenance_json FROM artifacts WHERE artifact_id=? AND story_id=? AND kind='voice_audio'",
                        (voice["audio_artifact_id"], story_id),
                    ).fetchone()
                if (
                    not audio_row
                    or audio_row["sha256"] != voice.get("audio_sha256")
                    or not Path(audio_row["path"]).is_file()
                    or digest_file(audio_row["path"]) != audio_row["sha256"]
                ):
                    continue
                audio_provenance = json.loads(audio_row["provenance_json"] or "{}")
                if audio_provenance.get("locale") != target_locale:
                    continue
                delivery = _story_profile(story["request"]).get("media_delivery") or {}
                if (
                    delivery.get("enabled") is True
                    and delivery.get("archive_on_generation", True)
                    and not _archive_copy_verified(
                        audio_provenance.get("delivery_archive"), audio_row["sha256"]
                    )
                ):
                    continue
            artifact_locales = (
                [
                    normalize_bcp47(caption_provenance.get(key))
                    for key in ("story_locale", "audio_locale", "caption_locale")
                ]
                if caption_provenance
                else []
            )
            if (
                not caption_row
                or caption_row["path"] != str(caption_path.resolve())
                or caption_row["sha256"] != variant.get("caption_sha256")
                or caption_provenance.get("media_sha256") != media_hash
                or artifact_locales != [target_locale] * 3
                or caption_provenance.get("language_review", {}).get("status")
                != "fluent_reviewed"
                or not caption_provenance.get("language_review", {}).get("reviewer")
            ):
                continue
            if (
                not media_row
                or Path(media_row["path"]).resolve() != media
                or media_row["sha256"] != media_hash
                or normalize_bcp47(media_provenance.get("audio_locale"))
                != target_locale
            ):
                continue
            parsed = parse_caption_file(
                caption_path, duration_seconds=video_duration_seconds(media)
            )
            if parsed["cue_count"] != variant.get(
                "caption_cue_count"
            ) or not variant.get("language_review", {}).get("reviewer"):
                continue
            delivery = _story_profile(story["request"]).get("media_delivery") or {}
            if delivery.get("enabled") is True and delivery.get(
                "archive_on_generation", True
            ):
                if not _archive_copy_verified(
                    caption_provenance.get("delivery_archive"),
                    variant.get("caption_sha256"),
                ) or not _archive_copy_verified(
                    media_provenance.get("delivery_archive"), media_hash
                ):
                    continue
            caption_policy = (
                _story_profile(story["request"]).get("caption_policy") or {}
            )
            burn_in = variant.get("burn_in_review", {})
            if caption_policy.get("burn_in") is True and (
                burn_in.get("required") is not True
                or burn_in.get("reviewed") is not True
                or not burn_in.get("reviewer")
            ):
                continue
        except (ValueError, TypeError, OSError):
            continue
        return variant
    return None
