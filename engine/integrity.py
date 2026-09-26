import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SQLITE_HEADER = b"SQLite format 3\x00"

# Confirmed against a real WeChat Linux client (db_storage/{message,contact,session,...}),
# not guessed: every .db/.kvdb file there is SQLCipher-encrypted - `file` reports "data"
# for all of them, and the first bytes are high-entropy with no plaintext header, since
# SQLCipher encrypts the header too. Content can't identify these as databases at all,
# so - unlike the plain-SQLite path above - this is deliberately extension-based. Doesn't
# match `.db-wal`/`.db-shm`/`.kvdb-wal`/`.kvdb-shm` companion files (their full suffix,
# e.g. ".db-wal", isn't in this set) - those have a different internal structure (WAL
# frames carry their own per-frame header) and page-alignment doesn't apply to them; they're
# still covered by the generic size/count/truncation checks below, just not this one.
ENCRYPTED_DB_EXTENSIONS = {".db", ".kvdb"}

# SQLCipher's default page size. Configurable in principle, but this is what a real
# WeChat client's files were observed to align to (908, 151, and 19 pages exactly, for
# three different .db files of different sizes) - good enough for a corruption signal.
SQLCIPHER_PAGE_SIZE = 4096


@dataclass
class IntegrityResult:
    ok: bool
    reason: str = ""


def basic_integrity_check(path: Path) -> IntegrityResult:
    """Placeholder check used to exercise staging/promote plumbing without a real profile."""
    path = Path(path)
    if not path.is_dir():
        return IntegrityResult(False, f"{path} is not a directory")
    if not any(path.iterdir()):
        return IntegrityResult(False, f"{path} is empty")
    return IntegrityResult(True, "basic check passed (exists, non-empty)")


def wechat_vault_integrity_check(
    staging_path: Path,
    last_good_path: Optional[Path] = None,
    max_drop_ratio: float = 0.2,
) -> IntegrityResult:
    """SQLite-aware check for the WeChat Vault profile. `last_good_path`, when given
    (normally the current live vault), enables the count/size/truncation comparisons;
    without it (e.g. first-ever promotion) only the SQLite check runs."""
    staging_path = Path(staging_path)
    if not staging_path.is_dir():
        return IntegrityResult(False, f"{staging_path} is not a directory")

    last_good_path = Path(last_good_path) if last_good_path is not None and Path(last_good_path).is_dir() else None

    bad_db = _check_sqlite_files(staging_path, last_good_path)
    if bad_db:
        return IntegrityResult(False, "; ".join(bad_db))

    if last_good_path is None:
        return IntegrityResult(True, "sqlite integrity ok (no prior vault to compare against)")

    staging_count, staging_size = _snapshot_stats(staging_path)
    good_count, good_size = _snapshot_stats(last_good_path)

    if good_count > 0 and staging_count < good_count * (1 - max_drop_ratio):
        return IntegrityResult(False, f"file count dropped from {good_count} to {staging_count}")
    if good_size > 0 and staging_size < good_size * (1 - max_drop_ratio):
        return IntegrityResult(False, f"total size dropped from {good_size} to {staging_size} bytes")

    truncated = _find_newly_truncated(staging_path, last_good_path)
    if truncated:
        return IntegrityResult(False, f"newly zero-byte/truncated files: {', '.join(truncated)}")

    return IntegrityResult(True, "sqlite integrity ok, size/count within expected range")


def _is_sqlite_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _check_sqlite_files(root: Path, last_good_path: Optional[Path] = None) -> list[str]:
    """Runs PRAGMA integrity_check on every file that currently looks like plain
    SQLite. Also catches the case header-sniffing alone would miss: a file that WAS
    a valid SQLite database in last_good_path but no longer has a valid header in
    root (e.g. its header got corrupted/truncated) - that's flagged, not silently
    treated as "not a database, nothing to check". Files that were never plain
    SQLite but match WeChat's real encrypted-database naming get a page-alignment
    check instead - see ENCRYPTED_DB_EXTENSIONS for why PRAGMA can't run on them."""
    problems = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)

        if _is_sqlite_file(path):
            ok, detail = _sqlite_integrity_check_file(path)
            if not ok:
                problems.append(f"{relative}: {detail}")
            continue

        if last_good_path is not None:
            previous = last_good_path / relative
            if previous.is_file() and _is_sqlite_file(previous):
                problems.append(f"{relative}: no longer has a valid SQLite header (was a database in the last known-good vault)")
                continue

        if path.suffix in ENCRYPTED_DB_EXTENSIONS:
            ok, detail = _check_page_alignment(path)
            if not ok:
                problems.append(f"{relative}: {detail}")

    return problems


def _check_page_alignment(path: Path, page_size: int = SQLCIPHER_PAGE_SIZE) -> tuple[bool, str]:
    """Weaker than PRAGMA integrity_check, but works without the decryption key,
    which this tool must never have or ask for. SQLCipher organizes data in
    fixed-size pages, so a genuine encrypted database's file size is always an
    exact multiple of the page size; a corrupted or truncated write landing
    exactly on a page boundary by chance is very unlikely."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, str(exc)
    if size == 0:
        return False, "zero-byte encrypted database file"
    if size % page_size != 0:
        return False, f"size {size} is not a multiple of the {page_size}-byte page size (possible truncation/corruption)"
    return True, "page-aligned"


def _sqlite_integrity_check_file(path: Path) -> tuple[bool, str]:
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute("PRAGMA integrity_check;").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, str(exc)
    result_text = rows[0][0] if rows else ""
    if result_text.lower() != "ok":
        return False, result_text
    return True, "ok"


def _snapshot_stats(root: Path) -> tuple[int, int]:
    count = 0
    total_size = 0
    for path in root.rglob("*"):
        if path.is_file():
            count += 1
            total_size += path.stat().st_size
    return count, total_size


def _find_newly_truncated(staging_path: Path, last_good_path: Path) -> list[str]:
    flagged = []
    for path in staging_path.rglob("*"):
        if not path.is_file() or path.stat().st_size != 0:
            continue
        previous = last_good_path / path.relative_to(staging_path)
        if previous.is_file() and previous.stat().st_size > 0:
            flagged.append(str(path.relative_to(staging_path)))
    return flagged
