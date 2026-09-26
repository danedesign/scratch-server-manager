import time

import pytest

from main import Manager
from tests.conftest import make_sqlite_db, wait_until


def write_config(cfg_path, text):
    cfg_path.write_text(text)


@pytest.fixture
def manager(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    cfg_path.write_text("folders: []\n")
    m = Manager(cfg_path)
    try:
        yield m, cfg_path
    finally:
        m.stop_all()


# ---------------------------------------------------------------- Hot Data ---

def test_hot_data_add_starts_watching(manager, tmp_path):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"""
folders:
  - path: {watched.as_posix()}
    profile: hot_data
    versions_to_keep: 3
""")
    m.reload()
    assert watched in m._hot_data_profiles

    (watched / "f.txt").write_text("hi")
    assert wait_until(lambda: m.status()[0].last_activity is not None)
    assert m.status()[0].status == "ok"


def test_hot_data_remove_stops_watching(manager, tmp_path):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n")
    m.reload()
    assert watched in m._hot_data_profiles

    write_config(cfg_path, "folders: []\n")
    m.reload()
    assert watched not in m._hot_data_profiles
    assert m.status() == []


def test_hot_data_pause_stops_watcher_but_keeps_row(manager, tmp_path):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n")
    m.reload()

    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n  paused: true\n")
    m.reload()
    assert watched not in m._hot_data_profiles
    row = m.status()[0]
    assert row.status == "paused" and row.paused is True

    # a write while paused must produce no activity at all
    (watched / "ignored.txt").write_text("should not be seen")
    time.sleep(0.3)
    assert m.status()[0].last_activity is None


def test_hot_data_resume_starts_a_fresh_watcher(manager, tmp_path):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n  paused: true\n")
    m.reload()

    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n  paused: false\n")
    m.reload()
    assert watched in m._hot_data_profiles
    assert m.status()[0].status == "ok"

    (watched / "f.txt").write_text("hi")
    assert wait_until(lambda: m.status()[0].last_activity is not None)


def test_hot_data_settings_change_restarts_watcher_live(manager, tmp_path):
    """The gap this closes: changing versions_to_keep on an already-running
    folder used to be silently ignored until the app restarted, since reload()
    only diffed on path presence. watchdog's Observer can't be updated in
    place, so "live" here means the watcher is stopped and a fresh one started
    with the new settings on the next reload - no restart of the app itself."""
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n  versions_to_keep: 3\n")
    m.reload()
    profile_before = m._hot_data_profiles[watched]
    assert profile_before.versions_to_keep == 3

    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n  versions_to_keep: 7\n")
    m.reload()
    profile_after = m._hot_data_profiles[watched]
    assert profile_after.versions_to_keep == 7
    assert profile_after is not profile_before, "a fresh profile is required - the old watcher can't be reused"

    (watched / "f.txt").write_text("hi")
    assert wait_until(lambda: m.status()[0].last_activity is not None), "the new watcher must actually be running"


def test_hot_data_unrelated_reload_does_not_restart_watcher(manager, tmp_path):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n  versions_to_keep: 3\n")
    m.reload()
    profile_before = m._hot_data_profiles[watched]

    m.reload()  # nothing changed
    assert m._hot_data_profiles[watched] is profile_before, "an unrelated reload must not restart the watcher"


def test_hot_data_nonexistent_path_does_not_crash_reload(manager, tmp_path):
    m, cfg_path = manager
    good = tmp_path / "good"
    good.mkdir()
    write_config(cfg_path, f"""
folders:
  - path: {(tmp_path / "does-not-exist").as_posix()}
    profile: hot_data
  - path: {good.as_posix()}
    profile: hot_data
""")
    m.reload()  # must not raise
    assert good in m._hot_data_profiles
    assert (tmp_path / "does-not-exist") not in m._hot_data_profiles


# ------------------------------------------------------------- WeChat Vault --

def wechat_config(staging, vault, **extra):
    lines = [
        "folders:",
        "  - profile: wechat_vault",
        f"    staging_path: {staging.as_posix()}",
        f"    vault_path: {vault.as_posix()}",
    ]
    for key, value in extra.items():
        lines.append(f"    {key}: {value}")
    return "\n".join(lines) + "\n"


def test_hot_data_status_includes_syncthing_summary_when_configured(manager, tmp_path, monkeypatch):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"""
folders:
  - path: {watched.as_posix()}
    profile: hot_data
    syncthing_folder_id: abcde-fghij
""")
    m.reload()

    monkeypatch.setattr(
        "main.get_folder_status",
        lambda folder_id: {"state": "syncing", "needFiles": 2} if folder_id == "abcde-fghij" else None,
    )
    row = m.status()[0]
    assert "syncthing: syncing (2 file(s) remaining)" in row.reason


