from engine.integrity import wechat_vault_integrity_check
from tests.conftest import make_sqlite_db


def test_valid_db_no_baseline_passes(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    make_sqlite_db(staging / "MSG0.db")
    result = wechat_vault_integrity_check(staging)
    assert result.ok


def test_corrupted_db_body_fails(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    db = staging / "MSG0.db"
    make_sqlite_db(db)
    with open(db, "r+b") as f:
        f.seek(100)
        f.write(b"\x00" * 200)

    result = wechat_vault_integrity_check(staging)
    assert not result.ok
    assert "header" not in result.reason.lower()  # this path is PRAGMA's own message


def test_corrupted_header_without_baseline_is_not_flagged(tmp_path):
    """Documents the known, accepted gap: with no last_good_path to compare
    against, a file whose header is already broken looks indistinguishable
    from a file that was never a database."""
    staging = tmp_path / "staging"
    staging.mkdir()
    db = staging / "MSG0.db"
    make_sqlite_db(db)
    with open(db, "r+b") as f:
        f.seek(0)
        f.write(b"\x00" * 20)

    result = wechat_vault_integrity_check(staging)
    assert result.ok  # no SQLite files detected at all -> nothing to check


def test_corrupted_header_with_baseline_is_flagged(tmp_path):
    """The actual bug found and fixed: header-sniffing alone would silently
    skip a header-corrupted file. With a last_good_path, it must be flagged."""
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    vault.mkdir()
    make_sqlite_db(staging / "MSG0.db")
    make_sqlite_db(vault / "MSG0.db")  # last-good copy has a valid header

    with open(staging / "MSG0.db", "r+b") as f:
        f.seek(0)
        f.write(b"\x00" * 20)

    result = wechat_vault_integrity_check(staging, last_good_path=vault)
    assert not result.ok
    assert "header" in result.reason.lower()


def test_file_count_drop_is_flagged(tmp_path):
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    vault.mkdir()
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        (vault / name).write_bytes(b"data")
    for name in ("a.jpg",):
        (staging / name).write_bytes(b"data")

    result = wechat_vault_integrity_check(staging, last_good_path=vault)
    assert not result.ok
    assert "dropped" in result.reason.lower()


def test_small_drop_within_ratio_passes(tmp_path):
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    vault.mkdir()
    for name in ("a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"):
        (vault / name).write_bytes(b"data")
    for name in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):  # 20% drop, at the default threshold
        (staging / name).write_bytes(b"data")

    result = wechat_vault_integrity_check(staging, last_good_path=vault, max_drop_ratio=0.2)
    assert result.ok


def test_newly_truncated_file_is_flagged(tmp_path):
    # Several other same-size files keep the aggregate size/count drop under the
    # threshold, isolating the truncation-specific check rather than tripping the
    # size-drop check first.
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    vault.mkdir()
    for name in ("b.jpg", "c.jpg", "d.jpg", "e.jpg", "f.jpg"):
        (vault / name).write_bytes(b"some bytes")
        (staging / name).write_bytes(b"some bytes")
    (vault / "avatar.jpg").write_bytes(b"some bytes")
    (staging / "avatar.jpg").write_bytes(b"")

    result = wechat_vault_integrity_check(staging, last_good_path=vault)
    assert not result.ok
    assert "truncated" in result.reason.lower()


def test_brand_new_zero_byte_file_not_flagged(tmp_path):
    """A zero-byte file with no prior counterpart could be a normal new file -
    only a regression (was non-zero, now zero) should be flagged."""
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    vault.mkdir()
    (vault / "existing.jpg").write_bytes(b"data")
    (staging / "existing.jpg").write_bytes(b"data")
    (staging / "brand_new.lock").write_bytes(b"")

    result = wechat_vault_integrity_check(staging, last_good_path=vault)
    assert result.ok
