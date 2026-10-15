"""Local, resumable director-led story production workflow.

The service stores user-provided research and creative documents with hashes. It
does not browse, generate media, upload, or publish on its own. Remote work stays
behind explicit MoneyPrinter LLM calls or documented manual handoffs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from app.utils import utils

PHASES = (
    "research",
    "creative",
    "screenplay",
    "storyboard",
    "flow",
    "assembly",
    "quality",
    "packaging",
    "approval",
    "analytics",
)
PHASE_DEPENDENCIES = {
    "research": (),
    "creative": ("research",),
    "screenplay": ("creative",),
    "storyboard": ("screenplay",),
    "flow": ("storyboard",),
    "assembly": ("flow",),
    "quality": ("assembly",),
    "packaging": ("quality",),
    "approval": ("packaging",),
    "analytics": ("approval",),
}
SCHEMA_VERSION = 1


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_decode_video(path: str | Path) -> tuple[bool, str]:
    """Decode a first and final video frame with the bundled MoviePy FFmpeg."""
    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return False, "ffmpeg_unavailable"
    resolved = str(Path(path).expanduser().resolve())
    if not Path(resolved).is_file():
        return False, "video_file_missing"
    for seek_args, stream_args in (
        ([], ["-map", "0:v:0", "-frames:v", "1"]),
        (["-sseof", "-1"], ["-map", "0:v:0", "-frames:v", "1"]),
        ([], ["-map", "0:a:0", "-t", "0.2"]),
    ):
        command = [
            executable,
            "-v",
            "error",
            *seek_args,
            "-i",
            resolved,
            *stream_args,
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "video_decode_failed"
        if result.returncode != 0:
            return False, "video_decode_failed"
    return True, "first_and_final_video_frames_and_audio_decoded"


def video_duration_seconds(path: str | Path) -> float | None:
    """Read the container duration reported by FFmpeg without decoding the film."""
    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [executable, "-hide_banner", "-i", str(Path(path).expanduser().resolve())],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr + result.stdout
    )
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def default_db_path() -> Path:
    return Path(utils.storage_dir("story_studio", create=True)) / "studio.sqlite3"


def snapshot_job_config(
    job_id: str, base_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Read the local allowlisted override file once and bind settings to a job."""
    from app.config import config
    from app.services.cost_router_overrides import apply_new_job_overrides

    source = base_config if base_config is not None else config.app
    path = Path(utils.root_dir()) / "cost-router-overrides.json"
    snapshot = apply_new_job_overrides(dict(source), path)
    snapshot["_cost_router_job_id"] = str(job_id)
    return snapshot


