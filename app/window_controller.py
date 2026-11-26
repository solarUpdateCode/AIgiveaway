"""Strict single-window capture and window-scoped remote control for Windows.

Security & Isolation Design:
- Captures ONLY the single HWND selected by the user via Win32 PrintWindow
  (never captures the full desktop or any other window).
- Sends input strictly to the selected HWND:
  * "background" mode: Uses Win32 PostMessage (WM_LBUTTONDOWN/UP, WM_CHAR,
    WM_MOUSEWHEEL) directly to the target HWND without moving the user's cursor.
  * "scoped_focus" mode: Brings ONLY the selected HWND to focus, clamps all
    coordinates strictly within its client rect, verifies GetForegroundWindow()
    matches the allowed HWND right before clicking, and refuses to click outside.
"""

from __future__ import annotations

import io
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    import win32api
    import win32con
    import win32gui
    import win32ui

    PW_RENDERFULLCONTENT = 0x00000002
    user32 = ctypes.windll.user32


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    width: int
    height: int

    @property
    def display_label(self) -> str:
        short_title = self.title if len(self.title) <= 64 else self.title[:61] + "..."
        return f"{short_title}  [{self.width}x{self.height}]"


def list_selectable_windows(exclude_hwnd: Optional[int] = None) -> List[WindowInfo]:
    """Return visible top-level windows that can be selected for isolated control."""
    if not IS_WINDOWS:
        return []

    windows: List[WindowInfo] = []

    def _enum_cb(hwnd: int, _extra) -> bool:
        if exclude_hwnd and hwnd == exclude_hwnd:
            return True
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        if title in ("Program Manager", "Settings", "Windows Input Experience"):
            return True
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        w, h = right - left, bottom - top
        if w < 200 or h < 150:
            return True
        cls_name = win32gui.GetClassName(hwnd)
        windows.append(WindowInfo(hwnd=hwnd, title=title, class_name=cls_name, width=w, height=h))
        return True

    win32gui.EnumWindows(_enum_cb, None)
    # Sort browser / Cymatics windows to the top for convenience
    def _sort_key(win: WindowInfo) -> Tuple[int, str]:
        tl = win.title.lower()
        if "cymatics" in tl:
            return (0, tl)
        if any(b in tl for b in ("chrome", "edge", "firefox", "brave", "opera")):
            return (1, tl)
        return (2, tl)

    windows.sort(key=_sort_key)
    return windows


