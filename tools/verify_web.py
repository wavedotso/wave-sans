"""Check the web fonts against the variable font they are cut from.

    .venv/bin/python tools/verify_web.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" build/fonts/web

tools/web.py splits the font into WOFF2 files by character, with a
stylesheet whose unicode-range values tell browsers which file has which
characters. This checks that:

- the stylesheet's rules give the font's family, weights and style, and
  name every file in the folder (the one-file WOFF2 aside) once;
- each rule's unicode-range lists exactly the characters its file maps,
  together the files map every character of the font, and only combining
  accents are in more than one file;
- each file keeps the font's names (copyright and license included; legacy
  Mac names and the names of stylistic sets it has no glyphs for aside),
  axes, named instances and vertical metrics;
- each file draws and shapes its characters as the font does when limited
  to them, which is how browsers use a font with a unicode-range (a letter
  and an accent compose only into a character the file has). At eight
  design-space locations, both ends of the grade axis included, it compares
  every outline and advance, every ordered pair of the file's characters,
  and a run of all of them with each OpenType feature on;
- the one-file WOFF2 has the font's tables unchanged, glyph names aside.

Prints each problem; exits 1 if any.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Set, Tuple

import uharfbuzz as hb
from fontTools.ttLib import TTFont

from verify import LOCATIONS, outline_keys, shape

WEB_LOCATIONS = LOCATIONS + [
    {"wght": 100, "opsz": 14, "GRAD": -50},
    {"wght": 900, "opsz": 32, "GRAD": 100},
]
WHOLE_FONT_TABLES_REBUILT = {"glyf", "loca", "head", "post"}
STYLE = {
    "head": ("unitsPerEm", "macStyle"),
    "hhea": ("ascent", "descent", "lineGap"),
    "OS/2": ("usWeightClass", "usWidthClass", "fsType", "fsSelection", "achVendID", "sTypoAscender",
             "sTypoDescender", "sTypoLineGap", "usWinAscent", "usWinDescent", "sxHeight", "sCapHeight"),
}


def rules(css: str) -> List[Dict[str, str]]:
    """The @font-face rules, each as {descriptor: value}."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [{name: " ".join(value.split()) for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]*);", body)}
            for body in re.findall(r"@font-face\s*\{(.*?)\}", css, flags=re.S)]


def code_points(unicode_range: str) -> Set[int]:
    points: Set[int] = set()
    for item in unicode_range.split(","):
        m = re.fullmatch(r"\s*U\+([0-9A-F]{1,6})(?:-([0-9A-F]{1,6}))?\s*", item, flags=re.I)
        if not m:
            raise ValueError(f"unicode-range item {item!r}")
        points.update(range(int(m[1], 16), int(m[2] or m[1], 16) + 1))
    return points


def sfnt(font: TTFont) -> bytes:
    """The font as plain OpenType data, for HarfBuzz (which reads no WOFF2)."""
    font.flavor = None
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def names(font: TTFont) -> Set[Tuple]:
    """Windows-platform name records (browsers read no other)."""
    return {(r.nameID, r.platEncID, r.langID, r.toUnicode()) for r in font["name"].names if r.platformID == 3}


def feature_names(font: TTFont) -> Dict[str, Set[int]]:
    """The name IDs each stylistic set and character variant labels itself with."""
    ids: Dict[str, Set[int]] = {}
    for record in font["GSUB"].table.FeatureList.FeatureRecord:
        params = record.Feature.FeatureParams
        if params is None:
            continue
        found = {getattr(params, attr, 0) for attr in ("UINameID", "FeatUILabelNameID", "FeatUITooltipTextNameID",
                                                       "SampleTextNameID")}
        first = getattr(params, "FirstParamUILabelNameID", 0)
        found |= set(range(first, first + getattr(params, "NumNamedParameters", 0))) if first else set()
        ids.setdefault(record.FeatureTag, set()).update(found - {0})
    return ids


def axes(font: TTFont) -> List[Tuple]:
    fvar = font["fvar"]
    return ([(a.axisTag, a.minValue, a.defaultValue, a.maxValue, a.axisNameID, a.flags) for a in fvar.axes]
            + [(sorted(i.coordinates.items()), i.subfamilyNameID, i.postscriptNameID) for i in fvar.instances])


def style(font: TTFont) -> Dict[str, object]:
    return {f"{table}.{attr}": getattr(font[table], attr) for table, attrs in STYLE.items() for attr in attrs}


