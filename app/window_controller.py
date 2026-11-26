"""Strict single-window capture and window-scoped remote control for Windows."""

from __future__ import annotations

import io
import os
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
    import win32process
    import win32ui

    PW_RENDERFULLCONTENT = 0x00000002
    DWMWA_CLOAKED = 14
    GA_ROOT = 2
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi


BROWSER_KEYWORDS = (
    "chrome",
    "edge",
    "firefox",
    "brave",
    "opera",
    "vivaldi",
    "arc",
    "cymatics",
    "youtube",
)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    width: int
    height: int
    is_minimized: bool = False
    is_browser: bool = False

    @property
    def display_label(self) -> str:
        prefix = "[Browser] " if self.is_browser else ""
        suffix = " (Minimized)" if self.is_minimized else f" [{self.width}x{self.height}]"
        max_len = 52
        short_title = self.title if len(self.title) <= max_len else self.title[: max_len - 3] + "..."
        return f"{prefix}{short_title}{suffix}"


def _is_window_cloaked(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        cloaked = ctypes.c_int(0)
        hr = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_CLOAKED),
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return hr == 0 and cloaked.value != 0
    except Exception:
        return False


def _looks_like_browser(title: str, class_name: str) -> bool:
    tl = title.lower()
    cl = class_name.lower()
    if any(k in tl for k in BROWSER_KEYWORDS):
        return True
    if cl in ("chrome_widgetwin_1", "mozillawindowclass", "opera_widgetwin_1"):
        return True
    return False


def list_selectable_windows(exclude_hwnd: Optional[int] = None) -> List[WindowInfo]:
    if not IS_WINDOWS:
        return []

    my_pid = os.getpid()
    windows: List[WindowInfo] = []

    def _enum_cb(hwnd: int, _extra) -> bool:
        if exclude_hwnd and hwnd == exclude_hwnd:
            return True
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == my_pid:
                return True
        except Exception:
            pass

        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if ex_style & win32con.WS_EX_TOOLWINDOW:
            return True

        if _is_window_cloaked(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        if title in ("Program Manager", "Windows Input Experience", "Default IME"):
            return True

        cls_name = win32gui.GetClassName(hwnd)
        minimized = bool(win32gui.IsIconic(hwnd))
        is_browser = _looks_like_browser(title, cls_name)

        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w, h = max(0, right - left), max(0, bottom - top)
        except Exception:
            w, h = 0, 0

        if not minimized and (w < 180 or h < 120):
            return True

        windows.append(
            WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=cls_name,
                width=w,
                height=h,
                is_minimized=minimized,
                is_browser=is_browser,
            )
        )
        return True

    win32gui.EnumWindows(_enum_cb, None)

    def _sort_key(win: WindowInfo) -> Tuple[int, int, str]:
        tl = win.title.lower()
        if "cymatics" in tl:
            return (0, 0 if not win.is_minimized else 1, tl)
        if win.is_browser:
            return (1, 0 if not win.is_minimized else 1, tl)
        return (2, 0 if not win.is_minimized else 1, tl)

    windows.sort(key=_sort_key)
    return windows


def pick_window_on_next_click(timeout_sec: float = 12.0) -> Optional[WindowInfo]:
    if not IS_WINDOWS:
        return None

    my_pid = os.getpid()
    deadline = time.time() + timeout_sec

    while (win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000) and time.time() < deadline:
        time.sleep(0.03)

    while time.time() < deadline:
        if win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000:
            return None
        if win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000:
            pt = win32api.GetCursorPos()
            hwnd = win32gui.WindowFromPoint(pt)
            if hwnd:
                root_hwnd = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
                try:
                    _, pid = win32process.GetWindowThreadProcessId(root_hwnd)
                    if pid == my_pid:
                        time.sleep(0.15)
                        continue
                except Exception:
                    pass
                title = win32gui.GetWindowText(root_hwnd).strip()
                cls_name = win32gui.GetClassName(root_hwnd)
                left, top, right, bottom = win32gui.GetWindowRect(root_hwnd)
                return WindowInfo(
                    hwnd=root_hwnd,
                    title=title or f"Window {root_hwnd}",
                    class_name=cls_name,
                    width=max(0, right - left),
                    height=max(0, bottom - top),
                    is_minimized=bool(win32gui.IsIconic(root_hwnd)),
                    is_browser=_looks_like_browser(title, cls_name),
                )
        time.sleep(0.04)
    return None


class ScopedWindowController:
    def __init__(self, hwnd: int, mode: str = "background") -> None:
        self.hwnd = hwnd
        self.mode = mode

    def is_valid(self) -> bool:
        if not IS_WINDOWS:
            return False
        return bool(self.hwnd and win32gui.IsWindow(self.hwnd))

    def is_minimized(self) -> bool:
        if not IS_WINDOWS or not self.is_valid():
            return True
        return bool(win32gui.IsIconic(self.hwnd))

    def restore_if_minimized(self) -> None:
        if IS_WINDOWS and self.is_valid() and self.is_minimized():
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            except Exception:
                try:
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                except Exception:
                    pass

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

            result = user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
            if result == 0:
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

        try:
            win32gui.SetForegroundWindow(self.hwnd)
            time.sleep(0.08)
            if win32gui.GetForegroundWindow() != self.hwnd:
                return False
            sx, sy = win32gui.ClientToScreen(self.hwnd, (cx, cy))
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
        if not IS_WINDOWS or not self.is_valid():
            return False
        win32gui.PostMessage(self.hwnd, win32con.WM_APPCOMMAND, self.hwnd, 1 << 16)
        return True

    def navigate_to_url(self, url: str) -> bool:
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
        return self.navigate_back()

    def flash_highlight(self) -> None:
        if not IS_WINDOWS or not self.is_valid():
            return
        try:
            self.restore_if_minimized()
            win32gui.FlashWindow(self.hwnd, True)
        except Exception:
            pass
