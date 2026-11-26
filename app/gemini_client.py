"""Multi-provider Vision AI client supporting Gemini, Ollama Cloud/Local, and Vercel AI Gateway."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests


GEMINI_STUDIO_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
VERTEX_EXPRESS_BASE = "https://aiplatform.googleapis.com/v1/publishers/google/models"
OLLAMA_CLOUD_CHAT_URL = "https://ollama.com/api/chat"
VERCEL_GATEWAY_CHAT_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"

PROVIDER_LABELS = {
    "gemini": "Google Gemini (AQ / AIza)",
    "ollama_cloud": "Ollama Cloud API",
    "vercel_gateway": "Vercel AI Gateway (vck_)",
    "ollama_local": "Ollama Local (localhost:11434)",
}

LABEL_TO_PROVIDER = {v: k for k, v in PROVIDER_LABELS.items()}

PROVIDER_MODELS: Dict[str, List[str]] = {
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.5-pro",
    ],
    "ollama_cloud": [
        "gemma4:31b",
        "qwen2.5vl:72b",
        "glm-5.3-flash:cloud",
        "llama4:scout",
        "llava",
    ],
    "vercel_gateway": [
        "google/gemini-2.5-flash",
        "google/gemini-2.5-flash-lite",
        "openai/gpt-4o-mini",
        "anthropic/claude-sonnet-4",
        "zai/glm-5.2-fast",
    ],
    "ollama_local": [
        "gemma4:e4b",
        "qwen2.5vl:7b",
        "llava:latest",
        "llama3.2-vision",
    ],
}

# Unified one-click dropdown presets: Display Label -> (provider_id, model_id)
UNIFIED_MODEL_PRESETS: Dict[str, Tuple[str, str]] = {
    "Gemini  •  gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    "Gemini  •  gemini-2.5-flash-lite": ("gemini", "gemini-2.5-flash-lite"),
    "Gemini  •  gemini-3.6-flash": ("gemini", "gemini-3.6-flash"),
    "Gemini  •  gemini-2.0-flash": ("gemini", "gemini-2.0-flash"),
    "Ollama Cloud  •  gemma4:31b": ("ollama_cloud", "gemma4:31b"),
    "Ollama Cloud  •  qwen2.5vl:72b": ("ollama_cloud", "qwen2.5vl:72b"),
    "Ollama Cloud  •  glm-5.3-flash:cloud": ("ollama_cloud", "glm-5.3-flash:cloud"),
    "Ollama Cloud  •  llama4:scout": ("ollama_cloud", "llama4:scout"),
    "Vercel Gateway  •  google/gemini-2.5-flash": ("vercel_gateway", "google/gemini-2.5-flash"),
    "Vercel Gateway  •  openai/gpt-4o-mini": ("vercel_gateway", "openai/gpt-4o-mini"),
    "Vercel Gateway  •  anthropic/claude-sonnet-4": ("vercel_gateway", "anthropic/claude-sonnet-4"),
    "Vercel Gateway  •  zai/glm-5.2-fast": ("vercel_gateway", "zai/glm-5.2-fast"),
    "Ollama Local  •  gemma4:e4b": ("ollama_local", "gemma4:e4b"),
    "Ollama Local  •  qwen2.5vl:7b": ("ollama_local", "qwen2.5vl:7b"),
}

AVAILABLE_MODELS = PROVIDER_MODELS["gemini"]


def preset_label_for(provider: str, model: str) -> str:
    for label, (prov, mod) in UNIFIED_MODEL_PRESETS.items():
        if prov == provider and mod == model:
            return label
    return next(iter(UNIFIED_MODEL_PRESETS.keys()))


@dataclass
class AgentDecision:
    page_state: str
    priority: str
    action: str
    x_norm: Optional[float] = None
    y_norm: Optional[float] = None
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
    detected_urls: List[str] = field(default_factory=list)
    livestream_status: Optional[str] = None
    reason: str = ""


SYSTEM_PROMPT = """You are AIgiveaway, a fast, careful visual automation agent watching ONLY ONE browser window showing https://cymatics.fm/ (a Cymatics livestream free-download / giveaway page or livestream video/chat).

Your mission has THREE jobs:

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
   - Set page_state="order_complete" and action="go_back" so we return to the livestream page to watch for newly unlocked freebies.

