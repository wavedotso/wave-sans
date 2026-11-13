"""Compare our build with the official Inter release, glyph by glyph.

    .venv/bin/python tools/verify.py "build/fonts/var/WaveSans[opsz,wght].ttf" \
        upstream/inter-release/extracted/InterVariable.ttf

Checks that no family name or vendor ID is still Inter's, then glyph set, code
points, axes, named instances and OpenType features. At several design-space
locations it then compares advance widths and every outline point, and shapes
every pair of characters with HarfBuzz to compare spacing: the glyphs each
pair becomes and their positions, which covers kerning. Prints each
difference; exits 1 if any is not listed in KNOWN.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Tuple

import uharfbuzz as hb
import unicodedata2 as unicodedata
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
# Inter's private-use code points for alternate marks: our toolchain's mark
# feature attaches them to the letter before them; the v4.1 release leaves
# them unattached. Only text that types these code points is affected.
PRIVATE_USE_MARKS = (0xE2BF, 0xE2C0, 0xE2C1, 0xEE07, 0xEE90, 0xEE9B, 0xEE9C, 0xF6C3)
KNOWN.update({("attach", cp): "private-use mark attached by ufo2ft" for cp in PRIVATE_USE_MARKS})


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


def spaced_chars(cmap: Dict[int, str]) -> str:
    """Characters whose spacing is compared: letters, numbers, punctuation,
    symbols, spaces and private-use alternates. Combining marks are left out:
    they attach to the character before them instead of being spaced."""
    def spaced(cp: int) -> bool:
        category = unicodedata.category(chr(cp))
        return category[0] in "LNPSZ" or category == "Co"
    return "".join(chr(cp) for cp in sorted(cmap) if spaced(cp))


def shape(font: hb.Font, text: str) -> List[Tuple[int, int, int, int, int]]:
    """(cluster, glyph ID, x advance, x offset, y offset) per glyph; the
    cluster is the index of the character the glyph comes from."""
    buf = hb.Buffer()
    buf.add_codepoints([ord(c) for c in text])
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    return [(i.cluster, i.codepoint, p.x_advance, p.x_offset, p.y_offset)
            for i, p in zip(buf.glyph_infos, buf.glyph_positions)]


def glyph_map(ours: TTFont, ref: TTFont) -> List[int]:
    """Our glyph ID for each of Inter's glyphs: the glyph of the same code
    point, or of the same name when unencoded. Names alone do not match: the
    toolchains name some encoded glyphs differently (uni0180 against bbar)."""
    ours_ids = {name: i for i, name in enumerate(ours.getGlyphOrder())}
    ours_cmap = ours.getBestCmap()
    ref_cps = {name: cp for cp, name in ref.getBestCmap().items()}

    def ours_for(name: str) -> int:
        cp = ref_cps.get(name)
        if cp is not None and cp in ours_cmap:
            return ours_ids[ours_cmap[cp]]
        return ours_ids.get(name, -1)
    return [ours_for(name) for name in ref.getGlyphOrder()]


def spacing(job: Tuple[str, str, Dict[str, float], str]) -> List[str]:
    """Pairs that shape differently at one location, with default features.

    Each run sets one character between all the others (x y1 x y2 ...), so
    together the runs cover every ordered pair. HarfBuzz puts a pair's kerning
    in the advance of its first glyph, so an advance difference is reported
    as the pair its character starts; an offset difference (a mark placed on
    the glyph before it) as the pair its character ends.
    """
    ours_path, ref_path, loc, chars = job
    fonts = []
    for path in (ours_path, ref_path):
        font = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
        font.set_variations(loc)
        fonts.append(font)
    ours, ref = fonts
    to_ours = glyph_map(TTFont(ours_path), TTFont(ref_path))
    pairs: Dict[str, str] = {}
    for x in chars:
        text = "".join(x + y for y in chars)
        a = shape(ours, text)
        b = [(cluster, to_ours[g], *rest) for cluster, g, *rest in shape(ref, text)]
        if a == b:
            continue
        for ga, gb in zip(a, b):
            if ga == gb:
                continue
            at = ga[0]
            if ga[:3] == gb[:3]:  # same glyph and advance: only its offsets differ
                if ("attach", ord(text[at])) in KNOWN:
                    continue
                pair = text[max(at - 1, 0):at + 1]
            else:
                pair = text[at:at + 2]
            why = "different glyphs" if ga[:2] != gb[:2] else f"ours {ga[2:]} vs Inter {gb[2:]}"
            pairs.setdefault(pair, why)
            if ga[0] != gb[0]:
                break  # the runs are out of step from here on
        if len(a) != len(b):
            pairs.setdefault(f"{x} + any", "different number of glyphs")
    shown = [f"{loc} spacing {pair!r}: {why}" for pair, why in sorted(pairs.items())[:12]]
    if len(pairs) > len(shown):
        shown.append(f"{loc} spacing: {len(pairs) - len(shown)} more pairs differ")
    return shown


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

    chars = spaced_chars(ref.getBestCmap())
    with ProcessPoolExecutor() as pool:
        # Spacing runs in other processes while the outlines are compared here.
        spaced = [pool.submit(spacing, (ours_path, ref_path, loc, chars)) for loc in LOCATIONS]
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
        for job in spaced:
            problems.extend(job.result())
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
