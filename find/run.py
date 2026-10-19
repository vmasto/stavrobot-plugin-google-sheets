#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402


def main(params: dict) -> dict:
    clauses = [f"mimeType = '{gs.SPREADSHEET_MIME}'", "trashed = false"]
    text = gs.text_param(params, "text", required=False)
    if text:
        clauses.append("name contains '" + text.replace("\\", "\\\\").replace("'", "\\'") + "'")
    query = {
        "q": " and ".join(clauses),
        "orderBy": "modifiedTime desc",
        "pageSize": gs.int_param(params, "max_results", 20, 1, 50),
        "fields": "nextPageToken,files(id,name,modifiedTime,webViewLink,owners(emailAddress))",
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
    }
    page_token = gs.text_param(params, "page_token", required=False)
    if page_token:
        query["pageToken"] = page_token
    listing = gs.drive("files", query)
    out = {
        "spreadsheets": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "modified": item.get("modifiedTime"),
                "owner": ((item.get("owners") or [{}])[0]).get("emailAddress"),
                "link": item.get("webViewLink"),
            }
            for item in listing.get("files", [])
        ]
    }
    if listing.get("nextPageToken"):
        out["next_page_token"] = listing["nextPageToken"]
    return out


if __name__ == "__main__":
    gs.run(main)
