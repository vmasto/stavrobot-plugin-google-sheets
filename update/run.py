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
    target = gs.Target(
        spreadsheet_id, gid, gs.text_param(params, "sheet", required=False), gs.text_param(params, "range")
    )
    rows = gs.rows_param(params, target)
    result = gs.sheets(
        "PUT",
        gs.value_range_path(spreadsheet_id, target.range),
        params={"valueInputOption": gs.input_option(params)},
        body={"values": rows},
    )
    return {
        "updated_range": result.get("updatedRange"),
        "cells_updated": result.get("updatedCells", 0),
        "link": gs.link(spreadsheet_id),
    }


if __name__ == "__main__":
    gs.run(main)