def load_director_profile(
    profile_id: str | None = None, profile_path: str | Path | None = None
) -> dict[str, Any]:
    """Load local creative strategy without copying private content into this repo."""
    repo_root = Path(utils.root_dir()).resolve()
    external_path = profile_path or os.environ.get("STORY_STUDIO_PROFILE_PATH")
    if external_path is None:
        if profile_id not in (None, "generic_public_starter"):
            raise FileNotFoundError(
                f"requested external profile is unavailable: {profile_id}"
            )
        return {
            "profile_id": "generic_public_starter",
            "profile_visibility": "public_generic",
            "profile_sha256": _digest_bytes(b"generic-public-starter-v1"),
            "brand": {
                "name": "Independent story studio",
                "voice": "clear, age-appropriate, evidence-aware",
            },
            "creative_defaults": {
                "target_duration_seconds": 420,
                "research_before_factual_script": True,
            },
            "story_values": ["accuracy", "clarity", "kindness", "respect for audience"],
            "editorial_policy": {
                "unverified_research": "label needs_research",
                "synthetic_media": "human review and applicable disclosure",
            },
            "director_template": {
                "role_briefs": [
                    "researcher",
                    "screenwriter",
                    "director",
                    "editor",
                    "caption_editor",
                    "growth_editor",
                ],
                "scene_contract_required": [
                    "scene_id",
                    "setting",
                    "visual_intent",
                    "speaker",
                    "continuity",
                    "duration_seconds",
                    "prompt",
                ],
            },
            "caption_policy": {
                "required": True,
                "audio_caption_locale_match": True,
                "burn_in": True,
                "sidecars": ["srt", "vtt"],
                "missing_locale_blocks_publication": True,
                "localizations_need_fluent_review": True,
            },
            "media_delivery": {
                "enabled": False,
                "destination": None,
                "timezone": "UTC",
                "archive_on_generation": True,
                "preserve_versions": True,
            },
            "approved_assets": [],
            "external": False,
        }
    profile_file = Path(external_path).expanduser().resolve()
    if profile_file.is_relative_to(repo_root):
        raise ValueError(
            "creative profiles and asset registries must stay outside the public repository"
        )
    profile = json.loads(profile_file.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("external profile must be a JSON object")
    resolved_id = str(profile.get("profile_id", "")).strip()
    if not resolved_id or profile_id not in (None, resolved_id):
        raise ValueError("external profile_id does not match the requested profile")
    template_path = (
        Path(str(profile.get("private_director_template", ""))).expanduser().resolve()
    )
    registry_path = (
        Path(str(profile.get("private_asset_registry", ""))).expanduser().resolve()
    )
    for private_file in (template_path, registry_path):
        if private_file.is_relative_to(repo_root):
            raise ValueError(
                "private template and asset registry must stay outside the public repository"
            )
        if not private_file.is_file():
            raise FileNotFoundError(
                f"external profile dependency is missing: {private_file.name}"
            )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    asset_records = []
    for asset_id, raw in registry.get("assets", {}).items():
        if not isinstance(raw, dict):
            continue
        asset_path = Path(str(raw.get("path", ""))).expanduser().resolve()
        claimed = str(raw.get("sha256", "")).lower()
        if not asset_path.is_file() or digest_file(asset_path) != claimed:
            raise ValueError(
                f"external approved asset failed its hash check: {asset_id}"
            )
        asset_records.append(
            {
                "asset_id": asset_id,
                "path": str(asset_path),
                "sha256": claimed,
                "reuse_policy": raw.get("reuse_policy"),
                "rights_basis": raw.get("rights_basis"),
            }
        )
    combined = _json(
        {
            "profile": profile,
            "template_sha256": digest_file(template_path),
            "registry_sha256": digest_file(registry_path),
            "asset_hashes": [record["sha256"] for record in asset_records],
        }
    )
    if profile_id not in (None, resolved_id):
        raise ValueError("requested private profile identifier does not match")
    return {
        **profile,
        "profile_sha256": _digest_bytes(combined.encode("utf-8")),
        "director_template": template,
        "approved_assets": asset_records,
        "external": True,
        "profile_file_sha256": digest_file(profile_file),
    }


def _profile_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    """Keep only approved creative settings and verified asset references locally."""
    return {
        key: profile.get(key)
        for key in (
            "profile_id",
            "profile_visibility",
            "profile_sha256",
            "brand",
            "creative_defaults",
            "story_values",
            "editorial_policy",
            "packaging_defaults",
            "brand_hashtag",
            "brand_hashtags",
            "director_template",
            "approved_assets",
            "external",
            "media_delivery",
            "caption_policy",
        )
    }


def _prompt_safe_profile_value(value: Any, key: str = "") -> Any:
    """Keep creative strategy while excluding local paths and credential fields."""
    key_norm = key.casefold().replace("-", "_")
    if any(
        term in key_norm
        for term in ("path", "credential", "secret", "api_key", "token")
    ):
        return None
    if isinstance(value, dict):
        return {
            str(k): _prompt_safe_profile_value(v, str(k))
            for k, v in value.items()
            if _prompt_safe_profile_value(v, str(k)) is not None
        }
    if isinstance(value, list):
        return [
            _prompt_safe_profile_value(item)
            for item in value
            if _prompt_safe_profile_value(item) is not None
        ]
    if isinstance(value, str) and (
        value.startswith("/Users/")
        or value.startswith("/home/")
        or re.match(r"^[A-Za-z]:\\", value)
    ):
        return None
    return value


def _story_profile(request: dict[str, Any]) -> dict[str, Any]:
    snapshot = request.get("profile_snapshot")
    if isinstance(snapshot, dict) and snapshot.get("profile_id"):
        return snapshot
    return load_director_profile(request.get("profile_id"))


def _archive_media_path(
    store: Any,
    story_id: str,
    path: str | Path,
    *,
    archive_kind: str,
    artifact_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Archive eligible media using only the story's external private policy."""
    story = store.story(story_id)
    profile = _story_profile(story["request"])
    policy_data = profile.get("media_delivery") or {}
    try:
        from app.services.media_delivery import (
            MediaArchivePolicy,
            MediaArtifact,
            archive_media_artifact,
        )
    except ImportError:
        return {"status": "unavailable", "reason": "media_delivery_service_unavailable"}
    try:
        policy = MediaArchivePolicy.from_mapping(policy_data)
        details = dict(artifact_provenance or {})
        provenance = details.get("source")
        if provenance not in {
            "generated",
            "flow_receipt",
            "reference_import",
            "manual_import",
        }:
            provenance = (
                "generated"
                if archive_kind.startswith("generated_")
                else "manual_import"
            )
        archive_kind = _media_archive_kind(Path(path), archive_kind)
        archived = archive_media_artifact(
            MediaArtifact(
                source_path=Path(path),
                story_title=story["title"],
                kind=archive_kind,
                provenance=provenance,
                locale=details.get("locale"),
                variant_id=details.get("variant_id"),
            ),
            policy,
        )
        archived["configured"] = bool(policy.enabled and policy.destination)
        archived["preserve_versions"] = bool(policy_data.get("preserve_versions", True))
        archived["caller_details"] = details
        return archived
    except Exception as exc:
        return {
            "status": "error",
            "reason": type(exc).__name__,
            "configured": bool(
                policy_data.get("enabled") is True and policy_data.get("destination")
            ),
        }


def _media_archive_kind(path: Path, requested: str) -> str:
    """Translate workflow artifact labels into the archive's strict allowlist."""
    if requested in {"imported_caption", "generated_caption"}:
        return requested
    if requested in {"generated_image", "generated_video", "generated_audio"}:
        return requested
    suffix = path.suffix.casefold()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "reference_image" if requested == "reference_image" else "imported_image"
    if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        return "imported_video"
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}:
        return "imported_audio"
    raise ValueError("file type is not an eligible media-delivery artifact")


def _archive_copy_verified(record: Any, source_sha256: str | None = None) -> bool:
    if (
        not isinstance(record, dict)
        or record.get("status") != "archived"
        or record.get("copy_verified") is not True
    ):
        return False
    archive_path = Path(str(record.get("archive_path", "")))
    if not archive_path.is_file():
        return False
    try:
        archive_sha = digest_file(archive_path)
    except OSError:
        return False
    return archive_sha == record.get("sha256") and (
        source_sha256 is None or archive_sha == source_sha256
    )


class StudioStore:
    """SQLite state repository; writes use short immediate transactions."""

    def __init__(self, db_path: str | Path | None = None):
        self.path = Path(db_path) if db_path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stories (
                    story_id TEXT PRIMARY KEY, title TEXT NOT NULL, request_json TEXT NOT NULL,
                    requested_duration_seconds INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                    profile_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS story_phases (
                    story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    phase TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    input_sha256 TEXT, output_sha256 TEXT, output_json TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(story_id, phase)
                );
                CREATE TABLE IF NOT EXISTS phase_runs (
                    run_id TEXT PRIMARY KEY, story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    phase TEXT NOT NULL, input_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                    started_at REAL NOT NULL, finished_at REAL, error_type TEXT, output_sha256 TEXT
                );
                CREATE INDEX IF NOT EXISTS phase_runs_by_story ON phase_runs(story_id, phase, started_at);
                CREATE TABLE IF NOT EXISTS source_evidence (
                    evidence_id TEXT PRIMARY KEY, story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    source TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'source_script_adaptation', citation TEXT, claim TEXT, rights_status TEXT NOT NULL DEFAULT 'unknown',
                    confidence TEXT NOT NULL DEFAULT 'unreviewed', source_sha256 TEXT, notes TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY, story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, path TEXT, sha256 TEXT NOT NULL, document_json TEXT,
                    provenance_json TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_by_story ON artifacts(story_id, kind, created_at);
                CREATE TABLE IF NOT EXISTS flow_receipts (
                    receipt_id TEXT PRIMARY KEY, story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    shot_id TEXT NOT NULL, prompt_sha256 TEXT NOT NULL, asset_path TEXT NOT NULL,
                    asset_sha256 TEXT NOT NULL, provider TEXT NOT NULL, quote_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL, imported_at REAL NOT NULL,
                    UNIQUE(story_id, shot_id, prompt_sha256, asset_sha256)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY, story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    artifact_sha256 TEXT NOT NULL, package_sha256 TEXT NOT NULL, approved_by TEXT NOT NULL,
                    approved_at REAL NOT NULL, revoked_at REAL
                );
                CREATE TABLE IF NOT EXISTS analytics_imports (
                    import_id TEXT PRIMARY KEY, story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
                    source TEXT NOT NULL, source_sha256 TEXT NOT NULL, imported_at REAL NOT NULL,
                    metrics_json TEXT NOT NULL, cost_json TEXT NOT NULL
                );
                PRAGMA user_version = 1;
            """)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(source_evidence)")
            }
            if "category" not in columns:
                conn.execute(
                    "ALTER TABLE source_evidence ADD COLUMN category TEXT NOT NULL DEFAULT 'source_script_adaptation'"
                )

    def create_story(
        self, request: dict[str, Any], *, story_id: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise TypeError("story request must be a JSON object")
        title = str(request.get("title", "")).strip()
        premise = str(request.get("premise", request.get("story_input", ""))).strip()
        if not title or not premise:
            raise ValueError("request requires a title and premise/story_input")
        profile = load_director_profile(request.get("profile_id"))
        defaults = profile.get("creative_defaults", {})
        audience_defaults = (
            defaults.get("initial_audience", {}) if isinstance(defaults, dict) else {}
        )
        duration = request.get(
            "target_duration_seconds", defaults.get("target_duration_seconds", 420)
        )
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("target_duration_seconds must be a positive number")
        audience = request.get("audience")
        if not isinstance(audience, dict):
            audience = {}
        request = {
            **request,
            "audience": {
                "age_min": audience.get("age_min", audience_defaults.get("age_min", 6)),
                "age_max": audience.get(
                    "age_max", audience_defaults.get("age_max", 12)
                ),
                "language": audience.get(
                    "language", audience_defaults.get("language", "en")
                ),
                "intended_made_for_kids": audience.get(
                    "intended_made_for_kids", audience_defaults.get("made_for_kids")
                ),
                "made_for_kids": None,
                "reviewed": False,
            },
        }
        if request["audience"]["age_min"] > request["audience"]["age_max"]:
            raise ValueError("audience age_min cannot exceed age_max")
        packaging_defaults = profile.get("packaging_defaults", {})
        default_targets = (
            packaging_defaults.get("platform_targets")
            if isinstance(packaging_defaults, dict)
            else None
        )
        request.setdefault(
            "platform_targets",
            default_targets
            or [
                "youtube_long",
                "youtube_short",
                "facebook_reels",
                "instagram_reels",
                "tiktok",
                "dailymotion",
                "rumble",
            ],
        )
        sid = story_id or uuid.uuid4().hex
        request = {
            **request,
            "profile_id": profile["profile_id"],
            "profile_snapshot_sha256": profile["profile_sha256"],
            "profile_snapshot": _profile_snapshot(profile),
        }
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO stories(story_id,title,request_json,requested_duration_seconds,profile_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (
                    sid,
                    title,
                    _json(request),
                    int(duration),
                    request.get("profile_id"),
                    now,
                    now,
                ),
            )
            conn.executemany(
                "INSERT INTO story_phases(story_id,phase,status,created_at,updated_at) VALUES(?,?, 'queued',?,?)",
                [(sid, phase, now, now) for phase in PHASES],
            )
        return self.story(sid)

    def story(self, story_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM stories WHERE story_id=?", (story_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown story: {story_id}")
            phases = conn.execute(
                "SELECT * FROM story_phases WHERE story_id=? ORDER BY rowid",
                (story_id,),
            ).fetchall()
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        result["phases"] = {
            phase["phase"]: {
                **dict(phase),
                "output": json.loads(phase["output_json"])
                if phase["output_json"]
                else None,
            }
            for phase in phases
        }
        return result

    def list_stories(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT story_id FROM stories ORDER BY created_at DESC"
                )
            ]
        return [self.story(sid) for sid in ids]

    def run_phase(
        self,
        story_id: str,
        phase: str,
        inputs: Any,
        worker: Callable[[], Any],
        *,
        external_call_may_have_started: bool = False,
        resolve_manual_handoff: bool = False,
    ) -> dict[str, Any]:
        if phase not in PHASES:
            raise ValueError(f"unsupported phase: {phase}")
        payload = _json(inputs)
        input_hash = _digest_bytes(payload.encode("utf-8"))
        run_id = uuid.uuid4().hex
        now = time.time()
        with self.transaction() as conn:
            story = conn.execute(
                "SELECT story_id FROM stories WHERE story_id=?", (story_id,)
            ).fetchone()
            if story is None:
                raise KeyError(f"unknown story: {story_id}")
            current = conn.execute(
                "SELECT * FROM story_phases WHERE story_id=? AND phase=?",
                (story_id, phase),
            ).fetchone()
            if (
                current["status"] == "complete"
                and current["input_sha256"] == input_hash
            ):
                return {
                    "status": "cached",
                    "phase": phase,
                    "output": json.loads(current["output_json"] or "null"),
                    "output_sha256": current["output_sha256"],
                }
            if current["status"] == "running":
                raise RuntimeError(
                    f"phase {phase} already has an active worker; inspect or recover the run explicitly"
                )
            if current["status"] == "needs_manual" and not resolve_manual_handoff:
                raise RuntimeError(
                    f"phase {phase} is held for human review; explicitly resolve it before retrying"
                )
            for dependency in PHASE_DEPENDENCIES[phase]:
                state = conn.execute(
                    "SELECT status FROM story_phases WHERE story_id=? AND phase=?",
                    (story_id, dependency),
                ).fetchone()[0]
                if state != "complete":
                    raise RuntimeError(f"phase {phase} requires completed {dependency}")
            if current["input_sha256"] and current["input_sha256"] != input_hash:
                self._invalidate_downstream_in_transaction(conn, story_id, phase, now)
            conn.execute(
                "UPDATE story_phases SET status='running',input_sha256=?,output_sha256=NULL,output_json=NULL,updated_at=? WHERE story_id=? AND phase=?",
                (input_hash, now, story_id, phase),
            )
            conn.execute(
                "INSERT INTO phase_runs(run_id,story_id,phase,input_sha256,status,started_at) VALUES(?,?,?,?,?,?)",
                (run_id, story_id, phase, input_hash, "running", now),
            )
        try:
            output = worker()
            serialized = _json(output)
            output_hash = _digest_bytes(serialized.encode("utf-8"))
            finished = time.time()
            with self.transaction() as conn:
                conn.execute(
                    "UPDATE story_phases SET status='complete',output_sha256=?,output_json=?,updated_at=? WHERE story_id=? AND phase=? AND input_sha256=?",
                    (output_hash, serialized, finished, story_id, phase, input_hash),
                )
                conn.execute(
                    "UPDATE phase_runs SET status='complete',finished_at=?,output_sha256=? WHERE run_id=?",
                    (finished, output_hash, run_id),
                )
            return {
                "status": "complete",
                "phase": phase,
                "output": output,
                "output_sha256": output_hash,
            }
        except Exception as exc:
            finished = time.time()
            uncertain = external_call_may_have_started and phase in {
                "creative",
                "screenplay",
                "storyboard",
                "flow",
                "assembly",
            }
            with self.transaction() as conn:
                conn.execute(
                    "UPDATE story_phases SET status=?,updated_at=? WHERE story_id=? AND phase=? AND input_sha256=?",
                    (
                        "needs_manual" if uncertain else "failed",
                        finished,
                        story_id,
                        phase,
                        input_hash,
                    ),
                )
                conn.execute(
                    "UPDATE phase_runs SET status=?,finished_at=?,error_type=? WHERE run_id=?",
                    (
                        "uncertain" if uncertain else "failed",
                        finished,
                        type(exc).__name__,
                        run_id,
                    ),
                )
            raise

    def _invalidate_downstream_in_transaction(
        self, conn: sqlite3.Connection, story_id: str, phase: str, now: float
    ) -> None:
        index = PHASES.index(phase)
        downstream = PHASES[index + 1 :]
        if downstream:
            placeholders = ",".join("?" for _ in downstream)
            conn.execute(
                f"UPDATE story_phases SET status='queued',input_sha256=NULL,output_sha256=NULL,output_json=NULL,updated_at=? WHERE story_id=? AND phase IN ({placeholders})",
                (now, story_id, *downstream),
            )
            conn.execute(
                "UPDATE approvals SET revoked_at=? WHERE story_id=? AND revoked_at IS NULL",
                (now, story_id),
            )

    def invalidate_downstream(self, story_id: str, phase: str) -> None:
        with self.transaction() as conn:
            self._invalidate_downstream_in_transaction(
                conn, story_id, phase, time.time()
            )

    def recover_stale_phase(
        self, story_id: str, phase: str, *, external_call_may_have_started: bool = True
    ) -> str:
        """Explicitly release a crashed run; uncertain external phases remain held for review."""
        if phase not in PHASES:
            raise ValueError(f"unsupported phase: {phase}")
        now = time.time()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT status FROM story_phases WHERE story_id=? AND phase=?",
                (story_id, phase),
            ).fetchone()
            if not row:
                raise KeyError(f"unknown phase {phase} for story {story_id}")
            if row["status"] != "running":
                return row["status"]
            uncertain = external_call_may_have_started and phase in {
                "creative",
                "screenplay",
                "storyboard",
                "flow",
                "assembly",
            }
            status = "needs_manual" if uncertain else "failed"
            conn.execute(
                "UPDATE story_phases SET status=?,updated_at=? WHERE story_id=? AND phase=?",
                (status, now, story_id, phase),
            )
            conn.execute(
                "UPDATE phase_runs SET status=?,finished_at=?,error_type=? WHERE story_id=? AND phase=? AND status='running'",
                (
                    "uncertain" if uncertain else "abandoned",
                    now,
                    "explicit_recovery",
                    story_id,
                    phase,
                ),
            )
            return status

    def resolve_manual_phase(
        self, story_id: str, phase: str, *, verified_no_duplicate_submission: bool
    ) -> str:
        """Allow retry only after a human confirms the prior external action did not submit."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT status FROM story_phases WHERE story_id=? AND phase=?",
                (story_id, phase),
            ).fetchone()
            if not row:
                raise KeyError(f"unknown phase {phase} for story {story_id}")
            if row["status"] != "needs_manual":
                return row["status"]
            if not verified_no_duplicate_submission:
                return "needs_manual"
            conn.execute(
                "UPDATE story_phases SET status='failed',updated_at=? WHERE story_id=? AND phase=?",
                (time.time(), story_id, phase),
            )
            return "failed"

    def wait_for_manual_phase(
        self, story_id: str, phase: str, inputs: Any, instructions: dict[str, Any]
    ) -> None:
        """Persist a human handoff as a resumable state without claiming completion."""
        if phase not in PHASES:
            raise ValueError(f"unsupported phase: {phase}")
        input_hash = _digest_bytes(_json(inputs).encode("utf-8"))
        now = time.time()
        with self.transaction() as conn:
            current = conn.execute(
                "SELECT status,input_sha256 FROM story_phases WHERE story_id=? AND phase=?",
                (story_id, phase),
            ).fetchone()
            if (
                current
                and current["status"] == "complete"
                and current["input_sha256"] == input_hash
            ):
                return
            if current and current["status"] == "running":
                raise RuntimeError(f"phase {phase} already has an active worker")
            for dependency in PHASE_DEPENDENCIES[phase]:
                row = conn.execute(
                    "SELECT status FROM story_phases WHERE story_id=? AND phase=?",
                    (story_id, dependency),
                ).fetchone()
                if not row or row[0] != "complete":
                    raise RuntimeError(f"phase {phase} requires completed {dependency}")
            if (
                current
                and current["input_sha256"]
                and current["input_sha256"] != input_hash
            ):
                self._invalidate_downstream_in_transaction(conn, story_id, phase, now)
            conn.execute(
                "UPDATE story_phases SET status='needs_manual',input_sha256=?,output_sha256=NULL,output_json=?,updated_at=? WHERE story_id=? AND phase=?",
                (input_hash, _json(instructions), now, story_id, phase),
            )

    def phase(self, story_id: str, phase: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM story_phases WHERE story_id=? AND phase=?",
                (story_id, phase),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown phase {phase} for story {story_id}")
        return dict(row)

    def add_evidence(self, story_id: str, evidence: dict[str, Any]) -> str:
        source = str(evidence.get("source", "")).strip()
        if not source:
            raise ValueError("evidence requires source")
        evidence_id = str(evidence.get("evidence_id") or uuid.uuid4().hex)
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO source_evidence
                (evidence_id,story_id,source,category,citation,claim,rights_status,confidence,source_sha256,notes,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    evidence_id,
                    story_id,
                    source,
                    evidence.get("category", "source_script_adaptation"),
                    evidence.get("citation"),
                    evidence.get("claim"),
                    evidence.get("rights_status", "unknown"),
                    evidence.get("confidence", "unreviewed"),
                    evidence.get("source_sha256"),
                    evidence.get("notes"),
                    time.time(),
                ),
            )
        records = self.evidence(story_id)
        self.run_phase(
            story_id,
            "research",
            records,
            lambda: {
                "status": "manual_evidence_imported",
                "evidence_count": len(records),
            },
        )
        return evidence_id

    def evidence(self, story_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM source_evidence WHERE story_id=? ORDER BY created_at",
                    (story_id,),
                )
            ]

    def add_artifact(
        self,
        story_id: str,
        kind: str,
        *,
        document: Any = None,
        path: str | Path | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path:
            resolved = Path(path).expanduser().resolve()
            sha = digest_file(resolved)
            path_text = str(resolved)
        else:
            if document is None:
                raise ValueError("artifact needs a file path or structured document")
            path_text = None
            sha = _digest_bytes(_json(document).encode("utf-8"))
        artifact_provenance = dict(provenance or {})
        if path and kind in {
            "master",
            "localized_media",
            "caption_track",
            "voice_audio",
            "generated_image",
            "generated_video",
            "generated_audio",
        }:
            archive_kind = (
                "imported_caption"
                if kind == "caption_track"
                else "imported_media"
                if kind in {"master", "localized_media"}
                else kind
            )
            archive = _archive_media_path(
                self,
                story_id,
                resolved,
                archive_kind=archive_kind,
                artifact_provenance=artifact_provenance,
            )
            artifact_provenance["delivery_archive"] = archive
        aid = uuid.uuid4().hex
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)",
                (
                    aid,
                    story_id,
                    kind,
                    path_text,
                    sha,
                    _json(document) if document is not None else None,
                    _json(artifact_provenance),
                    time.time(),
                ),
            )
        return {
            "artifact_id": aid,
            "kind": kind,
            "path": path_text,
            "sha256": sha,
            "document": document,
            "provenance": artifact_provenance,
        }

    def latest_artifact(self, story_id: str, kind: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE story_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
                (story_id, kind),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["document"] = (
            json.loads(item["document_json"]) if item["document_json"] else None
        )
        item["provenance"] = json.loads(item.pop("provenance_json"))
        item.pop("document_json")
        return item

    def import_flow_receipt(
        self, story_id: str, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        if receipt.get("provider_account_check_required"):
            self.wait_for_manual_phase(
                story_id,
                "flow",
                receipt,
                {
                    "status": "provider_account_check_required",
                    "automatic_retry": False,
                    "instruction": "Resolve the account check manually in the provider UI before continuing.",
                },
            )
            return {
                "status": "requires_human",
                "automatic_retry": False,
                "provider_account_check_required": True,
            }
        shot_id = str(receipt.get("shot_id", "")).strip()
        prompt_hash = str(receipt.get("prompt_sha256", "")).lower()
        asset = Path(str(receipt.get("asset_path", ""))).expanduser().resolve()
        if not asset.is_file():
            raise FileNotFoundError(
                "Flow receipt asset_path must identify an existing local file"
            )
        actual_hash = digest_file(asset)
        if (
            not shot_id
            or len(prompt_hash) != 64
            or prompt_hash
            != str(receipt.get("expected_prompt_sha256", prompt_hash)).lower()
        ):
            raise ValueError("receipt needs a shot_id and matching prompt_sha256")
        if (
            receipt.get("expected_asset_sha256")
            and actual_hash != str(receipt["expected_asset_sha256"]).lower()
        ):
            raise ValueError("Flow asset hash does not match receipt")
        recipe = self.latest_artifact(story_id, "flow_bundle")
        if not recipe:
            raise RuntimeError("export a Flow bundle before importing receipts")
        current_board = self.latest_artifact(story_id, "storyboard")
        if (
            not current_board
            or current_board["sha256"] != recipe["document"].get("storyboard_sha256")
            or self.phase(story_id, "storyboard")["status"] != "complete"
        ):
            raise ValueError(
                "Flow export is stale; re-export prompts for the current storyboard"
            )
        manifest = recipe["document"]
        if not isinstance(manifest, dict) or manifest.get("story_id") != story_id:
            raise ValueError("exported Flow bundle is not bound to this story")
        if recipe["sha256"] != _digest_bytes(_json(manifest).encode("utf-8")):
            raise ValueError("stored Flow bundle hash is invalid")
        shot = next(
            (
                item
                for item in manifest.get("shots", [])
                if item.get("shot_id") == shot_id
            ),
            None,
        )
        if not shot or shot.get("prompt_sha256") != prompt_hash:
            raise ValueError("receipt prompt does not match the exported shot bundle")
        expected = {
            item["shot_id"]: item["prompt_sha256"] for item in manifest.get("shots", [])
        }
        if len(expected) != len(manifest.get("shots", [])):
            raise ValueError("exported Flow bundle contains duplicate shot IDs")
        delivery_archive = _archive_media_path(
            self,
            story_id,
            asset,
            archive_kind="imported_media",
            artifact_provenance={"source": "flow_receipt", "variant_id": shot_id},
        )
        receipt_record = {
            **receipt,
            "asset_sha256": actual_hash,
            "delivery_archive": delivery_archive,
        }
        rid = str(receipt.get("receipt_id") or uuid.uuid4().hex)
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO flow_receipts VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    rid,
                    story_id,
                    shot_id,
                    prompt_hash,
                    str(asset),
                    actual_hash,
                    str(receipt.get("provider", "manual Flow")),
                    _json(receipt.get("quote", {"status": "unknown"})),
                    _json(receipt_record),
                    time.time(),
                ),
            )
            existing = conn.execute(
                "SELECT receipt_id FROM flow_receipts WHERE story_id=? AND shot_id=? AND prompt_sha256=? AND asset_sha256=?",
                (story_id, shot_id, prompt_hash, actual_hash),
            ).fetchone()
            if existing:
                rid = existing[0]
        receipts = self._flow_receipt_fingerprints(story_id)
        by_shot = {
            row["shot_id"]: row
            for row in receipts
            if row["prompt_sha256"] == expected.get(row["shot_id"])
        }
        complete = set(by_shot) == set(expected)
        if complete:
            self.run_phase(
                story_id,
                "flow",
                receipts,
                lambda: {
                    "status": "all_manual_receipts_imported",
                    "receipt_count": len(by_shot),
                },
                resolve_manual_handoff=True,
            )
        return {
            "receipt_id": rid,
            "shot_id": shot_id,
            "asset_path": str(asset),
            "asset_sha256": actual_hash,
            "delivery_archive": delivery_archive,
            "provider": receipt.get("provider", "manual Flow"),
            "billing": receipt.get("billing", {"status": "unknown"}),
            "idempotent": True,
            "flow_complete": complete,
        }

    def _flow_receipt_fingerprints(self, story_id: str) -> list[dict[str, str]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT r.shot_id,r.prompt_sha256,r.asset_sha256 FROM flow_receipts r
                WHERE r.story_id=? AND r.imported_at=(SELECT MAX(r2.imported_at) FROM flow_receipts r2 WHERE r2.story_id=r.story_id AND r2.shot_id=r.shot_id)
                ORDER BY r.shot_id""",
                    (story_id,),
                )
            ]

    def flow_receipts(self, story_id: str) -> list[dict[str, str]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT r.shot_id,r.prompt_sha256,r.asset_path,r.asset_sha256 FROM flow_receipts r
                WHERE r.story_id=? AND r.imported_at=(SELECT MAX(r2.imported_at) FROM flow_receipts r2 WHERE r2.story_id=r.story_id AND r2.shot_id=r.shot_id)
                ORDER BY r.shot_id""",
                    (story_id,),
                )
            ]


