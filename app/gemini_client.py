"""Gemini Vision REST client with full support for AQ.* Auth Keys and AIza keys.

Handles both Google AI Studio (generativelanguage.googleapis.com) and Vertex AI
Express Mode (aiplatform.googleapis.com) endpoints with automatic fallback.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests


GEMINI_STUDIO_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
VERTEX_EXPRESS_BASE = "https://aiplatform.googleapis.com/v1/publishers/google/models"

AVAILABLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]


@dataclass
class AgentDecision:
    """Structured action returned by Gemini Vision for the tracked window."""

    page_state: str  # "livestream", "learn_more", "cart", "checkout", "order_complete", "giveaway_popup", "other"
    priority: str  # "giveaway" or "normal"
    action: str  # "click", "type_and_submit", "fill_giveaway", "scroll_down", "scroll_up", "go_back", "wait"
    x_norm: Optional[float] = None  # 0.0 to 1.0 relative to window client width
    y_norm: Optional[float] = None  # 0.0 to 1.0 relative to window client height
    text_to_type: Optional[str] = None
    email_x_norm: Optional[float] = None
    email_y_norm: Optional[float] = None
    answer_x_norm: Optional[float] = None
    answer_y_norm: Optional[float] = None
    submit_x_norm: Optional[float] = None
    submit_y_norm: Optional[float] = None
    cart_total_is_zero: Optional[bool] = None
    item_name: Optional[str] = None
    giveaway_question: Optional[str] = None
    giveaway_answer: Optional[str] = None
    reason: str = ""


SYSTEM_PROMPT = """You are AIgiveaway, a fast, careful visual automation agent watching ONLY ONE browser window showing https://cymatics.fm/ (usually a Cymatics livestream free-download / giveaway page).

Your mission has TWO priorities:

PRIORITY 1 (URGENT - ALWAYS CHECK FIRST): RANDOM GIVEAWAY QUESTION
- If a giveaway question popup, banner, chat prompt, or form appears on the page asking a trivia/giveaway question and/or asking for an email address:
  - Immediately set priority="giveaway", page_state="giveaway_popup", action="fill_giveaway".
  - Read the question carefully and compute the shortest, most accurate answer in giveaway_answer.
  - Provide normalized coordinates (0.0 to 1.0 within the screenshot):
    - answer_x_norm, answer_y_norm: center of the answer input field (null if only an email field exists)
    - email_x_norm, email_y_norm: center of the email input field (null if not shown)
    - submit_x_norm, submit_y_norm: center of the Submit / Enter button.

