"""Select physical client coordinates on a frozen screenshot."""
from __future__ import annotations

import tkinter as tk
import ctypes as C
from ctypes import wintypes as W
from typing import Callable

from PIL import Image, ImageTk

from .models import Rect
from .win32 import U, monitor_workareas
from .taskbar import leave_taskbar_exposed


class Selection(tk.Toplevel):
    def __init__(self, parent: tk.Misc, image: Image.Image, bounds: Rect,
                 point: bool, callback: Callable[[Rect | None], None], allowed: Rect | None = None) -> None:
        super().__init__(parent)
        self.withdraw()
        self.callback, self.point = callback, point
        self.allowed = allowed
        self.owner = parent
        self.owner_was_iconic = parent.state() == "iconic"
        self.front_timer: str | None = None
        self.workareas = monitor_workareas()
        self.start: tuple[int, int] | None = None
        self.selection: Rect | None = None
        self.finished = False
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.canvas = tk.Canvas(self, width=bounds.width, height=bounds.height,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        if allowed:
            self.canvas.create_rectangle(*allowed.box, outline="#00c7ff", width=3)
        self.outline = self.canvas.create_rectangle(0, 0, 0, 0, outline="#ff3030", width=3)
        instruction = "파란 테두리 안의 탭을 클릭하세요 · Esc: 취소" if allowed else ("탭 가운데를 클릭하세요 · Esc: 취소" if point else "드래그한 뒤 놓으면 저장 · Esc: 취소")
        hint_x = allowed.x + allowed.width // 2 if allowed else bounds.width // 2
        hint_y = min(bounds.height - 24, allowed.y + allowed.height + 24) if allowed else bounds.height - 22
        self.canvas.create_text(hint_x, hint_y, text=instruction,
                                fill="#ffffff", font=("Malgun Gothic", 14, "bold"), tags="hint")
        bbox = self.canvas.bbox("hint")
        background = self.canvas.create_rectangle(bbox, fill="#111111", outline="#111111")
        self.canvas.tag_lower(background, "hint")
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.bind("<Escape>", lambda _: self.finish(None))
        self.bind("<Return>", lambda _: self.confirm())
        self.update_idletasks()
        self.deiconify()
        self.hwnd = U.GetAncestor(self.winfo_id(), 2)
        U.SetWindowPos(self.hwnd, -1, bounds.x, bounds.y, bounds.width, bounds.height, 0x0040)
        leave_taskbar_exposed(self.hwnd, bounds)
        self.focus_force()
        self.grab_set()
        self.front_timer = self.after(100, self.keep_front)

    def keep_front(self) -> None:
        self.front_timer = None
        if self.finished:
            return
        if self.owner_was_iconic and self.owner.state() == "normal":
            self.finish(None)
            return
        cursor = W.POINT()
        U.GetCursorPos(C.byref(cursor))
        if any(r.contains(Rect(cursor.x, cursor.y, 1, 1)) for r in self.workareas):
            foreground = U.GetForegroundWindow()
            pointer_window = U.GetAncestor(U.WindowFromPoint(cursor), 2)
            if foreground != self.hwnd or pointer_window != self.hwnd:
                U.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0013)
                if foreground != self.hwnd:
                    U.SetForegroundWindow(self.hwnd)
                    self.focus_force()
        self.front_timer = self.after(100, self.keep_front)

    def press(self, event: tk.Event) -> None:
        if self.point:
            candidate = Rect(event.x, event.y, 1, 1)
            self.selection = candidate if self.allowed is None or self.allowed.contains(candidate) else None
            if self.selection is None:
                self.bell()
        else:
            self.start = (event.x, event.y)
            self.selection = None

    def drag(self, event: tk.Event) -> None:
        if self.start is None:
            return
        x = max(0, min(event.x, self.photo.width()))
        y = max(0, min(event.y, self.photo.height()))
        left, right = sorted((self.start[0], x))
        top, bottom = sorted((self.start[1], y))
        self.selection = Rect(left, top, right - left, bottom - top)
        self.canvas.coords(self.outline, left, top, right, bottom)

    def release(self, event: tk.Event) -> None:
        if self.point:
            if self.selection:
                self.finish(self.selection)
        else:
            self.drag(event)
            self.start = None
            self.confirm()

    def confirm(self) -> None:
        if self.selection and min(self.selection.width, self.selection.height) >= 10:
            self.finish(self.selection)

    def finish(self, result: Rect | None) -> None:
        if self.finished:
            return
        self.finished = True
        if self.front_timer:
            self.after_cancel(self.front_timer)
            self.front_timer = None
        self.grab_release()
        self.destroy()
        self.callback(result)
