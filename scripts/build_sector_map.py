#!/usr/bin/env python3
"""
build_sector_map.py
-------------------
Builds data/sector_map.csv : SYMBOL, COMPANY, SECTOR, INDUSTRY

Step 1 (fast)  : downloads the Nifty Total Market (750) constituent list
                 from NSE archives -> gives SYMBOL, COMPANY and a broad
                 sector ("Industry" column in that file).
Step 2 (--enrich, optional but recommended, one-time ~8 min):
                 hits NSE's quote-equity API per symbol to get the full
                 classification (sector + basic industry) used for the
                 industry drill-down in the dashboard. Results are cached,
                 so re-running only fetches missing symbols.

Usage:
    python scripts/build_sector_map.py            # basic map
    python scripts/build_sector_map.py --enrich   # + industry drill-down
"""

import argparse
import csv
import io
import os
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(BASE_DIR, "data", "sector_map.csv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

INDEX_LIST_URLS = [
    # Nifty Total Market ~750 stocks (best coverage)
    "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
    # fallback: Nifty 500
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    # warm up cookies (needed for the /api/ endpoints)
    try:
        s.get("https://www.nseindia.com", timeout=15)
    except requests.RequestException:
        pass
    return s


def download_index_list(session: requests.Session) -> list[dict]:
    for url in INDEX_LIST_URLS:
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200 and "Symbol" in r.text[:500]:
                print(f"[ok] downloaded {url.rsplit('/', 1)[-1]}")
                reader = csv.DictReader(io.StringIO(r.text))
                rows = []
                for row in reader:
                    row = {k.strip(): (v or "").strip() for k, v in row.items()}
                    if row.get("Symbol"):
                        rows.append(
                            {
                                "SYMBOL": row["Symbol"],
                                "COMPANY": row.get("Company Name", ""),
                                "SECTOR": row.get("Industry", "Others"),
                                "INDUSTRY": "",  # filled by --enrich
                            }
                        )
                return rows
        except requests.RequestException as e:
            print(f"[warn] {url} failed: {e}")
    print("[error] could not download any index constituent list")
    sys.exit(1)


def load_existing() -> dict[str, dict]:
    if not os.path.exists(MAP_PATH):
        return {}
    with open(MAP_PATH, newline="", encoding="utf-8") as f:
        return {row["SYMBOL"]: row for row in csv.DictReader(f)}


def save_map(rows: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(MAP_PATH), exist_ok=True)
    with open(MAP_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["SYMBOL", "COMPANY", "SECTOR", "INDUSTRY"])
        w.writeheader()
        for sym in sorted(rows):
            w.writerow(rows[sym])


def enrich(session: requests.Session, rows: dict[str, dict]) -> None:
    """Fetch NSE's full classification per symbol (cached, resumable)."""
    todo = [s for s, r in rows.items() if not r.get("INDUSTRY")]
    print(f"[enrich] {len(todo)} symbols to fetch")
    for i, sym in enumerate(todo, 1):
        url = f"https://www.nseindia.com/api/quote-equity?symbol={requests.utils.quote(sym)}"
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 401 or r.status_code == 403:
                # cookies expired -> refresh session once
                session.get("https://www.nseindia.com", timeout=15)
                r = session.get(url, timeout=15)
            data = r.json()
            info = data.get("industryInfo") or {}
            sector = info.get("sector") or rows[sym]["SECTOR"]
            industry = info.get("basicIndustry") or info.get("industry") or ""
            rows[sym]["SECTOR"] = sector
            rows[sym]["INDUSTRY"] = industry
        except Exception as e:  # noqa: BLE001 — keep going, cache progress
            print(f"[warn] {sym}: {e}")
        if i % 25 == 0:
            save_map(rows)
            print(f"[enrich] {i}/{len(todo)} done (progress saved)")
        time.sleep(0.4)  # be polite; NSE rate-limits aggressively
    save_map(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enrich", action="store_true", help="fetch full industry classification per symbol")
    args = ap.parse_args()

    session = make_session()
    existing = load_existing()
    fresh = download_index_list(session)

    # merge: keep enriched fields already on disk
    for row in fresh:
        sym = row["SYMBOL"]
        if sym in existing and existing[sym].get("INDUSTRY"):
            row["INDUSTRY"] = existing[sym]["INDUSTRY"]
            row["SECTOR"] = existing[sym]["SECTOR"]
        existing[sym] = row

    save_map(existing)
    print(f"[ok] sector map has {len(existing)} symbols -> {MAP_PATH}")

    if args.enrich:
        enrich(session, existing)
        print("[ok] enrichment complete")


if __name__ == "__main__":
    main()
