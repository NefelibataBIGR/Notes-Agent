from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _NotesEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        notes_root: Path,
        supported_suffixes: tuple[str, ...],
        app_dir: Path,
        on_change: Callable[[Path], None],
        on_delete: Callable[[Path], None],
    ) -> None:
        super().__init__()
        self.notes_root = notes_root.resolve()
        self.supported_suffixes = supported_suffixes
        self.app_dir = app_dir.resolve()
        self.on_change = on_change
        self.on_delete = on_delete

    def _accept(self, src_path: str) -> Path | None:
        path = Path(src_path).resolve()
        if path.suffix.lower() not in self.supported_suffixes:
            return None
        try:
            path.relative_to(self.app_dir)
            return None
        except ValueError:
            pass
        return path

    def on_created(self, event):
        if event.is_directory:
            return
        path = self._accept(event.src_path)
        if path:
            self.on_change(path)

    def on_modified(self, event):
        if event.is_directory:
            return
        path = self._accept(event.src_path)
        if path:
            self.on_change(path)

    def on_moved(self, event):
        if event.is_directory:
            return
        src = self._accept(event.src_path)
        if src:
            self.on_delete(src)
        dst = self._accept(event.dest_path)
        if dst:
            self.on_change(dst)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = self._accept(event.src_path)
        if path:
            self.on_delete(path)


class NotesWatcher:
    def __init__(
        self,
        notes_root: Path,
        app_dir: Path,
        supported_suffixes: tuple[str, ...],
        on_change: Callable[[Path], None],
        on_delete: Callable[[Path], None],
    ) -> None:
        self.notes_root = notes_root
        self.observer: Observer | None = None
        self._lock = threading.Lock()
        self.handler = _NotesEventHandler(
            notes_root=notes_root,
            supported_suffixes=supported_suffixes,
            app_dir=app_dir,
            on_change=on_change,
            on_delete=on_delete,
        )

    def start(self) -> None:
        with self._lock:
            if self.observer and self.observer.is_alive():
                return
            self.observer = Observer()
            self.observer.schedule(self.handler, str(self.notes_root), recursive=True)
            self.observer.start()

    def stop(self) -> None:
        with self._lock:
            if not self.observer:
                return
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None

    def is_running(self) -> bool:
        return bool(self.observer and self.observer.is_alive())
