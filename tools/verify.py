"""Compare Wave Sans with the official Inter release, glyph by glyph.

    .venv/bin/python tools/verify.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" \
        upstream/inter-release/extracted/InterVariable.ttf

Wave Sans is Inter with the changes described below (the default I and l,
the grade axis, and KNOWN), and this checks that nothing else differs. It
checks that no family name or vendor ID is still Inter's and that the
copyright and license records are in place, then the glyph set,
code points, axes, named instances and OpenType features. At several
design-space locations it then compares each character's advance width and
outline with Inter's glyph for it, and shapes every pair of characters with
HarfBuzz, comparing the shapes each pair becomes and their positions, which
covers kerning. For the grade axis, it checks that no width or position moves
at any grade, that no outline collapses, and that grades match the weights
they stand for. Prints each difference; exits 1 if any is unexplained.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Set, Tuple

import pathops
import uharfbuzz as hb
import unicodedata2 as unicodedata
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.perimeterPen import PerimeterPen
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
    ("axis", "GRAD"): "added: grade, stroke weight without any width change",
}

# The grade axis: grade g gives the strokes of weight + g, and no advance or
# kerning moves at any grade. At Regular, each end of the axis must match the
# n stem of the weight it stands for, within a unit.
REGULAR = 400
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

# Inter gave its accented serifed I and tailed l alternates no kerning of
# their own. Ours kern like their base letter wherever that adds no overlap
# the base letter does not already have, measured at the six locations: every
# serifed I form, and ļ (with its ss03 and ss07 forms). Greek iotas with an
# accent left of the stem do so on their right side only, as Inter's plain
# ones do. ĺ, ḷ, ľ, ŀ and the other l forms keep Inter's kerning: their
# accents would touch some neighbors. kerning() checks these pair by pair;
# spacing() leaves their kerning to it.
# Escaped: Unicode normalization would turn U+1FDB (with oxia) into U+038A.
LEFT_ACCENTED_IOTAS = "ἸἹἺἻἼἽἾἿῚΊΊ"
KERNS_LIKE = {**{c: "I" for c in "ÍÌÎÏĨĪĬĮİǏȈȊỈỊƗḬḮІЇΙΪῘῙ" + LEFT_ACCENTED_IOTAS}, "ļ": "l"}
# Next to accented i, Ї keeps the kerning Inter gave its serifed alternate,
# in the masters where Inter gave it some; elsewhere it kerns like I.
KEEPS_INTER_KERNING = {"Ї": "ïĩīĭȋїḯ"}


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

# Every copy must carry the license (OFL condition 2): the copyright notice,
# which keeps Inter's line and declares the Reserved Font Name, and the
# license's description and address.
LICENSE_NAMES = {
    13: "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
        "This license is available with a FAQ at: https://openfontlicense.org",
    14: "https://openfontlicense.org",
}
COPYRIGHT_PARTS = ('with Reserved Font Name "Wave Sans"', "Copyright 2016 The Inter Project Authors")


def names(font: TTFont) -> List[str]:
    ids = PRESENTED_NAME_IDS | {i.postscriptNameID for i in font["fvar"].instances}
    problems = [f"name ID {r.nameID} still says Inter: {r.toUnicode()!r}"
                for r in font["name"].names if r.nameID in ids and "Inter" in r.toUnicode()]
    if font["OS/2"].achVendID == "RSMS":
        problems.append("OS/2 vendor ID is still Inter's (RSMS)")
    windows = {r.nameID: r.toUnicode() for r in font["name"].names if (r.platformID, r.langID) == (3, 0x409)}
    for name_id, text in LICENSE_NAMES.items():
        if windows.get(name_id) != text:
            problems.append(f"name ID {name_id} is not the license's: {windows.get(name_id)!r}")
    problems += [f"name ID 0 (copyright) lacks {part!r}" for part in COPYRIGHT_PARTS
                 if part not in windows.get(0, "")]
    return problems


def features(font: TTFont, table: str) -> List[str]:
    return sorted({r.FeatureTag for r in font[table].table.FeatureList.FeatureRecord})


def outline(glyph_set, name: str) -> List[Tuple[float, float]]:
    pen = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(pen)
    return [p for _, args in pen.value for p in args]


def deviation(glyph_set_a, name_a: str, glyph_set_b, name_b: str) -> float:
    """Mean distance between two outlines, in font units: the area between
    them over their length. For outlines whose curves were converted with
    other points, so they cannot be compared point by point."""
    paths = []
    for glyph_set, name in ((glyph_set_a, name_a), (glyph_set_b, name_b)):
        path = pathops.Path()
        glyph_set[name].draw(path.getPen(glyphSet=glyph_set))
        paths.append(path)
    between = AreaPen()
    pathops.op(paths[0], paths[1], pathops.PathOp.XOR).draw(between)
    length = PerimeterPen(glyph_set_a)
    glyph_set_a[name_a].draw(length)
    return abs(between.value) / length.value if length.value else 0.0


def reconverted(ours: TTFont, ref: TTFont, swap: Dict[int, int]) -> Dict[int, float]:
    """Code points whose outline has other points than Inter's but the same
    shape within a unit. Converting curves to TrueType over more masters (the
    grade masters) splits a few curves differently."""
    gsa, gsb = ours.getGlyphSet(), ref.getGlyphSet()
    ca, cb = ours.getBestCmap(), ref.getBestCmap()
    found = {}
    for cp, name_a in ca.items():
        name_b = cb.get(swap.get(cp, cp))
        if name_b and len(outline(gsa, name_a)) != len(outline(gsb, name_b)):
            distance = deviation(gsa, name_a, gsb, name_b)
            if distance <= 1:
                found[cp] = distance
    return found


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


Run = Tuple[str, Dict[str, bool], Dict[str, bool], str, Dict[int, int], str]


def standard_chars(ref: TTFont) -> str:
    return "".join(c for c in spaced_chars(ref.getBestCmap()) if unicodedata.category(c) != "Co")


def spacing_runs(ref: TTFont) -> List[Run]:
    """How Inter shows what Wave Sans shows: (label, our features, Inter's
    features, characters, Inter's stand-in characters, which of our default
    I and l forms are on: "round" dots, "square" dots or none). Inter reaches
    its alternates through features that run after its contextual forms, so
    it sets the same case-sensitive punctuation around them as we do around
    our defaults."""
    defaults, alternates = default_swap(ref)
    chars = spaced_chars(ref.getBestCmap())
    standard = standard_chars(ref)
    return [
        # Our default I and l are Inter's cv05 and cv08 forms.
        ("default", {}, {"cv05": True, "cv08": True}, standard, GREEK_IOTAS, "round"),
        # ss09 gives back Inter's own defaults.
        ("ss09", {"ss09": True}, {}, standard, {}, ""),
        # Square dots on our I and l are Inter's ss04 and ss07 forms. The
        # German sharp s, which ss04 also changes, and the Greek iotas, which
        # have no ss07 forms, are left out.
        ("ss07", {"ss07": True}, {"ss04": True, "ss07": True},
         "".join(c for c in standard if c != "ß" and ord(c) not in GREEK_IOTAS), {}, "square"),
        # Everything the swap leaves alone, private-use alternates included.
        # Private-use I and l alternates are compared glyph by glyph only:
        # Inter's contextual forms treat its own as letters, ours as symbols.
        ("unchanged", {}, {}, "".join(c for c in chars if ord(c) not in defaults
                                       and ord(c) not in alternates), {}, ""),
    ]


def kerned_like_base(text: str, at: int) -> bool:
    """Whether the kerning a glyph carries (with the character after it) is
    a KERNS_LIKE form's, which kerning() checks instead."""
    after = text[at + 1] if at + 1 < len(text) else ""
    return text[at] in KERNS_LIKE or (after in KERNS_LIKE and after not in LEFT_ACCENTED_IOTAS)


