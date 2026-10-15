#!/usr/bin/env python3
"""List generic source paths that may merit a human-reviewed upstream PR.

This tool prints paths only. It never exports file contents or prepares a push.
"""

from __future__ import annotations

import argparse
import json
import subprocess


FORBIDDEN_PARTS = (
    ".env",
    "config.toml",
    "episode",
    "prompt",
    "character",
    "story",
    "private",
    "account",
    "billing",
    "credential",
    "oauth",
    "token",
    "secret",
    "media",
    "outputs/",
    "storage/",
    "assets/",
)
ALLOWED_PREFIXES = ("app/", "test/", "tests/", ".github/workflows/")
ALLOWED_ROOT_FILES = {"pyproject.toml", "uv.lock", "requirements.txt"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", help="Reviewed upstream base commit")
    parser.add_argument("head", help="Candidate commit")
    args = parser.parse_args()
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", f"{args.base}...{args.head}"],
        text=True,
    ).splitlines()

    candidates = []
    excluded_count = 0
    for path in changed:
        normalized = path.replace("\\", "/").lower()
        allowed = normalized in ALLOWED_ROOT_FILES or normalized.startswith(ALLOWED_PREFIXES)
        sensitive = any(part in normalized for part in FORBIDDEN_PARTS)
        if allowed and not sensitive:
            candidates.append(path)
        else:
            excluded_count += 1

    print(json.dumps({"candidate_paths": sorted(candidates), "excluded_path_count": excluded_count}, indent=2))
    if excluded_count:
        print("Excluded paths are intentionally not listed. Inspect them locally before any contribution.")
    print("This list is only a starting point. Review content and licensing; no export or push was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
