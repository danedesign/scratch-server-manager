import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SQLITE_HEADER = b"SQLite format 3\x00"


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
    """Runs PRAGMA integrity_check on every file that currently looks like SQLite.
    Also catches the case a header-sniffing check would otherwise miss: a file that
    WAS a valid SQLite database in last_good_path but no longer has a valid header in
    root (e.g. its header got corrupted/truncated) - that's flagged, not silently
    treated as "not a database, nothing to check"."""
    problems = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _is_sqlite_file(path):
            ok, detail = _sqlite_integrity_check_file(path)
            if not ok:
                problems.append(f"{relative}: {detail}")
        elif last_good_path is not None:
            previous = last_good_path / relative
            if previous.is_file() and _is_sqlite_file(previous):
                problems.append(f"{relative}: no longer has a valid SQLite header (was a database in the last known-good vault)")
    return problems


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
