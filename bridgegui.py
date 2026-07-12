import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText


APP_TITLE = "Token Saving Bridge for AI Influence"
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

CONFIG_PATH = APP_DIR / "config.json"
TOKENS_PATH = APP_DIR / "tokens.json"
INTERCEPT_DIR = APP_DIR / "intercepts"
STDOUT_PATH = APP_DIR / "backend_stdout.log"
STDERR_PATH = APP_DIR / "backend_stderr.log"
BACKEND_SCRIPT_PATH = APP_DIR / "backend.py"
BACKEND_EXE_PATH = APP_DIR / "backend.exe"

DEFAULT_CONFIG = {
    "mode": "player2",
    "base_url": "http://127.0.0.1:4315/v1",
    "api_key": "",
    "model": "",
    "router_model": "qwen2.5:7b-instruct",
    "debug_mode": True,
    "show_intercepts": False,
    "input_token_cost_per_m": 0.0,
    "output_token_cost_per_m": 0.0,
}
DEFAULT_TOKENS = {
    "total_tokens": 0,
    "session_tokens": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "session_prompt_tokens": 0,
    "bg": "#0b0e15",
    "panel": "#10141e",
    "card": "#161b28",
    "card_alt": "#1c2231",
    "border": "#242c3d",
    "text": "#e9ecf4",
    "muted": "#8b93a7",
    "accent": "#7c6cf0",
    "accent_light": "#9d90fb",
    "accent_dark": "#5a4bd6",
    "ok": "#33d17a",
    "bad": "#f2495c",
    "entry": "#0f1320",
}

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"

TITLE_FONT = (FONT_FAMILY, 22, "bold")
SUBTITLE_FONT = (FONT_FAMILY, 10)
SECTION_FONT = (FONT_FAMILY, 12, "bold")
LABEL_FONT = (FONT_FAMILY, 10)
VALUE_FONT = (FONT_FAMILY, 19, "bold")
MUTED_FONT = (FONT_FAMILY, 9)
BUTTON_FONT = (FONT_FAMILY, 10, "bold")
LOG_FONT = (MONO_FAMILY, 10)

CARD_RADIUS = 18
BUTTON_RADIUS = 12
PILL_RADIUS = 999
ENTRY_RADIUS = 10


def _round_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]


class RoundedFrame(tk.Canvas):
    """A canvas that draws a rounded-rectangle background behind a plain
    tk.Frame, so that any normal widgets can be packed/gridded inside while
    still getting rounded corners."""

    def __init__(self, parent, bg, parent_bg=None, radius=CARD_RADIUS,
                 border=None, **kwargs):
        parent_bg = parent_bg if parent_bg is not None else THEME["bg"]
        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0, **kwargs)
        self.radius = radius
        self.color = bg
        self.border_color = border
        self.inner = tk.Frame(self, bg=bg)
        self._win = self.create_window(0, 0, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        w, h = event.width, event.height
        if w < 4 or h < 4:
            return
        self.delete("bg")
        points = _round_points(1, 1, w - 1, h - 1, self.radius)
        outline = self.border_color or self.color
        self.create_polygon(points, smooth=True, fill=self.color, outline=outline, tags="bg")
        self.tag_lower("bg")
        self.coords(self._win, 3, 3)
        self.itemconfig(self._win, width=max(w - 6, 1), height=max(h - 6, 1))

    def fit(self):
        """Size this card to its inner content's natural (requested) size.
        Call this once after all widgets have been added to .inner — Tk's
        Canvas has no concept of 'shrink to fit child', so without this the
        card falls back to an arbitrary default size, clipping tall content
        or leaving big empty gaps in short content."""
        self.inner.update_idletasks()
        w = self.inner.winfo_reqwidth() + 6
        h = self.inner.winfo_reqheight() + 6
        self.configure(width=w, height=h)


class RoundedButton(tk.Canvas):
    """A clickable, rounded-corner button drawn on a Canvas."""

    def __init__(self, parent, text, command=None, bg=None, fg="#0c0e16",
                 hover_bg=None, parent_bg=None, width=140, height=36,
                 radius=BUTTON_RADIUS, font=BUTTON_FONT):
        parent_bg = parent_bg if parent_bg is not None else THEME["card"]
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                          highlightthickness=0, bd=0, cursor="hand2")
        self.command = command
        self.base_color = bg or THEME["accent"]
        self.hover_color = hover_bg or self.base_color
        self.fg_color = fg
        self.radius = radius
        self.text = text
        self.font = font
        self.enabled = True
        self._current_w = width
        self._current_h = height
        self._render(self.base_color)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._render(self.hover_color if self.enabled else self.base_color))
        self.bind("<Leave>", lambda e: self._render(self.base_color))
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self._current_w, self._current_h = event.width, event.height
        self._render(self.base_color)

    def _render(self, color):
        self.delete("all")
        w, h = self._current_w, self._current_h
        fill = color if self.enabled else THEME["border"]
        text_fill = self.fg_color if self.enabled else THEME["muted"]
        points = _round_points(1, 1, max(w - 1, 2), max(h - 1, 2), self.radius)
        self.create_polygon(points, smooth=True, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=text_fill, font=self.font)

    def _on_click(self, event):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._render(self.base_color)