def research_request(story: dict[str, Any]) -> dict[str, Any]:
    req = story["request"]
    profile = _story_profile(req)
    return {
        "status": "needs_research",
        "story_id": story["story_id"],
        "profile_id": profile["profile_id"],
        "profile_snapshot_sha256": profile["profile_sha256"],
        "research_question": req.get("premise", req.get("story_input")),
        "audience": req.get(
            "audience", {"age_min": 6, "age_max": 12, "language": "en"}
        ),
        "fiction_taxonomy": req.get("fiction_taxonomy", "unclassified"),
        "claims_to_verify": req.get("claims_to_verify", []),
        "source_requirements": [
            "Record source title, author/publisher, canonical URL or citation, access date, claim supported, confidence, and rights status."
        ],
        "research_method": "Manual or explicitly configured research adapter; no sources have been fetched by this request card.",
    }


def validate_screenplay(document: dict[str, Any]) -> list[str]:
    issues = []
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        return ["screenplay must be an object with schema_version=1"]
    roles = document.get("roles")
    scenes = document.get("scenes")
    if not isinstance(roles, list) or not roles:
        issues.append("at least one role is required")
    if not isinstance(scenes, list) or not scenes:
        issues.append("at least one scene is required")
    role_ids = {
        r.get("role_id") for r in roles if isinstance(r, dict) and r.get("role_id")
    }
    for index, scene in enumerate(scenes or []):
        if not isinstance(scene, dict):
            issues.append(f"scene {index + 1} must be an object")
            continue
        if (
            not str(scene.get("scene_id", "")).strip()
            or not str(scene.get("setting", "")).strip()
        ):
            issues.append(f"scene {index + 1} needs scene_id and setting")
        for line in scene.get("lines", []):
            if (
                not isinstance(line, dict)
                or line.get("role_id") not in role_ids
                or not str(line.get("text", "")).strip()
            ):
                issues.append(
                    f"scene {index + 1} has a line with an unknown role or empty text"
                )
    return issues


