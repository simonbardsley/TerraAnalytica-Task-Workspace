"""Display classes, nearest-profile selection and off-screen correction (M3, spec s15).

Pure Python (no Qt) so it is unit-testable. Coordinates are Qt logical pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .schemas import DisplayClass, WorkspaceProfile

COMPACT_MAX_WIDTH = 1500
ULTRAWIDE_MIN_ASPECT = 1.95


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersection(self, other: Rect) -> Rect | None:
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2, y2 = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(x1, y1, x2 - x1, y2 - y1) if x2 > x1 and y2 > y1 else None

    def to_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    @classmethod
    def from_list(cls, v: Sequence[int]) -> Rect:
        return cls(int(v[0]), int(v[1]), int(v[2]), int(v[3]))


def classify_display(screens: Sequence[Rect]) -> DisplayClass:
    if len(screens) >= 3:
        return DisplayClass.MULTI_MONITOR
    if len(screens) == 2:
        return DisplayClass.DUAL_MONITOR
    if not screens:
        return DisplayClass.SINGLE_STANDARD
    s = screens[0]
    if s.h and s.w / s.h >= ULTRAWIDE_MIN_ASPECT:
        return DisplayClass.SINGLE_ULTRAWIDE
    return DisplayClass.SINGLE_COMPACT if s.w < COMPACT_MAX_WIDTH else DisplayClass.SINGLE_STANDARD


_D = DisplayClass
_FALLBACK = {
    _D.SINGLE_COMPACT: [_D.SINGLE_COMPACT, _D.SINGLE_STANDARD, _D.SINGLE_ULTRAWIDE, _D.DUAL_MONITOR, _D.MULTI_MONITOR],
    _D.SINGLE_STANDARD: [_D.SINGLE_STANDARD, _D.SINGLE_COMPACT, _D.SINGLE_ULTRAWIDE, _D.DUAL_MONITOR, _D.MULTI_MONITOR],
    _D.SINGLE_ULTRAWIDE: [
        _D.SINGLE_ULTRAWIDE, _D.SINGLE_STANDARD, _D.SINGLE_COMPACT, _D.DUAL_MONITOR, _D.MULTI_MONITOR,
    ],
    _D.DUAL_MONITOR: [_D.DUAL_MONITOR, _D.MULTI_MONITOR, _D.SINGLE_ULTRAWIDE, _D.SINGLE_STANDARD, _D.SINGLE_COMPACT],
    _D.MULTI_MONITOR: [_D.MULTI_MONITOR, _D.DUAL_MONITOR, _D.SINGLE_ULTRAWIDE, _D.SINGLE_STANDARD, _D.SINGLE_COMPACT],
}


def nearest_profile(profiles: Sequence[WorkspaceProfile], current: DisplayClass) -> WorkspaceProfile | None:
    """Exact class match, else the nearest compatible class (never mutates profiles)."""
    for wanted in _FALLBACK[current]:
        for p in profiles:
            if p.display_class == wanted and p.shell:
                return p
    return None


def is_adequately_visible(rect: Rect, screens: Sequence[Rect], min_w: int = 100, min_h: int = 50) -> bool:
    for s in screens:
        inter = rect.intersection(s)
        if inter and inter.w >= min(min_w, rect.w) and inter.h >= min(min_h, rect.h):
            return True
    return False


def clamp_rect(rect: Rect, screens: Sequence[Rect]) -> Rect:
    """Return ``rect`` moved/shrunk to sit fully inside the best-overlapping screen."""
    if not screens:
        return rect
    best = max(screens, key=lambda s: (lambda i: i.w * i.h if i else -1)(rect.intersection(s)))
    w, h = min(rect.w, best.w), min(rect.h, best.h)
    x = min(max(rect.x, best.x), best.right - w)
    y = min(max(rect.y, best.y), best.bottom - h)
    return Rect(x, y, w, h)
