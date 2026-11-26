"""Local configuration manager for AIgiveaway.

Stores user settings (including API key and email) strictly on the local machine
in %APPDATA%\\AIgiveaway\\config.json (never inside the repository).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


DEFAULT_TARGET_URL = "https://cymatics.fm/"
DEFAULT_EMAIL = "karankrajbhar23@gmail.com"
DEFAULT_MODEL = "gemini-2.5-flash"


def get_config_dir() -> Path:
    """Return the per-user local configuration directory."""
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
    api_key: str = ""
    api_endpoint_mode: str = "auto"  # "auto", "gemini_studio", "vertex_express"
    model: str = DEFAULT_MODEL
    target_url: str = DEFAULT_TARGET_URL
    giveaway_email: str = DEFAULT_EMAIL
    scan_interval_sec: float = 2.5
    auto_add_free: bool = True
    auto_check_learn_more: bool = True
    auto_checkout_free_only: bool = True
    auto_answer_giveaway: bool = True
    auto_return_to_page: bool = True
    background_input_mode: str = "background"  # "background" (PostMessage) or "scoped_focus"
    minimize_to_tray: bool = True
    last_window_title: str = ""
    claimed_items: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        cfg_path = path or get_config_path()
        data = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        # Allow environment variable override if no key saved yet
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        if not data.get("api_key") and env_key:
            data["api_key"] = env_key

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
