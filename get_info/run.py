#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets_client as gs  # noqa: E402
from urllib.parse import quote  # noqa: E402

FIELDS = (
    "spreadsheetId,spreadsheetUrl,properties(title,locale,timeZone),"
    "sheets.properties(sheetId,title,index,hidden,gridProperties(rowCount,columnCount,frozenRowCount)),"
    "namedRanges(name,range)"
)
MAX_HEADER_TABS = 30


def main(params: dict) -> dict:
    spreadsheet_id, _ = gs.spreadsheet_ref(params)
    meta = gs.sheets("GET", quote(spreadsheet_id, safe=""), params={"fields": FIELDS})
    tabs = [sheet["properties"] for sheet in meta.get("sheets", [])]
    titles = {tab["sheetId"]: tab["title"] for tab in tabs}

    # One request for every tab's first row, so the agent knows the columns.
    headers = {}
    if tabs:
        ranges = [f"{gs.quote_tab(tab['title'])}!1:1" for tab in tabs[:MAX_HEADER_TABS]]
        batch = gs.sheets("GET", f"{quote(spreadsheet_id, safe='')}/values:batchGet", params={"ranges": ranges})
        for tab, value_range in zip(tabs, batch.get("valueRanges", [])):
            headers[tab["sheetId"]] = (value_range.get("values") or [[]])[0]

    out_tabs = []
    for tab in tabs:
        grid = tab.get("gridProperties") or {}
        entry = {
            "title": tab["title"],
            "gid": tab["sheetId"],
            "rows": grid.get("rowCount"),
            "columns": grid.get("columnCount"),
            "header": headers.get(tab["sheetId"]),
        }
        if grid.get("frozenRowCount"):
            entry["frozen_rows"] = grid["frozenRowCount"]
        if tab.get("hidden"):
            entry["hidden"] = True
        out_tabs.append(entry)

    named = []
    for item in meta.get("namedRanges", []):
        grid = item.get("range") or {}
        named.append({"name": item.get("name"), "tab": titles.get(grid.get("sheetId", 0))})

    properties = meta.get("properties") or {}
    out = {
        "id": meta.get("spreadsheetId"),
        "title": properties.get("title"),
        "link": meta.get("spreadsheetUrl"),
        "locale": properties.get("locale"),
        "time_zone": properties.get("timeZone"),
        "tabs": out_tabs,
    }
    if named:
        out["named_ranges"] = named
    return out


if __name__ == "__main__":
    gs.run(main)
