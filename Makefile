# Wave Sans
#   make venv     create .venv from requirements.txt
#   make build    build/fonts/var/WaveSans[GRAD,opsz,wght].ttf from src/, and
#                 the web fonts in build/fonts/web
#   make verify   compare the build with the official Inter v4.1 release, and
#                 the web fonts with the build
#   make qa       FontBakery's checks, and how alike confusable pairs look
#                 next to Inter
#   make upstream download Inter's v4.1 release, which verify and qa compare
#                 against, and check its checksum (verify and qa do it too)
#   make specimen the specimen page and the web fonts in build/specimen,
#                 served at http://localhost:8000 (PORT=... to change it)
#   make package  the npm package @waveso/sans in build/package, and the
#                 release download build/wave-sans-<version>.zip with
#                 build/release-notes.md
#   make assets   the README images in assets/, drawn from the font
#   make clean    remove build/

FONT := build/fonts/var/WaveSans[GRAD,opsz,wght].ttf
WEB := build/fonts/web
SPECIMEN := build/specimen
PACKAGE := build/package
PORT ?= 8000
PYTHON ?= python3
INTER_DIR := upstream/inter-release
INTER_ZIP := $(INTER_DIR)/Inter-4.1.zip
INTER_ZIP_URL := https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
INTER_ZIP_SHA256 := 9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e
INTER_RELEASE ?= $(INTER_DIR)/extracted/InterVariable.ttf

.PHONY: venv build verify qa upstream specimen package assets clean

venv: .venv/.ok

.venv/.ok: requirements.txt
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt
	touch $@

build: venv
	bash tools/build.sh "$(FONT)" "$(WEB)"

verify: venv $(INTER_RELEASE)
	.venv/bin/python tools/verify.py "$(FONT)" "$(INTER_RELEASE)"
	.venv/bin/python tools/verify_web.py "$(FONT)" "$(WEB)" --specimen specimen/index.html

qa: venv $(INTER_RELEASE)
	.venv/bin/python tools/qa.py "$(FONT)"
	.venv/bin/python tools/legibility.py "$(FONT)" "$(INTER_RELEASE)"

upstream: $(INTER_RELEASE)

$(INTER_DIR)/extracted/InterVariable.ttf:
	mkdir -p "$(INTER_DIR)"
	curl -fsSL -o "$(INTER_ZIP)" "$(INTER_ZIP_URL)"
	echo "$(INTER_ZIP_SHA256)  $(INTER_ZIP)" | shasum -a 256 -c -
	rm -rf "$(INTER_DIR)/extracted"
	unzip -q "$(INTER_ZIP)" -d "$(INTER_DIR)/extracted"
	touch "$@"

# Browsers do not load fonts from a page opened as a file, so the specimen is
# served. build/specimen is the whole site: any web server can host the folder.
specimen: venv
	@test -f "$(WEB)/wave-sans.css" || { echo "no web fonts in $(WEB): run make build first"; exit 1; }
	mkdir -p "$(SPECIMEN)/fonts"
	cp specimen/index.html "$(SPECIMEN)/"
	cp "$(WEB)/wave-sans.css" "$(WEB)"/WaveSans-*.woff2 "$(SPECIMEN)/fonts/"
	@echo "specimen at http://localhost:$(PORT) (Ctrl-C stops it)"
	.venv/bin/python -m http.server "$(PORT)" --bind 127.0.0.1 --directory "$(SPECIMEN)"

package: venv
	.venv/bin/python tools/package.py "$(FONT)" "$(WEB)" "$(PACKAGE)"

assets: venv
	.venv/bin/python tools/assets.py "$(FONT)" assets

clean:
	rm -rf build
