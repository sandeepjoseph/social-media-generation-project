"""Verified, opt-in archiving of generated or imported story media.

This module deliberately has no destination default. A caller must resolve an
explicit media-delivery policy; without one, the service returns an
``unconfigured`` status and does not create files or claim verification.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_CAPTION_EXTENSIONS = {".srt", ".vtt", ".ass"}
_KIND_EXTENSIONS = {
    "generated_image": _IMAGE_EXTENSIONS,
    "imported_image": _IMAGE_EXTENSIONS,
    "reference_image": _IMAGE_EXTENSIONS,
    "generated_video": _VIDEO_EXTENSIONS,
    "imported_video": _VIDEO_EXTENSIONS,
    "generated_audio": _AUDIO_EXTENSIONS,
    "imported_audio": _AUDIO_EXTENSIONS,
    "generated_caption": _CAPTION_EXTENSIONS,
    "imported_caption": _CAPTION_EXTENSIONS,
}
_PROVENANCE = {"generated", "flow_receipt", "reference_import", "manual_import"}
_SENSITIVE_NAME_PARTS = (
    "screenshot",
    "screen-shot",
    "login",
    "billing",
    "account-info",
    "account_info",
    "account-details",
    "account_details",
    "private-account",
    "private_account",
    "receipt",
    "credential",
    "secret",
    "password",
    "api-key",
    "api_key",
    "apikey",
    "token",
)
_SENSITIVE_PATH_PARTS = {
    ".env",
    ".ssh",
    "config.toml",
    "credentials",
    "secrets",
    "billing",
    "login-screenshots",
    "screenshots",
}
_LOCKS_GUARD = threading.Lock()
_MANIFEST_LOCKS: dict[str, threading.RLock] = {}
_CHUNK_SIZE = 1024 * 1024


class MediaArchiveError(ValueError):
    """Raised when an artifact cannot be safely archived or verified."""


@dataclass(frozen=True, slots=True)
class MediaArchivePolicy:
    """Runtime policy supplied by the user's profile or application settings."""

    destination: str | Path | None = None
    timezone: str = "UTC"
    enabled: bool = False
    archive_on_generation: bool = True
    preserve_versions: bool = True
    manifest_name: str = "media-delivery-manifest.json"

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, TypeError) as exc:
            raise ValueError("timezone must name a valid IANA time zone") from exc
        manifest = Path(self.manifest_name)
        if manifest.name != self.manifest_name or self.manifest_name in {"", ".", ".."}:
            raise ValueError("manifest_name must be a simple filename")
        if manifest.suffix.lower() != ".json":
            raise ValueError("manifest_name must use the .json extension")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> MediaArchivePolicy:
        """Build a policy from an allowlisted profile mapping."""
        if not isinstance(value, Mapping):
            return cls()
        enabled = value.get("enabled", False)
        archive_on_generation = value.get("archive_on_generation", True)
        preserve_versions = value.get("preserve_versions", True)
        for name, setting in (
            ("enabled", enabled),
            ("archive_on_generation", archive_on_generation),
            ("preserve_versions", preserve_versions),
        ):
            if not isinstance(setting, bool):
                raise ValueError(f"{name} must be a boolean")
        destination = value.get("destination")
        if destination is not None and not isinstance(destination, (str, Path)):
            raise ValueError("destination must be a path string or Path")
        timezone = value.get("timezone", "UTC")
        if not isinstance(timezone, str):
            raise ValueError("timezone must be a string")
        return cls(
            destination=destination,
            timezone=timezone,
            enabled=enabled,
            archive_on_generation=archive_on_generation,
            preserve_versions=preserve_versions,
        )


@dataclass(frozen=True, slots=True)
class MediaArtifact:
    """A single allowlisted media or caption artifact, never a directory scan."""

    source_path: str | Path
    story_title: str
    kind: str
    provenance: str
    locale: str | None = None
    variant_id: str | None = None
    created_at: datetime | str | None = None
    date: str | None = None


def _slug(value: str, *, maximum_bytes: int) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    chars: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        allowed = category[0] in {"L", "N", "M"} or char in "._-"
        chars.append(char if allowed else "-")
    normalized_slug = re.sub(r"[-_]{2,}", "-", "".join(chars)).strip("-._")
    clusters: list[str] = []
    join_next = False
    for char in normalized_slug:
        category = unicodedata.category(char)
        if (category[0] == "M" or join_next) and clusters and clusters[-1] != "-":
            clusters[-1] += char
        elif category[0] != "M":
            clusters.append(char)
        join_next = "VIRAMA" in unicodedata.name(char, "")
    bounded: list[str] = []
    byte_count = 0
    for cluster in clusters:
        size = len(cluster.encode("utf-8"))
        if byte_count + size > maximum_bytes:
            break
        bounded.append(cluster)
        byte_count += size
    result = "".join(bounded).rstrip("-._")
    if not result or result in {".", ".."}:
        raise MediaArchiveError(
            "story and variant labels must contain readable characters"
        )
    return result


