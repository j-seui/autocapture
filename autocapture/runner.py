"""Capture workflow separated from Tk and the physical desktop for testing."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image

from .exporter import export_pptx
from .models import Config, Rect, TocGroup, covered_by_monitors


class Backend(Protocol):
    def activate(self) -> None: ...
    def geometry(self) -> tuple[Rect, int]: ...
    def click(self, x: int, y: int) -> None: ...
    def capture(self, region: Rect) -> Image.Image: ...
    def capture_screen(self, region: Rect) -> Image.Image: ...
    def escape_pressed(self) -> bool: ...
    def monitor_rects(self) -> list[Rect]: ...


@dataclass
class Result:
    pptx: Path | None
    session: Path
    completed: list[str]
    missing: list[str]
    error: str = ""


class Stopped(Exception):
    pass


def checked_geometry(backend: Backend, config: Config) -> Rect:
    bounds, dpi = backend.geometry()
    if (bounds.width, bounds.height, dpi) != (config.width, config.height, config.dpi):
        raise RuntimeError("창 크기 또는 화면 배율이 설정과 다릅니다. 원래 크기로 복원하거나 탭 영역을 다시 지정하세요.")
    return bounds


def run_capture(config: Config, backend: Backend, stop: threading.Event,
                notify: Callable[[str], None], hide: Callable[[], None]) -> Result:
    config.validate(complete=True)
    output = Path(config.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    session = output / ("captures_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    session.mkdir()
    captures: list[tuple[str, Path]] = []
    error = ""

    def wait(seconds: float) -> None:
        import time
        deadline = time.monotonic() + seconds
        while True:
            if stop.is_set() or backend.escape_pressed():
                raise Stopped("사용자가 캡처를 중단했습니다.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            stop.wait(min(.05, remaining))

    try:
        for index, tab in enumerate(config.tabs):
            wait(0)
            notify(f"{index + 1}/{len(config.tabs)}  {tab.name} — 준비 중")
            hide()
            backend.activate()
            wait(0)
            bounds = checked_geometry(backend, config)
            point = Rect(bounds.x + tab.click[0], bounds.y + tab.click[1], 1, 1)
            region = tab.region if tab.region_space == "screen" else tab.region.offset(bounds.x, bounds.y)
            if tab.region_space == "screen" and sorted(r.box for r in tab.screen_layout) != sorted(r.box for r in backend.monitor_rects()):
                raise RuntimeError("모니터 배치 또는 해상도가 변경되었습니다. 그래프 영역을 다시 지정하세요.")
            if not all(covered_by_monitors(r, backend.monitor_rects()) for r in (point, region)):
                raise RuntimeError("탭 위치 또는 캡처 영역이 화면 밖입니다.")
            backend.click(point.x, point.y)
            notify(f"{index + 1}/{len(config.tabs)}  {tab.name} — 로딩 대기 {tab.delay:g}초")
            wait(tab.delay)
            hide()
            wait(.25)
            if checked_geometry(backend, config) != bounds:
                raise RuntimeError("탭 전환 중 창이 이동했습니다. 다시 실행하세요.")
            if tab.region_space == "screen" and sorted(r.box for r in tab.screen_layout) != sorted(r.box for r in backend.monitor_rects()):
                raise RuntimeError("모니터 배치 또는 해상도가 변경되었습니다. 그래프 영역을 다시 지정하세요.")
            captured = backend.capture_screen(region) if tab.region_space == "screen" else backend.capture(region)
            path = session / f"{index + 1:03d}.png"
            captured.save(path)
            captures.append((tab.name, path))
    except Exception as exc:
        error = str(exc) or type(exc).__name__
    completed = [name for name, _ in captures]
    missing = [tab.name for tab in config.tabs[len(captures):]]
    result = Result(None, session, completed, missing, error)
    write_result(result)
    return result


def write_result(result: Result) -> None:
    try:
        (result.session / "result.json").write_text(json.dumps({
            "pptx": str(result.pptx) if result.pptx else None,
            "completed": result.completed, "missing": result.missing, "error": result.error,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        result.error += f"\n실행 기록 저장 실패: {exc}"


def save_capture(result: Result, output: Path, groups: list[TocGroup] | None = None) -> Path:
    """Export only the immutable capture session, never the current tab settings."""
    captures = [(name, result.session / f"{i:03d}.png")
                for i, name in enumerate(result.completed, 1)]
    destination = export_pptx(captures, output, partial=bool(result.missing), groups=groups)
    result.pptx = destination
    write_result(result)
    return destination
