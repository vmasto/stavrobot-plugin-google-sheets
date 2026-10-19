"""Offline tests against a fake Google Sheets.

Run with: uv run --with pytest --with requests pytest tests
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sheets_client as gs  # noqa: E402

SID = "1AbC_d-9"
URL = f"https://docs.google.com/spreadsheets/d/{SID}/edit#gid=77"
TABS = {
    "sheets": [
        {"properties": {"sheetId": 0, "title": "Log", "index": 0}},
        {"properties": {"sheetId": 77, "title": "Bob's tab", "index": 1}},
    ]
}


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def values_path(range_, suffix=""):
    return f"{SID}/values/{quote(range_, safe='')}{suffix}"


@pytest.fixture
def fake(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"client_id": "cid", "client_secret": "sec", "refresh_token": "rt", "permissions": ["*"]})
    )
    monkeypatch.setattr(gs, "CONFIG_PATH", config)
    monkeypatch.setattr(gs, "_token", None)

    calls, routes = [], {("GET", SID): Response(200, TABS)}

    def request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        assert 0 < kwargs["timeout"] <= gs.TIMEOUT
        if url == gs.TOKEN_URL:
            if kwargs["data"]["grant_type"] == "refresh_token":
                return Response(200, {"access_token": "at"})
            return routes[("POST", "token")]
        if url.startswith(gs.DRIVE_URL):
            path = "drive/" + url.removeprefix(gs.DRIVE_URL + "/")
        else:
            path = url.removeprefix(gs.SHEETS_URL).removeprefix("/")
        handler = routes[(method, path)]
        return handler(kwargs) if callable(handler) else handler

    monkeypatch.setattr(gs.session, "request", request)
    return type("Fake", (), {"routes": routes, "calls": calls, "config": config})


def tool(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}", ROOT / name / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def last(fake, method, path):
    return [call for call in fake.calls if call["method"] == method and call["url"].endswith(path)][-1]


def test_auth_url_requests_both_scopes_offline(fake):
    url = tool("auth_url")({})["url"]
    for part in (
        "client_id=cid",
        "access_type=offline",
        "prompt=consent",
        "auth%2Fspreadsheets+",
        "drive.metadata.readonly",
        "127.0.0.1",
    ):
        assert part in url


def test_auth_complete_saves_token_and_keeps_permissions(fake):
    scopes = " ".join(gs.SCOPES)
    fake.routes[("POST", "token")] = Response(200, {"refresh_token": "new", "access_token": "fresh", "scope": scopes})
    fake.routes[("GET", "drive/about")] = Response(200, {"user": {"emailAddress": "me@gmail.com"}})
    out = tool("auth_complete")({"url": "http://127.0.0.1/?code=4/abc&scope=x"})
    assert out == {"connected": True, "email": "me@gmail.com"}
    saved = json.loads(fake.config.read_text())
    assert saved["refresh_token"] == "new" and saved["permissions"] == ["*"]

    fake.routes[("POST", "token")] = Response(
        200, {"refresh_token": "x", "access_token": "x", "scope": gs.SHEETS_SCOPE}
    )
    assert "find won't work" in tool("auth_complete")({"url": "abc"})["warning"]

    fake.routes[("POST", "token")] = Response(200, {"refresh_token": "x", "access_token": "x", "scope": gs.DRIVE_SCOPE})
    with pytest.raises(gs.ToolError, match="not granted"):
        tool("auth_complete")({"url": "abc"})


def test_expired_refresh_token_explains_testing_mode(fake, monkeypatch):
    monkeypatch.setattr(gs.session, "request", lambda *args, **kwargs: Response(400, {"error": "invalid_grant"}))
    with pytest.raises(gs.ToolError, match="7 days"):
        tool("find")({})


def test_spreadsheet_accepts_ids_and_urls():
    assert gs.spreadsheet_ref({"spreadsheet": SID}) == (SID, None)
    assert gs.spreadsheet_ref({"spreadsheet": URL}) == (SID, 77)
    with pytest.raises(gs.ToolError, match="spreadsheet must be"):
        gs.spreadsheet_ref({"spreadsheet": "my budget"})


def test_find_lists_spreadsheets_by_name(fake):
    fake.routes[("GET", "drive/files")] = Response(
        200,
        {
            "files": [
                {
                    "id": SID,
                    "name": "Budget",
                    "modifiedTime": "t",
                    "webViewLink": "l",
                    "owners": [{"emailAddress": "me@x"}],
                }
            ],
            "nextPageToken": "p2",
        },
    )
    out = tool("find")({"text": "Bob's"})
    assert out == {
        "spreadsheets": [{"id": SID, "name": "Budget", "modified": "t", "owner": "me@x", "link": "l"}],
        "next_page_token": "p2",
    }
    query = last(fake, "GET", "files")["params"]["q"]
    assert "spreadsheet'" in query and "name contains 'Bob\\'s'" in query


def test_get_info_returns_tabs_with_headers(fake):
    fake.routes[("GET", SID)] = Response(
        200,
        {
            "spreadsheetId": SID,
            "spreadsheetUrl": "https://docs.google.com/x",
            "properties": {"title": "Budget", "locale": "el_GR", "timeZone": "Europe/Athens"},
            "sheets": [
                {
                    "properties": {
                        "sheetId": 0,
                        "title": "Log",
                        "index": 0,
                        "gridProperties": {"rowCount": 1000, "columnCount": 6, "frozenRowCount": 1},
                    }
                },
                {
                    "properties": {
                        "sheetId": 77,
                        "title": "Bob's tab",
                        "index": 1,
                        "hidden": True,
                        "gridProperties": {"rowCount": 10, "columnCount": 2},
                    }
                },
            ],
            "namedRanges": [{"name": "Total", "range": {"sheetId": 77}}],
        },
    )
    fake.routes[("GET", f"{SID}/values:batchGet")] = Response(
        200, {"valueRanges": [{"values": [["Date", "Amount"]]}, {}]}
    )
    out = tool("get_info")({"spreadsheet": URL})
    assert out["title"] == "Budget" and out["time_zone"] == "Europe/Athens"
    assert out["tabs"][0] == {
        "title": "Log",
        "gid": 0,
        "rows": 1000,
        "columns": 6,
        "header": ["Date", "Amount"],
        "frozen_rows": 1,
    }
    assert out["tabs"][1]["header"] == [] and out["tabs"][1]["hidden"] is True
    assert out["named_ranges"] == [{"name": "Total", "tab": "Bob's tab"}]
    assert last(fake, "GET", "values:batchGet")["params"]["ranges"] == ["'Log'!1:1", "'Bob''s tab'!1:1"]


def test_read_uses_the_url_tab_and_pages(fake):
    fake.routes[("GET", values_path("'Bob''s tab'"))] = Response(
        200, {"range": "'Bob''s tab'!A1:C1000", "values": [["a"], ["b"], ["c"]]}
    )
    out = tool("read")({"spreadsheet": URL, "max_rows": 2})
    assert out == {
        "range": "'Bob''s tab'!A1:C1000",
        "first_row": 1,
        "rows": [["a"], ["b"]],
        "next_range": "'Bob''s tab'!A3:C1000",
        "more_rows": 1,
    }
    params = last(fake, "GET", values_path("'Bob''s tab'"))["params"]
    assert params["valueRenderOption"] == "FORMATTED_VALUE"


def test_read_ranges_tabs_and_named_ranges(fake):
    fake.routes[("GET", values_path("'Log'!B5:C9"))] = Response(200, {"range": "Log!B5:C9", "values": [[1, 2]]})
    out = tool("read")({"spreadsheet": SID, "range": "B5:C9", "render": "unformatted"})
    assert out["first_row"] == 5 and out["rows"] == [[1, 2]] and "next_range" not in out

    fake.routes[("GET", values_path("'Expenses 2026'!A:D"))] = Response(200, {"range": "'Expenses 2026'!A1:D3"})
    assert tool("read")({"spreadsheet": SID, "range": "Expenses 2026!A:D"})["rows"] == []

    fake.routes[("GET", values_path("Total"))] = Response(200, {"range": "Log!F2", "values": [["€10"]]})
    assert tool("read")({"spreadsheet": SID, "range": "Total"})["rows"] == [["€10"]]

    with pytest.raises(gs.ToolError, match="render must be"):
        tool("read")({"spreadsheet": SID, "render": "pretty"})


def test_append_maps_object_rows_to_the_header(fake):
    fake.routes[("GET", values_path("'Log'!1:1"))] = Response(200, {"values": [["Date", "Vendor", "Amount", "Note"]]})
    fake.routes[("POST", values_path("'Log'", ":append"))] = Response(
        200, {"updates": {"updatedRange": "Log!A10:C11", "updatedRows": 2}}
    )
    out = tool("append")(
        {"spreadsheet": SID, "rows": [{"date": "2026-10-19", "Amount": 12.5}, {"Vendor": "ΔΕΗ", "note": None}]}
    )
    assert out["rows_added"] == 2 and out["updated_range"] == "Log!A10:C11"
    call = last(fake, "POST", ":append")
    assert call["json"] == {"values": [["2026-10-19", "", 12.5], ["", "ΔΕΗ"]]}
    assert call["params"] == {"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}

    with pytest.raises(gs.ToolError, match="No column named 'Total'"):
        tool("append")({"spreadsheet": SID, "rows": [{"Total": 1}]})


def test_append_accepts_a_flat_row_and_raw_input(fake):
    fake.routes[("POST", values_path("'Log'", ":append"))] = Response(200, {"updates": {"updatedRows": 1}})
    tool("append")({"spreadsheet": SID, "rows": ["=1+1", 3], "input": "raw"})
    call = last(fake, "POST", ":append")
    assert call["json"] == {"values": [["=1+1", 3]]} and call["params"]["valueInputOption"] == "RAW"
    with pytest.raises(gs.ToolError, match="Cell values"):
        tool("append")({"spreadsheet": SID, "rows": [[["nested"]]]})


def test_update_writes_and_refuses_misaligned_objects(fake):
    fake.routes[("PUT", values_path("'Log'!B5"))] = Response(200, {"updatedRange": "Log!B5:C5", "updatedCells": 2})
    out = tool("update")({"spreadsheet": SID, "range": "B5", "rows": [["x", "y"]]})
    assert out["cells_updated"] == 2
    with pytest.raises(gs.ToolError, match="column A"):
        tool("update")({"spreadsheet": SID, "range": "B5", "rows": [{"Date": "x"}]})
    with pytest.raises(gs.ToolError, match="range is required"):
        tool("update")({"spreadsheet": SID, "rows": [["x"]]})


def test_clear_needs_a_range_or_all_cells(fake):
    with pytest.raises(gs.ToolError, match="all_cells"):
        tool("clear")({"spreadsheet": SID})
    fake.routes[("POST", values_path("'Log'", ":clear"))] = Response(200, {"clearedRange": "Log!A1:Z1000"})
    assert tool("clear")({"spreadsheet": SID, "all_cells": True})["cleared_range"] == "Log!A1:Z1000"


def test_create_with_tabs_and_header(fake):
    fake.routes[("POST", "")] = Response(
        200, {"spreadsheetId": "new1", "spreadsheetUrl": "https://docs.google.com/new1"}
    )
    fake.routes[("PUT", f"new1/values/{quote(chr(39) + 'Costs' + chr(39) + '!A1', safe='')}")] = Response(200, {})
    out = tool("create")({"title": "Trip", "tabs": ["Costs", "People"], "rows": [["Item", "€"]]})
    assert out == {"id": "new1", "title": "Trip", "link": "https://docs.google.com/new1"}
    assert last(fake, "POST", gs.SHEETS_URL)["json"]["sheets"][1] == {"properties": {"title": "People"}}
    assert last(fake, "PUT", "A1")["json"] == {"values": [["Item", "€"]]}
    with pytest.raises(gs.ToolError, match="no header row yet"):
        tool("create")({"title": "Trip", "rows": [{"Item": 1}]})


def test_add_tab(fake):
    fake.routes[("POST", f"{SID}:batchUpdate")] = Response(
        200, {"replies": [{"addSheet": {"properties": {"sheetId": 9, "title": "2027"}}}]}
    )
    out = tool("add_tab")({"spreadsheet": SID, "title": "2027"})
    assert out["gid"] == 9 and out["link"].endswith("#gid=9")


def test_api_errors_explain_the_fix(fake):
    def error(status, message, state=""):
        return Response(status, {"error": {"code": status, "message": message, "status": state}})

    path = values_path("'Log'!A1")
    cases = [
        (error(403, "Google Sheets API has not been used in project 1 before or it is disabled."), "Enable it"),
        (error(403, "Request had insufficient authentication scopes.", "PERMISSION_DENIED"), "missing a scope"),
        (error(403, "The caller does not have permission", "PERMISSION_DENIED"), "not shared"),
        (error(400, "This operation is not supported for this document"), "Save as Google Sheets"),
        (error(404, "Requested entity was not found.", "NOT_FOUND"), "Not found"),
        (error(429, "Quota exceeded", "RESOURCE_EXHAUSTED"), "rate limiting"),
    ]
    for response, expected in cases:
        fake.routes[("GET", path)] = response
        with pytest.raises(gs.ToolError, match=expected):
            tool("read")({"spreadsheet": SID, "range": "A1"})


def test_errors_exit_non_zero_with_stderr(tmp_path):
    # No config.json next to the copied tool, so it must fail before any network call.
    plugin = tmp_path / "google-sheets"
    (plugin / "find").mkdir(parents=True)
    (plugin / "sheets_client.py").write_text((ROOT / "sheets_client.py").read_text())
    (plugin / "find" / "run.py").write_text((ROOT / "find" / "run.py").read_text())
    result = subprocess.run(
        [sys.executable, str(plugin / "find" / "run.py")],
        input="{}",
        capture_output=True,
        text=True,
        cwd=plugin / "find",
    )
    assert result.returncode == 1 and result.stdout == ""
    assert "client_id" in result.stderr


def test_run_scripts_are_executable_in_git():
    output = subprocess.run(
        ["git", "ls-files", "-s", "--", "*/run.py"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    entries = [line.split(maxsplit=3) for line in output.splitlines()]
    if not entries:
        pytest.skip("run.py files are not in the git index yet")
    assert all(mode == "100755" for mode, *_ in entries), entries