def _normalized_locale(locale: str | None) -> str | None:
    if locale is None or not str(locale).strip():
        return None
    normalized = str(locale).strip().replace("_", "-").lower()
    if not re.fullmatch(r"[a-z0-9]{2,8}(?:-[a-z0-9]{1,8})*", normalized):
        raise MediaArchiveError("locale must be a language tag such as en or ml")
    if len(normalized) > 24:
        raise MediaArchiveError("locale is too long for a safe media filename")
    return normalized


def _story_date(artifact: MediaArtifact, zone: ZoneInfo) -> tuple[str, str]:
    if artifact.date is not None:
        try:
            parsed = Date.fromisoformat(artifact.date)
        except (TypeError, ValueError) as exc:
            raise MediaArchiveError("date must use YYYY-MM-DD") from exc
        if parsed.isoformat() != artifact.date:
            raise MediaArchiveError("date must use YYYY-MM-DD")
        return parsed.isoformat(), "explicit"

    value = artifact.created_at
    if value is None:
        return datetime.now(zone).date().isoformat(), "policy_clock"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MediaArchiveError("created_at must be an ISO-8601 timestamp") from exc
    if not isinstance(value, datetime):
        raise MediaArchiveError("created_at must be a datetime or ISO-8601 string")
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    return value.astimezone(zone).date().isoformat(), "created_at"


def _is_sensitive_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    if any(
        part in _SENSITIVE_PATH_PARTS or part.startswith(".env.")
        for part in parts
    ):
        return True
    filename = path.name.lower()
    return any(marker in filename for marker in _SENSITIVE_NAME_PARTS)


def _validate_artifact(artifact: MediaArtifact) -> tuple[Path, str | None, str]:
    if artifact.kind not in _KIND_EXTENSIONS:
        raise MediaArchiveError("unsupported media artifact kind")
    if artifact.provenance not in _PROVENANCE:
        raise MediaArchiveError("unsupported media artifact provenance")
    if not isinstance(artifact.story_title, str) or not artifact.story_title.strip():
        raise MediaArchiveError("story_title is required")
    _slug(artifact.story_title, maximum_bytes=180)
    locale = _normalized_locale(artifact.locale)
    variant = ""
    if artifact.variant_id:
        variant = _slug(str(artifact.variant_id), maximum_bytes=24)
    source_input = Path(artifact.source_path).expanduser()
    if source_input.is_symlink():
        raise MediaArchiveError("symbolic-link sources are not accepted")
    if _is_sensitive_path(source_input):
        raise MediaArchiveError("sensitive-looking paths cannot be archived")
    if source_input.suffix.lower() not in _KIND_EXTENSIONS[artifact.kind]:
        raise MediaArchiveError("file extension does not match the artifact kind")
    try:
        source = source_input.resolve(strict=True)
    except OSError as exc:
        raise MediaArchiveError("artifact source does not exist") from exc
    if not source.is_file() or _is_sensitive_path(source):
        raise MediaArchiveError("artifact source is not an eligible regular media file")
    return source, locale, variant


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, temporary: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as incoming:
        before = os.fstat(incoming.fileno())
        with temporary.open("wb") as outgoing:
            for chunk in iter(lambda: incoming.read(_CHUNK_SIZE), b""):
                outgoing.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        after = os.fstat(incoming.fileno())
    if _stat_identity(before) != _stat_identity(after):
        raise MediaArchiveError("source changed while it was being archived")
    source_digest = digest.hexdigest()
    if _hash_file(temporary) != source_digest:
        raise MediaArchiveError("archive copy does not match the source hash")
    return source_digest, total


