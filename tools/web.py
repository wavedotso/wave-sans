"""Cut the variable font into web fonts: WOFF2 files by character, and a
stylesheet that loads them.

    .venv/bin/python tools/web.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" build/fonts/web

A browser downloads a file only when the page uses a character its
@font-face rule lists (unicode-range), so an English page fetches the Latin
file alone. The files start from the character sets web fonts are commonly
split into (latin, latin-ext, vietnamese, greek, cyrillic and their
extensions), which are tuned to how browsers combine accents with letters,
and change them where measured downloads say so:

- Latin extended is split by need: latin-ext has the letters living
  languages use (CLDR 48: the main letters of every Latin-script alphabet)
  with their accents; latin-phonetic has phonetic, historic and other
  specialist letters.
- Vietnamese wins the letters it shares with latin-ext (ă, đ, ĩ, ũ), so a
  Vietnamese page needs two files, not three.
- ₽ and ₴ are in the Cyrillic file, where Russian and Ukrainian pages
  already are.
- The characters those sets leave out get files of their own (symbols,
  letterlike, private-use), so together the files cover every character.

Each character is in exactly one file, except combining accents, which are
in every file whose letters take them. Every file keeps all axes and
OpenType features. WaveSans.woff2 is the whole font in one file, for setups
that do not split by character.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from itertools import groupby
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from fontTools import subset
from fontTools.ttLib import TTFont


def ranges(spec: str) -> Set[int]:
    """Code points from hex ranges, as in "0000-00FF 0131"."""
    points: Set[int] = set()
    for part in spec.split():
        first, _, last = part.partition("-")
        points.update(range(int(first, 16), int(last or first, 16) + 1))
    return points


# The common web font character sets, as unicode-range values.
LATIN = ranges("0000-00FF 0131 0152-0153 02BB-02BC 02C6 02DA 02DC 0304 0308 0329 2000-206F "
               "20AC 2122 2191 2193 2212 2215 FEFF FFFD")
VIETNAMESE = ranges("0102-0103 0110-0111 0128-0129 0168-0169 01A0-01A1 01AF-01B0 0300-0301 "
                    "0303-0304 0308-0309 0323 0329 1EA0-1EF9 20AB")
GREEK = ranges("0370-0377 037A-037F 0384-038A 038C 038E-03A1 03A3-03FF")
GREEK_EXT = ranges("1F00-1FFF")
CYRILLIC = ranges("0301 0400-045F 0490-0491 04B0-04B1 2116") | ranges("20B4 20BD")
CYRILLIC_EXT = ranges("0460-052F 1C80-1C8A 2DE0-2DFF A640-A69F FE2E-FE2F")

# The letters beyond Latin Extended-A that living languages use: every
# letter of the main exemplar set of a Latin-script language in CLDR 48
# (Vietnamese aside, which has its own file), and the combining accents
# those alphabets write with.
LIVING_LETTERS = ("ƁƆƉƊƎƏƐƑƒƔƖƗƘƙƛƝƱƲƳƴǀǁǂǃǍǎǏǐǑǒǓǔǝǦǧǪǫǰǸǹȘșȚțȞȟɄɓɔɖɗəɛɣɨɩɲʉʊʋʔʷʻʼˀᶻ"
                  "ḌḍḐḑḒḓḤḥḶḷḺḻḼḽḾḿṄṅṆṇṈṉṊṋṚṛṢṣṬṭṮṯṰṱṼṽẀẁẂẃẄẅẒẓẸẹẼẽỊịỌọỤụỲỳỸỹꞋꞌꟜ")
LIVING_ACCENTS = ranges("0300-0304 0307-0308 030C 0313 0323 0327 0329 0331 1DC6-1DC7")
# Latin Extended-A, those letters and accents, and the spacing accents of
# the Central European encodings (ˇ ˘ ˙ ˛ ˝).
LATIN_EXT = (ranges("0100-017F 02C7 02D8-02D9 02DB 02DD")
             | {ord(c) for c in LIVING_LETTERS} | LIVING_ACCENTS)
# Every other Latin letter and modifier, and every combining accent.
LATIN_PHONETIC = ranges("0100-036F 1AB0-1AFF 1D00-1EFF 2C60-2C7F A720-A7FF AB30-AB6F")
LETTERLIKE = ranges("2070-209F 2100-218F 2460-24FF 2776-2793 1F100-1F1FF")
PRIVATE_USE = ranges("E000-F8FF")

# (file, what it has, characters), highest priority first: a character
# goes to the first file whose set has it, and a combining accent to every
# such file. None: every character left.
FILES: List[Tuple[str, str, Optional[Set[int]]]] = [
    ("latin", "Basic Latin, Latin-1 and general punctuation", LATIN),
    ("vietnamese", "Vietnamese letters and accents", VIETNAMESE),
    ("latin-ext", "letters of living languages beyond Latin-1, with their accents", LATIN_EXT),
    ("latin-phonetic", "phonetic and historic letters, and every combining accent", LATIN_PHONETIC),
    ("greek", "Greek", GREEK),
    ("greek-ext", "polytonic Greek", GREEK_EXT),
    ("cyrillic", "Russian, Ukrainian, Belarusian, Bulgarian, Serbian and Macedonian", CYRILLIC),
    ("cyrillic-ext", "other Cyrillic alphabets and Church Slavonic", CYRILLIC_EXT),
    ("letterlike", "super- and subscripts, number forms, letterlike and enclosed symbols", LETTERLIKE),
    ("private-use", "alternates at private-use code points", PRIVATE_USE),
    ("symbols", "currency signs, arrows, math, keys, shapes: every other character", None),
]

AXIS_NAMES = {"wght": "weight", "opsz": "optical size", "GRAD": "grade"}  # in this order


def is_accent(cp: int) -> bool:
    return unicodedata.category(chr(cp)).startswith("M")


def split(cmap: Set[int]) -> List[Tuple[str, str, Set[int]]]:
    """Each file's characters, highest priority first."""
    taken: Set[int] = set()
    files = []
    for name, about, chars in FILES:
        wanted = cmap - taken if chars is None else chars & cmap
        points = {cp for cp in wanted if cp not in taken or is_accent(cp)}
        taken |= points
        files.append((name, about, points))
    return files


