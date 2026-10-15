"""Edit table-of-contents groups without changing capture order."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .models import Tab, TocGroup


class TocEditor(tk.Toplevel):
    def __init__(self, parent: tk.Misc, tabs: list[Tab], groups: list[TocGroup],
                 callback: Callable[[list[TocGroup]], None]) -> None:
        super().__init__(parent)
        self.callback = callback
        self.tab_names = [tab.name for tab in tabs]
        self.assignments = {tab_name: group.name for group in groups for tab_name in group.tabs}
        self.title("목차 만들기")
        self.geometry("570x540")
        self.minsize(500, 420)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="목차 묶음", font=("Malgun Gothic", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Ctrl 또는 Shift로 탭을 여러 개 선택하고 묶음 이름을 지정하세요.\n묶지 않은 탭은 목차에 개별 항목으로 표시됩니다.").pack(anchor="w", pady=(5, 10))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("tab", "group"), show="headings", selectmode="extended")
        self.table.heading("tab", text="탭 / 슬라이드")
        self.table.heading("group", text="목차 묶음")
        self.table.column("tab", width=250)
        self.table.column("group", width=240)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self.show_selected_group)
        self.group_name = tk.StringVar()
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(10, 5))
        ttk.Label(row, text="묶음 이름").pack(side="left", padx=(0, 8))
        self.name_entry = ttk.Entry(row, textvariable=self.group_name)
        self.name_entry.pack(side="left", fill="x", expand=True)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=5)
        ttk.Button(row, text="선택 탭 묶기 / 이름 변경", command=self.assign).pack(side="left")
        ttk.Button(row, text="선택 탭 묶음 해제", command=self.unassign).pack(side="left", padx=8)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(15, 0))
        ttk.Button(row, text="저장", command=self.save).pack(side="right")
        ttk.Button(row, text="취소", command=self.close).pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.name_entry.focus_set()

    def refresh(self) -> None:
        selected = self.table.selection()
        self.table.delete(*self.table.get_children())
        for index, name in enumerate(self.tab_names):
            self.table.insert("", "end", iid=str(index), values=(name, self.assignments.get(name, "")))
        for item in selected:
            if self.table.exists(item):
                self.table.selection_add(item)

    def selected_names(self) -> list[str]:
        return [self.tab_names[int(item)] for item in self.table.selection()]

    def show_selected_group(self, _: tk.Event) -> None:
        names = self.selected_names()
        groups = {self.assignments.get(name, "") for name in names}
        if len(groups) == 1:
            self.group_name.set(groups.pop())

    def assign(self) -> None:
        names = self.selected_names()
        name = self.group_name.get().strip()
        if not names:
            messagebox.showinfo("목차 만들기", "묶을 탭을 선택하세요.", parent=self)
            return
        if not name or len(name) > 80:
            messagebox.showerror("목차 만들기", "묶음 이름을 1~80자로 입력하세요.", parent=self)
            return
        existing = next((value for value in self.assignments.values() if value.casefold() == name.casefold()), name)
        for tab_name in names:
            self.assignments[tab_name] = existing
        self.refresh()

    def unassign(self) -> None:
        for tab_name in self.selected_names():
            self.assignments.pop(tab_name, None)
        self.refresh()

    def save(self) -> None:
        groups: dict[str, TocGroup] = {}
        for tab_name in self.tab_names:
            name = self.assignments.get(tab_name)
            if name:
                groups.setdefault(name.casefold(), TocGroup(name, [])).tabs.append(tab_name)
        try:
            self.callback(list(groups.values()))
        except Exception as exc:
            messagebox.showerror("목차 저장 실패", str(exc), parent=self)
            return
        self.close()

    def close(self) -> None:
        self.grab_release()
        self.destroy()