PRIORITY 2 (NORMAL): FREE STUFF TRACKER & $0.00 CHECKOUT LOOP
1. On the main/livestream page:
   - Look for UNLOCKED FREE items (marked "$0", "FREE", "Add to Cart", "Get Free", "Download Free") that are NOT in the already_claimed list.
   - Click the free item or its "Add to Cart" / "Free" button.
   - If auto_check_learn_more is true and you see a "Learn More" button on a card that might contain free options (and hasn't been checked yet), click "Learn More" to inspect it.
2. On a "Learn More" / product detail page:
   - Check if there is any FREE option ($0 / Free download / Free Lite / Add Free to Cart).
   - If YES: click to add it to cart.
   - If NO free option exists (all paid): return action="go_back" to return to the livestream page.
3. Cart & Checkout:
   - Once free items are in the cart (or cart drawer/icon shows items) and auto_checkout_free_only is true, click Checkout.
   - CRITICAL SAFETY RULE: On the Checkout page, carefully read the Total / Order Total.
     - Set cart_total_is_zero=true ONLY IF the displayed total is explicitly $0.00 or FREE.
     - If the total is ANY amount greater than $0.00 (e.g. $1.00, $15.00), set cart_total_is_zero=false and action="wait" with reason explaining a paid item was detected. NEVER click Complete Order / Pay if total > $0.00!
   - If total is $0.00 / FREE: fill email if requested, or click "Complete Order" / "Complete Free Order" / "Continue".
4. After Order Complete / Thank You page:
   - Set page_state="order_complete" and action="go_back" (or navigate back to tracked URL) so we return to the livestream page to watch for newly unlocked freebies.
5. If nothing new is currently unlocked and no giveaway question is visible:
   - Either scroll_down gently to check lower items, or action="wait" if already at the bottom / waiting for the next livestream unlock.

Return STRICT JSON ONLY (no markdown fences, no commentary) matching this schema:
{
  "page_state": "livestream|learn_more|cart|checkout|order_complete|giveaway_popup|other",
  "priority": "giveaway|normal",
  "action": "click|fill_giveaway|type_and_submit|scroll_down|scroll_up|go_back|wait",
  "x_norm": 0.5,
  "y_norm": 0.5,
  "text_to_type": null,
  "email_x_norm": null,
  "email_y_norm": null,
  "answer_x_norm": null,
  "answer_y_norm": null,
  "submit_x_norm": null,
  "submit_y_norm": null,
  "cart_total_is_zero": null,
  "item_name": null,
  "giveaway_question": null,
  "giveaway_answer": null,
  "reason": "short explanation of what you see and why you chose this action"
}
"""


def parse_decision_json(raw_text: str) -> AgentDecision:
    """Safely parse Gemini's JSON response into an AgentDecision."""
    cleaned = raw_text.strip()
    # Strip markdown code fences if the model wrapped JSON anyway
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(1)

    data: Dict[str, Any] = json.loads(cleaned)

    def _opt_float(key: str) -> Optional[float]:
        val = data.get(key)
        if val is None:
            return None
        fval = float(val)
        return max(0.0, min(1.0, fval))

    return AgentDecision(
        page_state=str(data.get("page_state", "other")),
        priority=str(data.get("priority", "normal")),
        action=str(data.get("action", "wait")),
        x_norm=_opt_float("x_norm"),
        y_norm=_opt_float("y_norm"),
        text_to_type=data.get("text_to_type"),
        email_x_norm=_opt_float("email_x_norm"),
        email_y_norm=_opt_float("email_y_norm"),
        answer_x_norm=_opt_float("answer_x_norm"),
        answer_y_norm=_opt_float("answer_y_norm"),
        submit_x_norm=_opt_float("submit_x_norm"),
        submit_y_norm=_opt_float("submit_y_norm"),
        cart_total_is_zero=data.get("cart_total_is_zero"),
        item_name=data.get("item_name"),
        giveaway_question=data.get("giveaway_question"),
        giveaway_answer=data.get("giveaway_answer"),
        reason=str(data.get("reason", "")),
    )


class GeminiVisionClient:
    """HTTP client for Gemini multimodal inference supporting AQ.* and AIza keys."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        endpoint_mode: str = "auto",
        timeout_sec: float = 20.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "gemini-2.5-flash").strip()
        self.endpoint_mode = endpoint_mode
        self.timeout_sec = timeout_sec
        self._resolved_endpoint: Optional[str] = None

    def _build_request(self, mode: str) -> Tuple[str, Dict[str, str], Dict[str, str]]:
        headers = {"Content-Type": "application/json"}
        params: Dict[str, str] = {}
        if mode == "vertex_express":
            url = f"{VERTEX_EXPRESS_BASE}/{self.model}:generateContent"
            params["key"] = self.api_key
        else:
            url = f"{GEMINI_STUDIO_BASE}/{self.model}:generateContent"
            headers["x-goog-api-key"] = self.api_key
        return url, headers, params

    def _call_generate_content(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Gemini API key is empty. Paste your key in Settings.")

        modes_to_try: List[str]
        if self.endpoint_mode in ("gemini_studio", "vertex_express"):
            modes_to_try = [self.endpoint_mode]
        elif self._resolved_endpoint:
            modes_to_try = [self._resolved_endpoint]
        else:
            # Current Google AI Studio AQ.* keys work on generativelanguage.googleapis.com;
            # Vertex AI Express AQ.* keys work on aiplatform.googleapis.com.
            modes_to_try = ["gemini_studio", "vertex_express"]

        last_error: Optional[Exception] = None
        for mode in modes_to_try:
            url, headers, params = self._build_request(mode)
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    params=params,
                    json=payload,
                    timeout=self.timeout_sec,
                )
                if resp.status_code == 200:
                    self._resolved_endpoint = mode
                    return resp.json()
                # If 403/401 on first mode in auto mode, try fallback endpoint
                if resp.status_code in (401, 403, 404) and len(modes_to_try) > 1:
                    last_error = RuntimeError(
                        f"HTTP {resp.status_code} from {mode}: {resp.text[:300]}"
                    )
                    continue
                raise RuntimeError(
                    f"Gemini API error ({resp.status_code}): {resp.text[:400]}"
                )
            except requests.RequestException as exc:
                last_error = exc
                if len(modes_to_try) > 1:
                    continue
                raise

        raise RuntimeError(f"All Gemini endpoints failed: {last_error}")

    @staticmethod
    def _extract_text(response_json: Dict[str, Any]) -> str:
        candidates = response_json.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Empty Gemini response: {response_json}")
        parts = candidates[0].get("content", {}).get("parts", [])
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        return "\n".join(texts).strip()

    def test_connection(self) -> Tuple[bool, str]:
        """Verify the API key and model work before starting background tracking."""
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": "Reply with exactly: OK"}]}
            ],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 16},
        }
        try:
            res = self._call_generate_content(payload)
            reply = self._extract_text(res)
            endpoint_label = self._resolved_endpoint or self.endpoint_mode
            return True, f"Connected ({endpoint_label}, {self.model}): {reply}"
        except Exception as exc:
            return False, str(exc)

    def analyze_window_frame(
        self,
        image_jpeg_bytes: bytes,
        *,
        giveaway_email: str,
        target_url: str,
        claimed_items: List[str],
        auto_add_free: bool,
        auto_check_learn_more: bool,
        auto_checkout_free_only: bool,
        auto_answer_giveaway: bool,
        auto_return_to_page: bool,
        recent_actions: List[str],
    ) -> AgentDecision:
        """Send a single window screenshot to Gemini and get a structured action."""
        b64_img = base64.b64encode(image_jpeg_bytes).decode("ascii")
        user_context = (
            f"Target URL: {target_url}\n"
            f"User Giveaway Email: {giveaway_email}\n"
            f"Feature Flags: auto_add_free={auto_add_free}, "
            f"auto_check_learn_more={auto_check_learn_more}, "
            f"auto_checkout_free_only={auto_checkout_free_only}, "
            f"auto_answer_giveaway={auto_answer_giveaway}, "
            f"auto_return_to_page={auto_return_to_page}\n"
            f"Already Claimed Items: {claimed_items[-30:]}\n"
            f"Recent Actions: {recent_actions[-6:]}\n"
            "Inspect this screenshot of the ONLY allowed browser window and return your JSON decision."
        )

        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": user_context},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": b64_img,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 512,
                "responseMimeType": "application/json",
            },
        }
        res = self._call_generate_content(payload)
        raw_text = self._extract_text(res)
        return parse_decision_json(raw_text)
