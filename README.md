# FootyScoresAPI

## Quick run (runs underlying scripts to quickly do what the task was about)

`./run.sh output.json` - download required files and generate output.json

## fetch_olympics_data.py

Purpose: Download OG2024 JSON dataset files from https://stacy.olympics.com/OG2024/data into a local `tmp/` folder for offline processing and validation.

### Notes

- This script requires `requests` (install with `pip install requests`).

### Quick examples

- Download the canonical event file by specifying `--comp`, `--event`, and `--lang` (the script always targets `GLO_EventGames`, and writes to `tmp/`):
  ./fetch_olympics_data.py --comp OG2024 --event FBLMTEAM11 --lang ENG --insecure

- Note: only `--comp`, `--event`, `--lang`, and `--insecure` are supported. You can pass `--event FBLMTEAM11`. The script constructs `GLO_EventGames~comp=...~event=...~lang=....json` and downloads it to `tmp/.`

- After downloading the main event file, the script will parse it and attempt to discover and download related resources. It downloads only the minimal files required by `assemble_api_response.py` (the `RES_ByRSC_H2H` files for each unit).

#### Options

- `--insecure` — skip SSL certificate verification (useful when testing behind TLS interceptors)
- `--base-url` — change base URL if a mirror is needed
- `--force` — overwrite existing files
- `--concurrency` — number of concurrent downloads (default 4)

## assemble_api_response.py

Purpose: Build a single JSON response (default `api-response.json`) from downloaded files in `tmp/` and write an endpoint-shaped payload (key is a placeholder endpoint URL containing `comp`, `event`, `unit`, and `lang` parameters).

### Usage:

- `./assemble_api_response.py --comp OG2024 --event FBLMTEAM11 --lang ENG --tmp tmp --out api-response.json`
- The assembler generates an endpoint for every unit in the event by default (one endpoint entry per unit), e.g. for group matches, quarters, semis, finals, etc. No additional flags are necessary.

#### Template behavior

- The assembler uses an internal default template for the endpoint body and no external template file is required.

#### Endpoint key format

- The top-level key for each endpoint now uses a path-style URL, for example:

  `/api/scores/OG2024/FBLMTEAM11/FNL-000100?lang=ENG`

  where the segments are `/api/scores/{comp}/{event}/{unit}?lang={lang}`.

