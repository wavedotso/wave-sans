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

## Build

```bash
make venv     # Python environment from requirements.txt
make build    # build/fonts/var/WaveSans[GRAD,opsz,wght].ttf
make verify   # compare with the official Inter release, glyph by glyph
```

Review images: `tools/proof.py` sets the same lines side by side in several
font setups (see its `--help`).

`make verify` needs Inter's v4.1 release unpacked in
`upstream/inter-release/extracted/` (download `Inter-4.1.zip` from
https://github.com/rsms/inter/releases/tag/v4.1).

## Layout

| Path | What it is |
|---|---|
| `src/` | Font sources (Glyphs 3 packages, OpenType feature files) |
| `misc/tools/` | Inter's build scripts that Wave Sans uses |
| `tools/` | Wave Sans build, verification and proof sheets |
| `upstream/` | Inter checkout and release, for reference (not in git) |
