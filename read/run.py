#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402
import json  # noqa: E402

# Keep the result small enough for the agent's context.
MAX_CHARS = 60_000


def main(params: dict) -> dict:
    spreadsheet_id, gid = gs.spreadsheet_ref(params)
    render = gs.text_param(params, "render", required=False) or "formatted"
    if render not in gs.RENDER_OPTIONS:
        raise gs.ToolError(f"render must be one of: {', '.join(gs.RENDER_OPTIONS)}.")
    max_rows = gs.int_param(params, "max_rows", 200, 1, 1000)
    target = gs.Target(
        spreadsheet_id,
        gid,
        gs.text_param(params, "sheet", required=False),
        gs.text_param(params, "range", required=False),
    )
    result = gs.sheets(
        "GET",
        gs.value_range_path(spreadsheet_id, target.range),
        params={"valueRenderOption": gs.RENDER_OPTIONS[render], "dateTimeRenderOption": "FORMATTED_STRING"},
    )
    values = result.get("values") or []
    rows, size = [], 0
    for row in values[:max_rows]:
        size += len(json.dumps(row, ensure_ascii=False))
        if rows and size > MAX_CHARS:
            break
        rows.append(row)

    # The API answers with the range it actually read, e.g. 'Log'!A1:F120.
    returned = result.get("range") or target.range
    tab, _, cells = returned.rpartition("!")
    match = gs.A1_CELLS.match(cells)
    start_col = (match.group(1) if match else "") or "A"
    first_row = int(match.group(2)) if match and match.group(2) else 1
    end_col = match.group(3) if match else None
    out = {"range": returned, "first_row": first_row, "rows": rows}
    if len(rows) < len(values):
        next_row = first_row + len(rows)
        next_cells = f"{start_col}{next_row}:{end_col or start_col}{match.group(4) if match else ''}"
        out["next_range"] = f"{tab}!{next_cells}" if tab else next_cells
        out["more_rows"] = len(values) - len(rows)
    return out


if __name__ == "__main__":
    gs.run(main)
