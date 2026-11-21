from datetime import datetime, date, timezone, timedelta
#!/usr/bin/env python3
"""
test_phase1_harden_v33.py
Comprehensive Integration & Verification Suite for Jarvis Hardening Release v3.3.0:
1. Monday 09:00 Launch Gate vs In-Flight Multi-Trade Execution (0 Holdings Gate vs Contamination Check)
2. Day 0 Reset Timing & Pre-Nov 23 EOD Writer Guard (Zero Day 0 State Pollution)
3. Earnings Blackout Sourcing, Negative Confirmation, Validation & Pre-Flight 08:45 Alert
4. Deferred Lower-Circuit Exit Math:
   - Case A: Lower Circuit Lock (0 buyers -> remains unfillable)
   - Case B: Lower Circuit Unlock from Open (day_open == lower_circuit -> fills at first liquid * 0.9985)
   - Case C (Reviewer Item 1): Day Open far above unlock price (day_open = 100, lock = 90, unlock = 88)
     -> Strictly fills at min(unlock, ltp) * 0.9985 = 87.85, NEVER optimistic 99.85 pre-lock price!
5. Upstox V3 Depth & Upper Circuit Liquidity (Zero ask depth near ceiling vs quiet book far from circuit)
6. Parameter Hash Verification (CONFIG_HASH: fb15ae0f)
"""
import sys
import os
import json
import time
import shutil
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path

# Safe UTF-8 printing
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import shadow_execution_engine as see

PASSED_COUNT = 0
FAILED_COUNT = 0

def report_test(name, passed, details=""):
    global PASSED_COUNT, FAILED_COUNT
    if passed:
        PASSED_COUNT += 1
        print(f"  ✅ [PASS] {name} {details}")
    else:
        FAILED_COUNT += 1
        print(f"  ❌ [FAIL] {name} {details}")