class RoundedBadge(tk.Canvas):
    """A pill-shaped status badge."""

    def __init__(self, parent, text, color, parent_bg=None, width=110, height=28, font=BUTTON_FONT):
        parent_bg = parent_bg if parent_bg is not None else THEME["card"]
        super().__init__(parent, width=width, height=height, bg=parent_bg, highlightthickness=0, bd=0)
        self.text = text
        self.color = color
        self.font = font
        self._current_w = width
        self._current_h = height
        self.bind("<Configure>", self._on_resize)
        self._render()

    def _on_resize(self, event):
        self._current_w, self._current_h = event.width, event.height
        self._render()

    def _render(self):
        self.delete("all")
        w, h = self._current_w, self._current_h
        radius = h / 2
        points = _round_points(1, 1, max(w - 1, 2), max(h - 1, 2), radius)
        self.create_polygon(points, smooth=True, fill=self.color, outline=self.color)
        self.create_text(w / 2, h / 2, text=self.text, fill="#0b0e15", font=self.font)

    def set(self, text, color):
        self.text = text
        self.color = color
        self._render()


def make_rounded_entry(parent, textvariable, parent_bg, width=280, height=38, show=None):
    """Returns a RoundedFrame containing a flat, borderless Entry, giving the
    illusion of a rounded pill-shaped input field."""
    frame = RoundedFrame(parent, bg=THEME["entry"], parent_bg=parent_bg,
                          radius=ENTRY_RADIUS, width=width, height=height,
                          border=THEME["border"])
    entry = tk.Entry(
        frame.inner,
        textvariable=textvariable,
        bg=THEME["entry"],
        fg=THEME["text"],
        insertbackground=THEME["text"],
        relief=tk.FLAT,
        bd=0,
        highlightthickness=0,
        font=LABEL_FONT,
        show=show if show else "",
    )
    entry.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
    return frame, entry


class BridgeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1140x1000")
        self.minsize(1020, 880)
        self.configure(bg=THEME["bg"])

        self.backend_proc = None
        self.backend_stdout_handle = None
        self.backend_stderr_handle = None
        self._stdout_read_pos = 0
        self._stderr_read_pos = 0
        self._seen_intercept_files = set()
        self._backend_action_in_progress = False

        self._ensure_files()
        self._initialize_log_tail_positions()
        self._build_style()
        self._build_ui()
        self._load_config_into_form()
        self._refresh_status_labels()

        self.after(1000, self._periodic_refresh)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Root.TFrame", background=THEME["bg"])
        style.configure("Panel.TFrame", background=THEME["panel"])
        style.configure("Card.TFrame", background=THEME["card"])

        style.configure("TLabel", background=THEME["bg"], foreground=THEME["text"], font=LABEL_FONT)
        style.configure("Title.TLabel", background=THEME["bg"], foreground=THEME["text"], font=TITLE_FONT)
        style.configure("SubTitle.TLabel", background=THEME["bg"], foreground=THEME["muted"], font=SUBTITLE_FONT)

        style.configure("SectionOnRoot.TLabel", background=THEME["bg"], foreground=THEME["accent_light"], font=SECTION_FONT)
        style.configure("Section.TLabel", background=THEME["card"], foreground=THEME["accent_light"], font=SECTION_FONT)
        style.configure("Field.TLabel", background=THEME["card"], foreground=THEME["muted"], font=LABEL_FONT)
        style.configure("Value.TLabel", background=THEME["card_alt"], foreground=THEME["text"], font=VALUE_FONT)
        style.configure("Muted.TLabel", background=THEME["card_alt"], foreground=THEME["muted"], font=MUTED_FONT)

        style.configure("TRadiobutton", background=THEME["card"], foreground=THEME["text"],
                         font=LABEL_FONT, focuscolor=THEME["card"])
        style.map("TRadiobutton",
                  background=[("active", THEME["card"])],
                  foreground=[("selected", THEME["accent_light"]), ("!selected", THEME["text"])])

        style.configure("TCheckbutton", background=THEME["card"], foreground=THEME["text"],
                         font=LABEL_FONT, focuscolor=THEME["card"])
        style.map("TCheckbutton",
                  background=[("active", THEME["card"])],
                  foreground=[("selected", THEME["accent_light"]), ("!selected", THEME["text"])])

        style.configure("Vertical.TScrollbar", background=THEME["card_alt"], troughcolor=THEME["panel"],
                         bordercolor=THEME["panel"], arrowcolor=THEME["muted"])

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = ttk.Frame(self, style="Root.TFrame", padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root, style="Root.TFrame")
        header.pack(fill=tk.X)

        title_row = ttk.Frame(header, style="Root.TFrame")
        title_row.pack(fill=tk.X, anchor="w")
        ttk.Label(title_row, text="Token Saving Bridge for AI Influence", style="Title.TLabel").pack(side=tk.LEFT, anchor="w")

        ttk.Label(
            header,
            text="",
            style="SubTitle.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        body = ttk.Frame(root, style="Root.TFrame")
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body, style="Root.TFrame")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right = ttk.Frame(body, style="Root.TFrame", width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        self._build_config_panel(left)
        self._build_backend_panel(left)
        self._build_log_panel(left)
        self._build_status_panel(right)

    def _card(self, parent, pack_opts=None, height=None):
        """Convenience: create a rounded card and return its inner frame."""
        kwargs = {}
        if height is not None:
            kwargs["height"] = height
        card = RoundedFrame(parent, bg=THEME["card"], parent_bg=THEME["bg"],
                             radius=CARD_RADIUS, border=THEME["border"], **kwargs)
        card.pack(**(pack_opts or {"fill": tk.X}))
        inner = card.inner
        inner.configure(padx=0, pady=0)
        return card, inner

    def _build_config_panel(self, parent):
        card, panel = self._card(parent)
        panel.configure(padx=14, pady=14)

        ttk.Label(panel, text="Configuration", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        self.mode_var = tk.StringVar(value="player2")
        self.model_var = tk.StringVar()
        self.router_model_var = tk.StringVar()
        self.input_token_cost_var = tk.StringVar(value="0")
        self.output_token_cost_var = tk.StringVar(value="0")
        self.key_var = tk.StringVar()
        self.base_var = tk.StringVar()

        mode_row = ttk.Frame(panel, style="Card.TFrame")
        mode_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 4))
        ttk.Radiobutton(mode_row, text="Player 2 (local)", value="player2", variable=self.mode_var,
                         command=self._on_mode_changed).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Radiobutton(mode_row, text="OpenRouter (cloud)", value="openrouter", variable=self.mode_var,
                         command=self._on_mode_changed).pack(side=tk.LEFT)

        ttk.Label(panel, text="Model", style="Field.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Label(panel, text="API key", style="Field.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", pady=(12, 4))

        model_entry, _ = make_rounded_entry(panel, self.model_var, THEME["card"], height=38)
        model_entry.grid(row=3, column=0, columnspan=2, sticky="we", padx=(0, 8))

        key_entry, _ = make_rounded_entry(panel, self.key_var, THEME["card"], height=38, show="*")
        key_entry.grid(row=3, column=2, columnspan=2, sticky="we")

        ttk.Label(panel, text="Base URL", style="Field.TLabel").grid(row=4, column=0, columnspan=4, sticky="w", pady=(12, 4))
        base_entry, _ = make_rounded_entry(panel, self.base_var, THEME["card"], height=38)
        base_entry.grid(row=5, column=0, columnspan=4, sticky="we")

        ttk.Label(panel, text="Router Model (Ollama)", style="Field.TLabel").grid(row=6, column=0, columnspan=4, sticky="w", pady=(12, 4))
        router_entry, _ = make_rounded_entry(panel, self.router_model_var, THEME["card"], height=38)
        router_entry.grid(row=7, column=0, columnspan=4, sticky="we")

        ttk.Label(panel, text="Input Cost ($ per 1M tokens)", style="Field.TLabel").grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Label(panel, text="Output Cost ($ per 1M tokens)", style="Field.TLabel").grid(row=8, column=2, columnspan=2, sticky="w", pady=(12, 4))

        in_cost_entry, _ = make_rounded_entry(panel, self.input_token_cost_var, THEME["card"], height=38)
        in_cost_entry.grid(row=9, column=0, columnspan=2, sticky="we", padx=(0, 8))

        out_cost_entry, _ = make_rounded_entry(panel, self.output_token_cost_var, THEME["card"], height=38)
        out_cost_entry.grid(row=9, column=2, columnspan=2, sticky="we")

        button_bar = ttk.Frame(panel, style="Card.TFrame")
        button_bar.grid(row=10, column=0, columnspan=4, sticky="we", pady=(16, 4))

        save_btn = RoundedButton(button_bar, "Save Config", command=self._save_config,
                                  bg=THEME["accent"], hover_bg=THEME["accent_light"],
                                  parent_bg=THEME["card"], width=140, height=38)
        save_btn.pack(side=tk.LEFT)

        reload_btn = RoundedButton(button_bar, "Reload", command=self._load_config_into_form,
                                    bg=THEME["card_alt"], hover_bg=THEME["border"], fg=THEME["text"],
                                    parent_bg=THEME["card"], width=120, height=38)
        reload_btn.pack(side=tk.LEFT, padx=(10, 0))

        for i in range(4):
            panel.columnconfigure(i, weight=1)

        card.fit()

    def _build_backend_panel(self, parent):
        card, panel = self._card(parent, pack_opts={"fill": tk.X, "pady": (12, 0)})
        panel.configure(padx=14, pady=14)

        ttk.Label(panel, text="Backend Runtime", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        status_row = ttk.Frame(panel, style="Card.TFrame")
        status_row.grid(row=1, column=0, columnspan=4, sticky="we")

        ttk.Label(status_row, text="Status:", style="Field.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        self.status_var = tk.StringVar(value="INACTIVE")
        self.status_badge = RoundedBadge(status_row, "INACTIVE", THEME["bad"], parent_bg=THEME["card"], width=110, height=28)
        self.status_badge.pack(side=tk.LEFT)

        self.show_intercepts_var = tk.BooleanVar(value=False)
        self.debug_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            status_row,
            text="Show intercepts in logger",
            variable=self.show_intercepts_var,
            command=self._on_toggle_intercepts,
        ).pack(side=tk.RIGHT)

        ttk.Checkbutton(
            status_row,
            text="Backend debug mode",
            variable=self.debug_mode_var,
        ).pack(side=tk.RIGHT, padx=(0, 12))

        btn_row = ttk.Frame(panel, style="Card.TFrame")
        btn_row.grid(row=2, column=0, columnspan=4, sticky="we", pady=(14, 0))

        RoundedButton(btn_row, "Start Backend", command=self._start_backend,
                      bg=THEME["ok"], hover_bg="#4ee295",
                      parent_bg=THEME["card"], width=150, height=38).pack(side=tk.LEFT, padx=(0, 10))

        RoundedButton(btn_row, "Stop Backend", command=self._stop_backend,
                      bg=THEME["bad"], hover_bg="#ff6f80", fg="#1a0508",
                      parent_bg=THEME["card"], width=150, height=38).pack(side=tk.LEFT, padx=(0, 10))

        RoundedButton(btn_row, "Open Stdout Log", command=lambda: self._open_file(STDOUT_PATH),
                      bg=THEME["card_alt"], hover_bg=THEME["border"], fg=THEME["text"],
                      parent_bg=THEME["card"], width=160, height=38).pack(side=tk.LEFT, padx=(0, 10))

        RoundedButton(btn_row, "Open Stderr Log", command=lambda: self._open_file(STDERR_PATH),
                      bg=THEME["card_alt"], hover_bg=THEME["border"], fg=THEME["text"],
                      parent_bg=THEME["card"], width=160, height=38).pack(side=tk.LEFT)

        for i in range(4):
            panel.columnconfigure(i, weight=1)

        card.fit()

    def _build_log_panel(self, parent):
        card, panel = self._card(parent, pack_opts={"fill": tk.BOTH, "expand": True, "pady": (12, 0)})
        panel.configure(padx=14, pady=14)

        ttk.Label(panel, text="Activity Log", style="Section.TLabel").pack(anchor="w", pady=(0, 12))

        log_wrap = RoundedFrame(panel, bg=THEME["entry"], parent_bg=THEME["card"],
                                 radius=ENTRY_RADIUS, border=THEME["border"])
        log_wrap.pack(fill=tk.BOTH, expand=True)

        self.log_text = ScrolledText(
            log_wrap.inner,
            height=16,
            bg=THEME["entry"],
            fg=THEME["text"],
            insertbackground=THEME["text"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            font=LOG_FONT,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.log_text.insert(tk.END, "Ready. Start Backend when you are set.\n")
        self.log_text.configure(state=tk.DISABLED)

    def _build_status_panel(self, parent):
        ttk.Label(parent, text="Stats", style="SectionOnRoot.TLabel").pack(anchor="w", pady=(0, 12))

        mode_card, mode_inner = self._card(parent, pack_opts={"fill": tk.X, "pady": (0, 10)})
        mode_inner.configure(padx=14, pady=12)
        ttk.Label(mode_inner, text="Current Backend Mode", style="Muted.TLabel").pack(anchor="w")
        self.mode_info_var = tk.StringVar(value="player2")
        ttk.Label(mode_inner, textvariable=self.mode_info_var, style="Value.TLabel").pack(anchor="w", pady=(6, 0))
        mode_card.fit()

        card1, inner1 = self._card(parent, pack_opts={"fill": tk.X, "pady": (0, 10)})
        inner1.configure(padx=14, pady=12)
        ttk.Label(inner1, text="Total Tokens", style="Muted.TLabel").pack(anchor="w")
        self.total_tokens_var = tk.StringVar(value="0")
        ttk.Label(inner1, textvariable=self.total_tokens_var, style="Value.TLabel").pack(anchor="w", pady=(6, 0))
        card1.fit()

        card2, inner2 = self._card(parent, pack_opts={"fill": tk.X, "pady": (0, 10)})
        inner2.configure(padx=14, pady=12)
        ttk.Label(inner2, text="Session Tokens", style="Muted.TLabel").pack(anchor="w")
        self.session_tokens_var = tk.StringVar(value="0")
        ttk.Label(inner2, textvariable=self.session_tokens_var, style="Value.TLabel").pack(anchor="w", pady=(6, 0))
        card2.fit()

        card3, inner3 = self._card(parent, pack_opts={"fill": tk.X})
        inner3.configure(padx=14, pady=12)
        ttk.Label(inner3, text="Estimated Savings", style="Muted.TLabel").pack(anchor="w")
        self.cost_var = tk.StringVar(value="$0.0000")
        ttk.Label(inner3, textvariable=self.cost_var, style="Value.TLabel").pack(anchor="w", pady=(6, 0))
        card3.fit()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _ensure_files(self):
        if not CONFIG_PATH.exists():
            self._save_json(CONFIG_PATH, DEFAULT_CONFIG)
        if not TOKENS_PATH.exists():
            self._save_json(TOKENS_PATH, DEFAULT_TOKENS)

    def _load_json(self, path, default_obj):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return default_obj.copy()

    def _save_json(self, path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)

    def _load_config_into_form(self):
        cfg = self._load_json(CONFIG_PATH, DEFAULT_CONFIG)
        mode = cfg.get("mode", "player2")
        self.mode_var.set(mode)
        self.model_var.set(cfg.get("model", ""))
        self.router_model_var.set(cfg.get("router_model", DEFAULT_CONFIG["router_model"]))
        self.input_token_cost_var.set(str(cfg.get("input_token_cost_per_m", DEFAULT_CONFIG["input_token_cost_per_m"])))
        self.output_token_cost_var.set(str(cfg.get("output_token_cost_per_m", DEFAULT_CONFIG["output_token_cost_per_m"])))
        self.key_var.set(cfg.get("api_key", ""))
        self.base_var.set(cfg.get("base_url", ""))
        self.debug_mode_var.set(bool(cfg.get("debug_mode", DEFAULT_CONFIG["debug_mode"])))
        self.show_intercepts_var.set(bool(cfg.get("show_intercepts", DEFAULT_CONFIG["show_intercepts"])))
        self._on_mode_changed()
        self._seed_seen_intercepts()
        self.mode_info_var.set(mode)
        self._append_log("Configuration loaded.")

    def _save_config(self, show_message=True):
        mode = self.mode_var.get().strip() or "player2"
        cfg = {
            "mode": mode,
            "base_url": self.base_var.get().strip(),
            "api_key": self.key_var.get().strip(),
            "model": self.model_var.get().strip(),
            "router_model": self.router_model_var.get().strip() or DEFAULT_CONFIG["router_model"],
            "debug_mode": bool(self.debug_mode_var.get()),
            "show_intercepts": bool(self.show_intercepts_var.get()),
            "input_token_cost_per_m": self._to_float(self.input_token_cost_var.get()),
            "output_token_cost_per_m": self._to_float(self.output_token_cost_var.get()),
        }
        self._save_json(CONFIG_PATH, cfg)
        self.mode_info_var.set(mode)
        self._append_log(f"Saved config.json (mode={mode}).")
        if show_message:
            messagebox.showinfo(APP_TITLE, "Configuration saved.")

    def _on_mode_changed(self):
        mode = self.mode_var.get().strip()
        if mode == "player2":
            self.base_var.set("http://127.0.0.1:4315/v1")
            self.model_var.set("")
            self.key_var.set("")
        elif mode == "openrouter":
            self.base_var.set("https://openrouter.ai/api/v1")

    def _append_log(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}\n"
        try:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        except tk.TclError:
            # Widget may be torn down during close; ignore late log updates.
            pass

    def _run_on_ui(self, callback):
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _append_log_async(self, text):
        self._run_on_ui(lambda: self._append_log(text))

    def _set_backend_action_in_progress(self, in_progress: bool):
        self._backend_action_in_progress = in_progress

    def _to_float(self, value, default=0.0):
        try:
            return float(str(value).strip())
        except Exception:
            return default

    def _seed_seen_intercepts(self):
        if not self.show_intercepts_var.get():
            self._seen_intercept_files.clear()
            return
        if not INTERCEPT_DIR.exists():
            return
        self._seen_intercept_files = {p.name for p in INTERCEPT_DIR.glob("*.json")}

    def _on_toggle_intercepts(self):
        if self.show_intercepts_var.get():
            self._seed_seen_intercepts()
            self._append_log("Intercept logger enabled. New intercepts will be logged. Full intercepts will be available in the intercepts directory.")
        else:
            self._append_log("Intercept logger disabled.")

    def _poll_intercepts(self):
        if not self.show_intercepts_var.get():
            return
        if not INTERCEPT_DIR.exists():
            return

        try:
            candidates = sorted(INTERCEPT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        except Exception:
            return

        for path in candidates:
            if path.name in self._seen_intercept_files:
                continue
            self._seen_intercept_files.add(path.name)
            self._append_log(f"[INTERCEPTOR] Saved raw request -> {path}")

    # ------------------------------------------------------------------
    # Backend process management
    # ------------------------------------------------------------------
    def _start_backend(self):
        if self._backend_action_in_progress:
            self._append_log("Backend action already in progress. Please wait...")
            return

        if self.backend_proc and self.backend_proc.poll() is not None:
            self.backend_proc = None
            self._close_backend_handles()

        if self.backend_proc and self.backend_proc.poll() is None:
            messagebox.showinfo(APP_TITLE, "Backend is already running.")
            return

        if getattr(sys, "frozen", False):
            if not BACKEND_EXE_PATH.exists():
                messagebox.showerror(APP_TITLE, f"Cannot find backend.exe in {APP_DIR}")
                return
            backend_cmd = [str(BACKEND_EXE_PATH)]
        else:
            if not BACKEND_SCRIPT_PATH.exists():
                messagebox.showerror(APP_TITLE, f"Cannot find backend.py in {APP_DIR}")
                return
            py = sys.executable or "python"
            backend_cmd = [py, str(BACKEND_SCRIPT_PATH)]

        self._save_config(show_message=False)
        router_model = self.router_model_var.get().strip() or DEFAULT_CONFIG["router_model"]

        self._set_backend_action_in_progress(True)
        self._append_log("Starting backend...")
        worker = threading.Thread(
            target=self._start_backend_worker,
            args=(backend_cmd, router_model),
            daemon=True,
        )
        worker.start()

    def _start_backend_worker(self, backend_cmd, router_model):
        stdout_handle = None
        stderr_handle = None
        try:
            try:
                # Do not preflight Ollama from GUI thread/worker.
                # backend.py already owns Ollama startup/recovery and provides clearer runtime logs.
                self._close_backend_handles()

                if STDOUT_PATH.exists():
                    STDOUT_PATH.unlink()
                if STDERR_PATH.exists():
                    STDERR_PATH.unlink()
            except Exception:
                pass

            stdout_handle = open(STDOUT_PATH, "w", encoding="utf-8")
            stderr_handle = open(STDERR_PATH, "w", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                backend_cmd,
                cwd=str(APP_DIR),
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=env,
            )

            def _on_started():
                self.backend_stdout_handle = stdout_handle
                self.backend_stderr_handle = stderr_handle
                self.backend_proc = proc
                self._stdout_read_pos = 0
                self._stderr_read_pos = 0
                self.status_var.set("ACTIVE")
                self._set_status_badge(True)
                self._append_log(f"Backend started (PID {self.backend_proc.pid}).")

            self._run_on_ui(_on_started)
        except Exception as exc:
            try:
                if stdout_handle:
                    stdout_handle.close()
            except Exception:
                pass
            try:
                if stderr_handle:
                    stderr_handle.close()
            except Exception:
                pass
            self._append_log_async(f"Failed to start backend: {exc}")
            self._run_on_ui(lambda: messagebox.showerror(APP_TITLE, f"Failed to start backend: {exc}"))
        finally:
            self._run_on_ui(lambda: self._set_backend_action_in_progress(False))

    def _run_start_preflight_checks(self, router_model):
        if not getattr(sys, "frozen", False):
            missing_modules = []
            for module_name in ("fastapi", "openai", "uvicorn"):
                try:
                    __import__(module_name)
                except Exception:
                    missing_modules.append(module_name)
            if missing_modules:
                missing_str = ", ".join(missing_modules)
                return (
                    f"Missing Python packages: {missing_str}. "
                    f"Install with: {sys.executable} -m pip install {missing_str}"
                )

        ollama_path = shutil.which("ollama")
        if not ollama_path:
            return "Ollama is not installed or not on PATH."

        try:
            result = subprocess.run(
                [ollama_path, "list"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            return f"Could not verify Ollama models: {exc}"

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            return f"Ollama check failed: {detail}"

        model_names = set()
        for line in (result.stdout or "").splitlines():
            if not line.strip() or line.strip().upper().startswith("NAME"):
                continue
            model_name = line.split()[0].strip().lower()
            model_names.add(model_name)
            if model_name.endswith(":latest"):
                model_names.add(model_name[: -len(":latest")])

        if router_model.lower() not in model_names:
            return (
                f"Router model '{router_model}' is not pulled in Ollama. "
                f"Run: ollama pull {router_model}"
            )

        return None

    def _stop_backend(self):
        if self._backend_action_in_progress:
            self._append_log("Backend action already in progress. Please wait...")
            return

        if not self.backend_proc or self.backend_proc.poll() is not None:
            self.backend_proc = None
            self._close_backend_handles()
            self.status_var.set("INACTIVE")
            self._set_status_badge(False)
            return

        proc = self.backend_proc
        self._set_backend_action_in_progress(True)
        self._append_log("Stopping backend...")
        worker = threading.Thread(target=self._stop_backend_worker, args=(proc,), daemon=True)
        worker.start()

    def _stop_backend_worker(self, proc):
        stop_msg = "Backend stopped."
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            stop_msg = "Backend force-killed."
        except Exception as exc:
            stop_msg = f"Failed to stop backend cleanly: {exc}"
        finally:
            def _on_stopped():
                if self.backend_proc is proc:
                    self.backend_proc = None
                self.status_var.set("INACTIVE")
                self._set_status_badge(False)
                self._close_backend_handles()
                self._append_log(stop_msg)
                self._set_backend_action_in_progress(False)

            self._run_on_ui(_on_stopped)

    def _set_status_badge(self, is_active: bool):
        if is_active:
            self.status_var.set("ACTIVE")
            self.status_badge.set("ACTIVE", THEME["ok"])
        else:
            self.status_var.set("INACTIVE")
            self.status_badge.set("INACTIVE", THEME["bad"])

    def _close_backend_handles(self):
        for handle in (self.backend_stdout_handle, self.backend_stderr_handle):
            try:
                if handle:
                    handle.close()
            except Exception:
                pass
        self.backend_stdout_handle = None
        self.backend_stderr_handle = None

    def _open_file(self, path: Path):
        try:
            if not path.exists():
                path.touch()
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to open file: {exc}")

    def _initialize_log_tail_positions(self):
        try:
            self._stdout_read_pos = STDOUT_PATH.stat().st_size if STDOUT_PATH.exists() else 0
        except Exception:
            self._stdout_read_pos = 0
        try:
            self._stderr_read_pos = STDERR_PATH.stat().st_size if STDERR_PATH.exists() else 0
        except Exception:
            self._stderr_read_pos = 0

    def _refresh_status_labels(self):
        tok = self._load_json(TOKENS_PATH, DEFAULT_TOKENS)
        total = int(tok.get("total_tokens", 0))
        session = int(tok.get("session_tokens", 0))

        total_prompt = int(tok.get("total_prompt_tokens", 0))
        total_completion = int(tok.get("total_completion_tokens", 0))
        in_cost_per_m = self._to_float(self.input_token_cost_var.get())
        out_cost_per_m = self._to_float(self.output_token_cost_var.get())

        total_cost = (total_prompt / 1_000_000.0) * in_cost_per_m + (total_completion / 1_000_000.0) * out_cost_per_m

        self.total_tokens_var.set(f"{total:,}")
        self.session_tokens_var.set(f"{session:,}")
        self.cost_var.set(f"${total_cost:,.4f}")

    def _tail_log_file(self, file_path: Path, start_pos: int) -> int:
        if not file_path.exists():
            return start_pos
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start_pos)
                chunk = f.read()
                new_pos = f.tell()
            if chunk:
                for line in chunk.splitlines():
                    if line.strip():
                        self._append_log(line)
            return new_pos
        except Exception:
            return start_pos

    def _poll_backend_logs(self):
        if not self.backend_proc or self.backend_proc.poll() is not None:
            return
        self._stdout_read_pos = self._tail_log_file(STDOUT_PATH, self._stdout_read_pos)
        self._stderr_read_pos = self._tail_log_file(STDERR_PATH, self._stderr_read_pos)

    def _periodic_refresh(self):
        try:
            if self.backend_proc and self.backend_proc.poll() is not None:
                self._append_log(f"Backend exited (code {self.backend_proc.returncode}).")
                self.backend_proc = None
                self._close_backend_handles()
                self._set_status_badge(False)

            if self.backend_proc and self.backend_proc.poll() is None:
                self._set_status_badge(True)
            else:
                self._set_status_badge(False)

            self._poll_backend_logs()
            self._refresh_status_labels()
            self._poll_intercepts()
        except Exception as exc:
            self._append_log(f"UI refresh warning: {exc}")
        finally:
            self.after(1000, self._periodic_refresh)

    def _on_close(self):
        self._stop_backend()
        self.destroy()


if __name__ == "__main__":
    app = BridgeApp()
    app.mainloop()