def first_kerns(font: hb.Font, text: str, feats: Dict[str, bool]) -> List[Tuple[int, int, int]]:
    """(cluster, glyph ID, kerning with the next glyph) per glyph."""
    buf = hb.Buffer()
    buf.add_codepoints([ord(c) for c in text])
    buf.guess_segment_properties()
    hb.shape(font, buf, feats)
    return [(i.cluster, i.codepoint, p.x_advance - font.get_glyph_h_advance(i.codepoint))
            for i, p in zip(buf.glyph_infos, buf.glyph_positions)]


def kerning(job: Tuple[str, str, Dict[str, float], str]) -> List[str]:
    """Each KERNS_LIKE form against its base letter at one location: with
    every partner, before and after it, the same kerning and the same partner
    glyph, with and without ss03 and ss07 (KEEPS_INTER_KERNING pairs may
    instead match Inter's own alternate)."""
    ours_path, ref_path, loc, partners = job
    fonts = []
    for path in (ours_path, ref_path):
        font = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
        font.set_variations(loc)
        fonts.append(font)
    ours, ref = fonts

    def inter_kerns(pair: str, feats: Dict[str, bool]) -> int:
        return first_kerns(ref, pair, {**feats, "cv05": True, "cv08": True})[0][2]

    pairs: Dict[str, str] = {}
    for feats in ({}, {"ss03": True}, {"ss07": True}):
        tag = ",".join(feats) or "default"
        for x, base in KERNS_LIKE.items():
            text = "".join(x + p for p in partners)
            a = first_kerns(ours, text, feats)
            b = first_kerns(ours, "".join(base + p for p in partners), feats)
            if [g[0] for g in a] != [g[0] for g in b]:
                pairs[f"{x} {tag}"] = "different glyph sequences"
                continue
            for (at, glyph_a, kern_a), (_, glyph_b, kern_b) in zip(a, b):
                pair = text[at:at + 2]
                if at % 2 and glyph_a != glyph_b:
                    pairs.setdefault(f"{pair} {tag}", "partner glyph differs")
                if kern_a == kern_b or (at % 2 and x in LEFT_ACCENTED_IOTAS) or len(pair) < 2:
                    continue
                partner = pair[1] if at % 2 == 0 else pair[0]
                if partner in KEEPS_INTER_KERNING.get(x, "") and kern_a == inter_kerns(pair, feats):
                    continue
                like = base + pair[1] if at % 2 == 0 else pair[0] + base
                pairs.setdefault(f"{pair} {tag}", f"kerns {kern_a}, {like} {kern_b}")
    label = f"{loc} kerning like the base letter"
    shown = [f"{label}: {pair!r} {why}" for pair, why in sorted(pairs.items())[:12]]
    if len(pairs) > len(shown):
        shown.append(f"{label}: {len(pairs) - len(shown)} more pairs differ")
    return shown


