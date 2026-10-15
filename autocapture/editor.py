"""Per-tab calibration dialog."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from PIL import ImageTk

from .models import Config, Rect, Tab, covered_by_monitors
from .runner import checked_geometry
from .selection import Selection
from .taskbar import TaskbarSession
from .win32 import Desktop


class TabEditor(tk.Toplevel):
    def __init__(self, parent: tk.Tk, desktop: Desktop, config: Config,
                 existing: Tab | None, callback: Callable[[Tab], None]) -> None:
        super().__init__(parent)
        self.parent, self.desktop, self.config, self.callback = parent, desktop, config, callback
        self.selecting = False
        self.taskbar: TaskbarSession | None = None
        self.pending: str | None = None
        self.overlay: Selection | None = None
        self.title("탭 등록 / 수정")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.click = existing.click if existing else None
        self.region = existing.region if existing else None
        self.region_space = existing.region_space if existing else "screen"
        self.screen_layout = list(existing.screen_layout) if existing else []
        self.name = tk.StringVar(value=existing.name if existing else "")
        self.delay = tk.StringVar(value=str(existing.delay if existing else 3))
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="원하는 탭 이름을 입력하고 캡처할 순서대로 등록하세요.").pack(anchor="w")
        ttk.Label(frame, text=f"대상 창: {desktop.window.title}", wraplength=580).pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, text="탭 위치는 Launchpad 안에서, 그래프 영역은 전체 화면에서 지정합니다.\n별도 그래프 창도 포함할 수 있습니다. 그래프 창 위치가 바뀌면 영역을 다시 지정하세요.", wraplength=580).pack(anchor="w", pady=4)
        fields = ttk.Frame(frame)
        fields.pack(fill="x", pady=12)
        ttk.Label(fields, text="탭 이름").grid(row=0, column=0, padx=5)
        ttk.Entry(fields, textvariable=self.name, width=24).grid(row=0, column=1)
        ttk.Label(fields, text="대기 시간(초)").grid(row=0, column=2, padx=10)
        ttk.Entry(fields, textvariable=self.delay, width=8).grid(row=0, column=3)
        ttk.Button(frame, text="1. 탭 클릭 위치 지정", command=lambda: self.select(True)).pack(fill="x", pady=4)
        ttk.Button(frame, text="2. 그래프 영역 지정 (전체 화면)", command=lambda: self.select(False)).pack(fill="x", pady=4)
        self.details = ttk.Label(frame, wraplength=580)
        self.details.pack(anchor="w", pady=8)
        self.preview = ttk.Label(frame, text="영역을 지정하면 캡처 미리보기가 표시됩니다.", anchor="center")
        self.preview.pack(fill="both", pady=8)
        ttk.Button(frame, text="이 탭 저장", command=self.commit).pack(side="right")
        ttk.Button(frame, text="취소", command=self.close).pack(side="right", padx=8)
        self.bind("<Return>", self.save_on_enter)
        self.bind("<KP_Enter>", self.save_on_enter)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.after_idle(self.focus_editor)

    def focus_editor(self) -> None:
        if self.winfo_exists() and not self.selecting:
            self.lift()
            self.focus_force()

    def refresh(self) -> None:
        mode = "화면 기준" if self.region_space == "screen" else "창 기준 (기존 설정)"
        self.details.configure(text=f"클릭 위치: {self.click or '미지정'}\n캡처 영역 [{mode}]: {self.region or '미지정'}")

    def restore(self) -> None:
        self.selecting = False
        if self.pending:
            self.after_cancel(self.pending)
            self.pending = None
        if self.taskbar:
            self.taskbar.finish()
            self.taskbar = None
        self.overlay = None
        self.parent.deiconify()
        self.deiconify()
        self.update_idletasks()
        self.focus_editor()
        self.grab_set()

    def cancel_selection(self) -> None:
        if not self.selecting:
            return
        if self.overlay and self.overlay.winfo_exists():
            self.overlay.finish(None)
        else:
            self.restore()

    def select(self, point: bool) -> None:
        if self.selecting:
            return
        try:
            delay = float(self.delay.get())
            if not .5 <= delay <= 120:
                raise ValueError("대기 시간은 0.5~120초로 입력하세요.")
            if not point and self.click is None:
                raise ValueError("먼저 탭 클릭 위치를 지정하세요.")
            self.selecting = True
            self.grab_release()
            self.withdraw()
            self.taskbar = TaskbarSession(self.parent, self.cancel_selection)
            self.update_idletasks()
            # Allow pending Tk/Windows hide and focus events to finish first.
            self.pending = self.after(200, lambda: self.begin_selection(point, delay))
        except Exception as exc:
            self.restore()
            messagebox.showerror("설정 오류", str(exc), parent=self)

    def begin_selection(self, point: bool, delay: float) -> None:
        if not self.selecting:
            return
        try:
            self.desktop.activate()
            bounds = checked_geometry(self.desktop, self.config)
            if not point:
                self.desktop.click(bounds.x + self.click[0], bounds.y + self.click[1])
            self.pending = self.after(int((.3 if point else delay) * 1000), lambda: self.open_selection(point, bounds))
        except Exception as exc:
            self.restore()
            messagebox.showerror("설정 오류", str(exc), parent=self)

    def open_selection(self, point: bool, bounds: Rect) -> None:
        if not self.selecting:
            return
        try:
            # Only tab-point selection belongs to the Launchpad window.
            if point:
                self.desktop.activate()
            if checked_geometry(self.desktop, self.config) != bounds:
                raise RuntimeError("영역 지정 중 창이 이동했습니다. 다시 지정하세요.")
            screenshot, selection_bounds, layout = self.desktop.snapshot_desktop()
            allowed = bounds.offset(-selection_bounds.x, -selection_bounds.y) if point else None

            def selected(rect: Rect | None) -> None:
                if rect:
                    if point:
                        self.click = (rect.x + selection_bounds.x - bounds.x,
                                      rect.y + selection_bounds.y - bounds.y)
                    else:
                        absolute = rect.offset(selection_bounds.x, selection_bounds.y)
                        if not covered_by_monitors(absolute, layout):
                            self.restore()
                            messagebox.showerror("영역 지정 오류", "모니터 화면 안의 영역을 지정하세요. 모니터 사이의 빈 공간은 포함할 수 없습니다.", parent=self)
                            return
                        self.region = absolute
                        self.region_space = "screen"
                        self.screen_layout = layout
                        image = screenshot.crop(rect.box)
                        image.thumbnail((580, 310))
                        self.photo = ImageTk.PhotoImage(image, master=self)
                        self.preview.configure(image=self.photo, text="")
                self.restore()
                self.refresh()

            self.overlay = Selection(self.parent, screenshot, selection_bounds, point, selected, allowed)
        except Exception as exc:
            self.restore()
            messagebox.showerror("영역 지정 오류", str(exc), parent=self)

    def commit(self) -> None:
        try:
            if self.click is None or self.region is None:
                raise ValueError("탭 클릭 위치와 캡처 영역을 모두 지정하세요.")
            tab = Tab(self.name.get().strip(), self.click, self.region, float(self.delay.get()),
                      self.region_space, self.screen_layout)
            tab.validate(self.config.width, self.config.height)
            self.callback(tab)
            self.close()
        except Exception as exc:
            messagebox.showerror("저장 오류", str(exc), parent=self)

    def save_on_enter(self, _: tk.Event) -> str:
        if not self.selecting:
            self.commit()
        return "break"

    def close(self) -> None:
        self.grab_release()
        self.destroy()
        self.parent.deiconify()
        self.parent.lift()
        self.parent.focus_force()
