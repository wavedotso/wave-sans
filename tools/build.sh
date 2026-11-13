#!/bin/bash
# Build the variable font from src/, following Inter's own pipeline step by
# step (Inter's Makefile, Roman), plus the grade axis (tools/grade.py).
# Usage: tools/build.sh <output font>
# (make build passes build/fonts/var/WaveSans[GRAD,opsz,wght].ttf).
set -euo pipefail
cd "$(dirname "$0")/.."

FONT="${1:?usage: tools/build.sh <output font>}"
BIN=.venv/bin
UFO=build/ufo
OUT="$(dirname "$FONT")"
mkdir -p "$UFO" "$OUT"
ln -sfn ../../src/features "$UFO/features"

echo "[1/6] glyphspackage -> glyphs"
"$BIN/glyphspkg" -o "$UFO/" src/WaveSans-Roman.glyphspackage

echo "[2/6] glyphs -> designspace and master UFOs"
"$BIN/fontmake" --verbose WARNING -o ufo -g "$UFO/WaveSans-Roman.glyphs" \
  --designspace-path "$UFO/WaveSans-Roman.designspace" --master-dir "$UFO" --instance-dir "$UFO"
"$BIN/python" misc/tools/postprocess-designspace.py "$UFO/WaveSans-Roman.designspace"

echo "[3/6] variable designspace"
"$BIN/python" misc/tools/gen-var-designspace.py "$UFO/WaveSans-Roman.designspace" "$UFO/WaveSans-Roman.var.designspace"

echo "[4/6] grade masters"
"$BIN/python" tools/grade.py "$UFO/WaveSans-Roman.var.designspace" "$UFO/WaveSans-Roman.grade.designspace"

echo "[5/6] variable font"
"$BIN/fontmake" --verbose WARNING -o variable -m "$UFO/WaveSans-Roman.grade.designspace" \
  --output-path "$OUT/.WaveSans-Roman.var.ttf" \
  --overlaps-backend pathops --flatten-components --no-autohint --production-names

echo "[6/6] finish (names, STAT)"
"$BIN/python" misc/tools/bake-vf.py "$OUT/.WaveSans-Roman.var.ttf" -o "$FONT"

echo "built $FONT"
