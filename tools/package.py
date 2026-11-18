"""Put a release together: the npm package @waveso/sans in a folder, ready to
publish, and the fonts as people download them.

    .venv/bin/python tools/package.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" build/fonts/web build/package

The package is package/package.json and package/README.md, LICENSE.txt and
FONTLOG.txt, the web fonts with their stylesheet, and the variable font.
Next to the folder go wave-sans-<version>.zip, with the variable font, the
web fonts, the license and the FONTLOG, and release-notes.md, the FONTLOG
entries of the font version. This checks that:

- the package version matches the font version, which version.txt sets and
  the build writes into the font with three decimals (0.1 is 0.001, 1.2 is
  1.002): version 0.1 is package 0.1.x, where the last number counts
  releases of the same font;
- FONTLOG.txt has entries under "Wave Sans <version>";
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
import zipfile
from pathlib import Path
from typing import List

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
ALWAYS_PUBLISHED = {"package.json", "README.md"}


def font_version(font: Path) -> str:
    """The font's version as version.txt and FONTLOG write it: the font's
    revision 0.001 is version 0.1."""
    major, minor = f"{TTFont(font)['head'].fontRevision:.3f}".split(".")
    return f"{int(major)}.{int(minor)}"


def release_notes(fontlog: str, version: str) -> str:
    """The FONTLOG entries under "Wave Sans <version>", as Markdown."""
    heading = re.compile(rf"Wave Sans {re.escape(version)}\b")
    notes: List[str] = []
    inside = False
    for line in fontlog.splitlines():
        if line.startswith("Wave Sans "):
            if inside:
                break
            inside = bool(heading.match(line))
        elif inside:
            if line and not line.startswith(("- ", "  ")):
                break
            notes.append(line)
    return "\n".join(notes).strip()


def release_zip(path: Path, font: Path, web: Path) -> None:
    """The fonts as people download them, in one folder named like the zip."""
    folder = path.stem
    files = [(font, font.name), (ROOT / "LICENSE.txt", "LICENSE.txt"), (ROOT / "FONTLOG.txt", "FONTLOG.txt")]
    files += [(f, f"web/{f.name}") for f in sorted(web.iterdir()) if f.suffix in (".css", ".woff2")]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, name in files:
            archive.write(source, f"{folder}/{name}")


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
    version = font_version(args.font)
    if not re.fullmatch(rf"{re.escape(version)}\.\d+", manifest["version"]):
        print(f"package/package.json has version {manifest['version']}; the font is version {version}, "
              f"so the package must be {version}.x")
        return 1
    notes = release_notes((ROOT / "FONTLOG.txt").read_text(), version)
    if not notes:
        print(f"FONTLOG.txt has no entries under Wave Sans {version}")
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

    download = args.out.parent / f"wave-sans-{manifest['version']}.zip"
    release_zip(download, args.font, args.web)
    (args.out.parent / "release-notes.md").write_text(notes + "\n")
    print(f"{download}: {download.stat().st_size / 1024:.0f} KB; release notes in {args.out.parent / 'release-notes.md'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
