import json
from pathlib import Path
import shutil
import os
import subprocess
import sys

import pytest

from app.services.studio_channel_setup import initialize_channel, channel_environment
from app.services.story_studio import load_director_profile
from app.utils import utils


def test_fresh_channel_loads_mandatory_cinema_and_isolated_state(tmp_path, monkeypatch):
    root = tmp_path / "new-channel"
    initialize_channel(
        root,
        channel_id="new-channel",
        channel_name="New Channel",
        rights_owner="Example Inc.",
    )
    env = channel_environment(root)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    profile = load_director_profile()
    assert profile["mandatory_cinema"] is True
    assert profile["approved_assets"] == []
    assert profile["creative_defaults"]["initial_audience"]["reviewed"] is False
    assert profile["production_attribution"]["rights_owner"] == "Example Inc."
    assert Path(utils.storage_dir()) == root / "storage"
    assert (
        json.loads((root / "accounts.json").read_text())["platforms"]["youtube_long"][
            "account_id"
        ]
        == ""
    )
    assert 'llm_provider = ""' in (root / "config.toml").read_text()


def test_reuses_rules_not_credentials_accounts_assets_or_approvals(tmp_path):
    source = tmp_path / "original"
    initialize_channel(source, channel_id="old-channel", channel_name="Old Channel")
    profile = json.loads((source / "brand-profile.json").read_text())
    profile.update(
        {
            "api_key": "never-copy-me",
            "accounts": {"youtube": "old-owner"},
            "approved_assets": ["old-cast"],
        }
    )
    profile["production_attribution"] = {
        "required": True,
        "credit_line": "Example Media built this.",
        "required_hashtags": ["OldChannel", "ExampleMedia"],
        "search_keywords": ["Example Media"],
        "rights_owner": "Example Inc.",
    }
    (source / "brand-profile.json").write_text(json.dumps(profile))
    learning = json.loads((source / "production-learning.json").read_text())
    learning["entries"] = [
        {
            "id": "acting",
            "criterion_id": "native",
            "rule": "Old Channel actors speak visibly",
            "status": "applied",
            "evidence": "/old/laptop/private.mp4",
        },
        {"id": "experiment", "status": "experiment"},
    ]
    (source / "production-learning.json").write_text(json.dumps(learning))
    root = tmp_path / "second"
    initialize_channel(
        root,
        channel_id="second-channel",
        channel_name="New Channel",
        source_profile=source / "brand-profile.json",
    )
    output = "".join(p.read_text() for p in root.glob("*.json"))
    assert (
        "never-copy-me" not in output
        and "old-owner" not in output
        and "old-cast" not in output
    )
    assert "/old/laptop/private.mp4" not in output
    copied = json.loads((root / "brand-profile.json").read_text())
    assert copied["production_attribution"]["required_hashtags"] == [
        "NewChannel",
        "ExampleMedia",
    ]
    assert "New Channel actors speak visibly" in output
    assert json.loads((root / "asset-registry.json").read_text())["assets"] == {}


def test_moved_channel_rebases_private_paths(tmp_path):
    old = tmp_path / "old"
    initialize_channel(old, channel_id="old-channel", channel_name="Old Channel")
    new = tmp_path / "new"
    shutil.move(old, new)
    env = channel_environment(new)
    profile = load_director_profile(profile_path=env["STORY_STUDIO_PROFILE_PATH"])
    assert Path(profile["private_director_template"]).parent == new
    assert profile["media_delivery"]["destination"] == str(new / "media")


def test_refuses_existing_state_or_git_checkout(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    with pytest.raises(FileExistsError):
        initialize_channel(root, channel_id="new-channel", channel_name="Name")
    (root / ".git").mkdir()
    with pytest.raises(ValueError, match="outside a Git"):
        initialize_channel(
            root / "private", channel_id="new-channel", channel_name="Name"
        )


def test_launched_runtime_reads_external_config_only(tmp_path):
    root = tmp_path / "isolated"
    initialize_channel(root, channel_id="isolated-channel", channel_name="Name")
    env = {**os.environ, **channel_environment(root)}
    code = "from app.config import config; import os; assert config.config_file == os.environ['STORY_STUDIO_CONFIG_PATH']; assert config.app.get('llm_provider') == ''; assert not config.app.get('openai_api_key')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
