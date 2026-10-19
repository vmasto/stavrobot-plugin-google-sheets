#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402
from urllib.parse import urlencode  # noqa: E402


def main(params: dict) -> dict:
    client_id, _ = gs.client_credentials(gs.load_config())
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": gs.REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(gs.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return {
        "url": f"{gs.AUTHORIZE_URL}?{query}",
        "next": "Open the URL and allow access, ticking every box. The browser then fails to load a 127.0.0.1 "
        "page. Copy that page's full address and pass it to auth_complete.",
    }


if __name__ == "__main__":
    gs.run(main)
