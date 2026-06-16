#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / "src" / "gui.py"
MARKER = "# (forked: startup app-update auto-check disabled)"
UPDATE_LINE_RE = re.compile(
    r"^(?P<indent>\s*)self\.after\(\s*2000\s*,\s*self\._check_for_app_update\s*\)\s*$",
    re.M,
)


def main() -> int:
    text = GUI.read_text(encoding="utf-8")
    if MARKER in text:
        print("No-update-notice patch already applied.")
        return 0

    def _repl(m: re.Match[str]) -> str:
        return f"{m.group('indent')}{MARKER}\n"

    new_text, n = UPDATE_LINE_RE.subn(_repl, text, count=1)
    if n != 1:
        print(
            "ERROR: could not find the startup update check line to patch in src/gui.py",
            file=sys.stderr,
        )
        return 1

    GUI.write_text(new_text, encoding="utf-8")
    print("Applied no-update-notice patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
