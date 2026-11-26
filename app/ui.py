"""Easy-to-use Windows Desktop UI for AIgiveaway using CustomTkinter + System Tray."""

from __future__ import annotations

import datetime
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import customtkinter as ctk
from PIL import Image

from app import __app_name__, __version__
from app.agent_engine import AgentStats, GiveawayAgentEngine
from app.config import AppConfig
from app.gemini_client import AVAILABLE_MODELS, GeminiVisionClient
from app.icon_gen import create_app_icon_image
from app.window_controller import (
    ScopedWindowController,
    WindowInfo,
    list_selectable_windows,
    pick_window_on_next_click,
)

try:
    import pystray
except ImportError:
    pystray = None


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AIgiveawayApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{__app_name__} v{__version__} — Cymatics Live Freebie & Giveaway AI")
        self.geometry("1040x720")
        self.minsize(920, 640)

        self.config_data = AppConfig.load()
        self._windows_map: Dict[str, WindowInfo] = {}
        self._tray_icon = None
        self._preview_photo: Optional[ctk.CTkImage] = None
        self._show_key = False

        self.engine = GiveawayAgentEngine(
            config=self.config_data,
            on_log=lambda msg: self.after(0, self._append_log, msg),
            on_status=lambda st: self.after(0, self._update_status, st),
            on_preview=lambda img: self.after(0, self._update_preview, img),
            on_stats=lambda st: self.after(0, self._update_stats, st),
        )

        self._set_window_icon()
        self._build_ui()
        self._refresh_windows()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_window_icon(self) -> None:
        if sys.platform == "win32":
            ico_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / "app.ico"
            if ico_path.exists():
                try:
                    self.iconbitmap(str(ico_path))
                except Exception:
                    pass

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, corner_radius=12, fg_color="#0f172a")
        header.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.grid(row=0, column=0, padx=16, pady=12, sticky="w")
        ctk.CTkLabel(
            title_col,
            text=f"AIgiveaway v{__version__}",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#38bdf8",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_col,
            text="Window-Scoped Local AI for Cymatics.fm Free Drops & Giveaways",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
        ).pack(anchor="w")

        self.status_badge = ctk.CTkLabel(
            header,
            text="● AI OFF",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f87171",
            fg_color="#1e293b",
            corner_radius=8,
            padx=14,
            pady=6,
        )
        self.status_badge.grid(row=0, column=1, padx=12, sticky="e")

        self.power_btn = ctk.CTkButton(
            header,
            text="TURN AI ON",
            width=180,
            height=48,
            corner_radius=10,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._toggle_ai,
        )
        self.power_btn.grid(row=0, column=2, padx=(6, 16), pady=12)

        setup = ctk.CTkFrame(self, corner_radius=12)
        setup.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        setup.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            setup,
            text="Allowed Window ONLY:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 8), pady=(12, 6), sticky="w")

        self.window_var = ctk.StringVar(value="Select a browser window...")
        self.window_menu = ctk.CTkOptionMenu(
            setup,
            variable=self.window_var,
            values=["Click Refresh or Pick Browser..."],
            dynamic_resizing=False,
        )
        self.window_menu.grid(row=0, column=1, columnspan=2, padx=4, pady=(12, 6), sticky="ew")

        win_btns = ctk.CTkFrame(setup, fg_color="transparent")
        win_btns.grid(row=0, column=3, padx=(6, 14), pady=(12, 6), sticky="e")

        self.pick_btn = ctk.CTkButton(
            win_btns,
            text="Pick Browser",
            width=102,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            command=self._pick_window_clicked,
        )
        self.pick_btn.pack(side="left", padx=2)
        ctk.CTkButton(win_btns, text="Refresh", width=70, command=self._refresh_windows).pack(side="left", padx=2)
        ctk.CTkButton(
            win_btns,
            text="Highlight",
            width=74,
            fg_color="#334155",
            hover_color="#475569",
            command=self._highlight_selected_window,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            win_btns,
            text="Open Cymatics",
            width=108,
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=lambda: webbrowser.open(self.url_entry.get().strip() or "https://cymatics.fm/"),
        ).pack(side="left", padx=2)

        ctk.CTkLabel(setup, text="Tracked Page URL:", font=ctk.CTkFont(size=13)).grid(
            row=1, column=0, padx=(14, 8), pady=6, sticky="w"
        )
        self.url_entry = ctk.CTkEntry(setup, placeholder_text="https://cymatics.fm/")
        self.url_entry.insert(0, self.config_data.target_url)
        self.url_entry.grid(row=1, column=1, padx=4, pady=6, sticky="ew")

        ctk.CTkLabel(setup, text="Giveaway Email:", font=ctk.CTkFont(size=13)).grid(
            row=1, column=2, padx=(14, 8), pady=6, sticky="w"
        )
        self.email_entry = ctk.CTkEntry(setup, placeholder_text="karankrajbhar23@gmail.com")
        self.email_entry.insert(0, self.config_data.giveaway_email)
        self.email_entry.grid(row=1, column=3, padx=(4, 14), pady=6, sticky="ew")

        ctk.CTkLabel(setup, text="Gemini API Key:", font=ctk.CTkFont(size=13)).grid(
            row=2, column=0, padx=(14, 8), pady=6, sticky="w"
        )
        key_frame = ctk.CTkFrame(setup, fg_color="transparent")
        key_frame.grid(row=2, column=1, padx=4, pady=6, sticky="ew")
        key_frame.grid_columnconfigure(0, weight=1)

        self.api_key_entry = ctk.CTkEntry(key_frame, show="*", placeholder_text="Paste your AQ... or AIza... API key")
        if self.config_data.api_key:
            self.api_key_entry.insert(0, self.config_data.api_key)
        self.api_key_entry.grid(row=0, column=0, sticky="ew")

        self.show_key_btn = ctk.CTkButton(
            key_frame, text="Show", width=55, fg_color="#334155", command=self._toggle_show_key
        )
        self.show_key_btn.grid(row=0, column=1, padx=(4, 2))
        ctk.CTkButton(
            key_frame, text="Test", width=55, fg_color="#0ea5e9", command=self._test_api_key
        ).grid(row=0, column=2, padx=2)

        ctk.CTkLabel(setup, text="Model & Speed:", font=ctk.CTkFont(size=13)).grid(
            row=2, column=2, padx=(14, 8), pady=6, sticky="w"
        )
        model_frame = ctk.CTkFrame(setup, fg_color="transparent")
        model_frame.grid(row=2, column=3, padx=(4, 14), pady=6, sticky="ew")
        self.model_var = ctk.StringVar(value=self.config_data.model)
        ctk.CTkOptionMenu(model_frame, variable=self.model_var, values=AVAILABLE_MODELS, width=165).pack(
            side="left", padx=(0, 6)
        )
        self.interval_entry = ctk.CTkEntry(model_frame, width=58)
        self.interval_entry.insert(0, str(self.config_data.scan_interval_sec))
        self.interval_entry.pack(side="left")
        ctk.CTkLabel(model_frame, text="sec", text_color="#94a3b8").pack(side="left", padx=4)

        toggles = ctk.CTkFrame(setup, fg_color="transparent")
        toggles.grid(row=3, column=0, columnspan=4, padx=14, pady=(6, 12), sticky="ew")

        self.var_add_free = ctk.BooleanVar(value=self.config_data.auto_add_free)
        self.var_learn_more = ctk.BooleanVar(value=self.config_data.auto_check_learn_more)
        self.var_checkout = ctk.BooleanVar(value=self.config_data.auto_checkout_free_only)
        self.var_giveaway = ctk.BooleanVar(value=self.config_data.auto_answer_giveaway)
        self.var_return = ctk.BooleanVar(value=self.config_data.auto_return_to_page)
        self.var_bg_mode = ctk.BooleanVar(value=(self.config_data.background_input_mode == "background"))
        self.var_tray = ctk.BooleanVar(value=self.config_data.minimize_to_tray)

        ctk.CTkCheckBox(toggles, text="Add Free Stuff", variable=self.var_add_free).grid(row=0, column=0, padx=8, pady=3, sticky="w")
        ctk.CTkCheckBox(toggles, text="Check 'Learn More'", variable=self.var_learn_more).grid(row=0, column=1, padx=8, pady=3, sticky="w")
        ctk.CTkCheckBox(toggles, text="Auto-Checkout ($0 Only)", variable=self.var_checkout).grid(row=0, column=2, padx=8, pady=3, sticky="w")
        ctk.CTkCheckBox(toggles, text="Fast Giveaway Q&A", variable=self.var_giveaway).grid(row=0, column=3, padx=8, pady=3, sticky="w")

        ctk.CTkCheckBox(toggles, text="Return to Page After Order", variable=self.var_return).grid(row=1, column=0, padx=8, pady=3, sticky="w")
        ctk.CTkCheckBox(toggles, text="Background Input (No Cursor Hijack)", variable=self.var_bg_mode).grid(
            row=1, column=1, columnspan=2, padx=8, pady=3, sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="Hide to System Tray on Close", variable=self.var_tray).grid(row=1, column=3, padx=8, pady=3, sticky="w")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, padx=16, pady=(6, 14), sticky="nsew")
        bottom.grid_columnconfigure(0, weight=2)
        bottom.grid_columnconfigure(1, weight=3)
        bottom.grid_rowconfigure(0, weight=1)

        preview_card = ctk.CTkFrame(bottom, corner_radius=12)
        preview_card.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        preview_card.grid_rowconfigure(1, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            preview_card,
            text="Allowed Window View (Desktop Hidden)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8",
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="Click 'Pick Browser' (or use the dropdown)\nto lock onto your Cymatics browser window,\nthen click TURN AI ON.",
            text_color="#64748b",
            fg_color="#0b1120",
            corner_radius=8,
        )
        self.preview_label.grid(row=1, column=0, padx=12, pady=6, sticky="nsew")

        self.stats_label = ctk.CTkLabel(
            preview_card,
            text="Scans: 0  |  Free Added: 0  |  $0 Orders: 0  |  Giveaways: 0",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1",
        )
        self.stats_label.grid(row=2, column=0, padx=12, pady=(4, 10))

        log_card = ctk.CTkFrame(bottom, corner_radius=12)
        log_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)

        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="ew")
        ctk.CTkLabel(log_hdr, text="Live Activity Log", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(
            log_hdr,
            text="Save Settings",
            width=105,
            height=26,
            fg_color="#334155",
            command=self._save_settings_clicked,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            log_hdr,
            text="Clear Claimed",
            width=100,
            height=26,
            fg_color="#334155",
            command=self._clear_claimed_items,
        ).pack(side="right", padx=4)

        self.log_box = ctk.CTkTextbox(log_card, font=ctk.CTkFont(family="Consolas", size=12), state="disabled")
        self.log_box.grid(row=1, column=0, padx=12, pady=(4, 12), sticky="nsew")

        self._append_log("Ready. Click 'Pick Browser' (or choose from dropdown), test your API key, and click TURN AI ON.")

    def _collect_config(self) -> AppConfig:
        try:
            interval = max(0.8, float(self.interval_entry.get().strip()))
        except ValueError:
            interval = 2.5

        self.config_data.api_key = self.api_key_entry.get().strip()
        self.config_data.model = self.model_var.get().strip()
        self.config_data.target_url = self.url_entry.get().strip() or "https://cymatics.fm/"
        self.config_data.giveaway_email = self.email_entry.get().strip() or "karankrajbhar23@gmail.com"
        self.config_data.scan_interval_sec = interval
        self.config_data.auto_add_free = bool(self.var_add_free.get())
        self.config_data.auto_check_learn_more = bool(self.var_learn_more.get())
        self.config_data.auto_checkout_free_only = bool(self.var_checkout.get())
        self.config_data.auto_answer_giveaway = bool(self.var_giveaway.get())
        self.config_data.auto_return_to_page = bool(self.var_return.get())
        self.config_data.background_input_mode = "background" if self.var_bg_mode.get() else "scoped_focus"
        self.config_data.minimize_to_tray = bool(self.var_tray.get())

        selected = self._windows_map.get(self.window_var.get())
        if selected:
            self.config_data.last_window_title = selected.title
        return self.config_data

    def _save_settings_clicked(self) -> None:
        cfg = self._collect_config()
        path = cfg.save()
        self._append_log(f"Settings saved locally to {path}")

    def _clear_claimed_items(self) -> None:
        self.config_data.claimed_items.clear()
        self.config_data.save()
        self._append_log("Cleared claimed items history.")

    def _toggle_show_key(self) -> None:
        self._show_key = not self._show_key
        self.api_key_entry.configure(show="" if self._show_key else "*")
        self.show_key_btn.configure(text="Hide" if self._show_key else "Show")

    def _test_api_key(self) -> None:
        cfg = self._collect_config()
        if not cfg.api_key:
            self._append_log("[ERROR] Paste your Gemini API key first.")
            return
        self._append_log(f"Testing Gemini API key with {cfg.model} (auto-fallback enabled)...")

        def _worker() -> None:
            client = GeminiVisionClient(cfg.api_key, model=cfg.model, endpoint_mode=cfg.api_endpoint_mode)
            ok, msg = client.test_connection()
            if ok and client.model != cfg.model:
                self.after(0, self.model_var.set, client.model)
            prefix = "[OK]" if ok else "[FAILED]"
            self.after(0, self._append_log, f"{prefix} {msg}")

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_windows(self) -> None:
        wins: List[WindowInfo] = list_selectable_windows()
        self._windows_map = {w.display_label: w for w in wins}

        labels = list(self._windows_map.keys())
        if not labels:
            labels = ["No windows found — open Chrome/Edge & click Refresh"]
            self.window_menu.configure(values=labels)
            self.window_var.set(labels[0])
            return

        self.window_menu.configure(values=labels)
        chosen = labels[0]
        for lbl, win in self._windows_map.items():
            if self.config_data.last_window_title and self.config_data.last_window_title == win.title:
                chosen = lbl
                break
        self.window_var.set(chosen)
        self._append_log(f"Found {len(wins)} windows ({sum(1 for w in wins if w.is_browser)} browser windows).")

    def _pick_window_clicked(self) -> None:
        self.pick_btn.configure(text="Click Browser...", state="disabled")
        self._append_log("Click directly on your Cymatics browser window now (or press ESC to cancel)...")

        def _worker() -> None:
            picked = pick_window_on_next_click(timeout_sec=15.0)
            self.after(0, self._finish_pick_window, picked)

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_pick_window(self, picked: Optional[WindowInfo]) -> None:
        self.pick_btn.configure(text="Pick Browser", state="normal")
        if picked is None:
            self._append_log("Window pick cancelled or timed out.")
            return
        label = picked.display_label
        self._windows_map[label] = picked
        self.window_menu.configure(values=list(self._windows_map.keys()))
        self.window_var.set(label)
        self.config_data.last_window_title = picked.title
        self._append_log(f"Locked onto browser window: '{picked.title}'")

    def _highlight_selected_window(self) -> None:
        win = self._windows_map.get(self.window_var.get())
        if not win:
            self._append_log("Select a valid window first.")
            return
        ctrl = ScopedWindowController(win.hwnd)
        ctrl.flash_highlight()
        self._append_log(f"Highlighted allowed window: '{win.title}'")

    def _toggle_ai(self) -> None:
        if self.engine.is_running:
            self.engine.stop()
            self._set_button_off()
            return

        cfg = self._collect_config()
        cfg.save()

        if not cfg.api_key:
            self._append_log("[ERROR] Please paste your Gemini API key before turning AI ON.")
            return

        win = self._windows_map.get(self.window_var.get())
        if not win:
            self._append_log("[ERROR] Please select or pick your Cymatics browser window first.")
            return

        ctrl = ScopedWindowController(win.hwnd)
        ctrl.restore_if_minimized()
        self.engine.start(hwnd=win.hwnd, config=cfg)
        self.power_btn.configure(text="TURN AI OFF", fg_color="#dc2626", hover_color="#b91c1c")

    def _set_button_off(self) -> None:
        self.power_btn.configure(text="TURN AI ON", fg_color="#16a34a", hover_color="#15803d")

    def _update_status(self, status: str) -> None:
        if status == "STOPPED":
            self.status_badge.configure(text="● AI OFF", text_color="#f87171")
            self._set_button_off()
        elif status == "ERROR":
            self.status_badge.configure(text="● API ERROR", text_color="#fbbf24")
        elif "PAUSED" in status:
            self.status_badge.configure(text=f"● {status}", text_color="#fbbf24")
        else:
            self.status_badge.configure(text=f"● AI ON — {status}", text_color="#4ade80")

    def _update_stats(self, stats: AgentStats) -> None:
        self.stats_label.configure(
            text=(
                f"Scans: {stats.scans}  |  Free Added: {stats.free_items_added}  |  "
                f"$0 Orders: {stats.checkouts_completed}  |  Giveaways: {stats.giveaways_answered}"
            )
        )

    def _update_preview(self, img: Image.Image) -> None:
        thumb = img.copy()
        thumb.thumbnail((360, 240))
        self._preview_photo = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=thumb.size)
        self.preview_label.configure(image=self._preview_photo, text="")

    def _append_log(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        cfg = self._collect_config()
        cfg.save()
        if cfg.minimize_to_tray and pystray is not None:
            self.withdraw()
            self._start_tray_icon()
        else:
            self._quit_app()

    def _start_tray_icon(self) -> None:
        if self._tray_icon is not None or pystray is None:
            return
        icon_img = create_app_icon_image(64)
        menu = pystray.Menu(
            pystray.MenuItem("Show AIgiveaway", lambda: self.after(0, self._restore_from_tray), default=True),
            pystray.MenuItem("Toggle AI ON/OFF", lambda: self.after(0, self._toggle_ai)),
            pystray.MenuItem("Quit", lambda: self.after(0, self._quit_app)),
        )
        self._tray_icon = pystray.Icon(__app_name__, icon_img, __app_name__, menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _restore_from_tray(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.deiconify()
        self.lift()

    def _quit_app(self) -> None:
        self.engine.stop()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.destroy()