def spacing(job: Tuple[str, str, Dict[str, float], Run, str]) -> List[str]:
    """Pairs that shape differently at one location in one run.

    Each pass sets one character between all the others (x y1 x y2 ...), so
    together the passes cover every ordered pair. HarfBuzz puts a pair's
    kerning in the advance of its first glyph, so an advance difference is
    reported as the pair its character starts; an offset difference (a mark
    placed on the glyph before it) as the pair it ends. Characters in
    reshaped (see reconverted) are compared by position only.
    """
    ours_path, ref_path, loc, (name, ours_feats, ref_feats, chars, stand_ins, dots), reshaped = job
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
            if ga[0] == gb[0] and ga[2:] == gb[2:] and text[at] in reshaped:
                continue  # same place, outline split differently: compared by deviation()
            if dots and ga[:2] == gb[:2] and ga[3:] == gb[3:] and kerned_like_base(text, at):
                continue  # only the kerning of a KERNS_LIKE form differs: kerning() checks it
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


class ContourAreas:
    """Pen that records the signed area of each contour."""

    def __init__(self) -> None:
        self.areas: List[float] = []
        self.pen = AreaPen()

    def moveTo(self, p):
        self.pen = AreaPen()
        self.pen.moveTo(p)

    def lineTo(self, p):
        self.pen.lineTo(p)

    def qCurveTo(self, *points):
        self.pen.qCurveTo(*points)

    def curveTo(self, *points):
        self.pen.curveTo(*points)

    def closePath(self):
        self.pen.closePath()
        self.areas.append(self.pen.value)

    def endPath(self):
        self.closePath()