class ScopedWindowController:
    """Controls ONLY the single user-approved HWND."""

    def __init__(self, hwnd: int, mode: str = "background") -> None:
        self.hwnd = hwnd
        self.mode = mode  # "background" or "scoped_focus"

    def is_valid(self) -> bool:
        if not IS_WINDOWS:
            return False
        return bool(self.hwnd and win32gui.IsWindow(self.hwnd))

    def is_minimized(self) -> bool:
        if not IS_WINDOWS or not self.is_valid():
            return True
        return bool(win32gui.IsIconic(self.hwnd))

    def get_title(self) -> str:
        if not IS_WINDOWS or not self.is_valid():
            return ""
        return win32gui.GetWindowText(self.hwnd)

    def get_client_size(self) -> Tuple[int, int]:
        if not IS_WINDOWS or not self.is_valid():
            return (0, 0)
        left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
        return (max(0, right - left), max(0, bottom - top))

    def capture_image(self, max_width: int = 1280) -> Optional[Image.Image]:
        """Capture ONLY the target window's content using PrintWindow (background-safe)."""
        if not IS_WINDOWS or not self.is_valid() or self.is_minimized():
            return None

        width, height = self.get_client_size()
        if width < 50 or height < 50:
            return None

        hwnd_dc = win32gui.GetWindowDC(self.hwnd)
        mfc_dc = None
        save_dc = None
        bitmap = None
        try:
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # PW_RENDERFULLCONTENT works on Chrome/Edge/Electron even behind other windows
            result = user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
            if result == 0:
                # Fallback to client area PrintWindow flag (1)
                result = user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 1)
            if result == 0:
                return None

            bmp_info = bitmap.GetInfo()
            bmp_bits = bitmap.GetBitmapBits(True)
            img = Image.frombuffer(
                "RGB",
                (bmp_info["bmWidth"], bmp_info["bmHeight"]),
                bmp_bits,
                "raw",
                "BGRX",
                0,
                1,
            )
            if img.width > max_width:
                ratio = max_width / float(img.width)
                img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
            return img
        finally:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)

    def capture_jpeg_bytes(self, quality: int = 80) -> Optional[Tuple[bytes, Image.Image]]:
        img = self.capture_image()
        if img is None:
            return None
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), img

    def _norm_to_client_xy(self, x_norm: float, y_norm: float) -> Tuple[int, int]:
        width, height = self.get_client_size()
        cx = int(max(2, min(width - 2, round(x_norm * width))))
        cy = int(max(2, min(height - 2, round(y_norm * height))))
        return cx, cy

    def _find_child_at(self, client_x: int, client_y: int) -> Tuple[int, int, int]:
        """Find deepest child HWND inside target window (needed for Chromium render widget)."""
        screen_pt = win32gui.ClientToScreen(self.hwnd, (client_x, client_y))
        child = win32gui.ChildWindowFromPointEx(
            self.hwnd,
            (client_x, client_y),
            win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPDISABLED,
        )
        target = child if child and win32gui.IsWindow(child) else self.hwnd
        local_x, local_y = win32gui.ScreenToClient(target, screen_pt)
        return target, local_x, local_y

    def click_normalized(self, x_norm: float, y_norm: float) -> bool:
        """Click strictly inside the allowed window."""
        if not IS_WINDOWS or not self.is_valid() or self.is_minimized():
            return False

        cx, cy = self._norm_to_client_xy(x_norm, y_norm)

        if self.mode == "background":
            target, lx, ly = self._find_child_at(cx, cy)
            lparam = win32api.MAKELONG(lx, ly)
            win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lparam)
            time.sleep(0.03)
            win32gui.PostMessage(target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(0.05)
            win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lparam)
            return True

        # Scoped focus fallback: strictly verify foreground HWND & clamp inside window
        try:
            win32gui.SetForegroundWindow(self.hwnd)
            time.sleep(0.08)
            if win32gui.GetForegroundWindow() != self.hwnd:
                return False
            sx, sy = win32gui.ClientToScreen(self.hwnd, (cx, cy))
            # Save and restore user cursor position quickly
            prev_pos = win32api.GetCursorPos()
            win32api.SetCursorPos((sx, sy))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.04)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.02)
            win32api.SetCursorPos(prev_pos)
            return True
        except Exception:
            return False

    def type_text(self, text: str, press_enter: bool = False) -> bool:
        """Send text strictly to the allowed window via WM_CHAR."""
        if not IS_WINDOWS or not self.is_valid() or not text:
            return False

        target = self.hwnd
        for ch in text:
            win32gui.PostMessage(target, win32con.WM_CHAR, ord(ch), 0)
            time.sleep(0.01)
        if press_enter:
            win32gui.PostMessage(target, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            time.sleep(0.02)
            win32gui.PostMessage(target, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        return True

    def scroll(self, direction: str = "down", ticks: int = 4) -> bool:
        """Scroll strictly inside the allowed window."""
        if not IS_WINDOWS or not self.is_valid() or self.is_minimized():
            return False

        cx, cy = self._norm_to_client_xy(0.5, 0.5)
        sx, sy = win32gui.ClientToScreen(self.hwnd, (cx, cy))
        delta = -120 * ticks if direction == "down" else 120 * ticks
        wparam = win32api.MAKELONG(0, delta & 0xFFFF)
        lparam = win32api.MAKELONG(sx, sy)
        target, _, _ = self._find_child_at(cx, cy)
        win32gui.PostMessage(target, win32con.WM_MOUSEWHEEL, wparam, lparam)
        return True

    def navigate_back(self) -> bool:
        """Send Browser Back command strictly to the allowed window."""
        if not IS_WINDOWS or not self.is_valid():
            return False
        win32gui.PostMessage(self.hwnd, win32con.WM_APPCOMMAND, self.hwnd, 1 << 16)
        return True

    def navigate_to_url(self, url: str) -> bool:
        """Focus browser address bar (Ctrl+L) inside allowed window and open URL."""
        if not IS_WINDOWS or not self.is_valid() or not url:
            return False
        if self.mode == "scoped_focus":
            try:
                win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(0.08)
                if win32gui.GetForegroundWindow() != self.hwnd:
                    return False
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord("L"), 0, 0, 0)
                time.sleep(0.03)
                win32api.keybd_event(ord("L"), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.08)
                self.type_text(url, press_enter=True)
                return True
            except Exception:
                return False
        # In pure background mode, use Browser Back first
        return self.navigate_back()

    def flash_highlight(self) -> None:
        """Briefly flash the selected window taskbar/border so user confirms it's the right one."""
        if not IS_WINDOWS or not self.is_valid():
            return
        try:
            win32gui.FlashWindow(self.hwnd, True)
        except Exception:
            pass