PRIORITY 3 (ALWAYS): LIVE STREAM & LINK EXTRACTION
- If you see any visible URLs, drop links, or giveaway links on screen or in livestream chat, list them in "detected_urls".
- Briefly note any livestream status in "livestream_status".

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
  "detected_urls": [],
  "livestream_status": null,
  "reason": "short explanation of what you see and why you chose this action"
}
"""


def parse_decision_json(raw_text: str) -> AgentDecision:
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return AgentDecision(page_state="other", priority="normal", action="wait", reason="Empty AI response")

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

    raw_urls = data.get("detected_urls") or []
    urls = [str(u).strip() for u in raw_urls if isinstance(u, str) and u.strip().startswith(("http://", "https://"))]

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
        detected_urls=urls,
        livestream_status=data.get("livestream_status"),
        reason=str(data.get("reason", "")),
    )


def _gemini_generation_config(model: str, json_mode: bool = True) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {"temperature": 0.1, "maxOutputTokens": 2048}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    if model.lower().startswith("gemini-2.5-flash"):
        cfg["thinkingConfig"] = {"thinkingBudget": 0}
    return cfg


class MultiProviderVisionClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        provider: str = "gemini",
        endpoint_mode: str = "auto",
        ollama_local_url: str = "http://localhost:11434",
        timeout_sec: float = 30.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.provider = (provider or "gemini").strip()
        self.model = (model or PROVIDER_MODELS.get(self.provider, ["gemini-2.5-flash"])[0]).strip()
        self.endpoint_mode = endpoint_mode
        self.ollama_local_url = (ollama_local_url or "http://localhost:11434").rstrip("/")
        self.timeout_sec = timeout_sec
        self._resolved_endpoint: Optional[str] = None

    def _gemini_request(self, mode: str, model: str) -> Tuple[str, Dict[str, str], Dict[str, str]]:
        headers = {"Content-Type": "application/json"}
        params: Dict[str, str] = {}
        if mode == "vertex_express":
            url = f"{VERTEX_EXPRESS_BASE}/{model}:generateContent"
            params["key"] = self.api_key
        elif mode == "gemini_studio_query":
            url = f"{GEMINI_STUDIO_BASE}/{model}:generateContent"
            params["key"] = self.api_key
        else:
            url = f"{GEMINI_STUDIO_BASE}/{model}:generateContent"
            headers["x-goog-api-key"] = self.api_key
        return url, headers, params

    def _call_gemini(self, payload_builder) -> str:
        if not self.api_key:
            raise ValueError("Gemini API key is empty. Run setup_local_keys.bat or paste it once in API Keys.")
        modes = (
            [self.endpoint_mode]
            if self.endpoint_mode in ("gemini_studio", "vertex_express")
            else ([self._resolved_endpoint] if self._resolved_endpoint else ["gemini_studio", "vertex_express", "gemini_studio_query"])
        )
        models = [self.model] + [m for m in PROVIDER_MODELS["gemini"] if m != self.model and "flash" in m]
        last_error: Optional[str] = None
        for model_name in models:
            payload = payload_builder(model_name)
            got_404_on_all = True
            for mode in modes:
                url, headers, params = self._gemini_request(mode, model_name)
                try:
                    resp = requests.post(url, headers=headers, params=params, json=payload, timeout=self.timeout_sec)
                    if resp.status_code == 200:
                        self._resolved_endpoint = mode
                        self.model = model_name
                        return self._extract_gemini_text(resp.json())
                    if resp.status_code != 404:
                        got_404_on_all = False
                    last_error = f"HTTP {resp.status_code} ({mode}/{model_name}): {resp.text[:260]}"
                    if resp.status_code in (401, 403, 404):
                        continue
                    if resp.status_code == 400 and "thinkingConfig" in str(payload):
                        retry_payload = dict(payload)
                        gc = dict(retry_payload.get("generationConfig", {}))
                        gc.pop("thinkingConfig", None)
                        retry_payload["generationConfig"] = gc
                        resp2 = requests.post(url, headers=headers, params=params, json=retry_payload, timeout=self.timeout_sec)
                        if resp2.status_code == 200:
                            self._resolved_endpoint = mode
                            self.model = model_name
                            return self._extract_gemini_text(resp2.json())
                        last_error = f"HTTP {resp2.status_code} ({mode}/{model_name}): {resp2.text[:260]}"
                except requests.RequestException as exc:
                    got_404_on_all = False
                    last_error = f"Network error ({mode}): {exc}"
            if not got_404_on_all:
                break
        raise RuntimeError(last_error or "Gemini API request failed.")

    @staticmethod
    def _extract_gemini_text(response_json: Dict[str, Any]) -> str:
        candidates = response_json.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Empty Gemini response: {response_json}")
        parts = candidates[0].get("content", {}).get("parts", [])
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text") and not p.get("thought")]
        return "\n".join(texts).strip()

    def _call_ollama(self, prompt_text: str, system_text: Optional[str], b64_img: Optional[str], json_mode: bool) -> str:
        is_cloud = self.provider == "ollama_cloud"
        if is_cloud and not self.api_key:
            raise ValueError("Ollama Cloud API key is empty. Run setup_local_keys.bat or paste it once.")
        url = OLLAMA_CLOUD_CHAT_URL if is_cloud else f"{self.ollama_local_url}/api/chat"
        headers = {"Content-Type": "application/json"}
        if is_cloud:
            headers["Authorization"] = f"Bearer {self.api_key}"

        messages: List[Dict[str, Any]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        user_msg: Dict[str, Any] = {"role": "user", "content": prompt_text}
        if b64_img:
            user_msg["images"] = [b64_img]
        messages.append(user_msg)

        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"

        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_sec)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status_code} ({self.model}): {resp.text[:300]}")
        data = resp.json()
        self._resolved_endpoint = "ollama_cloud" if is_cloud else "ollama_local"
        msg = data.get("message") or {}
        return str(msg.get("content", "")).strip()

    def _call_vercel_gateway(self, prompt_text: str, system_text: Optional[str], b64_img: Optional[str], json_mode: bool) -> str:
        if not self.api_key:
            raise ValueError("Vercel AI Gateway key is empty. Run setup_local_keys.bat or paste it once.")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        messages: List[Dict[str, Any]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        if b64_img:
            user_content: Any = [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
            ]
        else:
            user_content = prompt_text
        messages.append({"role": "user", "content": user_content})

        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1, "max_tokens": 1500}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = requests.post(VERCEL_GATEWAY_CHAT_URL, headers=headers, json=payload, timeout=self.timeout_sec)
        if resp.status_code == 400 and json_mode:
            payload.pop("response_format", None)
            resp = requests.post(VERCEL_GATEWAY_CHAT_URL, headers=headers, json=payload, timeout=self.timeout_sec)
        if resp.status_code != 200:
            raise RuntimeError(f"Vercel Gateway HTTP {resp.status_code} ({self.model}): {resp.text[:300]}")

        data = resp.json()
        self._resolved_endpoint = "vercel_gateway"
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Empty Vercel Gateway response: {data}")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict)).strip()
        return str(content).strip()

    def test_connection(self) -> Tuple[bool, str]:
        try:
            if self.provider in ("ollama_cloud", "ollama_local"):
                reply = self._call_ollama("Reply with exactly: OK", None, None, json_mode=False)
                return True, f"Connected ({self.provider}, {self.model}): {reply[:80]}"
            if self.provider == "vercel_gateway":
                reply = self._call_vercel_gateway("Reply with exactly: OK", None, None, json_mode=False)
                return True, f"Connected (vercel_gateway, {self.model}): {reply[:80]}"

            def _build(model_name: str) -> Dict[str, Any]:
                return {
                    "contents": [{"role": "user", "parts": [{"text": "Reply with exactly: OK"}]}],
                    "generationConfig": _gemini_generation_config(model_name, json_mode=False),
                }

            reply = self._call_gemini(_build)
            return True, f"Connected ({self._resolved_endpoint or 'gemini'}, {self.model}): {reply[:80]}"
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

        if self.provider in ("ollama_cloud", "ollama_local"):
            raw = self._call_ollama(user_context, SYSTEM_PROMPT, b64_img, json_mode=True)
            return parse_decision_json(raw)
        if self.provider == "vercel_gateway":
            raw = self._call_vercel_gateway(user_context, SYSTEM_PROMPT, b64_img, json_mode=True)
            return parse_decision_json(raw)

        def _build(model_name: str) -> Dict[str, Any]:
            return {
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": user_context},
                            {"inlineData": {"mimeType": "image/jpeg", "data": b64_img}},
                        ],
                    }
                ],
                "generationConfig": _gemini_generation_config(model_name, json_mode=True),
            }

        raw = self._call_gemini(_build)
        return parse_decision_json(raw)


GeminiVisionClient = MultiProviderVisionClient
