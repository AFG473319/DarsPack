"""Windows 11 Fluent System & DWM backdrop integration.

Applies native Windows 11 Immersive Dark Mode, rounded corners, and
Mica / Acrylic system backdrop to top-level windows via dwmapi.dll.
Fails silently and safely on non-Windows platforms or in headless tests.
"""
from __future__ import annotations

import sys


def apply_fluent_window_effects(window, dark: bool = True) -> bool:
    """Apply native Windows 11 Mica backdrop and titlebar styling.

    dark=False switches the titlebar (and Mica tint) to the light look,
    matching the light theme (پوسته‌ی روشن)."""
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.winId())
        if not hwnd:
            return False

        dwmapi = ctypes.windll.dwmapi

        # 1. Immersive Dark Mode Titlebar (Windows 10 1809+ / Windows 11)
        dark_value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE, 19 = older Win10
            if dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(attr),
                ctypes.byref(dark_value),
                ctypes.sizeof(dark_value),
            ) == 0:
                break

        # 2. Windows 11 Rounded Corners (DWMWA_WINDOW_CORNER_PREFERENCE = 33)
        # 2 = DWMWCP_ROUND
        corner_pref = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(33),
            ctypes.byref(corner_pref),
            ctypes.sizeof(corner_pref),
        )

        # 3. Windows 11 System Backdrop Type (DWMWA_SYSTEMBACKDROP_TYPE = 38, Win11 22H2+)
        # 2 = DWMSBT_MAINWINDOW (Mica)
        # 4 = DWMSBT_TABBEDWINDOW (Mica Alt)
        backdrop_type = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(38),
            ctypes.byref(backdrop_type),
            ctypes.sizeof(backdrop_type),
        )

        return True
    except Exception:
        return False
