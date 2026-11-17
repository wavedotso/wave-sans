# Wave Sans

Wave's typeface, built on [Inter](https://github.com/rsms/inter) v4.1 by
Rasmus Andersson, under the SIL Open Font License 1.1 ([LICENSE.txt](LICENSE.txt)).
"Wave Sans" is a Reserved Font Name: a modified version must be published
under another name.

The first commit is Inter's sources, untouched. Every later commit is one
reviewed Wave Sans change on top of them, so `git log` is the full list of
differences from Inter. [FONTLOG.txt](FONTLOG.txt) summarizes them for people
who use the fonts.

## Axes

| Axis | Range | Set with |
|---|---|---|
| `wght` weight | 100 to 900 | `font-weight` |
| `opsz` optical size | 14 to 32 | automatic: it follows the font size (`font-optical-sizing: auto`) |
| `GRAD` grade | −50 to +100 | `font-variation-settings: "GRAD" -25` |

Grade changes stroke weight without changing any width or kerning, so text
never reflows. It is measured in weight units: grade +100 has the strokes of
weight +100. Use about −25 for light text on dark backgrounds, where text
looks heavier, and up to +100 for hover and selected states. Axis tags are
case-sensitive, and `font-variation-settings` replaces the value of a parent
element rather than adding to it.

## Web

`make build` also writes web fonts to `build/fonts/web/`: WOFF2 files split
by character set, and `wave-sans.css`, which loads them. Serve the folder and
link the stylesheet:

```html
<link rel="stylesheet" href="/fonts/wave-sans.css">
```

```css
body { font-family: "Wave Sans", system-ui, sans-serif; }
```

A browser downloads only the files whose characters a page uses. An English
page needs `WaveSans-latin.woff2` (about 140 KB); a Polish page adds
`latin-ext` (about 70 KB); a Russian page needs `cyrillic`, plus `latin` for
digits and punctuation. Letters of living languages are split from phonetic
and historic ones, and symbols, letterlike forms and private-use alternates
have files of their own, so together the files cover every character. Every
file has all three axes and every OpenType feature. Preloading the Latin file
avoids a flash of fallback text:

```html
<link rel="preload" href="/fonts/WaveSans-latin.woff2" as="font" type="font/woff2" crossorigin>
```

`WaveSans.woff2` is the whole font in one file (about 460 KB), for setups
that do not split by character.

## Specimen

`specimen/index.html` shows the font at work: usernames, grade, sizes and
weights, languages with the files each one loads, OpenType features and every
character. `make specimen` copies it and the web fonts into `build/specimen`
and serves it at http://localhost:8000. That folder is the whole site, so any
web server can host it. `make verify` checks that the font has every
character the page uses.

## Build

```bash
make venv     # Python environment from requirements.txt
make build    # build/fonts/var/WaveSans[GRAD,opsz,wght].ttf and build/fonts/web/
make verify   # compare with the official Inter release glyph by glyph, and the web fonts with the build
make qa       # FontBakery's checks, and confusable pairs measured against Inter
make specimen # the specimen page, served at http://localhost:8000
```

`make qa` runs FontBakery's universal checks and fails on any difference,
item by item, from the problems recorded in `tools/qa-known.json`;
`tools/qa.py` gives the reason each one is accepted. It then measures how
alike confusable pairs look at 11, 12, 13, 14 and 16 px on 1x and 2x screens,
Wave Sans against Inter: I l 1, O 0 o, rn m, cl d and vv w, and I T, l t and
l L, which the serifed I and tailed l bring a little closer. A score compares
one pair across the two fonts, not one pair with another.
`tools/legibility.py --image <file>` draws the pairs at 12 px, pixel by pixel.

Review images: `tools/proof.py` sets the same lines side by side in several
font setups (see its `--help`).

`make verify` and `make qa` need Inter's v4.1 release unpacked in
`upstream/inter-release/extracted/` (download `Inter-4.1.zip` from
https://github.com/rsms/inter/releases/tag/v4.1).

## Layout

| Path | What it is |
|---|---|
| `src/` | Font sources (Glyphs 3 packages, OpenType feature files) |
| `specimen/` | The specimen page |
| `misc/tools/` | Inter's build scripts that Wave Sans uses |
| `tools/` | Wave Sans build, verification and proof sheets |
| `upstream/` | Inter checkout and release, for reference (not in git) |
