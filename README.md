# Google Sheets plugin

Lets Stavrobot find, read, append to, overwrite, clear and create spreadsheets in your Google account.

## Before installing

You need your own Google Cloud OAuth client, it's free:

1. In https://console.cloud.google.com create a project and enable the Google Sheets API and the Google Drive API. `find` uses the Drive API to search spreadsheets by name. A project you already use for the Gmail, Calendar or Drive plugin works too.
2. Under Google Auth Platform, set up the consent screen as External. Then on Audience click Publish app. Apps left in Testing get refresh tokens that expire after 7 days, so you'd have to reconnect every week.
3. Under Clients, create an OAuth client of type Desktop app, or reuse one you already have in the same project.

The app stays unverified, which is fine for personal use. Google shows a warning when you connect and caps unverified apps at 100 users.

## Installation

Tell Stavrobot to install `https://github.com/vmasto/stavrobot-plugin-google-sheets`.

## Configuration

- `client_id` and `client_secret`: from the Desktop app client.
- `refresh_token`: leave it empty. Ask Stavrobot to connect Google Sheets and it sends you a link. Google warns the app is unverified, click Advanced and continue. Tick every box on the consent screen, or `find` won't work. After you allow access the browser shows an error page on `127.0.0.1`, that's expected. Copy the full address and send it back, the plugin saves the token itself.

The plugin asks for two scopes. `spreadsheets` reads and writes every spreadsheet you can open. `drive.metadata.readonly` lets `find` search spreadsheets by name, and it also lets the bot see the names and details of every other file in your Drive. It can't read their content.

`update` overwrites cells and `clear` empties them. To undo either, restore an earlier version in Sheets (File > Version history).

## Tools

- `auth_url`, `auth_complete`: connect your account.
- `find`: searches spreadsheets by name, newest first.
- `get_info`: returns the title, link, tabs with their size and header row, and named ranges.
- `read`: reads cells from a tab, formatted, unformatted or as formulas, 200 rows at a time by default.
- `append`: adds rows after the last row of a table. It accepts rows as objects keyed by header name, so the bot doesn't need the column order.
- `update`: overwrites cells from a starting cell.
- `clear`: empties a range, or a whole tab.
- `create`: creates a spreadsheet, optionally with a header row.
- `add_tab`: adds a tab, optionally with a header row.

Every tool takes a spreadsheet id or its URL. A URL with `#gid=` picks that tab.

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
