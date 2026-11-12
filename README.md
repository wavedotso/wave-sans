# Wave Sans

Wave's typeface, built on [Inter](https://github.com/rsms/inter) v4.1 by
Rasmus Andersson, under the SIL Open Font License 1.1 ([LICENSE.txt](LICENSE.txt)).

The first commit is Inter's sources, untouched. Every later commit is one
reviewed Wave Sans change on top of them, so `git log` is the full list of
differences from Inter.

## Build

```bash
make venv     # Python environment from requirements.txt
make build    # build/fonts/var/InterVariable.ttf
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
