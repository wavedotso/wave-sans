"""Check the font with FontBakery and fail on any problem that is not known
and explained.

    .venv/bin/python tools/qa.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf"
    .venv/bin/python tools/qa.py "build/fonts/var/WaveSans[GRAD,opsz,wght].ttf" --update

FontBakery checks a font against the OpenType specification and common
practice (its universal profile). Most of what it reports on Wave Sans comes
from Inter and is accepted for the reasons in ACCEPTED. Every reported item
is compared with the ones recorded in tools/qa-known.json, so a problem cannot
hide behind an accepted check: a kink in a newly drawn letter adds an item to
the interpolation message and fails. A recorded item that is no longer
reported fails too, so that a fixed problem cannot come back unnoticed. After
an intended change, review the differences and record them with --update.
Checks that need the network are skipped: they would send the family name to
outside services.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

KNOWN_FILE = Path(__file__).with_name("qa-known.json")

# Each FontBakery check we accept problems from, with the reason. Inter's,
# unless noted.
ACCEPTED: Dict[str, str] = {
    "base_has_width": "U+0488 and U+0489 are enclosing marks drawn with no width",
    "case_mapping": "some letters lack their other case (U+01C6 has no U+01C4): new letters, for later",
    "family/win_ascent_and_descent": "Windows metrics equal the typo metrics (USE_TYPO_METRICS is set), "
                                     "so line height is the same everywhere; tall stacked accents can clip "
                                     "in old Windows apps",
    "file_size": "ours: the grade axis adds variation data; pages load the web files instead",
    "interpolation_issues": "kinks between masters in a few drawings (U+019B, U+02B8, lambda)",
    "no_mac_entries": "Mac-platform names, which the build writes; platforms read the Windows ones",
    "opentype/gdef_mark_chars": "U+0488, U+0489, U+20DD and U+20DE are not in the mark class",
    "overlapping_path_segments": "overlapping segments in a few drawings",
    "smart_dropout": "the variable font is unhinted, so it has no hinting program",
    "unreachable_glyphs": "parts and alternates that no character or feature reaches",
}

# A reported problem: (check, status, code, message text), and the items of
# the list the message gives, if any.
Key = Tuple[str, str, str, str]
Report = Dict[Key, List[str]]


def canonical(message: str, font: Path) -> Tuple[str, List[str]]:
    """A message as its text and its list items, sorted: FontBakery lists
    items in an order that follows Python's hash function, which differs
    between Python versions."""
    text, items = [], set()
    for line in message.splitlines():
        line = " ".join(line.split()).replace(str(font), "<font>").replace(font.name, "<font>")
        if line.startswith(("- ", "* ", "|")):
            items.add(line.lstrip("-* "))
        elif line:
            text.append(line)
    return " ".join(text), sorted(items)


def fontbakery(font: Path) -> Tuple[Report, List[str]]:
    """Every FAIL and WARN of the universal profile, and every check that
    crashed (ERROR or FATAL), which is never recorded."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        run = subprocess.run([sys.executable, "-m", "fontbakery", "check-universal", "--skip-network",
                              "--full-lists", "--json", str(report), str(font)], capture_output=True, text=True)
        if not report.exists():
            raise SystemExit(f"FontBakery did not run:\n{run.stdout}{run.stderr}")
        sections = json.loads(report.read_text())["sections"]
    found: Report = {}
    crashed = []
    for section in sections:
        for check in section["checks"]:
            name = re.sub(r"^<FontBakeryCheck:(.*)>$", r"\1", check["key"][1])
            for log in check["logs"]:
                message = log.get("message") or {}
                text, items = canonical(str(message.get("message") or ""), font)
                if log["status"] in ("ERROR", "FATAL"):
                    crashed.append(f"{log['status']} {name}: {text[:300]}")
                elif log["status"] in ("FAIL", "WARN"):
                    found[(name, log["status"], message.get("code") or "", text)] = items
    return found, crashed


def differences(found: Report, known: Report) -> List[str]:
    """New problems, items added to or gone from known ones, and known
    problems no longer reported."""
    lines = []
    for key in sorted(found.keys() | known.keys()):
        check, status, code, text = key
        added = sorted(set(found.get(key, [])) - set(known.get(key, [])))
        removed = sorted(set(known.get(key, [])) - set(found.get(key, [])))
        if key not in known:
            reason = "" if check in ACCEPTED else " (no reason in ACCEPTED)"
            lines.append(f"new {status} {check} [{code}]{reason}: {text}")
        elif key not in found:
            lines.append(f"fixed {status} {check} [{code}]: {text}")
        elif added or removed:
            lines.append(f"changed {status} {check} [{code}]: {text}")
        lines += [f"  + {item}" for item in added] + [f"  - {item} (fixed)" for item in removed]
    return lines


def load() -> Report:
    if not KNOWN_FILE.exists():
        return {}
    return {(e["check"], e["status"], e["code"], e["text"]): e["items"] for e in json.loads(KNOWN_FILE.read_text())}


def save(found: Report) -> None:
    entries = [dict(check=c, status=s, code=k, text=t, items=found[(c, s, k, t)]) for c, s, k, t in sorted(found)]
    KNOWN_FILE.write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("font", type=Path)
    ap.add_argument("--update", action="store_true", help=f"record today's problems in {KNOWN_FILE.name}")
    args = ap.parse_args(argv)
    if not args.font.is_file():
        raise SystemExit(f"no font at {args.font}")
    found, crashed = fontbakery(args.font)
    for line in crashed:
        print(f"crashed: {line}")
    diff = differences(found, load())
    unexplained = sorted({key[0] for key in found} - set(ACCEPTED))
    if args.update:
        if crashed or unexplained:
            print("not recorded: " + ("checks crashed" if crashed else
                                      f"add a reason to ACCEPTED first for {', '.join(unexplained)}"))
            return 1
        print("\n".join(diff) if diff else "no differences")
        save(found)
        print(f"recorded {len(found)} problems in {KNOWN_FILE}")
        return 0
    if diff:
        print("\n".join(diff))
    for check in sorted({key[0] for key in found} & set(ACCEPTED)):
        print(f"known: {check} ({ACCEPTED[check]})")
    ok = not diff and not crashed
    print(f"FontBakery: {len(found)} known problems in {len({key[0] for key in found})} checks, nothing new"
          if ok else "FontBakery: differences from tools/qa-known.json (record intended ones with --update)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
