"""Easy-to-use Windows Desktop UI for AIgiveaway v1.1.1.

Features:
- One-dropdown AI Model switcher across Gemini, Ollama Cloud, Vercel AI Gateway, and Ollama Local
- All API keys saved permanently in %APPDATA%\\AIgiveaway\\config.json (auto-saved, never lost on switch/update)
- Browser Selector Addon (Chrome, Brave, Opera, Edge, Firefox, Vivaldi, Arc, All Windows) + Pick Window
- Live Stream & Website Link Tracker tab with real-time link discovery
- One-click ON / OFF button + System Tray background mode
"""

from __future__ import annotations

import datetime
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

import customtkinter as ctk
from PIL import Image

from app import __app_name__, __version__
from app.agent_engine import AgentStats, GiveawayAgentEngine
from app.config import AppConfig
from app.gemini_client import (
    UNIFIED_MODEL_PRESETS,
    MultiProviderVisionClient,
    preset_label_for,
)
from app.icon_gen import create_app_icon_image
from app.link_monitor import LiveWebsiteLinkMonitor, TrackedLink
from app.window_controller import (
    BROWSER_FILTER_OPTIONS,
    ScopedWindowController,
    WindowInfo,
    launch_browser_with_url,
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
    """Main desktop window for AIgiveaway."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{__app_name__} v{__version__} — Multi-AI Cymatics Live Drop & Stream Tracker")
        self.geometry("1120x770")
        self.minsize(980, 680)

        self.config_data = AppConfig.load()
        self._windows_map: Dict[str, WindowInfo] = {}
        self._tracked_links: List[TrackedLink] = []
        self._tray_icon = None
        self._preview_photo: Optional[ctk.CTkImage] = None
        self._show_keys = False

        self.link_monitor = LiveWebsiteLinkMonitor(
            on_links_updated=lambda all_l, new_l: self.after(0, self._on_links_updated, all_l, new_l),
            on_log=lambda msg: self.after(0, self._append_log, msg),
        )

        self.engine = GiveawayAgentEngine(
            config=self.config_data,
            on_log=lambda msg: self.after(0, self._append_log, msg),
            on_status=lambda st: self.after(0, self._update_status, st),
            on_preview=lambda img: self.after(0, self._update_preview, img),
            on_stats=lambda st: self.after(0, self._update_stats, st),
            on_detected_urls=lambda urls: self.link_monitor.add_screen_urls(urls),
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

        # ==================== 1. TOP HEADER & BIG ON/OFF BAR ====================
        header = ctk.CTkFrame(self, corner_radius=12, fg_color="#0f172a")
        header.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.grid(row=0, column=0, padx=16, pady=10, sticky="w")
        ctk.CTkLabel(
            title_col,
            text=f"AIgiveaway v{__version__}",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#38bdf8",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_col,
            text="One-Dropdown Multi-AI (Gemini / Ollama / Vercel) • Window-Scoped • Live Stream & Link Tracker",
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
            width=175,
            height=46,
            corner_radius=10,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._toggle_ai,
        )
        self.power_btn.grid(row=0, column=2, padx=(6, 16), pady=10)

        # ==================== 2. QUICK SETUP CARD ====================
        setup = ctk.CTkFrame(self, corner_radius=12)
        setup.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        setup.grid_columnconfigure(2, weight=1)
        setup.grid_columnconfigure(4, weight=1)

        # Row 0: Browser Selector Addon (Chrome, Brave, Opera, etc.) + Allowed Window
        ctk.CTkLabel(setup, text="Browser & Window:", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=(14, 6), pady=(10, 5), sticky="w"
        )
        self.browser_filter_var = ctk.StringVar(value=self.config_data.browser_filter)
        ctk.CTkOptionMenu(
            setup,
            variable=self.browser_filter_var,
            values=BROWSER_FILTER_OPTIONS,
            width=125,
            command=lambda _v: self._refresh_windows(),
        ).grid(row=0, column=1, padx=4, pady=(10, 5), sticky="w")

        self.window_var = ctk.StringVar(value="Select a browser window...")
        self.window_menu = ctk.CTkOptionMenu(
            setup,
            variable=self.window_var,
            values=["Click Refresh or Pick Window..."],
            dynamic_resizing=False,
        )
        self.window_menu.grid(row=0, column=2, columnspan=2, padx=4, pady=(10, 5), sticky="ew")

        win_btns = ctk.CTkFrame(setup, fg_color="transparent")
        win_btns.grid(row=0, column=4, padx=(6, 14), pady=(10, 5), sticky="e")

        self.pick_btn = ctk.CTkButton(
            win_btns, text="Pick Window", width=96, fg_color="#7c3aed", hover_color="#6d28d9", command=self._pick_window_clicked
        )
        self.pick_btn.pack(side="left", padx=2)
        ctk.CTkButton(win_btns, text="Refresh", width=66, command=self._refresh_windows).pack(side="left", padx=2)
        ctk.CTkButton(
            win_btns, text="Highlight", width=70, fg_color="#334155", hover_color="#475569", command=self._highlight_selected_window
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            win_btns, text="Open Site", width=78, fg_color="#0284c7", hover_color="#0369a1", command=self._open_in_selected_browser
        ).pack(side="left", padx=2)

        # Row 1: Unified One-Dropdown AI Model Selector + Test AI + Speed
        ctk.CTkLabel(setup, text="AI Model (Instant):", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=1, column=0, padx=(14, 6), pady=5, sticky="w"
        )
        initial_preset = preset_label_for(self.config_data.ai_provider, self.config_data.model)
        self.unified_model_var = ctk.StringVar(value=initial_preset)
        self.unified_model_menu = ctk.CTkOptionMenu(
            setup,
            variable=self.unified_model_var,
            values=list(UNIFIED_MODEL_PRESETS.keys()),
            command=self._on_unified_model_changed,
        )
        self.unified_model_menu.grid(row=1, column=1, columnspan=2, padx=4, pady=5, sticky="ew")

        ai_ctrl = ctk.CTkFrame(setup, fg_color="transparent")
        ai_ctrl.grid(row=1, column=3, columnspan=2, padx=(4, 14), pady=5, sticky="ew")
        ctk.CTkButton(ai_ctrl, text="Test AI", width=76, fg_color="#0ea5e9", command=self._test_api_key).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(ai_ctrl, text="Speed:", text_color="#94a3b8").pack(side="left")
        self.interval_entry = ctk.CTkEntry(ai_ctrl, width=52)
        self.interval_entry.insert(0, str(self.config_data.scan_interval_sec))
        self.interval_entry.pack(side="left", padx=4)
        ctk.CTkLabel(ai_ctrl, text="sec", text_color="#94a3b8").pack(side="left", padx=(0, 12))

        ctk.CTkLabel(ai_ctrl, text="Email:", text_color="#94a3b8").pack(side="left")
        self.email_entry = ctk.CTkEntry(ai_ctrl, placeholder_text="karankrajbhar23@gmail.com")
        self.email_entry.insert(0, self.config_data.giveaway_email)
        self.email_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Row 2: Tracked Website / Livestream URL + Scan Links Now
        ctk.CTkLabel(setup, text="Tracked Page URL:", font=ctk.CTkFont(size=13)).grid(
            row=2, column=0, padx=(14, 6), pady=5, sticky="w"
        )
        url_frame = ctk.CTkFrame(setup, fg_color="transparent")
        url_frame.grid(row=2, column=1, columnspan=4, padx=(4, 14), pady=5, sticky="ew")
        url_frame.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="https://cymatics.fm/")
        self.url_entry.insert(0, self.config_data.target_url)
        self.url_entry.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(
            url_frame,
            text="Scan Website Links Now",
            width=165,
            fg_color="#0f766e",
            hover_color="#115e59",
            command=self._scan_links_now,
        ).grid(row=0, column=1, padx=(8, 0))

        # Row 3: Feature Toggles
        toggles = ctk.CTkFrame(setup, fg_color="transparent")
        toggles.grid(row=3, column=0, columnspan=5, padx=14, pady=(4, 10), sticky="ew")

        self.var_add_free = ctk.BooleanVar(value=self.config_data.auto_add_free)
        self.var_learn_more = ctk.BooleanVar(value=self.config_data.auto_check_learn_more)
        self.var_checkout = ctk.BooleanVar(value=self.config_data.auto_checkout_free_only)
        self.var_giveaway = ctk.BooleanVar(value=self.config_data.auto_answer_giveaway)
        self.var_return = ctk.BooleanVar(value=self.config_data.auto_return_to_page)
        self.var_live_links = ctk.BooleanVar(value=self.config_data.monitor_live_links)
        self.var_auto_open_drops = ctk.BooleanVar(value=self.config_data.auto_open_new_drops)
        self.var_bg_mode = ctk.BooleanVar(value=(self.config_data.background_input_mode == "background"))
        self.var_tray = ctk.BooleanVar(value=self.config_data.minimize_to_tray)

        ctk.CTkCheckBox(toggles, text="Add Free Stuff", variable=self.var_add_free).grid(row=0, column=0, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(toggles, text="Check 'Learn More'", variable=self.var_learn_more).grid(row=0, column=1, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(toggles, text="Auto-Checkout ($0 Only)", variable=self.var_checkout).grid(row=0, column=2, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(toggles, text="Fast Giveaway Q&A", variable=self.var_giveaway).grid(row=0, column=3, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(toggles, text="Return After Order", variable=self.var_return).grid(row=0, column=4, padx=8, pady=2, sticky="w")

        ctk.CTkCheckBox(toggles, text="Live Stream & Link Monitor", variable=self.var_live_links).grid(row=1, column=0, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(toggles, text="Auto-Open New Free Drops", variable=self.var_auto_open_drops).grid(row=1, column=1, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(toggles, text="Background Input (No Cursor Hijack)", variable=self.var_bg_mode).grid(
            row=1, column=2, columnspan=2, padx=8, pady=2, sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="Hide to Tray on Close", variable=self.var_tray).grid(row=1, column=4, padx=8, pady=2, sticky="w")

        # ==================== 3. LIVE PREVIEW + 3 TABS ====================
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, padx=16, pady=(4, 14), sticky="nsew")
        bottom.grid_columnconfigure(0, weight=2)
        bottom.grid_columnconfigure(1, weight=3)
        bottom.grid_rowconfigure(0, weight=1)

        preview_card = ctk.CTkFrame(bottom, corner_radius=12)
        preview_card.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        preview_card.grid_rowconfigure(1, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            preview_card,
            text="Allowed Browser Window View (Desktop Hidden)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8",
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="1. Select Browser (Chrome/Brave/Opera) or Pick Window\n2. Pick ANY AI Model from the dropdown (keys auto-saved)\n3. Click 'TURN AI ON' to track drops & giveaways live",
            text_color="#64748b",
            fg_color="#0b1120",
            corner_radius=8,
        )
        self.preview_label.grid(row=1, column=0, padx=12, pady=6, sticky="nsew")

        self.stats_label = ctk.CTkLabel(
            preview_card,
            text="Scans: 0  |  Free: 0  |  $0 Orders: 0  |  Giveaways: 0  |  Links: 0",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1",
        )
        self.stats_label.grid(row=2, column=0, padx=12, pady=(4, 10))

        right_tabs = ctk.CTkTabview(bottom, corner_radius=12)
        right_tabs.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        tab_log = right_tabs.add("Live Activity Log")
        tab_links = right_tabs.add("Live Stream & Website Links")
        tab_keys = right_tabs.add("Saved API Keys")

        # Tab 1: Activity Log
        tab_log.grid_rowconfigure(1, weight=1)
        tab_log.grid_columnconfigure(0, weight=1)
        log_hdr = ctk.CTkFrame(tab_log, fg_color="transparent")
        log_hdr.grid(row=0, column=0, padx=6, pady=(2, 4), sticky="ew")
        ctk.CTkButton(log_hdr, text="Save Settings", width=105, height=26, fg_color="#334155", command=self._save_settings_clicked).pack(
            side="right", padx=3
        )
        ctk.CTkButton(log_hdr, text="Clear Claimed", width=100, height=26, fg_color="#334155", command=self._clear_claimed_items).pack(
            side="right", padx=3
        )
        self.log_box = ctk.CTkTextbox(tab_log, font=ctk.CTkFont(family="Consolas", size=12), state="disabled")
        self.log_box.grid(row=1, column=0, padx=6, pady=(2, 6), sticky="nsew")

        # Tab 2: Live Stream & Website Links
        tab_links.grid_rowconfigure(1, weight=1)
        tab_links.grid_columnconfigure(0, weight=1)
        links_bar = ctk.CTkFrame(tab_links, fg_color="transparent")
        links_bar.grid(row=0, column=0, padx=6, pady=(2, 4), sticky="ew")

        self.link_filter_var = ctk.StringVar(value="All Links")
        ctk.CTkOptionMenu(
            links_bar,
            variable=self.link_filter_var,
            values=["All Links", "FREE / DROP", "LIVESTREAM", "PRODUCT", "NEW Only"],
            width=130,
            height=26,
            command=lambda _v: self._render_links_view(),
        ).pack(side="left", padx=(0, 6))
        self.links_count_label = ctk.CTkLabel(links_bar, text="0 live links tracked", text_color="#94a3b8")
        self.links_count_label.pack(side="left", padx=6)
        ctk.CTkButton(links_bar, text="Refresh Links", width=100, height=26, fg_color="#0f766e", command=self._scan_links_now).pack(
            side="right", padx=3
        )

        self.links_scroll = ctk.CTkScrollableFrame(tab_links, fg_color="#0b1120", corner_radius=8)
        self.links_scroll.grid(row=1, column=0, padx=6, pady=(2, 6), sticky="nsew")
        self.links_scroll.grid_columnconfigure(0, weight=1)

        # Tab 3: Permanent Saved API Keys (All 3 stored simultaneously — never re-enter!)
        tab_keys.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            tab_keys,
            text="All API keys are saved permanently in %APPDATA%\\AIgiveaway\\config.json.\nSwitch AI models anytime from the top dropdown without re-entering keys.",
            text_color="#94a3b8",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 12), sticky="w")

        ctk.CTkLabel(tab_keys, text="Google Gemini Key:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.gemini_key_entry = ctk.CTkEntry(tab_keys, show="*", placeholder_text="AQ... or AIza...")
        if self.config_data.api_key:
            self.gemini_key_entry.insert(0, self.config_data.api_key)
        self.gemini_key_entry.grid(row=1, column=1, padx=10, pady=6, sticky="ew")

        ctk.CTkLabel(tab_keys, text="Ollama Cloud Key:", font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, padx=10, pady=6, sticky="w")
        self.ollama_key_entry = ctk.CTkEntry(tab_keys, show="*", placeholder_text="Ollama Cloud API key")
        if self.config_data.ollama_api_key:
            self.ollama_key_entry.insert(0, self.config_data.ollama_api_key)
        self.ollama_key_entry.grid(row=2, column=1, padx=10, pady=6, sticky="ew")

        ctk.CTkLabel(tab_keys, text="Vercel AI Gateway Key:", font=ctk.CTkFont(weight="bold")).grid(row=3, column=0, padx=10, pady=6, sticky="w")
        self.vercel_key_entry = ctk.CTkEntry(tab_keys, show="*", placeholder_text="vck_...")
        if self.config_data.vercel_api_key:
            self.vercel_key_entry.insert(0, self.config_data.vercel_api_key)
        self.vercel_key_entry.grid(row=3, column=1, padx=10, pady=6, sticky="ew")

        key_btns = ctk.CTkFrame(tab_keys, fg_color="transparent")
        key_btns.grid(row=4, column=0, columnspan=2, padx=10, pady=12, sticky="w")
        self.show_keys_btn = ctk.CTkButton(key_btns, text="Show All Keys", width=120, fg_color="#334155", command=self._toggle_show_keys)
        self.show_keys_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(key_btns, text="Save All Keys Permanently", width=185, fg_color="#16a34a", command=self._save_settings_clicked).pack(
            side="left", padx=4
        )

        self._append_log("Ready. All saved keys loaded automatically — just pick any AI Model from the dropdown and click TURN AI ON.")

    # ==================== MODEL & CONFIG ACTIONS ====================
    def _on_unified_model_changed(self, preset_label: str) -> None:
        prov, mod = UNIFIED_MODEL_PRESETS.get(preset_label, ("gemini", "gemini-2.5-flash"))
        self.config_data.ai_provider = prov
        self.config_data.model = mod
        self._collect_config().save()
        has_key = prov == "ollama_local" or bool(self.config_data.get_active_api_key())
        key_note = "saved key ready" if has_key else "no key saved yet (open Saved API Keys tab)"
        self._append_log(f"Switched AI to {preset_label} ({key_note}).")

    def _collect_config(self) -> AppConfig:
        try:
            interval = max(0.8, float(self.interval_entry.get().strip()))
        except ValueError:
            interval = 2.5

        prov, mod = UNIFIED_MODEL_PRESETS.get(
            self.unified_model_var.get(), (self.config_data.ai_provider, self.config_data.model)
        )
        self.config_data.ai_provider = prov
        self.config_data.model = mod
        self.config_data.api_key = self.gemini_key_entry.get().strip()
        self.config_data.ollama_api_key = self.ollama_key_entry.get().strip()
        self.config_data.vercel_api_key = self.vercel_key_entry.get().strip()
        self.config_data.target_url = self.url_entry.get().strip() or "https://cymatics.fm/"
        self.config_data.giveaway_email = self.email_entry.get().strip() or "karankrajbhar23@gmail.com"
        self.config_data.scan_interval_sec = interval
        self.config_data.browser_filter = self.browser_filter_var.get()
        self.config_data.auto_add_free = bool(self.var_add_free.get())
        self.config_data.auto_check_learn_more = bool(self.var_learn_more.get())
        self.config_data.auto_checkout_free_only = bool(self.var_checkout.get())
        self.config_data.auto_answer_giveaway = bool(self.var_giveaway.get())
        self.config_data.auto_return_to_page = bool(self.var_return.get())
        self.config_data.monitor_live_links = bool(self.var_live_links.get())
        self.config_data.auto_open_new_drops = bool(self.var_auto_open_drops.get())
        self.config_data.background_input_mode = "background" if self.var_bg_mode.get() else "scoped_focus"
        self.config_data.minimize_to_tray = bool(self.var_tray.get())

        selected = self._windows_map.get(self.window_var.get())
        if selected:
            self.config_data.last_window_title = selected.title
        return self.config_data

    def _save_settings_clicked(self) -> None:
        cfg = self._collect_config()
        path = cfg.save()
        self._append_log(f"All API keys & settings saved permanently to {path}")

    def _clear_claimed_items(self) -> None:
        self.config_data.claimed_items.clear()
        self.config_data.save()
        self._append_log("Cleared claimed items history.")

    def _toggle_show_keys(self) -> None:
        self._show_keys = not self._show_keys
        mask = "" if self._show_keys else "*"
        self.gemini_key_entry.configure(show=mask)
        self.ollama_key_entry.configure(show=mask)
        self.vercel_key_entry.configure(show=mask)
        self.show_keys_btn.configure(text="Hide All Keys" if self._show_keys else "Show All Keys")

    def _test_api_key(self) -> None:
        cfg = self._collect_config()
        cfg.save()
        if cfg.ai_provider != "ollama_local" and not cfg.get_active_api_key():
            self._append_log(f"[ERROR] No API key saved for {cfg.ai_provider}. Open 'Saved API Keys' tab or run setup_local_keys.bat.")
            return
        self._append_log(f"Testing {cfg.ai_provider} / {cfg.model}...")

        def _worker() -> None:
            client = MultiProviderVisionClient(
                api_key=cfg.get_active_api_key(),
                model=cfg.model,
                provider=cfg.ai_provider,
                endpoint_mode=cfg.api_endpoint_mode,
                ollama_local_url=cfg.ollama_local_url,
            )
            ok, msg = client.test_connection()
            prefix = "[OK]" if ok else "[FAILED]"
            self.after(0, self._append_log, f"{prefix} {msg}")

        threading.Thread(target=_worker, daemon=True).start()

    # ==================== BROWSER WINDOW ACTIONS ====================
    def _refresh_windows(self) -> None:
        b_filter = self.browser_filter_var.get()
        wins: List[WindowInfo] = list_selectable_windows(browser_filter=b_filter)
        self._windows_map = {w.display_label: w for w in wins}

        labels = list(self._windows_map.keys())
        if not labels:
            labels = [f"No {b_filter} windows open — click Open Site or Pick Window"]
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
        self._append_log(f"Found {len(wins)} window(s) matching '{b_filter}'.")

    def _open_in_selected_browser(self) -> None:
        url = self.url_entry.get().strip() or "https://cymatics.fm/"
        b_filter = self.browser_filter_var.get()
        launch_browser_with_url(b_filter, url)
        self._append_log(f"Opened {url} in {b_filter}. Click Refresh or Pick Window once it loads.")

    def _pick_window_clicked(self) -> None:
        self.pick_btn.configure(text="Click Now...", state="disabled")
        self._append_log("Click directly on your browser window (Chrome/Brave/Opera/etc.) now, or press ESC...")

        def _worker() -> None:
            picked = pick_window_on_next_click(timeout_sec=15.0)
            self.after(0, self._finish_pick_window, picked)

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_pick_window(self, picked: Optional[WindowInfo]) -> None:
        self.pick_btn.configure(text="Pick Window", state="normal")
        if picked is None:
            self._append_log("Window pick cancelled or timed out.")
            return
        label = picked.display_label
        self._windows_map[label] = picked
        self.window_menu.configure(values=list(self._windows_map.keys()))
        self.window_var.set(label)
        self.config_data.last_window_title = picked.title
        self._append_log(f"Locked onto allowed window: '{picked.title}' ({picked.browser_name or picked.process_name})")

    def _highlight_selected_window(self) -> None:
        win = self._windows_map.get(self.window_var.get())
        if not win:
            self._append_log("Select a valid window first.")
            return
        ctrl = ScopedWindowController(win.hwnd)
        ctrl.flash_highlight()
        self._append_log(f"Highlighted allowed window: '{win.title}'")

    # ==================== LIVE STREAM & WEBSITE LINK MONITOR ====================
    def _scan_links_now(self) -> None:
        url = self.url_entry.get().strip() or "https://cymatics.fm/"
        self.link_monitor._target_url = url
        self._append_log(f"[LINKS] Scanning live links on {url}...")
        threading.Thread(target=self._safe_scan_once, daemon=True).start()

    def _safe_scan_once(self) -> None:
        try:
            all_links, new_links = self.link_monitor.scan_once()
            self.after(
                0,
                self._append_log,
                f"[LINKS] Found {len(all_links)} live links ({len(new_links)} new) on {self.link_monitor._target_url}.",
            )
        except Exception as exc:
            self.after(0, self._append_log, f"[LINKS ERROR] {exc}")

    def _on_links_updated(self, all_links: List[TrackedLink], new_links: List[TrackedLink]) -> None:
        self._tracked_links = all_links
        self.links_count_label.configure(text=f"{len(all_links)} live links tracked")
        self._update_stats(self.engine.stats)
        self._render_links_view()

        if new_links and self.var_auto_open_drops.get():
            for link in new_links:
                if link.category in ("FREE / DROP", "LIVESTREAM"):
                    self._append_log(f"[AUTO-OPEN DROP] Opening newly unlocked link: {link.url}")
                    launch_browser_with_url(self.browser_filter_var.get(), link.url)
                    break

    def _render_links_view(self) -> None:
        for child in self.links_scroll.winfo_children():
            child.destroy()

        flt = self.link_filter_var.get()
        items = self._tracked_links
        if flt == "NEW Only":
            items = [l for l in items if l.is_new]
        elif flt != "All Links":
            items = [l for l in items if l.category == flt]

        if not items:
            ctk.CTkLabel(
                self.links_scroll,
                text="No links yet — click 'Scan Website Links Now' or turn AI ON.",
                text_color="#64748b",
            ).grid(row=0, column=0, padx=10, pady=12, sticky="w")
            return

        cat_colors = {
            "FREE / DROP": "#22c55e",
            "LIVESTREAM": "#f43f5e",
            "PRODUCT": "#38bdf8",
            "PAGE": "#94a3b8",
        }
        for idx, link in enumerate(items[:80]):
            row = ctk.CTkFrame(self.links_scroll, fg_color="#111827", corner_radius=6)
            row.grid(row=idx, column=0, padx=4, pady=2, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            badge_text = ("NEW • " if link.is_new else "") + link.category
            ctk.CTkLabel(
                row,
                text=badge_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=cat_colors.get(link.category, "#cbd5e1"),
                width=105,
                anchor="w",
            ).grid(row=0, column=0, padx=(8, 4), pady=4)

            ctk.CTkLabel(
                row,
                text=f"{link.label}\n{link.url}",
                font=ctk.CTkFont(size=11),
                text_color="#e2e8f0",
                anchor="w",
                justify="left",
            ).grid(row=0, column=1, padx=4, pady=4, sticky="ew")

            ctk.CTkButton(
                row,
                text="Open",
                width=56,
                height=24,
                fg_color="#0284c7",
                command=lambda u=link.url: launch_browser_with_url(self.browser_filter_var.get(), u),
            ).grid(row=0, column=2, padx=(4, 8), pady=4)

    # ==================== POWER ON / OFF ====================
    def _toggle_ai(self) -> None:
        if self.engine.is_running:
            self.engine.stop()
            self.link_monitor.stop()
            self._set_button_off()
            return

        cfg = self._collect_config()
        cfg.save()

        if cfg.ai_provider != "ollama_local" and not cfg.get_active_api_key():
            self._append_log(f"[ERROR] No API key saved for {cfg.ai_provider}. Open 'Saved API Keys' tab or run setup_local_keys.bat.")
            return

        win = self._windows_map.get(self.window_var.get())
        if not win:
            self._append_log("[ERROR] Select or click 'Pick Window' for your browser window first.")
            return

        ctrl = ScopedWindowController(win.hwnd)
        ctrl.restore_if_minimized()
        self.engine.start(hwnd=win.hwnd, config=cfg)
        if cfg.monitor_live_links:
            self.link_monitor.start(cfg.target_url, interval_sec=cfg.link_poll_interval_sec)
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
                f"Scans: {stats.scans}  |  Free: {stats.free_items_added}  |  "
                f"$0 Orders: {stats.checkouts_completed}  |  Giveaways: {stats.giveaways_answered}  |  "
                f"Links: {len(self._tracked_links)}"
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

    # ==================== SYSTEM TRAY ====================
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
        self.link_monitor.stop()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.destroy()
