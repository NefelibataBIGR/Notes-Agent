from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievalResult:
    chunk_id: int
    file_path: str
    line_start: int
    line_end: int
    content: str
    score: float
    heading_path: str = ""


@dataclass
class EditPreview:
    file_path: str
    backup_path: str
    diff_text: str
    new_text: str
    intent_text: str = ""
