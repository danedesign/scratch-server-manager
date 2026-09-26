import shutil
import time
from pathlib import Path
from typing import Optional

from engine.checksum import compute_checksum
from engine.logger import get_logger
from engine.watcher import FolderWatcher


class HotDataProfile:
    """Watches, versions, and logs a folder. Does not move bytes between machines —
    cross-machine transport is delegated to Syncthing (or similar) watching the same path."""

    def __init__(self, path: Path, version_dir: Path, versions_to_keep: int = 5):
        self.path = Path(path).resolve()
        self.version_dir = Path(version_dir).resolve()
        if self.version_dir == self.path or self.version_dir in self.path.parents or self.path in self.version_dir.parents:
            raise ValueError("version_dir must not be inside the watched path (would cause recursive events)")
        self.versions_to_keep = versions_to_keep
        self._logger = get_logger()
        self._watcher = FolderWatcher(self.path, self._handle_event)
        self._last_checksum: dict[Path, str] = {}
        self.last_event_at: Optional[float] = None
        self.last_event_type: Optional[str] = None

    def start(self) -> None:
        self.version_dir.mkdir(parents=True, exist_ok=True)
        self._watcher.start()

    def stop(self) -> None:
        self._watcher.stop()

    def _handle_event(self, event_type: str, file_path: Path) -> None:
        self.last_event_at = time.time()
        self.last_event_type = event_type

        if event_type == "deleted":
            self._last_checksum.pop(file_path, None)
            self._logger.info("deleted %s (last version retained for rollback)", file_path)
            return

        checksum = compute_checksum(file_path)
        if checksum is None:
            self._logger.info("%s %s (unreadable, likely in-flight)", event_type, file_path)
            return

        self._logger.info("%s %s checksum=%s", event_type, file_path, checksum)

        # Windows (and some other backends) fire duplicate create+modify events for one
        # write; skip re-versioning content that hasn't actually changed since last snapshot.
        if self._last_checksum.get(file_path) == checksum:
            return
        self._last_checksum[file_path] = checksum
        self._snapshot(file_path)

    def _snapshot(self, file_path: Path) -> None:
        relative = file_path.resolve().relative_to(self.path)
        dest_dir = self.version_dir / relative.parent
        dest_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%dT%H%M%S")
        dest = dest_dir / f"{relative.name}.{timestamp}"
        shutil.copy2(file_path, dest)
        self._prune_versions(dest_dir, relative.name)

    def _prune_versions(self, dest_dir: Path, filename: str) -> None:
        versions = sorted(dest_dir.glob(f"{filename}.*"), key=lambda p: p.stat().st_mtime)
        excess = len(versions) - self.versions_to_keep
        if excess <= 0:
            return
        for old in versions[:excess]:
            old.unlink()
