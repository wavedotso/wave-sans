# Wave Sans
#   make venv     create .venv from requirements.txt
#   make build    build/fonts/var/WaveSans[GRAD,opsz,wght].ttf from src/, and
#                 the web fonts in build/fonts/web
#   make verify   compare the build with the official Inter v4.1 release, and
#                 the web fonts with the build
#   make qa       FontBakery's checks, and how alike confusable pairs look
#                 next to Inter
#   make specimen the specimen page and the web fonts in build/specimen,
#                 served at http://localhost:8000 (PORT=... to change it)
#   make clean    remove build/

FONT := build/fonts/var/WaveSans[GRAD,opsz,wght].ttf
WEB := build/fonts/web
SPECIMEN := build/specimen
PORT ?= 8000
INTER_RELEASE ?= upstream/inter-release/extracted/InterVariable.ttf

.PHONY: venv build verify qa specimen clean

venv: .venv/.ok

.venv/.ok: requirements.txt
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt
	touch $@

build: venv
	bash tools/build.sh "$(FONT)" "$(WEB)"

verify: venv
	.venv/bin/python tools/verify.py "$(FONT)" "$(INTER_RELEASE)"
	.venv/bin/python tools/verify_web.py "$(FONT)" "$(WEB)" --specimen specimen/index.html

qa: venv
	.venv/bin/python tools/qa.py "$(FONT)"
	.venv/bin/python tools/legibility.py "$(FONT)" "$(INTER_RELEASE)"

# Browsers do not load fonts from a page opened as a file, so the specimen is
# served. build/specimen is the whole site: any web server can host the folder.
specimen: venv
	@test -f "$(WEB)/wave-sans.css" || { echo "no web fonts in $(WEB): run make build first"; exit 1; }
	mkdir -p "$(SPECIMEN)/fonts"
	cp specimen/index.html "$(SPECIMEN)/"
	cp "$(WEB)/wave-sans.css" "$(WEB)"/WaveSans-*.woff2 "$(SPECIMEN)/fonts/"
	@echo "specimen at http://localhost:$(PORT) (Ctrl-C stops it)"
	.venv/bin/python -m http.server "$(PORT)" --bind 127.0.0.1 --directory "$(SPECIMEN)"

clean:
	rm -rf build
