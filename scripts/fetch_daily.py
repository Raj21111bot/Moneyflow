#!/usr/bin/env python3
"""
fetch_daily.py
--------------
Downloads NSE's full bhavcopy with delivery data
(sec_bhavdata_full_DDMMYYYY.csv), aggregates traded value and delivery
value by SECTOR and INDUSTRY (using data/sector_map.csv), and updates the
rolling history at docs/data/history.json that the dashboard reads.

Usage:
    python scripts/fetch_daily.py                # today (skips holidays)
    python scripts/fetch_daily.py --date 2026-07-03
    python scripts/fetch_daily.py --backfill 45  # seed ~45 trading days
"""

import argparse
import csv
import io
import json
import os
import sys
from datetime import date, datetime, timedelta

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(BASE_DIR, "data", "sector_map.csv")
HISTORY_PATH = os.path.join(BASE_DIR, "docs", "data", "history.json")

MAX_DAYS_KEPT = 160         # rolling window of trading days kept in JSON (~150+ trading days / 7+ months)
SERIES_INCLUDED = {"EQ", "BE", "BZ"}
MIN_STOCK_CR = 1.0          # per-stock rows below this traded value aren't stored
                            # (sector/industry totals still include them)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=15)
    except requests.RequestException:
        pass
    return s


