"""Keep the main taskbar entry and restore/cancel from it during screen selection."""
from __future__ import annotations

import ctypes as C
import tkinter as tk
from ctypes import wintypes as W
from typing import Callable

from .models import Rect
from .win32 import U, api, monitor_workareas


class TaskbarSession:
    def __init__(self, root: tk.Tk, cancel: Callable[[], None]) -> None:
        self.root, self.cancel = root, cancel
        self.active = True
        self.binding = root.bind("<Map>", self.on_map, add="+")
        root.iconify()
        root.update_idletasks()

    def on_map(self, event: tk.Event) -> None:
        if self.active and event.widget is self.root and self.root.state() == "normal":
            self.active = False
            self.root.after_idle(self.cancel)

    def finish(self) -> None:
        self.active = False
        if self.binding:
            self.root.unbind("<Map>", self.binding)
            self.binding = None


def leave_taskbar_exposed(hwnd: int, bounds: Rect) -> None:
    """Cut taskbars/appbars out of the screenshot overlay so their real buttons work."""
    gdi = C.WinDLL("gdi32", use_last_error=True)
    gdi.CreateRectRgn.argtypes = [C.c_int] * 4
    gdi.CreateRectRgn.restype = W.HANDLE
    gdi.CombineRgn.argtypes = [W.HANDLE, W.HANDLE, W.HANDLE, C.c_int]
    gdi.CombineRgn.restype = C.c_int
    gdi.DeleteObject.argtypes = [W.HANDLE]
    gdi.DeleteObject.restype = W.BOOL
    api("SetWindowRgn", C.c_int, W.HWND, W.HANDLE, W.BOOL)
    region = gdi.CreateRectRgn(0, 0, 0, 0)
    if not region:
        raise C.WinError(C.get_last_error())
    try:
        for work in monitor_workareas():
            left, top = max(work.x, bounds.x), max(work.y, bounds.y)
            right = min(work.x + work.width, bounds.x + bounds.width)
            bottom = min(work.y + work.height, bounds.y + bounds.height)
            if left >= right or top >= bottom:
                continue
            part = gdi.CreateRectRgn(left - bounds.x, top - bounds.y, right - bounds.x, bottom - bounds.y)
            if not part:
                raise C.WinError(C.get_last_error())
            try:
                if not gdi.CombineRgn(region, region, part, 2):  # RGN_OR
                    raise C.WinError(C.get_last_error())
            finally:
                gdi.DeleteObject(part)
        if not U.SetWindowRgn(hwnd, region, True):
            raise C.WinError(C.get_last_error())
        region = None  # Windows now owns the region.
    finally:
        if region:
            gdi.DeleteObject(region)