def _manifest_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _MANIFEST_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _manifest_lock(path: Path) -> Iterator[None]:
    local_lock = _manifest_lock_for(path)
    with local_lock:
        lock_path = path.with_name(path.name + ".lock")
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_manifest(path: Path, document: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_manifest(path: Path, record: dict[str, Any], timezone: str) -> None:
    with _manifest_lock(path):
        if path.exists():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise MediaArchiveError("existing media manifest is unreadable") from exc
            if not isinstance(document, dict) or not isinstance(document.get("files"), list):
                raise MediaArchiveError("existing media manifest has an unsupported shape")
        else:
            document = {"schema_version": 1, "files": []}
        for existing in document["files"]:
            if existing.get("archive_path") == record["archive_path"]:
                if existing.get("sha256") != record["sha256"]:
                    raise MediaArchiveError("manifest path exists with a different content hash")
                return
        document.update(
            {
                "schema_version": 1,
                "timezone": timezone,
                "source_files_preserved": True,
                "files": [*document["files"], record],
                "count": len(document["files"]) + 1,
            }
        )
        document["total_bytes"] = sum(
            int(item.get("bytes", 0)) for item in document["files"]
        )
        _write_manifest(path, document)


def archive_media_artifact(
    artifact: MediaArtifact,
    policy: MediaArchivePolicy,
) -> dict[str, Any]:
    """Archive one artifact atomically and return a verified receipt.

    The source is never moved or deleted. If the policy is not configured, a
    receipt with ``status='unconfigured'`` is returned without reading or
    writing media bytes.
    """
    if not isinstance(policy, MediaArchivePolicy):
        raise TypeError("policy must be a MediaArchivePolicy")
    source, locale, variant = _validate_artifact(artifact)
    base_result: dict[str, Any] = {
        "source_path": str(source),
        "archive_path": None,
        "manifest_path": None,
        "sha256": None,
        "bytes": None,
        "copy_verified": False,
        "story_title": artifact.story_title,
        "kind": artifact.kind,
        "provenance": artifact.provenance,
        "locale": locale,
        "variant_id": variant or None,
    }
    if not policy.enabled or not policy.destination:
        base_result["status"] = "unconfigured" if not policy.destination else "disabled"
        return base_result
    if artifact.provenance == "generated" and not policy.archive_on_generation:
        base_result["status"] = "disabled"
        return base_result

    zone = ZoneInfo(policy.timezone)
    story_date, date_basis = _story_date(artifact, zone)
    story_slug = _slug(artifact.story_title, maximum_bytes=180)
    filename_story_slug = _slug(artifact.story_title, maximum_bytes=80)
    source_slug = _slug(source.stem, maximum_bytes=48)
    destination = Path(policy.destination).expanduser().resolve()
    story_folder_name = f"{story_date}_{story_slug}"
    story_folder = destination / story_folder_name
    story_folder.mkdir(parents=True, exist_ok=True)
    content_hash = _hash_file(source)
    locale_part = f".{locale}" if locale else ""
    variant_part = f"_{variant}" if variant and policy.preserve_versions else ""
    stem = (
        f"{story_date}_{filename_story_slug}_{artifact.kind}{locale_part}"
        f"{variant_part}_{source_slug}_{content_hash[:16]}"
    )
    extension = source.suffix.lower()
    while len((stem + extension).encode("utf-8")) > 240 and source_slug:
        source_slug = source_slug[:-1].rstrip("-._")
        stem = (
            f"{story_date}_{filename_story_slug}_{artifact.kind}{locale_part}"
            f"{variant_part}_{source_slug}_{content_hash[:16]}"
        )
    if len((stem + extension).encode("utf-8")) > 255:
        raise MediaArchiveError("story label is too long for a safe media filename")
    target = story_folder / f"{stem}{extension}"
    temporary: Path | None = None
    try:
        if target.exists():
            if _hash_file(target) != content_hash:
                raise MediaArchiveError("existing archive file differs from the source")
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".partial", dir=story_folder
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            copied_hash, byte_count = _copy_verified(source, temporary)
            if copied_hash != content_hash:
                raise MediaArchiveError("source changed while it was being archived")
            try:
                # A hard link publishes atomically without replacing a file
                # another process may have created after the initial check.
                os.link(temporary, target)
            except FileExistsError:
                if _hash_file(target) != content_hash:
                    raise MediaArchiveError(
                        "existing archive file differs from the source"
                    )
            temporary.unlink(missing_ok=True)
            temporary = None
            if _hash_file(target) != content_hash:
                raise MediaArchiveError("published archive file failed hash verification")
        byte_count = target.stat().st_size
        if _hash_file(source) != content_hash:
            raise MediaArchiveError("source changed after archive verification")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    manifest_path = destination / policy.manifest_name
    record = {
        **base_result,
        "status": "archived",
        "source_path": str(source.resolve()),
        "archive_path": str(target.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "sha256": content_hash,
        "bytes": byte_count,
        "date": story_date,
        "date_basis": date_basis,
        "timezone": policy.timezone,
        "copy_verified": True,
        "source_preserved": True,
    }
    _append_manifest(manifest_path, record, policy.timezone)
    return record


def add_artifact(
    artifact: MediaArtifact,
    policy: MediaArchivePolicy,
) -> dict[str, Any]:
    """Integration-friendly name for :func:`archive_media_artifact`."""
    return archive_media_artifact(artifact, policy)
