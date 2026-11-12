#!/bin/bash
# Build the variable font from src/, following Inter's own pipeline step by
# step (Inter's Makefile, Roman). Output: build/fonts/var/InterVariable.ttf
set -euo pipefail
cd "$(dirname "$0")/.."

BIN=.venv/bin
UFO=build/ufo
OUT=build/fonts/var
mkdir -p "$UFO" "$OUT"
ln -sfn ../../src/features "$UFO/features"

echo "[1/5] glyphspackage -> glyphs"
"$BIN/glyphspkg" -o "$UFO/" src/Inter-Roman.glyphspackage

echo "[2/5] glyphs -> designspace and master UFOs"
"$BIN/fontmake" --verbose WARNING -o ufo -g "$UFO/Inter-Roman.glyphs" \
  --designspace-path "$UFO/Inter-Roman.designspace" --master-dir "$UFO" --instance-dir "$UFO"
"$BIN/python" misc/tools/postprocess-designspace.py "$UFO/Inter-Roman.designspace"

echo "[3/5] variable designspace"
"$BIN/python" misc/tools/gen-var-designspace.py "$UFO/Inter-Roman.designspace" "$UFO/Inter-Roman.var.designspace"

echo "[4/5] variable font"
"$BIN/fontmake" --verbose WARNING -o variable -m "$UFO/Inter-Roman.var.designspace" \
  --output-path "$OUT/.Inter-Roman.var.ttf" \
  --overlaps-backend pathops --flatten-components --no-autohint --production-names

echo "[5/5] finish (names, STAT)"
"$BIN/python" misc/tools/bake-vf.py "$OUT/.Inter-Roman.var.ttf" -o "$OUT/InterVariable.ttf"

echo "built $OUT/InterVariable.ttf"
