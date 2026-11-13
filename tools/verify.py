"""Compare Wave Sans with the official Inter release, glyph by glyph.

    .venv/bin/python tools/verify.py "build/fonts/var/WaveSans[opsz,wght].ttf" \
        upstream/inter-release/extracted/InterVariable.ttf

Wave Sans is Inter with the changes described below (the default I and l,
and KNOWN), and this checks that nothing else differs. It checks that no
family name or vendor ID is still Inter's, then the glyph set, code points,
axes, named instances and OpenType features. At several design-space
locations it then compares each character's advance width and outline with
Inter's glyph for it, and shapes every pair of characters with HarfBuzz,
comparing the shapes each pair becomes and their positions, which covers
kerning. Prints each difference; exits 1 if any is unexplained.
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
    ("feature", "cv05"): "removed: its tailed l is the default",
    ("feature", "cv08"): "removed: its serifed I is the default",
    ("feature", "ss09"): "added: Inter's plain I and l",
}
# Inter's private-use code points for alternate marks: our toolchain's mark
# feature attaches them to the letter before them; the v4.1 release leaves
# them unattached. Only text that types these code points is affected.
PRIVATE_USE_MARKS = (0xE2BF, 0xE2C0, 0xE2C1, 0xEE07, 0xEE90, 0xEE9B, 0xEE9C, 0xF6C3)
KNOWN.update({("attach", cp): "private-use mark attached by ufo2ft" for cp in PRIVATE_USE_MARKS})

# The serifed I and tailed l are the defaults. Our glyph for a code point is
# Inter's glyph for its partner: the pairs Inter's ss04 swaps (without the
# alternate German sharp s), and their ss03 and ss07 variants. The Greek
# capital iotas, which Inter's set leaves plain, take the serifed shapes of
# these twins: Cyrillic I, Greek iota with oxia, Latin I with dieresis.
# Feature ss09 gives back Inter's plain forms, which adds three glyphs: the
# plain Greek iotas, defaults in Inter.
GREEK_IOTAS = {0x0399: 0x0406, 0x038A: 0x1FDB, 0x03AA: 0x00CF}


def single_subs(font: TTFont, tag: str) -> Dict[str, str]:
    """A font's single substitutions under one feature."""
    gsub = font["GSUB"].table
    subs: Dict[str, str] = {}
    for record in gsub.FeatureList.FeatureRecord:
        if record.FeatureTag == tag:
            for index in record.Feature.LookupListIndex:
                lookup = gsub.LookupList.Lookup[index]
                for table in lookup.SubTable:
                    table = table.ExtSubTable if lookup.LookupType == 7 else table
                    subs.update(getattr(table, "mapping", {}))
    return subs


