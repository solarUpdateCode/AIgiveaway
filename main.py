"""Entry point for AIgiveaway Windows Desktop Application."""

from __future__ import annotations

import ctypes
import sys

from app.ui import AIgiveawayApp


def _enable_windows_dpi_awareness() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main() -> None:
    _enable_windows_dpi_awareness()
    app = AIgiveawayApp()
    app.mainloop()


if __name__ == "__main__":
    main()