def test_hot_data_status_unaffected_when_syncthing_unconfigured(manager, tmp_path, monkeypatch):
    m, cfg_path = manager
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n")
    m.reload()

    monkeypatch.setattr("main.get_folder_status", lambda folder_id: pytest.fail("should not be called"))
    row = m.status()[0]
    assert "syncthing" not in row.reason


def make_vault_folders(tmp_path):
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    make_sqlite_db(staging / "MSG0.db")
    return staging, vault


def test_wechat_vault_add_schedules_a_job(manager, tmp_path):
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60))
    m.reload()
    assert staging in m.wechat_vault_profiles
    assert m._scheduler.next_run(str(staging)) is not None


def test_wechat_vault_remove_unschedules_and_drops_profile(manager, tmp_path):
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault))
    m.reload()

    write_config(cfg_path, "folders: []\n")
    m.reload()
    assert staging not in m.wechat_vault_profiles
    assert m._scheduler.next_run(str(staging)) is None


def test_wechat_vault_unrelated_reload_does_not_reset_timer(manager, tmp_path):
    """The timer-reset trap: APScheduler's add_job(replace_existing=True) resets
    next_run_time even for identical settings, so Manager.reload() must not
    call schedule() again for a folder whose config didn't actually change."""
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60))
    m.reload()
    first = m._scheduler.next_run(str(staging))

    m.reload()  # nothing changed
    second = m._scheduler.next_run(str(staging))
    assert first == second


def test_wechat_vault_interval_change_reschedules(manager, tmp_path):
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60))
    m.reload()
    first = m._scheduler.next_run(str(staging))

    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=30))
    m.reload()
    second = m._scheduler.next_run(str(staging))
    assert second != first


def test_wechat_vault_non_interval_change_updates_profile_without_resetting_timer(manager, tmp_path):
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, keep_failed_staging="true"))
    m.reload()
    first = m._scheduler.next_run(str(staging))

    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, keep_failed_staging="false"))
    m.reload()
    second = m._scheduler.next_run(str(staging))
    assert second == first
    assert m.wechat_vault_profiles[staging].keep_failed_staging is False


def test_wechat_vault_pause_unschedules_but_keeps_profile(manager, tmp_path):
    """The bug found and fixed: pausing used to drop the profile entirely,
    which silently broke manual "Promote now" (it looks the profile up in
    this same dict) while paused."""
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60))
    m.reload()

    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, paused="true"))
    m.reload()
    assert m._scheduler.next_run(str(staging)) is None
    assert staging in m.wechat_vault_profiles, "profile must survive pause for manual promote to keep working"

    row = m.status()[0]
    assert row.status == "paused" and row.paused is True


def test_manual_promote_still_works_while_paused(manager, tmp_path):
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, paused="true"))
    m.reload()

    profile = m.wechat_vault_profiles[staging]
    result = profile.promote_now(machine_id="manual-test")
    assert result.promoted

    row = m.status()[0]
    assert row.status == "paused"
    assert "last manual promote: ok" in row.reason
    assert row.last_activity is not None
    assert m._scheduler.next_run(str(staging)) is None, "a manual promote must not resurrect the schedule"


def test_pause_then_resume_preserves_prior_promotion_history(manager, tmp_path):
    """A pleasant side effect of fixing the "born paused" bug above: pausing an
    already-running folder now reuses the same profile object rather than
    discarding and rebuilding it, so a promotion from before the pause is still
    visible after resuming - it no longer resets to blank."""
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60))
    m.reload()
    m.wechat_vault_profiles[staging].promote_now(machine_id="before-pause")
    assert m.status()[0].last_activity is not None

    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, paused="true"))
    m.reload()
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, paused="false"))
    m.reload()

    assert m.status()[0].last_activity is not None, "promotion history should survive a pause/resume cycle"


def test_wechat_vault_resume_reschedules(manager, tmp_path):
    m, cfg_path = manager
    staging, vault = make_vault_folders(tmp_path)
    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, paused="true"))
    m.reload()
    assert m._scheduler.next_run(str(staging)) is None

    write_config(cfg_path, wechat_config(staging, vault, promote_interval_minutes=60, paused="false"))
    m.reload()
    assert m._scheduler.next_run(str(staging)) is not None


def test_stop_all_cleans_up_without_raising(tmp_path):
    # Not using the `manager` fixture - it also calls stop_all() on teardown,
    # and this test wants to be the only caller so it can inspect state after.
    cfg_path = tmp_path / "folders.yaml"
    staging, vault = make_vault_folders(tmp_path)
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    write_config(cfg_path, wechat_config(staging, vault) + f"  - path: {watched.as_posix()}\n    profile: hot_data\n")

    m = Manager(cfg_path)
    m.reload()
    m.stop_all()  # must not raise
    assert m._hot_data_profiles == {}
    assert m.wechat_vault_profiles == {}
