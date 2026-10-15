#!/usr/bin/env python3
"""Create a content-free impact summary for upstream commits."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.PIPE).strip()


def classify(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    review_sensitive = (
        normalized.startswith((".github/", ".devcontainer/"))
        or normalized in {"pyproject.toml", "uv.lock", "requirements.txt", "dockerfile"}
        or normalized.startswith(("app/config/", "config", "docs/skill/"))
        or any(word in normalized for word in ("auth", "credential", "token", "secret", "oauth", "billing"))
    )
    if review_sensitive:
        return "security-or-runtime-review"
    if normalized.startswith(("test/", "tests/")):
        return "test-review"
    if normalized.startswith(("docs/", "readme")):
        return "documentation-review"
    return "application-customization-review"


def markdown_path(path: str) -> str:
    safe = path.replace("|", "%7C").replace("`", "\\`").replace("\n", "%0A").replace("\r", "")
    return f"`{safe}`"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()

    base_sha = git("rev-parse", args.base)
    upstream_sha = git("rev-parse", args.upstream)
    merge_base = git("merge-base", args.base, args.upstream)
    commits = git("rev-list", "--count", f"{args.base}..{args.upstream}")
    rows = git("diff", "--name-status", "--find-renames", merge_base, upstream_sha).splitlines()
    changes = []
    for row in rows:
        fields = row.split("\t")
        status = fields[0]
        path = fields[-1]
        changes.append({"status": status, "path": path, "classification": classify(path)})

    mergeable = True
    try:
        subprocess.run(
            ["git", "merge-tree", "--write-tree", base_sha, upstream_sha],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        mergeable = False

    payload = {
        "base_sha": base_sha,
        "upstream_sha": upstream_sha,
        "incoming_commit_count": int(commits),
        "has_changes": base_sha != upstream_sha and int(commits) > 0,
        "mergeable": mergeable,
        "changes": changes,
    }
    markdown = [
        "## Upstream impact review",
        "",
        f"Upstream: `harry0703/MoneyPrinterTurbo` `main` at `{upstream_sha}`",
        f"Fork base: `{base_sha}`",
        f"Incoming commits: {commits}",
        f"Merge-tree result: {'clean' if mergeable else 'conflict; human resolution required'}",
        "",
        "No incoming file contents are copied into this report. Every change remains subject to human review; no automatic merge is enabled.",
        "",
        "| Status | Path | Review class |",
        "| --- | --- | --- |",
    ]
    markdown.extend(
        f"| `{item['status']}` | {markdown_path(item['path'])} | `{item['classification']}` |"
        for item in changes
    )
    if not changes:
        markdown.append("| — | No changed paths | — |")
    Path(args.markdown).write_text("\n".join(markdown) + "\n", encoding="utf-8")
    Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
