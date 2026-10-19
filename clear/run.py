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
    cells = gs.text_param(params, "range", required=False)
    if not cells and params.get("all_cells") is not True:
        raise gs.ToolError("range is required. To clear the whole tab, set all_cells to true.")
    target = gs.Target(spreadsheet_id, gid, gs.text_param(params, "sheet", required=False), cells)
    result = gs.sheets("POST", gs.value_range_path(spreadsheet_id, target.range, ":clear"), body={})
    return {"cleared_range": result.get("clearedRange"), "link": gs.link(spreadsheet_id)}


if __name__ == "__main__":
    gs.run(main)
