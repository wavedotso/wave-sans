"""Measure how alike confusable characters look at small sizes, Wave Sans
against Inter.

    .venv/bin/python tools/legibility.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" \
        upstream/inter-release/extracted/InterVariable.ttf [--image build/proofs/legibility.png]

Usernames mix letters and figures, so I and l, O and 0, or rn and m must not
look alike in a dense interface. Each pair is set at 11, 12, 13, 14 and 16 px
on a 1x and a 2x screen, roughly as browsers draw unhinted text (shaped with
HarfBuzz, filled by Skia with antialiasing, the baseline on a whole pixel,
optical size following the pixel size), and the two strings are compared
pixel by pixel. The score is the share of their ink that differs, at the
horizontal offset where they look most alike (searched in steps of 1/16 px,
up to 3 px either way): 0 means they look identical, 1 that they share no
ink. Higher is easier to tell apart.

A score compares the same pair between the two fonts. It is not a scale
across pairs: a width difference scores high however recognizable the
letters are, so pairs readers never confuse can score lower than O and 0.
The last pairs show what the serifed I and tailed l cost: they come a little
closer to T, t and L.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import skia
import uharfbuzz as hb

from proof import Column, Setter

PAIRS: List[Tuple[str, str]] = [
    ("I", "l"), ("I", "1"), ("l", "1"),
    ("O", "0"), ("o", "0"),
    ("rn", "m"), ("cl", "d"), ("vv", "w"),
    ("I", "T"), ("l", "t"), ("l", "L"),
]
SIZES = (11, 12, 13, 14, 16)
SCALES = (1, 2)
SHIFTS = [i / 16 for i in range(-48, 49)]
IMAGE_PX = 12


def coverage(setter: Setter, text: str, px: float, scale: int, x: float, size: Tuple[float, float],
             wght: float) -> np.ndarray:
    """The text's ink, 0 to 1 per device pixel, drawn at x on a canvas of
    size (CSS px), with the baseline on the device pixel nearest 1.15 em."""
    width, height = size
    surface = skia.Surface(math.ceil(width * scale), math.ceil(height * scale))
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    canvas.scale(scale, scale)
    path, _ = setter.path(text, px, x, round(px * 1.15 * scale) / scale, wght)
    canvas.drawPath(path, skia.Paint(AntiAlias=True, Color=skia.ColorBLACK))
    return surface.makeImageSnapshot().toarray()[..., 3] / 255.0


def canvas_size(setter: Setter, a: str, b: str, px: float, wght: float) -> Tuple[float, float]:
    """Room for both strings, centered, at every shift."""
    advance = max(setter.path(s, px, 0, 0, wght)[1] for s in (a, b))
    return advance + 2 * (max(SHIFTS) + 1), px * 1.5


def score(setter: Setter, a: str, b: str, px: float, scale: int, wght: float) -> float:
    """The share of ink that differs between a and b, both centered, at the
    shift of b where they look most alike."""
    size = canvas_size(setter, a, b, px, wght)
    adv_a, adv_b = (setter.path(s, px, 0, 0, wght)[1] for s in (a, b))
    ink_a = coverage(setter, a, px, scale, (size[0] - adv_a) / 2, size, wght)
    best = 1.0
    for dx in SHIFTS:
        ink_b = coverage(setter, b, px, scale, (size[0] - adv_b) / 2 + dx, size, wght)
        best = min(best, float(np.abs(ink_a - ink_b).sum() / (ink_a.sum() + ink_b.sum())))
    return best


def measure(font: Path, wght: float) -> Dict[Tuple[str, str, int], List[float]]:
    """(a, b, scale) -> scores at each size. Stops if the font lacks a
    character or draws one without ink."""
    setter = Setter(Column.parse("", str(font)))
    cmap = hb.Font(setter.face)
    px = SIZES[0]
    for char in sorted({c for pair in PAIRS for s in pair for c in s}):
        if cmap.get_nominal_glyph(ord(char)) is None or not coverage(setter, char, px, 1, 2, (px * 2, px * 1.5),
                                                                     wght).any():
            raise SystemExit(f"{font}: no glyph with ink for {char!r}")
    return {(a, b, scale): [score(setter, a, b, px, scale, wght) for px in SIZES]
            for a, b in PAIRS for scale in SCALES}


def sheet(out: Path, fonts: List[Tuple[str, Path]], scores: List[Dict], wght: float, zoom: int = 8) -> None:
    """Each pair at IMAGE_PX on a 1x screen, every pixel shown zoom times
    larger, with its score at that size."""
    setters = [Setter(Column.parse(label, str(font))) for label, font in fonts]
    cells = []
    for a, b in PAIRS:
        row = []
        for setter in setters:
            width = max(setter.path(s, IMAGE_PX, 0, 0, wght)[1] for s in (a, b)) + 4
            inks = [coverage(setter, s, IMAGE_PX, 1, (width - setter.path(s, IMAGE_PX, 0, 0, wght)[1]) / 2,
                             (width, IMAGE_PX * 1.5), wght) for s in (a, b)]
            row.append(np.concatenate([inks[0], np.zeros((inks[0].shape[0], 3)), inks[1]], axis=1))
        cells.append(row)
    pad, gap, label_w, head = 24, 40, 120, 64
    cell_w = max(c.shape[1] for row in cells for c in row) * zoom
    cell_h = max(c.shape[0] for row in cells for c in row) * zoom
    row_h = cell_h + 30
    width = pad * 2 + label_w + len(fonts) * cell_w + (len(fonts) - 1) * gap
    height = pad * 2 + head + len(PAIRS) * row_h
    surface = skia.Surface(width, height)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color(250, 249, 246))
    face = skia.Typeface.MakeFromFile(str(fonts[-1][1]))
    title, small = skia.Font(face, 17), skia.Font(face, 14)
    ink = skia.Paint(AntiAlias=True, Color=skia.Color(17, 20, 26))
    muted = skia.Paint(AntiAlias=True, Color=skia.Color(118, 124, 134))
    canvas.drawString(f"Confusable pairs at {IMAGE_PX} px on a 1x screen, weight {wght:g}: each pixel "
                      f"shown {zoom} times larger, with the pair's score at that size", pad, pad + 16, title, ink)
    for i, (label, _) in enumerate(fonts):
        canvas.drawString(label, pad + label_w + i * (cell_w + gap), pad + head - 12, small, muted)
    for r, ((a, b), row) in enumerate(zip(PAIRS, cells)):
        y = pad + head + r * row_h
        canvas.drawString(f"{a}  {b}", pad, y + cell_h / 2 + 6, small, ink)
        for i, cell in enumerate(row):
            pixels = np.repeat(np.repeat(255 - (cell * 255).astype(np.uint8), zoom, 0), zoom, 1)
            image = skia.Image.fromarray(np.ascontiguousarray(pixels), colorType=skia.kGray_8_ColorType)
            x = pad + label_w + i * (cell_w + gap)
            canvas.drawImage(image, x, y)
            canvas.drawString(f"{scores[i][(a, b, 1)][SIZES.index(IMAGE_PX)]:.2f}", x, y + cell_h + 18, small, muted)
    out.parent.mkdir(parents=True, exist_ok=True)
    surface.makeImageSnapshot().save(str(out), skia.kPNG)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ours", type=Path)
    ap.add_argument("inter", type=Path)
    ap.add_argument("--wght", type=float, default=400)
    ap.add_argument("--image", type=Path, help=f"also draw the pairs at {IMAGE_PX} px, pixel by pixel")
    args = ap.parse_args(argv)
    theirs, ours = measure(args.inter, args.wght), measure(args.ours, args.wght)
    print(f"Confusable pairs at weight {args.wght:g}: share of ink that differs (0 identical, 1 nothing "
          f"in common), mean of {', '.join(map(str, SIZES))} px. Compare a pair across fonts, not pairs.")
    print(f"{'pair':8} {'Inter 1x':>9} {'2x':>5} {'Wave Sans 1x':>13} {'2x':>5}   change 1x, 2x")
    for a, b in PAIRS:
        t1, t2 = (sum(theirs[(a, b, s)]) / len(SIZES) for s in SCALES)
        o1, o2 = (sum(ours[(a, b, s)]) / len(SIZES) for s in SCALES)
        change = "same" if max(abs(o1 - t1), abs(o2 - t2)) < 0.005 else f"{o1 - t1:+.2f}, {o2 - t2:+.2f}"
        print(f"{a + ' ' + b:8} {t1:9.2f} {t2:5.2f} {o1:13.2f} {o2:5.2f}   {change}")
    if args.image:
        sheet(args.image, [("Inter", args.inter), ("Wave Sans", args.ours)], [theirs, ours], args.wght)
        print(f"wrote {args.image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