def load_sector_map() -> dict[str, tuple[str, str]]:
    if not os.path.exists(MAP_PATH):
        print("[error] data/sector_map.csv missing — run scripts/build_sector_map.py first")
        sys.exit(1)
    out = {}
    with open(MAP_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sector = row.get("SECTOR") or "Others"
            industry = row.get("INDUSTRY") or sector
            company = row.get("COMPANY") or row["SYMBOL"]
            out[row["SYMBOL"]] = (sector, industry, company)
    return out


def fetch_bhav(session: requests.Session, d: date) -> list[dict] | None:
    """Returns parsed rows for the date, or None if no file (holiday/weekend)."""
    url = (
        "https://nsearchives.nseindia.com/products/content/"
        f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
    )
    try:
        r = session.get(url, timeout=45)
    except requests.RequestException as e:
        print(f"[warn] {d}: request failed: {e}")
        return None
    if r.status_code != 200 or "SYMBOL" not in r.text[:200]:
        return None
    reader = csv.DictReader(io.StringIO(r.text))
    rows = []
    for raw in reader:
        row = {k.strip(): (v or "").strip() for k, v in raw.items()}
        rows.append(row)
    return rows


def aggregate(rows: list[dict], smap: dict) -> dict:
    """
    Returns:
    {
      "<sector>": {
        "turnover": float(Cr), "delivery": float(Cr), "symbols": set(),
        "industries": {"<industry>": {"turnover":..,"delivery":..,"symbols":set()}}
      }
    }
    """
    agg: dict = {}
    for row in rows:
        if row.get("SERIES") not in SERIES_INCLUDED:
            continue
        sym = row.get("SYMBOL", "")
        sector, industry, company = smap.get(sym, ("Others", "Others", sym))
        try:
            turnover_cr = float(row.get("TURNOVER_LACS", "0").replace(",", "")) / 100.0
        except ValueError:
            turnover_cr = 0.0
        try:
            deliv_qty = float(row.get("DELIV_QTY", "0").replace(",", ""))
            avg_price = float(row.get("AVG_PRICE", "0").replace(",", ""))
            delivery_cr = deliv_qty * avg_price / 1e7
        except ValueError:
            delivery_cr = 0.0

        s = agg.setdefault(
            sector, {"turnover": 0.0, "delivery": 0.0, "symbols": set(), "industries": {}}
        )
        s["turnover"] += turnover_cr
        s["delivery"] += delivery_cr
        s["symbols"].add(sym)
        ind = s["industries"].setdefault(
            industry, {"turnover": 0.0, "delivery": 0.0, "symbols": set(), "stocks": {}}
        )
        ind["turnover"] += turnover_cr
        ind["delivery"] += delivery_cr
        ind["symbols"].add(sym)
        st = ind["stocks"].setdefault(sym, {"name": company, "turnover": 0.0, "delivery": 0.0})
        st["turnover"] += turnover_cr   # covers multi-series (EQ+BE) symbols
        st["delivery"] += delivery_cr

    # drop tiny per-stock rows to keep the JSON small (totals unaffected)
    for sdata in agg.values():
        for idata in sdata["industries"].values():
            idata["stocks"] = {
                k: v for k, v in idata["stocks"].items() if v["turnover"] >= MIN_STOCK_CR
            }
    return agg


def load_history() -> dict:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": "", "dates": [], "sectors": {}}


def merge_day(history: dict, day: str, agg: dict) -> None:
    if day not in history["dates"]:
        history["dates"].append(day)
    history["dates"] = sorted(set(history["dates"]), reverse=True)[:MAX_DAYS_KEPT]
    kept = set(history["dates"])

    for sector, sdata in agg.items():
        node = history["sectors"].setdefault(
            sector, {"count": 0, "turnover": {}, "delivery": {}, "industries": {}}
        )
        node["turnover"][day] = round(sdata["turnover"], 2)
        node["delivery"][day] = round(sdata["delivery"], 2)
        node["count"] = len(sdata["symbols"])
        for ind, idata in sdata["industries"].items():
            inode = node["industries"].setdefault(
                ind, {"count": 0, "turnover": {}, "delivery": {}, "stocks": {}}
            )
            inode["turnover"][day] = round(idata["turnover"], 2)
            inode["delivery"][day] = round(idata["delivery"], 2)
            inode["count"] = len(idata["symbols"])
            for sym, stdata in idata["stocks"].items():
                snode = inode["stocks"].setdefault(sym, {"turnover": {}, "delivery": {}})
                snode["name"] = stdata.get("name", sym)
                snode["turnover"][day] = round(stdata["turnover"], 2)
                snode["delivery"][day] = round(stdata["delivery"], 2)

    # trim anything outside the rolling window
    for sector in list(history["sectors"]):
        node = history["sectors"][sector]
        for key in ("turnover", "delivery"):
            node[key] = {d: v for d, v in node[key].items() if d in kept}
        for ind in list(node["industries"]):
            inode = node["industries"][ind]
            for key in ("turnover", "delivery"):
                inode[key] = {d: v for d, v in inode[key].items() if d in kept}
            for sym in list(inode.get("stocks", {})):
                snode = inode["stocks"][sym]
                for key in ("turnover", "delivery"):
                    snode[key] = {d: v for d, v in snode[key].items() if d in kept}
                if not snode["turnover"]:
                    del inode["stocks"][sym]
            if not inode["turnover"]:
                del node["industries"][ind]
        if not node["turnover"]:
            del history["sectors"][sector]

    history["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def save_history(history: dict) -> None:
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, separators=(",", ":"))
    size_kb = os.path.getsize(HISTORY_PATH) // 1024
    print(f"[ok] wrote {HISTORY_PATH} ({size_kb} KB, {len(history['dates'])} days)")


def process_date(session, smap, history, d: date) -> bool:
    rows = fetch_bhav(session, d)
    if rows is None:
        print(f"[skip] {d}: no bhavcopy (weekend/holiday or not yet published)")
        return False
    agg = aggregate(rows, smap)
    merge_day(history, d.isoformat(), agg)
    total = sum(s["turnover"][d.isoformat()] for s in history["sectors"].values()
                if d.isoformat() in s["turnover"])
    print(f"[ok] {d}: {len(agg)} sectors, total traded value ~₹{total:,.0f} Cr")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--backfill", type=int, default=0, help="seed N trading days of history")
    args = ap.parse_args()

    session = make_session()
    smap = load_sector_map()
    history = load_history()

    if args.backfill:
        got, d = 0, date.today()
        while got < args.backfill and (date.today() - d).days < args.backfill * 2 + 30:
            if d.weekday() < 5 and process_date(session, smap, history, d):
                got += 1
            d -= timedelta(days=1)
    else:
        d = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
        if not process_date(session, smap, history, d) and not args.date:
            # today not published yet -> try previous weekday so the run isn't wasted
            prev = d - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            process_date(session, smap, history, prev)

    save_history(history)


if __name__ == "__main__":
    main()
