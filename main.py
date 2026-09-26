import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine.config import HotDataFolderConfig, WeChatVaultFolderConfig, load_config
from engine.logger import get_logger
from engine.scheduler import PromotionScheduler
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
    """Starts/stops profiles to match folders.yaml. Both profiles support add,
    remove, and pause/resume live; changing other settings on an already-running
    Hot Data folder still needs a restart (Milestone 5's scope never grew to cover
    that - WeChat Vault's diffing is stricter and does pick up other changes, since
    it has to compare configs anyway to know whether to touch the schedule).
    Pausing a WeChat Vault folder unschedules its job without losing its config or
    its manual "Promote now" availability - only the automatic side is paused."""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._hot_data_profiles: dict[Path, HotDataProfile] = {}
        self._hot_data_configs: dict[Path, HotDataFolderConfig] = {}
        self._hot_data_last_known: dict[Path, tuple] = {}
        self.wechat_vault_profiles: dict[Path, WeChatVaultProfile] = {}
        self._wechat_vault_configs: dict[Path, WeChatVaultFolderConfig] = {}
        self._scheduler = PromotionScheduler()

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

        wanted_vault = {c.staging_path: c for c in configs if isinstance(c, WeChatVaultFolderConfig)}

        for staging_path in list(self.wechat_vault_profiles):
            cfg = wanted_vault.get(staging_path)
            if cfg is None:
                # Folder removed entirely - the profile goes with it.
                self.wechat_vault_profiles.pop(staging_path)
                self._scheduler.unschedule(str(staging_path))
                logger.info("Removed WeChat Vault profile for %s (removed from config)", staging_path)
            elif cfg.paused and self._scheduler.next_run(str(staging_path)) is not None:
                # Still configured, just paused - keep the profile alive (manual
                # "Promote now" must keep working; it looks profiles up in this
                # same dict), only stop the automatic schedule.
                self._scheduler.unschedule(str(staging_path))
                logger.info("Paused automatic WeChat Vault promotion for %s", staging_path)

        for staging_path, cfg in wanted_vault.items():
            old_cfg = self._wechat_vault_configs.get(staging_path)
            if old_cfg == cfg:
                continue  # unchanged - leave the running profile and its schedule alone

            # Rebuild the profile only if one doesn't exist yet, or a field it
            # actually carries changed - NOT just because `paused` flipped. This
            # matters two ways: (a) a folder added paused from the very start
            # still needs a profile at all, so manual "Promote now" has something
            # to call (previously it didn't: KeyError/silent no-op); (b) a folder
            # that was already running keeps its *same* profile object across a
            # pause/resume cycle, so last_attempt_at/last_result (e.g. from a
            # manual promote taken while paused) survive instead of resetting.
            profile_fields_changed = (
                old_cfg is None
                or old_cfg.vault_path != cfg.vault_path
                or old_cfg.keep_failed_staging != cfg.keep_failed_staging
            )
            if staging_path not in self.wechat_vault_profiles or profile_fields_changed:
                self.wechat_vault_profiles[staging_path] = WeChatVaultProfile(
                    cfg.staging_path, cfg.vault_path, cfg.keep_failed_staging,
                )

            if cfg.paused:
                continue  # profile exists for manual use; no automatic schedule

            if old_cfg is None or old_cfg.paused or old_cfg.promote_interval_minutes != cfg.promote_interval_minutes:
                # New folder, resuming from pause (no existing job to preserve), or
                # its interval changed - (re)schedule. The job calls through
                # _promote_callback rather than binding straight to this profile's
                # promote_now, so a later non-interval change (e.g. keep_failed_staging)
                # can swap the profile in place, above, without touching (and
                # resetting) this schedule.
                self._scheduler.schedule(str(staging_path), cfg.promote_interval_minutes, self._promote_callback(staging_path))
                logger.info(
                    "Scheduled WeChat Vault promotion for %s -> %s every %d minute(s)",
                    staging_path, cfg.vault_path, cfg.promote_interval_minutes,
                )
            else:
                logger.info("Updated WeChat Vault profile for %s (schedule unchanged)", staging_path)

        self._wechat_vault_configs = wanted_vault

    def _promote_callback(self, staging_path: Path):
        def callback():
            profile = self.wechat_vault_profiles.get(staging_path)
            if profile is not None:
                profile.promote_now()
        return callback

    def stop_all(self) -> None:
        for profile in self._hot_data_profiles.values():
            profile.stop()
        self._hot_data_profiles.clear()
        self.wechat_vault_profiles.clear()
        self._scheduler.shutdown()

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

        for staging_path, cfg in self._wechat_vault_configs.items():
            # Pausing never removes the profile (manual "Promote now" must keep
            # working - see reload()), so this is only None for a folder added
            # directly as paused, which never got a profile built for it.
            profile = self.wechat_vault_profiles.get(staging_path)
            last_attempt_at = profile.last_attempt_at if profile else None
            result = profile.last_result if profile else None

            if cfg.paused:
                status_label = "paused"
                if result is not None:
                    reason = f"paused - last manual promote: {'ok' if result.promoted else 'failed'}, {result.reason}"
                else:
                    reason = "paused"
            else:
                next_run = self._scheduler.next_run(str(staging_path))
                next_run_note = f"next auto-promote {next_run.strftime('%Y-%m-%d %H:%M:%S')}" if next_run else "not scheduled"
                if result is None:
                    status_label, reason = "unknown", f"not yet promoted ({next_run_note})"
                elif result.promoted:
                    status_label, reason = "ok", f"{result.reason} ({next_run_note})"
                else:
                    status_label, reason = "failed", f"{result.reason} ({next_run_note})"

            rows.append(FolderStatus(
                profile="wechat_vault",
                path=str(staging_path),
                detail=f"vault at {cfg.vault_path}",
                last_activity=_format_time(last_attempt_at),
                status=status_label,
                reason=reason,
                paused=cfg.paused,
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
