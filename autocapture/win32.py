"""Small typed Win32 adapter; all coordinates are physical client pixels."""
from __future__ import annotations

import ctypes as C
import os
import time
from ctypes import wintypes as W
from dataclasses import dataclass

from PIL import Image, ImageGrab

from .models import Rect, covered_by_monitors

U = C.WinDLL("user32", use_last_error=True)


def api(name: str, restype: object, *argtypes: object) -> object:
    func = getattr(U, name)
    func.restype, func.argtypes = restype, argtypes
    return func


enum_callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
monitor_callback = C.WINFUNCTYPE(W.BOOL, W.HANDLE, W.HDC, C.POINTER(W.RECT), W.LPARAM)
api("EnumWindows", W.BOOL, enum_callback, W.LPARAM)
api("IsWindowVisible", W.BOOL, W.HWND)
api("IsWindow", W.BOOL, W.HWND)
api("IsIconic", W.BOOL, W.HWND)
api("GetWindowTextW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
api("GetClassNameW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
api("GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
api("GetClientRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
api("ClientToScreen", W.BOOL, W.HWND, C.POINTER(W.POINT))
api("GetDpiForWindow", W.UINT, W.HWND)
api("SetForegroundWindow", W.BOOL, W.HWND)
api("GetForegroundWindow", W.HWND)
api("ShowWindow", W.BOOL, W.HWND, C.c_int)
api("GetAsyncKeyState", C.c_short, C.c_int)
api("SetCursorPos", W.BOOL, C.c_int, C.c_int)
api("GetCursorPos", W.BOOL, C.POINTER(W.POINT))
api("mouse_event", None, W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t)
api("EnumDisplayMonitors", W.BOOL, W.HDC, C.POINTER(W.RECT), monitor_callback, W.LPARAM)
api("GetAncestor", W.HWND, W.HWND, W.UINT)
api("WindowFromPoint", W.HWND, W.POINT)
api("SetWindowPos", W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
api("AttachThreadInput", W.BOOL, W.DWORD, W.DWORD, W.BOOL)
api("BringWindowToTop", W.BOOL, W.HWND)
K = C.WinDLL("kernel32", use_last_error=True)
K.GetCurrentThreadId.restype = W.DWORD


def enable_dpi_awareness() -> None:
    api("SetProcessDpiAwarenessContext", W.BOOL, C.c_void_p)
    U.SetProcessDpiAwarenessContext(C.c_void_p(-4))


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    class_name: str


def window_identity(hwnd: int) -> Window:
    title, name = C.create_unicode_buffer(1024), C.create_unicode_buffer(256)
    U.GetWindowTextW(hwnd, title, len(title))
    U.GetClassNameW(hwnd, name, len(name))
    return Window(hwnd, title.value, name.value)


def windows() -> list[Window]:
    result = []
    utility_titles = {"Bloomberg Launchpad → PowerPoint", "탭 등록 / 수정", "Bloomberg 캡처 진행"}

    @enum_callback
    def collect(hwnd: int, _: int) -> bool:
        process = W.DWORD()
        U.GetWindowThreadProcessId(hwnd, C.byref(process))
        item = window_identity(hwnd)
        if (U.IsWindowVisible(hwnd) and item.title and process.value != os.getpid()
                and item.title not in utility_titles):
            result.append(item)
        return True

    U.EnumWindows(collect, 0)
    return sorted(result, key=lambda w: ("launchpad" not in w.title.lower(), w.title))


def monitors() -> list[Rect]:
    result = []

    @monitor_callback
    def collect(_: int, __: int, pointer: C.POINTER(W.RECT), ___: int) -> bool:
        r = pointer.contents
        result.append(Rect(r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    U.EnumDisplayMonitors(None, None, collect, 0)
    return result


def monitor_workareas() -> list[Rect]:
    class MonitorInfo(C.Structure):
        _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]

    api("GetMonitorInfoW", W.BOOL, W.HANDLE, C.POINTER(MonitorInfo))
    result = []

    @monitor_callback
    def collect(handle: int, _: int, __: C.POINTER(W.RECT), ___: int) -> bool:
        info = MonitorInfo()
        info.size = C.sizeof(info)
        if U.GetMonitorInfoW(handle, C.byref(info)):
            r = info.work
            result.append(Rect(r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    U.EnumDisplayMonitors(None, None, collect, 0)
    if not result:
        raise RuntimeError("모니터 작업 영역을 확인할 수 없습니다.")
    return result


class Desktop:
    def __init__(self, window: Window) -> None:
        self.window = window

    def geometry(self) -> tuple[Rect, int]:
        if not U.IsWindow(self.window.hwnd):
            raise RuntimeError("대상 창이 닫혔습니다. 창을 다시 선택하세요.")
        if window_identity(self.window.hwnd).class_name != self.window.class_name:
            raise RuntimeError("대상 창이 변경되었습니다. 창을 다시 선택하세요.")
        if U.IsIconic(self.window.hwnd):
            raise RuntimeError("대상 창이 최소화되었습니다. 복원 후 다시 실행하세요.")
        rect, origin = W.RECT(), W.POINT(0, 0)
        if not U.GetClientRect(self.window.hwnd, C.byref(rect)) or not U.ClientToScreen(self.window.hwnd, C.byref(origin)):
            raise C.WinError(C.get_last_error())
        return Rect(origin.x, origin.y, rect.right, rect.bottom), U.GetDpiForWindow(self.window.hwnd)

    def activate(self) -> None:
        if not U.IsWindow(self.window.hwnd):
            raise RuntimeError("대상 창을 찾을 수 없습니다.")
        if U.IsIconic(self.window.hwnd):
            U.ShowWindow(self.window.hwnd, 9)
        U.SetForegroundWindow(self.window.hwnd)
        if U.GetForegroundWindow() != self.window.hwnd:
            current_thread = K.GetCurrentThreadId()
            foreground_thread = U.GetWindowThreadProcessId(U.GetForegroundWindow(), None)
            attached = current_thread != foreground_thread and U.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                U.BringWindowToTop(self.window.hwnd)
                U.SetForegroundWindow(self.window.hwnd)
            finally:
                if attached:
                    U.AttachThreadInput(current_thread, foreground_thread, False)
        time.sleep(0.15)
        if U.GetForegroundWindow() != self.window.hwnd:
            raise RuntimeError("창 활성화에 실패했습니다. Launchpad를 직접 클릭한 뒤 다시 실행하세요.")

    def click(self, x: int, y: int) -> None:
        if U.GetForegroundWindow() != self.window.hwnd:
            raise RuntimeError("다른 창이 활성화되어 탭 클릭을 중단했습니다.")
        target = U.GetAncestor(U.WindowFromPoint(W.POINT(x, y)), 2)
        if target != self.window.hwnd:
            raise RuntimeError("탭 위치가 다른 창에 가려져 있습니다.")
        U.SetCursorPos(x, y)
        # Let the target process handle pointer movement before pressing/releasing.
        time.sleep(.05)
        U.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(.05)
        U.mouse_event(0x0004, 0, 0, 0, 0)

    def capture(self, region: Rect) -> Image.Image:
        layout = monitors()
        if not covered_by_monitors(region, layout):
            raise RuntimeError("캡처 영역이 화면 밖이거나 모니터 사이의 빈 공간에 있습니다.")
        if U.GetForegroundWindow() != self.window.hwnd:
            raise RuntimeError("다른 창이 활성화되어 캡처를 중단했습니다.")
        # Catch topmost overlays at representative points, in addition to foreground checks.
        for fx, fy in ((0, 0), (1, 0), (0, 1), (1, 1), (.5, .5)):
            point = W.POINT(region.x + int((region.width - 1) * fx), region.y + int((region.height - 1) * fy))
            if U.GetAncestor(U.WindowFromPoint(point), 2) != self.window.hwnd:
                raise RuntimeError("캡처 영역이 다른 창에 가려져 있습니다.")
        return self._grab_with_parked_cursor(region, layout)

    def capture_screen(self, region: Rect) -> Image.Image:
        """Graphs can be independent windows, so ownership is not constrained to Launchpad."""
        layout = monitors()
        if not covered_by_monitors(region, layout):
            raise RuntimeError("캡처 영역이 화면 밖이거나 모니터 사이의 빈 공간에 있습니다.")
        return self._grab_with_parked_cursor(region, layout)

    def _grab_with_parked_cursor(self, region: Rect, layout: list[Rect]) -> Image.Image:
        original = W.POINT()
        if not U.GetCursorPos(C.byref(original)):
            raise C.WinError(C.get_last_error())
        rightmost = max(layout, key=lambda r: (r.x + r.width, -r.y))
        if not U.SetCursorPos(rightmost.x + rightmost.width - 1, rightmost.y):
            raise C.WinError(C.get_last_error())
        try:
            # Give hover effects time to clear before taking the screenshot.
            time.sleep(.1)
            return ImageGrab.grab(bbox=region.box, all_screens=True).convert("RGB")
        finally:
            U.SetCursorPos(original.x, original.y)

    def snapshot_desktop(self) -> tuple[Image.Image, Rect, list[Rect]]:
        layout = monitors()
        if not layout:
            raise RuntimeError("모니터를 찾을 수 없습니다.")
        left, top = min(r.x for r in layout), min(r.y for r in layout)
        right = max(r.x + r.width for r in layout)
        bottom = max(r.y + r.height for r in layout)
        bounds = Rect(left, top, right - left, bottom - top)
        # Gaps may appear in the selector, but selected output must be on real displays.
        image = ImageGrab.grab(bbox=bounds.box, all_screens=True).convert("RGB")
        return image, bounds, layout

    def escape_pressed(self) -> bool:
        return bool(U.GetAsyncKeyState(0x1B) & 0x8000)

    def monitor_rects(self) -> list[Rect]:
        return monitors()