def css_range(points: Iterable[int]) -> List[str]:
    """unicode-range items, as in ["U+0041-005A", "U+0061"]."""
    items = []
    for _, run in groupby(enumerate(sorted(points)), lambda p: p[1] - p[0]):
        first, *rest = [cp for _, cp in run]
        items.append(f"U+{first:04X}" + (f"-{rest[-1]:04X}" if rest else ""))
    return items


def wrap(items: List[str], start: int, indent: str, width: int = 80) -> str:
    """Items separated by commas, in lines of at most width columns; the
    first line starts at column start, the others after indent."""
    lines, line = [], ""
    for item in items:
        piece = item + ","
        if line and (start if not lines else len(indent)) + len(line) + 1 + len(piece) > width:
            lines.append(line)
            line = piece
        else:
            line = f"{line} {piece}" if line else piece
    lines.append(line)
    return f"\n{indent}".join(lines)[:-1]


def comment(text: str) -> str:
    return textwrap.fill(text, 75, initial_indent="/* ", subsequent_indent="   ") + " */\n"


def subset_font(src: Path, points: Set[int], out: Path) -> Set[int]:
    """A WOFF2 file with these characters and everything they reach through
    OpenType features; returns the characters it maps."""
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]  # keeps the copyright and license (OFL)
    options.name_languages = ["*"]
    options.notdef_outline = True
    font = TTFont(src, recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=points)
    subsetter.subset(font)
    font.flavor = "woff2"
    font.save(out)
    return set(font.getBestCmap())


def whole_font(src: Path, out: Path) -> None:
    """The whole font as WOFF2, without glyph names (post format 3)."""
    font = TTFont(src, recalcTimestamp=False)
    font["post"].formatType = 3.0
    font.flavor = "woff2"
    font.save(out)


def stylesheet(font: TTFont, files: List[Tuple[str, str, str, Set[int]]]) -> str:
    """@font-face rules, lowest priority first: where two rules list the same
    character, browsers use the later one."""
    family = font["name"].getDebugName(16) or font["name"].getDebugName(1)
    axes = {a.axisTag: a for a in font["fvar"].axes}
    weight = axes["wght"]
    order = [*AXIS_NAMES, *(tag for tag in axes if tag not in AXIS_NAMES)]
    about = ", ".join(f"{AXIS_NAMES.get(tag, tag)} {axes[tag].minValue:g} to {axes[tag].maxValue:g}"
                      for tag in order if tag in axes)
    rules = [comment(f"{family}, a variable font: {about}. Each file has some of the "
                     "characters: a browser downloads a file only when the page uses a "
                     "character its unicode-range lists. Where two rules list the same "
                     "character (combining accents), the later one wins.")]
    for name, desc, filename, points in files:
        rules.append(comment(f"{name}: {desc}") +
                     "@font-face {\n"
                     f'  font-family: "{family}";\n'
                     "  font-style: normal;\n"
                     f"  font-weight: {weight.minValue:g} {weight.maxValue:g};\n"
                     "  font-display: swap;\n"
                     f'  src: url("{filename}") format("woff2");\n'
                     f"  unicode-range: {wrap(css_range(points), len('  unicode-range: '), '    ')};\n"
                     "}\n")
    return "\n".join(rules)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("font", type=Path, help="the variable font (TTF)")
    ap.add_argument("out", type=Path, help="output folder")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for old in [*args.out.glob("*.woff2"), *args.out.glob("*.css")]:
        old.unlink()
    font = TTFont(args.font)
    prefix = args.font.name.split("[")[0]
    files = split(set(font.getBestCmap()))
    whole = args.out / f"{prefix}.woff2"
    with ProcessPoolExecutor() as pool:
        jobs = [(name, desc, f"{prefix}-{name}.woff2",
                 pool.submit(subset_font, args.font, points, args.out / f"{prefix}-{name}.woff2"))
                for name, desc, points in files]
        done = pool.submit(whole_font, args.font, whole)
        made = [(name, desc, filename, job.result()) for name, desc, filename, job in jobs]
        done.result()
    for name, desc, filename, mapped in made:
        print(f"  {filename:30} {len(mapped):5} characters {(args.out / filename).stat().st_size / 1024:6.1f} KB")
    print(f"  {whole.name:30} {len(font.getBestCmap()):5} characters {whole.stat().st_size / 1024:6.1f} KB")
    css = args.out / "wave-sans.css"
    css.write_text(stylesheet(font, list(reversed(made))))
    print(f"  {css.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
