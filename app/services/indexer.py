from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from app.models import RetrievalResult


class IndexingCancelled(Exception):
    pass


class NotesIndexer:
    def __init__(self, db_path: Path, notes_root: Path, app_dir: Path, supported_suffixes: tuple[str, ...]) -> None:
        self.index_path = db_path
        self.notes_root = notes_root.resolve()
        self.app_dir = app_dir
        self.supported_suffixes = supported_suffixes
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._ensure_scope_consistent()

    def build_full_index(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        embedder_key: str = "",
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        snapshot_state = copy.deepcopy(self._state)
        files = list(self._iter_note_files())
        indexed_count = 0
        total = len(files)

        if progress_callback is not None:
            progress_callback(0, total, "准备开始")

        try:
            if embedder_key and self._state.get("embedding_provider") != embedder_key:
                self._state["chunks"] = []
                self._state["files"] = {}
                self._state["next_chunk_id"] = 1
                self._state["embedding_provider"] = embedder_key

            active = {str(p.resolve()) for p in files}
            stale_paths = [path for path in self._state["files"].keys() if path not in active]
            for path in stale_paths:
                self._raise_if_cancelled(cancel_callback)
                self._remove_file_internal(path)

            for idx, file_path in enumerate(files, start=1):
                self._raise_if_cancelled(cancel_callback)
                changed = self.index_file(
                    file_path,
                    embedder=embedder,
                    embedder_key=embedder_key,
                    force=True,
                    autosave=False,
                    cancel_callback=cancel_callback,
                )
                if changed:
                    indexed_count += 1
                if progress_callback is not None:
                    progress_callback(idx, total, str(file_path))

            self._save_state()
            return {
                "files_seen": len(files),
                "files_reindexed": indexed_count,
                "chunks_total": len(self._state["chunks"]),
            }
        except Exception:
            self._state = snapshot_state
            self._save_state()
            raise

    def incremental_sync(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        embedder_key: str = "",
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        snapshot_state = copy.deepcopy(self._state)
        files = list(self._iter_note_files())
        active = {str(p.resolve()) for p in files}

        if embedder_key and self._state.get("embedding_provider") != embedder_key:
            return self.build_full_index(
                embedder=embedder,
                embedder_key=embedder_key,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if progress_callback is not None:
            progress_callback(0, len(files), "准备开始")

        try:
            reindexed = 0
            added = 0
            for idx, file_path in enumerate(files, start=1):
                self._raise_if_cancelled(cancel_callback)
                key = str(file_path.resolve())
                existed = key in self._state["files"]
                if self._is_changed(file_path):
                    self.index_file(
                        file_path,
                        embedder=embedder,
                        embedder_key=embedder_key,
                        autosave=False,
                        cancel_callback=cancel_callback,
                    )
                    reindexed += 1
                    if not existed:
                        added += 1
                if progress_callback is not None:
                    progress_callback(idx, len(files), str(file_path))

            removed = 0
            stale_paths = [path for path in self._state["files"].keys() if path not in active]
            for path in stale_paths:
                self._raise_if_cancelled(cancel_callback)
                self._remove_file_internal(path)
                removed += 1

            self._save_state()
            return {
                "files_added": added,
                "files_reindexed": max(0, reindexed - added),
                "files_removed": removed,
            }
        except Exception:
            self._state = snapshot_state
            self._save_state()
            raise

    def index_file(
        self,
        file_path: Path,
        embedder: Callable[[str], list[float]] | None = None,
        embedder_key: str = "",
        force: bool = False,
        autosave: bool = True,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> bool:
        file_path = file_path.resolve()
        if not file_path.exists() or not file_path.is_file():
            return False
        if file_path.suffix.lower() not in self.supported_suffixes:
            return False
        if self._is_under_app_dir(file_path):
            return False

        mtime = file_path.stat().st_mtime
        sha256 = self._hash_file(file_path)
        key = str(file_path)
        current_meta = self._state["files"].get(key)

        if (not force) and current_meta and current_meta["mtime"] == mtime and current_meta["sha256"] == sha256:
            return False

        if embedder_key:
            self._state["embedding_provider"] = embedder_key

        self._raise_if_cancelled(cancel_callback)
        text = self._read_text(file_path)
        text = self._preprocess_text(file_path, text)
        chunks = self._chunk_text(text)

        base_id = self._state["next_chunk_id"]
        new_records: list[dict] = []
        for i, chunk in enumerate(chunks):
            self._raise_if_cancelled(cancel_callback)
            record = {
                "id": base_id + i,
                "file_path": key,
                "chunk_index": chunk["chunk_index"],
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "content": chunk["content"],
                "heading_path": chunk.get("heading_path", ""),
                "embedding": None,
            }
            if embedder is not None:
                record["embedding"] = embedder(chunk["content"])
            new_records.append(record)

        self._raise_if_cancelled(cancel_callback)
        self._remove_file_internal(key)
        self._state["chunks"].extend(new_records)
        self._state["next_chunk_id"] = base_id + len(chunks)
        self._state["files"][key] = {
            "mtime": mtime,
            "sha256": sha256,
            "indexed_at": datetime.utcnow().isoformat(),
        }
        if autosave:
            self._save_state()
        return True

    def remove_file(self, file_path: Path) -> bool:
        key = str(file_path.resolve())
        existed = key in self._state["files"]
        self._remove_file_internal(key)
        self._save_state()
        return existed

    def search(
        self,
        question: str,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[RetrievalResult]:
        tokens = self._tokenize(question)
        query_years = re.findall(r"\d{3,4}", question)
        total_docs = max(1, len(self._state["chunks"]))
        idf = self._compute_idf(tokens, total_docs) if tokens else {}
        scored: list[tuple[float, dict]] = []

        for chunk in self._state["chunks"]:
            lexical_score = self._lexical_score(tokens, idf, chunk["content"]) if tokens else 0.0
            vector_score = 0.0
            if query_embedding is not None and isinstance(chunk.get("embedding"), list):
                vector_score = self._cosine_similarity(query_embedding, chunk["embedding"])

            if lexical_score <= 0 and vector_score <= 0:
                continue

            # 混合检索：词法匹配保证可控，向量匹配补充语义召回
            combined_score = lexical_score * 0.45 + vector_score * 0.55
            year_hit = self._year_hit_count(query_years, chunk)
            if year_hit > 0:
                # 年份精确命中时显著加权，避免被语义噪声压制
                combined_score += 6.0 + year_hit * 2.0
            scored.append((combined_score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]
        return [
            RetrievalResult(
                chunk_id=item["id"],
                file_path=item["file_path"],
                line_start=item["line_start"],
                line_end=item["line_end"],
                content=item["content"],
                score=score,
                heading_path=item.get("heading_path", ""),
            )
            for score, item in top
        ]

    @staticmethod
    def _year_hit_count(query_years: list[str], chunk: dict) -> int:
        if not query_years:
            return 0
        content = str(chunk.get("content", ""))
        heading = str(chunk.get("heading_path", ""))
        hit = 0
        for y in query_years:
            if y and (y in content or y in heading):
                hit += 1
        return hit

    def get_stats(self) -> dict[str, int]:
        embedded_chunks = 0
        for chunk in self._state["chunks"]:
            if isinstance(chunk.get("embedding"), list):
                embedded_chunks += 1
        return {
            "files": len(self._state["files"]),
            "chunks": len(self._state["chunks"]),
            "embedded_chunks": embedded_chunks,
        }

    def list_indexed_files(self) -> list[str]:
        return sorted(self._state["files"].keys())

    def get_scope_info(self) -> dict[str, object]:
        return {
            "root": str(self.notes_root),
            "recursive": True,
            "suffixes": list(self.supported_suffixes),
        }

    def _remove_file_internal(self, key: str) -> None:
        self._state["files"].pop(key, None)
        self._state["chunks"] = [chunk for chunk in self._state["chunks"] if chunk["file_path"] != key]

    def _is_changed(self, file_path: Path) -> bool:
        key = str(file_path.resolve())
        meta = self._state["files"].get(key)
        if meta is None:
            return True
        if file_path.stat().st_mtime != meta["mtime"]:
            return True
        return self._hash_file(file_path) != meta["sha256"]

    def _load_state(self) -> dict:
        if not self.index_path.exists():
            return {
                "files": {},
                "chunks": [],
                "next_chunk_id": 1,
                "embedding_provider": "",
                "scope_root": "",
                "scope_suffixes": [],
            }
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("invalid state")
            data.setdefault("files", {})
            data.setdefault("chunks", [])
            data.setdefault("next_chunk_id", 1)
            data.setdefault("embedding_provider", "")
            data.setdefault("scope_root", "")
            data.setdefault("scope_suffixes", [])
            return data
        except Exception:
            return {
                "files": {},
                "chunks": [],
                "next_chunk_id": 1,
                "embedding_provider": "",
                "scope_root": "",
                "scope_suffixes": [],
            }

    def _save_state(self) -> None:
        self._state["scope_root"] = str(self.notes_root)
        self._state["scope_suffixes"] = list(self.supported_suffixes)
        self.index_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _raise_if_cancelled(cancel_callback: Callable[[], bool] | None = None) -> None:
        if cancel_callback is not None and bool(cancel_callback()):
            raise IndexingCancelled("索引任务已取消")

    def _ensure_scope_consistent(self) -> None:
        scope_root = str(self.notes_root)
        old_root = str(self._state.get("scope_root", ""))
        old_suffixes = tuple(self._state.get("scope_suffixes", []))
        if old_root and old_root != scope_root:
            self._state = {
                "files": {},
                "chunks": [],
                "next_chunk_id": 1,
                "embedding_provider": "",
                "scope_root": scope_root,
                "scope_suffixes": list(self.supported_suffixes),
            }
            self._save_state()
            return
        if old_suffixes and old_suffixes != self.supported_suffixes:
            self._state["files"] = {}
            self._state["chunks"] = []
            self._state["next_chunk_id"] = 1
            self._state["embedding_provider"] = ""
            self._state["scope_root"] = scope_root
            self._state["scope_suffixes"] = list(self.supported_suffixes)
            self._save_state()

    def _iter_note_files(self) -> Iterable[Path]:
        for path in self.notes_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.supported_suffixes:
                continue
            if self._is_under_app_dir(path):
                continue
            yield path.resolve()

    def _is_under_app_dir(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.app_dir.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _hash_file(file_path: Path) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _read_text(file_path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return file_path.read_text(encoding="utf-8", errors="ignore")

    def _preprocess_text(self, file_path: Path, text: str) -> str:
        suffix = file_path.suffix.lower()
        if suffix in (".md", ".markdown"):
            return self._preprocess_markdown(text)
        return text

    @staticmethod
    def _preprocess_markdown(text: str) -> str:
        lines = text.splitlines()
        out_lines: list[str] = []
        heading_stack: list[tuple[int, str]] = []
        in_code_block = False

        for raw in lines:
            line = raw.rstrip()
            striped = line.strip()

            # Keep fenced code block boundaries, avoid parsing headings inside code.
            if striped.startswith("```") or striped.startswith("~~~"):
                in_code_block = not in_code_block
                out_lines.append(line)
                continue

            if in_code_block:
                out_lines.append(line)
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                title = NotesIndexer._clean_md_inline(heading_match.group(2).strip())
                if not title:
                    continue
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
                breadcrumb = " > ".join(item[1] for item in heading_stack)
                out_lines.append(f"[H{level}] {breadcrumb}")
                continue

            cleaned = NotesIndexer._clean_md_inline(line)
            out_lines.append(cleaned)

        return "\n".join(out_lines)

    @staticmethod
    def _clean_md_inline(line: str) -> str:
        s = line
        s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)      # image alt text
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)        # markdown link text
        s = re.sub(r"<https?://[^>]+>", "", s)               # bare links in <>
        s = re.sub(r"`([^`]+)`", r"\1", s)                    # inline code
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)              # bold
        s = re.sub(r"\*([^*]+)\*", r"\1", s)                  # italic
        s = re.sub(r"__([^_]+)__", r"\1", s)                  # bold underscore
        s = re.sub(r"_([^_]+)_", r"\1", s)                    # italic underscore
        return s

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 700) -> list[dict[str, object]]:
        lines = text.splitlines()
        chunks: list[dict[str, object]] = []
        current: list[str] = []
        current_len = 0
        start_line = 1
        chunk_index = 0
        current_heading_path = ""
        chunk_heading_path = ""

        for idx, raw_line in enumerate(lines, start=1):
            line = raw_line.rstrip()
            heading_match = re.match(r"^\[H[1-6]\]\s+(.*)$", line)
            if heading_match:
                current_heading_path = heading_match.group(1).strip()
            if not current:
                start_line = idx
                chunk_heading_path = current_heading_path

            if line == "" and current:
                content = "\n".join(current).strip()
                if content:
                    chunks.append(
                        {
                            "chunk_index": chunk_index,
                            "line_start": start_line,
                            "line_end": idx - 1,
                            "content": content,
                            "heading_path": chunk_heading_path,
                        }
                    )
                    chunk_index += 1
                current = []
                current_len = 0
                continue

            projected = current_len + len(line) + 1
            if current and projected > max_chars:
                content = "\n".join(current).strip()
                if content:
                    chunks.append(
                        {
                            "chunk_index": chunk_index,
                            "line_start": start_line,
                            "line_end": idx - 1,
                            "content": content,
                            "heading_path": chunk_heading_path,
                        }
                    )
                    chunk_index += 1
                current = [line]
                current_len = len(line)
                start_line = idx
                chunk_heading_path = current_heading_path
            else:
                current.append(line)
                current_len = projected

        if current:
            content = "\n".join(current).strip()
            if content:
                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "line_start": start_line,
                        "line_end": len(lines),
                        "content": content,
                        "heading_path": chunk_heading_path,
                    }
                )

        if not chunks and text.strip():
            chunks.append(
                {
                    "chunk_index": 0,
                    "line_start": 1,
                    "line_end": max(1, len(lines)),
                    "content": text.strip(),
                    "heading_path": chunk_heading_path or current_heading_path,
                }
            )
        return chunks

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens: list[str] = []
        units = re.findall(r"[A-Za-z_]+|[0-9]+|[\u4e00-\u9fff]+", text)
        for unit in units:
            if re.fullmatch(r"[A-Za-z_]+", unit):
                low = unit.lower()
                if len(low) >= 2:
                    tokens.append(low)
                continue

            if re.fullmatch(r"[0-9]+", unit):
                if len(unit) >= 2:
                    tokens.append(unit)
                continue

            # Chinese sequence: keep phrase + overlapping bigrams to improve recall.
            if len(unit) >= 2:
                tokens.append(unit)
                for i in range(len(unit) - 1):
                    tokens.append(unit[i : i + 2])
            else:
                tokens.append(unit)
        return tokens

    @staticmethod
    def _lexical_score(tokens: list[str], idf: dict[str, float], content: str) -> float:
        if not tokens:
            return 0.0
        doc_tokens = NotesIndexer._tokenize(content)
        if not doc_tokens:
            return 0.0

        tf_map: dict[str, int] = {}
        for token in doc_tokens:
            tf_map[token] = tf_map.get(token, 0) + 1

        score = 0.0
        matched_terms = 0
        for token in tokens:
            tf = tf_map.get(token, 0)
            if tf > 0:
                matched_terms += 1
                score += (1.0 + math.log(1 + tf)) * idf.get(token, 1.0)

        if score <= 0:
            return 0.0
        return score + matched_terms * 0.35

    def _compute_idf(self, query_tokens: list[str], total_docs: int) -> dict[str, float]:
        idf: dict[str, float] = {}
        tokenized_chunks: list[set[str]] = []
        for chunk in self._state["chunks"]:
            tokenized_chunks.append(set(self._tokenize(chunk["content"])))

        for token in set(query_tokens):
            doc_freq = 0
            for token_set in tokenized_chunks:
                if token in token_set:
                    doc_freq += 1
            idf[token] = math.log((total_docs + 1) / (doc_freq + 1)) + 1.0
        return idf

    @staticmethod
    def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
        if len(v1) != len(v2) or not v1:
            return 0.0
        dot = 0.0
        n1 = 0.0
        n2 = 0.0
        for a, b in zip(v1, v2):
            dot += a * b
            n1 += a * a
            n2 += b * b
        if n1 <= 0 or n2 <= 0:
            return 0.0
        return dot / (math.sqrt(n1) * math.sqrt(n2))
