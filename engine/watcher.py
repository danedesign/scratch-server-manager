from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

EventCallback = Callable[[str, Path], None]


class FolderWatcher:
    def __init__(self, path: Path, on_event: EventCallback, recursive: bool = True):
        self.path = Path(path)
        self._on_event = on_event
        self._recursive = recursive
        self._observer = Observer()

    def start(self) -> None:
        handler = _Handler(self._on_event)
        self._observer.schedule(handler, str(self.path), recursive=self._recursive)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()


class _Handler(FileSystemEventHandler):
    def __init__(self, on_event: EventCallback):
        self._on_event = on_event

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_event("created", Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_event("modified", Path(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_event("deleted", Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_event("moved", Path(event.dest_path))
