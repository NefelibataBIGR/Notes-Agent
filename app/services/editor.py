from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.models import EditPreview


@dataclass
class EditCommand:
    action: str
    file_token: str
    old_text: str = ""
    new_text: str = ""
    replace_all: bool = False


class NoteEditor:
    def __init__(self, notes_root: Path, backup_dir: Path) -> None:
        self.notes_root = notes_root.resolve()
        self.backup_dir = backup_dir.resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def parse_instruction(self, instruction: str) -> EditCommand:
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("修改指令为空")

        file_token = self._extract_file_token(normalized)
        quoted = self._extract_quoted_texts(normalized)
        replace_all = any(flag in normalized for flag in ("全部", "所有", "all"))

        if "追加" in normalized:
            if len(quoted) < 1:
                # fallback: 例如 “在 xxx.md 末尾追加：新的内容”
                m = re.search(r"(?:追加|添加|新增)[:：]?\s*(.+)$", normalized)
                if m:
                    return EditCommand(action="append", file_token=file_token, new_text=m.group(1).strip())
                raise ValueError("追加操作需要至少一段引用文本")
            return EditCommand(action="append", file_token=file_token, new_text=quoted[-1])

        if any(x in normalized for x in ("替换", "改成", "改为", "replace")):
            if len(quoted) < 2:
                # fallback: 例如 “把 A 替换为 B”
                m = re.search(r"(?:把|将)?\s*(.+?)\s*(?:替换为|替换成|改为|改成)\s*(.+)", normalized)
                if m:
                    old_text = m.group(1).strip()
                    new_text = m.group(2).strip()
                    if old_text and new_text and old_text != new_text:
                        return EditCommand(
                            action="replace",
                            file_token=file_token,
                            old_text=old_text,
                            new_text=new_text,
                            replace_all=replace_all,
                        )
                raise ValueError("替换操作需要两段可识别的文本（建议用引号包裹）")
            return EditCommand(
                action="replace",
                file_token=file_token,
                old_text=quoted[0],
                new_text=quoted[1],
                replace_all=replace_all,
            )

        if any(x in normalized for x in ("删除", "删掉", "去掉")):
            if len(quoted) >= 1:
                return EditCommand(
                    action="delete",
                    file_token=file_token,
                    old_text=quoted[0],
                    new_text="",
                    replace_all=replace_all,
                )
            m = re.search(r"(?:删除|删掉|去掉)[:：]?\s*(.+)$", normalized)
            if m:
                old_text = m.group(1).strip()
                if old_text:
                    return EditCommand(
                        action="delete",
                        file_token=file_token,
                        old_text=old_text,
                        new_text="",
                        replace_all=replace_all,
                    )
            raise ValueError("删除操作需要可识别文本（建议用引号包裹）")

        raise ValueError("暂不支持该指令，请使用“替换/改成/追加”格式")

    def preview(self, instruction: str) -> EditPreview:
        command = self.parse_instruction(instruction)
        return self.preview_from_command(command)

    def preview_from_command(self, command: EditCommand) -> EditPreview:
        target = self.resolve_file_path(command.file_token)
        original_text = self._read_text(target)
        hit_count = 0

        if command.action == "replace":
            if command.old_text not in original_text:
                raise ValueError("未在目标文件中找到待替换文本")
            hit_count = original_text.count(command.old_text)
            count = -1 if command.replace_all else 1
            new_text = original_text.replace(command.old_text, command.new_text, count)
        elif command.action == "append":
            suffix = command.new_text
            hit_count = 1
            if not original_text.endswith("\n"):
                new_text = original_text + "\n" + suffix + "\n"
            else:
                new_text = original_text + suffix + "\n"
        elif command.action == "delete":
            if command.old_text not in original_text:
                raise ValueError("未在目标文件中找到待删除文本")
            hit_count = original_text.count(command.old_text)
            count = -1 if command.replace_all else 1
            new_text = original_text.replace(command.old_text, "", count)
        else:
            raise ValueError("不支持的操作")

        if new_text == original_text:
            raise ValueError("修改后内容未发生变化")

        diff = difflib.unified_diff(
            original_text.splitlines(),
            new_text.splitlines(),
            fromfile=str(target),
            tofile=str(target),
            lineterm="",
        )
        backup_path = self._build_backup_path(target)
        intent_text = self._build_intent_text(command, target, hit_count)
        return EditPreview(
            file_path=str(target),
            backup_path=str(backup_path),
            diff_text="\n".join(diff),
            new_text=new_text,
            intent_text=intent_text,
        )

    def _build_intent_text(self, command: EditCommand, target: Path, hit_count: int) -> str:
        action_map = {
            "replace": "替换文本",
            "append": "末尾追加",
            "delete": "删除文本",
        }
        action_name = action_map.get(command.action, command.action)
        lines = [
            f"目标文件: {target}",
            f"动作类型: {action_name}",
            f"命中次数: {hit_count}",
            f"作用范围: {'全部匹配' if command.replace_all else '首次匹配'}",
        ]
        if command.old_text:
            lines.append(f"旧文本预览: {self._shorten(command.old_text)}")
        if command.new_text:
            lines.append(f"新文本预览: {self._shorten(command.new_text)}")
        return "\n".join(lines)

    @staticmethod
    def _shorten(text: str, limit: int = 90) -> str:
        s = text.replace("\n", " ").strip()
        if len(s) <= limit:
            return s
        return s[:limit] + "..."

    def apply_preview(self, preview: EditPreview, backup_enabled: bool = True) -> str:
        target = Path(preview.file_path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {target}")
        backup = Path(preview.backup_path)
        raw_bytes = target.read_bytes()
        backup_path_str = ""
        if backup_enabled:
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(raw_bytes)
            backup_path_str = str(backup)

        original = self._read_text(target)
        encoding = "utf-8"
        if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
            encoding = "utf-16"
        target.write_text(preview.new_text, encoding=encoding)
        return backup_path_str

    def resolve_file_path(self, file_token: str) -> Path:
        token = (
            file_token.strip()
            .strip('"')
            .strip("'")
            .strip("\u201c")
            .strip("\u201d")
        )
        if not token:
            raise ValueError("请在指令中指定目标文件")

        candidate = Path(token)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            self._ensure_in_notes_root(resolved)
            if not resolved.exists():
                raise FileNotFoundError(f"目标文件不存在: {resolved}")
            return resolved

        direct = (self.notes_root / candidate).resolve()
        if direct.exists():
            self._ensure_in_notes_root(direct)
            return direct

        matches = [p for p in self.notes_root.rglob(candidate.name) if p.is_file()]
        if len(matches) == 1:
            return matches[0].resolve()
        if not matches:
            raise FileNotFoundError(f"未找到文件: {token}")
        raise ValueError(f"匹配到多个同名文件，请使用更完整路径: {token}")

    def _ensure_in_notes_root(self, path: Path) -> None:
        try:
            path.relative_to(self.notes_root)
        except ValueError as exc:
            raise ValueError("只允许修改笔记目录内的文件") from exc

    def _build_backup_path(self, target: Path) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = target.name.replace(" ", "_")
        return self.backup_dir / f"{safe_name}.{timestamp}.bak"

    @staticmethod
    def _extract_quoted_texts(text: str) -> list[str]:
        matches = re.findall(r"[\"'\u201c\u201d]([^\"'\u201c\u201d]+)[\"'\u201c\u201d]", text)
        return [m.strip() for m in matches if m.strip()]

    @staticmethod
    def _extract_file_token(text: str) -> str:
        path_pattern = r"([A-Za-z]:\\[^\s\"“”]+\.(?:md|txt)|[^\s\"“”]+\.(?:md|txt))"
        match = re.search(path_pattern, text, re.IGNORECASE)
        if not match:
            return ""
        return match.group(1)

    @staticmethod
    def _read_text(path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")