def metadata(name: str, web: TTFont, font: TTFont) -> List[str]:
    """Names, axes, instances, STAT, avar and vertical metrics, as the font has them."""
    problems = []
    kept = {r.FeatureTag for r in web["GSUB"].table.FeatureList.FeatureRecord} if "GSUB" in web else set()
    unused = {i for tag, ids in feature_names(font).items() if tag not in kept for i in ids}
    expected = {r for r in names(font) if r[0] not in unused}
    if names(web) != expected:
        ids = sorted({r[0] for r in names(web) ^ expected})
        problems.append(f"{name}: name records differ from the font's for IDs {ids}")
    if axes(web) != axes(font):
        problems.append(f"{name}: axes or named instances differ")
    for tag in ("STAT", "avar", "MVAR"):
        if tag in font and (tag not in web or web[tag].compile(web) != font[tag].compile(font)):
            problems.append(f"{name}: {tag} differs")
    ours, theirs = style(web), style(font)
    problems += [f"{name}: {key} {ours[key]!r}, font has {theirs[key]!r}" for key in ours if ours[key] != theirs[key]]
    return problems


def stylesheet(css: str, folder: Path, font: TTFont, whole: str) -> Tuple[List[str], Dict[str, Set[int]]]:
    """Problems with the rules, and each file's characters by its rules."""
    family = font["name"].getDebugName(16) or font["name"].getDebugName(1)
    wght = next(a for a in font["fvar"].axes if a.axisTag == "wght")
    expected = {"font-family": f'"{family}"', "font-style": "normal",
                "font-weight": f"{wght.minValue:g} {wght.maxValue:g}", "font-display": "swap"}
    problems: List[str] = []
    files: Dict[str, Set[int]] = {}
    for rule in rules(css):
        m = re.fullmatch(r'url\("([^"/]+\.woff2)"\) format\("woff2"\)', rule.get("src", ""))
        if not m:
            problems.append(f"stylesheet: src {rule.get('src')!r} is not one local WOFF2 file")
            continue
        file = m[1]
        for key, value in expected.items():
            if rule.get(key) != value:
                problems.append(f"stylesheet {file}: {key} {rule.get(key)!r}, expected {value!r}")
        if file in files:
            problems.append(f"stylesheet: {file} has two rules")
        if "unicode-range" not in rule:
            problems.append(f"stylesheet {file}: no unicode-range, so every page would download it")
            continue
        files[file] = code_points(rule["unicode-range"])
    on_disk = {p.name for p in folder.glob("*.woff2")}
    for file in sorted(set(files) - on_disk):
        problems.append(f"stylesheet: {file} does not exist")
    for file in sorted(on_disk - set(files) - {whole}):
        problems.append(f"{file}: no rule in the stylesheet loads it")
    return problems, files


def coverage(files: Dict[str, Set[int]], cmap: Set[int]) -> List[str]:
    """Every character in some file, and only combining accents in two."""
    problems = []
    union = set().union(*files.values()) if files else set()
    if cmap - union:
        problems.append(f"{len(cmap - union)} characters in no file: "
                        + " ".join(f"U+{cp:04X}" for cp in sorted(cmap - union)[:20]))
    if union - cmap:
        problems.append(f"{len(union - cmap)} characters listed that the font lacks")
    seen: Dict[int, str] = {}
    for file, points in files.items():
        for cp in points:
            if cp in seen and not unicodedata.category(chr(cp)).startswith("M"):
                problems.append(f"U+{cp:04X} is in {seen[cp]} and {file}")
            seen.setdefault(cp, file)
    return problems


def whole_font(name: str, web: TTFont, font: TTFont) -> List[str]:
    """The one-file WOFF2 against the font: every table unchanged, except
    that glyph names are dropped and the outline tables are rebuilt from the
    WOFF2 encoding (compared glyph by glyph)."""
    problems = []
    if sorted(web.keys()) != sorted(font.keys()):
        problems.append(f"tables {sorted(web.keys())}, font has {sorted(font.keys())}")
    for tag in sorted(set(web.keys()) & set(font.keys()) - WHOLE_FONT_TABLES_REBUILT - {"GlyphOrder"}):
        if web.reader[tag] != font.reader[tag]:
            problems.append(f"table {tag} differs")
    if web["post"].formatType != 3.0:
        problems.append(f"post format {web['post'].formatType}, expected 3 (no glyph names)")
    for attr in ("italicAngle", "underlinePosition", "underlineThickness", "isFixedPitch"):
        if getattr(web["post"], attr) != getattr(font["post"], attr):
            problems.append(f"post.{attr} differs")
    for attr in vars(font["head"]):
        if attr not in ("checkSumAdjustment", "flags", "tableTag") and getattr(web["head"], attr) != getattr(font["head"], attr):
            problems.append(f"head.{attr} differs")
    glyf_a, glyf_b = web["glyf"], font["glyf"]
    for gid, (a, b) in enumerate(zip(web.getGlyphOrder(), font.getGlyphOrder())):
        (pa, ea, fa), (pb, eb, fb) = glyf_a[a].getCoordinates(glyf_a), glyf_b[b].getCoordinates(glyf_b)
        if list(pa) != list(pb) or list(ea) != list(eb) or [f & 1 for f in fa] != [f & 1 for f in fb]:
            problems.append(f"glyph {gid} ({b}) differs")
    return [f"{name}: {p}" for p in problems]


