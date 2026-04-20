from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    root_notes_dir: Path
    app_dir: Path
    db_path: Path
    backup_dir: Path
    settings_path: Path
    supported_suffixes: tuple[str, ...] = (".md", ".markdown", ".txt")

    @classmethod
    def build_default(cls) -> "AppConfig":
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).resolve().parent
        else:
            app_dir = Path(__file__).resolve().parents[1]
        root_notes_dir = app_dir.parent
        data_dir = app_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            root_notes_dir=root_notes_dir,
            app_dir=app_dir,
            db_path=data_dir / "notes_index.json",
            backup_dir=backup_dir,
            settings_path=data_dir / "settings.json",
        )
