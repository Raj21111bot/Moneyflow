# NSE Money Flow Dashboard

Sector-wise and industry-wise daily money flow (traded value + delivery value, in ₹ Cr) built from NSE's official bhavcopy files, with 30-day-average heatmap highlighting, a Signals page (delivery-spike screener with per-stock Daily/Weekly/Monthly accumulation-distribution trend), and a Sectors page (Excel-style expandable sector→stock accumulation/distribution ranking).

## What's inside

```
moneyflow/
├── scripts/
│   ├── build_sector_map.py     # one-time: symbol → sector/industry mapping
│   ├── fetch_daily.py          # daily: download bhavcopy, aggregate, update JSON
│   ├── daily_refresh.ps1       # wrapper run by Task Scheduler (handles encoding, git push)
│   ├── launch_dashboard.ps1    # starts the local server (if needed) + opens the dashboard
│   └── setup_new_machine.ps1   # run once on a new laptop after restoring this folder
├── data/sector_map.csv         # generated symbol → sector/industry mapping
├── docs/
│   ├── index.html              # the dashboard
│   └── data/history.json       # rolling ~160 trading day (7+ month) aggregated data
└── .github/workflows/update.yml   # manual-only GitHub Pages fallback (see below)
```

Ships with **real NSE data** already populated (`docs/data/history.json`, ~160 trading days as of the last fetch) — nothing needs re-fetching after a restore unless you want to.

## Restoring on a new machine (after a backup/laptop swap)

1. Copy this whole `moneyflow` folder to the new laptop (from OneDrive, USB, wherever it was backed up to).
2. Make sure Python 3.10+ is installed (check "Add to PATH" during install).
3. Run `scripts\setup_new_machine.ps1` once (right-click → Run with PowerShell). It installs the `requests` package, points the helper scripts at this machine's Python, registers the "MoneyFlow Daily Refresh" scheduled task (Mon–Fri, 5:00 PM local — **adjust if this machine isn't in Kuwait's timezone**, it should land ~7:00–7:30 PM IST, after NSE publishes), and creates the "NSE Money Flow" desktop shortcut.
4. Double-click the desktop shortcut — the dashboard should open with all the existing history already in it.
5. Optional but recommended: in Task Scheduler, also enable **"Wake the computer to run this task"** on the task's Settings tab, and check `powercfg /q SCHEME_CURRENT SUB_SLEEP RTCWAKE` allows wake timers — this was needed on the old laptop because it sometimes slept through the 5 PM trigger; may or may not be needed on the new one.
6. A `.git` repo already exists in this folder (initialized, no commits yet — GitHub Pages/mobile-access setup was started but deferred). Safe to ignore, or pick that back up later; see "Daily automation" below.

## Setup from scratch (only if you don't already have history.json)

Requires Python 3.10+ and `pip install requests`.

**1. Build the sector map**

```
python scripts/build_sector_map.py --enrich
```