def quality_report(
    store: StudioStore, story_id: str, *, master_path: str | Path | None = None
) -> dict[str, Any]:
    from app.services.studio_captions import find_localized_variant

    issues = []
    evidence = store.evidence(story_id)
    if store.phase(story_id, "flow")["status"] != "complete":
        issues.append("manual_flow_receipts_incomplete")
    if store.phase(story_id, "assembly")["status"] != "complete":
        issues.append("assembled_master_not_imported")
    required_categories = {
        "source_script_adaptation",
        "visual",
        "voice",
        "music_ambience",
    }
    seen_categories = {row.get("category") for row in evidence}
    if not evidence:
        issues.append("needs_research: no source evidence imported")
    for category in sorted(required_categories - seen_categories):
        issues.append(f"rights_review_required: missing rights record for {category}")
    for row in evidence:
        if (
            row["confidence"] in {"unreviewed", "low"}
            and row["rights_status"] != "not_used"
        ):
            issues.append(
                f"needs_research: evidence confidence unresolved for {row['source']}"
            )
        if row["rights_status"] not in {
            "original",
            "licensed",
            "public_domain",
            "cleared",
            "not_used",
        }:
            issues.append(f"rights_review_required: {row['source']}")
    screenplay = store.latest_artifact(story_id, "screenplay")
    if not screenplay or not screenplay["document"]:
        issues.append("screenplay_missing")
    else:
        issues.extend(validate_screenplay(screenplay["document"]))
    storyboard = store.latest_artifact(story_id, "storyboard")
    if not storyboard:
        issues.append("storyboard_missing")
    review = store.latest_artifact(story_id, "quality_review")
    script_sha = (
        _digest_bytes(_screenplay_plain_text(screenplay["document"]).encode("utf-8"))
        if screenplay
        else None
    )
    current_master_sha = (
        digest_file(master_path)
        if master_path and Path(master_path).is_file()
        else None
    )
    measured_duration = (
        video_duration_seconds(master_path) if current_master_sha else None
    )
    if current_master_sha is None:
        issues.append("current_master_file_missing")
    else:
        decoded, decode_detail = sample_decode_video(master_path)
        if not decoded:
            issues.append(f"master_video_decode_failed:{decode_detail}")
        localized = find_localized_variant(store, story_id, master_path)
        if not localized:
            issues.append("master_caption_voice_locale_variant_missing_or_stale")
        profile = _story_profile(store.story(story_id)["request"])
        delivery_policy = profile.get("media_delivery") or {}
        master_artifact = store.latest_artifact(story_id, "master")
        archive = (
            (master_artifact or {}).get("provenance", {}).get("delivery_archive", {})
        )
        if (
            delivery_policy.get("enabled") is True
            and delivery_policy.get("archive_on_generation", True)
            and not _archive_copy_verified(archive, current_master_sha)
        ):
            issues.append("master_media_delivery_archive_unverified")
    if not review:
        issues.append("human_media_qa_not_imported")
    else:
        review_doc = review["document"] or {}
        if (
            review_doc.get("status") != "passed"
            or review_doc.get("story_id") != story_id
            or review_doc.get("script_sha256") != script_sha
            or review_doc.get("master_sha256") != current_master_sha
        ):
            issues.append("human_media_qa_stale_or_unbound")
        if not all(
            review_doc.get(key) is True
            for key in (
                "technical_decode_pass",
                "visual_review_pass",
                "audio_review_pass",
            )
        ):
            issues.append("human_media_qa_checks_incomplete")
        if not str(review_doc.get("reviewer", "")).strip():
            issues.append("human_media_qa_reviewer_missing")
    recipe = store.latest_artifact(story_id, "flow_bundle")
    if recipe:
        expected = {
            item.get("shot_id"): item.get("prompt_sha256")
            for item in (recipe["document"] or {}).get("shots", [])
        }
        actual = {
            row["shot_id"]: row for row in store._flow_receipt_fingerprints(story_id)
        }
        if set(expected) != set(actual) or any(
            actual[key]["prompt_sha256"] != expected[key] for key in expected
        ):
            issues.append("flow_receipts_do_not_match_current_bundle")
        for row in store.flow_receipts(story_id):
            if (
                not Path(row["asset_path"]).is_file()
                or digest_file(row["asset_path"]) != row["asset_sha256"]
            ):
                issues.append("flow_receipt_asset_changed_or_missing")
                break
            decoded, _ = sample_decode_video(row["asset_path"])
            if not decoded:
                issues.append("flow_receipt_media_decode_failed")
                break
        profile = _story_profile(store.story(story_id)["request"])
        delivery_policy = profile.get("media_delivery") or {}
        if delivery_policy.get("enabled") is True and delivery_policy.get(
            "archive_on_generation", True
        ):
            reference_assets = (recipe["document"] or {}).get(
                "approved_reference_assets", []
            )
            for reference in reference_assets:
                if not _archive_copy_verified(
                    reference.get("delivery_archive"), reference.get("sha256")
                ):
                    issues.append("reference_asset_delivery_archive_unverified")
                    break
            with store.connect() as conn:
                raw_receipts = conn.execute(
                    "SELECT receipt_json FROM flow_receipts WHERE story_id=?",
                    (story_id,),
                ).fetchall()
            for raw in raw_receipts:
                receipt = json.loads(raw[0] or "{}")
                if not _archive_copy_verified(
                    receipt.get("delivery_archive"), receipt.get("asset_sha256")
                ):
                    issues.append("flow_receipt_delivery_archive_unverified")
                    break
    if issues:
        status = "blocked"
    else:
        status = "passed"
    story = store.story(story_id)
    return {
        "schema_version": 1,
        "story_id": story_id,
        "status": status,
        "passed": status == "passed",
        "issues": issues,
        "evidence_count": len(evidence),
        "script_sha256": script_sha,
        "screenplay_sha256": screenplay["sha256"] if screenplay else None,
        "storyboard_sha256": storyboard["sha256"] if storyboard else None,
        "master_sha256": current_master_sha,
        "duration_seconds": measured_duration,
        "duration_verified": measured_duration is not None,
        "audience": story["request"].get("audience", {}),
        "review_required": [
            "age fit",
            "fiction/factual framing",
            "continuity",
            "voice",
            "rights",
            "visual match",
            "AI disclosure where applicable",
        ],
    }


def import_quality_review(
    store: StudioStore,
    story_id: str,
    report: dict[str, Any],
    *,
    master_path: str | Path,
) -> dict[str, Any]:
    """Import explicit reviewer attestations bound to the current script and master."""
    master = Path(master_path).expanduser().resolve()
    if not master.is_file():
        raise FileNotFoundError("QA requires an existing assembled master")
    screenplay = store.latest_artifact(story_id, "screenplay")
    script_sha = (
        _digest_bytes(
            _screenplay_plain_text((screenplay or {}).get("document", {})).encode(
                "utf-8"
            )
        )
        if screenplay
        else None
    )
    required = ("technical_decode_pass", "visual_review_pass", "audio_review_pass")
    if (
        report.get("status") != "passed"
        or report.get("story_id") != story_id
        or report.get("script_sha256") != script_sha
        or report.get("master_sha256") != digest_file(master)
    ):
        raise ValueError(
            "QA report must be passed and bound to the current story, script, and master hashes"
        )
    decoded, _decode_detail = sample_decode_video(master)
    if not decoded:
        raise ValueError(
            "assembled master failed the local first/final frame decode check"
        )
    if not str(report.get("reviewer", "")).strip() or not all(
        report.get(key) is True for key in required
    ):
        raise ValueError(
            "QA report needs a named reviewer and passing decode, visual, and audio checks"
        )
    artifact = store.add_artifact(
        story_id,
        "quality_review",
        document=report,
        provenance={
            "master_sha256": report["master_sha256"],
            "reviewer": report["reviewer"],
        },
    )
    if store.phase(story_id, "assembly")["status"] != "complete":
        raise RuntimeError(
            "import the assembled master through platform packaging before quality approval"
        )
    result = quality_report(store, story_id, master_path=master)
    if not result["passed"]:
        return result
    store.run_phase(
        story_id,
        "quality",
        {
            "qa_review_sha256": artifact["sha256"],
            "script_sha256": script_sha,
            "master_sha256": report["master_sha256"],
        },
        lambda: {
            "status": "passed",
            "reviewer": report["reviewer"],
            "master_sha256": report["master_sha256"],
        },
    )
    return result


