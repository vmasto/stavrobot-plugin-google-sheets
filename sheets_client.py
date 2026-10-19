"""Shared Google Sheets API client for the plugin's tools."""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

PLUGIN_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PLUGIN_ROOT / "config.json"

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_URL = "https://www.googleapis.com/drive/v3"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
# Only for find: the Sheets API has no way to list spreadsheets.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
SCOPES = [SHEETS_SCOPE, DRIVE_SCOPE]
# Desktop OAuth clients accept a loopback redirect without registering it. Nothing
# listens there: the user copies the URL from the address bar instead.
REDIRECT_URI = "http://127.0.0.1"

# The plugin-runner kills a tool after 30 seconds, so give up a bit earlier
# with a readable error instead.
DEADLINE_SECONDS = 25
TIMEOUT = 15
MAX_WRITE_ROWS = 5000

SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
RENDER_OPTIONS = {
    "formatted": "FORMATTED_VALUE",
    "unformatted": "UNFORMATTED_VALUE",
    "formula": "FORMULA",
}
INPUT_OPTIONS = {"user_entered": "USER_ENTERED", "raw": "RAW"}

_started = time.monotonic()
session = requests.Session()


class ToolError(Exception):
    pass


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except FileNotFoundError:
        return {}
    except ValueError:
        raise ToolError("config.json is not valid JSON.")


