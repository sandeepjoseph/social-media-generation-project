"""Portable, isolated channel initialization; never copies credentials or posts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

from app.services.studio_cinema import CONTRACT_VERSION, DEFAULTS

PLATFORM_CATEGORIES = {
    "youtube_long": {"primary": "Education", "fallback": "Film & Animation"},
    "youtube_short": {"primary": "Education", "fallback": "Film & Animation"},
    "facebook_reels": {"primary": "Digital creator", "secondary": "Education"},
    "instagram_reels": {"primary": "Digital creator", "secondary": "Education"},
    "tiktok": {},
    "dailymotion": {"primary": "Education", "fallback": "Entertainment"},
    "rumble": {"primary": "Entertainment", "secondary": "Education"},
}
_PROFILE_FIELDS = (
    "creative_defaults",
    "story_values",
    "editorial_policy",
    "packaging_defaults",
    "caption_policy",
    "cinema_policy",
    "efficiency_policy",
    "production_attribution",
)
_TEMPLATE_FIELDS = (
    "schema_version",
    "input_contract",
    "role_briefs",
    "scene_contract_required",
    "execution_policy",
    "acceptance_criteria",
)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, document):
    with Path(path).open("x", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        output.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")


def _dependency(profile, profile_path, key):
    raw = str(profile.get(key) or "")
    # A private policy checkout can be moved to a new laptop even if its source
    # profile recorded the old laptop's absolute dependency locations.
    local = Path(profile_path).parent / raw.replace("\\", "/").rsplit("/", 1)[-1]
    if not raw:
        raise ValueError(f"Source profile is missing {key}")
    return _read(local if local.is_file() else Path(raw).expanduser())


def _rename(value, old, new):
    if isinstance(value, dict):
        return {key: _rename(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_rename(item, old, new) for item in value]
    return value.replace(old, new) if old and isinstance(value, str) else value


def initialize_channel(
    root,
    *,
    channel_id,
    channel_name,
    source_profile=None,
    rights_owner=None,
    media_root=None,
    timezone="America/Toronto",
):
    """Create fresh private state from creative policy, without old account state."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,47}", channel_id):
        raise ValueError("Channel ID needs 2–48 lowercase letters, digits or hyphens")
    if not channel_name.strip() or len(channel_name) > 80 or "\n" in channel_name:
        raise ValueError("Channel name needs one nonempty line, up to 80 characters")
    ZoneInfo(timezone)
    root = Path(root).expanduser().resolve()
    if any(
        (parent / ".git").exists()
        for parent in (root, *root.parents)
        if parent != Path.home()
    ):
        raise ValueError("Channel state must stay outside a Git checkout")
    if root.exists():
        raise FileExistsError(
            "Choose a new channel directory; existing state is never overwritten"
        )
    source = _read(source_profile) if source_profile else {}
    source_template = (
        _dependency(source, source_profile, "private_director_template")
        if source
        else {}
    )
    learning = (
        _dependency(source, source_profile, "private_learning_log")
        if source
        else {"revision": 0, "entries": []}
    )
    revision = source.get("template_revision") or "portable-cinema-v1"
    if source and (
        source_template.get("template_revision") != revision
        or learning.get("active_template_revision") != revision
    ):
        raise ValueError(
            "Source profile, template and applied learning revisions must match"
        )
    profile = {
        key: copy.deepcopy(source[key]) for key in _PROFILE_FIELDS if key in source
    }
    old_brand = source.get("brand")
    old_brand = old_brand.get("name", "") if isinstance(old_brand, dict) else old_brand
    profile = _rename(profile, old_brand, channel_name)
    profile.update(
        {
            "profile_id": channel_id,
            "profile_visibility": "private_local",
            "brand": channel_name,
            "template_revision": revision,
            "mandatory_cinema": True,
            "required_cinema_contract_version": CONTRACT_VERSION,
            "cinema_policy": {
                **DEFAULTS,
                **profile.get("cinema_policy", {}),
                "enabled": True,
            },
            "private_director_template": str(root / "director-template.json"),
            "private_learning_log": str(root / "production-learning.json"),
            "private_asset_registry": str(root / "asset-registry.json"),
            "media_delivery": {
                "enabled": True,
                "destination": str(
                    Path(media_root).expanduser().resolve()
                    if media_root
                    else Path.home() / "Desktop" / "Deployments" / "Social" / channel_id
                ),
                "timezone": timezone,
                "archive_on_generation": True,
                "preserve_versions": True,
            },
        }
    )
    creative = profile.setdefault("creative_defaults", {})
    creative["initial_audience"] = {
        "age_min": 6,
        "age_max": 10,
        "language": "en",
        "made_for_kids": True,
        "reviewed": False,
    }
    creative["target_duration_seconds"] = 420
    creative.setdefault(
        "languages", {"primary": "English", "additional_draft": "Malayalam"}
    )
    profile.setdefault(
        "caption_policy",
        {
            "required": True,
            "audio_caption_locale_match": True,
            "burn_in": True,
            "sidecars": ["srt", "vtt"],
            "missing_locale_blocks_publication": True,
            "localizations_need_fluent_review": True,
        },
    )
    packaging = profile.setdefault("packaging_defaults", {})
    packaging["platform_categories"] = copy.deepcopy(PLATFORM_CATEGORIES)
    packaging["platform_targets"] = [
        p for p in PLATFORM_CATEGORIES if p != "youtube_short"
    ]
    brand_token = (
        re.sub(r"[^A-Za-z0-9_]", "", channel_name)[:32]
        or channel_id.replace("-", "")[:32]
    )
    packaging["brand_hashtag"] = brand_token
    attribution = profile.setdefault("production_attribution", {})
    if source:
        # Only the channel hashtag changes. Company attribution stays intact.
        old_token = re.sub(r"[^A-Za-z0-9_]", "", str(old_brand))[:32]
        attribution["required_hashtags"] = list(
            dict.fromkeys(
                [brand_token]
                + [
                    tag
                    for tag in source.get("production_attribution", {}).get(
                        "required_hashtags", []
                    )
                    if tag.removeprefix("#") not in {old_token, brand_token}
                ]
            )
        )[:4]
    if rights_owner is not None:
        if not rights_owner.strip() or "\n" in rights_owner:
            raise ValueError("Rights owner needs a nonempty single line")
        attribution["rights_owner"] = rights_owner.strip()
    attribution["copyright_required"] = bool(attribution.get("rights_owner"))
    template = {
        key: copy.deepcopy(source_template[key])
        for key in _TEMPLATE_FIELDS
        if key in source_template
    }
    template = _rename(template, old_brand, channel_name)
    template.update(
        {"schema_version": 1, "brand": channel_name, "template_revision": revision}
    )
    template.setdefault(
        "role_briefs",
        {
            role: f"Provide and validate the {role} decisions before generation."
            for role in (
                "researcher",
                "screenwriter",
                "director",
                "choreographer",
                "cinematographer",
                "lighting",
                "sound",
                "caption_editor",
                "growth_editor",
                "quality_reviewer",
            )
        },
    )
    template.setdefault(
        "acceptance_criteria",
        [
            "Native character acting and dialogue; two-character A/V pilot and actual lip-sync review.",
            "Six to eight minutes, coherent plot, no repeated-shot padding or silent TTS fallback.",
            "Fluent locale-bound captions, reviewed rights, audience, AI and exact-master publication gates.",
        ],
    )
    template.setdefault(
        "scene_contract_required",
        [
            "camera",
            "lighting",
            "weather",
            "story_clock",
            "sound_cues",
            "prop_state_before",
            "prop_state_after",
            "continuity",
            "costume_state",
        ],
    )
    fresh_learning = {
        "schema_version": 1,
        "revision": learning.get("revision", 0),
        "active_template_revision": revision,
        "entries": [
            {
                key: _rename(row[key], old_brand, channel_name)
                for key in ("id", "criterion_id", "rule", "status")
                if key in row
            }
            for row in learning.get("entries", [])
            if row.get("status") == "applied"
        ],
    }
    root.mkdir(parents=True, mode=0o700)
    os.chmod(root, 0o700)
    for directory in (root / "storage", Path(profile["media_delivery"]["destination"])):
        directory.mkdir(parents=True, exist_ok=True)
    _write(root / "brand-profile.json", profile)
    _write(root / "director-template.json", template)
    _write(root / "production-learning.json", fresh_learning)
    _write(root / "asset-registry.json", {"schema_version": 1, "assets": {}})
    _write(
        root / "accounts.json",
        {
            "schema_version": 1,
            "channel_id": channel_id,
            "platforms": {
                p: {
                    "account_id": "",
                    "handle": "",
                    "connection_status": "not_configured",
                    "category_suggestion": category,
                }
                for p, category in PLATFORM_CATEGORIES.items()
            },
            "note": "Fresh owner accounts and supported publishing adapters must be connected and verified per platform; this file grants no access or publishing permission.",
        },
    )
    _write(root / "cost-router-overrides.json", {})
    # No real/default example credential values or old provider budgets imported.
    config_path = root / "config.toml"
    config_path.write_text('[app]\nllm_provider = ""\n\n[ui]\n', encoding="utf-8")
    os.chmod(config_path, 0o600)
    manifest = {
        "schema_version": 1,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "profile": "brand-profile.json",
        "runtime_config": "config.toml",
        "storage": "storage",
        "accounts": "accounts.json",
        "cost_overrides": "cost-router-overrides.json",
        "status": "configure_local_credentials_and_accounts_before_generation_or_publication",
        "copied_credentials": False,
        "copied_approvals": False,
        "copied_media": False,
        "source_policy_sha256": hashlib.sha256(
            Path(source_profile).read_bytes()
        ).hexdigest()
        if source
        else None,
    }
    _write(root / "channel.json", manifest)
    return {"channel_root": str(root), **manifest}