class Chords:
    """Pen that records each segment as a straight chord: exact for the
    straight stems the n stem is measured on."""

    def __init__(self) -> None:
        self.segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        self.start = self.current = (0.0, 0.0)

    def moveTo(self, p):
        self.start = self.current = p

    def lineTo(self, p):
        self.segments.append((self.current, p))
        self.current = p

    def qCurveTo(self, *points):
        self.lineTo(points[-1])

    def curveTo(self, *points):
        self.lineTo(points[-1])

    def closePath(self):
        self.lineTo(self.start)

    def endPath(self):
        pass


def n_stem(font: hb.Font, y: float) -> float:
    """Width of the left stem of n, crossed by a horizontal line at y."""
    pen = Chords()
    font.draw_glyph_with_pen(font.get_nominal_glyph(ord("n")), pen)
    xs = sorted(x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                for (x0, y0), (x1, y1) in pen.segments if (y0 <= y < y1) or (y1 <= y < y0))
    return xs[1] - xs[0]


def grades(job: Tuple[str, Dict[str, float], str]) -> List[str]:
    """At one location, at both ends of the grade axis against grade 0: every
    advance, and every pair's glyphs and kerning, stay the same (marks may
    move with their letter); and no contour flips or loses most of its area."""
    path, loc, chars = job
    face = hb.Face(hb.Blob.from_file_path(path))
    axis = next(a for a in face.axis_infos if a.tag == "GRAD")
    font = hb.Font(face)
    ends = (axis.min_value, axis.max_value)

    def at(grade: float) -> None:
        font.set_variations({**loc, "GRAD": grade})

    def placed(text: str) -> List[Tuple[int, int, int]]:
        buf = hb.Buffer()
        buf.add_codepoints([ord(c) for c in text])
        buf.guess_segment_properties()
        hb.shape(font, buf, {})
        return [(i.cluster, i.codepoint, p.x_advance) for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def contours() -> List[List[float]]:
        out = []
        for gid in range(face.glyph_count):
            pen = ContourAreas()
            font.draw_glyph_with_pen(gid, pen)
            out.append(pen.areas)
        return out

    problems: List[str] = []
    at(0)
    advances = [font.get_glyph_h_advance(g) for g in range(face.glyph_count)]
    areas = contours()
    for grade in ends:
        at(grade)
        moved = [g for g in range(face.glyph_count) if font.get_glyph_h_advance(g) != advances[g]]
        if moved:
            problems.append(f"{loc} GRAD {grade:g}: {len(moved)} advances change")
        collapsed = [g for g, (before, after) in enumerate(zip(areas, contours()))
                     if any(abs(a) > 2000 and b / a < 0.15 for a, b in zip(before, after))]
        if collapsed:
            names = [font.glyph_to_string(g) for g in collapsed[:6]]
            problems.append(f"{loc} GRAD {grade:g}: {len(collapsed)} glyphs with a collapsing contour, e.g. {names}")
    pairs: Dict[str, str] = {}
    for x in chars:
        text = "".join(x + y for y in chars)
        at(0)
        base = placed(text)
        for grade in ends:
            at(grade)
            for a, b in zip(base, placed(text)):
                if a != b:
                    pairs.setdefault(f"{text[a[0]:a[0] + 2]} GRAD {grade:g}", f"{b[2] - a[2]:+d} units")
                    break
    problems += [f"{loc} pair {pair!r} moves {why}" for pair, why in sorted(pairs.items())[:12]]
    return problems


def grade_matches_weight(path: str, x_height: float) -> List[str]:
    """At Regular, each end of the grade axis has the n stem of the weight it
    stands for (grade g, weight REGULAR + g), within a unit."""
    face = hb.Face(hb.Blob.from_file_path(path))
    axis = next(a for a in face.axis_infos if a.tag == "GRAD")
    font = hb.Font(face)
    problems = []
    for opsz in (14, 32):
        for grade in (axis.min_value, axis.max_value):
            font.set_variations({"wght": REGULAR, "opsz": opsz, "GRAD": grade})
            graded = n_stem(font, x_height / 2)
            font.set_variations({"wght": REGULAR + grade, "opsz": opsz, "GRAD": 0})
            weighted = n_stem(font, x_height / 2)
            if abs(graded - weighted) > 1:
                problems.append(f"opsz {opsz} GRAD {grade:g}: n stem {graded:.1f}, "
                                f"weight {REGULAR + grade:g} has {weighted:.1f}")
    return problems


def compare(ours_path: str, ref_path: str) -> Tuple[List[str], List[str]]:
    """Unexplained differences, and notes on the explained ones found."""
    ours, ref = TTFont(ours_path), TTFont(ref_path)
    problems: List[str] = names(ours)
    notes: List[str] = []

    def check(label: str, a, b) -> None:
        if a != b:
            problems.append(f"{label}: ours {a!r} vs Inter {b!r}")

    check("glyph count", len(ours.getGlyphOrder()), len(ref.getGlyphOrder()) + len(GREEK_IOTAS))
    check("code points", sorted(ours.getBestCmap()), sorted(ref.getBestCmap()))
    check("axes", [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in ours["fvar"].axes
                   if ("axis", a.axisTag) not in KNOWN],
          [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in ref["fvar"].axes])
    check("named instances", len(ours["fvar"].instances), len(ref["fvar"].instances))
    for table in ("GSUB", "GPOS"):
        ours_tags, ref_tags = set(features(ours, table)), set(features(ref, table))
        for tag in sorted(ours_tags ^ ref_tags):
            if ("feature", tag) not in KNOWN:
                problems.append(f"{table} feature {tag} only in {'ours' if tag in ours_tags else 'Inter'}")
    graded = any(a.axisTag == "GRAD" for a in ours["fvar"].axes)
    if graded:
        problems += grade_matches_weight(ours_path, ours["OS/2"].sxHeight)

    defaults, alternates = default_swap(ref)
    swap = {**defaults, **alternates}
    reshaped = reconverted(ours, ref, swap)
    if reshaped:
        notes.append(f"{len(reshaped)} outlines converted to TrueType curves with other points, "
                     f"within {max(reshaped.values()):.2f} units: "
                     + " ".join(f"U+{cp:04X}" for cp in sorted(reshaped)))
    reshaped_chars = "".join(chr(cp) for cp in reshaped)
    runs, partners = spacing_runs(ref), standard_chars(ref)
    with ProcessPoolExecutor() as pool:
        # Spacing runs in other processes while the outlines are compared here.
        spaced = [pool.submit(spacing, (ours_path, ref_path, loc, run, reshaped_chars))
                  for loc in LOCATIONS for run in runs]
        spaced += [pool.submit(kerning, (ours_path, ref_path, loc, partners)) for loc in LOCATIONS]
        if graded:
            spaced += [pool.submit(grades, (ours_path, loc, partners)) for loc in LOCATIONS]
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
                    if cp not in reshaped or deviation(gsa, name_a, gsb, name_b) > 1:
                        problems.append(f"{loc} U+{cp:04X} outline: {len(pa)} vs {len(pb)} points")
                    continue
                drift = max((abs(x1 - x2) + abs(y1 - y2) for (x1, y1), (x2, y2) in zip(pa, pb)), default=0)
                if drift > 1:
                    problems.append(f"{loc} U+{cp:04X} outline drift {drift:.1f} units")
        for job in spaced:
            problems.extend(job.result())
    return problems, notes


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ours")
    ap.add_argument("inter")
    args = ap.parse_args(argv)
    problems, notes = compare(args.ours, args.inter)
    for p in problems:
        print(p)
    for note in notes:
        print(f"known: {note}")
    defaults, alternates = default_swap(TTFont(args.inter))
    print(f"known: {len(defaults)} code points show Inter's serifed I and tailed l, "
          f"{len(alternates)} private-use ones its plain forms")
    print(f"known: {len(KERNS_LIKE)} accented I and l forms kern like their base letter, checked pair by pair")
    for (kind, key), why in KNOWN.items():
        print(f"known: {kind} {f'U+{key:04X}' if isinstance(key, int) else key} ({why})")
    print("identical to Inter except known differences" if not problems else f"{len(problems)} unexplained differences")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
