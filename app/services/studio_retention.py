"""Dry-run media cleanup after verified publishing and exact owner confirmation.

No deletion API is provided: an operator must present the immutable plan and get
the owner's confirmation before using a filesystem tool. Documents, captions,
profiles, code and historical publication evidence are never cleanup candidates.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".wav", ".mp3", ".m4a", ".aac", ".flac"}


def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cleanup_plan(*, release_id, master_sha256, media, allowed_roots, required_platforms, receipts):
    """Fail closed for missing evidence or changed/unsafe files; never unlink.

    Receipts must name this release and master, have a public watch URL and an
    observation time, and report public publication. Historical posts for a
    different edition do not satisfy the gate. An incomplete release stays held.
    """
    if not release_id or not re.fullmatch(r"[0-9a-f]{64}", master_sha256):
        raise ValueError("A release identity and exact master hash are required")
    roots = [Path(root).expanduser().resolve() for root in allowed_roots]
    if not roots:
        raise ValueError("Explicit media roots required")
    required = sorted(set(required_platforms))
    if not required:
        raise ValueError("Explicit publication targets required")
    verified = set()
    for receipt in receipts:
        if (receipt.get("release_id") == release_id
                and receipt.get("master_sha256") == master_sha256
                and receipt.get("status") == "public_verified"
                and receipt.get("public_url", "").startswith("https://")
                and receipt.get("observed_at")):
            verified.add(receipt.get("platform"))
    candidates, issues = [], []
    seen = set()
    for item in media:
        path = Path(item["path"]).expanduser()
        resolved = path.resolve()
        if (not path.is_absolute() or path.is_symlink()
                or not any(resolved.is_relative_to(root) for root in roots)
                or path.suffix.lower() not in MEDIA_EXTENSIONS):
            issues.append({"path": str(path), "issue": "unsafe_or_non_media_path"})
            continue
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        if not path.is_file():
            issues.append({"path": str(path), "issue": "missing"})
            continue
        digest = _sha(path)
        if digest != item.get("sha256"):
            issues.append({"path": str(path), "issue": "hash_mismatch"})
            continue
        candidates.append({"path": str(resolved), "sha256": digest, "bytes": path.stat().st_size})
    missing = sorted(set(required) - verified)
    plan = {
        "release_id": release_id, "master_sha256": master_sha256,
        "required_platforms": required, "missing_publication_receipts": missing,
        "candidates": candidates, "issues": issues,
        "bytes_reclaimable": sum(item["bytes"] for item in candidates),
        "ready_to_ask_owner": bool(candidates) and not missing and not issues,
        "owner_confirmation_required": True, "automatic_deletion_allowed": False,
        "preserve": ["code", "preferences", "scripts", "captions", "rights", "reviews", "publication_receipts", "file_hash_tombstones"],
        "note": "After the owner confirms this exact plan, record deleted paths/hashes as unavailable locally; old archive checks no longer prove file availability.",
    }
    plan["plan_sha256"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def validate_owner_confirmation(plan, confirmation):
    """Check scope binding; callers still need an actual human message."""
    current = {key: value for key, value in plan.items() if key != "plan_sha256"}
    digest = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
    return bool(
        plan.get("ready_to_ask_owner") is True
        and plan.get("plan_sha256") == digest
        and confirmation.get("approved") is True
        and confirmation.get("plan_sha256") == digest
        and str(confirmation.get("owner_message_reference", "")).strip()
    )
