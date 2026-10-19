#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402
from urllib.parse import quote  # noqa: E402


def main(params: dict) -> dict:
    spreadsheet_id, _ = gs.spreadsheet_ref(params)
    title = gs.text_param(params, "title")
    rows = params.get("rows")
    if rows is not None:
        rows = gs.rows_param({"rows": rows})
    result = gs.sheets(
        "POST",
        f"{quote(spreadsheet_id, safe='')}:batchUpdate",
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    )
    properties = result["replies"][0]["addSheet"]["properties"]
    if rows:
        gs.sheets(
            "PUT",
            gs.value_range_path(spreadsheet_id, f"{gs.quote_tab(title)}!A1"),
            params={"valueInputOption": "USER_ENTERED"},
            body={"values": rows},
        )
    return {
        "title": properties["title"],
        "gid": properties["sheetId"],
        "link": f"{gs.link(spreadsheet_id)}#gid={properties['sheetId']}",
    }


if __name__ == "__main__":
    gs.run(main)
