"""Background AI tracking engine for Cymatics.fm giveaways & free drops."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from PIL import Image

from app.config import AppConfig
from app.gemini_client import AgentDecision, GeminiVisionClient
from app.window_controller import ScopedWindowController


@dataclass
class AgentStats:
    scans: int = 0
    free_items_added: int = 0
    checkouts_completed: int = 0
    giveaways_answered: int = 0
    last_state: str = "idle"


class GiveawayAgentEngine:
    """Runs the background watch-and-act loop strictly on the allowed window."""

    def __init__(
        self,
        config: AppConfig,
        on_log: Callable[[str], None],
        on_status: Callable[[str], None],
        on_preview: Callable[[Image.Image], None],
        on_stats: Callable[[AgentStats], None],
    ) -> None:
        self.config = config
        self.on_log = on_log
        self.on_status = on_status
        self.on_preview = on_preview
        self.on_stats = on_stats

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._controller: Optional[ScopedWindowController] = None
        self._client: Optional[GeminiVisionClient] = None
        self._recent_actions: List[str] = []
        self.stats = AgentStats()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def start(self, hwnd: int, config: AppConfig) -> None:
        if self.is_running:
            return
        self.config = config
        self._controller = ScopedWindowController(hwnd=hwnd, mode=config.background_input_mode)
        self._client = GeminiVisionClient(
            api_key=config.api_key,
            model=config.model,
            endpoint_mode=config.api_endpoint_mode,
        )
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="AIgiveawayLoop", daemon=True)
        self._thread.start()
        self.on_status("RUNNING")
        self.on_log(
            f"AI ON — Tracking window '{self._controller.get_title()}' "
            f"(mode: {config.background_input_mode}, model: {config.model})."
        )

    def stop(self) -> None:
        self._stop_event.set()
        self.on_status("STOPPED")
        self.on_log("AI OFF — Background tracking stopped.")

    def _record_action(self, desc: str) -> None:
        self._recent_actions.append(desc)
        if len(self._recent_actions) > 15:
            self._recent_actions = self._recent_actions[-15:]

    def _execute_decision(self, decision: AgentDecision) -> None:
        assert self._controller is not None

        # Safety guardrail: NEVER complete paid checkouts
        if decision.page_state == "checkout" and decision.cart_total_is_zero is False:
            self.on_log(
                f"[SAFETY STOP] Non-$0.00 checkout detected ({decision.reason}). "
                "Skipping checkout — only FREE ($0.00) orders are allowed."
            )
            self._record_action("blocked_paid_checkout")
            return

        # Priority 1: Fast Giveaway Question Solver
        if decision.action == "fill_giveaway":
            if not self.config.auto_answer_giveaway:
                self.on_log("Giveaway question detected, but Auto-Answer Giveaway is disabled.")
                return

            self.on_log(
                f"[GIVEAWAY] Question: {decision.giveaway_question or 'Detected'} -> "
                f"Answer: {decision.giveaway_answer or '(email only)'}"
            )
            if decision.answer_x_norm is not None and decision.answer_y_norm is not None and decision.giveaway_answer:
                self._controller.click_normalized(decision.answer_x_norm, decision.answer_y_norm)
                time.sleep(0.08)
                self._controller.type_text(decision.giveaway_answer)
                time.sleep(0.06)

            if decision.email_x_norm is not None and decision.email_y_norm is not None and self.config.giveaway_email:
                self._controller.click_normalized(decision.email_x_norm, decision.email_y_norm)
                time.sleep(0.08)
                self._controller.type_text(self.config.giveaway_email)
                time.sleep(0.06)

            if decision.submit_x_norm is not None and decision.submit_y_norm is not None:
                self._controller.click_normalized(decision.submit_x_norm, decision.submit_y_norm)
                self.stats.giveaways_answered += 1
                self._record_action(f"submitted_giveaway:{decision.giveaway_answer}")
                self.on_log(
                    f"[GIVEAWAY SUBMITTED] Sent answer with {self.config.giveaway_email}."
                )
            return

        # Priority 2: Normal Free-Item / Learn-More / Checkout Actions
        if decision.action == "click" and decision.x_norm is not None and decision.y_norm is not None:
            if decision.page_state == "checkout" and not self.config.auto_checkout_free_only:
                self.on_log("On checkout page, but Auto-Checkout ($0.00 Only) is disabled.")
                return
            if decision.page_state == "checkout" and decision.cart_total_is_zero is not True:
                self.on_log(
                    "[SAFETY] Checkout total not confirmed as $0.00 — waiting instead of clicking."
                )
                return

            ok = self._controller.click_normalized(decision.x_norm, decision.y_norm)
            if ok:
                label = decision.item_name or decision.reason or "element"
                self.on_log(f"[CLICK] ({decision.page_state}) {label}")
                self._record_action(f"click:{decision.page_state}:{label}")
                if decision.item_name and decision.page_state in ("livestream", "learn_more"):
                    if decision.item_name not in self.config.claimed_items:
                        self.config.claimed_items.append(decision.item_name)
                        self.config.save()
                    self.stats.free_items_added += 1
                if decision.page_state == "checkout" and decision.cart_total_is_zero:
                    self.stats.checkouts_completed += 1
            return

        if decision.action == "type_and_submit" and decision.x_norm is not None and decision.y_norm is not None:
            text = decision.text_to_type or self.config.giveaway_email
            self._controller.click_normalized(decision.x_norm, decision.y_norm)
            time.sleep(0.08)
            self._controller.type_text(text, press_enter=True)
            self.on_log(f"[TYPE] Entered '{text}' on {decision.page_state}.")
            self._record_action(f"type:{decision.page_state}")
            return

        if decision.action == "scroll_down":
            self._controller.scroll("down", ticks=4)
            self.on_log(f"[SCROLL] Scrolling down ({decision.reason}).")
            self._record_action("scroll_down")
            return

        if decision.action == "scroll_up":
            self._controller.scroll("up", ticks=4)
            self.on_log(f"[SCROLL] Scrolling up ({decision.reason}).")
            self._record_action("scroll_up")
            return

        if decision.action == "go_back":
            if decision.page_state == "order_complete" and self.config.auto_return_to_page:
                self.on_log(
                    f"[RETURN] Order complete — returning to {self.config.target_url} to track new unlocks."
                )
                self._controller.navigate_to_url(self.config.target_url)
            else:
                self.on_log(f"[BACK] Returning to previous page ({decision.reason}).")
                self._controller.navigate_back()
            self._record_action("go_back")
            return

        # Default: wait
        if decision.reason:
            self.on_log(f"[WATCHING] {decision.reason}")

    def _run_loop(self) -> None:
        assert self._controller is not None and self._client is not None

        while not self._stop_event.is_set():
            if not self._controller.is_valid():
                self.on_log("Selected window was closed. Turning AI OFF.")
                self.stop()
                return

            if self._controller.is_minimized():
                self.on_status("PAUSED (WINDOW MINIMIZED)")
                self.on_log("Allowed window is minimized — keep it open behind other apps so PrintWindow can see it.")
                self._stop_event.wait(2.5)
                continue

            self.on_status("SCANNING")
            captured = self._controller.capture_jpeg_bytes(quality=78)
            if captured is None:
                self.on_log("Could not capture allowed window frame. Retrying...")
                self._stop_event.wait(2.0)
                continue

            jpeg_bytes, pil_img = captured
            self.on_preview(pil_img)

            try:
                decision = self._client.analyze_window_frame(
                    jpeg_bytes,
                    giveaway_email=self.config.giveaway_email,
                    target_url=self.config.target_url,
                    claimed_items=self.config.claimed_items,
                    auto_add_free=self.config.auto_add_free,
                    auto_check_learn_more=self.config.auto_check_learn_more,
                    auto_checkout_free_only=self.config.auto_checkout_free_only,
                    auto_answer_giveaway=self.config.auto_answer_giveaway,
                    auto_return_to_page=self.config.auto_return_to_page,
                    recent_actions=self._recent_actions,
                )
                self.stats.scans += 1
                self.stats.last_state = decision.page_state
                self.on_stats(self.stats)

                if not self._stop_event.is_set():
                    self._execute_decision(decision)

            except Exception as exc:
                self.on_status("ERROR")
                self.on_log(f"[API ERROR] {exc}")

            # Wait configured interval (faster re-check right after giveaway or click)
            delay = max(0.8, float(self.config.scan_interval_sec))
            self._stop_event.wait(delay)
