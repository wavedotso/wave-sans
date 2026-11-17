"""Draw the README's images from the font: the wordmark, for light and dark
backgrounds, and a showcase in Wave's three themes.

    .venv/bin/python tools/assets.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" assets

Every letter in them is the font's own outline, shaped with HarfBuzz at a
given weight, optical size and grade. The images follow the font, so run
this again (make assets) after a change to the letters.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

# Wave's themes: background, text and secondary text.
GRAPHITE = ("#28292E", "#F3F3F4", "#B0B1B7")
INK = ("#020812", "#F2F4F6", "#888E96")
PAPER = ("#FFFFFF", "#0D0D0D", "#5C5857")

WIDTH, HEIGHT, PANEL = 1200, 397, 400
WEIGHTS = range(100, 1000, 100)


def number(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


class Setter:
    """Sets lines of text as SVG path data, at a size in pixels."""

    def __init__(self, font_path: Path):
        self.font = TTFont(font_path)
        self.face = hb.Face(font_path.read_bytes())
        self.upem = self.font["head"].unitsPerEm
        self.glyph_sets: Dict[Tuple, object] = {}

    def location(self, size: float, wght: float, grad: float) -> Dict[str, float]:
        return {"wght": wght, "opsz": min(max(size, 14), 32), "GRAD": grad}

    def width(self, text: str, size: float, wght: float = 400, grad: float = 0) -> float:
        return sum(advance for _, advance in self.shape(text, self.location(size, wght, grad))) * size / self.upem

    def shape(self, text: str, location: Dict[str, float]) -> List[Tuple[str, int]]:
        font = hb.Font(self.face)
        font.set_variations(location)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf)
        return [(self.font.getGlyphName(info.codepoint), pos.x_advance)
                for info, pos in zip(buf.glyph_infos, buf.glyph_positions)]

    def draw(self, text: str, x: float, y: float, size: float, wght: float = 400,
             grad: float = 0) -> Tuple[str, Tuple[float, float, float, float]]:
        """Path data for a line whose baseline starts at (x, y), and its bounds."""
        location = self.location(size, wght, grad)
        key = tuple(sorted(location.items()))
        if key not in self.glyph_sets:
            self.glyph_sets[key] = self.font.getGlyphSet(location=location)
        glyphs = self.glyph_sets[key]
        scale = size / self.upem
        path, bounds = SVGPathPen(glyphs, ntos=number), BoundsPen(glyphs)
        cursor = 0.0
        for name, advance in self.shape(text, location):
            transform = (scale, 0, 0, -scale, x + cursor * scale, y)
            glyphs[name].draw(TransformPen(path, transform))
            glyphs[name].draw(TransformPen(bounds, transform))
            cursor += advance
        return path.getCommands(), bounds.bounds


def svg(width: float, height: float, label: str, body: List[str]) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {number(width)} {number(height)}" '
        f'role="img" aria-label="{label}">',
        *body,
        "</svg>",
        "",
    ])


def wordmark(setter: Setter, color: str) -> str:
    d, (x0, y0, x1, y1) = setter.draw("Wave Sans", 0, 0, 120, wght=600)
    pad = 4
    return svg(x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, "Wave Sans", [
        f'<path transform="translate({number(pad - x0)} {number(pad - y0)})" fill="{color}" d="{d}"/>',
    ])


def centered(setter: Setter, runs: List[Tuple[str, float]], left: float, baseline: float, size: float,
             gap: float, color: str) -> List[str]:
    """Runs of text, each in its own weight, centered in a panel."""
    widths = [setter.width(text, size, wght) for text, wght in runs]
    x = left + (PANEL - sum(widths) - gap * (len(runs) - 1)) / 2
    paths = []
    for (text, wght), w in zip(runs, widths):
        d, _ = setter.draw(text, x, baseline, size, wght=wght)
        paths.append(f'<path fill="{color}" d="{d}"/>')
        x += w + gap
    return paths


def showcase(setter: Setter) -> str:
    panels = [
        (GRAPHITE, [("I l 1 O 0", 500)], 112, 0, "Unambiguous", "I, l, 1, O and 0, distinct by default"),
        (INK, [("a", w) for w in WEIGHTS], 84, 6, "Variable", "Thin to Black, with optical size and grade"),
        (PAPER, [("Ag Ωλ Жя", 500)], 100, 0, "Global", "Latin, Greek and Cyrillic"),
    ]
    # Rounded, with a hairline frame, so the white panel keeps its edge on a
    # white page.
    body = [
        f'<clipPath id="frame"><rect width="{WIDTH}" height="{HEIGHT}" rx="16"/></clipPath>',
        '<g clip-path="url(#frame)">',
    ]
    for i, ((background, text, secondary), runs, size, gap, title, caption) in enumerate(panels):
        left = i * PANEL
        body.append(f'<rect x="{left}" y="0" width="{PANEL}" height="{HEIGHT}" fill="{background}"/>')
        fit = min(size, size * (PANEL - 80) / (sum(setter.width(t, size, w) for t, w in runs) + gap * (len(runs) - 1)))
        body += centered(setter, runs, left, 210, fit, gap * fit / size, text)
        d, _ = setter.draw(title, left + 40, 339, 19, wght=700)
        body.append(f'<path fill="{text}" d="{d}"/>')
        d, _ = setter.draw(caption, left + 40, 361, 12.5, wght=400)
        body.append(f'<path fill="{secondary}" d="{d}"/>')
    body += ["</g>", f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="15.5" '
                     f'fill="none" stroke="{PAPER[1]}" stroke-opacity="0.12"/>']
    label = ("Wave Sans in Wave's three themes: I, l, 1, O and 0, distinct by default, on Graphite; "
             "the weights from Thin to Black on Ink; Latin, Greek and Cyrillic on Paper")
    return svg(WIDTH, HEIGHT, label, body)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("font", type=Path, help="the variable font (TTF)")
    ap.add_argument("out", type=Path, help="the folder to write the images to")
    args = ap.parse_args(argv)
    setter = Setter(args.font)
    args.out.mkdir(parents=True, exist_ok=True)
    images = {
        "wordmark-light.svg": wordmark(setter, PAPER[1]),
        "wordmark-dark.svg": wordmark(setter, GRAPHITE[1]),
        "showcase.svg": showcase(setter),
    }
    for name, content in images.items():
        (args.out / name).write_text(content)
        print(f"{args.out / name}: {len(content.encode()) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
