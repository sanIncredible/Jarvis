#!/usr/bin/env python3
"""
sync_earnings_calendar.py
Fetches upcoming corporate action announcements (Quarterly Results, Splits, Bonus, Rights, Mergers)
from NSE Event Calendar API and generates data/earnings_calendar.json.
Syncs to OCI VM (/home/opc/Jarvis/data/earnings_calendar.json).
"""
import sys
import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = DATA_DIR / "earnings_calendar.json"

MAJOR_ACTION_KEYWORDS = [
    "financial result",
    "financial results",
    "results",
    "bonus",
    "split",
    "sub-division",
    "sub division",
    "rights",
    "merger",
    "demerger",
    "amalgamation"
]

def fetch_nse_calendar():
    url = "https://www.nseindia.com/api/event-calendar?index=equities"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"
    }

    session = requests.Session()
    session.headers.update(headers)
    
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        print(f"Notice: NSE returned HTTP {resp.status_code}")
    except Exception as e:
        print(f"Error requesting NSE event calendar: {e}")
    return []

def process_calendar(records):
    cal_map = {}
    total_events = 0

    for rec in records:
        if not isinstance(rec, dict):
            continue
        sym = str(rec.get("symbol", "")).strip().upper()
        if not sym:
            continue
        
        purpose = str(rec.get("purpose", "")).strip()
        bm_desc = str(rec.get("bm_desc", "")).strip()
        dt_raw = str(rec.get("date", "")).strip()

        # Check for major corporate actions
        combined_text = f"{purpose} {bm_desc}".lower()
        is_major = any(kw in combined_text for kw in MAJOR_ACTION_KEYWORDS)
        if not is_major:
            continue

        # Parse date: DD-Mon-YYYY (e.g. '23-Nov-2026')
        iso_date = None
        for fmt in ["%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"]:
            try:
                dt_obj = datetime.strptime(dt_raw, fmt)
                iso_date = dt_obj.strftime("%Y-%m-%d")
                break
            except Exception:
                pass

        if not iso_date:
            continue

        total_events += 1
        cal_map[sym] = {
            "date": iso_date,
            "purpose": purpose,
            "desc": bm_desc
        }

    output = {
        "_metadata": {
            "last_synced_ist": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "NSE Corporate Announcements / Board Meetings",
            "total_blackout_symbols": len(cal_map),
            "major_actions": ["Financial Results", "Bonus", "Split", "Rights", "Merger/Demerger"]
        },
        "symbols": cal_map
    }
    return output

def main():
    print("🔄 Fetching NSE Corporate Event Calendar...")
    records = fetch_nse_calendar()
    if not records or len(records) == 0:
        print("❌ Sourcing failed: NSE returned 0 records or request was rejected. Preserving existing data/earnings_calendar.json!")
        return False

    print(f"Received {len(records)} raw records from NSE.")
    
    data = process_calendar(records)
    if len(data.get("symbols", {})) == 0 and len(records) > 0:
        print("⚠️ Warning: No major corporate actions matched keywords.")
    print(f"Identified {len(data['symbols'])} symbols with major corporate actions.")

    # Write to local data/earnings_calendar.json
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Saved locally to {OUT_FILE}")

    # Push to OCI VM
    ssh_key = BASE_DIR / "ssh-key-2026-09-21_new.key"
    cfg_file = BASE_DIR / "config_credentials.json"
    oci_host = None
    if cfg_file.is_file():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            oci_host = cfg.get("oci", {}).get("host")
        except Exception:
            pass

    if ssh_key.is_file() and oci_host:
        cmd = [
            "scp",
            "-i", str(ssh_key),
            "-o", "StrictHostKeyChecking=no",
            str(OUT_FILE),
            f"opc@{oci_host}:/home/opc/Jarvis/data/earnings_calendar.json"
        ]
        try:
            print("📤 Syncing earnings_calendar.json to OCI VM...")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                print("✅ Successfully synced to OCI VM!")
            else:
                print(f"Notice on SCP sync: {res.stderr}")
        except Exception as scp_err:
            print(f"Notice running SCP: {scp_err}")

if __name__ == "__main__":
    main()
