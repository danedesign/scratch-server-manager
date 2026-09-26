import json

from engine.integrity import IntegrityResult
from engine.staging import promote


def always_ok(path):
    return IntegrityResult(True, "fine")


def always_fail(path):
    return IntegrityResult(False, "forced failure")


def make_staging(tmp_path, content=b"data"):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "f.txt").write_bytes(content)
    return staging


def test_bootstrap_promotion_creates_vault(tmp_path):
    staging = make_staging(tmp_path, b"v1")
    vault = tmp_path / "vault"
    result = promote(staging, vault, always_ok)
    assert result.promoted
    assert (vault / "f.txt").read_bytes() == b"v1"


def test_failed_check_leaves_vault_untouched(tmp_path):
    staging = make_staging(tmp_path, b"v1")
    vault = tmp_path / "vault"
    promote(staging, vault, always_ok)  # establish a good vault first

    (staging / "f.txt").write_bytes(b"v2-bad")
    result = promote(staging, vault, always_fail)
    assert not result.promoted
    assert (vault / "f.txt").read_bytes() == b"v1"  # untouched


def test_failed_check_quarantines_staging_copy(tmp_path):
    staging = make_staging(tmp_path)
    vault = tmp_path / "vault"
    promote(staging, vault, always_fail, keep_failed_staging=True)
    quarantine_dirs = list(tmp_path.glob("staging.failed-*"))
    assert len(quarantine_dirs) == 1
    assert (quarantine_dirs[0] / "f.txt").exists()
    assert staging.exists()  # the live staging dir itself is never touched


def test_failed_check_no_quarantine_when_disabled(tmp_path):
    staging = make_staging(tmp_path)
    vault = tmp_path / "vault"
    promote(staging, vault, always_fail, keep_failed_staging=False)
    assert list(tmp_path.glob("staging.failed-*")) == []


def test_repeated_rapid_failures_do_not_crash(tmp_path):
    """The actual bug found and fixed: same-second quarantine directory names
    collided and crashed with FileExistsError. Calling promote() several times
    in a tight loop (no sleep) reliably reproduces the same-second window."""
    staging = make_staging(tmp_path)
    vault = tmp_path / "vault"
    for _ in range(5):
        result = promote(staging, vault, always_fail, keep_failed_staging=True)
        assert not result.promoted
    assert len(list(tmp_path.glob("staging.failed-*"))) == 5


def test_swap_replaces_existing_vault_atomically(tmp_path):
    staging = make_staging(tmp_path, b"v1")
    vault = tmp_path / "vault"
    promote(staging, vault, always_ok)

    (staging / "f.txt").write_bytes(b"v2")
    (staging / "new_file.txt").write_bytes(b"extra")
    result = promote(staging, vault, always_ok)

    assert result.promoted
    assert (vault / "f.txt").read_bytes() == b"v2"
    assert (vault / "new_file.txt").read_bytes() == b"extra"
    # no leftover temp swap directories
    assert list(tmp_path.glob("vault.new")) == []
    assert list(tmp_path.glob("vault.old-*")) == []


def test_promotion_state_recorded(tmp_path):
    staging = make_staging(tmp_path)
    vault = tmp_path / "vault"
    promote(staging, vault, always_ok, machine_id="machine-a")

    state_path = tmp_path / "vault.promotion-state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["machine"] == "machine-a"


def test_different_machine_promotion_logged_but_not_blocked(tmp_path, app_log):
    staging = make_staging(tmp_path)
    vault = tmp_path / "vault"
    promote(staging, vault, always_ok, machine_id="machine-a")

    (staging / "f.txt").write_bytes(b"v2")
    result = promote(staging, vault, always_ok, machine_id="machine-b")

    assert result.promoted  # single-writer check flags, never blocks
    assert any("machine-b" in m and "machine-a" in m for m in app_log.messages())


def test_alert_fires_on_failure_and_dedupes_repeats(tmp_path, capture_server, monkeypatch):
    monkeypatch.setenv("SYNC_MANAGER_NTFY_URL", f"http://127.0.0.1:{capture_server.server_address[1]}/")
    staging = make_staging(tmp_path)
    vault = tmp_path / "vault"

    promote(staging, vault, always_fail)
    promote(staging, vault, always_fail)
    promote(staging, vault, always_fail)
    assert len(capture_server.received) == 1, "identical repeat failures must not re-alert"

    promote(staging, vault, always_ok)
    promote(staging, vault, always_fail)
    assert len(capture_server.received) == 2, "a fresh failure after recovery must alert again"
