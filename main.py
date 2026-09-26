import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine.config import HotDataFolderConfig, WeChatVaultFolderConfig, load_config
from engine.logger import get_logger
from engine.watcher import FolderWatcher
from profiles.hot_data import HotDataProfile
from profiles.wechat_vault import WeChatVaultProfile
from web.app import create_app

logger = get_logger()

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "folders.yaml"
DASHBOARD_PORT = 8420


@dataclass
class FolderStatus:
    profile: str
    path: str
    detail: str
    last_activity: Optional[str]
    status: str
    reason: str = ""
    paused: bool = False


def _format_time(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def _version_dir_for(cfg: HotDataFolderConfig) -> Path:
    return cfg.version_dir or cfg.path.parent / f"{cfg.path.name}.versions"


class Manager:
    """Starts/stops profiles to match folders.yaml. Hot Data folders are added,
    removed, and paused/resumed live; changing other settings on a folder that's
    already running still needs a restart for now (Milestone 5's scope never grew
    to cover that). WeChat Vault has no running state to diff, so its profiles are
    just rebuilt each reload - and no pause control for it either, since there's no
    scheduler yet to pause; a pause button with nothing to suspend would be a lie."""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._hot_data_profiles: dict[Path, HotDataProfile] = {}
        self._hot_data_configs: dict[Path, HotDataFolderConfig] = {}
        self._hot_data_last_known: dict[Path, tuple] = {}
        self.wechat_vault_profiles: dict[Path, WeChatVaultProfile] = {}

    def reload(self) -> None:
        configs = load_config(self.config_path)
        wanted_hot_data = {c.path: c for c in configs if isinstance(c, HotDataFolderConfig)}
        self._hot_data_configs = wanted_hot_data

        for path in list(self._hot_data_profiles):
            cfg = wanted_hot_data.get(path)
            if cfg is None or cfg.paused:
                profile = self._hot_data_profiles.pop(path)
                self._hot_data_last_known[path] = (profile.last_event_at, profile.last_event_type)
                logger.info("Stopping Hot Data profile for %s (%s)", path, "paused" if cfg else "removed from config")
                profile.stop()

        for path, cfg in wanted_hot_data.items():
            if cfg.paused or path in self._hot_data_profiles:
                continue
            profile = HotDataProfile(cfg.path, _version_dir_for(cfg), cfg.versions_to_keep)
            try:
                profile.start()
            except OSError as exc:
                # e.g. the configured path doesn't exist (typo'd or not created yet) -
                # skip it, don't take the whole reload down; it'll retry next reload.
                logger.error("Could not start Hot Data profile for %s: %s", path, exc)
                continue
            self._hot_data_profiles[path] = profile
            self._hot_data_last_known.pop(path, None)
            logger.info("Started Hot Data profile for %s", path)

        self.wechat_vault_profiles = {
            cfg.staging_path: WeChatVaultProfile(cfg.staging_path, cfg.vault_path, cfg.keep_failed_staging)
            for cfg in configs if isinstance(cfg, WeChatVaultFolderConfig)
        }
        for staging_path, profile in self.wechat_vault_profiles.items():
            logger.info(
                "Configured WeChat Vault profile %s -> %s (no scheduler yet; use the dashboard's Promote now)",
                staging_path, profile.vault_path,
            )

    def stop_all(self) -> None:
        for profile in self._hot_data_profiles.values():
            profile.stop()
        self._hot_data_profiles.clear()
        self.wechat_vault_profiles.clear()

    def status(self) -> list[FolderStatus]:
        rows = []
        for path, cfg in self._hot_data_configs.items():
            profile = self._hot_data_profiles.get(path)
            if profile is not None:
                last_event_at, last_event_type = profile.last_event_at, profile.last_event_type
                status_label, reason = "ok", (last_event_type or "watching, no changes seen yet")
            else:
                last_event_at, last_event_type = self._hot_data_last_known.get(path, (None, None))
                status_label, reason = "paused", "paused"
            rows.append(FolderStatus(
                profile="hot_data",
                path=str(path),
                detail=f"versions in {_version_dir_for(cfg)}",
                last_activity=_format_time(last_event_at),
                status=status_label,
                reason=reason,
                paused=(profile is None),
            ))

        for staging_path, profile in self.wechat_vault_profiles.items():
            result = profile.last_result
            if result is None:
                status_label, reason = "unknown", "not yet promoted (no scheduler wired up yet)"
            elif result.promoted:
                status_label, reason = "ok", result.reason
            else:
                status_label, reason = "failed", result.reason
            rows.append(FolderStatus(
                profile="wechat_vault",
                path=str(staging_path),
                detail=f"vault at {profile.vault_path}",
                last_activity=_format_time(profile.last_attempt_at),
                status=status_label,
                reason=reason,
            ))

        return rows


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    manager = Manager(config_path)
    manager.reload()

    def on_config_change(event_type: str, path: Path) -> None:
        if event_type in ("modified", "created") and path.resolve() == config_path.resolve():
            logger.info("Config changed, reloading %s", config_path)
            manager.reload()

    config_watcher = FolderWatcher(config_path.parent, on_config_change, recursive=False)
    config_watcher.start()
    logger.info("Watching config %s", config_path)

    app = create_app(manager)
    logger.info("Dashboard on http://0.0.0.0:%d (Ctrl+C to stop)", DASHBOARD_PORT)

    try:
        app.run(host="0.0.0.0", port=DASHBOARD_PORT, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        config_watcher.stop()
        manager.stop_all()
        logger.info("Stopped")


if __name__ == "__main__":
    main()
