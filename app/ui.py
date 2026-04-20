from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import webbrowser
import os
import queue
import threading
import re

from app.agent import NoteAgent
from app.models import EditPreview
from app.services.indexer import IndexingCancelled
from app.services.providers import PROVIDER_PRESETS, get_provider_by_id
from app.services.settings import AppSettings


class MainWindow:
    def __init__(self, root: tk.Tk, agent: NoteAgent) -> None:
        self.root = root
        self.agent = agent
        self.pending_preview: EditPreview | None = None
        self.current_page = "qa"
        self._reindex_running = False
        self._reindex_cancel_event: threading.Event | None = None
        self._active_index_task: str | None = None
        self._watcher_transition = False
        self._watcher_transition_action = ""
        self._watcher_events: queue.Queue = queue.Queue()
        self._watcher_polling = False
        self._hover_tip: tk.Toplevel | None = None
        self._index_progress_value = 0.0
        self._index_wave_offset = 0
        self._index_wave_job = None
        self._timeline_state = "idle"
        self._timeline_mode = ""
        self._timeline_detail = "等待任务"
        self.theme_mode = "day"
        self.palette = self._get_palette(self.theme_mode)

        self.root.title("Notes Agent Studio")
        self.root.geometry("1260x860")
        self.root.minsize(1120, 760)
        self.root.configure(bg=self.palette["app_bg"])
        self._apply_ttk_theme()

        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.provider_label_to_id = {preset.label: preset.id for preset in PROVIDER_PRESETS}
        self.provider_id_to_label = {preset.id: preset.label for preset in PROVIDER_PRESETS}

        self._build_layout()
        self._build_pages()

        self._load_settings_to_form()
        self._refresh_stats()
        self._show_page("qa")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _day_palette() -> dict[str, str]:
        return {
            "app_bg": "#f5f6f8",
            "sidebar_bg": "#eef1f5",
            "sidebar_divider": "#d8dfe8",
            "main_bg": "#f7f9fc",
            "header_bg": "#f7f9fc",
            "card_bg": "#ffffff",
            "card_border": "#d9e0ea",
            "text_primary": "#243447",
            "text_secondary": "#5d7087",
            "nav_idle_bg": "#eef1f5",
            "nav_idle_fg": "#4f6074",
            "nav_active_bg": "#2f6feb",
            "nav_active_fg": "#ffffff",
            "btn_primary_bg": "#2f6feb",
            "btn_primary_active": "#255fcb",
            "btn_primary_fg": "#ffffff",
            "btn_secondary_bg": "#e8edf5",
            "btn_secondary_active": "#dce4ef",
            "btn_secondary_fg": "#2e425a",
            "input_bg": "#ffffff",
            "info_bg": "#f3f6fa",
            "link_fg": "#1e66d0",
            "link_disabled_fg": "#8a99aa",
            "accent": "#4f7dd9",
        }

    @staticmethod
    def _night_palette() -> dict[str, str]:
        return {
            "app_bg": "#0c1118",
            "sidebar_bg": "#121923",
            "sidebar_divider": "#263142",
            "main_bg": "#0f1620",
            "header_bg": "#111b29",
            "card_bg": "#162233",
            "card_border": "#2a3a52",
            "text_primary": "#e3ecf9",
            "text_secondary": "#9cb0cb",
            "nav_idle_bg": "#121923",
            "nav_idle_fg": "#9fb3cf",
            "nav_active_bg": "#3b82f6",
            "nav_active_fg": "#ffffff",
            "btn_primary_bg": "#3b82f6",
            "btn_primary_active": "#2f6fda",
            "btn_primary_fg": "#ffffff",
            "btn_secondary_bg": "#223349",
            "btn_secondary_active": "#2b3f58",
            "btn_secondary_fg": "#d2def1",
            "input_bg": "#0f1a29",
            "info_bg": "#142032",
            "link_fg": "#76b3ff",
            "link_disabled_fg": "#6f819a",
            "accent": "#3b82f6",
        }

    def _get_palette(self, mode: str) -> dict[str, str]:
        return self._night_palette() if mode == "night" else self._day_palette()

    def _apply_ttk_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Youth.Horizontal.TProgressbar",
            troughcolor="#dde6f2",
            background=self.palette["btn_primary_bg"],
            bordercolor="#dde6f2",
            lightcolor=self.palette["btn_primary_bg"],
            darkcolor=self.palette["btn_primary_bg"],
            thickness=11,
        )
        style.configure(
            "Youth.TCombobox",
            fieldbackground=self.palette["input_bg"],
            background=self.palette["btn_secondary_bg"],
            foreground=self.palette["text_primary"],
            arrowcolor=self.palette["text_secondary"],
            bordercolor=self.palette["card_border"],
            lightcolor=self.palette["card_border"],
            darkcolor=self.palette["card_border"],
            padding=4,
        )

    def _make_button(
        self, parent: tk.Widget, text: str, command, primary: bool = False, compact: bool = False
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            bg=self.palette["btn_primary_bg"] if primary else self.palette["btn_secondary_bg"],
            fg=self.palette["btn_primary_fg"] if primary else self.palette["btn_secondary_fg"],
            activebackground=self.palette["btn_primary_active"] if primary else self.palette["btn_secondary_active"],
            activeforeground=self.palette["btn_primary_fg"] if primary else self.palette["btn_secondary_fg"],
            font=("Microsoft YaHei UI", 10, "bold" if primary else "normal"),
            padx=10 if compact else 12,
            pady=4 if compact else 6,
            cursor="hand2",
        )

    def _show_hover_tip(self, widget: tk.Widget, text: str) -> None:
        self._hide_hover_tip()
        if not text:
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        try:
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(
            tip,
            text=text,
            bg="#fff9db",
            fg="#3a2f00",
            relief="solid",
            bd=1,
            padx=6,
            pady=3,
            font=("Microsoft YaHei UI", 9),
        ).pack()
        tip.wm_geometry(f"+{widget.winfo_pointerx() + 14}+{widget.winfo_pointery() + 14}")
        self._hover_tip = tip

    def _move_hover_tip(self, widget: tk.Widget) -> None:
        if self._hover_tip is None:
            return
        self._hover_tip.wm_geometry(f"+{widget.winfo_pointerx() + 14}+{widget.winfo_pointery() + 14}")

    def _hide_hover_tip(self, _event=None) -> None:
        if self._hover_tip is None:
            return
        try:
            self._hover_tip.destroy()
        except tk.TclError:
            pass
        self._hover_tip = None

    def _bind_dynamic_tip(self, widget: tk.Widget, text_getter) -> None:
        widget.bind("<Enter>", lambda _e: self._show_hover_tip(widget, text_getter()))
        widget.bind("<Motion>", lambda _e: self._move_hover_tip(widget))
        widget.bind("<Leave>", self._hide_hover_tip)
        widget.bind("<Destroy>", self._hide_hover_tip)

    @staticmethod
    def _mix_hex(color: str, target: str, ratio: float) -> str:
        ratio = max(0.0, min(1.0, float(ratio)))
        c = color.lstrip("#")
        t = target.lstrip("#")
        if len(c) != 6 or len(t) != 6:
            return color
        cr, cg, cb = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        tr, tg, tb = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
        rr = int(cr + (tr - cr) * ratio)
        rg = int(cg + (tg - cg) * ratio)
        rb = int(cb + (tb - cb) * ratio)
        return f"#{rr:02x}{rg:02x}{rb:02x}"

    def _set_index_progress(self, value: float) -> None:
        self._index_progress_value = max(0.0, min(100.0, float(value)))
        self._draw_index_progress_bar()
        self._render_timeline_ops()

    def _draw_index_progress_bar(self) -> None:
        if not hasattr(self, "reindex_progress_canvas"):
            return
        canvas = self.reindex_progress_canvas
        width = max(8, int(canvas.winfo_width()))
        height = max(8, int(canvas.winfo_height()))
        fill_w = int(width * (self._index_progress_value / 100.0))

        trough = self._mix_hex(self.palette["btn_secondary_bg"], "#ffffff", 0.22)
        base_fill = self.palette["btn_primary_bg"]
        wave = self._mix_hex(base_fill, "#ffffff", 0.45)
        border = self.palette["card_border"]

        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill=trough, outline=border, width=1)
        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, height, fill=base_fill, outline="")
            band_w = 18
            step = 34
            start_x = -step + (self._index_wave_offset % step)
            x = start_x
            while x < fill_w:
                canvas.create_rectangle(x, 0, x + band_w, height, fill=wave, outline="")
                x += step
        canvas.create_rectangle(0, 0, width, height, outline=border, width=1)

    def _index_wave_tick(self) -> None:
        self._index_wave_job = None
        self._index_wave_offset = (self._index_wave_offset + 3) % 1000
        self._draw_index_progress_bar()
        if self._reindex_running:
            self._index_wave_job = self.root.after(60, self._index_wave_tick)

    def _start_index_wave_animation(self) -> None:
        if self._index_wave_job is None:
            self._index_wave_job = self.root.after(60, self._index_wave_tick)

    def _stop_index_wave_animation(self) -> None:
        if self._index_wave_job is None:
            return
        try:
            self.root.after_cancel(self._index_wave_job)
        except tk.TclError:
            pass
        self._index_wave_job = None

    def _set_timeline_meta(self, state: str, mode: str = "", detail: str = "") -> None:
        self._timeline_state = state
        self._timeline_mode = mode
        if detail:
            self._timeline_detail = detail
        self._render_timeline_ops()

    def _render_timeline_ops(self) -> None:
        if not hasattr(self, "timeline_stage_widgets"):
            return

        state = self._timeline_state
        progress = self._index_progress_value
        mode_text = {"full": "全量重建", "incremental": "增量同步"}.get(self._timeline_mode, "索引任务")
        title_map = {
            "idle": "Timeline Ops / 待机",
            "running": f"Timeline Ops / {mode_text}进行中",
            "done": f"Timeline Ops / {mode_text}完成",
            "cancelled": f"Timeline Ops / {mode_text}已取消",
            "error": f"Timeline Ops / {mode_text}失败",
        }
        self.timeline_title_var.set(title_map.get(state, "Timeline Ops"))
        self.timeline_detail_var.set(self._timeline_detail)

        if state == "running":
            if progress < 10:
                active = 0
            elif progress < 60:
                active = 1
            elif progress < 99:
                active = 2
            else:
                active = 3
            stage_states = ["done" if i < active else "active" if i == active else "idle" for i in range(4)]
        elif state == "done":
            stage_states = ["done", "done", "done", "done"]
        elif state == "cancelled":
            stage_states = ["done", "done", "error", "idle"]
        elif state == "error":
            stage_states = ["done", "done", "error", "idle"]
        else:
            stage_states = ["active", "idle", "idle", "idle"]

        color_map = {
            "idle": (self._mix_hex(self.palette["btn_secondary_bg"], "#ffffff", 0.35), self.palette["text_secondary"]),
            "active": (self._mix_hex(self.palette["btn_primary_bg"], "#ffffff", 0.25), self.palette["text_primary"]),
            "done": ("#2db87c", self.palette["text_primary"]),
            "error": ("#d46a6a", self.palette["text_primary"]),
        }

        for i, key in enumerate(("prepare", "scan", "index", "finish")):
            dot_canvas, label = self.timeline_stage_widgets[key]
            dot_canvas.delete("all")
            dot_color, text_color = color_map[stage_states[i]]
            dot_canvas.create_oval(2, 2, 16, 16, fill=dot_color, outline="")
            label.configure(fg=text_color)

    def _build_layout(self) -> None:
        shell = tk.Frame(self.root, bg=self.palette["app_bg"])
        shell.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(shell, bg=self.palette["sidebar_bg"], width=230)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        main = tk.Frame(shell, bg=self.palette["main_bg"])
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title_wrap = tk.Frame(self.sidebar, bg=self.palette["sidebar_bg"])
        title_wrap.pack(fill=tk.X, padx=14, pady=(16, 10))
        tk.Label(
            title_wrap,
            text="Notes Agent",
            bg=self.palette["sidebar_bg"],
            fg=self.palette["text_primary"],
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="RAG Workspace",
            bg=self.palette["sidebar_bg"],
            fg=self.palette["text_secondary"],
            font=("Consolas", 10),
        ).pack(anchor="w", pady=(2, 0))

        self._make_nav_button("qa", "问答")
        self._make_nav_button("edit", "修改")
        self._make_nav_button("update", "更新")
        self._make_nav_button("settings", "设置")

        tk.Frame(self.sidebar, bg=self.palette["sidebar_divider"], height=1).pack(fill=tk.X, padx=12, pady=10)

        self.side_status_var = tk.StringVar(value="索引状态加载中...")
        tk.Label(
            self.sidebar,
            textvariable=self.side_status_var,
            justify=tk.LEFT,
            wraplength=196,
            bg=self.palette["sidebar_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=14)

        self.header = tk.Frame(main, bg=self.palette["header_bg"], height=62)
        self.header.pack(fill=tk.X)
        self.header.pack_propagate(False)

        self.header_title_var = tk.StringVar(value="问答")
        tk.Label(
            self.header,
            textvariable=self.header_title_var,
            bg=self.palette["header_bg"],
            fg=self.palette["text_primary"],
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(side=tk.LEFT, padx=18, pady=14)

        self.header_hint_var = tk.StringVar(value="基于笔记语义检索并回答")
        tk.Label(
            self.header,
            textvariable=self.header_hint_var,
            bg=self.palette["header_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 10),
        ).pack(side=tk.LEFT, pady=16)

        self.theme_toggle_var = tk.StringVar(value=self._theme_toggle_text())
        tk.Button(
            self.header,
            textvariable=self.theme_toggle_var,
            command=self._on_toggle_theme,
            relief="flat",
            bd=0,
            bg=self.palette["accent"],
            fg="#ffffff",
            activebackground=self.palette["btn_primary_active"],
            activeforeground="#ffffff",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=10,
            pady=3,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=16, pady=14)

        self.content = tk.Frame(main, bg=self.palette["main_bg"])
        self.content.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

    def _theme_toggle_text(self) -> str:
        return "切换模式"

    def _snapshot_ui_state(self) -> dict[str, str]:
        state: dict[str, str] = {"page": self.current_page}
        if hasattr(self, "question_var"):
            state["question"] = self.question_var.get()
        if hasattr(self, "instruction_text"):
            state["instruction"] = self.instruction_text.get("1.0", tk.END)
        if hasattr(self, "answer_text"):
            state["answer"] = self.answer_text.get("1.0", tk.END)
        if hasattr(self, "sources_text"):
            state["sources"] = self.sources_text.get("1.0", tk.END)
        if hasattr(self, "diff_text"):
            state["diff"] = self.diff_text.get("1.0", tk.END)
        if hasattr(self, "edit_intent_text"):
            state["intent"] = self.edit_intent_text.get("1.0", tk.END)
        if hasattr(self, "log_text"):
            state["log"] = self.log_text.get("1.0", tk.END)
        return state

    def _restore_ui_state(self, state: dict[str, str]) -> None:
        if "question" in state:
            self.question_var.set(state["question"].rstrip("\n"))
        if "instruction" in state:
            self._set_text(self.instruction_text, state["instruction"].rstrip("\n"))
        if "answer" in state:
            self._set_text(self.answer_text, state["answer"].rstrip("\n"))
        if "sources" in state:
            self._set_text(self.sources_text, state["sources"].rstrip("\n"))
        if "diff" in state:
            self._set_text(self.diff_text, state["diff"].rstrip("\n"))
        if "intent" in state:
            self._set_text(self.edit_intent_text, state["intent"].rstrip("\n"))
        if "log" in state:
            self._set_text(self.log_text, state["log"].rstrip("\n"))

    def _rebuild_ui_for_theme(self) -> None:
        state = self._snapshot_ui_state()
        self._hide_hover_tip()
        self._stop_index_wave_animation()
        for child in self.root.winfo_children():
            child.destroy()

        self.nav_buttons = {}
        self.pages = {}
        self.root.configure(bg=self.palette["app_bg"])
        self._apply_ttk_theme()

        self._build_layout()
        self._build_pages()
        self._load_settings_to_form()
        self._refresh_stats()
        self._show_page(state.get("page", "qa"))
        self._restore_ui_state(state)

    def _on_toggle_theme(self) -> None:
        if self._reindex_running:
            messagebox.showinfo("提示", "索引任务进行中，暂不支持切换模式。")
            return
        self.theme_mode = "night" if self.theme_mode == "day" else "day"
        self.palette = self._get_palette(self.theme_mode)
        self._rebuild_ui_for_theme()

    def _make_nav_button(self, key: str, text: str) -> None:
        btn = tk.Button(
            self.sidebar,
            text=text,
            command=lambda k=key: self._show_page(k),
            relief="flat",
            bd=0,
            bg=self.palette["nav_idle_bg"],
            fg=self.palette["nav_idle_fg"],
            activebackground=self.palette["nav_active_bg"],
            activeforeground=self.palette["nav_active_fg"],
            font=("Microsoft YaHei UI", 11, "bold"),
            padx=14,
            pady=9,
            anchor="w",
            cursor="hand2",
        )
        btn.pack(fill=tk.X, padx=10, pady=3)
        self.nav_buttons[key] = btn

    def _build_pages(self) -> None:
        self.pages["qa"] = self._build_qa_page()
        self.pages["edit"] = self._build_edit_page()
        self.pages["update"] = self._build_update_page()
        self.pages["settings"] = self._build_settings_page()

    def _new_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=self.palette["main_bg"])
        return page

    def _card(self, parent: tk.Widget, pady: int = 10) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=self.palette["card_bg"],
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=self.palette["card_border"],
            highlightcolor=self.palette["card_border"],
        )
        card.pack(fill=tk.BOTH, expand=True, pady=(0, pady))
        return card

    def _title(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=self.palette["card_bg"],
            fg=self.palette["text_primary"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))

    def _subtitle(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=self.palette["card_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=12, pady=(0, 8))

    def _text(self, parent: tk.Widget, height: int, mono: bool = False) -> tk.Text:
        font = ("Consolas", 10) if mono else ("Microsoft YaHei UI", 10)
        return tk.Text(
            parent,
            height=height,
            wrap=tk.WORD,
            font=font,
            bg=self.palette["input_bg"],
            fg=self.palette["text_primary"],
            relief="solid",
            bd=1,
            highlightthickness=0,
            padx=8,
            pady=7,
        )

    def _build_qa_page(self) -> tk.Frame:
        page = self._new_page()

        ask_card = self._card(page, pady=8)
        self._title(ask_card, "问题输入")
        self._subtitle(ask_card, "支持自然语言提问，系统会附带可追溯来源。")

        row = tk.Frame(ask_card, bg=self.palette["card_bg"])
        row.pack(fill=tk.X, padx=12, pady=(0, 12))

        self.question_var = tk.StringVar()
        question_entry = tk.Entry(
            row,
            textvariable=self.question_var,
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            bg=self.palette["input_bg"],
            fg=self.palette["text_primary"],
        )
        question_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._make_button(
            row,
            text="提问",
            command=self._on_ask,
            primary=True,
        ).pack(side=tk.LEFT, padx=8)

        result_card = self._card(page, pady=0)
        self._title(result_card, "回答")
        self.qa_progress_var = tk.DoubleVar(value=0.0)
        self.qa_progress = ttk.Progressbar(
            result_card,
            variable=self.qa_progress_var,
            mode="determinate",
            maximum=100.0,
            style="Youth.Horizontal.TProgressbar",
        )
        self.qa_progress.pack(fill=tk.X, padx=12, pady=(0, 6))

        self.qa_progress_text_var = tk.StringVar(value="问答进度: 未开始")
        tk.Label(
            result_card,
            textvariable=self.qa_progress_text_var,
            bg=self.palette["card_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self.answer_text = self._text(result_card, height=12)
        self.answer_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))

        self._title(result_card, "来源")
        self.sources_text = self._text(result_card, height=8, mono=True)
        self.sources_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        return page

    def _build_edit_page(self) -> tk.Frame:
        page = self._new_page()

        cmd_card = self._card(page, pady=8)
        self._title(cmd_card, "修改指令")
        self._subtitle(
            cmd_card,
            "支持自然语言指令（系统会尝试自动理解）；先预览 diff，再确认写入文件。修改完会自动更新索引，无需手动同步或重建。",
        )

        self.instruction_text = self._text(cmd_card, height=5)
        self.instruction_text.pack(fill=tk.X, padx=12, pady=(0, 10))

        row = tk.Frame(cmd_card, bg=self.palette["card_bg"])
        row.pack(fill=tk.X, padx=12, pady=(0, 12))
        self._make_button(
            row,
            text="预览修改",
            command=self._on_preview_edit,
            primary=False,
        ).pack(side=tk.LEFT)
        self._make_button(
            row,
            text="应用并保存",
            command=self._on_apply_edit,
            primary=True,
        ).pack(side=tk.LEFT, padx=8)

        diff_card = self._card(page, pady=0)
        self._title(diff_card, "修改意图确认")
        self.edit_intent_text = self._text(diff_card, height=6, mono=True)
        self.edit_intent_text.pack(fill=tk.X, expand=False, padx=12, pady=(0, 10))

        self._title(diff_card, "修改预览 (Diff)")
        self.diff_text = self._text(diff_card, height=20, mono=True)
        self.diff_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        return page

    def _build_update_page(self) -> tk.Frame:
        page = self._new_page()

        action_card = self._card(page, pady=8)
        self._title(action_card, "Ops Console")
        self._subtitle(action_card, "执行索引任务、管理监听器；任务运行中可单击同一按钮取消。")
        row = tk.Frame(action_card, bg=self.palette["card_bg"])
        row.pack(fill=tk.X, padx=12, pady=(4, 10))

        self.full_reindex_btn = self._make_button(row, text="全量重建索引", command=self._on_full_reindex, primary=True)
        self.full_reindex_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.incremental_sync_btn = self._make_button(row, text="增量同步", command=self._on_incremental_sync, primary=False)
        self.incremental_sync_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.watcher_btn = self._make_button(row, text="启动监听", command=self._on_start_watcher, primary=False)
        self.watcher_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._bind_dynamic_tip(self.full_reindex_btn, self._full_reindex_tip_text)
        self._bind_dynamic_tip(self.incremental_sync_btn, self._incremental_sync_tip_text)
        self._bind_dynamic_tip(self.watcher_btn, self._watcher_tip_text)
        self._refresh_update_action_buttons()

        metrics = tk.Frame(action_card, bg=self.palette["card_bg"])
        metrics.pack(fill=tk.X, padx=12, pady=(0, 12))
        self.metric_files_var = tk.StringVar(value="文件 0")
        self.metric_chunks_var = tk.StringVar(value="分块 0")
        self.metric_watch_var = tk.StringVar(value="监听 未运行")
        for var in (self.metric_files_var, self.metric_chunks_var, self.metric_watch_var):
            tk.Label(
                metrics,
                textvariable=var,
                bg=self._mix_hex(self.palette["info_bg"], "#ffffff", 0.2),
                fg=self.palette["text_primary"],
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=10,
                pady=5,
                relief="flat",
            ).pack(side=tk.LEFT, padx=(0, 8))

        self.stats_var = tk.StringVar(value="")
        tk.Label(
            action_card,
            textvariable=self.stats_var,
            justify=tk.LEFT,
            bg=self.palette["card_bg"],
            fg=self.palette["text_secondary"],
            font=("Consolas", 9),
            wraplength=960,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        timeline_card = self._card(page, pady=8)
        self.timeline_title_var = tk.StringVar(value="Timeline Ops / 待机")
        tk.Label(
            timeline_card,
            textvariable=self.timeline_title_var,
            bg=self.palette["card_bg"],
            fg=self.palette["text_primary"],
            font=("Consolas", 12, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 2))
        self.timeline_detail_var = tk.StringVar(value="等待任务")
        tk.Label(
            timeline_card,
            textvariable=self.timeline_detail_var,
            bg=self.palette["card_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=12, pady=(0, 8))

        stage_row = tk.Frame(timeline_card, bg=self.palette["card_bg"])
        stage_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        self.timeline_stage_widgets = {}
        stage_labels = [("prepare", "准备"), ("scan", "扫描"), ("index", "建索引"), ("finish", "完成")]
        for key, label_text in stage_labels:
            item = tk.Frame(stage_row, bg=self.palette["card_bg"])
            item.pack(side=tk.LEFT, padx=(0, 20))
            dot = tk.Canvas(item, width=18, height=18, bg=self.palette["card_bg"], highlightthickness=0, bd=0)
            dot.pack(side=tk.LEFT)
            label = tk.Label(
                item,
                text=label_text,
                bg=self.palette["card_bg"],
                fg=self.palette["text_secondary"],
                font=("Microsoft YaHei UI", 9, "bold"),
            )
            label.pack(side=tk.LEFT, padx=(4, 0))
            self.timeline_stage_widgets[key] = (dot, label)

        self.reindex_progress_canvas = tk.Canvas(
            timeline_card,
            height=14,
            bg=self.palette["card_bg"],
            highlightthickness=0,
            bd=0,
        )
        self.reindex_progress_canvas.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.reindex_progress_canvas.bind("<Configure>", lambda _e: self._draw_index_progress_bar())
        self._set_index_progress(0.0)

        self.reindex_progress_text_var = tk.StringVar(value="重建进度: 0/0")
        tk.Label(
            timeline_card,
            textvariable=self.reindex_progress_text_var,
            bg=self.palette["card_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=12, pady=(0, 10))

        self._render_timeline_ops()

        log_card = self._card(page, pady=0)
        self._title(log_card, "Event Stream")
        self.log_text = self._text(log_card, height=18, mono=True)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        return page

    def _build_settings_page(self) -> tk.Frame:
        page = self._new_page()
        card = self._card(page, pady=0)

        self._title(card, "模型与 API 设置")
        self._subtitle(card, "支持多提供商预设，选择后自动填充参数。")

        form = tk.Frame(card, bg=self.palette["card_bg"])
        form.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.use_llm_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            form,
            text="启用 LLM + RAG",
            variable=self.use_llm_var,
            bg=self.palette["card_bg"],
            fg=self.palette["text_primary"],
            selectcolor=self.palette["card_bg"],
            font=("Microsoft YaHei UI", 10, "bold"),
            activebackground=self.palette["card_bg"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tk.Label(
            form,
            text="提供商预设",
            bg=self.palette["card_bg"],
            fg=self.palette["text_primary"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(
            row=1, column=0, sticky="w", pady=5
        )
        self.provider_var = tk.StringVar(value=PROVIDER_PRESETS[0].label)
        self.provider_combo = ttk.Combobox(
            form,
            textvariable=self.provider_var,
            values=[preset.label for preset in PROVIDER_PRESETS],
            state="readonly",
            width=68,
            font=("Microsoft YaHei UI", 10),
            style="Youth.TCombobox",
        )
        self.provider_combo.grid(row=1, column=1, sticky="ew", pady=5)
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_selected)

        self.api_base_var = self._form_entry(form, "API Base URL", 2)
        self.api_key_var = self._form_entry(form, "API Key", 3, show="*")
        self.chat_model_var = self._form_entry(form, "Chat Model", 4)
        self.embedding_model_var = self._form_entry(form, "Embedding Model", 5)
        self.topk_var = self._form_entry(form, "Top-K", 6, width=12)
        self.notes_root_var = self._form_entry(form, "笔记目录路径", 7, width=72)
        self.index_dir_var = self._form_entry(form, "索引存放目录", 8, width=72)
        tk.Label(
            form,
            text="备份策略",
            bg=self.palette["card_bg"],
            fg=self.palette["text_primary"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(
            row=9, column=0, sticky="w", pady=(4, 2)
        )
        self.backup_mode_label_to_value = {
            "总是备份": "always",
            "每次询问": "ask",
            "从不备份": "never",
        }
        self.backup_mode_value_to_label = {v: k for k, v in self.backup_mode_label_to_value.items()}
        self.backup_mode_var = tk.StringVar(value="每次询问")
        self.backup_mode_combo = ttk.Combobox(
            form,
            textvariable=self.backup_mode_var,
            values=list(self.backup_mode_label_to_value.keys()),
            state="readonly",
            width=18,
            font=("Microsoft YaHei UI", 10),
            style="Youth.TCombobox",
        )
        self.backup_mode_combo.grid(row=9, column=1, sticky="w", pady=(4, 2))
        self._make_button(
            form,
            text="浏览...",
            command=self._on_browse_notes_root,
            compact=True,
        ).grid(row=7, column=2, sticky="w", padx=(8, 0))
        self._make_button(
            form,
            text="浏览...",
            command=self._on_browse_index_dir,
            compact=True,
        ).grid(row=8, column=2, sticky="w", padx=(8, 0))

        action_row = tk.Frame(form, bg=self.palette["card_bg"])
        action_row.grid(row=10, column=0, columnspan=3, sticky="w", pady=(10, 8))
        self._make_button(
            action_row,
            text="保存设置",
            command=self._on_save_settings,
            primary=True,
        ).pack(side=tk.LEFT)
        self._make_button(
            action_row,
            text="连通性测试",
            command=self._on_test_connection,
            primary=False,
        ).pack(side=tk.LEFT, padx=8)

        info_wrap = tk.Frame(
            form,
            bg=self.palette["info_bg"],
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=self.palette["card_border"],
            highlightcolor=self.palette["card_border"],
        )
        info_wrap.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        self.provider_note_var = tk.StringVar(value="")
        tk.Label(
            info_wrap,
            textvariable=self.provider_note_var,
            justify=tk.LEFT,
            bg=self.palette["info_bg"],
            fg=self.palette["text_secondary"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=10, pady=(8, 4))

        self.api_key_link_var = tk.StringVar(value="")
        self.api_key_link_label = tk.Label(
            info_wrap,
            textvariable=self.api_key_link_var,
            bg=self.palette["info_bg"],
            fg=self.palette["link_fg"],
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "underline"),
        )
        self.api_key_link_label.pack(anchor="w", padx=10, pady=(0, 3))

        self.docs_link_var = tk.StringVar(value="")
        self.docs_link_label = tk.Label(
            info_wrap,
            textvariable=self.docs_link_var,
            bg=self.palette["info_bg"],
            fg=self.palette["link_fg"],
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "underline"),
        )
        self.docs_link_label.pack(anchor="w", padx=10, pady=(0, 8))

        form.columnconfigure(1, weight=1)
        return page

    def _form_entry(self, parent: tk.Widget, label: str, row: int, show: str | None = None, width: int = 72) -> tk.StringVar:
        tk.Label(
            parent,
            text=label,
            bg=self.palette["card_bg"],
            fg=self.palette["text_primary"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(
            row=row, column=0, sticky="w", pady=5
        )
        var = tk.StringVar()
        entry = tk.Entry(
            parent,
            textvariable=var,
            width=width,
            font=("Consolas", 10),
            relief="solid",
            bg=self.palette["input_bg"],
            fg=self.palette["text_primary"],
        )
        if show:
            entry.configure(show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        return var

    def _show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        for page_key, frame in self.pages.items():
            if page_key == key:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

        for page_key, button in self.nav_buttons.items():
            if page_key == key:
                button.configure(bg=self.palette["nav_active_bg"], fg=self.palette["nav_active_fg"])
            else:
                button.configure(bg=self.palette["nav_idle_bg"], fg=self.palette["nav_idle_fg"])

        self.current_page = key
        labels = {
            "qa": ("问答", "基于笔记语义检索并回答"),
            "edit": ("修改", "先预览差异，再安全落盘"),
            "update": ("更新", "全量重建、增量同步、实时监听"),
            "settings": ("设置", "提供商预设、模型参数与 API 配置"),
        }
        title, hint = labels.get(key, ("", ""))
        self.header_title_var.set(title)
        self.header_hint_var.set(hint)

    def _load_settings_to_form(self) -> None:
        s = self.agent.get_settings()
        self.provider_var.set(self.provider_id_to_label.get(s.provider_id, PROVIDER_PRESETS[0].label))
        self.use_llm_var.set(s.use_llm_rag)
        self.api_base_var.set(s.api_base_url)
        self.api_key_var.set(s.api_key)
        self.chat_model_var.set(s.chat_model)
        self.embedding_model_var.set(s.embedding_model)
        self.topk_var.set(str(s.top_k))
        self.notes_root_var.set(s.notes_root_dir)
        self.index_dir_var.set(s.vector_index_dir)
        self.backup_mode_var.set(self.backup_mode_value_to_label.get(s.backup_mode, "每次询问"))
        self._refresh_provider_note()

    def _read_settings_from_form(self) -> AppSettings:
        top_k_raw = self.topk_var.get().strip() or "6"
        try:
            top_k = int(top_k_raw)
        except ValueError as exc:
            raise ValueError("Top-K 必须是整数") from exc

        return AppSettings(
            provider_id=self.provider_label_to_id.get(self.provider_var.get(), "custom"),
            notes_root_dir=self.notes_root_var.get().strip(),
            vector_index_dir=self.index_dir_var.get().strip(),
            backup_mode=self.backup_mode_label_to_value.get(self.backup_mode_var.get(), "ask"),
            use_llm_rag=bool(self.use_llm_var.get()),
            api_base_url=self.api_base_var.get().strip() or "https://api.openai.com/v1",
            api_key=self.api_key_var.get().strip(),
            chat_model=self.chat_model_var.get().strip(),
            embedding_model=self.embedding_model_var.get().strip(),
            top_k=top_k,
        )

    def _refresh_provider_note(self) -> None:
        provider_id = self.provider_label_to_id.get(self.provider_var.get(), "custom")
        preset = get_provider_by_id(provider_id)

        lines = [
            f"当前预设: {preset.label}",
            f"Base URL: {preset.api_base_url}",
            "说明: 预设会自动填充 URL 和模型名，可按需手改。",
        ]
        if preset.note:
            lines.append(f"备注: {preset.note}")
        lines.append("提示: 保存后请在“更新”页执行一次“全量重建索引”。")
        self.provider_note_var.set("\n".join(lines))

        self._set_link(self.api_key_link_label, self.api_key_link_var, "API Key 获取页面", preset.api_key_url)
        self._set_link(self.docs_link_label, self.docs_link_var, "模型/接口文档", preset.docs_url)

    def _set_link(self, label: tk.Label, text_var: tk.StringVar, title: str, url: str) -> None:
        text_var.set(f"{title}: {url}" if url else f"{title}: (当前预设未提供)")
        label.unbind("<Button-1>")
        if not url:
            label.configure(fg=self.palette["link_disabled_fg"], cursor="arrow")
            return
        label.configure(fg=self.palette["link_fg"], cursor="hand2")
        label.bind("<Button-1>", lambda _e, u=url: self._open_url(u))

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _on_provider_selected(self, _event=None) -> None:
        provider_id = self.provider_label_to_id.get(self.provider_var.get(), "custom")
        preset = get_provider_by_id(provider_id)
        self.api_base_var.set(preset.api_base_url)
        self.chat_model_var.set(preset.chat_model)
        self.embedding_model_var.set(preset.embedding_model)
        self._refresh_provider_note()

    def _on_browse_notes_root(self) -> None:
        selected = filedialog.askdirectory(
            title="选择笔记目录",
            initialdir=self.notes_root_var.get().strip() or self.agent.get_settings().notes_root_dir or ".",
            mustexist=True,
        )
        if selected:
            self.notes_root_var.set(selected)

    def _on_browse_index_dir(self) -> None:
        selected = filedialog.askdirectory(
            title="选择索引存放目录",
            initialdir=self.index_dir_var.get().strip() or self.agent.get_settings().vector_index_dir or ".",
            mustexist=True,
        )
        if selected:
            self.index_dir_var.set(selected)

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)

    def _render_markdown(self, widget: tk.Text, markdown_text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)

        if self.theme_mode == "night":
            h1_color, h2_color, h3_color = "#9fc8ff", "#86b7ff", "#6ca6ff"
            code_bg, code_fg = "#1a2a40", "#d3e3ff"
            hr_color = "#466892"
        else:
            h1_color, h2_color, h3_color = "#1f4f95", "#2a63a8", "#3576b8"
            code_bg, code_fg = "#eef3f9", "#2f4760"
            hr_color = "#9ab0c8"

        # style tags
        widget.tag_configure("md_normal", font=("Microsoft YaHei UI", 10), foreground=self.palette["text_primary"])
        widget.tag_configure("md_h1", font=("Microsoft YaHei UI", 14, "bold"), foreground=h1_color)
        widget.tag_configure("md_h2", font=("Microsoft YaHei UI", 13, "bold"), foreground=h2_color)
        widget.tag_configure("md_h3", font=("Microsoft YaHei UI", 12, "bold"), foreground=h3_color)
        widget.tag_configure("md_quote", foreground=self.palette["text_secondary"], lmargin1=18, lmargin2=18)
        widget.tag_configure("md_bold", font=("Microsoft YaHei UI", 10, "bold"), foreground=self.palette["text_primary"])
        widget.tag_configure("md_code", font=("Consolas", 10), background=code_bg, foreground=code_fg)
        widget.tag_configure("md_codeblock", font=("Consolas", 10), background=code_bg, foreground=code_fg)
        widget.tag_configure("md_hr", foreground=hr_color, font=("Consolas", 10))

        in_code_block = False
        for raw_line in markdown_text.splitlines():
            line = raw_line.rstrip("\n")

            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                widget.insert(tk.END, "\n")
                continue

            if in_code_block:
                widget.insert(tk.END, line + "\n", ("md_codeblock",))
                continue

            if re.match(r"^\s*([-*_])\1{2,}\s*$", line):
                widget.insert(tk.END, "─" * 88 + "\n", ("md_hr",))
                continue

            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                level = len(m.group(1))
                text = m.group(2).strip()
                if level == 1:
                    widget.insert(tk.END, text + "\n", ("md_h1",))
                elif level == 2:
                    widget.insert(tk.END, text + "\n", ("md_h2",))
                else:
                    widget.insert(tk.END, text + "\n", ("md_h3",))
                continue

            q = re.match(r"^\s*>\s?(.*)$", line)
            if q:
                self._insert_inline_markdown(widget, q.group(1), base_tag="md_quote")
                widget.insert(tk.END, "\n", ("md_quote",))
                continue

            ul = re.match(r"^\s*[-*+]\s+(.*)$", line)
            if ul:
                widget.insert(tk.END, "• ", ("md_normal",))
                self._insert_inline_markdown(widget, ul.group(1), base_tag="md_normal")
                widget.insert(tk.END, "\n", ("md_normal",))
                continue

            ol = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
            if ol:
                widget.insert(tk.END, f"{ol.group(1)}. ", ("md_normal",))
                self._insert_inline_markdown(widget, ol.group(2), base_tag="md_normal")
                widget.insert(tk.END, "\n", ("md_normal",))
                continue

            self._insert_inline_markdown(widget, line, base_tag="md_normal")
            widget.insert(tk.END, "\n", ("md_normal",))

        widget.configure(state=tk.NORMAL)

    def _insert_inline_markdown(self, widget: tk.Text, text: str, base_tag: str = "md_normal") -> None:
        # simplify markdown links: [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
        pattern = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`)")
        pos = 0
        for m in pattern.finditer(text):
            if m.start() > pos:
                widget.insert(tk.END, text[pos:m.start()], (base_tag,))
            token = m.group(0)
            if token.startswith("**") and token.endswith("**"):
                widget.insert(tk.END, token[2:-2], ("md_bold",))
            elif token.startswith("__") and token.endswith("__"):
                widget.insert(tk.END, token[2:-2], ("md_bold",))
            elif token.startswith("`") and token.endswith("`"):
                widget.insert(tk.END, token[1:-1], ("md_code",))
            else:
                widget.insert(tk.END, token, (base_tag,))
            pos = m.end()
        if pos < len(text):
            widget.insert(tk.END, text[pos:], (base_tag,))

    def _append_log(self, message: str) -> None:
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _refresh_stats(self) -> None:
        stats = self.agent.get_stats()
        scope = self.agent.get_index_scope_info()
        running = "运行中" if self.agent.watcher_running() else "未运行"
        suffixes = ",".join(scope.get("suffixes", []))
        summary = (
            f"笔记根目录: {scope.get('root')} | 递归索引: 是 | 后缀: {suffixes} | 已索引文件: {stats['files']} | 分块数: {stats['chunks']} "
            f"| 向量分块: {stats.get('embedded_chunks', 0)} | 监听器: {running}"
        )
        self.stats_var.set(summary)
        if hasattr(self, "metric_files_var"):
            self.metric_files_var.set(f"文件 {stats['files']}")
        if hasattr(self, "metric_chunks_var"):
            self.metric_chunks_var.set(f"分块 {stats['chunks']}")
        if hasattr(self, "metric_watch_var"):
            self.metric_watch_var.set(f"监听 {running}")
        self.side_status_var.set(f"文件: {stats['files']}\n分块: {stats['chunks']}\n向量: {stats.get('embedded_chunks', 0)}\n监听: {running}")
        self._refresh_update_action_buttons()

    def _on_save_settings(self) -> None:
        try:
            settings = self._read_settings_from_form()
            self.agent.update_settings(settings)
            self._load_settings_to_form()
            self._refresh_stats()
            self._append_log("设置已保存")
            messagebox.showinfo("完成", "设置已保存。若修改了 Embedding 配置，请执行一次全量重建索引。")
        except Exception as exc:
            messagebox.showerror("错误", f"保存设置失败: {exc}")

    def _on_test_connection(self) -> None:
        try:
            settings = self._read_settings_from_form()
            self.agent.update_settings(settings)
            if not settings.use_llm_rag:
                messagebox.showinfo("提示", "当前未启用 LLM+RAG")
                return
            result = self.agent.test_connection()
            messagebox.showinfo("成功", f"模型调用成功。\n模型: {result['model']}\n返回: {result['message']}")
        except Exception as exc:
            messagebox.showerror("错误", f"连通性测试失败: {exc}")

    def _on_ask(self) -> None:
        # self.question_var: 问题输入框变量
        # self.qa_progress_var: 进度条数值变量
        # self.qa_progress_text_var: 进度文本变量
        # self.answer_text: 答案显示区域
        # self.sources_text: 来源显示区域
        question = self.question_var.get().strip()
        if not question:
            messagebox.showwarning("提示", "请输入问题")
            return
        try:
            self.qa_progress_var.set(0.0) # 设置进度条为0%
            self.qa_progress_text_var.set("问答进度: 开始")
            self.root.update_idletasks() # 强制立即更新UI

            def _progress(percent: int, message: str) -> None: # 定义进度回调函数
                pct = max(0, min(100, int(percent))) # 确保百分比在0-100范围内
                self.qa_progress_var.set(float(pct)) # 更新进度条值
                self.qa_progress_text_var.set(f"问答进度: {pct}% | {message}")
                self.root.update_idletasks() # 实时更新UI

            result = self.agent.ask(question, progress_callback=_progress)
        except Exception as exc:
            self.qa_progress_var.set(0.0) # 重置进度
            self.qa_progress_text_var.set("问答进度: 失败")
            messagebox.showerror("错误", f"问答失败: {exc}")
            return

        self.qa_progress_var.set(100.0)
        self.qa_progress_text_var.set("问答进度: 100% | 已完成")
        self._render_markdown(self.answer_text, result["answer"]) # 渲染答案
        lines = []
        labels = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        for idx, src in enumerate(result["sources"], start=1):
            heading = src.get("heading", "") or "(未识别标题)" # 获取标题，默认值
            seq = labels[idx - 1] if idx <= len(labels) else str(idx)
            lines.append(
                f"片段{seq}：{src['file']} | 标题: {heading} | 行: {src['line_start']}-{src['line_end']} (score={src['score']})"
            )
        self._set_text(self.sources_text, "\n".join(lines) if lines else "无")

    def _on_preview_edit(self) -> None:
        instruction = self.instruction_text.get("1.0", tk.END).strip() # 从 Text控件获取用户输入的编辑指令
        if not instruction:
            messagebox.showwarning("提示", "请输入修改指令")
            return
        try:
            preview = self.agent.preview_edit(instruction) # 调用agent的预览编辑功能
            self.pending_preview = preview # 保存预览结果供后续使用
            self._set_text(self.edit_intent_text, preview.intent_text or "未解析到意图摘要") # 显示修改意图摘要
            self._set_text(self.diff_text, preview.diff_text) # 显示差异对比
            self._append_log(f"生成修改预览: {preview.file_path}")  # 记录日志
        except Exception as exc:
            self.pending_preview = None
            self._set_text(self.edit_intent_text, "")
            messagebox.showerror("错误", f"预览失败: {exc}")

    def _on_apply_edit(self) -> None:
        if self.pending_preview is None:
            messagebox.showwarning("提示", "请先预览修改")
            return

        if not messagebox.askyesno("确认", "确认将预览内容写入文件吗？"):
            return

        try:
            mode = self.agent.get_settings().backup_mode
            if mode == "always":
                backup_enabled = True
            elif mode == "never":
                backup_enabled = False
            else:
                backup_enabled = messagebox.askyesno(
                    "备份确认",
                    "本次修改是否创建备份（.bak）？\n可在“设置 -> 备份策略”中修改默认行为。",
                )

            backup = self.agent.apply_edit(self.pending_preview, backup_enabled=backup_enabled)
            if backup:
                self._append_log(f"已保存修改，备份文件: {backup}")
                messagebox.showinfo("完成", f"保存成功，备份: {backup}")
            else:
                self._append_log("已保存修改（未创建备份）")
                messagebox.showinfo("完成", "保存成功（未创建备份）")
            self.pending_preview = None
            self._set_text(self.edit_intent_text, "")
            self._set_text(self.diff_text, "")
            self._refresh_stats()
        except Exception as exc:
            messagebox.showerror("错误", f"保存失败: {exc}")

    def _full_reindex_tip_text(self) -> str:
        if self._reindex_running and self._active_index_task == "full":
            return "点击取消全量重建"
        return ""

    def _incremental_sync_tip_text(self) -> str:
        if self._reindex_running and self._active_index_task == "incremental":
            return "点击取消增量同步"
        return ""

    def _watcher_tip_text(self) -> str:
        if self._watcher_transition and self._watcher_transition_action == "start":
            return "监听启动中，请稍候"
        if self._watcher_transition and self._watcher_transition_action == "stop":
            return "监听停止中，请稍候"
        if self.agent.watcher_running():
            return "点击取消监听"
        return ""

    def _refresh_update_action_buttons(self) -> None:
        if not hasattr(self, "full_reindex_btn"):
            return

        full_cmd = self._on_full_reindex
        incr_cmd = self._on_incremental_sync
        full_state = tk.NORMAL
        incr_state = tk.NORMAL
        full_text = "全量重建索引"
        incr_text = "增量同步"

        if self._reindex_running:
            if self._active_index_task == "full":
                full_text = "全量重建中..."
                full_cmd = self._on_cancel_index_task
                incr_state = tk.DISABLED
            elif self._active_index_task == "incremental":
                incr_text = "增量同步中..."
                incr_cmd = self._on_cancel_index_task
                full_state = tk.DISABLED

        self.full_reindex_btn.configure(text=full_text, command=full_cmd, state=full_state)
        self.incremental_sync_btn.configure(text=incr_text, command=incr_cmd, state=incr_state)

        watcher_text = "启动监听"
        watcher_cmd = self._on_start_watcher
        watcher_state = tk.NORMAL
        if self._watcher_transition:
            watcher_text = "启动监听中..." if self._watcher_transition_action == "start" else "停止监听中..."
            watcher_state = tk.DISABLED
        elif self.agent.watcher_running():
            watcher_text = "监听中..."
            watcher_cmd = self._on_stop_watcher

        if self._reindex_running:
            watcher_state = tk.DISABLED

        self.watcher_btn.configure(text=watcher_text, command=watcher_cmd, state=watcher_state)

    def _ensure_watcher_polling(self) -> None:
        if self._watcher_polling:
            return
        self._watcher_polling = True
        self.root.after(120, self._poll_watcher_events)

    def _poll_watcher_events(self) -> None:
        keep_polling = self._watcher_transition
        while True:
            try:
                event = self._watcher_events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "watcher_start_done":
                err = event[1]
                self._watcher_transition = False
                self._watcher_transition_action = ""
                if err:
                    messagebox.showerror("错误", f"启动监听失败: {err}")
                    self._set_timeline_meta("error", "", f"监听启动失败：{err}")
                else:
                    self._append_log("文件监听已启动")
                    self._set_timeline_meta("idle", "", "监听器已启动，等待文件变化")
                self._refresh_stats()
                self._refresh_update_action_buttons()
                keep_polling = False
            elif kind == "watcher_stop_done":
                err = event[1]
                self._watcher_transition = False
                self._watcher_transition_action = ""
                if err:
                    messagebox.showerror("错误", f"停止监听失败: {err}")
                    self._set_timeline_meta("error", "", f"监听停止失败：{err}")
                else:
                    self._append_log("文件监听已停止")
                    self._set_timeline_meta("idle", "", "监听器已停止，等待手动启动")
                self._refresh_stats()
                self._refresh_update_action_buttons()
                keep_polling = False

        if keep_polling:
            self.root.after(120, self._poll_watcher_events)
        else:
            self._watcher_polling = False

    def _on_full_reindex(self) -> None:
        if self._reindex_running: # 防止重复执行
            messagebox.showinfo("提示", "全量重建正在进行中，请稍候。")
            return

        self._reindex_running = True # 设置运行标志
        self._active_index_task = "full"
        self._reindex_cancel_event = threading.Event()
        self._refresh_update_action_buttons()
        self._set_index_progress(0.0) # 重置进度条
        self._start_index_wave_animation()
        self.reindex_progress_text_var.set("重建进度: 0/0 | 准备中")
        self._set_timeline_meta("running", "full", "准备阶段：初始化任务")
        self._append_log("开始全量重建索引") # 记录日志

        events: queue.Queue = queue.Queue() # 创建线程安全的队列，用于工作线程和主线程之间的通信

        def _worker() -> None:
            try:
                # 定义进度回调函数
                def _progress(done: int, total: int, current_file: str) -> None:
                    events.put(("progress", done, total, current_file))

                result = self.agent.build_full_index(
                    progress_callback=_progress,
                    cancel_callback=self._reindex_cancel_event.is_set if self._reindex_cancel_event else None,
                ) # 执行实际的索引重建，通过回调函数发送进度更新
                events.put(("done", result, None, None)) # 完成后发送 "done"事件
            except IndexingCancelled:
                events.put(("cancelled", "索引任务已取消", None, None))
            except Exception as exc:
                events.put(("error", str(exc), None, None))

        threading.Thread(target=_worker, daemon=True).start() # 启动工作线程
        self._poll_reindex_events(events) # 调用轮询函数监听事件队列

    def _poll_reindex_events(self, events: queue.Queue) -> None:
        keep_polling = self._reindex_running
        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "progress":
                done = int(event[1])
                total = int(event[2]) if event[2] else 0
                current_file = str(event[3] or "")
                pct = 100.0 if total <= 0 else (done / total) * 100.0
                self._set_index_progress(max(0.0, min(100.0, pct)))
                self.reindex_progress_text_var.set(
                    f"重建进度: {done}/{total} | 当前: {os.path.basename(current_file) if current_file else '-'}"
                )
                self._set_timeline_meta(
                    "running",
                    "full",
                    f"扫描与重建中：{done}/{total} | {os.path.basename(current_file) if current_file else '-'}",
                )
                keep_polling = True
            elif kind == "done":
                result = event[1]
                self._set_index_progress(100.0)
                self._stop_index_wave_animation()
                self.reindex_progress_text_var.set(
                    f"重建进度: {result['files_seen']}/{result['files_seen']} | 已完成"
                )
                self._set_timeline_meta("done", "full", f"完成：扫描 {result['files_seen']} 文件")
                self._append_log(
                    f"全量重建完成: 扫描 {result['files_seen']} 文件, 重建 {result['files_reindexed']} 文件, 总分块 {result['chunks_total']}"
                )
                self._refresh_stats()
                self._reindex_running = False
                self._reindex_cancel_event = None
                self._active_index_task = None
                self._refresh_update_action_buttons()
                keep_polling = False
            elif kind == "cancelled":
                self._reindex_running = False
                self._reindex_cancel_event = None
                self._active_index_task = None
                keep_polling = False
                self._set_index_progress(0.0)
                self._stop_index_wave_animation()
                self.reindex_progress_text_var.set("重建进度: 已取消（已回滚）")
                self._set_timeline_meta("cancelled", "full", "已取消：索引已回滚到任务前状态")
                self._append_log("全量重建已取消，索引已回滚到任务前状态")
                self._refresh_stats()
                self._refresh_update_action_buttons()
            elif kind == "error":
                self._reindex_running = False
                self._reindex_cancel_event = None
                self._active_index_task = None
                keep_polling = False
                self._stop_index_wave_animation()
                self.reindex_progress_text_var.set("重建进度: 失败")
                self._set_timeline_meta("error", "full", f"失败：{event[1]}")
                self._refresh_update_action_buttons()
                messagebox.showerror("错误", f"重建索引失败: {event[1]}")

        if keep_polling:
            self.root.after(120, lambda: self._poll_reindex_events(events))

    def _on_incremental_sync(self) -> None:
        if self._reindex_running:
            messagebox.showinfo("提示", "已有索引任务正在执行，请稍候。")
            return

        self._reindex_running = True
        self._active_index_task = "incremental"
        self._reindex_cancel_event = threading.Event()
        self._refresh_update_action_buttons()
        self._set_index_progress(0.0)
        self._start_index_wave_animation()
        self.reindex_progress_text_var.set("增量同步: 进行中")
        self._set_timeline_meta("running", "incremental", "准备阶段：检查变更文件")
        self._append_log("开始增量同步")

        events: queue.Queue = queue.Queue()

        def _worker() -> None:
            try:
                def _progress(done: int, total: int, current_file: str) -> None:
                    events.put(("progress", done, total, current_file))

                result = self.agent.incremental_sync(
                    progress_callback=_progress,
                    cancel_callback=self._reindex_cancel_event.is_set if self._reindex_cancel_event else None,
                )
                events.put(("done", result))
            except IndexingCancelled:
                events.put(("cancelled", "索引任务已取消"))
            except Exception as exc:
                events.put(("error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self._poll_incremental_sync_events(events)

    def _poll_incremental_sync_events(self, events: queue.Queue) -> None:
        keep_polling = self._reindex_running

        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "progress":
                done = int(event[1])
                total = int(event[2]) if event[2] else 0
                current_file = str(event[3] or "")
                pct = 100.0 if total <= 0 else (done / total) * 100.0
                self._set_index_progress(max(0.0, min(100.0, pct)))
                self.reindex_progress_text_var.set(
                    f"增量同步: {done}/{total} | 当前: {os.path.basename(current_file) if current_file else '-'}"
                )
                self._set_timeline_meta(
                    "running",
                    "incremental",
                    f"同步中：{done}/{total} | {os.path.basename(current_file) if current_file else '-'}",
                )
                keep_polling = True
            elif kind == "done":
                result = event[1]
                self._set_index_progress(100.0)
                self._stop_index_wave_animation()
                self.reindex_progress_text_var.set("增量同步: 已完成")
                self._set_timeline_meta(
                    "done",
                    "incremental",
                    f"完成：新增 {result.get('files_added', 0)}，更新 {result['files_reindexed']}，删除 {result['files_removed']}",
                )
                self._append_log(
                    f"增量同步完成: 增加 {result.get('files_added', 0)} 文件, 删除 {result['files_removed']} 文件，更新 {result['files_reindexed']} 文件"
                )
                self._refresh_stats()
                self._reindex_running = False
                self._reindex_cancel_event = None
                self._active_index_task = None
                self._refresh_update_action_buttons()
                keep_polling = False
            elif kind == "cancelled":
                self._reindex_running = False
                self._reindex_cancel_event = None
                self._active_index_task = None
                keep_polling = False
                self._set_index_progress(0.0)
                self._stop_index_wave_animation()
                self.reindex_progress_text_var.set("增量同步: 已取消（已回滚）")
                self._set_timeline_meta("cancelled", "incremental", "已取消：索引已回滚到任务前状态")
                self._append_log("增量同步已取消，索引已回滚到任务前状态")
                self._refresh_stats()
                self._refresh_update_action_buttons()
            elif kind == "error":
                self._reindex_running = False
                self._reindex_cancel_event = None
                self._active_index_task = None
                keep_polling = False
                self._stop_index_wave_animation()
                self.reindex_progress_text_var.set("增量同步: 失败")
                self._set_timeline_meta("error", "incremental", f"失败：{event[1]}")
                self._refresh_update_action_buttons()
                messagebox.showerror("错误", f"增量同步失败: {event[1]}")

        if keep_polling:
            self.root.after(120, lambda: self._poll_incremental_sync_events(events))

    def _on_cancel_index_task(self) -> None:
        if not self._reindex_running or self._reindex_cancel_event is None:
            messagebox.showinfo("提示", "当前没有可取消的索引任务。")
            return
        if self._reindex_cancel_event.is_set():
            return
        self._reindex_cancel_event.set()
        self._append_log("已请求取消索引任务，正在回滚到任务前状态...")
        self.reindex_progress_text_var.set("索引任务: 正在取消并回滚")
        self._set_timeline_meta("running", self._active_index_task or "", "正在取消：等待回滚完成")
        self._refresh_update_action_buttons()

    def _on_start_watcher(self) -> None:
        if self._reindex_running:
            messagebox.showinfo("提示", "索引任务进行中，请稍后再操作监听器。")
            return
        if self._watcher_transition:
            return
        if self.agent.watcher_running():
            return

        self._watcher_transition = True
        self._watcher_transition_action = "start"
        self._set_timeline_meta("idle", "", "监听器启动中...")
        self._refresh_update_action_buttons()

        def _worker() -> None:
            err = ""
            try:
                self.agent.start_watcher()
            except Exception as exc:
                err = str(exc)
            self._watcher_events.put(("watcher_start_done", err))

        threading.Thread(target=_worker, daemon=True).start()
        self._ensure_watcher_polling()

    def _on_stop_watcher(self) -> None:
        if self._reindex_running:
            messagebox.showinfo("提示", "索引任务进行中，请稍后再操作监听器。")
            return
        if self._watcher_transition:
            return
        if not self.agent.watcher_running():
            return

        self._watcher_transition = True
        self._watcher_transition_action = "stop"
        self._set_timeline_meta("idle", "", "监听器停止中...")
        self._refresh_update_action_buttons()

        def _worker() -> None:
            err = ""
            try:
                self.agent.stop_watcher()
            except Exception as exc:
                err = str(exc)
            self._watcher_events.put(("watcher_stop_done", err))

        threading.Thread(target=_worker, daemon=True).start()
        self._ensure_watcher_polling()

    def _on_close(self) -> None:
        self._hide_hover_tip()
        self._stop_index_wave_animation()
        self.agent.stop_watcher()
        self.root.destroy()


def run_ui() -> int:
    root = tk.Tk()
    agent = NoteAgent()
    MainWindow(root, agent)
    root.mainloop()
    return 0
