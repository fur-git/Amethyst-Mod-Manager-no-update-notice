#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "# (forked: startup app-update auto-check disabled)"

PATCH_TARGETS = (
    (
        ROOT / "src" / "gui_qt" / "app.py",
        re.compile(
            r"^(?P<indent>\s*)QTimer\.singleShot\(\s*2000\s*,\s*self\._check_for_app_update\s*\)\s*$",
            re.M,
        ),
    ),
    (
        ROOT / "src" / "gui.py",
        re.compile(
            r"^(?P<indent>\s*)self\.after\(\s*2000\s*,\s*self\._check_for_app_update\s*\)\s*$",
            re.M,
        ),
    ),
)


def main() -> int:
    for path, pattern in PATCH_TARGETS:
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            print(f"No-update-notice patch already applied in {path.relative_to(ROOT)}.")
            return 0

        def _repl(m: re.Match[str]) -> str:
            return f"{m.group('indent')}{MARKER}\n"

        new_text, n = pattern.subn(_repl, text, count=1)
        if n != 1:
            print(
                f"ERROR: could not find the startup update check line to patch in {path.relative_to(ROOT)}",
                file=sys.stderr,
            )
            return 1

        path.write_text(new_text, encoding="utf-8")
        print(f"Applied no-update-notice patch in {path.relative_to(ROOT)}.")
        return 0

    print(
        "ERROR: no GUI entry file found to patch (expected src/gui_qt/app.py or src/gui.py)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
