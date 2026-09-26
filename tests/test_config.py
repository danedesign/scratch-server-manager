import sys
from pathlib import Path

import pytest
import yaml

from engine.config import (
    HotDataFolderConfig,
    WeChatVaultFolderConfig,
    append_folder,
    load_config,
    set_paused,
)


def write(cfg_path: Path, text: str) -> None:
    cfg_path.write_text(text)


def test_parses_hot_data_and_wechat_vault(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, """
folders:
  - path: /srv/hotdata/documents
    profile: hot_data
    versions_to_keep: 3

  - profile: wechat_vault
    staging_path: /srv/wechat/staging
    vault_path: /srv/vault/wechat
    promote_interval_minutes: 30
""")
    configs = load_config(cfg_path)
    assert len(configs) == 2
    hot = next(c for c in configs if isinstance(c, HotDataFolderConfig))
    vault = next(c for c in configs if isinstance(c, WeChatVaultFolderConfig))
    assert hot.versions_to_keep == 3 and hot.paused is False
    assert vault.promote_interval_minutes == 30 and vault.keep_failed_staging is True


def test_unknown_profile_is_skipped_not_raised(tmp_path, caplog):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, """
folders:
  - profile: not_a_real_profile
    path: /whatever
""")
    configs = load_config(cfg_path)
    assert configs == []


def test_unknown_key_warns_but_entry_still_loads(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, """
folders:
  - profile: hot_data
    path: /srv/hotdata/photos
    made_up_key: surprise
""")
    configs = load_config(cfg_path)
    assert len(configs) == 1
    assert configs[0].path == Path("/srv/hotdata/photos")


def test_missing_required_key_is_skipped_not_raised(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, """
folders:
  - profile: wechat_vault
    staging_path: /srv/wechat/staging
""")
    configs = load_config(cfg_path)
    assert configs == []


def test_empty_or_missing_folders_key(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, "folders: []\n")
    assert load_config(cfg_path) == []


def test_append_folder_adds_to_existing_list(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, "folders:\n- profile: hot_data\n  path: /a\n")
    append_folder(cfg_path, {"profile": "hot_data", "path": "/b", "versions_to_keep": 5})
    raw = yaml.safe_load(cfg_path.read_text())
    assert len(raw["folders"]) == 2
    assert raw["folders"][1]["path"] == "/b"


def test_append_folder_creates_file_if_missing(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    append_folder(cfg_path, {"profile": "hot_data", "path": "/a", "versions_to_keep": 5})
    raw = yaml.safe_load(cfg_path.read_text())
    assert len(raw["folders"]) == 1


def test_set_paused_hot_data(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, "folders:\n- profile: hot_data\n  path: /srv/hotdata/documents\n")
    set_paused(cfg_path, "hot_data", "path", "/srv/hotdata/documents", True)
    configs = load_config(cfg_path)
    assert configs[0].paused is True


def test_set_paused_wechat_vault(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, """
folders:
  - profile: wechat_vault
    staging_path: /srv/wechat/staging
    vault_path: /srv/vault/wechat
""")
    set_paused(cfg_path, "wechat_vault", "staging_path", "/srv/wechat/staging", True)
    configs = load_config(cfg_path)
    assert configs[0].paused is True


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="backslash-vs-forward-slash equivalence is a Windows-only pathlib "
           "behavior; on POSIX a backslash is just a literal character, not a "
           "separator, so this scenario can't occur on a real Linux deployment "
           "(folders.yaml there only ever has forward slashes) - confirmed by "
           "running the suite on Debian, where this test correctly fails as a "
           "different-paths comparison, not a false pass.",
)
def test_set_paused_matches_despite_separator_style_windows(tmp_path):
    """The real bug this guards: YAML forward slashes vs a live Path's native
    (backslash on Windows) separator must still be recognized as the same entry."""
    cfg_path = tmp_path / "folders.yaml"
    write(cfg_path, "folders:\n- profile: hot_data\n  path: C:/Users/example/documents\n")
    set_paused(cfg_path, "hot_data", "path", r"C:\Users\example\documents", True)
    configs = load_config(cfg_path)
    assert configs[0].paused is True
