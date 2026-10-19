#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402


def main(params: dict) -> dict:
    spreadsheet_id, gid = gs.spreadsheet_ref(params)
    target = gs.Target(spreadsheet_id, gid, gs.text_param(params, "sheet", required=False), None)
    rows = gs.rows_param(params, target)
    result = gs.sheets(
        "POST",
        gs.value_range_path(spreadsheet_id, target.range, ":append"),
        params={"valueInputOption": gs.input_option(params), "insertDataOption": "INSERT_ROWS"},
        body={"values": rows},
    )
    updates = result.get("updates") or {}
    return {
        "updated_range": updates.get("updatedRange"),
        "rows_added": updates.get("updatedRows", 0),
        "link": gs.link(spreadsheet_id),
    }


if __name__ == "__main__":
    gs.run(main)
