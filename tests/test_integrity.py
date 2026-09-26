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


# --- Encrypted (SQLCipher-style) databases: confirmed against a real WeChat
# client, not guessed - see engine/integrity.py's ENCRYPTED_DB_EXTENSIONS comment.

def test_page_aligned_encrypted_db_passes(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "message_0.db").write_bytes(b"\xaa" * 4096 * 3)  # high-entropy, no SQLite header
    result = wechat_vault_integrity_check(staging)
    assert result.ok


def test_non_page_aligned_encrypted_db_is_flagged(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "message_0.db").write_bytes(b"\xaa" * (4096 * 3 + 17))  # 17 bytes short of aligned
    result = wechat_vault_integrity_check(staging)
    assert not result.ok
    assert "page size" in result.reason.lower()


def test_zero_byte_encrypted_db_is_flagged(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "message_0.db").write_bytes(b"")
    result = wechat_vault_integrity_check(staging)
    assert not result.ok
    assert "zero-byte" in result.reason.lower()


def test_kvdb_extension_also_checked(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "media_0.kvdb").write_bytes(b"\xbb" * (4096 * 2 + 1))
    result = wechat_vault_integrity_check(staging)
    assert not result.ok
    assert "media_0.kvdb" in result.reason


def test_wal_and_shm_companions_not_page_checked(tmp_path):
    """WAL/SHM files have their own internal structure (WAL frames carry a
    per-frame header) - page-alignment doesn't apply to them, and they should
    not be flagged just for having an "odd" size. They're still covered by the
    generic size/count checks when a last_good_path is available, just not this
    one - not exercised here since this test only cares that they're skipped,
    not corruption-flagged, by the page-alignment check specifically."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "message_0.db").write_bytes(b"\xaa" * 4096 * 3)  # valid, keeps this test isolated
    (staging / "message_0.db-wal").write_bytes(b"\xcc" * 12345)  # deliberately "odd" size
    (staging / "message_0.db-shm").write_bytes(b"\xdd" * 999)
    result = wechat_vault_integrity_check(staging)
    assert result.ok


def test_mixed_plain_and_encrypted_dbs_both_checked(tmp_path):
    """A vault can plausibly contain both: real WeChat has some plain-SQLite
    files (e.g. head_image.db has been observed unencrypted in some builds)
    alongside SQLCipher ones. Both detection paths must coexist correctly."""
    staging = tmp_path / "staging"
    staging.mkdir()
    make_sqlite_db(staging / "plain.db")
    (staging / "encrypted.db").write_bytes(b"\xaa" * (4096 * 2 + 5))  # misaligned
    result = wechat_vault_integrity_check(staging)
    assert not result.ok
    assert "encrypted.db" in result.reason
    assert "plain.db" not in result.reason
