# Wave Sans
#   make venv     create .venv from requirements.txt
#   make build    build/fonts/var/WaveSans[GRAD,opsz,wght].ttf from src/, and
#                 the web fonts in build/fonts/web
#   make verify   compare the build with the official Inter v4.1 release, and
#                 the web fonts with the build
#   make clean    remove build/

FONT := build/fonts/var/WaveSans[GRAD,opsz,wght].ttf
WEB := build/fonts/web
INTER_RELEASE ?= upstream/inter-release/extracted/InterVariable.ttf

.PHONY: venv build verify clean

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
	.venv/bin/python tools/verify_web.py "$(FONT)" "$(WEB)"

clean:
	rm -rf build
