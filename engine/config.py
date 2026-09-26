from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml

from engine.logger import get_logger

logger = get_logger()


@dataclass
class HotDataFolderConfig:
    path: Path
    version_dir: Optional[Path] = None
    versions_to_keep: int = 5
    paused: bool = False


@dataclass
class WeChatVaultFolderConfig:
    staging_path: Path
    vault_path: Path
    promote_interval_minutes: int = 60
    keep_failed_staging: bool = True


FolderConfig = Union[HotDataFolderConfig, WeChatVaultFolderConfig]

# staging_path/vault_path (not the single `path` from the original planning-notes example)
# because the two can legitimately live on different disks/trees - deriving one from the
# other the way Hot Data derives its sibling `.versions` dir would be guessing.
KNOWN_KEYS = {
    "hot_data": {"path", "version_dir", "versions_to_keep", "paused"},
    "wechat_vault": {"staging_path", "vault_path", "promote_interval_minutes", "keep_failed_staging"},
}


def load_config(config_path: Path) -> list[FolderConfig]:
    config_path = Path(config_path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    entries = raw.get("folders") or []

    configs: list[FolderConfig] = []
    for entry in entries:
        profile = entry.get("profile")
        if profile not in KNOWN_KEYS:
            logger.warning("Skipping folder entry with unknown profile %r: %s", profile, entry)
            continue

        unknown = set(entry) - KNOWN_KEYS[profile] - {"profile"}
        for key in unknown:
            logger.warning("Ignoring unknown key %r for profile %r in entry: %s", key, profile, entry)

        try:
            if profile == "hot_data":
                configs.append(HotDataFolderConfig(
                    path=Path(entry["path"]),
                    version_dir=Path(entry["version_dir"]) if "version_dir" in entry else None,
                    versions_to_keep=entry.get("versions_to_keep", 5),
                    paused=entry.get("paused", False),
                ))
            else:
                configs.append(WeChatVaultFolderConfig(
                    staging_path=Path(entry["staging_path"]),
                    vault_path=Path(entry["vault_path"]),
                    promote_interval_minutes=entry.get("promote_interval_minutes", 60),
                    keep_failed_staging=entry.get("keep_failed_staging", True),
                ))
        except KeyError as exc:
            logger.warning("Skipping folder entry missing required key %s: %s", exc, entry)

    return configs


def append_folder(config_path: Path, entry: dict) -> None:
    """Adds one folder entry to folders.yaml. Rewrites the whole file via
    yaml.safe_dump, so hand-added comments/formatting won't survive a write made
    through the dashboard - a known tradeoff of a UI and hand-editing sharing one file."""
    config_path = Path(config_path)
    raw = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    raw = raw or {}
    raw.setdefault("folders", []).append(entry)
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False))


def set_paused(config_path: Path, hot_data_path: str, paused: bool) -> None:
    """Flips `paused` on the hot_data entry matching this path. Compares via Path,
    not the raw string, since the YAML may use forward slashes while a path built
    from a live Config object renders with the OS's own separator."""
    config_path = Path(config_path)
    target = Path(hot_data_path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    for entry in raw.get("folders", []):
        if entry.get("profile") == "hot_data" and Path(entry.get("path", "")) == target:
            entry["paused"] = paused
            break
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
