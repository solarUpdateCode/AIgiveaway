"""Local configuration manager for AIgiveaway.

Stores user settings (including per-provider API keys and email) strictly on
the local machine in %APPDATA%\\AIgiveaway\\config.json (never in Git).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


DEFAULT_TARGET_URL = "https://cymatics.fm/"
DEFAULT_EMAIL = "karankrajbhar23@gmail.com"
DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"


def get_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        cfg_dir = Path(base) / "AIgiveaway"
    else:
        cfg_dir = Path.home() / ".config" / "AIgiveaway"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


@dataclass
class AppConfig:
    ai_provider: str = DEFAULT_PROVIDER  # "gemini", "ollama_cloud", "ollama_local", "vercel_gateway"
    api_key: str = ""  # Gemini API key
    ollama_api_key: str = ""  # Ollama Cloud API key
    vercel_api_key: str = ""  # Vercel AI Gateway key (vck_...)
    ollama_local_url: str = "http://localhost:11434"
    api_endpoint_mode: str = "auto"
    model: str = DEFAULT_MODEL
    target_url: str = DEFAULT_TARGET_URL
    giveaway_email: str = DEFAULT_EMAIL
    scan_interval_sec: float = 2.5
    link_poll_interval_sec: float = 8.0
    browser_filter: str = "All Browsers"
    auto_add_free: bool = True
    auto_check_learn_more: bool = True
    auto_checkout_free_only: bool = True
    auto_answer_giveaway: bool = True
    auto_return_to_page: bool = True
    monitor_live_links: bool = True
    auto_open_new_drops: bool = False
    background_input_mode: str = "background"
    minimize_to_tray: bool = True
    last_window_title: str = ""
    claimed_items: List[str] = field(default_factory=list)

    def get_active_api_key(self) -> str:
        if self.ai_provider == "ollama_cloud":
            return (self.ollama_api_key or "").strip()
        if self.ai_provider == "vercel_gateway":
            return (self.vercel_api_key or "").strip()
        if self.ai_provider == "ollama_local":
            return ""
        return (self.api_key or "").strip()

    def set_active_api_key(self, key: str) -> None:
        cleaned = (key or "").strip()
        if self.ai_provider == "ollama_cloud":
            self.ollama_api_key = cleaned
        elif self.ai_provider == "vercel_gateway":
            self.vercel_api_key = cleaned
        elif self.ai_provider == "gemini":
            self.api_key = cleaned

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        cfg_path = path or get_config_path()
        data = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        if not data.get("api_key"):
            env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
            if env_key:
                data["api_key"] = env_key
        if not data.get("ollama_api_key") and os.environ.get("OLLAMA_API_KEY"):
            data["ollama_api_key"] = os.environ["OLLAMA_API_KEY"]
        if not data.get("vercel_api_key"):
            v_key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_AI_API_KEY") or ""
            if v_key:
                data["vercel_api_key"] = v_key

        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def save(self, path: Path | None = None) -> Path:
        cfg_path = path or get_config_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return cfg_path
