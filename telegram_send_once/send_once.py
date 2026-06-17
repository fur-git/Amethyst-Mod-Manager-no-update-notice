#!/usr/bin/env python3
"""Send one Telegram message and exit."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_MESSAGE = "Health check failed and a bug was found and requires your attention"

def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    bot_token = _require("TELEGRAM_BOT_TOKEN")
    user_id = _require("TELEGRAM_USER_ID")
    message = (
        sys.argv[1].strip()
        if len(sys.argv) > 1 and sys.argv[1].strip()
        else os.environ.get("TELEGRAM_MESSAGE", DEFAULT_MESSAGE).strip() or DEFAULT_MESSAGE
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": user_id, "text": message}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                body = response.read().decode("utf-8")
                print(f"Telegram API returned {response.status}: {body}", file=sys.stderr)
                sys.exit(1)
    except urllib.error.HTTPError as exc:
        print(f"Telegram API error {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Network error: {exc.reason}", file=sys.stderr)
        sys.exit(1)

    print("Message sent.")
    sys.exit(0)


if __name__ == "__main__":
    main()
