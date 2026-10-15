"""Validated, versioned configuration and screen geometry."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.x + self.width, self.y + self.height

    def contains(self, other: Rect) -> bool:
        return (other.width > 0 and other.height > 0 and
                self.x <= other.x and self.y <= other.y and
                other.x + other.width <= self.x + self.width and
                other.y + other.height <= self.y + self.height)

    def offset(self, x: int, y: int) -> Rect:
        return Rect(self.x + x, self.y + y, self.width, self.height)


def covered_by_monitors(rect: Rect, monitors: list[Rect]) -> bool:
    """Reject uncovered monitor gaps, including negative desktop coordinates."""
    remaining = [rect]
    for monitor in monitors:
        next_parts = []
        for part in remaining:
            l, t = max(part.x, monitor.x), max(part.y, monitor.y)
            r = min(part.x + part.width, monitor.x + monitor.width)
            b = min(part.y + part.height, monitor.y + monitor.height)
            if l >= r or t >= b:
                next_parts.append(part)
                continue
            for candidate in (Rect(part.x, part.y, part.width, t - part.y),
                              Rect(part.x, b, part.width, part.y + part.height - b),
                              Rect(part.x, t, l - part.x, b - t),
                              Rect(r, t, part.x + part.width - r, b - t)):
                if candidate.width > 0 and candidate.height > 0:
                    next_parts.append(candidate)
        remaining = next_parts
    return not remaining


@dataclass
class Tab:
    name: str
    click: tuple[int, int]
    region: Rect
    delay: float = 3.0
    region_space: str = "window"
    screen_layout: list[Rect] = field(default_factory=list)

    def validate(self, width: int, height: int) -> None:
        if not self.name.strip() or len(self.name) > 80:
            raise ValueError("탭 이름은 1~80자로 입력하세요.")
        if not math.isfinite(self.delay) or not 0.5 <= self.delay <= 120:
            raise ValueError("대기 시간은 0.5~120초로 입력하세요.")
        bounds = Rect(0, 0, width, height)
        if not bounds.contains(Rect(*self.click, 1, 1)):
            raise ValueError("탭 클릭 위치가 창 밖입니다. 다시 지정하세요.")
        if min(self.region.width, self.region.height) < 10:
            raise ValueError("캡처 영역은 가로·세로 10픽셀 이상이어야 합니다.")
        if self.region_space == "window":
            if not bounds.contains(self.region):
                raise ValueError("기존 창 기준 캡처 영역이 창 밖입니다. 전체 화면에서 다시 지정하세요.")
        elif self.region_space == "screen":
            if not self.screen_layout or not covered_by_monitors(self.region, self.screen_layout):
                raise ValueError("캡처 영역이 화면 밖이거나 모니터 사이의 빈 공간에 있습니다.")
        else:
            raise ValueError("지원하지 않는 캡처 좌표 형식입니다.")


@dataclass
class TocGroup:
    name: str
    tabs: list[str]


@dataclass
class Config:
    window_title: str = ""
    window_class: str = ""
    width: int = 0
    height: int = 0
    dpi: int = 96
    output_dir: str = ""
    tabs: list[Tab] = field(default_factory=list)
    version: int = 2
    toc_groups: list[TocGroup] = field(default_factory=list)

    def validate(self, complete: bool = False) -> None:
        if self.version != 2:
            raise ValueError("지원하지 않는 설정 버전입니다.")
        if self.tabs and (self.width <= 0 or self.height <= 0 or self.dpi <= 0):
            raise ValueError("저장된 창 크기 또는 배율이 올바르지 않습니다.")
        for tab in self.tabs:
            tab.validate(self.width, self.height)
        if len({tab.name.casefold() for tab in self.tabs}) != len(self.tabs):
            raise ValueError("탭 이름은 중복될 수 없습니다.")
        known_tabs = {tab.name.casefold() for tab in self.tabs}
        used_tabs: set[str] = set()
        group_names: set[str] = set()
        for group in self.toc_groups:
            name = group.name.strip()
            if not name or len(name) > 80 or name.casefold() in group_names:
                raise ValueError("목차 묶음 이름은 1~80자로 입력하고 중복되지 않아야 합니다.")
            group_names.add(name.casefold())
            if not group.tabs:
                raise ValueError("목차 묶음에는 탭이 하나 이상 있어야 합니다.")
            for tab_name in group.tabs:
                key = tab_name.casefold()
                if key not in known_tabs or key in used_tabs:
                    raise ValueError("목차 묶음의 탭이 없거나 여러 묶음에 중복되어 있습니다.")
                used_tabs.add(key)
        if complete:
            if not self.tabs:
                raise ValueError("캡처할 탭을 하나 이상 등록하세요.")
            if not self.output_dir:
                raise ValueError("저장 폴더를 선택하세요.")


def config_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BloombergAutoCapture" / "config.json"


def save_config(config: Config, path: Path | None = None) -> None:
    config.validate()
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version", 1) == 1:
        data["version"] = 2
    data["tabs"] = [Tab(t["name"], tuple(t["click"]), Rect(**t["region"]), float(t["delay"]),
                        t.get("region_space", "window"), [Rect(**r) for r in t.get("screen_layout", [])])
                    for t in data.get("tabs", [])]
    data["toc_groups"] = [TocGroup(g["name"], list(g["tabs"])) for g in data.get("toc_groups", [])]
    config = Config(**data)
    config.validate()
    return config
