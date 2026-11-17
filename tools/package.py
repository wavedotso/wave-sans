"""Put the npm package @waveso/sans together in a folder, ready to publish.

    .venv/bin/python tools/package.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" build/fonts/web build/package

The package is package/package.json and package/README.md, LICENSE.txt and
FONTLOG.txt, the web fonts with their stylesheet, and the variable font.
This checks that:

- the package version matches the font version: font 1.000 is package
  1.0.x, font 1.001 is 1.1.x, and the last number counts releases of the
  same font;
- every file the stylesheet loads and every export points to is in the
  folder;
- every file in the folder is one the package's "files" list publishes.

Prints the files and their sizes; exits 1 on any problem.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
ALWAYS_PUBLISHED = {"package.json", "README.md"}


def font_version(font: Path) -> str:
    """The npm version prefix for a font: revision 1.000 is "1.0."."""
    major, minor = f"{TTFont(font)['head'].fontRevision:.3f}".split(".")
    return f"{int(major)}.{int(minor)}."


def empty(folder: Path) -> None:
    """Delete and recreate a folder. Finder can recreate .DS_Store inside a
    folder while it is deleted, which fails with "Directory not empty"."""
    for _ in range(5):
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            break
        time.sleep(0.2)
    else:
        shutil.rmtree(folder)
    folder.mkdir(parents=True)


def check(folder: Path, manifest: dict, css: str) -> List[str]:
    problems = []
    names = {p.name for p in folder.iterdir()}
    for url in re.findall(r'url\("?([^")]+)"?\)', css):
        if url not in names:
            problems.append(f"wave-sans.css loads {url}, which is not in the package")
    for subpath, target in manifest["exports"].items():
        for path in target.values() if isinstance(target, dict) else [target]:
            pattern = path.removeprefix("./")
            if not any(fnmatch.fnmatchcase(name, pattern) for name in names):
                problems.append(f"export {subpath} points to {path}, which is not in the package")
    for name in sorted(names - ALWAYS_PUBLISHED):
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in manifest["files"]):
            problems.append(f"{name} is in the folder but not in the package's files list")
    return problems


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("font", type=Path, help="the variable font (TTF)")
    ap.add_argument("web", type=Path, help="the web fonts folder")
    ap.add_argument("out", type=Path, help="the package folder to write")
    args = ap.parse_args(argv)

    manifest = json.loads((ROOT / "package" / "package.json").read_text())
    expected = font_version(args.font)
    if not manifest["version"].startswith(expected):
        print(f"package/package.json has version {manifest['version']}, the font is {expected}x")
        return 1

    empty(args.out)
    sources = [ROOT / "package" / "package.json", ROOT / "package" / "README.md", ROOT / "LICENSE.txt",
               ROOT / "FONTLOG.txt", args.web / "wave-sans.css", *sorted(args.web.glob("*.woff2")), args.font]
    for source in sources:
        shutil.copy2(source, args.out / source.name)

    problems = check(args.out, manifest, (args.web / "wave-sans.css").read_text())
    for p in problems:
        print(p)
    files = sorted(args.out.iterdir())
    for f in files:
        print(f"{f.stat().st_size / 1024:8.0f} KB  {f.name}")
    print(f"{manifest['name']} {manifest['version']}: {len(files)} files, "
          f"{sum(f.stat().st_size for f in files) / 1024:.0f} KB, in {args.out}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