def limited(font: hb.Font, points: Set[int]) -> hb.Font:
    """The font, mapping only these characters, as a browser uses it for a
    @font-face rule with this unicode-range."""
    def nominal(_font, cp: int, _data) -> int:
        return font.get_nominal_glyph(cp) or 0 if cp in points else 0
    funcs = hb.FontFuncs.create()
    funcs.set_nominal_glyph_func(nominal, None)
    sub = hb.Font(font)
    sub.funcs = funcs
    return sub


def shaping(job: Tuple[bytes, Dict[str, Tuple[bytes, List[int]]], List[str], Dict[str, float]]) -> List[str]:
    """Each file against the font limited to its characters, at one
    location: the outline and advance of each character, every ordered pair
    of its characters (x y1 x y2 ...), and a run of all of them with each
    feature on."""
    font_data, web_files, tags, loc = job
    whole = hb.Font(hb.Face(font_data))
    whole.set_variations(loc)
    font_keys = outline_keys(whole)
    problems: List[str] = []
    for file, (data, points) in web_files.items():
        web = hb.Font(hb.Face(data))
        web.set_variations(loc)
        web_keys = outline_keys(web)
        font = limited(whole, set(points))
        font.set_variations(loc)
        label = f"{loc} {file}"
        for cp in points:
            a, b = web.get_nominal_glyph(cp), font.get_nominal_glyph(cp)
            if a is None or web_keys[a] != font_keys[b]:
                problems.append(f"{label} U+{cp:04X}: outline differs")
            elif web.get_glyph_h_advance(a) != font.get_glyph_h_advance(b):
                problems.append(f"{label} U+{cp:04X}: advance {web.get_glyph_h_advance(a)}, "
                                f"font has {font.get_glyph_h_advance(b)}")
        chars = "".join(chr(cp) for cp in points)
        pairs: Dict[str, str] = {}
        for x in chars:
            text = "".join(x + y for y in chars)
            a, b = shape(web, web_keys, text, {}), shape(font, font_keys, text, {})
            if a == b:
                continue
            for ga, gb in zip(a, b):
                if ga != gb:
                    pairs.setdefault(text[ga[0]:ga[0] + 2], "different shape" if ga[:2] != gb[:2]
                                     else f"{ga[2:]} vs font {gb[2:]}")
                    break
            if len(a) != len(b):
                pairs.setdefault(f"{x} + any", "different number of glyphs")
        problems += [f"{label} pair {pair!r}: {why}" for pair, why in sorted(pairs.items())[:8]]
        if len(pairs) > 8:
            problems.append(f"{label}: {len(pairs) - 8} more pairs differ")
        for tag in tags:
            if shape(web, web_keys, chars, {tag: True}) != shape(font, font_keys, chars, {tag: True}):
                problems.append(f"{label}: shapes differently with {tag} on")
    return problems


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("font", type=Path, help="the variable font (TTF)")
    ap.add_argument("web", type=Path, help="the web fonts folder")
    args = ap.parse_args(argv)
    font = TTFont(args.font)
    cmap = set(font.getBestCmap())
    whole = f"{args.font.name.split('[')[0]}.woff2"
    css = args.web / "wave-sans.css"
    problems, files = stylesheet(css.read_text(), args.web, font, whole)
    problems += coverage(files, cmap)

    web_files: Dict[str, Tuple[bytes, List[int]]] = {}
    for file, points in files.items():
        if not (args.web / file).exists():
            continue
        web = TTFont(args.web / file)
        mapped = set(web.getBestCmap())
        if mapped != points:
            problems.append(f"{file}: maps {len(mapped)} characters, its unicode-range lists {len(points)} "
                            f"(differ: {' '.join(f'U+{cp:04X}' for cp in sorted(mapped ^ points)[:10])})")
        problems += metadata(file, web, font)
        web_files[file] = (sfnt(web), sorted(mapped & cmap))
    if (args.web / whole).exists():
        problems += whole_font(whole, TTFont(args.web / whole), font)
    else:
        problems.append(f"{whole} does not exist")

    tags = sorted({r.FeatureTag for t in ("GSUB", "GPOS") for r in font[t].table.FeatureList.FeatureRecord})
    font_data = (args.font).read_bytes()
    with ProcessPoolExecutor() as pool:
        for result in pool.map(shaping, [(font_data, web_files, tags, loc) for loc in WEB_LOCATIONS]):
            problems += result

    for p in problems:
        print(p)
    sizes = sum((args.web / f).stat().st_size for f in files if (args.web / f).exists())
    print(f"web: {len(files)} files and {whole} cover all {len(cmap)} characters "
          f"({sizes / 1024:.0f} KB together)")
    print("web fonts match the font" if not problems
          else f"{len(problems)} web font problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
