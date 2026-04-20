from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    provider_id: str = "custom"
    notes_root_dir: str = ""
    vector_index_dir: str = ""
    backup_mode: str = "ask"
    use_llm_rag: bool = False
    api_base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    top_k: int = 6


class SettingsStore:
    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        if not self.settings_path.exists():
            return AppSettings()
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return AppSettings()
            defaults = asdict(AppSettings())
            defaults.update(data)
            settings = AppSettings(**defaults)
            settings.top_k = max(1, min(20, int(settings.top_k)))
            if settings.backup_mode not in {"ask", "always", "never"}:
                settings.backup_mode = "ask"
            return settings
        except Exception:
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.settings_path.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
