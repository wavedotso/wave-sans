# Wave Sans
#   make venv     create .venv from requirements.txt
#   make build    build/fonts/var/InterVariable.ttf from src/
#   make verify   compare the build with the official Inter v4.1 release
#   make clean    remove build/

INTER_RELEASE ?= upstream/inter-release/extracted/InterVariable.ttf

.PHONY: venv build verify clean

venv: .venv/.ok

.venv/.ok: requirements.txt
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt
	touch $@

build: venv
	bash tools/build.sh

verify: venv
	.venv/bin/python tools/verify.py build/fonts/var/InterVariable.ttf $(INTER_RELEASE)

clean:
	rm -rf build
