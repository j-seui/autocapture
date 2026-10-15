"""Desktop application entry UI."""
from __future__ import annotations

import copy
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .editor import TabEditor
from .models import Config, Tab, TocGroup, config_path, load_config, save_config
from .progress import CaptureProgress
from .runner import Result, save_capture
from .toc_editor import TocEditor
from .win32 import Desktop, windows


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bloomberg Launchpad → PowerPoint")
        self.geometry("850x620")
        self.minsize(740, 520)
        self.running = False
        self.last_output: Path | None = None
        self.last_capture: Result | None = None
        try:
            self.config_data = load_config()
        except Exception as exc:
            self.config_data = Config()
            messagebox.showwarning("설정 읽기 실패", f"기존 설정을 읽을 수 없습니다.\n{exc}\n\n{config_path()}", parent=self)
        self.folder = tk.StringVar(value=self.config_data.output_dir or str(Path.home() / "Documents" / "BloombergCaptures"))
        self.status = tk.StringVar(value="처음에는 창 선택 → 탭 등록 → 저장 폴더 선택 순서로 설정하세요.")
        self.build_ui()
        self.refresh_windows()
        self.refresh_tabs()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self) -> None:
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Bloomberg Launchpad 캡처", font=("Malgun Gothic", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="원하는 탭을 원하는 순서로 등록 · 캡처 후 PPT 저장 · 탭당 슬라이드 1장").pack(anchor="w", pady=(4, 16))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.window_picker = ttk.Combobox(row, state="readonly")
        self.window_picker.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="창 목록 새로고침", command=self.refresh_windows).pack(side="right", padx=(8, 0))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=12)
        ttk.Label(row, text="저장 폴더").pack(side="left", padx=(0, 8))
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="찾아보기", command=self.choose_folder).pack(side="right", padx=(8, 0))
        self.table = ttk.Treeview(frame, columns=("name", "delay", "click", "area"), show="headings", selectmode="browse", height=12)
        for col, title, width in (("name", "탭 이름", 170), ("delay", "대기(초)", 80),
                                  ("click", "탭 클릭 위치", 140), ("area", "영역 (x, y, 가로, 세로)", 390)):
            self.table.heading(col, text=title)
            self.table.column(col, width=width)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<Double-1>", lambda _: self.edit_tab())
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=10)
        for label, command in (("탭 추가", lambda: self.edit_tab(True)), ("수정", self.edit_tab),
                               ("삭제", self.delete_tab), ("순서 위로", lambda: self.move(-1)),
                               ("순서 아래로", lambda: self.move(1)), ("전체 재설정", self.reset_tabs)):
            ttk.Button(row, text=label, command=command).pack(side="left", padx=(0, 5))
        ttk.Button(row, text="목차 만들기", command=self.edit_toc).pack(side="left", padx=(0, 5))
        ttk.Label(frame, textvariable=self.status, wraplength=760).pack(anchor="w", pady=8)
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.save_button = ttk.Button(row, text="PPT 저장", command=self.save_ppt, state="disabled")
        self.save_button.pack(side="right")
        ttk.Button(row, text="캡처 시작", command=self.start).pack(side="right", padx=8)
        ttk.Button(row, text="저장 폴더 열기", command=self.open_folder).pack(side="left")
        ttk.Button(row, text="설정 저장", command=self.persist_message).pack(side="left", padx=8)

    def refresh_windows(self) -> None:
        self.available = windows()
        self.window_picker["values"] = [f"{w.title}  [0x{w.hwnd:X}]" for w in self.available]
        self.window_picker.set("")
        exact = [i for i, w in enumerate(self.available) if w.title == self.config_data.window_title and w.class_name == self.config_data.window_class]
        matches = exact or [i for i, w in enumerate(self.available) if "launchpad" in w.title.lower() and (not self.config_data.window_class or w.class_name == self.config_data.window_class)]
        if len(matches) == 1:
            self.window_picker.current(matches[0])

    def desktop(self) -> Desktop:
        index = self.window_picker.current()
        if index < 0:
            raise ValueError("대상 Launchpad 창을 선택하세요.")
        return Desktop(self.available[index])

    def refresh_tabs(self) -> None:
        self.table.delete(*self.table.get_children())
        for index, tab in enumerate(self.config_data.tabs):
            r = tab.region
            mode = "화면" if tab.region_space == "screen" else "창"
            self.table.insert("", "end", iid=str(index), values=(tab.name, f"{tab.delay:g}",
                                                             f"{tab.click[0]}, {tab.click[1]}",
                                                             f"[{mode}] {r.x}, {r.y}, {r.width}, {r.height}"))

    def selected(self) -> int | None:
        selection = self.table.selection()
        return int(selection[0]) if selection else None

    def persist(self) -> None:
        self.config_data.output_dir = self.folder.get().strip()
        save_config(self.config_data)

    def persist_message(self) -> None:
        try:
            self.persist()
            self.status.set(f"설정 저장 완료: {config_path()}")
        except Exception as exc:
            messagebox.showerror("설정 저장 실패", str(exc), parent=self)

    def choose_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="PPT 저장 폴더 선택")
        if path:
            self.folder.set(path)

    def edit_tab(self, adding: bool = False) -> None:
        index = None if adding else self.selected()
        if not adding and index is None:
            return
        try:
            desktop = self.desktop()
            bounds, dpi = desktop.geometry()
            config = self.config_data
            if config.tabs and (config.width, config.height, config.dpi) != (bounds.width, bounds.height, dpi):
                raise ValueError("창 크기·배율이 변경되었습니다. 원래 상태로 복원하거나 전체 재설정 후 등록하세요.")
            config.width, config.height, config.dpi = bounds.width, bounds.height, dpi
            config.window_title, config.window_class = desktop.window.title, desktop.window.class_name

            def commit(tab: Tab) -> None:
                candidate = copy.deepcopy(self.config_data)
                if index is None:
                    candidate.tabs.append(tab)
                else:
                    old_name = candidate.tabs[index].name
                    candidate.tabs[index] = tab
                    for group in candidate.toc_groups:
                        group.tabs = [tab.name if name == old_name else name for name in group.tabs]
                candidate.output_dir = self.folder.get().strip()
                save_config(candidate)
                self.config_data = candidate
                self.refresh_tabs()
                self.status.set(f"{tab.name} 저장 완료. 총 {len(candidate.tabs)}개 탭")

            TabEditor(self, desktop, config, None if index is None else config.tabs[index], commit)
        except Exception as exc:
            messagebox.showerror("탭 설정 오류", str(exc), parent=self)

    def delete_tab(self) -> None:
        index = self.selected()
        if index is not None:
            name = self.config_data.tabs[index].name
            del self.config_data.tabs[index]
            for group in self.config_data.toc_groups:
                group.tabs = [tab_name for tab_name in group.tabs if tab_name != name]
            self.config_data.toc_groups = [group for group in self.config_data.toc_groups if group.tabs]
            self.refresh_tabs()
            self.persist_message()

    def edit_toc(self) -> None:
        if not self.config_data.tabs:
            messagebox.showinfo("목차 만들기", "먼저 탭을 등록하세요.", parent=self)
            return

        def commit(groups: list[TocGroup]) -> None:
            candidate = copy.deepcopy(self.config_data)
            candidate.toc_groups = groups
            candidate.output_dir = self.folder.get().strip()
            save_config(candidate)
            self.config_data = candidate
            self.status.set(f"목차 묶음 {len(groups)}개 저장 완료")

        TocEditor(self, self.config_data.tabs, self.config_data.toc_groups, commit)

    def move(self, step: int) -> None:
        index = self.selected()
        if index is None or not 0 <= index + step < len(self.config_data.tabs):
            return
        tabs = self.config_data.tabs
        tabs[index], tabs[index + step] = tabs[index + step], tabs[index]
        self.refresh_tabs()
        self.table.selection_set(str(index + step))
        self.persist_message()

    def reset_tabs(self) -> None:
        if messagebox.askyesno("전체 재설정", "저장된 탭 위치와 캡처 영역을 모두 지우고 다시 등록할까요?", parent=self):
            self.config_data.tabs.clear()
            self.config_data.toc_groups.clear()
            self.refresh_tabs()
            self.persist_message()

    def start(self) -> None:
        if self.running:
            return
        try:
            self.config_data.output_dir = self.folder.get().strip()
            self.config_data.validate(complete=True)
            desktop = self.desktop()
            self.config_data.window_title, self.config_data.window_class = desktop.window.title, desktop.window.class_name
            self.persist()
            self.running = True
            self.last_capture = None
            self.save_button.configure(state="disabled")
            self.progress = CaptureProgress(self, copy.deepcopy(self.config_data), desktop, self.finished)
        except Exception as exc:
            self.running = False
            messagebox.showerror("실행 오류", str(exc), parent=self)

    def finished(self, result: Result | None) -> None:
        self.running = False
        if result is None:
            return
        self.last_capture = result
        self.save_button.configure(state="normal" if result.completed else "disabled")
        text = f"완료 {len(result.completed)}개 / 누락 {len(result.missing)}개\n"
        text += f"캡처 이미지: {result.session}"
        if result.completed:
            text += "\nPPT 저장 버튼을 누르면 이 캡처 결과로 PPT를 만듭니다."
        if result.missing:
            text += "\n누락 탭: " + ", ".join(result.missing)
        if result.error:
            text += "\n\n" + result.error
        self.status.set(text)
        (messagebox.showwarning if result.error else messagebox.showinfo)("캡처 결과", text, parent=self)

    def save_ppt(self) -> None:
        if self.running or not self.last_capture or not self.last_capture.completed:
            return
        try:
            folder = self.folder.get().strip()
            if not folder:
                raise ValueError("PPT를 저장할 폴더를 선택하세요.")
            self.save_button.configure(state="disabled")
            self.status.set("PPT 저장 중…")
            self.update_idletasks()
            self.last_output = save_capture(self.last_capture, Path(folder), self.config_data.toc_groups)
            self.status.set(f"PPT 저장 완료: {self.last_output}")
            messagebox.showinfo("PPT 저장 완료", str(self.last_output), parent=self)
        except Exception as exc:
            self.status.set("PPT 저장에 실패했습니다. 폴더를 확인하고 다시 저장하세요.")
            messagebox.showerror("PPT 저장 실패", f"{exc}\n캡처 PNG는 보존되어 다시 저장할 수 있습니다.", parent=self)
        finally:
            self.save_button.configure(state="normal")

    def open_folder(self) -> None:
        path = Path(self.folder.get().strip())
        if path.is_dir():
            os.startfile(str(path.resolve()))
        else:
            messagebox.showinfo("저장 폴더", "첫 캡처 실행 시 저장 폴더가 생성됩니다.", parent=self)

    def close(self) -> None:
        if self.running:
            self.progress.stop.set()
        else:
            self.destroy()
