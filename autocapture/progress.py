"""Thread-safe UI bridge; progress window is hidden before every screenshot."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .models import Config
from .runner import Result, run_capture
from .taskbar import TaskbarSession
from .win32 import Desktop, U


class CaptureProgress:
    def __init__(self, root: tk.Tk, config: Config, desktop: Desktop,
                 finished: Callable[[Result | None], None]) -> None:
        self.root, self.config, self.desktop, self.finished = root, config, desktop, finished
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.window = tk.Toplevel(root)
        self.window.title("Bloomberg 캡처 진행")
        self.window.geometry("440x125")
        self.window.attributes("-topmost", True)
        self.status = ttk.Label(self.window, text="시작 준비 중…", padding=12)
        self.status.pack(fill="x")
        ttk.Button(self.window, text="중지 (Esc)", command=self.stop.set).pack()
        ttk.Label(self.window, text="캡처 순간에는 이 창이 잠시 숨겨집니다.").pack(pady=5)
        self.window.protocol("WM_DELETE_WINDOW", self.stop.set)
        self.taskbar = TaskbarSession(root, self.stop.set)
        self.window.withdraw()
        self.window.update_idletasks()
        threading.Thread(target=self.work, daemon=True).start()
        self.root.after(50, self.poll)

    def hide(self) -> None:
        ready = threading.Event()
        self.events.put(("hide", ready))
        if not ready.wait(10):
            raise RuntimeError("진행 창을 숨기지 못해 캡처를 중단했습니다.")

    def work(self) -> None:
        try:
            result = run_capture(self.config, self.desktop, self.stop,
                                 lambda text: self.events.put(("status", text)), self.hide)
            self.events.put(("done", result))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def show_without_focus(self) -> None:
        hwnd = U.GetAncestor(self.window.winfo_id(), 2)
        U.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        U.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0013)  # NOMOVE | NOSIZE | NOACTIVATE

    def poll(self) -> None:
        while not self.events.empty():
            kind, payload = self.events.get_nowait()
            if kind == "status":
                self.status.configure(text=payload)
                if "로딩 대기" in payload:
                    self.show_without_focus()
            elif kind == "hide":
                U.ShowWindow(U.GetAncestor(self.window.winfo_id(), 2), 0)
                self.root.update_idletasks()
                payload.set()
            elif kind in ("done", "error"):
                self.taskbar.finish()
                self.window.destroy()
                self.root.deiconify()
                if kind == "error":
                    messagebox.showerror("캡처 오류", payload, parent=self.root)
                    self.finished(None)
                else:
                    self.finished(payload)
                return
        self.root.after(50, self.poll)

