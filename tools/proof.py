"""Comparison sheets for reviews: the same lines set in several font setups.

    .venv/bin/python tools/proof.py build/proofs/name.png \
        --column "Inter"     upstream/inter-release/extracted/InterVariable.ttf \
        --column "Wave Sans" "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" \
        --column "Dark mode" "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" dark,GRAD=-25 \
        --line 110 "Il1 O0o" --line 15 "a feed post…"

Each column is a label, a font file and optional settings, comma separated:
OpenType features (ss04), axis values (GRAD=-25), and dark for light text on
a dark background. Each line is a pixel size and the text. Text is shaped by
HarfBuzz and filled by Skia, unhinted, at 2x, so it matches what a browser
shows on a high-density screen. Optical size follows the pixel size, as CSS
font-optical-sizing does.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import skia
import uharfbuzz as hb

INK = skia.Color(17, 20, 26)
PAPER = skia.Color(250, 249, 246)
MUTED = skia.Color(118, 124, 134)
RULE = skia.Color(222, 225, 230)
DARK_INK = skia.Color(232, 234, 238)
DARK_PAPER = skia.Color(22, 24, 29)
DARK_MUTED = skia.Color(140, 146, 156)


@dataclass(frozen=True)
class Column:
    label: str
    font: Path
    features: Tuple[str, ...]
    axes: Tuple[Tuple[str, float], ...] = ()
    dark: bool = False

    @classmethod
    def parse(cls, label: str, font: str, settings: str = "") -> "Column":
        items = [s for s in settings.split(",") if s]
        axes = tuple((s.split("=")[0], float(s.split("=")[1])) for s in items if "=" in s)
        features = tuple(s for s in items if "=" not in s and s != "dark")
        return cls(label, Path(font), features, axes, "dark" in items)


class _Pen:
    """HarfBuzz draw callbacks → skia.Path in pixels (y down)."""

    def __init__(self, path: skia.Path, ox: float, oy: float, k: float):
        self.path, self.ox, self.oy, self.k = path, ox, oy, k

    def _p(self, x: float, y: float) -> Tuple[float, float]:
        return self.ox + x * self.k, self.oy - y * self.k

    def moveTo(self, p):
        self.path.moveTo(*self._p(*p))

    def lineTo(self, p):
        self.path.lineTo(*self._p(*p))

    def curveTo(self, a, b, c):
        self.path.cubicTo(*self._p(*a), *self._p(*b), *self._p(*c))

    def qCurveTo(self, *pts):
        offs, end = pts[:-1], pts[-1]
        for i, off in enumerate(offs):
            nxt = end if i == len(offs) - 1 else ((off[0] + offs[i + 1][0]) / 2, (off[1] + offs[i + 1][1]) / 2)
            self.path.quadTo(*self._p(*off), *self._p(*nxt))

    def closePath(self):
        self.path.close()

    def endPath(self):
        pass


class Setter:
    def __init__(self, column: Column):
        self.face = hb.Face(hb.Blob.from_file_path(str(column.font)))
        self.upem = self.face.upem
        self.features: Dict[str, bool] = {f: True for f in column.features}
        axes = {a.tag: (a.min_value, a.max_value) for a in self.face.axis_infos} if self.face.axis_infos else {}
        self.axes = axes
        self.settings = {tag: value for tag, value in column.axes if tag in axes}

    def path(self, text: str, px: float, x: float, baseline: float, wght: float = 400) -> Tuple[skia.Path, float]:
        font = hb.Font(self.face)
        variations = {}
        if "wght" in self.axes:
            variations["wght"] = wght
        if "opsz" in self.axes:
            lo, hi = self.axes["opsz"]
            variations["opsz"] = min(max(px, lo), hi)
        variations.update(self.settings)
        if variations:
            font.set_variations(variations)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf, self.features)
        k = px / self.upem
        path, cur = skia.Path(), 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            font.draw_glyph_with_pen(info.codepoint, _Pen(path, x + (cur + pos.x_offset) * k, baseline - pos.y_offset * k, k))
            cur += pos.x_advance
        return path, cur * k


def wrap(setter: Setter, text: str, px: float, width: float, wght: float) -> List[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and setter.path(trial, px, 0, 0, wght)[1] > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def render(out: Path, columns: List[Column], lines: List[Tuple[float, str, float]], col_width: float = 520, scale: float = 2.0) -> None:
    setters = [Setter(c) for c in columns]
    pad, gap, head = 28.0, 36.0, 48.0
    # Lay out every column's lines first, so all columns share one height per line.
    blocks = []
    for px, text, wght in lines:
        wrapped = [wrap(s, text, px, col_width, wght) for s in setters]
        rows = max(len(w) for w in wrapped)
        blocks.append((px, wght, wrapped, rows * px * 1.42 + px * 0.5))
    label_w = 84.0  # right gutter for size labels
    width = pad * 2 + col_width * len(columns) + gap * (len(columns) - 1) + label_w
    height = pad + head + sum(b[3] for b in blocks) + pad
    surface = skia.Surface(int(width * scale), int(height * scale))
    cv = surface.getCanvas()
    cv.clear(PAPER)
    cv.scale(scale, scale)
    # Labels are set in the first column's font: no outside typeface involved.
    label_face = skia.Typeface.MakeFromFile(str(columns[0].font))
    label_font = skia.Font(label_face, 14)
    muted, rule = skia.Paint(AntiAlias=True, Color=MUTED), skia.Paint(Color=RULE, StrokeWidth=1)
    inks = [skia.Paint(AntiAlias=True, Color=DARK_INK if c.dark else INK) for c in columns]
    for i, c in enumerate(columns):
        x = pad + i * (col_width + gap)
        if c.dark:
            left = 0 if i == 0 else x - gap / 2
            cv.drawRect(skia.Rect(left, 0, x + col_width + gap / 2, height), skia.Paint(Color=DARK_PAPER))
        label = skia.Paint(AntiAlias=True, Color=DARK_MUTED) if c.dark else muted
        cv.drawString(c.label, x, pad + 16, label_font, label)
        if i and not (c.dark or columns[i - 1].dark):
            cv.drawLine(x - gap / 2, pad, x - gap / 2, height - pad, rule)
    y = pad + head
    for px, wght, wrapped, h in blocks:
        for i, (s, ws) in enumerate(zip(setters, wrapped)):
            x = pad + i * (col_width + gap)
            for j, ln in enumerate(ws):
                p, _ = s.path(ln, px, x, y + px * 1.05 + j * px * 1.42, wght)
                cv.drawPath(p, inks[i])
        cv.drawString(f"{px:g}px · {wght:g}", width - pad - label_w + 26, y + 12, skia.Font(label_face, 10), muted)
        y += h
    out.parent.mkdir(parents=True, exist_ok=True)
    surface.makeImageSnapshot().save(str(out), skia.kPNG)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--column", nargs="+", action="append", required=True, metavar=("LABEL", "FONT"),
                    help="label font [settings: features, TAG=value axes, dark]")
    ap.add_argument("--line", nargs="+", action="append", required=True, metavar=("PX", "TEXT"), help="px text [wght]")
    ap.add_argument("--width", type=float, default=520)
    a = ap.parse_args(argv)
    columns = [Column.parse(*c[:3]) for c in a.column]
    lines = [(float(l[0]), l[1], float(l[2]) if len(l) > 2 else 400.0) for l in a.line]
    render(a.out, columns, lines, a.width)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
