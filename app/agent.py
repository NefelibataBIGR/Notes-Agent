from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from app.config import AppConfig
from app.models import EditPreview
from app.services.editor import EditCommand, NoteEditor
from app.services.indexer import NotesIndexer
from app.services.llm_client import OpenAICompatibleClient
from app.services.settings import AppSettings, SettingsStore
from app.services.watcher import NotesWatcher


class NoteAgent:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.build_default()
        self.settings_store = SettingsStore(self.config.settings_path)
        self.settings = self.settings_store.load()

        self.notes_root = self._resolve_notes_root(self.settings.notes_root_dir)
        self.index_dir = self._resolve_index_dir(self.settings.vector_index_dir)
        self.settings.notes_root_dir = str(self.notes_root)
        self.settings.vector_index_dir = str(self.index_dir)
        self.settings_store.save(self.settings)
        self._index_lock = threading.RLock()
        self._init_services(self.notes_root, self.index_dir)

    def _resolve_notes_root(self, path_text: str) -> Path:
        if path_text and path_text.strip():
            candidate = Path(path_text.strip()).expanduser().resolve()
            if candidate.exists() and candidate.is_dir():
                return candidate
        return self.config.root_notes_dir.resolve()

    def _resolve_index_dir(self, path_text: str) -> Path:
        default_dir = self.config.db_path.parent.resolve()
        if path_text and path_text.strip():
            candidate = Path(path_text.strip()).expanduser().resolve()
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError:
                candidate = None
            if candidate is not None and candidate.exists() and candidate.is_dir():
                return candidate
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    def _init_services(self, notes_root: Path, index_dir: Path) -> None:
        self.notes_root = notes_root.resolve()
        self.index_dir = index_dir.resolve()
        self.indexer = NotesIndexer(
            db_path=self.index_dir / self.config.db_path.name,
            notes_root=self.notes_root,
            app_dir=self.config.app_dir,
            supported_suffixes=self.config.supported_suffixes,
        )
        self.editor = NoteEditor(
            notes_root=self.notes_root,
            backup_dir=self.config.backup_dir,
        )
        self.watcher = NotesWatcher(
            notes_root=self.notes_root,
            app_dir=self.config.app_dir,
            supported_suffixes=self.config.supported_suffixes,
            on_change=self._on_file_changed,
            on_delete=self._on_file_deleted,
        )

    def _reinit_services(self, notes_root: Path, index_dir: Path) -> None:
        try:
            if hasattr(self, "watcher"):
                self.watcher.stop()
        except Exception:
            pass
        self._init_services(notes_root, index_dir)

    def get_settings(self) -> AppSettings:
        return self.settings

    def update_settings(self, settings: AppSettings) -> None:
        settings.top_k = max(1, min(20, int(settings.top_k)))
        new_root = self._resolve_notes_root(settings.notes_root_dir)
        new_index_dir = self._resolve_index_dir(settings.vector_index_dir)
        old_root = self.notes_root
        old_index_dir = self.index_dir
        settings.notes_root_dir = str(new_root)
        settings.vector_index_dir = str(new_index_dir)

        self.settings = settings
        self.settings_store.save(settings)

        if new_root != old_root or new_index_dir != old_index_dir:
            self._reinit_services(new_root, new_index_dir)

    def build_full_index(self, progress_callback=None, cancel_callback=None) -> dict[str, int]:
        embedder, embedder_key = self._build_embedder()
        with self._index_lock:
            return self.indexer.build_full_index(
                embedder=embedder,
                embedder_key=embedder_key,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

    def incremental_sync(self, progress_callback=None, cancel_callback=None) -> dict[str, int]:
        embedder, embedder_key = self._build_embedder()
        with self._index_lock:
            return self.indexer.incremental_sync(
                embedder=embedder,
                embedder_key=embedder_key,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

    def get_stats(self) -> dict[str, int]:
        return self.indexer.get_stats()

    def ask(self, question: str, progress_callback=None) -> dict[str, object]:
        q = question.strip()
        if not q:
            raise ValueError("问题不能为空")
        if progress_callback is not None:
            progress_callback(2, "准备问答")

        try:
            client = self._build_client_if_enabled()
        except ValueError as exc:
            if self.settings.use_llm_rag:
                raise ValueError(
                    "已启用 LLM+RAG，但配置不完整。请在“设置”中填写 API Key/模型名，"
                    "或关闭 LLM 模式后重试。"
                ) from exc
            raise
        if progress_callback is not None:
            progress_callback(12, "加载模型配置")
        query_embedding: list[float] | None = None
        if client is not None:
            if progress_callback is not None:
                progress_callback(28, "生成问题向量")
            query_embedding = client.embedding(self.settings.embedding_model, q)

        if progress_callback is not None:
            progress_callback(46, "检索相关笔记片段")
        results = self.indexer.search(q, limit=self.settings.top_k, query_embedding=query_embedding)
        if not results:
            if progress_callback is not None:
                progress_callback(100, "未检索到相关内容")
            return {
                "answer": "没有在已索引笔记中检索到相关内容。请先重建索引，或换一种提问方式。",
                "sources": [],
            }

        sources = [
            {
                "file": item.file_path,
                "heading": self._resolve_item_heading(
                    item.heading_path,
                    item.content,
                    query_text=q,
                    file_path=item.file_path,
                    line_start=item.line_start,
                ),
                "line_start": item.line_start,
                "line_end": item.line_end,
                "score": round(item.score, 4),
            }
            for item in results
        ]

        if client is None:
            if progress_callback is not None:
                progress_callback(82, "整理检索结果")
            answer = self._fallback_answer(results)
            if progress_callback is not None:
                progress_callback(100, "回答完成")
            return {"answer": answer, "sources": sources}

        if progress_callback is not None:
            progress_callback(72, "调用大模型生成回答")
        answer = self._llm_answer(client, q, results)
        if progress_callback is not None:
            progress_callback(100, "回答完成")
        return {"answer": answer, "sources": sources}

    def preview_edit(self, instruction: str) -> EditPreview:
        try:
            return self.editor.preview(instruction)
        except Exception as exc:
            client = self._build_client_if_enabled()
            if client is None:
                raise ValueError(
                    "当前本地规则无法解析该自然语言修改指令。请改写为包含文件名和明确操作（替换/追加/删除），"
                    "或启用 LLM+RAG 后再试。"
                ) from exc
            cmd = self._llm_parse_edit_command(client, instruction)
            return self.editor.preview_from_command(cmd)

    def apply_edit(self, preview: EditPreview, backup_enabled: bool | None = None) -> str:
        if backup_enabled is None:
            backup_enabled = self.settings.backup_mode != "never"
        backup = self.editor.apply_preview(preview, backup_enabled=bool(backup_enabled))
        embedder, embedder_key = self._build_embedder()
        with self._index_lock:
            self.indexer.index_file(Path(preview.file_path), embedder=embedder, embedder_key=embedder_key)
        return backup

    def test_connection(self) -> dict[str, str]:
        client = self._build_client_if_enabled()
        if client is None:
            raise ValueError("当前未启用 LLM+RAG")
        content = client.chat(
            model=self.settings.chat_model,
            messages=[
                {"role": "system", "content": "你是连通性检测助手。只输出 OK。"},
                {"role": "user", "content": "只回复 OK。"},
            ],
            temperature=0,
        )
        return {"model": self.settings.chat_model, "message": content.strip()}

    def start_watcher(self) -> None:
        self.watcher.start()

    def stop_watcher(self) -> None:
        self.watcher.stop()

    def watcher_running(self) -> bool:
        return self.watcher.is_running()

    def get_index_scope_info(self) -> dict[str, object]:
        return self.indexer.get_scope_info()

    def _on_file_changed(self, path: Path) -> None:
        try:
            embedder, embedder_key = self._build_embedder()
            with self._index_lock:
                self.indexer.index_file(path, embedder=embedder, embedder_key=embedder_key)
        except Exception:
            pass

    def _on_file_deleted(self, path: Path) -> None:
        try:
            with self._index_lock:
                self.indexer.remove_file(path)
        except Exception:
            pass

    def _build_client_if_enabled(self) -> OpenAICompatibleClient | None:
        if not self.settings.use_llm_rag:
            return None
        if not self.settings.api_key.strip():
            raise ValueError("已启用 LLM+RAG，但未填写 API Key")
        if not self.settings.chat_model.strip() or not self.settings.embedding_model.strip():
            raise ValueError("已启用 LLM+RAG，但模型名未填写")
        return OpenAICompatibleClient(
            base_url=self.settings.api_base_url,
            api_key=self.settings.api_key,
        )

    def _build_embedder(self) -> tuple[callable | None, str]:
        client = self._build_client_if_enabled()
        if client is None:
            return None, ""

        model = self.settings.embedding_model.strip()
        provider = self.settings.api_base_url.strip()
        embedder_key = f"{provider}|{model}"

        def _embed(text: str) -> list[float]:
            return client.embedding(model, text)

        return _embed, embedder_key

    @staticmethod
    def _fallback_answer(results) -> str:
        answer_lines = ["当前未启用 LLM，以下是检索到的高相关片段："]
        for idx, item in enumerate(results[:3], start=1):
            snippet = item.content.replace("\n", " ").strip()
            if len(snippet) > 180:
                snippet = snippet[:180] + "..."
            answer_lines.append(f"{idx}. {snippet}")
        answer_lines.append("可在“设置”页启用 LLM+RAG 获得语义问答。")
        return "\n".join(answer_lines)

    def _llm_answer(self, client: OpenAICompatibleClient, question: str, results) -> str:
        query_years = re.findall(r"\d{3,4}", question)
        year_hits: list[str] = []
        for y in query_years:
            if any((y in item.content) or (y in (item.heading_path or "")) for item in results):
                year_hits.append(y)

        context_lines: list[str] = []
        for i, item in enumerate(results[: min(8, len(results))], start=1):
            heading = self._resolve_item_heading(
                item.heading_path,
                item.content,
                query_text=question,
                file_path=item.file_path,
                line_start=item.line_start,
            )
            context_lines.append(
                f"[片段{i}] 文件: {item.file_path} 标题: {heading} 行: {item.line_start}-{item.line_end}\n{item.content}"
            )

        context = "\n\n".join(context_lines)
        system = (
            "你是一个笔记问答助手。必须优先依据提供的笔记片段回答，不要编造。"
            "如果信息不足，明确说明‘笔记中未覆盖’并给出已知范围。"
            "回答使用中文，先给结论，再给要点。"
        )
        guard = ""
        if year_hits:
            guard = (
                f"\n严格规则：片段中已出现年份 {', '.join(year_hits)}。"
                "禁止回答“该年份未覆盖/未出现”，必须基于片段直接概括该年份内容。"
            )
        user = f"用户问题:\n{question}{guard}\n\n可用笔记片段:\n{context}"

        content = client.chat(
            model=self.settings.chat_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return content

    def _llm_parse_edit_command(self, client: OpenAICompatibleClient, instruction: str) -> EditCommand:
        system = "你是笔记编辑指令解析器。将自然语言解析为 JSON，只输出 JSON。"
        user = (
            "输出 JSON: "
            "{\"action\":\"replace|append|delete\",\"file\":\"...md\",\"old_text\":\"...\",\"new_text\":\"...\",\"replace_all\":true/false}"
            f"\n指令: {instruction}"
        )
        raw = client.chat(
            model=self.settings.chat_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        data = self._extract_json(raw)
        action = str(data.get("action", "")).strip().lower()
        file_token = str(data.get("file", "")).strip()
        old_text = str(data.get("old_text", ""))
        new_text = str(data.get("new_text", ""))
        replace_all = bool(data.get("replace_all", False))

        if action not in {"replace", "append", "delete"}:
            raise ValueError(f"LLM 未返回可用 action: {action}")
        if not file_token:
            raise ValueError("LLM 未解析出目标文件")
        if action in {"replace", "delete"} and not old_text:
            raise ValueError("LLM 未解析出 old_text")
        if action == "append" and not new_text:
            raise ValueError("LLM 未解析出 new_text")

        return EditCommand(
            action=action,
            file_token=file_token,
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
        )

    @staticmethod
    def _extract_json(raw: str) -> dict:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("LLM 返回的 JSON 不是对象")
        return data

    @staticmethod
    def _resolve_item_heading(
        heading_path: str,
        content: str,
        query_text: str = "",
        file_path: str = "",
        line_start: int = 1,
    ) -> str:
        query_years = set(re.findall(r"\d{3,4}", query_text or ""))
        content_headings: list[str] = []
        for line in content.splitlines():
            m = re.match(r"^\[H[1-6]\]\s+(.*)$", line.strip())
            if m:
                value = m.group(1).strip()
                if value:
                    content_headings.append(value)
        if query_years and content_headings:
            for heading in content_headings:
                if any(y in heading for y in query_years):
                    return heading
        if heading_path and heading_path.strip():
            if query_years and any(y in heading_path for y in query_years):
                return heading_path.strip()
            if not content_headings:
                return heading_path.strip()
        if content_headings:
            return content_headings[0]
        if file_path:
            inferred = NoteAgent._infer_heading_from_file(file_path, line_start)
            if inferred:
                return inferred
        return "(未识别标题)"

    @staticmethod
    def _infer_heading_from_file(file_path: str, line_start: int) -> str:
        path = Path(file_path)
        if not path.exists():
            return ""
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                raw = path.read_text(encoding="gb18030", errors="ignore")
        lines = raw.splitlines()
        end = max(0, min(len(lines), line_start - 1))
        stack: list[tuple[int, str]] = []
        for idx in range(end):
            m = re.match(r"^(#{1,6})\s+(.*)$", lines[idx].rstrip())
            if not m:
                continue
            level = len(m.group(1))
            title = m.group(2).strip()
            if not title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        if not stack:
            return ""
        return " > ".join(item[1] for item in stack)