Downloads the Nifty Total Market constituent list (~750 stocks, covers the vast majority of NSE cash turnover) for sector-level classification. ⚠️ `--enrich` (per-symbol industry drill-down via NSE's quote-equity API) is blocked from most networks we've tested — it'll just spin without enriching anything. Safe to skip; industries fall back to their parent sector name, which is what's actually running today.

**2. Seed history (so Avg30 works from day one)**

```
python scripts/fetch_daily.py --backfill 160
```

NSE's archive goes back at least 8-9 months from any network we've tested; 160 trading days (~7+ months) is what this dashboard currently keeps as its rolling window.

**3. Preview locally**

```
python scripts/dashboard_server.py
```

Open **http://127.0.0.1:8000** — not `localhost:8000`. On at least one machine we've run this on, `localhost` resolved via IPv6 first and stalled ~21 seconds before falling back; `127.0.0.1` is instant. (`scripts/launch_dashboard.ps1` already does this correctly and starts the server for you if it isn't running — it uses `dashboard_server.py`, not the plain `python -m http.server`, specifically so the dashboard's **Refresh data** button works: that button POSTs to `/api/refresh`, which the plain stdlib server doesn't have and would 404 on.)

## Daily automation

**Option A — laptop fetches, GitHub Pages hosts (for network-independent / mobile access)**

Actual setup used here: the laptop keeps fetching from NSE on its own schedule (Option B below — proven reliable from this network), and `scripts/daily_refresh.ps1` also pushes the updated `docs/data/history.json` to GitHub afterward. GitHub Pages then serves the site at a public URL reachable from any device, any network (phone on 4G/5G, home Wi-Fi, anywhere) — independent of whether the laptop is on office Ethernet or off entirely.

The `.github/workflows/update.yml` Actions-fetches-from-NSE trigger is intentionally disabled (`workflow_dispatch` only, no `schedule`) — GitHub's own runners are cloud-datacenter IPs, which NSE often blocks, so relying on them was the unreliable path. It's kept as a manual fallback only.

**One-time go-live steps — run these on a network that isn't blocking GitHub** (office networks sometimes block github.com/gitlab.com/bitbucket.org entirely as policy; try home Wi-Fi or a phone hotspot if `winget install --id Git.Git` or `git push` fails):

1. Install Git for Windows: `winget install --id Git.Git -e`
2. `cd` into this folder, then:
   ```
   git init
   git add .
   git commit -m "Initial commit"
   ```
3. Create a repo on github.com (public — Pages hosting on a private repo needs a paid plan), then:
   ```
   git remote add origin https://github.com/<you>/moneyflow.git
   git branch -M main
   git push -u origin main
   ```
4. Repo → Settings → Pages → Source: *Deploy from branch*, branch `main`, folder `/docs`. Wait ~1 minute, then the dashboard is live at `https://<you>.github.io/moneyflow/`.
5. Bookmark that URL on your phone (any network) and on the laptop. `scripts/daily_refresh.ps1` will push new data there automatically from then on, whenever it can reach GitHub.

⚠️ If step 1 or 3's push fails with a connection error while on the office network, that's the same GitHub-is-blocked issue — switch networks and retry just that step.

**Option B — Run locally on a schedule (what's actually running)**

Windows Task Scheduler runs `scripts\daily_refresh.ps1` Mon–Fri at **7:00 AM** (morning catch-up, in case last evening's run was missed) and **5:00 PM** (primary — after NSE typically publishes, ~6:30–7 PM IST ≈ 5 PM Kuwait). Task name: **"MoneyFlow Daily Refresh"**. The script fetches the day's data, then makes a best-effort attempt to `git add`/`commit`/`push` (silently does nothing if no GitHub remote is configured yet — see the migration section above). Set up via `scripts/setup_new_machine.ps1` on a fresh machine.

## Notes & current scope

- **NSE only for now.** NSE carries ~90%+ of Indian cash-market turnover; BSE was investigated (see below) but doesn't publish delivery-quantity data in its public bhavcopy, so it can't get the same accumulation/distribution treatment as NSE stocks — not incorporated.
- **Delivery value** = delivered quantity × day's average price — the better proxy for "real" money flow vs intraday churn. This is the metric every feature in this app (heatmap highlighting, Signals scoring, Sectors accumulation/distribution, per-stock D/W/M trend) is built on.
- Stocks outside the Nifty Total Market universe are grouped under **Others** (currently ~1,950 stocks — expanding this one specifically on the Sectors page will be slow to render; every named sector is under 125 stocks and expands instantly).
- History is trimmed to a rolling **~160 trading days** (7+ months) to keep the JSON manageable while giving Daily/Weekly/Monthly views a solid baseline.
- Data publishes after market close (~6:30–7 PM IST); the dashboard is always ready before the next trading day, assuming the laptop was awake for the 5 PM (or 7 AM catch-up) fetch.
