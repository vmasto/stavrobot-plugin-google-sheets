#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


def main(params: dict) -> dict:
    value = gs.text_param(params, "url")
    if value.startswith("http"):
        query = parse_qs(urlparse(value).query)
        if "error" in query:
            raise gs.ToolError(f"Google returned an error: {query['error'][0]}. Run auth_url again.")
        if "code" not in query:
            raise gs.ToolError("That address has no code in it. Copy the full address after allowing access.")
        code = query["code"][0]
    else:
        code = value

    client_id, client_secret = gs.client_credentials(gs.load_config())
    response = gs.send(
        "POST",
        gs.TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": gs.REDIRECT_URI,
        },
    )
    if not response.ok:
        raise gs.ToolError(
            f"Google refused the code ({gs.token_error(response)}). Codes work once and expire fast, run auth_url again."
        )
    body = response.json()
    granted = body.get("scope", "").split()
    if gs.SHEETS_SCOPE not in granted:
        raise gs.ToolError("Access to Sheets was not granted. Run auth_url again and tick every box.")
    if not body.get("refresh_token"):
        raise gs.ToolError("Google returned no refresh token, run auth_url again.")
    gs.save_config({"refresh_token": body["refresh_token"]})
    gs._token = body["access_token"]
    if gs.DRIVE_SCOPE not in granted:
        return {
            "connected": True,
            "warning": "Drive file listing was not granted, so find won't work. Run auth_url again to fix it.",
        }
    user = gs.drive("about", {"fields": "user(emailAddress)"}).get("user") or {}
    return {"connected": True, "email": user.get("emailAddress")}


if __name__ == "__main__":
    gs.run(main)
