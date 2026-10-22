"""Private, portable media inventory and evidence-backed publication ledger.

No network calls, provider jobs, approvals, or publishing side effects. Run beside
an active Studio checkout; existing episode/build snapshots remain untouched.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from urllib.parse import urlsplit

SCHEMA = 1
MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".srt",
    ".vtt",
    ".ass",
    ".json",
    ".txt",
    ".md",
    ".pdf",
    ".csv",
    ".html",
}
STATUSES = {
    "not_started",
    "prepared",
    "submitted",
    "processing",
    "historical_published",
    "owner_reported",
    "published_visibility_unverified",
    "public_verified",
    "private",
    "held",
    "failed",
    "unknown",
}
PLATFORMS = {
    "youtube_long",
    "youtube_short",
    "facebook_reels",
    "instagram_reels",
    "tiktok",
    "dailymotion",
    "rumble",
}
KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
EXCLUDED = {
    "proof",
    "screenshot",
    "prepublish",
    "published",
    "billing",
    "api-key",
    "login",
    "verification",
    "account",
    "payment",
    "secret",
    "credential",
    ".env",
}


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation timestamps require an explicit timezone offset")
    return parsed.astimezone(timezone.utc)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(root):
    """Serialize local writers. A stale lock is explicit, never silently broken."""
    lock = Path(root) / ".writer.lock"
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            time.sleep(0.05)
    else:
        raise RuntimeError(
            "Tracker is locked; finish the other writer or inspect the stale .writer.lock"
        )
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink()


class Tracker:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.catalog_path = self.root / "catalog.json"
        self.events_path = self.root / "events.jsonl"
        self.roots_path = self.root / "roots.local.json"
        self.catalog = json.loads(self.catalog_path.read_text())
        if self.catalog.get("schema_version") != SCHEMA:
            raise ValueError("Unsupported tracker schema; migrate before writing")

    @classmethod
    def create(cls, root, channel_id):
        if not KEY.fullmatch(channel_id):
            raise ValueError("Invalid channel ID")
        root = Path(root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if (root / "catalog.json").exists():
            raise FileExistsError("Existing tracker is never overwritten")
        atomic(
            root / "catalog.json",
            {
                "schema_version": SCHEMA,
                "channel_id": channel_id,
                "created_at": stamp(),
                "releases": {},
                "files": {},
            },
        )
        atomic(root / "roots.local.json", {})
        (root / ".gitignore").write_text("roots.local.json\n.writer.lock\n.*.tmp\n")
        (root / "events.jsonl").touch()
        return cls(root)

    def _reload(self):
        self.catalog = json.loads(self.catalog_path.read_text())

    def bind_root(self, alias, path):
        if not KEY.fullmatch(alias):
            raise ValueError("Invalid root alias")
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(resolved)
        with locked(self.root):
            roots = json.loads(self.roots_path.read_text())
            roots[alias] = str(resolved)
            atomic(self.roots_path, roots)

    def resolve(self, locator):
        roots = json.loads(self.roots_path.read_text())
        raw = locator["relative_path"]
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts or "\\" in raw or not raw:
            raise ValueError(
                "Portable locators cannot be absolute or escape their root"
            )
        base = Path(roots[locator["root"]]).resolve()
        target = (base / Path(*relative.parts)).resolve()
        if not target.is_relative_to(base):
            raise ValueError("Locator symlink escapes its root")
        return target

    def scan(self, alias, *, prefix="", story_id=None):
        """Inventory all actual media bytes, not logins/screenshots; preserve versions."""
        locator = {"root": alias, "relative_path": prefix or "."}
        source = self.resolve(locator)
        if not source.is_dir():
            raise NotADirectoryError(source)
        roots = json.loads(self.roots_path.read_text())
        base = Path(roots[alias]).resolve()
        found = {}
        for path in sorted(source.rglob("*")):
            if (
                not path.is_file()
                or path.is_symlink()
                or path.suffix.lower() not in MEDIA_SUFFIXES
            ):
                continue
            relative = path.relative_to(base).as_posix()
            lower = relative.lower()
            if any(word in lower for word in EXCLUDED) or "/.git/" in "/" + relative:
                continue
            key = hashlib.sha256((alias + ":" + relative).encode()).hexdigest()
            found[key] = {
                "root": alias,
                "relative_path": relative,
                "sha256": digest(path),
                "bytes": path.stat().st_size,
                "story_id": story_id,
                "observed_at": stamp(),
            }
        with locked(self.root):
            self._reload()
            for key, item in found.items():
                previous = self.catalog["files"].get(key)
                if previous and previous["sha256"] != item["sha256"]:
                    history = list(previous.get("previous_bytes", []))
                    history.append(
                        {k: previous[k] for k in ("sha256", "bytes", "observed_at")}
                    )
                    item["previous_bytes"] = history
                elif previous and previous.get("previous_bytes"):
                    item["previous_bytes"] = previous["previous_bytes"]
                self.catalog["files"][key] = item
            atomic(self.catalog_path, self.catalog)
        return len(found)

    def track_file(self, path, *, story_id=None):
        """Track one registered Studio artifact without rescanning the archive."""
        raw = Path(path).expanduser()
        if raw.is_symlink():
            raise ValueError("Artifact tracker does not follow symlinks")
        path = raw.resolve()
        if path.suffix.lower() not in MEDIA_SUFFIXES or any(
            word in path.name.lower() for word in EXCLUDED
        ):
            return {"status": "excluded_non_delivery_file"}
        roots = json.loads(self.roots_path.read_text())
        matches = [
            (alias, Path(root).resolve())
            for alias, root in roots.items()
            if path.is_relative_to(Path(root).resolve())
        ]
        if not matches:
            raise ValueError(
                "Artifact is outside tracker roots; bind its working folder before importing"
            )
        alias, base = max(matches, key=lambda pair: len(pair[1].parts))
        relative = path.relative_to(base).as_posix()
        if any(word in relative.lower() for word in EXCLUDED):
            return {"status": "excluded_non_delivery_file"}
        key = hashlib.sha256((alias + ":" + relative).encode()).hexdigest()
        item = {
            "root": alias,
            "relative_path": relative,
            "sha256": digest(path),
            "bytes": path.stat().st_size,
            "story_id": story_id,
            "observed_at": stamp(),
        }
        with locked(self.root):
            self._reload()
            previous = self.catalog["files"].get(key)
            history = list((previous or {}).get("previous_bytes", []))
            if previous and previous["sha256"] != item["sha256"]:
                history.append(
                    {k: previous[k] for k in ("sha256", "bytes", "observed_at")}
                )
            if history:
                item["previous_bytes"] = history
            self.catalog["files"][key] = item
            atomic(self.catalog_path, self.catalog)
        return {
            "status": "tracked",
            "root": alias,
            "relative_path": relative,
            "sha256": item["sha256"],
        }

    def add_release(self, release):
        """Explicit immutable release identity; review evidence does not transfer."""
        required = (
            "release_id",
            "story_id",
            "title",
            "version",
            "locale",
            "quality",
            "targets",
        )
        if any(not release.get(k) for k in required) or not KEY.fullmatch(
            release["release_id"]
        ):
            raise ValueError(
                "Release needs a stable ID, story, title, version, locale, quality and targets"
            )
        if set(release["targets"]) - PLATFORMS:
            raise ValueError("Unknown platform")
        if release["quality"] not in {
            "accepted_ai_review",
            "legacy_not_current_contract",
            "held",
            "draft",
            "stopped_private",
        }:
            raise ValueError("Explicit quality provenance is required")
        if release.get("master_sha256") and not SHA.fullmatch(release["master_sha256"]):
            raise ValueError("Invalid master SHA256")
        if release.get("master"):
            path = self.resolve(release["master"])
            if not path.is_file() or digest(path) != release.get("master_sha256"):
                raise ValueError("Master locator must resolve to the declared bytes")
        with locked(self.root):
            self._reload()
            existing = self.catalog["releases"].get(release["release_id"])
            if existing and existing != release:
                raise ValueError("Release is immutable; create a distinct version")
            self.catalog["releases"][release["release_id"]] = release
            atomic(self.catalog_path, self.catalog)

    def events(self):
        previous = ""
        result = []
        for line in self.events_path.read_text().splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            payload = {k: v for k, v in event.items() if k != "event_sha256"}
            if (
                event["previous_event_sha256"] != previous
                or hashlib.sha256(canonical(payload)).hexdigest()
                != event["event_sha256"]
            ):
                raise ValueError("Publication ledger integrity failed")
            previous = event["event_sha256"]
            result.append(event)
        return result

    def record(self, event):
        """Append one factual observation. An upload click is never public proof."""
        if (
            event.get("status") not in STATUSES
            or not event.get("event_id")
            or not KEY.fullmatch(event["event_id"])
        ):
            raise ValueError("Event needs a valid idempotency ID and status")
        with locked(self.root):
            self._reload()
            release = self.catalog["releases"].get(event.get("release_id"))
            if not release or event.get("platform") not in release["targets"]:
                raise ValueError("Unknown release/platform target")
            if (
                not event.get("observed_at")
                or not event.get("evidence", {}).get("kind")
                or not event["evidence"].get("note")
            ):
                raise ValueError(
                    "Timestamp and explicit evidence provenance are required"
                )
            instant(event["observed_at"])
            if event.get("master_sha256") and event["master_sha256"] != release.get(
                "master_sha256"
            ):
                raise ValueError("Publication event belongs to different master bytes")
            if event.get("status") == "public_verified":
                if event["evidence"]["kind"] not in {
                    "native_library",
                    "native_public_player",
                    "official_api",
                } or not event["evidence"].get("public_visibility_observed"):
                    raise ValueError(
                        "Public verification requires observed native visibility"
                    )
                legacy_unknown = (
                    release["quality"] == "legacy_not_current_contract"
                    and event["evidence"].get("upload_source_binding")
                    == "unverified_historical_variant"
                )
                if not event.get("url") or (
                    not event.get("master_sha256") and not legacy_unknown
                ):
                    raise ValueError(
                        "Public verification needs a URL and bound upload master, or an explicitly unbound legacy observation"
                    )
            if event.get("url"):
                url = urlsplit(event["url"])
                if (
                    url.scheme != "https"
                    or not url.hostname
                    or url.username
                    or url.password
                ):
                    raise ValueError("Post URL must be HTTPS without credentials")
            history = self.events()
            payload = dict(event)
            payload.pop("event_sha256", None)
            payload.pop("previous_event_sha256", None)
            for old in history:
                if old["event_id"] == payload["event_id"]:
                    if {
                        k: v
                        for k, v in old.items()
                        if k not in {"previous_event_sha256", "event_sha256"}
                    } != payload:
                        raise ValueError(
                            "Idempotency ID already used for different data"
                        )
                    return old
            payload["previous_event_sha256"] = (
                history[-1]["event_sha256"] if history else ""
            )
            payload["event_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
            # Rewrite atomically: readers never see a partial final JSONL record.
            data = "".join(
                json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n"
                for x in [*history, payload]
            )
            fd, name = tempfile.mkstemp(prefix=".events.", dir=self.root)
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(data)
                os.replace(name, self.events_path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            return payload

    def report(self):
        self._reload()
        latest = {}
        for event in self.events():
            key = (event["release_id"], event["platform"])
            # Late imports of old receipts cannot replace a newer observation.
            if key not in latest or instant(event["observed_at"]) >= instant(
                latest[key]["observed_at"]
            ):
                latest[key] = event
        rows = []
        for rid, release in sorted(self.catalog["releases"].items()):
            posts = {
                p: latest.get((rid, p), {"status": "not_started"})
                for p in release["targets"]
            }
            all_verified = bool(posts) and all(
                p["status"] == "public_verified" for p in posts.values()
            )
            all_bound = bool(posts) and all(
                p["status"] == "public_verified"
                and p.get("master_sha256")
                and p.get("master_sha256") == release.get("master_sha256")
                for p in posts.values()
            )
            rows.append(
                {
                    "release_id": rid,
                    "title": release["title"],
                    "quality": release["quality"],
                    "all_targets_public_verified": all_verified,
                    "all_targets_exact_master_bound": all_bound,
                    "platforms": posts,
                }
            )
        return {
            "schema_version": SCHEMA,
            "channel_id": self.catalog["channel_id"],
            "generated_at": stamp(),
            "file_count": len(self.catalog["files"]),
            "releases": rows,
        }

    def verify_files(self):
        self._reload()
        issues = []
        for item in self.catalog["files"].values():
            try:
                path = self.resolve(item)
                if not path.is_file():
                    issues.append(
                        {
                            "file": {k: item[k] for k in ("root", "relative_path")},
                            "issue": "missing",
                        }
                    )
                elif digest(path) != item["sha256"]:
                    issues.append(
                        {
                            "file": {k: item[k] for k in ("root", "relative_path")},
                            "issue": "hash_mismatch",
                        }
                    )
            except (KeyError, ValueError) as error:
                issues.append(
                    {
                        "file": {k: item[k] for k in ("root", "relative_path")},
                        "issue": str(error),
                    }
                )
        self.events()
        return issues


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tracker", required=True, type=Path)
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("--channel-id", required=True)
    bind = commands.add_parser("bind-root")
    bind.add_argument("alias")
    bind.add_argument("path", type=Path)
    scan = commands.add_parser("scan")
    scan.add_argument("alias")
    scan.add_argument("--prefix", default="")
    scan.add_argument("--story-id")
    commands.add_parser("add-release").add_argument("json_file", type=Path)
    commands.add_parser("record").add_argument("json_file", type=Path)
    report = commands.add_parser("report")
    report.add_argument("--output", type=Path)
    commands.add_parser("verify")
    a = p.parse_args()
    if a.command == "init":
        Tracker.create(a.tracker, a.channel_id)
        return
    t = Tracker(a.tracker)
    if a.command == "bind-root":
        t.bind_root(a.alias, a.path)
    elif a.command == "scan":
        print(
            json.dumps(
                {"files_scanned": t.scan(a.alias, prefix=a.prefix, story_id=a.story_id)}
            )
        )
    elif a.command == "add-release":
        t.add_release(json.loads(a.json_file.read_text()))
    elif a.command == "record":
        print(json.dumps(t.record(json.loads(a.json_file.read_text())), indent=2))
    elif a.command == "report":
        result = t.report()
        if a.output:
            atomic(a.output, result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    elif a.command == "verify":
        issues = t.verify_files()
        print(json.dumps({"passed": not issues, "issues": issues}, indent=2))
        raise SystemExit(bool(issues))


if __name__ == "__main__":
    main()
