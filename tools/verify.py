"""Compare our build with the official Inter release, glyph by glyph.

    .venv/bin/python tools/verify.py "build/fonts/var/WaveSans[opsz,wght].ttf" \
        upstream/inter-release/extracted/InterVariable.ttf

Checks that no family name or vendor ID is still Inter's, then glyph set, code
points, axes, named instances and OpenType features, then advance widths and
every outline point at several design-space locations. Prints each difference;
exits 1 if any is not listed in KNOWN.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Tuple

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

LOCATIONS: List[Dict[str, float]] = [
    {"wght": 100, "opsz": 14},
    {"wght": 400, "opsz": 14},
    {"wght": 700, "opsz": 14},
    {"wght": 900, "opsz": 14},
    {"wght": 400, "opsz": 32},
    {"wght": 900, "opsz": 32},
]

# Differences we understand and accept, with the reason.
KNOWN = {
    # Combining dot below: our toolchain zeroes mark advances (correct for a
    # combining mark); the v4.1 release ships 495.
    ("advance", 0x0323): "combining mark advance zeroed by ufo2ft",
}


# Name records that present the family to users: family, unique, full and
# PostScript names, and the variations prefix. The original project reserves
# "Inter", so none of them may carry it. The copyright notice (ID 0) keeps
# Inter's line, as the license requires.
PRESENTED_NAME_IDS = {1, 3, 4, 6, 16, 17, 18, 21, 22, 25}


def names(font: TTFont) -> List[str]:
    ids = PRESENTED_NAME_IDS | {i.postscriptNameID for i in font["fvar"].instances}
    problems = [f"name ID {r.nameID} still says Inter: {r.toUnicode()!r}"
                for r in font["name"].names if r.nameID in ids and "Inter" in r.toUnicode()]
    if font["OS/2"].achVendID == "RSMS":
        problems.append("OS/2 vendor ID is still Inter's (RSMS)")
    return problems


def features(font: TTFont, table: str) -> List[str]:
    return sorted({r.FeatureTag for r in font[table].table.FeatureList.FeatureRecord})


def outline(glyph_set, name: str) -> List[Tuple[float, float]]:
    pen = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(pen)
    return [p for _, args in pen.value for p in args]


def compare(ours_path: str, ref_path: str) -> List[str]:
    ours, ref = TTFont(ours_path), TTFont(ref_path)
    problems: List[str] = names(ours)

    def check(label: str, a, b) -> None:
        if a != b:
            problems.append(f"{label}: ours {a!r} vs Inter {b!r}")

    check("glyph count", len(ours.getGlyphOrder()), len(ref.getGlyphOrder()))
    check("code points", sorted(ours.getBestCmap()), sorted(ref.getBestCmap()))
    check("axes", [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in ours["fvar"].axes],
          [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in ref["fvar"].axes])
    check("named instances", len(ours["fvar"].instances), len(ref["fvar"].instances))
    for table in ("GSUB", "GPOS"):
        check(f"{table} features", features(ours, table), features(ref, table))

    for loc in LOCATIONS:
        a = instantiateVariableFont(TTFont(ours_path), loc)
        b = instantiateVariableFont(TTFont(ref_path), loc)
        ca, cb = a.getBestCmap(), b.getBestCmap()
        gsa, gsb = a.getGlyphSet(), b.getGlyphSet()
        for cp, name_b in cb.items():
            name_a = ca.get(cp)
            if name_a is None:
                continue
            adv_a, adv_b = a["hmtx"][name_a][0], b["hmtx"][name_b][0]
            if adv_a != adv_b and ("advance", cp) not in KNOWN:
                problems.append(f"{loc} U+{cp:04X} advance: ours {adv_a} vs Inter {adv_b}")
            pa, pb = outline(gsa, name_a), outline(gsb, name_b)
            if len(pa) != len(pb):
                problems.append(f"{loc} U+{cp:04X} outline: {len(pa)} vs {len(pb)} points")
                continue
            drift = max((abs(x1 - x2) + abs(y1 - y2) for (x1, y1), (x2, y2) in zip(pa, pb)), default=0)
            if drift > 1:
                problems.append(f"{loc} U+{cp:04X} outline drift {drift:.1f} units")
    return problems


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ours")
    ap.add_argument("inter")
    args = ap.parse_args(argv)
    problems = compare(args.ours, args.inter)
    for p in problems:
        print(p)
    for (kind, cp), why in KNOWN.items():
        print(f"known: U+{cp:04X} {kind} ({why})")
    print("identical to Inter except known differences" if not problems else f"{len(problems)} unexplained differences")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