def save_config(updates: dict) -> None:
    # Read again right before writing so keys set elsewhere, like permissions, survive.
    config = load_config()
    config.update(updates)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def client_credentials(config: dict) -> tuple[str, str]:
    client_id = str(config.get("client_id") or "").strip()
    client_secret = str(config.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ToolError("Set client_id and client_secret from your Google Cloud OAuth client first.")
    return client_id, client_secret


def send(method: str, url: str, **kwargs) -> requests.Response:
    remaining = DEADLINE_SECONDS - (time.monotonic() - _started)
    if remaining < 1:
        raise ToolError("Ran out of time talking to Google Sheets, try a smaller range.")
    try:
        return session.request(method, url, timeout=min(TIMEOUT, remaining), **kwargs)
    except requests.Timeout:
        raise ToolError("Google Sheets did not respond in time.")
    except requests.RequestException as error:
        raise ToolError(f"Network error talking to Google Sheets ({type(error).__name__}).")


def token_error(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    return body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"


_token = None


def access_token() -> str:
    global _token
    if _token:
        return _token
    config = load_config()
    client_id, client_secret = client_credentials(config)
    refresh_token = str(config.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ToolError("Google Sheets is not connected yet. Run auth_url, then auth_complete.")
    response = send(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    if not response.ok:
        reason = token_error(response)
        hint = ""
        if "invalid_grant" in reason or "expired" in reason.lower():
            hint = (
                " Tokens from an OAuth app in Testing status expire after 7 days, publish the app to production first."
            )
        raise ToolError(f"Google refused the refresh token ({reason}).{hint} Run auth_url and auth_complete again.")
    _token = response.json()["access_token"]
    return _token


def api_error(response: requests.Response, service: str = "Google Sheets") -> ToolError:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    message = error.get("message") or response.text.strip()[:300]
    status = error.get("status") or ""
    reasons = {item.get("reason") for item in error.get("errors") or [] if isinstance(item, dict)}

    if response.status_code == 401:
        return ToolError("Google rejected the access token. Run auth_url and auth_complete again.")
    if "SERVICE_DISABLED" in message or "has not been used in project" in message or "accessNotConfigured" in reasons:
        return ToolError(f"The {service} API is off in your Google Cloud project. Enable it, then retry.")
    if response.status_code == 403 and ("insufficient" in message.lower() or "insufficientPermissions" in reasons):
        return ToolError("The token is missing a scope. Run auth_url and auth_complete again, and tick every box.")
    if response.status_code == 429 or status == "RESOURCE_EXHAUSTED":
        return ToolError("Google Sheets is rate limiting, retry in a minute.")
    if "not supported for this document" in message:
        return ToolError(
            "That file is an Excel file in Drive, not a Google Sheet. Open it in Drive and use "
            "File > Save as Google Sheets, then use the new file's id."
        )
    if response.status_code == 403:
        return ToolError("No access to that spreadsheet. It may be someone else's and not shared with the user.")
    if response.status_code == 404:
        return ToolError("Not found. Check the spreadsheet id, it may be deleted.")
    return ToolError(f"{service} API error {response.status_code}: {message}")


def request(method: str, url: str, params=None, body=None, service: str = "Google Sheets") -> dict:
    response = send(method, url, headers={"Authorization": f"Bearer {access_token()}"}, params=params, json=body)
    if not response.ok:
        raise api_error(response, service)
    return response.json() if response.content else {}


def sheets(method: str, path: str, params=None, body=None) -> dict:
    return request(method, f"{SHEETS_URL}/{path}" if path else SHEETS_URL, params, body)


def drive(path: str, params: dict) -> dict:
    return request("GET", f"{DRIVE_URL}/{path}", params, service="Google Drive")


SPREADSHEET_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
GID = re.compile(r"[#?&]gid=(\d+)")


def spreadsheet_ref(params: dict) -> tuple[str, int | None]:
    """Return the spreadsheet id, and the tab id if a pasted URL named one."""
    value = text_param(params, "spreadsheet")
    match = SPREADSHEET_URL.search(value)
    if match:
        gid = GID.search(value)
        return match.group(1), int(gid.group(1)) if gid else None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ToolError("spreadsheet must be a spreadsheet id or a docs.google.com/spreadsheets URL.")
    return value, None


def tabs(spreadsheet_id: str) -> list[dict]:
    meta = sheets("GET", quote(spreadsheet_id, safe=""), params={"fields": "sheets.properties(sheetId,title,index)"})
    return [sheet["properties"] for sheet in meta.get("sheets", [])]


def tab_title(spreadsheet_id: str, sheet: str | None, gid: int | None) -> str:
    """The tab to use: the one named, else the one in the URL, else the first."""
    if sheet:
        return sheet
    found = tabs(spreadsheet_id)
    if gid is not None:
        for tab in found:
            if tab.get("sheetId") == gid:
                return tab["title"]
    if not found:
        raise ToolError("The spreadsheet has no tabs.")
    return min(found, key=lambda tab: tab.get("index", 0))["title"]


def quote_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


A1_CELLS = re.compile(r"^([A-Za-z]{0,3})(\d*)(?::([A-Za-z]{0,3})(\d*))?$")


class Target:
    """Where a tool reads or writes: a tab, and optionally cells or a named range in it."""

    def __init__(self, spreadsheet_id: str, gid: int | None, sheet: str | None, cells: str | None):
        self.spreadsheet_id = spreadsheet_id
        self.tab = None  # quoted tab, e.g. 'Expenses 2026'
        self.cells = cells
        if cells and "!" in cells:
            tab, _, self.cells = cells.rpartition("!")
            self.tab = tab if tab.startswith("'") else quote_tab(tab)
        elif cells and not A1_CELLS.match(cells) and not sheet:
            pass  # a named range, which already knows its tab
        else:
            self.tab = quote_tab(tab_title(spreadsheet_id, sheet, gid))

    @property
    def range(self) -> str:
        if self.tab and self.cells:
            return f"{self.tab}!{self.cells}"
        return self.tab or self.cells

    @property
    def start(self) -> tuple[str, int]:
        """The start column and row, like ("B", 5) for B5:D9. Defaults to A and 1."""
        match = A1_CELLS.match(self.cells or "")
        if not match:
            return "A", 1
        return (match.group(1) or "A").upper(), int(match.group(2) or 1)


def value_range_path(spreadsheet_id: str, range_: str, suffix: str = "") -> str:
    return f"{quote(spreadsheet_id, safe='')}/values/{quote(range_, safe='')}{suffix}"


def link(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def header_row(target: Target) -> list[str]:
    if not target.tab:
        raise ToolError("Object rows need a tab with a header row, pass sheet.")
    path = value_range_path(target.spreadsheet_id, f"{target.tab}!1:1")
    values = sheets("GET", path).get("values") or [[]]
    return [str(cell) for cell in values[0]]


def rows_param(params: dict, target: Target | None = None) -> list[list]:
    """Rows as lists of cells, or as objects keyed by the tab's header row."""
    rows = params.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ToolError("rows is required: a list of rows, each a list of cell values or an object.")
    if not any(isinstance(row, (list, dict)) for row in rows):
        rows = [rows]  # a single row passed flat
    if len(rows) > MAX_WRITE_ROWS:
        raise ToolError(f"At most {MAX_WRITE_ROWS} rows at once.")
    if any(isinstance(row, dict) for row in rows):
        if target is None:
            raise ToolError("Pass rows as lists of cell values here, there is no header row yet.")
        if target.start[0] != "A":
            raise ToolError("Object rows fill columns from A, so range must start in column A. Use list rows instead.")
        headers = header_row(target)
        columns = {name.strip().lower(): index for index, name in enumerate(headers) if name.strip()}
        converted = []
        for row in rows:
            if not isinstance(row, dict):
                raise ToolError("Don't mix object rows and list rows.")
            cells = [None] * len(headers)
            for key, value in row.items():
                index = columns.get(str(key).strip().lower())
                if index is None:
                    raise ToolError(f"No column named {key!r}. The header row is: {headers}")
                cells[index] = value
            while cells and cells[-1] is None:
                cells.pop()
            converted.append(cells)
        rows = converted
    for row in rows:
        if not isinstance(row, list):
            raise ToolError("Each row must be a list of cell values or an object.")
        for cell in row:
            if isinstance(cell, (list, dict)):
                raise ToolError("Cell values must be text, numbers, booleans or null.")
    return [["" if cell is None else cell for cell in row] for row in rows]


def input_option(params: dict) -> str:
    value = text_param(params, "input", required=False) or "user_entered"
    if value not in INPUT_OPTIONS:
        raise ToolError(f"input must be one of: {', '.join(INPUT_OPTIONS)}.")
    return INPUT_OPTIONS[value]


def int_param(params: dict, name: str, default: int, low: int, high: int) -> int:
    value = params.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{name} must be a whole number.")
    return max(low, min(high, value))


def text_param(params: dict, name: str, required: bool = True) -> str | None:
    value = params.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolError(f"{name} is required.")
        return None
    if not isinstance(value, str):
        raise ToolError(f"{name} must be a string.")
    return value.strip()


def run(main) -> None:
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
        if not isinstance(params, dict):
            raise ToolError("Input must be a JSON object.")
        result = main(params)
    except ToolError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print("Input is not valid JSON.", file=sys.stderr)
        sys.exit(1)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
