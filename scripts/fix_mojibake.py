#!/usr/bin/env python3
"""Repair common UTF-8 text decoded as Windows-1252."""

import argparse
from pathlib import Path

MARKERS = (chr(0xC3), chr(0xE2), chr(0xC2), chr(0xF0), chr(0x178), chr(0xFFFD))
PATTERNS = (
    "templates/**/*.html",
    "static/**/*.css",
    "app/**/*.py",
    "tests/**/*.py",
    "README.md",
    ".vscode/settings.json",
)


def marker_count(text):
    return sum(text.count(marker) for marker in MARKERS)


def files(root):
    found = []
    for pattern in PATTERNS:
        found.extend(root.glob(pattern))
    return sorted(set(found))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    repaired = []
    unchanged = []
    manual = []
    for path in files(root):
        text = path.read_text(encoding="utf-8")
        before = marker_count(text)
        if not before:
            continue
        try:
            candidate = text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            manual.append(path.relative_to(root))
            continue
        after = marker_count(candidate)
        if after < before:
            repaired.append((path.relative_to(root), before, after))
            if not args.dry_run:
                path.write_text(candidate, encoding="utf-8", newline="")
        else:
            unchanged.append(path.relative_to(root))
    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"{mode}: repairable={len(repaired)} manual_fix_needed={len(manual)} unchanged={len(unchanged)}")
    for path, before, after in repaired:
        print(f"  repairable {path}: {before} -> {after}")
    for path in manual:
        print(f"  manual fix needed {path}")
    for path in unchanged:
        print(f"  unchanged {path}")


if __name__ == "__main__":
    main()