def build_platform_package(
    store: StudioStore,
    story_id: str,
    *,
    master_path: str | Path,
    captions_path: str | Path | None = None,
    platforms: tuple[str, ...] | None = None,
    human_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Draft platform assets using the shared generic growth service; no publishing."""
    from app.services.studio_growth import DEFAULT_PLATFORMS, package_story
    from app.services.studio_captions import find_localized_variant, normalize_bcp47

    story = store.story(story_id)
    profile = _story_profile(story["request"])
    packaging_defaults = profile.get("packaging_defaults") or {}
    master = Path(master_path).expanduser().resolve()
    master_artifact = store.add_artifact(
        story_id,
        "master",
        path=master,
        provenance={"manual_review": human_review or {}, "source": "local file"},
    )
    if store.phase(story_id, "flow")["status"] == "complete":
        store.run_phase(
            story_id,
            "assembly",
            {
                "flow_receipts": store._flow_receipt_fingerprints(story_id),
                "master_sha256": master_artifact["sha256"],
            },
            lambda: {
                "status": "local_master_imported",
                "master_sha256": master_artifact["sha256"],
            },
        )
    qa_doc = quality_report(store, story_id, master_path=master)
    store.add_artifact(
        story_id,
        "quality_report",
        document=qa_doc,
        provenance={"master_sha256": qa_doc["master_sha256"]},
    )
    selected_platforms = tuple(
        platforms or story["request"].get("platform_targets") or DEFAULT_PLATFORMS
    )
    platform_assets = {}
    for platform, review in ((human_review or {}).get("platform_assets") or {}).items():
        if not isinstance(review, dict) or not review.get("path"):
            continue
        platform_asset_path = Path(review["path"]).expanduser().resolve()
        if platform_asset_path.is_file():
            decoded, _ = sample_decode_video(platform_asset_path)
            platform_assets[platform] = {
                "path": str(platform_asset_path),
                "sha256": digest_file(platform_asset_path),
                "variant_reviewed": review.get("variant_reviewed") is True and decoded,
                "audience_reviewed": review.get("audience_reviewed") is True,
            }
    master_variant = find_localized_variant(store, story_id, master)
    platform_captions = {}
    target_locale = normalize_bcp47(
        story["request"].get("audience", {}).get("language", "en")
    )
    for platform in selected_platforms:
        media_asset = platform_assets.get(platform, {})
        media_path = media_asset.get("path")
        variant = (
            find_localized_variant(store, story_id, media_path) if media_path else None
        )
        platform_captions[platform] = (
            {
                "path": variant["caption_path"],
                "sha256": variant["caption_sha256"],
                "media_sha256": variant["media_sha256"],
                "locale_match": variant["story_locale"]
                == target_locale
                == variant["audio_locale"]
                == variant["caption_locale"],
                "language_reviewed": variant["language_review"]["status"]
                == "fluent_reviewed"
                and bool(variant["language_review"].get("reviewer")),
            }
            if variant
            else {}
        )
    master_caption_path = (master_variant or {}).get("caption_path")
    master_captions = (
        {
            "path": master_caption_path,
            "sha256": (master_variant or {}).get("caption_sha256"),
        }
        if master_variant
        else None
    )
    if not master_captions and captions_path and Path(captions_path).is_file():
        # A file alone is not language approval. Keep it visible for review,
        # while the independent locale gate remains false.
        master_captions = {
            "path": str(Path(captions_path).expanduser().resolve()),
            "sha256": digest_file(captions_path),
        }
    facts = {
        "story_id": story_id,
        "title": story["title"],
        "script_text": _screenplay_plain_text(
            (store.latest_artifact(story_id, "screenplay") or {}).get("document", {})
        ),
        "audience": {
            **story["request"].get(
                "audience", {"age_min": 6, "age_max": 12, "language": "en"}
            ),
            "made_for_kids": (human_review or {}).get("made_for_kids_reviewed"),
            "reviewed": bool((human_review or {}).get("audience_reviewed", False)),
        },
        "fiction_taxonomy": story["request"].get("fiction_taxonomy", "unclassified"),
        "moral_or_learning_intent": story["request"].get(
            "moral_or_learning_intent", ""
        ),
        "source_evidence": store.evidence(story_id),
        "qa_report": qa_doc,
        "master": {"path": str(master), "sha256": digest_file(master)},
        "captions": master_captions,
        "captions_locale_match": bool(
            master_variant
            and master_variant["story_locale"]
            == target_locale
            == master_variant["audio_locale"]
            == master_variant["caption_locale"]
            and master_variant["language_review"]["status"] == "fluent_reviewed"
        ),
        "platform_captions": platform_captions,
        "thumbnail_brief": story["request"].get(
            "thumbnail_brief",
            "Create an accurate, age-appropriate frame that reflects the story without adding claims.",
        ),
        "topics": story["request"].get("topics", []),
        "brand": profile.get("brand", {}),
        "brand_hashtags": profile.get("brand_hashtags")
        or profile.get("brand_hashtag")
        or packaging_defaults.get("brand_hashtag", []),
        "chapters": story["request"].get("chapters", []),
        "duration_seconds": qa_doc.get("duration_seconds"),
        "duration_verified": qa_doc.get("duration_verified") is True,
        "packaging_defaults": _prompt_safe_profile_value(packaging_defaults),
        "ai_realistic_content": (human_review or {}).get("ai_realistic_content"),
        "platform_targets": list(selected_platforms),
        "platform_assets": platform_assets,
    }
    package = package_story(facts, platforms=selected_platforms, approval=None)
    store.add_artifact(
        story_id,
        "package_facts",
        document={"facts": facts, "platforms": selected_platforms},
        provenance={"hash_bound_to_master": facts["master"]["sha256"]},
    )
    store.add_artifact(
        story_id,
        "platform_package",
        document=package,
        provenance={
            "manual_handoff_only": True,
            "master_sha256": facts["master"]["sha256"],
        },
    )
    if store.phase(story_id, "quality")["status"] == "complete":
        store.run_phase(
            story_id,
            "packaging",
            {
                "master_sha256": facts["master"]["sha256"],
                "package_sha256": package["package_sha256"],
                "platforms": selected_platforms,
            },
            lambda: {
                "status": "manual_platform_package_drafted",
                "package_sha256": package["package_sha256"],
            },
        )
    return package


def _screenplay_plain_text(document: Any) -> str:
    if isinstance(document, str):
        return document
    lines = []
    for scene in document.get("scenes", []) if isinstance(document, dict) else []:
        if not isinstance(scene, dict):
            continue
        for line in scene.get("lines", []):
            if isinstance(line, dict) and line.get("text"):
                lines.append(f"{line.get('role_id', 'role')}: {line['text']}")
    return "\n".join(lines)


def request_screenplay_draft(
    store: StudioStore, story_id: str, *, app_config: dict[str, Any]
) -> dict[str, Any]:
    """Make one explicit routed LLM request for structured creative work."""
    from app.services.llm import _call_generate_response

    story = store.story(story_id)
    evidence = store.evidence(story_id)
    if not evidence:
        raise RuntimeError(
            "import source evidence before requesting a screenplay draft"
        )
    request = story["request"]
    profile = _story_profile(request)
    director_template = profile.get("director_template", {})
    prompt = {
        "task": "Draft an original, age-appropriate screenplay using only the supplied evidence for factual claims.",
        "output_contract": {
            "schema_version": 1,
            "roles": [
                {"role_id": "", "name": "", "function": "", "voice_direction": ""}
            ],
            "scenes": [
                {
                    "scene_id": "",
                    "setting": "",
                    "visual_intent": "",
                    "lines": [{"role_id": "", "text": "", "delivery": ""}],
                }
            ],
        },
        "story": {
            "title": story["title"],
            "premise": request.get("premise", request.get("story_input")),
            "audience": request.get("audience", {}),
            "fiction_taxonomy": request.get("fiction_taxonomy", "unclassified"),
            "moral_or_learning_intent": request.get("moral_or_learning_intent", ""),
            "target_duration_seconds": story["requested_duration_seconds"],
        },
        "evidence": evidence,
        "production_profile": {
            "profile_id": profile["profile_id"],
            "profile_snapshot_sha256": profile["profile_sha256"],
            "profile_visibility": profile.get("profile_visibility", "public_generic"),
            "brand": profile.get("brand", {}),
            "creative_defaults": profile.get("creative_defaults", {}),
            "story_values": profile.get("story_values", []),
            "editorial_policy": profile.get("editorial_policy", {}),
            "role_briefs": director_template.get("role_briefs", []),
            "scene_contract_required": director_template.get(
                "scene_contract_required", []
            ),
            "execution_policy": director_template.get("execution_policy", {}),
            "acceptance_criteria": director_template.get("acceptance_criteria", []),
            "full_director_template": _prompt_safe_profile_value(director_template),
            "approved_asset_references": [
                {
                    key: asset.get(key)
                    for key in ("asset_id", "sha256", "reuse_policy", "rights_basis")
                }
                for asset in profile.get("approved_assets", [])
            ],
        },
        "constraints": [
            "Use no citations or factual claims beyond evidence entries.",
            "Keep fiction and verified history clearly distinguishable.",
            "Return a single JSON object and no markdown.",
            "Include all speaking roles and narrator roles explicitly.",
        ],
    }
    snapshot = snapshot_job_config(story_id, app_config)
    prompt_text = json.dumps(prompt, ensure_ascii=False)
    creative_phase = store.run_phase(
        story_id,
        "creative",
        {
            "prompt_sha256": _digest_bytes(prompt_text.encode("utf-8")),
            "profile_snapshot_sha256": profile["profile_sha256"],
            "evidence_sha256": _digest_bytes(_json(evidence).encode("utf-8")),
        },
        lambda: {
            "raw_response": _call_generate_response(
                prompt_text,
                app_config=snapshot,
                stage="creative",
                task_type="scriptwriting",
            )
        },
        external_call_may_have_started=True,
    )
    raw = creative_phase["output"].get("raw_response", "")
    if not isinstance(raw, str) or raw.startswith("Error: "):
        raise RuntimeError(f"screenplay request failed: {raw}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("model returned invalid screenplay JSON") from exc
    issues = validate_screenplay(document)
    if issues:
        raise ValueError("screenplay failed structure checks: " + "; ".join(issues))
    screenplay_phase = store.run_phase(
        story_id,
        "screenplay",
        {
            "creative_output_sha256": creative_phase["output_sha256"],
            "screenplay": document,
        },
        lambda: store.add_artifact(
            story_id,
            "screenplay",
            document=document,
            provenance={
                "generator": "MoneyPrinter LLM adapter",
                "router_stage": "creative",
                "status": "draft_requires_editor_review",
                "evidence_sha256": _digest_bytes(_json(evidence).encode("utf-8")),
            },
        ),
    )
    return screenplay_phase["output"]


def ingest_screenplay_document(
    store: StudioStore,
    story_id: str,
    document: dict[str, Any],
    *,
    source: str = "manual import",
) -> dict[str, Any]:
    issues = validate_screenplay(document)
    if issues:
        raise ValueError("screenplay failed structure checks: " + "; ".join(issues))
    evidence = store.evidence(story_id)
    if evidence and store.phase(story_id, "research")["status"] != "complete":
        store.run_phase(
            story_id,
            "research",
            evidence,
            lambda: {
                "status": "manual_evidence_imported",
                "evidence_count": len(evidence),
            },
        )
    creative = store.run_phase(
        story_id,
        "creative",
        {
            "screenplay_sha256": _digest_bytes(_json(document).encode("utf-8")),
            "source": source,
        },
        lambda: {
            "status": "manually_authored_creative",
            "editor_review_required": True,
        },
    )
    phase = store.run_phase(
        story_id,
        "screenplay",
        {"creative_output_sha256": creative["output_sha256"], "document": document},
        lambda: store.add_artifact(
            story_id,
            "screenplay",
            document=document,
            provenance={"source": source, "status": "editor_review_required"},
        ),
    )
    return phase["output"]


def ingest_storyboard_document(
    store: StudioStore,
    story_id: str,
    document: dict[str, Any],
    *,
    source: str = "manual import",
) -> dict[str, Any]:
    issues = validate_storyboard(store, story_id, document)
    if issues:
        raise ValueError("storyboard failed structure checks: " + "; ".join(issues))
    screenplay = store.latest_artifact(story_id, "screenplay")
    if not screenplay:
        raise RuntimeError("import a valid screenplay before the storyboard")
    phase = store.run_phase(
        story_id,
        "storyboard",
        {"screenplay_sha256": screenplay["sha256"], "document": document},
        lambda: store.add_artifact(
            story_id,
            "storyboard",
            document=document,
            provenance={"source": source, "status": "director_visual_review_required"},
        ),
    )
    return phase["output"]


def validate_storyboard(store: StudioStore, story_id: str, document: Any) -> list[str]:
    """Validate closed shot, scene, role, and approved-reference identifiers."""
    if (
        not isinstance(document, dict)
        or document.get("schema_version", 1) != 1
        or not isinstance(document.get("shots"), list)
        or not document["shots"]
    ):
        return ["storyboard needs schema_version=1 and a non-empty shots array"]
    screenplay_artifact = store.latest_artifact(story_id, "screenplay")
    if not screenplay_artifact or not isinstance(
        screenplay_artifact.get("document"), dict
    ):
        return ["a validated screenplay is required before storyboarding"]
    screenplay = screenplay_artifact["document"]
    scene_ids = {
        str(scene.get("scene_id"))
        for scene in screenplay.get("scenes", [])
        if isinstance(scene, dict) and scene.get("scene_id")
    }
    role_ids = {
        str(role.get("role_id"))
        for role in screenplay.get("roles", [])
        if isinstance(role, dict) and role.get("role_id")
    }
    profile = _story_profile(store.story(story_id)["request"])
    approved_ids = {
        str(asset.get("asset_id"))
        for asset in profile.get("approved_assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }
    seen_ids: set[str] = set()
    issues = []
    for index, shot in enumerate(document["shots"]):
        label = f"shot {index + 1}"
        if not isinstance(shot, dict):
            issues.append(f"{label} must be an object")
            continue
        shot_id = str(shot.get("shot_id", "")).strip()
        if not shot_id or shot_id in seen_ids:
            issues.append(f"{label} needs a unique shot_id")
        seen_ids.add(shot_id)
        duration = shot.get("duration_seconds")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            issues.append(
                f"{shot_id or label} needs a finite positive duration_seconds"
            )
        if not str(shot.get("prompt", "")).strip():
            issues.append(f"{shot_id or label} needs a prompt")
        scene_id = shot.get("scene_id")
        if scene_id is not None and scene_id not in scene_ids:
            issues.append(
                f"{shot_id or label} references unknown scene_id {scene_id!r}"
            )
        references = shot.get("reference_assets", [])
        if not isinstance(references, list):
            issues.append(f"{shot_id or label} reference_assets must be a list")
        elif any(
            not isinstance(asset_id, str) or asset_id not in approved_ids
            for asset_id in references
        ):
            issues.append(f"{shot_id or label} references an unknown approved asset")
        roles = shot.get("roles", [])
        if not isinstance(roles, list) or any(
            not isinstance(role_id, str) or role_id not in role_ids for role_id in roles
        ):
            issues.append(f"{shot_id or label} references an unknown screenplay role")
    return issues


def request_storyboard_draft(
    store: StudioStore, story_id: str, *, app_config: dict[str, Any]
) -> dict[str, Any]:
    """Draft a structured shot plan with one explicitly requested routed LLM call."""
    from app.services.llm import _call_generate_response

    screenplay_artifact = store.latest_artifact(story_id, "screenplay")
    if (
        not screenplay_artifact
        or store.phase(story_id, "screenplay")["status"] != "complete"
    ):
        raise RuntimeError(
            "import or draft and validate a screenplay before requesting a storyboard"
        )
    story = store.story(story_id)
    profile = _story_profile(story["request"])
    template = profile.get("director_template", {})
    approved_assets = [
        {
            key: asset.get(key)
            for key in ("asset_id", "label", "sha256", "reuse_policy", "rights_basis")
        }
        for asset in profile.get("approved_assets", [])
    ]
    contract = {
        "schema_version": 1,
        "shots": [
            {
                "shot_id": "unique stable id",
                "scene_id": "one screenplay scene_id",
                "duration_seconds": 8,
                "treatment": "visual treatment",
                "camera": "framing and movement",
                "lighting": "lighting plan",
                "weather": "weather or null",
                "props": [],
                "audio": "sound and dialogue handling",
                "transition": "transition to next shot",
                "roles": ["screenplay role_id"],
                "reference_assets": ["approved asset_id only"],
                "capabilities": [],
                "prompt": "complete generation prompt",
            }
        ],
    }
    prompt = {
        "task": "Create a director-led, scene-complete shot plan from the validated screenplay. This is a draft for human visual review; do not claim research or media generation.",
        "output_contract": contract,
        "story": {
            "story_id": story_id,
            "title": story["title"],
            "target_duration_seconds": story["requested_duration_seconds"],
            "audience": story["request"].get("audience", {}),
            "fiction_taxonomy": story["request"].get(
                "fiction_taxonomy", "unclassified"
            ),
        },
        "screenplay": screenplay_artifact["document"],
        "production_profile": {
            "profile_id": profile["profile_id"],
            "profile_snapshot_sha256": profile["profile_sha256"],
            "profile_visibility": profile.get("profile_visibility", "public_generic"),
            "role_briefs": template.get("role_briefs", []),
            "scene_contract_required": template.get("scene_contract_required", []),
            "execution_policy": template.get("execution_policy", {}),
            "full_director_template": _prompt_safe_profile_value(template),
            "approved_reference_assets": approved_assets,
        },
        "constraints": [
            "Return one JSON object and no markdown.",
            "Use only screenplay scene_id values, screenplay role_id values, and listed approved asset_id values.",
            "Give every shot a unique shot_id and finite positive duration_seconds.",
            "Preserve all required treatment, camera, lighting, weather, props, audio, and transition fields.",
            "Do not invent source evidence or claim that Flow has generated any shot.",
            "Narration and voice selection are not automated by this storyboard request; preserve voice intent for later human/provider review.",
        ],
    }
    prompt_text = json.dumps(prompt, ensure_ascii=False)
    snapshot = snapshot_job_config(story_id, app_config)
    inputs = {
        "screenplay_sha256": screenplay_artifact["sha256"],
        "profile_sha256": profile["profile_sha256"],
        "prompt_sha256": _digest_bytes(prompt_text.encode("utf-8")),
    }

    def generate_and_validate():
        raw = _call_generate_response(
            prompt_text,
            app_config=snapshot,
            stage="storyboard",
            task_type="storyboarding",
        )
        store.add_artifact(
            story_id,
            "storyboard_draft_response",
            document={"raw_response": raw},
            provenance={
                "router_stage": "storyboard",
                "status": "unvalidated_model_response",
            },
        )
        if not isinstance(raw, str) or raw.startswith("Error: "):
            raise RuntimeError(f"storyboard request failed: {raw}")
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("model returned invalid storyboard JSON") from exc
        issues = validate_storyboard(store, story_id, document)
        if issues:
            raise ValueError("storyboard failed structure checks: " + "; ".join(issues))
        return store.add_artifact(
            story_id,
            "storyboard",
            document=document,
            provenance={
                "generator": "MoneyPrinter LLM adapter",
                "router_stage": "storyboard",
                "status": "draft_requires_director_visual_review",
                "screenplay_sha256": screenplay_artifact["sha256"],
            },
        )

    phase = store.run_phase(
        story_id,
        "storyboard",
        inputs,
        generate_and_validate,
        external_call_may_have_started=True,
    )
    return phase["output"]


def export_flow_bundle(store: StudioStore, story_id: str) -> dict[str, Any]:
    if store.phase(story_id, "storyboard")["status"] != "complete":
        raise RuntimeError(
            "complete and review the storyboard phase before exporting Flow prompts"
        )
    board = store.latest_artifact(story_id, "storyboard")
    if not board or not isinstance(board["document"], dict):
        raise RuntimeError("a structured storyboard is required")
    shots = board["document"].get("shots", [])
    if not shots:
        raise ValueError("storyboard has no shots")
    bundle_shots = []
    profile = _story_profile(store.story(story_id)["request"])
    for asset in profile.get("approved_assets", []):
        asset_path = Path(str(asset.get("path", "")))
        if not asset_path.is_file() or digest_file(asset_path) != asset.get("sha256"):
            raise ValueError(
                f"approved reference asset changed since this project snapshot: {asset.get('asset_id', 'unknown')}"
            )
    archived_assets = {}
    for asset in profile["approved_assets"]:
        archived_assets[asset["asset_id"]] = {
            **asset,
            "delivery_archive": _archive_media_path(
                store,
                story_id,
                asset["path"],
                archive_kind="reference_image",
                artifact_provenance={
                    "source": "reference_import",
                    "variant_id": asset["asset_id"],
                },
            ),
        }
    assets_by_id = archived_assets
    for index, shot in enumerate(shots):
        prompt = str(shot.get("prompt", "")).strip()
        if not prompt:
            raise ValueError(f"shot {shot.get('shot_id', index + 1)} has no prompt")
        prompt_hash = _digest_bytes(prompt.encode("utf-8"))
        references = shot.get("reference_assets", [])
        if not isinstance(references, list):
            raise ValueError(
                f"shot {shot.get('shot_id', index + 1)} reference_assets must be a list"
            )
        if any(
            not isinstance(asset_id, str) or asset_id not in assets_by_id
            for asset_id in references
        ):
            raise ValueError(
                f"shot {shot.get('shot_id', index + 1)} references an unknown approved asset"
            )
        resolved_references = [assets_by_id[asset_id] for asset_id in references]
        # Keep the whole reviewed shot contract in the handoff. This includes
        # director treatment/camera/lighting/weather/props/audio/transition
        # fields, while stripping local absolute paths and credential-like data.
        exported_shot = _prompt_safe_profile_value(shot)
        bundle_shots.append(
            {
                **exported_shot,
                "shot_id": str(shot.get("shot_id") or f"shot-{index + 1:03d}"),
                "duration_seconds": shot.get("duration_seconds"),
                "prompt": prompt,
                "prompt_sha256": prompt_hash,
                "roles": shot.get("roles", []),
                "reference_assets": resolved_references,
                "capabilities": shot.get("capabilities", []),
                "estimated_cost": {
                    "status": "unknown",
                    "domain": "provider credits or API billing",
                    "amount": None,
                },
                "handoff": "manual_browser_only",
            }
        )
    bundle = {
        "schema_version": 1,
        "story_id": story_id,
        "profile_id": profile["profile_id"],
        "profile_snapshot_sha256": profile["profile_sha256"],
        "profile_visibility": profile.get("profile_visibility", "public_generic"),
        "storyboard_sha256": board["sha256"],
        "status": "manual_generation_required",
        "approved_reference_assets": list(archived_assets.values()),
        "shots": bundle_shots,
        "provider_account_check_required": "hold_without_retry_or_account_switch",
        "receipt_schema": {
            "shot_id": "",
            "prompt_sha256": "",
            "asset_path": "absolute local file path",
            "expected_asset_sha256": "optional claimed SHA-256",
            "provider": "manual Flow",
            "quote": {"status": "unknown"},
            "billing": {"status": "unknown"},
        },
        "limitations": [
            "No supported Flow API or credentials are configured here.",
            "Do not infer a price from a stale quote; enter a current quote in the receipt.",
            "A provider account warning is a human hold, not a retry signal.",
        ],
    }
    store.wait_for_manual_phase(
        story_id,
        "flow",
        {"storyboard_sha256": board["sha256"]},
        {
            "status": "manual_generation_required",
            "shot_count": len(bundle_shots),
            "prompt_hashes": [shot["prompt_sha256"] for shot in bundle_shots],
        },
    )
    store.add_artifact(
        story_id,
        "flow_bundle",
        document=bundle,
        provenance={"manual_browser_only": True, "storyboard_sha256": board["sha256"]},
    )
    return bundle


def approve_package(
    store: StudioStore,
    story_id: str,
    artifact_sha256: str,
    package_sha256: str,
    approved_by: str,
) -> str:
    approved_by = str(approved_by or "").strip()
    if not approved_by:
        raise ValueError("approval requires a named owner or reviewer")
    package = store.latest_artifact(story_id, "platform_package")
    master = store.latest_artifact(story_id, "master")
    expected_package_hash = (
        (package["document"] or {}).get("package_sha256") if package else None
    )
    if (
        not package
        or not master
        or expected_package_hash != package_sha256
        or master["sha256"] != artifact_sha256
    ):
        raise ValueError(
            "approval hashes must match the current package and master artifacts"
        )
    package_document = package["document"] or {}
    if not package_document.get("readiness", {}).get("required_checks_passed"):
        raise RuntimeError(
            "package readiness checks have not passed; resolve review queue first"
        )
    facts_artifact = store.latest_artifact(story_id, "package_facts")
    if (
        not facts_artifact
        or facts_artifact["document"]["facts"]["master"]["sha256"] != artifact_sha256
    ):
        raise ValueError("package facts are stale for the current master")
    facts = facts_artifact["document"]["facts"]
    platform_assets = list((facts.get("platform_assets") or {}).values())
    platform_caption_assets = list((facts.get("platform_captions") or {}).values())
    assets_to_check = (
        platform_assets
        + platform_caption_assets
        + ([facts["captions"]] if facts.get("captions") else [])
    )
    for asset in assets_to_check:
        asset_path = Path(asset.get("path", ""))
        if not asset_path.is_file() or digest_file(asset_path) != asset.get("sha256"):
            raise ValueError("package contains an asset that changed after review")
        if asset in platform_assets and not sample_decode_video(asset_path)[0]:
            raise ValueError(
                "platform variant failed the current local media decode check"
            )
    from app.services.studio_captions import find_localized_variant

    for platform, media_asset in (facts.get("platform_assets") or {}).items():
        current_variant = find_localized_variant(
            store, story_id, media_asset.get("path", "")
        )
        recorded_caption = (facts.get("platform_captions") or {}).get(platform, {})
        if (
            not current_variant
            or current_variant.get("caption_sha256") != recorded_caption.get("sha256")
            or current_variant.get("media_sha256") != media_asset.get("sha256")
        ):
            raise ValueError(
                f"localized caption, voice, or media variant is stale for {platform}"
            )
    current_qa = quality_report(store, story_id, master_path=master["path"])
    if not current_qa["passed"] or current_qa["script_sha256"] != facts_artifact[
        "document"
    ]["facts"].get("qa_report", {}).get("script_sha256"):
        raise ValueError(
            "package QA evidence is stale for the current script or master"
        )
    from app.services.studio_growth import package_story

    approved_package = package_story(
        facts_artifact["document"]["facts"],
        platforms=tuple(facts_artifact["document"]["platforms"]),
        approval={"master_sha256": artifact_sha256, "package_sha256": package_sha256},
    )
    if not approved_package.get("readiness", {}).get("ready_for_manual_handoff"):
        raise RuntimeError("exact package approval could not be verified")
    if store.phase(story_id, "packaging")["status"] != "complete":
        raise RuntimeError("complete platform packaging before approval")
    store.add_artifact(
        story_id,
        "platform_package",
        document=approved_package,
        provenance={
            "manual_handoff_only": True,
            "approved_package_sha256": package_sha256,
            "master_sha256": artifact_sha256,
        },
    )
    aid = uuid.uuid4().hex
    phase = store.run_phase(
        story_id,
        "approval",
        {
            "master_sha256": artifact_sha256,
            "package_sha256": package_sha256,
            "approved_by": approved_by,
        },
        lambda: _record_approval(
            store, story_id, artifact_sha256, package_sha256, approved_by, aid
        ),
    )
    return phase["output"]["approval_id"]


def _record_approval(
    store: StudioStore,
    story_id: str,
    master_sha256: str,
    package_sha256: str,
    approved_by: str,
    approval_id: str,
) -> dict[str, str]:
    with store.transaction() as conn:
        conn.execute(
            "UPDATE approvals SET revoked_at=? WHERE story_id=? AND revoked_at IS NULL",
            (time.time(), story_id),
        )
        conn.execute(
            "INSERT INTO approvals VALUES(?,?,?,?,?,?,NULL)",
            (
                approval_id,
                story_id,
                master_sha256,
                package_sha256,
                approved_by,
                time.time(),
            ),
        )
    return {"status": "approved_for_manual_handoff_only", "approval_id": approval_id}


def import_analytics(
    store: StudioStore,
    story_id: str,
    path: str | Path,
    *,
    source: str,
    metrics: dict[str, Any],
    cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if store.phase(story_id, "approval")["status"] != "complete":
        raise RuntimeError(
            "import analytics only after exact-hash owner approval and manual publication"
        )
    source_path = Path(path).expanduser().resolve()
    source_hash = digest_file(source_path)
    cost_record = cost or {
        "status": "unknown",
        "domains": {
            "api": "unknown",
            "Flow credits": "unknown",
            "rendering": "unknown",
            "TTS": "unknown",
        },
    }
    record_id = uuid.uuid4().hex
    result = store.run_phase(
        story_id,
        "analytics",
        {
            "source_sha256": source_hash,
            "source": source,
            "metrics": metrics,
            "cost": cost_record,
        },
        lambda: _record_analytics(
            store, story_id, source, source_hash, metrics, cost_record, record_id
        ),
    )
    return result["output"]


def _record_analytics(
    store: StudioStore,
    story_id: str,
    source: str,
    source_hash: str,
    metrics: dict[str, Any],
    cost_record: dict[str, Any],
    record_id: str,
) -> dict[str, Any]:
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO analytics_imports VALUES(?,?,?,?,?,?,?)",
            (
                record_id,
                story_id,
                source,
                source_hash,
                time.time(),
                _json(metrics),
                _json(cost_record),
            ),
        )
    duration = metrics.get("accepted_video_duration_seconds")
    amount = cost_record.get("flow_credits", {}).get("amount")
    credits_per_minute = (
        amount / (duration / 60)
        if isinstance(amount, (int, float))
        and not isinstance(amount, bool)
        and isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(duration)
        and duration > 0
        else None
    )
    return {
        "import_id": record_id,
        "source_sha256": source_hash,
        "metrics": metrics,
        "cost": cost_record,
        "credits_per_minute": credits_per_minute,
        "accepted_video_duration_seconds": duration,
        "views": metrics.get("views"),
        "publishing": "not performed by Studio",
    }


def import_legacy_benchmark(
    store: StudioStore, request_path: str | Path
) -> dict[str, Any]:
    """Read a legacy plan as provenance; never alter its source file."""
    path = Path(request_path).expanduser().resolve()
    doc = json.loads(path.read_text(encoding="utf-8"))
    duration = doc.get(
        "duration_seconds",
        doc.get("total_duration_seconds", doc.get("final_duration_seconds")),
    )
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("legacy plan needs a positive duration_seconds field")
    request = {
        "title": doc.get("title", path.stem),
        "premise": "Read-only legacy production benchmark",
        "target_duration_seconds": int(duration),
        "legacy_import": True,
        "source_path": str(path),
        "source_sha256": digest_file(path),
        "duration_policy": "preserve_source_duration",
    }
    story = store.create_story(request)
    store.add_artifact(
        story["story_id"],
        "legacy_benchmark",
        path=path,
        provenance={"read_only_import": True, "duration_seconds": int(duration)},
    )
    return {
        "story_id": story["story_id"],
        "duration_seconds": int(duration),
        "source_path": str(path),
        "source_sha256": request["source_sha256"],
        "source_modified": False,
    }


def six_episode_experiment_plan(
    series_title: str, *, duration_seconds: int = 420
) -> dict[str, Any]:
    """Produce a staging plan only; this never submits generation or publish jobs."""
    experiments = [
        (
            "audience_clarity",
            "Test opening clarity with a human-scored storyboard review.",
        ),
        ("research_depth", "Compare source-evidence coverage and correction rate."),
        (
            "character_continuity",
            "Track character/voice consistency across reviewed shots.",
        ),
        (
            "visual_route",
            "Compare manual Flow quote, capability fit, and accepted-shot rate.",
        ),
        (
            "caption_readability",
            "Compare sampled caption readability and correction count.",
        ),
        (
            "title_thumbnail",
            "Compare two truthful metadata treatments after publication authorization.",
        ),
    ]
    return {
        "schema_version": 1,
        "series_title": series_title,
        "status": "staged_not_generated",
        "default_target_duration_seconds": duration_seconds,
        "episodes": [
            {
                "episode": index,
                "title": f"{series_title} experiment {index}",
                "duration_seconds": duration_seconds,
                "hypothesis": hypothesis,
                "primary_measure": measure,
                "generation_authorized": False,
                "publication_authorized": False,
            }
            for index, (measure, hypothesis) in enumerate(experiments, start=1)
        ],
        "cost_tracking": {
            "api_billing": "separate; actual provider usage if returned, otherwise unknown",
            "flow_credits": "separate manual quote and receipt; unknown until verified",
            "tts": "separate voice/model ledger",
            "rendering": "local compute time; not a provider credit",
        },
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Local Director Studio workflow")
    parser.add_argument(
        "--db", help="SQLite path (defaults to ignored storage/story_studio)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser(
        "create", help="create a resumable story from one JSON request"
    )
    create.add_argument("request_json")
    sub.add_parser("list", help="list stories and phase statuses")
    show = sub.add_parser("show", help="show a story status")
    show.add_argument("story_id")
    research = sub.add_parser(
        "research-request", help="write a manual research request card"
    )
    research.add_argument("story_id")
    research.add_argument("--out", required=True)
    evidence = sub.add_parser(
        "add-evidence", help="import one manually reviewed source-evidence JSON object"
    )
    evidence.add_argument("story_id")
    evidence.add_argument("evidence_json")
    script = sub.add_parser(
        "ingest-screenplay", help="validate and store a structured screenplay"
    )
    script.add_argument("story_id")
    script.add_argument("screenplay_json")
    board = sub.add_parser(
        "ingest-storyboard", help="store a structured storyboard JSON"
    )
    board.add_argument("story_id")
    board.add_argument("storyboard_json")
    variant = sub.add_parser(
        "register-variant",
        help="hash-bind localized media, voice, and fluent-reviewed captions",
    )
    variant.add_argument("story_id")
    variant.add_argument("media_path")
    variant.add_argument("caption_path")
    variant.add_argument("--variant-id", required=True)
    variant.add_argument("--audio-locale", required=True)
    variant.add_argument("--caption-locale", required=True)
    variant.add_argument("--fluent-reviewer", required=True)
    variant.add_argument(
        "--voice-json",
        required=True,
        help="voice record JSON with locale/status/reviewer",
    )
    variant.add_argument(
        "--burn-in-reviewed",
        action="store_true",
        help="human-attest that captions are visible in the media pixels",
    )
    variant.add_argument("--burn-in-reviewer", default="")
    storyboard_draft = sub.add_parser(
        "storyboard-draft", help="explicitly request one routed LLM storyboard draft"
    )
    storyboard_draft.add_argument("story_id")
    flow = sub.add_parser(
        "export-flow", help="export manual prompt bundle, no provider calls"
    )
    flow.add_argument("story_id")
    flow.add_argument("--out", required=True)
    receipt = sub.add_parser(
        "import-flow-receipt", help="hash-validate a manual Flow receipt JSON"
    )
    receipt.add_argument("story_id")
    receipt.add_argument("receipt_json")
    qa = sub.add_parser("qa", help="run local evidence and structure gates")
    qa.add_argument("story_id")
    qa.add_argument("--master")
    qa_import = sub.add_parser(
        "import-qa",
        help="import named reviewer checks bound to current script and master",
    )
    qa_import.add_argument("story_id")
    qa_import.add_argument("review_json")
    qa_import.add_argument("--master", required=True)
    resolve = sub.add_parser(
        "resolve-phase",
        help="release an uncertain phase only after a human confirms no duplicate submission",
    )
    resolve.add_argument("story_id")
    resolve.add_argument("phase", choices=PHASES)
    resolve.add_argument("--verified-no-duplicate-submission", action="store_true")
    legacy = sub.add_parser("import-legacy", help="read a legacy plan as a benchmark")
    legacy.add_argument("request_json")
    package = sub.add_parser(
        "package", help="draft manual platform metadata for verified assets"
    )
    package.add_argument("story_id")
    package.add_argument("--master", required=True)
    package.add_argument("--captions")
    package.add_argument("--platform", action="append", dest="platforms")
    package.add_argument("--audience-reviewed", action="store_true")
    package.add_argument(
        "--review-json",
        help="optional JSON object containing platform_assets and human review attestations",
    )
    package.add_argument("--made-for-kids", choices=("yes", "no"))
    package.add_argument(
        "--ai-review", choices=("reviewed_not_required", "disclosed", "not_applicable")
    )
    approve = sub.add_parser(
        "approve", help="record owner approval against exact master and package SHA-256"
    )
    approve.add_argument("story_id")
    approve.add_argument("--master-sha256", required=True)
    approve.add_argument("--package-sha256", required=True)
    approve.add_argument("--approved-by", required=True)
    analytics = sub.add_parser(
        "import-analytics",
        help="import a local analytics export without account access",
    )
    analytics.add_argument("story_id")
    analytics.add_argument("source_file")
    analytics.add_argument("--source", required=True)
    analytics.add_argument("--metrics-json", required=True)
    analytics.add_argument("--cost-json")
    experiment = sub.add_parser(
        "experiment-plan", help="stage six episode experiments without generation"
    )
    experiment.add_argument("series_title")
    experiment.add_argument("--duration-seconds", type=int, default=420)
    experiment.add_argument("--out", required=True)
    args = parser.parse_args()
    store = StudioStore(args.db)
    if args.command == "create":
        result = store.create_story(
            json.loads(Path(args.request_json).read_text(encoding="utf-8"))
        )
    elif args.command == "list":
        result = [
            {
                "story_id": s["story_id"],
                "title": s["title"],
                "duration_seconds": s["requested_duration_seconds"],
                "phases": {k: v["status"] for k, v in s["phases"].items()},
            }
            for s in store.list_stories()
        ]
    elif args.command == "show":
        result = store.story(args.story_id)
    elif args.command == "research-request":
        result = research_request(store.story(args.story_id))
        Path(args.out).write_text(_json(result) + "\n", encoding="utf-8")
    elif args.command == "add-evidence":
        result = {
            "evidence_id": store.add_evidence(
                args.story_id,
                json.loads(Path(args.evidence_json).read_text(encoding="utf-8")),
            )
        }
    elif args.command == "ingest-screenplay":
        doc = json.loads(Path(args.screenplay_json).read_text(encoding="utf-8"))
        issues = validate_screenplay(doc)
        if issues:
            result = {"status": "blocked", "issues": issues}
        else:
            result = ingest_screenplay_document(
                store,
                args.story_id,
                doc,
                source=str(Path(args.screenplay_json).resolve()),
            )
    elif args.command == "ingest-storyboard":
        doc = json.loads(Path(args.storyboard_json).read_text(encoding="utf-8"))
        result = ingest_storyboard_document(
            store, args.story_id, doc, source=str(Path(args.storyboard_json).resolve())
        )
    elif args.command == "register-variant":
        from app.services.studio_captions import register_localized_variant

        result = register_localized_variant(
            store,
            args.story_id,
            media_path=args.media_path,
            caption_path=args.caption_path,
            variant_id=args.variant_id,
            audio_locale=args.audio_locale,
            caption_locale=args.caption_locale,
            fluent_reviewer=args.fluent_reviewer,
            voice_record=json.loads(Path(args.voice_json).read_text(encoding="utf-8")),
            burn_in_reviewed=args.burn_in_reviewed,
            burn_in_reviewer=args.burn_in_reviewer,
        )
    elif args.command == "storyboard-draft":
        from app.config import config

        result = request_storyboard_draft(
            store, args.story_id, app_config=dict(config.app)
        )
    elif args.command == "export-flow":
        result = export_flow_bundle(store, args.story_id)
        Path(args.out).write_text(_json(result) + "\n", encoding="utf-8")
    elif args.command == "import-flow-receipt":
        result = store.import_flow_receipt(
            args.story_id,
            json.loads(Path(args.receipt_json).read_text(encoding="utf-8")),
        )
    elif args.command == "qa":
        result = quality_report(store, args.story_id, master_path=args.master)
        store.add_artifact(args.story_id, "quality_report", document=result)
    elif args.command == "import-qa":
        result = import_quality_review(
            store,
            args.story_id,
            json.loads(Path(args.review_json).read_text(encoding="utf-8")),
            master_path=args.master,
        )
    elif args.command == "resolve-phase":
        result = {
            "status": store.resolve_manual_phase(
                args.story_id,
                args.phase,
                verified_no_duplicate_submission=args.verified_no_duplicate_submission,
            ),
            "automatic_retry": False,
        }
    elif args.command == "import-legacy":
        result = import_legacy_benchmark(store, args.request_json)
    elif args.command == "package":
        review = (
            json.loads(Path(args.review_json).read_text(encoding="utf-8"))
            if args.review_json
            else {}
        )
        review["audience_reviewed"] = args.audience_reviewed or review.get(
            "audience_reviewed", False
        )
        if args.made_for_kids is not None:
            review["made_for_kids_reviewed"] = args.made_for_kids == "yes"
        if args.ai_review is not None:
            review["ai_realistic_content"] = args.ai_review
        result = build_platform_package(
            store,
            args.story_id,
            master_path=args.master,
            captions_path=args.captions,
            platforms=tuple(args.platforms) if args.platforms else None,
            human_review=review,
        )
    elif args.command == "approve":
        result = {
            "approval_id": approve_package(
                store,
                args.story_id,
                args.master_sha256,
                args.package_sha256,
                args.approved_by,
            ),
            "status": "approved_for_manual_handoff_only",
        }
    elif args.command == "import-analytics":
        result = import_analytics(
            store,
            args.story_id,
            args.source_file,
            source=args.source,
            metrics=json.loads(Path(args.metrics_json).read_text(encoding="utf-8")),
            cost=json.loads(Path(args.cost_json).read_text(encoding="utf-8"))
            if args.cost_json
            else None,
        )
    elif args.command == "experiment-plan":
        result = six_episode_experiment_plan(
            args.series_title, duration_seconds=args.duration_seconds
        )
        Path(args.out).write_text(_json(result) + "\n", encoding="utf-8")
    else:
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return (
        0 if not (isinstance(result, dict) and result.get("status") == "blocked") else 1
    )


if __name__ == "__main__":
    raise SystemExit(_cli())
