#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402


def main(params: dict) -> dict:
    title = gs.text_param(params, "title")
    tabs = params.get("tabs") or ["Sheet1"]
    if not isinstance(tabs, list) or not all(isinstance(tab, str) and tab.strip() for tab in tabs):
        raise gs.ToolError("tabs must be a list of tab names.")
    rows = params.get("rows")
    if rows is not None:
        rows = gs.rows_param({"rows": rows})
    body = {
        "properties": {"title": title},
        "sheets": [{"properties": {"title": tab.strip()}} for tab in tabs],
    }
    created = gs.sheets("POST", "", body=body)
    spreadsheet_id = created["spreadsheetId"]
    if rows:
        first = gs.quote_tab(tabs[0].strip())
        gs.sheets(
            "PUT",
            gs.value_range_path(spreadsheet_id, f"{first}!A1"),
            params={"valueInputOption": "USER_ENTERED"},
            body={"values": rows},
        )
    return {"id": spreadsheet_id, "title": title, "link": created.get("spreadsheetUrl") or gs.link(spreadsheet_id)}


if __name__ == "__main__":
    gs.run(main)