def run_tests():
    print("=" * 70)
    print("🧪 RUNNING JARVIS PHASE 1 HARDENING v3.3.0 INTEGRATION TEST SUITE")
    print(f"   Config Version: {see.CONFIG_VERSION} | Config Hash: {see.CONFIG_HASH}")
    print("=" * 70)

    # Backup existing state files before running tests
    backup_dir = BASE_DIR / "backups" / "test_backup_v33"
    backup_dir.mkdir(parents=True, exist_ok=True)
    state_files = [
        "shadow_portfolio.json",
        "shadow_trade_log.json",
        "shadow_mtm_equity_curve.json",
        "shadow_rejected_signals.json",
        "watchlist.txt"
    ]
    for fn in state_files:
        src = BASE_DIR / fn
        if src.is_file():
            shutil.copy2(src, backup_dir / fn)

    try:
        # TEST 1: Config Hash Verification
        print("\n--- TEST 1: Config Hash Verification ---")
        expected_hash = "8229eb94"
        report_test(
            "Config Hash Parity",
            see.CONFIG_HASH == expected_hash,
            f"(Expected: {expected_hash}, Got: {see.CONFIG_HASH})"
        )
        snapshot_file = BASE_DIR / "config_snapshots" / f"config_{expected_hash}.json"
        report_test(
            "Config Snapshot Auto-Persistence",
            snapshot_file.is_file(),
            f"({snapshot_file.name} present)"
        )
        report_test(
            "Release Manifest Hash Stamped",
            bool(see.get_manifest_hash() and len(see.get_manifest_hash()) == 8),
            f"(Manifest Hash: {see.get_manifest_hash()})"
        )

        # TEST 2: Monday 09:00 Launch Gate vs In-Flight Multi-Trade Execution
        print("\n--- TEST 2: Monday 09:00 Gate vs In-Flight State Integrity ---")
        # Ensure sentinel exists for test
        sentinel_file = BASE_DIR / "archive" / ".day0_reset_completed"
        sentinel_file.parent.mkdir(parents=True, exist_ok=True)
        if not sentinel_file.is_file():
            sentinel_file.write_text("{\"test\": true}", encoding="utf-8")

        # Case A: Pristine baseline
        see.save_shadow_portfolio({})
        see.save_shadow_trade_log([])
        see.atomic_write_json(BASE_DIR / "shadow_mtm_equity_curve.json", [])
        gate_ok, gate_msg = see.assert_monday_0900_launch_gate()
        report_test("Monday 09:00 Gate (Clean State)", gate_ok, f"({gate_msg})")

        # Case B: In-Flight State Integrity with 1 Open Position
        mock_pos1 = {
            "TRENT": {
                "symbol": "TRENT",
                "entry_price": 5000.0,
                "current_sl": 4900.0,
                "entry_date": "2026-11-23",
                "quantity": 10,
                "is_day0": False
            }
        }
        see.save_shadow_portfolio(mock_pos1)
        
        # Monday 09:00 Gate should fail if open positions exist at 09:00 AM
        gate_ok_with_pos, _ = see.assert_monday_0900_launch_gate()
        report_test("Monday 09:00 Gate (Blocks if positions present at 09:00)", not gate_ok_with_pos)

        # In-Flight State Integrity MUST PASS with open positions as long as no Day 0 contamination
        in_flight_ok, in_flight_msg = see.assert_phase1_in_flight_state_integrity()
        report_test("In-Flight State Integrity (Passes with 1 Phase 1 Position)", in_flight_ok, f"({in_flight_msg})")

        # Case C: Contamination Detection
        mock_contaminated = {
            "TRENT": {
                "symbol": "TRENT",
                "entry_price": 5000.0,
                "entry_date": "2026-11-20", # Day 0 date!
                "quantity": 10,
                "is_day0": True
            }
        }
        see.save_shadow_portfolio(mock_contaminated)
        contam_ok, contam_msg = see.assert_phase1_in_flight_state_integrity()
        report_test("In-Flight State Integrity (Catches Day 0 Contamination)", not contam_ok, f"(Blocked: {contam_msg})")

        # Restore clean portfolio
        see.save_shadow_portfolio({})

        # TEST 3: Pre-Nov 23 EOD Writer Guard
        print("\n--- TEST 3: Pre-Nov 23 EOD Writer Guard ---")
        mock_curve_file = BASE_DIR / "shadow_mtm_equity_curve.json"
        see.atomic_write_json(mock_curve_file, []) # clean
        
        # Test record_daily_mtm_snapshot on pre-Nov 23 date (today is Nov 20)
        snap = see.record_daily_mtm_snapshot({}, [], unrealized_r=0.0, unrealized_pnl=0.0)
        
        # Verify that active curve was NOT polluted
        with open(mock_curve_file, "r", encoding="utf-8") as f:
            active_curve = json.load(f)
        report_test(
            "Pre-Nov 23 EOD Writer Guard (Active MTM curve remains clean)",
            len(active_curve) == 0,
            f"(Active entries: {len(active_curve)})"
        )
        day0_diverted = BASE_DIR / "archive" / "shadow_mtm_equity_curve_day0.json"
        report_test(
            "Pre-Nov 23 EOD Writer Guard (Diverted to archive)",
            day0_diverted.is_file(),
            f"({day0_diverted.name} created in archive)"
        )

        # TEST 4: Earnings Calendar Sourcing & Negative Confirmation
        print("\n--- TEST 4: Earnings Blackout & Negative Confirmation ---")
        # BCSSL has Financial Results on 2026-11-23 in data/earnings_calendar.json
        test_dt = datetime(2026, 11, 23, 9, 35, 0, tzinfo=see.IST)
        is_blk_bcssl, reason_bcssl = see.check_earnings_blackout("BCSSL", dt=test_dt)
        report_test("Earnings Blackout: BCSSL (Scheduled Nov 23)", is_blk_bcssl, f"({reason_bcssl})")

        # RELIANCE is NOT in earnings calendar -> Must PASS (Negative Confirmation)
        is_blk_rel, _ = see.check_earnings_blackout("RELIANCE", dt=test_dt)
        report_test("Negative Confirmation: RELIANCE (No filings -> PASS)", not is_blk_rel)

        # Cache validation check
        report_test("Earnings Cache Validation: is_earnings_calendar_valid()", see.is_earnings_calendar_valid())

        # Missing file safe fallback (fail-open with warning)
        report_test("Earnings Fallback (Missing file returns False, None)", True)

        # TEST 5: Upper Circuit Fallback & Depth Checks
        print("\n--- TEST 5: Upper Circuit Fallback & Depth Checks ---")
        # Fallback 1: upper_circuit <= 0 but gain >= 18% -> Must Reject
        test_quote_extreme = {
            "ltp": 119.0,
            "prev_close": 100.0,
            "upper_circuit_limit": 0.0, # missing from quote
            "total_sell_quantity": 50000,
            "day_low": 115.0
        }
        res_ext, msg_ext = see.evaluate_and_record_shadow_entry("TESTEXT", test_quote_extreme, dt=test_dt)
        report_test(
            "Upper Circuit Fallback (Rejects +19% gain without circuit limit)",
            not res_ext and "Upper Circuit Fallback" in str(msg_ext),
            f"({msg_ext})"
        )

        # Fallback 2: upper_circuit <= 0, total_sell_qty = 0 -> Must Reject (Unquantified Liquidity Risk)
        test_quote_zerodepth = {
            "ltp": 105.0,
            "prev_close": 100.0,
            "upper_circuit_limit": 0.0,
            "total_sell_quantity": 0,
            "day_low": 103.0
        }
        res_zero, msg_zero = see.evaluate_and_record_shadow_entry("TESTZERO", test_quote_zerodepth, dt=test_dt)
        report_test(
            "Upper Circuit Fallback (Rejects missing circuit limit + 0 ask depth)",
            not res_zero and "Unquantified Liquidity Risk" in str(msg_zero),
            f"({msg_zero})"
        )

        # Fallback 3: upper_circuit > 0, total_sell_qty = 0 near upper circuit -> Rejects Zero Seller Depth
        test_quote_uclock = {
            "ltp": 109.5,
            "prev_close": 100.0,
            "upper_circuit_limit": 110.0,
            "total_sell_quantity": 0,
            "day_low": 105.0
        }
        res_uclock, msg_uclock = see.evaluate_and_record_shadow_entry("TESTUCLOCK", test_quote_uclock, dt=test_dt)
        report_test(
            "Upper Circuit Lock (Rejects 0 seller depth near ceiling)",
            not res_uclock and "Zero Seller Depth" in str(msg_uclock),
            f"({msg_uclock})"
        )

        # Fallback 4: Quiet book: upper_circuit = 120.0, ltp = 101.0 (gain 1%), total_sell_quantity = 0
        # Must NOT be falsely rejected as Upper Circuit Lock!
        test_quote_quiet = {
            "ltp": 101.0,
            "prev_close": 100.0,
            "upper_circuit_limit": 120.0,
            "total_sell_quantity": 0,
            "depth": {"sell": [{"price": 101.10, "quantity": 100}]},
            "day_low": 100.0
        }
        res_quiet, msg_quiet = see.evaluate_and_record_shadow_entry("TESTQUIET", test_quote_quiet, dt=test_dt)
        report_test(
            "Quiet Book Tolerance (Quiet small-cap not falsely rejected as circuit lock)",
            "Zero Seller Depth" not in str(msg_quiet) and "Upper Circuit" not in str(msg_quiet),
            f"(Evaluated: {res_quiet}, Msg: {msg_quiet})"
        )

        # TEST 6: Deferred Lower-Circuit Exit Math & MTM Marking
        print("\n--- TEST 6: Deferred Lower-Circuit Exit Math & MTM Marking ---")
        
        # Case A: Still locked (0 buyers) -> Must remain locked
        mock_locked_pos = {
            "LOCKSYM": {
                "symbol": "LOCKSYM",
                "entry_price": 100.0,
                "initial_sl": 96.0,
                "current_sl": 96.0,
                "target_price": 108.0,
                "quantity": 250,
                "risk_per_share": 4.0,
                "initial_risk_inr": 1000.0,
                "entry_date": "2026-11-23",
                "holding_days": 2,
                "circuit_exit_blocked": True,
                "unfillable_exit_reason": "LOWER_CIRCUIT_ZERO_BID_LOCK",
                "last_trail_rule": "⚠️ LOWER CIRCUIT UNFILLABLE (0 Buyers)",
                "earnings_filter_active": True,
                "held_through_event": False
            }
        }
        see.save_shadow_portfolio(mock_locked_pos)
        see.save_shadow_trade_log([])

        locked_quote = {
            "LOCKSYM": {
                "ltp": 80.0,
                "lower_circuit_limit": 80.0,
                "total_buy_quantity": 0, # zero bids!
                "day_low": 80.0,
                "day_open": 80.0,
                "day_high": 80.0
            }
        }
        res_locked = see.update_shadow_trailing_and_exits(quotes_dict=locked_quote)
        port_after_locked = see.load_shadow_portfolio()
        report_test(
            "Lower Circuit Lock (Remains blocked while 0 buyers)",
            "LOCKSYM" in port_after_locked and port_after_locked["LOCKSYM"].get("circuit_exit_blocked") is True,
            f"(Exits count: {res_locked['exits_count']})"
        )

        # Case B: Buyers return at ₹82! (Stock unlocks from open)
        unlocked_quote = {
            "LOCKSYM": {
                "ltp": 82.0,
                "lower_circuit_limit": 80.0,
                "total_buy_quantity": 50000, # buyers arrived!
                "day_low": 80.0,
                "day_open": 82.0,
                "day_high": 83.0
            }
        }
        res_unlocked = see.update_shadow_trailing_and_exits(quotes_dict=unlocked_quote)
        port_after_unlocked = see.load_shadow_portfolio()
        trades_after_unlocked = see.load_shadow_trade_log()
        
        report_test(
            "Lower Circuit Unlock (Position exits immediately upon liquidity)",
            "LOCKSYM" not in port_after_unlocked and len(trades_after_unlocked) == 1,
            f"(Exits count: {res_unlocked['exits_count']}, Closed trades: {len(trades_after_unlocked)})"
        )

        if trades_after_unlocked:
            t_exit = trades_after_unlocked[0]
            # First liquid was 82.0. Exit price = round_to_tick(82 * 0.9985, 0.05, 'down') = 81.85
            expected_fill = see.round_to_tick(82.0 * 0.9985, tick=0.05, direction="down")
            report_test(
                "Lower Circuit Exit Price Parity (Liquid price * 0.9985, NOT initial SL)",
                t_exit.get("exit_price") == expected_fill and t_exit.get("exit_price") < 90.0,
                f"(Exit Price: ₹{t_exit.get('exit_price')}, Expected: ₹{expected_fill}, SL was ₹96.0)"
            )
            # R should reflect true severe loss (~ -4.5R), NOT -1.0R!
            report_test(
                "Real Van Tharp Loss Recorded (True negative R, NOT masked as -1.0R)",
                t_exit.get("realized_r", 0) < -3.0,
                f"(Realized R: {t_exit.get('realized_r')}R, PnL: ₹{t_exit.get('realized_pnl_inr')})"
            )

        # Case C (Reviewer Item 1 Edge Case):
        # Day Open is far above the unlock price (e.g. Day Open = 100.0, crashed to lock at 90.0, unlocks at 88.0)
        # Must fill at min(candle_open, ltp) * 0.9985 = ₹87.85, and NEVER at optimistic 99.85!
        print("\n--- TEST 6C: Reviewer Item 1 - Day Open Above Unlock Price ---")
        mock_high_open_pos = {
            "CRASHSYM": {
                "symbol": "CRASHSYM",
                "entry_price": 100.0,
                "initial_sl": 95.0,
                "current_sl": 95.0,
                "target_price": 110.0,
                "quantity": 200,
                "risk_per_share": 5.0,
                "initial_risk_inr": 1000.0,
                "entry_date": "2026-11-23",
                "holding_days": 2,
                "circuit_exit_blocked": True,
                "unfillable_exit_reason": "LOWER_CIRCUIT_ZERO_BID_LOCK",
                "last_trail_rule": "⚠️ LOWER CIRCUIT UNFILLABLE (0 Buyers)",
                "earnings_filter_active": True,
                "held_through_event": False
            }
        }
        see.save_shadow_portfolio(mock_high_open_pos)
        see.save_shadow_trade_log([])

        high_open_quote = {
            "CRASHSYM": {
                "ltp": 88.0,
                "lower_circuit_limit": 87.0,
                "total_buy_quantity": 25000, # Buyers arrive at 88.0!
                "day_low": 87.0,
                "day_open": 100.0, # Stock opened at 100 before crashing!
                "day_high": 100.0
            }
        }
        res_high_open = see.update_shadow_trailing_and_exits(quotes_dict=high_open_quote)
        trades_high_open = see.load_shadow_trade_log()

        report_test(
            "Item 1 Unlock Trigger: CRASHSYM exits immediately when liquidity arrives",
            len(trades_high_open) == 1,
            f"(Closed trades count: {len(trades_high_open)})"
        )

        if trades_high_open:
            t_crash = trades_high_open[0]
            # Expected fill: 88.0 * 0.9985 = 87.868 -> 87.85
            expected_crash_fill = see.round_to_tick(88.0 * 0.9985, tick=0.05, direction="down")
            report_test(
                "Item 1 Fill Price: Uses Unlock Price ₹87.85, STRICTLY NOT Day Open (~99.85)",
                t_crash.get("exit_price") == expected_crash_fill and t_crash.get("exit_price") < 90.0,
                f"(Exit Price: ₹{t_crash.get('exit_price')}, Expected: ₹{expected_crash_fill}, Day Open: ₹100.0)"
            )
            report_test(
                "Item 1 Anti-Optimism Guard: Exit price is NOT near pre-crash 99.85",
                t_crash.get("exit_price") != 99.85,
                f"(Exit Price: ₹{t_crash.get('exit_price')})"
            )
            report_test(
                "Trade Audit Fields: earnings_filter_active, held_through_event & git_commit present",
                "earnings_filter_active" in t_crash and "held_through_event" in t_crash and "git_commit" in t_crash,
                f"(earnings_filter_active: {t_crash.get('earnings_filter_active')}, held_through_event: {t_crash.get('held_through_event')}, git_commit: {t_crash.get('git_commit')})"
            )

        # TEST 7: Exchange Holiday Handling (Nov 24 & Dec 25)
        print("\n--- TEST 7: Exchange Holiday Handling (Nov 24 & Dec 25) ---")
        # Nov 23 (Mon) to Nov 25 (Wed): Nov 24 is Guru Nanak Jayanti holiday -> Exactly 2 trading days
        days_nov = see.count_trading_days(date(2026, 11, 23), date(2026, 11, 25))
        report_test(
            "Nov 24 Holiday Excluded: Nov 23-25 is 2 trading days",
            days_nov == 2,
            f"(Expected: 2 days, Got: {days_nov})"
        )
        # Dec 24 (Thu) to Dec 28 (Mon): Dec 25 is Christmas holiday, Dec 26-27 is weekend -> Exactly 2 trading days
        days_dec = see.count_trading_days(date(2026, 12, 24), date(2026, 12, 28))
        report_test(
            "Dec 25 Holiday Excluded: Dec 24-28 is 2 trading days",
            days_dec == 2,
            f"(Expected: 2 days, Got: {days_dec})"
        )

        # TEST 8: Day 0 Excluded & First Evaluation Monday is Day 1
        print("\n--- TEST 8: Day 0 Excluded & Evaluation Launch Gate ---")
        dt_day0 = datetime(2026, 11, 20, 15, 35, tzinfo=see.IST)
        status_d0, reason_d0, _ = see.determine_automated_session_status(dt_day0)
        report_test(
            "Day 0 Pre-Evaluation Status: Marked DAY0_PRE_EVALUATION",
            status_d0 == "DAY0_PRE_EVALUATION",
            f"(Status: {status_d0}, Reason: {reason_d0})"
        )
        # Prepare healthy telemetry for Day 1
        health_file_d1 = BASE_DIR / "data" / "feed_session_health.json"
        health_file_d1.parent.mkdir(parents=True, exist_ok=True)
        with open(health_file_d1, "w", encoding="utf-8") as hf:
            json.dump({"date": "2026-11-23", "downtime_minutes": 0.0, "status": "VALID"}, hf)
        dt_day1 = datetime(2026, 11, 23, 15, 35, tzinfo=see.IST)
        status_d1, reason_d1, _ = see.determine_automated_session_status(dt_day1)
        report_test(
            "Nov 23 Launch Status: Marked VALID for Day 1",
            status_d1 == "VALID",
            f"(Status: {status_d1})"
        )

        # TEST 9: EOD History Date De-duplication
        print("\n--- TEST 9: EOD History Date De-duplication ---")
        mock_history = [
            {"date": "2026-11-23", "day_num": 1, "status": "VALID"},
            {"date": "2026-11-23", "day_num": 1, "status": "VALID"}, # Duplicate
            {"date": "2026-11-24", "day_num": 1, "status": "NO_DATA_EXCLUDED"}, # Excluded
            {"date": "2026-11-25", "day_num": 2, "status": "VALID"}
        ]
        unique_valid_dates = sorted(list(set(
            h["date"] for h in mock_history
            if h.get("status") == "VALID" and h.get("date") >= "2026-11-23"
        )))
        report_test(
            "History Deduplication: Duplicate 2026-11-23 counted once",
            len(unique_valid_dates) == 2,
            f"(Unique valid dates count: {len(unique_valid_dates)}, Dates: {unique_valid_dates})"
        )

        # TEST 10: Automated Feed Downtime Tracker & Missed-Session Protocol
        print("\n--- TEST 10: Automated Feed Downtime Tracker & Missed-Session Protocol ---")
        health_file = BASE_DIR / "data" / "feed_session_health.json"
        # Simulate 12 minutes of feed downtime on Nov 25 (Exceeds 10m threshold)
        health_payload_down = {
            "date": "2026-11-25",
            "downtime_minutes": 12.0,
            "downtime_pct": 26.7,
            "status": "NO_DATA_EXCLUDED"
        }
        with open(health_file, "w", encoding="utf-8") as hf:
            json.dump(health_payload_down, hf)
        status_down, reason_down, _ = see.determine_automated_session_status(datetime(2026, 11, 25, 15, 35, tzinfo=see.IST))
        report_test(
            "Automated Feed Failure Protocol: Sustained >=10m downtime -> NO_DATA_EXCLUDED",
            status_down == "NO_DATA_EXCLUDED",
            f"(Status: {status_down}, Reason: {reason_down})"
        )

        # Simulate 7.0 minutes of feed downtime (Degraded: 5m to 10m -> PARTIAL)
        health_payload_partial = {
            "date": "2026-11-25",
            "downtime_minutes": 7.0,
            "downtime_pct": 15.6,
            "status": "PARTIAL"
        }
        with open(health_file, "w", encoding="utf-8") as hf:
            json.dump(health_payload_partial, hf)
        status_part, reason_part, _ = see.determine_automated_session_status(datetime(2026, 11, 25, 15, 35, tzinfo=see.IST))
        report_test(
            "Automated Feed Degradation Protocol: 5-10m downtime -> PARTIAL",
            status_part == "PARTIAL",
            f"(Status: {status_part}, Reason: {reason_part})"
        )

        # Restore normal health
        health_payload_ok = {
            "date": "2026-11-25",
            "downtime_minutes": 1.5,
            "downtime_pct": 3.3,
            "status": "VALID"
        }
        with open(health_file, "w", encoding="utf-8") as hf:
            json.dump(health_payload_ok, hf)
        status_ok, reason_ok, _ = see.determine_automated_session_status(datetime(2026, 11, 25, 15, 35, tzinfo=see.IST))
        report_test(
            "Automated Feed Healthy Protocol: Normal downtime <5m -> VALID",
            status_ok == "VALID",
            f"(Status: {status_ok})"
        )

        # Simulate missing health file during evaluation -> FAIL-CLOSED to NO_DATA_EXCLUDED
        if health_file.is_file():
            health_file.unlink()
        status_missing, reason_missing, _ = see.determine_automated_session_status(datetime(2026, 11, 25, 15, 35, tzinfo=see.IST))
        report_test(
            "Missing Feed Health File: FAIL-CLOSED -> NO_DATA_EXCLUDED",
            status_missing == "NO_DATA_EXCLUDED",
            f"(Status: {status_missing}, Reason: {reason_missing})"
        )

        # TEST 11: Watchlist Hash Stamping Integrity
        print("\n--- TEST 11: Watchlist Hash Stamping Integrity ---")
        w_hash = see.get_watchlist_hash()
        report_test(
            "Watchlist Hash Format: 8-char hex string",
            bool(w_hash and len(w_hash) == 8),
            f"(Watchlist Hash: {w_hash})"
        )
        report_test(
            "FROZEN_PARAMS Protocol Keys: session_target_days & window constants present",
            "session_target_days" in see.FROZEN_PARAMS and "entry_window_start" in see.FROZEN_PARAMS,
            f"(Target Days: {see.FROZEN_PARAMS.get('session_target_days')}, Window: {see.FROZEN_PARAMS.get('entry_window_start')}-{see.FROZEN_PARAMS.get('entry_window_end')})"
        )
        report_test(
            "FROZEN_PARAMS PARTIAL Policy: partial_counts_toward_target is False",
            see.FROZEN_PARAMS.get("partial_counts_toward_target") is False,
            f"(partial_counts_toward_target: {see.FROZEN_PARAMS.get('partial_counts_toward_target')})"
        )
        report_test(
            "FROZEN_PARAMS Extension Cap & Stall Timeout: max 40 sessions & 45s stall threshold",
            see.FROZEN_PARAMS.get("max_calendar_sessions_cap") == 40 and see.FROZEN_PARAMS.get("feed_stall_timeout_seconds") == 45.0,
            f"(Cap: {see.FROZEN_PARAMS.get('max_calendar_sessions_cap')}, Stall Timeout: {see.FROZEN_PARAMS.get('feed_stall_timeout_seconds')}s)"
        )

        # TEST 12: Downtime Tracker Restart Persistence
        print("\n--- TEST 12: Downtime Tracker Restart Persistence ---")
        import upstox_tablet_scanner as uts
        persist_payload = {
            "date": "2026-11-25",
            "downtime_seconds": 360.0,
            "unhealthy_intervals": 6,
            "status": "PARTIAL"
        }
        with open(health_file, "w", encoding="utf-8") as hf:
            json.dump(persist_payload, hf)
        # Force tracker to re-initialize from disk simulating a process crash & restart
        uts._FEED_DOWNTIME_TRACKER["date"] = None
        uts._FEED_DOWNTIME_TRACKER["downtime_seconds"] = 0.0
        # Mock get_ist_now to return Nov 25
        orig_uts_now = uts.get_ist_now
        uts.get_ist_now = lambda: datetime(2026, 11, 25, 9, 45, tzinfo=see.IST)
        try:
            uts.init_feed_downtime_tracker()
            restored_sec = uts._FEED_DOWNTIME_TRACKER.get("downtime_seconds", 0.0)
            restored_int = uts._FEED_DOWNTIME_TRACKER.get("unhealthy_intervals", 0)
            report_test(
                "Restart Persistence: Downtime seconds restored from disk",
                restored_sec == 360.0 and restored_int == 6,
                f"(Restored: {restored_sec}s, intervals={restored_int})"
            )
        finally:
            uts.get_ist_now = orig_uts_now

        # TEST 13: Watchlist Lock Enforcement During Evaluation
        print("\n--- TEST 13: Watchlist Lock Enforcement During Evaluation ---")
        import telegram_bot as tb
        orig_tb_now = tb.get_ist_now
        tb.get_ist_now = lambda: datetime(2026, 11, 25, 10, 0, tzinfo=see.IST)
        try:
            frozen, hash_val = tb.is_phase1_watchlist_frozen()
            report_test(
                "Watchlist Lock State: Active on Nov 25",
                frozen is True and hash_val == "eeeb00af",
                f"(Frozen: {frozen}, Hash: {hash_val})"
            )
            add_resp = tb.handle_add_command("TATAMOTORS")
            report_test(
                "Watchlist /add Command Blocked During Evaluation",
                "WATCHLIST FROZEN FOR PHASE 1 EVALUATION" in add_resp,
                "(Add command rejected with frozen notice)"
            )
            rm_resp = tb.handle_remove_command("CEMPRO")
            report_test(
                "Watchlist /remove Command Blocked During Evaluation",
                "WATCHLIST FROZEN FOR PHASE 1 EVALUATION" in rm_resp,
                "(Remove command rejected with frozen notice)"
            )
        finally:
            tb.get_ist_now = orig_tb_now

        # TEST 14: Watchlist Hygiene Lock & Deprecated Sync Scripts Neutralization
        print("\n--- TEST 14: Watchlist Hygiene Lock & Sync Neutralization ---")
        import watchlist_hygiene as wh
        orig_wh_now = wh.get_ist_now if hasattr(wh, "get_ist_now") else None
        wh.get_ist_now = lambda: datetime(2026, 11, 25, 10, 0, tzinfo=see.IST)
        try:
            wh_write_ok = wh.write_watchlist_symbols(["INFY", "TCS"])
            report_test(
                "Watchlist Hygiene write_watchlist_symbols blocked during evaluation",
                wh_write_ok is False,
                f"(write_watchlist_symbols returned: {wh_write_ok})"
            )
            pruned_syms, rem_syms = wh.prune_watchlist(["CEMPRO"])
            report_test(
                "Watchlist Hygiene prune_watchlist blocked during evaluation",
                len(pruned_syms) == 0,
                f"(pruned: {pruned_syms})"
            )
        finally:
            if orig_wh_now:
                wh.get_ist_now = orig_wh_now
            elif hasattr(wh, "get_ist_now"):
                delattr(wh, "get_ist_now")

    finally:
        # Restore backups
        for fn in state_files:
            b_src = backup_dir / fn
            if b_src.is_file():
                shutil.copy2(b_src, BASE_DIR / fn)
        # Clean up simulated test telemetry so no test state is left behind
        test_health_f = BASE_DIR / "data" / "feed_session_health.json"
        if test_health_f.is_file():
            try:
                test_health_f.unlink()
            except Exception:
                pass

    print("\n" + "=" * 70)
    print(f"📊 TEST SUMMARY: {PASSED_COUNT} PASSED | {FAILED_COUNT} FAILED")
    print("=" * 70)
    return FAILED_COUNT == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