def default_swap(ref: TTFont) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Inter's code point for the glyph each of ours shows, split into our
    defaults and our private-use alternates (the plain forms)."""
    cps = {name: cp for cp, name in ref.getBestCmap().items()}
    base = [(d, a) for d, a in single_subs(ref, "ss04").items() if d != "germandbls"]
    pairs = list(base)
    for tag in ("ss03", "ss07"):
        variant = single_subs(ref, tag)
        pairs += [(variant[d], variant[a]) for d, a in base if d in variant and a in variant]
    encoded = [(cps[d], cps[a]) for d, a in pairs if d in cps and a in cps]
    defaults = dict(encoded)
    defaults.update({cp: defaults[twin] for cp, twin in GREEK_IOTAS.items()})
    return defaults, {a: d for d, a in encoded}


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


class OutlineKey:
    """Pen that records a glyph's outline, rounded to font units. Glyphs of
    the same shape get the same key, whatever their names or IDs: the two
    fonts name some glyphs differently, and swap the I and l alternates."""

    def __init__(self) -> None:
        self.ops: List[Tuple] = []

    def moveTo(self, p):
        self.ops.append(("M", *map(round, p)))

    def lineTo(self, p):
        self.ops.append(("L", *map(round, p)))

    def curveTo(self, *points):
        self.ops.append(("C", *(round(v) for p in points for v in p)))

    def qCurveTo(self, *points):
        self.ops.append(("Q", *(round(v) for p in points for v in p)))

    def closePath(self):
        self.ops.append(("Z",))

    def endPath(self):
        self.ops.append(("E",))


def outline_keys(font: hb.Font) -> List[int]:
    keys = []
    for gid in range(font.face.glyph_count):
        pen = OutlineKey()
        font.draw_glyph_with_pen(gid, pen)
        keys.append(hash(tuple(pen.ops)))
    return keys


def shape(font: hb.Font, keys: List[int], text: str, feats: Dict[str, bool]) -> List[Tuple[int, ...]]:
    """(cluster, outline key, x advance, x offset, y offset) per glyph; the
    cluster is the index of the character the glyph comes from."""
    buf = hb.Buffer()
    buf.add_codepoints([ord(c) for c in text])
    buf.guess_segment_properties()
    hb.shape(font, buf, feats)
    return [(i.cluster, keys[i.codepoint], p.x_advance, p.x_offset, p.y_offset)
            for i, p in zip(buf.glyph_infos, buf.glyph_positions)]


Run = Tuple[str, Dict[str, bool], Dict[str, bool], str, Dict[int, int]]


def spacing_runs(ref: TTFont) -> List[Run]:
    """How Inter shows what Wave Sans shows: (label, our features, Inter's
    features, characters, Inter's stand-in characters). Inter reaches its
    alternates through features that run after its contextual forms, so it
    sets the same case-sensitive punctuation around them as we do around our
    defaults."""
    defaults, alternates = default_swap(ref)
    chars = spaced_chars(ref.getBestCmap())
    standard = "".join(c for c in chars if unicodedata.category(c) != "Co")
    return [
        # Our default I and l are Inter's cv05 and cv08 forms.
        ("default", {}, {"cv05": True, "cv08": True}, standard, GREEK_IOTAS),
        # ss09 gives back Inter's own defaults.
        ("ss09", {"ss09": True}, {}, standard, {}),
        # Square dots on our I and l are Inter's ss04 and ss07 forms. The
        # German sharp s, which ss04 also changes, and the Greek iotas, which
        # have no ss07 forms, are left out.
        ("ss07", {"ss07": True}, {"ss04": True, "ss07": True},
         "".join(c for c in standard if c != "ß" and ord(c) not in GREEK_IOTAS), {}),
        # Everything the swap leaves alone, private-use alternates included.
        # Private-use I and l alternates are compared glyph by glyph only:
        # Inter's contextual forms treat its own as letters, ours as symbols.
        ("unchanged", {}, {}, "".join(c for c in chars if ord(c) not in defaults
                                       and ord(c) not in alternates), {}),
    ]


def spacing(job: Tuple[str, str, Dict[str, float], Run]) -> List[str]:
    """Pairs that shape differently at one location in one run.

    Each pass sets one character between all the others (x y1 x y2 ...), so
    together the passes cover every ordered pair. HarfBuzz puts a pair's
    kerning in the advance of its first glyph, so an advance difference is
    reported as the pair its character starts; an offset difference (a mark
    placed on the glyph before it) as the pair it ends.
    """
    ours_path, ref_path, loc, (name, ours_feats, ref_feats, chars, stand_ins) = job
    fonts = []
    for path in (ours_path, ref_path):
        font = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
        font.set_variations(loc)
        fonts.append((font, outline_keys(font)))
    (ours, ours_keys), (ref, ref_keys) = fonts
    to_ref = {cp: chr(partner) for cp, partner in stand_ins.items()}
    label = f"{loc} {name} spacing"
    pairs: Dict[str, str] = {}
    for x in chars:
        text = "".join(x + y for y in chars)
        a = shape(ours, ours_keys, text, ours_feats)
        b = shape(ref, ref_keys, text.translate(to_ref), ref_feats)
        if a == b:
            continue
        for ga, gb in zip(a, b):
            if ga == gb:
                continue
            at = ga[0]
            if ga[:3] == gb[:3]:  # same shape and advance: only its offsets differ
                if ("attach", ord(text[at])) in KNOWN:
                    continue
                pair = text[max(at - 1, 0):at + 1]
            else:
                pair = text[at:at + 2]
            why = "different shapes" if ga[:2] != gb[:2] else f"ours {ga[2:]} vs Inter {gb[2:]}"
            pairs.setdefault(pair, why)
            if ga[0] != gb[0]:
                break  # the runs are out of step from here on
        if len(a) != len(b):
            pairs.setdefault(f"{x} + any", "different number of glyphs")
    shown = [f"{label} {pair!r}: {why}" for pair, why in sorted(pairs.items())[:12]]
    if len(pairs) > len(shown):
        shown.append(f"{label}: {len(pairs) - len(shown)} more pairs differ")
    return shown


def compare(ours_path: str, ref_path: str) -> List[str]:
    ours, ref = TTFont(ours_path), TTFont(ref_path)
    problems: List[str] = names(ours)

    def check(label: str, a, b) -> None:
        if a != b:
            problems.append(f"{label}: ours {a!r} vs Inter {b!r}")

    check("glyph count", len(ours.getGlyphOrder()), len(ref.getGlyphOrder()) + len(GREEK_IOTAS))
    check("code points", sorted(ours.getBestCmap()), sorted(ref.getBestCmap()))
    check("axes", [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in ours["fvar"].axes],
          [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in ref["fvar"].axes])
    check("named instances", len(ours["fvar"].instances), len(ref["fvar"].instances))
    for table in ("GSUB", "GPOS"):
        ours_tags, ref_tags = set(features(ours, table)), set(features(ref, table))
        for tag in sorted(ours_tags ^ ref_tags):
            if ("feature", tag) not in KNOWN:
                problems.append(f"{table} feature {tag} only in {'ours' if tag in ours_tags else 'Inter'}")

    defaults, alternates = default_swap(ref)
    swap = {**defaults, **alternates}
    runs = spacing_runs(ref)
    with ProcessPoolExecutor() as pool:
        # Spacing runs in other processes while the outlines are compared here.
        spaced = [pool.submit(spacing, (ours_path, ref_path, loc, run))
                  for loc in LOCATIONS for run in runs]
        for loc in LOCATIONS:
            a = instantiateVariableFont(TTFont(ours_path), loc)
            b = instantiateVariableFont(TTFont(ref_path), loc)
            ca, cb = a.getBestCmap(), b.getBestCmap()
            gsa, gsb = a.getGlyphSet(), b.getGlyphSet()
            for cp, name_a in ca.items():
                name_b = cb.get(swap.get(cp, cp))
                if name_b is None:
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
    defaults, alternates = default_swap(TTFont(args.inter))
    print(f"known: {len(defaults)} code points show Inter's serifed I and tailed l, "
          f"{len(alternates)} private-use ones its plain forms")
    for (kind, key), why in KNOWN.items():
        print(f"known: {kind} {f'U+{key:04X}' if isinstance(key, int) else key} ({why})")
    print("identical to Inter except known differences" if not problems else f"{len(problems)} unexplained differences")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
