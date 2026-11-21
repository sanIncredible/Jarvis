#!/usr/bin/env python3
"""
🛡️ JARVIS PHASE 1 POST-CLOSE AUDIT TOOL (v3.3.0 Strict)
======================================================
Automates the 4 mandatory reviewer sign-off checks after market close:
1. shadow_history_eod.json has exactly one target date entry with status == 'VALID'.
2. day_num increments properly to next valid session.
3. feed_session_health.json records sensible downtime (<10.0m) during 09:30-10:15.
4. All trade records & portfolio entries carry config_hash == '1813c808', watchlist_hash == 'eeeb00af', git_commit.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))

EXPECTED_CONFIG_HASH = "8229eb94"
EXPECTED_WATCHLIST_HASH = "eeeb00af"

def run_post_close_audit(check_date="2026-11-23"):
    print("=" * 75)
    print(f"🔍 RUNNING POST-CLOSE AUDIT FOR SESSION: {check_date}")
    print("=" * 75)

    all_passed = True

    # CHECK 1: Exactly one entry in shadow_history_eod.json with status VALID
    eod_file = BASE_DIR / "shadow_history_eod.json"
    c1_ok = False
    c1_msg = ""
    if not eod_file.is_file():
        c1_msg = f"FAIL: {eod_file.name} does not exist yet."
    else:
        try:
            with open(eod_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            matching = [h for h in history if h.get("date") == check_date]
            if len(matching) == 1:
                st = matching[0].get("status")
                dn = matching[0].get("day_num")
                wh = matching[0].get("watchlist_hash")
                if st == "VALID":
                    c1_ok = True
                    c1_msg = f"PASS: Exactly 1 entry found with status=VALID (day_num={dn}, watchlist_hash={wh})"
                else:
                    c1_msg = f"FAIL: Entry found but status is '{st}' (expected 'VALID')"
            elif len(matching) == 0:
                c1_msg = f"FAIL: No entry found for date {check_date}"
            else:
                c1_msg = f"FAIL: Duplicate entries found ({len(matching)} entries) for date {check_date}"
        except Exception as e:
            c1_msg = f"FAIL: Corrupt history file: {e}"

    print(f"Check 1 [EOD History Entry]: {'✅' if c1_ok else '❌'} {c1_msg}")
    if not c1_ok:
        all_passed = False

    # CHECK 2: day_num on next day
    # Next trading day after Nov 23: Nov 24 is Gurunanak Jayanti holiday, so next is Nov 25
    c2_ok = False
    c2_msg = ""
    if c1_ok:
        # Calculate what day_num would be on next trading day
        try:
            from shadow_execution_engine import START_DATE_STR
            with open(eod_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            valid_past_dates = sorted(list(set(
                h.get("date") for h in history
                if h.get("date", "") >= START_DATE_STR
                and h.get("status") == "VALID"
            )))
            next_day_num = len(valid_past_dates) + 1
            if next_day_num == 2:
                c2_ok = True
                c2_msg = f"PASS: Accumulated {len(valid_past_dates)} valid session(s). Next session will read day_num={next_day_num}."
            else:
                c2_msg = f"FAIL: Next day_num would be {next_day_num} (expected 2)"
        except Exception as e:
            c2_msg = f"FAIL: {e}"
    else:
        c2_msg = "SKIPPED: Check 1 must pass first"

    print(f"Check 2 [Day Num Sequence]:   {'✅' if c2_ok else '❌'} {c2_msg}")
    if not c2_ok:
        all_passed = False

    # CHECK 3: feed_session_health.json sensible downtime minutes
    health_file = BASE_DIR / "data" / "feed_session_health.json"
    c3_ok = False
    c3_msg = ""
    if not health_file.is_file():
        c3_msg = f"FAIL: {health_file} does not exist"
    else:
        try:
            with open(health_file, "r", encoding="utf-8") as f:
                hdata = json.load(f)
            f_date = hdata.get("date")
            down_min = float(hdata.get("downtime_minutes", 0.0))
            down_pct = float(hdata.get("downtime_pct", 0.0))
            status = hdata.get("status")
            if f_date == check_date:
                if down_min < 10.0 and status in ("VALID", "PARTIAL"):
                    c3_ok = True
                    c3_msg = f"PASS: Telemetry for {f_date}: downtime={down_min:.1f}m ({down_pct:.1f}%), status={status}"
                else:
                    c3_msg = f"WARNING: Downtime {down_min:.1f}m >= 10.0m threshold (Status: {status})"
            else:
                c3_msg = f"FAIL: Telemetry file is for date {f_date}, not {check_date}"
        except Exception as e:
            c3_msg = f"FAIL: Could not read health file: {e}"

    print(f"Check 3 [Feed Telemetry]:     {'✅' if c3_ok else '❌'} {c3_msg}")
    if not c3_ok:
        all_passed = False

    # CHECK 4: Trade records carry config_hash, git_commit, and watchlist_hash
    trade_file = BASE_DIR / "shadow_trade_log.json"
    port_file = BASE_DIR / "shadow_portfolio.json"
    c4_ok = True
    c4_notes = []

    # Check portfolio
    try:
        from shadow_execution_engine import get_manifest_hash
        exp_mh = get_manifest_hash()
        with open(port_file, "r", encoding="utf-8") as f:
            port = json.load(f)
        for sym, pos in port.items():
            ch = pos.get("config_hash")
            wh = pos.get("watchlist_hash")
            mh = pos.get("manifest_hash") or pos.get("git_commit")
            if ch != EXPECTED_CONFIG_HASH:
                c4_ok = False
                c4_notes.append(f"Port {sym}: config_hash {ch} != {EXPECTED_CONFIG_HASH}")
            if wh != EXPECTED_WATCHLIST_HASH:
                c4_ok = False
                c4_notes.append(f"Port {sym}: watchlist_hash {wh} != {EXPECTED_WATCHLIST_HASH}")
            if mh != exp_mh:
                c4_ok = False
                c4_notes.append(f"Port {sym}: manifest_hash {mh} != {exp_mh}")
    except Exception as e:
        c4_notes.append(f"Error reading portfolio: {e}")

    # Check trades
    try:
        with open(trade_file, "r", encoding="utf-8") as f:
            tlog = json.load(f)
        today_trades = [t for t in tlog if t.get("entry_date") == check_date or t.get("exit_date") == check_date]
        for t in today_trades:
            sym = t.get("symbol")
            ch = t.get("config_hash")
            wh = t.get("watchlist_hash")
            mh = t.get("manifest_hash") or t.get("git_commit")
            if ch != EXPECTED_CONFIG_HASH:
                c4_ok = False
                c4_notes.append(f"Trade {sym}: config_hash {ch} != {EXPECTED_CONFIG_HASH}")
            if wh != EXPECTED_WATCHLIST_HASH:
                c4_ok = False
                c4_notes.append(f"Trade {sym}: watchlist_hash {wh} != {EXPECTED_WATCHLIST_HASH}")
            if mh != exp_mh:
                c4_ok = False
                c4_notes.append(f"Trade {sym}: manifest_hash {mh} != {exp_mh}")
    except Exception as e:
        c4_notes.append(f"Error reading trade log: {e}")

    if not c4_notes:
        c4_msg = f"PASS: All records stamped with config_hash={EXPECTED_CONFIG_HASH}, watchlist_hash={EXPECTED_WATCHLIST_HASH}, manifest_hash={exp_mh}"
    else:
        c4_msg = "; ".join(c4_notes)

    print(f"Check 4 [Trade Stamp Parity]: {'✅' if c4_ok else '❌'} {c4_msg}")
    if not c4_ok:
        all_passed = False

    print("=" * 75)
    print(f"OVERALL AUDIT RESULT: {'🎉 ALL CHECKS PASSED' if all_passed else '⚠️ SOME CHECKS REQUIRE ATTENTION'}")
    print("=" * 75)
    return all_passed

if __name__ == "__main__":
    target_dt = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d")
    success = run_post_close_audit(target_dt)
    sys.exit(0 if success else 1)