def channel_environment(root):
    """Resolve local paths after transfer; rebase policy dependencies on this laptop."""
    root = Path(root).expanduser().resolve()
    manifest = _read(root / "channel.json")
    profile_path = root / manifest["profile"]
    profile = _read(profile_path)
    for key, filename in (
        ("private_director_template", "director-template.json"),
        ("private_learning_log", "production-learning.json"),
        ("private_asset_registry", "asset-registry.json"),
    ):
        profile[key] = str(root / filename)
    # Isolated delivery remains portable. An explicit external archive can be
    # selected in the private profile on the destination laptop.
    if not Path(profile["media_delivery"]["destination"]).is_dir():
        destination = (
            Path.home() / "Desktop" / "Deployments" / "Social" / manifest["channel_id"]
        )
        profile["media_delivery"]["destination"] = str(destination)
        destination.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    if profile_path.read_text(encoding="utf-8") != serialized:
        profile_path.write_text(serialized, encoding="utf-8")
    return {
        "STORY_STUDIO_PROFILE_PATH": str(profile_path),
        "STORY_STUDIO_CONFIG_PATH": str(root / manifest["runtime_config"]),
        "STORY_STUDIO_STORAGE_ROOT": str(root / manifest["storage"]),
        "STORY_STUDIO_COST_OVERRIDES_PATH": str(root / manifest["cost_overrides"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--root", required=True)
    init.add_argument("--channel-id", required=True)
    init.add_argument("--channel-name", required=True)
    init.add_argument("--source-profile")
    init.add_argument("--rights-owner")
    init.add_argument("--media-root")
    init.add_argument("--timezone", default="America/Toronto")
    launch = commands.add_parser("launch")
    launch.add_argument("--root", required=True)
    launch.add_argument("--port", type=int, default=8511)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "init":
        print(json.dumps(initialize_channel(**args), indent=2))
    else:
        root = args["root"]
        env = {**os.environ, **channel_environment(root)}
        repo = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
        raise SystemExit(
            subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(repo / "webui" / "Main.py"),
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(args["port"]),
                ],
                cwd=repo,
                env=env,
            )
        )


if __name__ == "__main__":
    main()
