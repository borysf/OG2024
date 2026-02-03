# scripts/ - helper scripts

fetch_olympics_data.py

Purpose: Download OG2024 JSON dataset files from https://stacy.olympics.com/OG2024/data into a local `tmp/` folder for offline processing and validation.

Quick examples

- Download the canonical event file by specifying `--comp`, `--event`, and `--lang` (the script always targets `GLO_EventGames`, and writes to `tmp/`):
  ./scripts/fetch_olympics_data.py --comp OG2024 --event FBLMTEAM11 --lang ENG --insecure

- Note: only `--comp`, `--event`, `--lang`, and `--insecure` are supported. You can pass `--event FBLMTEAM11` (the trailing `------------` will be added automatically to form `FBLMTEAM11------------`). The script constructs `GLO_EventGames~comp=...~event=...~lang=....json` and downloads it to `tmp/.`

- After downloading the main event file, the script will parse it and attempt to discover and download related resources. By default it downloads only the minimal files required by `assemble_api_response.py` (the `RES_ByRSC_H2H` files for each unit).

- If you previously saw HTTP 403 (Forbidden) errors, the downloader now sends a browser-like `User-Agent` and `Referer` header to reduce false positives from servers that block non-browser clients.

Options

- `--insecure` — skip SSL certificate verification (useful when testing behind TLS interceptors)
- `--base-url` — change base URL if a mirror is needed
- `--force` — overwrite existing files
- `--concurrency` — number of concurrent downloads (default 4)

Additional script: `assemble_api_response.py`

Purpose: Build a single JSON response (default `example.json`) from downloaded files in `tmp/` and write an endpoint-shaped payload (key is a placeholder endpoint URL containing `comp`, `event`, `unit`, and `lang` parameters). Uses `endpoint-template.json` as the response template by default.

Usage:

- `./scripts/assemble_api_response.py --comp OG2024 --event FBLMTEAM11 --lang ENG --tmp tmp --template endpoint-template.json --out example.json`
- The assembler generates an endpoint for every unit in the event by default (one endpoint entry per unit), e.g. for group matches, quarters, semis, finals, etc. No additional flags are necessary.

Endpoint key format

- The top-level key for each endpoint now uses a path-style URL, for example:

  `/api/scores/OG2024/FBLMTEAM11/FNL-000100?lang=ENG`

  where the segments are `/api/scores/{comp}/{event}/{unit}?lang={lang}`.

Notes

- Filenames are normalized by removing trailing duplication suffixes like ` (1)` before `.json`.
- This script requires `requests` (install with `pip install requests`).
