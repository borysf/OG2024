#!/usr/bin/env python3
"""fetch_olympics_data.py

Downloads dataset JSON files from the OG2024 public data endpoint.

Features:
- Minimal CLI: specify `--comp`, `--event`, and `--lang`. Use `--insecure` to skip SSL verification.
- By default this script downloads the minimal set of files required by
  `scripts/assemble_api_response.py` (the main `GLO_EventGames` and
  `RES_ByRSC_H2H` files for each unit).
- Files are written to `tmp/` by default.

Usage examples:
  ./scripts/fetch_olympics_data.py --comp OG2024 --event FBLMTEAM11 --lang ENG --insecure
  ./scripts/fetch_olympics_data.py --comp OG2024 --event FBLMTEAM11 --lang ENG
  (This will download `GLO_EventGames~comp=OG2024~event=FBLMTEAM11------------~lang=ENG.json` into `tmp/`)

"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable, List

try:
    import requests
except Exception:
    print("This script requires the 'requests' package. Install with: pip install requests", file=sys.stderr)
    raise

BASE_DEFAULT = "https://stacy.olympics.com/OG2024/data"
DEFAULT_OUT = "tmp"

# Default headers mimic a modern browser to avoid 403 responses from servers that block non-browser clients.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.117 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_filename(name: str) -> str:
    # remove common duplication suffix like ' (1)' before extension
    return re.sub(r" \(\d+\)(?=\.json$)", "", name)


# Event codes in filenames expect trailing '-' padding (e.g. `FBLMTEAM11------------`).
# Users may pass the short event id (e.g. `FBLMTEAM11`) and it will be padded to the canonical length.

def canonicalize_event(event: str, total_len: int = 22, pad_char: str = "-") -> str:
    """Return a canonical event code with trailing padding.

    - If the provided value contains any dash ('-'), treat it as a (possibly partial) full code and pad to length.
    - If it contains no dashes, append padding to reach the canonical length.
    """
    if not event:
        return event
    e = event.strip()
    if "-" in e:
        if len(e) < total_len:
            return e + pad_char * (total_len - len(e))
        return e
    # no dash present: append padding
    if len(e) < total_len:
        return e + pad_char * (total_len - len(e))
    return e



def build_filename(resource: str, comp: str | None, event: str | None, lang: str | None) -> str:
    """Build a filename from components.

    Produces: RESOURCE~comp=...~event=...~lang=....json
    """
    parts = [resource]
    if comp:
        parts.append(f"comp={comp}")
    if event:
        parts.append(f"event={event}")
    if lang:
        parts.append(f"lang={lang}")
    return "~".join(parts) + ".json"


def build_url(base_url: str, filename: str) -> str:
    # quote the filename to be safe in URLs
    from urllib.parse import quote

    return f"{base_url.rstrip('/')}/{quote(filename)}"


def download_one(session: requests.Session, url: str, out_path: Path, insecure: bool, timeout: int = 30, max_retries: int = 3) -> bool:
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            # Use the provided session (pre-configured headers) to make the request.
            with session.get(url, stream=True, timeout=timeout, verify=not insecure) as r:
                if r.status_code == 404:
                    print(f"NOT FOUND: {url}")
                    return False
                r.raise_for_status()
                tmp_path = out_path.with_suffix(out_path.suffix + ".download")
                with tmp_path.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            fh.write(chunk)
                tmp_path.replace(out_path)
                return True
        except Exception as e:
            last_exc = e
            wait = 1 + attempt * 0.5
            print(f"Error downloading {url} (attempt {attempt}/{max_retries}): {e}. Retrying in {wait:.1f}s...")
            time.sleep(wait)
    print(f"Failed to download {url} after {max_retries} attempts: {last_exc}")
    return False


def download_many(filenames: Iterable[str], base_url: str, out_dir: Path, insecure: bool, concurrency: int, force: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    filenames = list(dict.fromkeys(filenames))  # preserve order, dedupe
    total = len(filenames)
    print(f"Downloading {total} files to {out_dir} (concurrency={concurrency})")

    tasks = []
    # create a session and apply default headers (including Referer) to reduce chance of 403
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.setdefault("Referer", base_url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {}
        for name in filenames:
            name = normalize_filename(name)
            out_path = out_dir / name
            if out_path.exists() and not force:
                print(f"SKIP (exists): {name}")
                continue
            url = build_url(base_url, name)
            fut = ex.submit(download_one, session, url, out_path, insecure)
            futures[fut] = name

        completed = 0
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            ok = fut.result()
            status = "OK" if ok else "ERR"
            print(f"{status}: {name}")
            completed += 1
    print(f"Finished downloads (attempted {completed}/{total}).")
    return 0


def discover_related_files(main_json_path: Path, comp: str, lang: str) -> List[str]:
    """Parse the downloaded event JSON and discover related filenames to download.

    This function returns a broad set of related files (legacy behavior). Prefer using
    `discover_needed_files` if you only want the files required by `assemble_api_response.py`.

    Returns a list of filenames (not URLs) to attempt to download.
    """
    import json

    if not main_json_path.exists():
        print(f"Main JSON not found for discovery: {main_json_path}")
        return []

    with main_json_path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except Exception as e:
            print(f"Failed to parse JSON {main_json_path}: {e}")
            return []

    event_code = None
    event = data.get("event") or {}
    event_code = event.get("code") if isinstance(event, dict) else None

    # derive discipline code (first 3 letters of the event code) if possible
    disc = None
    if event_code and len(event_code) >= 3:
        disc = event_code[:3].upper()

    unit_codes = set()
    dates = set()

    for phase in event.get("phases", []) if isinstance(event.get("phases", []), list) else []:
        for unit in phase.get("units", []) if isinstance(phase.get("units", []), list) else []:
            code = unit.get("code")
            if code:
                unit_codes.add(code)
            schedule = unit.get("schedule") or {}
            # schedule may contain a top-level startDate or a list of start entries
            sd = schedule.get("startDate")
            if sd:
                dates.add(sd.split("T", 1)[0])
            starts = schedule.get("start")
            if isinstance(starts, list):
                for s in starts:
                    sd2 = s.get("startDate")
                    if sd2:
                        dates.add(sd2.split("T", 1)[0])

    filenames = []

    if event_code:
        filenames.append(f"SEL_Phases~comp={comp}~lang={lang}~event={event_code}.json")

    if disc:
        filenames.append(f"GLO_EventUnits~comp={comp}~disc={disc}~lang={lang}.json")
        filenames.append(f"SEL_Events~comp={comp}~disc={disc}~lang={lang}.json")
        filenames.append(f"GLO_Positions~comp={comp}~disc={disc}~lang={lang}.json")
        filenames.append(f"CIS_Ticker~comp={comp}~disc={disc}~type=RESULTS.json")

    # Generic resources
    filenames.append(f"CIS_H1~comp={comp}.json")
    filenames.append(f"MIS_ParticipantNames~comp={comp}~lang={lang}.json")
    filenames.append(f"MIS_NOCS~comp={comp}~lang={lang}.json")
    filenames.append(f"GLO_Disciplines~comp={comp}~lang={lang}.json")
    filenames.append(f"GLO_SportCodes~comp={comp}~lang={lang}.json")

    for uc in sorted(unit_codes):
        if disc:
            filenames.append(f"RES_ByRSC_H2H~comp={comp}~disc={disc}~rscResult={uc}~lang={lang}.json")

    for d in sorted(dates):
        if disc:
            filenames.append(f"SCH_ByDisciplineH2H~comp={comp}~disc={disc}~lang={lang}~date={d}.json")

    # dedupe but preserve order
    seen = set()
    out = []
    for f in filenames:
        if f not in seen:
            out.append(f)
            seen.add(f)
    print(f"Discovered {len(out)} related files to attempt downloading.")
    return out


def discover_needed_files(main_json_path: Path, comp: str, lang: str) -> List[str]:
    """Return a minimal list of files required by `assemble_api_response.py`.

    Currently this includes only `RES_ByRSC_H2H` files for each unit found in the main event JSON.
    """
    import json

    if not main_json_path.exists():
        print(f"Main JSON not found for discovery: {main_json_path}")
        return []

    with main_json_path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except Exception as e:
            print(f"Failed to parse JSON {main_json_path}: {e}")
            return []

    event = data.get("event") or {}
    event_code = event.get("code") if isinstance(event, dict) else None
    disc = event_code[:3].upper() if event_code and len(event_code) >= 3 else None

    unit_codes = set()
    for phase in event.get("phases", []) if isinstance(event.get("phases", []), list) else []:
        for unit in phase.get("units", []) if isinstance(phase.get("units", []), list) else []:
            code = unit.get("code")
            if code:
                unit_codes.add(code)

    filenames = []
    for uc in sorted(unit_codes):
        if disc:
            filenames.append(f"RES_ByRSC_H2H~comp={comp}~disc={disc}~rscResult={uc}~lang={lang}.json")

    print(f"Discovered {len(filenames)} RES_ByRSC_H2H files to attempt downloading.")
    return filenames


# (was) parse_keyvals: removed because the CLI now only accepts fixed arguments (--comp, --event, --lang, --insecure).


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download OG2024 JSON data files from stacy.olympics.com")
    p.add_argument("--insecure", action="store_true", help="Skip SSL certificate validation")
    p.add_argument("--comp", default="OG2024", help="Competition code (default: OG2024)")
    p.add_argument("--event", default="FBLMTEAM11", help="Event code (default: FBLMTEAM11)")
    p.add_argument("--lang", default="ENG", help="Language code (default: ENG)")

    args = p.parse_args(argv)

    out_dir = Path(DEFAULT_OUT)
    event_code = canonicalize_event(args.event)
    filename = build_filename("GLO_EventGames", args.comp, event_code, args.lang)
    files: List[str] = [filename]

    # use fixed concurrency=4 and force=False
    rc = download_many(files, BASE_DEFAULT, out_dir, args.insecure, 4, False)

    # If the main file was downloaded, discover and download only the files needed by the assembler
    main_path = out_dir / normalize_filename(filename)
    if main_path.exists():
        related = discover_needed_files(main_path, args.comp, args.lang)
        if related:
            print("Attempting to download needed RES files only...")
            download_many(related, BASE_DEFAULT, out_dir, args.insecure, 4, False)
    else:
        print(f"Main file not present after download: {main_path}. Skipping discovery.")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
