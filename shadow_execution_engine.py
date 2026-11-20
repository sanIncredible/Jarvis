"""
Jarvis Phase 1: Autonomous Shadow Execution Engine
===================================================
Autonomous Paper Trading Engine for Positional / Swing Breakout Setups.

Key Specifications & Edge-Case Protections:
1. Entry Window: Strictly 09:30:00 to 10:15:00 IST (Mon-Fri).
2. Sizing Model: Strictly R-Multiples ($1R = ₹1,000 fixed risk per trade).
3. Strategy Sieve: 11-Point Technical Checklist + Situational Awareness (SA) Regime.
4. Uncapped Capacity: Captures all qualified setups to record true statistical edge over 30 days.
5. Edge-Case Guards:
   - Same-Day Re-Entry Trap: Blocks re-entering a symbol that already traded/exited today.
   - Stop-Loss Sanitization: Guards against LOD >= FillPrice and division-by-zero.
   - Penny Stock Collar: Enforces minimum price threshold (LTP >= ₹20).
   - Realistic Overnight Gap-Down Slippage: If market opens below SL on Day 2+, exits at Day Open.
   - Session-Based Holding Days: Counts business/trading days (excluding weekends/holidays).
   - Live EMA Resolution: Resolves 10 EMA & 20 EMA from data.json cache / daily bars.
   - Thread-Safe Atomic Writes: Protects JSON ledgers from process interruption or race conditions.
   - Day 30 Milestone Banner: Flags mature benchmark completion on Day 30.
6. Multi-Day Swing Trailing Engine:
   - Day 1: Structural LOD Stop (Full breathing room, zero premature choking).
   - Day 1 Close: Day-1 Spurt Shield (+4.5% on heavy volume -> trailed to breakeven).
   - Day 2+: 10 EMA / 20 EMA Trailing Stop along swing structure.
   - Extensions: Parabolic 5 EMA exit & 30% profit target cap.
7. Automated EOD Report: Dispatches daily at 15:35 IST directly to Telegram Topic 11 ('reports').
8. Isolated Storage: shadow_portfolio.json, shadow_trade_log.json, shadow_history_eod.json.
"""

import os
import sys
import json
import time
import math
import tempfile
import threading
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path

# Safe Windows console output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
SHADOW_PORTFOLIO_FILE = BASE_DIR / "shadow_portfolio.json"
SHADOW_LOG_FILE = BASE_DIR / "shadow_trade_log.json"
SHADOW_EOD_FILE = BASE_DIR / "shadow_history_eod.json"
DATA_FILE = BASE_DIR / "data.json"

FIXED_RISK_PER_TRADE_INR = 1000.0  # 1.0R = ₹1,000 INR
START_DATE_STR = "2026-11-20"
EVALUATION_HORIZON_DAYS = 30

IST = timezone(timedelta(hours=5, minutes=30))
SHADOW_LOCK = threading.RLock()

SYMBOL_ALIASES = {
    "M&M": "M_M",
    "M_M": "M_M",
    "BAJAJ-AUTO": "BAJAJ_AUTO",
    "BAJAJ_AUTO": "BAJAJ_AUTO",
    "L&TFH": "L_TFH",
    "L_TFH": "L_TFH",
    "M&MFIN": "M_MFIN",
    "M_MFIN": "M_MFIN"
}


def resolve_symbol(symbol):
    """Normalizes symbol aliases cleanly for uniform dictionary and file lookups."""
    if not symbol:
        return ""
    s = str(symbol).strip().upper()
    return SYMBOL_ALIASES.get(s, s)


def get_ist_now():
    """Returns current datetime in Indian Standard Time (UTC+5:30)."""
    return datetime.now(timezone.utc).astimezone(IST)


def round_to_clean_int(val):
    """Rounds float price to nearest whole integer."""
    if val is None:
        return 0
    try:
        return int(round(float(val)))
    except Exception:
        return 0


NSE_HOLIDAYS_2026 = {
    "2026-01-26", "2026-03-03", "2026-03-20", "2026-03-27", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-27", "2026-08-15", "2026-09-04",
    "2026-10-02", "2026-10-20", "2026-11-08", "2026-11-10", "2026-11-24", "2026-12-25"
}


def count_trading_days(date_start, date_end):
    """Counts actual trading days (Monday to Friday, excluding exchange holidays) between two dates inclusive."""
    if date_start > date_end:
        return 1
    cur = date_start
    days = 0
    while cur <= date_end:
        if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in NSE_HOLIDAYS_2026:
            days += 1
        cur += timedelta(days=1)
    return max(1, days)


def atomic_write_json(file_path: Path, data):
    """Atomically writes JSON to disk using a temporary file to prevent corruption."""
    try:
        dir_name = file_path.parent
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, str(file_path))
        return True
    except Exception as ex:
        print(f"Error atomic writing {file_path.name}: {ex}")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False


def load_config():
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_shadow_portfolio():
    """Loads active open swing shadow positions (thread-safe)."""
    with SHADOW_LOCK:
        if SHADOW_PORTFOLIO_FILE.is_file():
            try:
                with open(SHADOW_PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def save_shadow_portfolio(data):
    """Persists active open swing shadow positions (thread-safe & atomic)."""
    with SHADOW_LOCK:
        return atomic_write_json(SHADOW_PORTFOLIO_FILE, data)


def load_shadow_trade_log():
    """Loads closed trade log (thread-safe)."""
    with SHADOW_LOCK:
        if SHADOW_LOG_FILE.is_file():
            try:
                with open(SHADOW_LOG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []


def save_shadow_trade_log(data):
    """Persists closed trade log (thread-safe & atomic)."""
    with SHADOW_LOCK:
        return atomic_write_json(SHADOW_LOG_FILE, data)


def get_cached_symbol_metrics(symbol):
    """Retrieves cached EMA10, EMA20, and daily metrics from data.json."""
    if not DATA_FILE.is_file():
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        sym_u = symbol.strip().upper()
        for s in d.get("stocks", []):
            if str(s.get("symbol", "")).upper() == sym_u:
                return s
    except Exception:
        pass
    return {}


def send_phase1_telegram_alert(message_html, topic_name="reports"):
    """
    Dispatches Telegram message directly to Topic 11 ('reports') or designated topic.
    Includes message length safety (< 3900 chars) and plain text fallback on entity parse errors.
    """
    try:
        cfg = load_config()
        tg = cfg.get("telegram", {})
        if not tg.get("enabled", True):
            return False, "Telegram disabled"
        bot_token = tg.get("bot_token")
        chat_id = tg.get("group_id") or tg.get("chat_id")
        if not bot_token or not chat_id:
            return False, "Missing bot_token or chat_id"

        topics = tg.get("topics", {})
        thread_id = topics.get(topic_name, 11)  # Default Topic 11 'reports'

        # Safeguard against 4096 character limit
        text_to_send = message_html
        if len(text_to_send) > 3900:
            text_to_send = text_to_send[:3900] + "\n\n<i>... [Report truncated to fit Telegram limit]</i>"

        import urllib.request
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text_to_send,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if thread_id:
            payload["message_thread_id"] = int(thread_id)

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "Jarvis-ShadowEngine"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201), "OK"
        except Exception as parse_err:
            # Fallback: Retry with plain text without HTML parse_mode in case of malformed entity
            if "400" in str(parse_err):
                import re
                clean_text = re.sub(r"<[^>]+>", "", text_to_send)
                payload["text"] = clean_text
                payload.pop("parse_mode", None)
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data_bytes,
                    headers={"Content-Type": "application/json", "User-Agent": "Jarvis-ShadowEngine"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status in (200, 201), "OK (Plaintext Fallback)"
            raise parse_err
    except Exception as ex:
        return False, str(ex)


def is_entry_window_active(dt=None):
    """
    User Mandate: Entry timing is strictly from 09:30 to 10:15 AM IST (Mon-Fri).
    """
    if dt is None:
        dt = get_ist_now()

    # Mon=0, Fri=4, Sat=5, Sun=6
    if dt.weekday() >= 5:
        return False

    t = dt.time()
    t_start = dtime(9, 30, 0)
    t_end = dtime(10, 15, 0)
    return t_start <= t <= t_end


def evaluate_and_record_shadow_entry(symbol, quote_data, trigger_price=None, day_low=None, regime_code="EXPANSION", trigger_name="ORB Breakout"):
    """
    Evaluates candidate breakout against strategy checklist and logs paper fill if qualified.
    Runs strictly during 09:30 - 10:15 AM IST.
    Guards against:
    - Outside prime window
    - Already open positions
    - Same-day re-entry whipsaw traps
    - Bad stop loss data (LOD >= fill price)
    - Division-by-zero
    - Micro-penny stocks (< ₹20)
    """
    sym = resolve_symbol(symbol).strip().upper()
    if not sym:
        return False, "Invalid symbol"

    now = get_ist_now()
    if not is_entry_window_active(now):
        t_str = now.strftime("%H:%M:%S")
        return False, f"Outside 09:30-10:15 AM momentum entry window (Current: {t_str})"

    # SA Regime Guard: No long breakouts during Panic Selling / Climax Washout
    reg_u = str(regime_code or "EXPANSION").upper()
    if reg_u in ("WASHOUT", "CLIMAX", "DEFENSIVE_WATERFALL"):
        return False, f"SA Regime Bunker Mode ({reg_u}): New long entries strictly blocked"

    portfolio = load_shadow_portfolio()
    if sym in portfolio:
        return False, f"{sym} already held in active shadow portfolio"

    # Edge Case Guard 1: Same-Day Re-Entry Trap (Check both entry_date and exit_date)
    today_str = now.strftime("%Y-%m-%d")
    trade_log = load_shadow_trade_log()
    already_traded_today = any(t.get("symbol") == sym and (t.get("entry_date") == today_str or t.get("exit_date") == today_str) for t in trade_log)
    if already_traded_today:
        return False, f"{sym} already entered/exited today (Whipsaw protection: 1 trade per symbol per session)"

    ltp = float(trigger_price or quote_data.get("ltp") or 0.0)
    if ltp <= 0:
        return False, "Invalid LTP"

    # Edge Case Guard 2: Penny Stock Collar
    if ltp < 20.0:
        return False, f"Penny stock filter: {sym} LTP ₹{ltp:.2f} < ₹20 threshold"

    # Realistic Marketable Fill (+0.15% slippage collar)
    fill_price = round_to_clean_int(ltp * 1.0015)

    # Initial Structural Stop Loss: Day Low at trigger moment with buffer
    dl = float(day_low or quote_data.get("day_low") or (fill_price * 0.975))
    buffer = max(1.0, round(dl * 0.002, 2))
    initial_sl = round_to_clean_int(dl - buffer)

    # Edge Case Guard 3: Stop-Loss Sanitization (Ensure SL is strictly at least ₹1 below fill price)
    if initial_sl >= fill_price:
        initial_sl = fill_price - 1

    # Risk distance per share (ensures min 1.0 to prevent division by zero)
    risk_per_share = max(1.0, float(fill_price - initial_sl))
    risk_pct = round((risk_per_share / fill_price) * 100.0, 2)

    # Edge Case Guard 4: Excessive Stop Distance Rejection (Checklist Rule 6: <= 4.0% Limit)
    if risk_pct > 4.0:
        return False, f"Wide Stop-Loss: Distance to Day Low is {risk_pct:.1f}% (> 4.0% limit). Capital preserved against excessive tail risk."

    # P0-11: Standardized 1.0R = ₹1,000 Position Sizing with Institutional ATR Risk Floor
    atr_val = (quote_data or {}).get("atr14") or (quote_data or {}).get("atr_3m")
    if not atr_val:
        sc_d = get_cached_symbol_metrics(sym) or {}
        atr_val = sc_d.get("atr14")
    atr_14_f = float(atr_val) if (atr_val and float(atr_val) > 0) else (fill_price * 0.02)
    effective_risk_dist = max(risk_per_share, atr_14_f * 0.75, 1.0)
    qty = max(1, int(FIXED_RISK_PER_TRADE_INR // effective_risk_dist))
    target_price = round_to_clean_int(fill_price + (2.0 * risk_per_share))
    capital_invested = round_to_clean_int(qty * fill_price)
    initial_risk_inr = max(1.0, float(round_to_clean_int(qty * risk_per_share)))

    # P0-7: Strategy Checklist (Hard Gates vs Soft Scores)
    ck_note = "Qualified Playbook Setup"
    try:
        from order_engine import evaluate_strategy_checklist
        ck = evaluate_strategy_checklist(sym, quote_data=quote_data, calc_data={"ltp": fill_price, "day_low": initial_sl, "day_high": float((quote_data or {}).get("day_high") or fill_price), "risk_pct": risk_pct})
        
        # 1. Enforce Hard Gates (Must All Pass)
        if not ck.get("hard_gates_passed", True):
            failed_gates = ck.get("failed_hard_gates", [])
            return False, f"Checklist Hard Gate failed: {', '.join(failed_gates)}"

        soft_score = ck.get("soft_score", 0)
        soft_total = ck.get("soft_total", 7)
        ck_note = f"Hard Gates PASSED ✅ | Quality: {soft_score}/{soft_total} ⭐"

        # 2. Minimum Soft Score Conviction threshold (At least 2 quality points required)
        if soft_score < 2:
            return False, f"Checklist conviction low ({soft_score}/{soft_total} < 2 required)"
    except Exception:
        pass

    entry_record = {
        "symbol": sym,
        "entry_price": fill_price,
        "initial_sl": initial_sl,
        "current_sl": initial_sl,
        "target_price": target_price,
        "risk_per_share": round(risk_per_share, 2),
        "risk_pct": risk_pct,
        "quantity": qty,
        "initial_risk_inr": initial_risk_inr,
        "fixed_risk_inr": initial_risk_inr,
        "effective_risk_dist": round(effective_risk_dist, 2),
        "capital_invested": capital_invested,
        "entry_date": today_str,
        "entry_time": now.strftime("%H:%M:%S"),
        "highest_ltp": fill_price,
        "highest_r": 0.0,
        "last_trail_rule": "🛑 INITIAL STOP LOSS (Day Low Structural)",
        "holding_days": 1,
        "sa_regime": reg_u,
        "trigger_name": trigger_name,
        "checklist_note": ck_note,
        "status": "OPEN"
    }

    portfolio[sym] = entry_record
    save_shadow_portfolio(portfolio)

    # Dispatch Telegram Alert to Topic 11 ('reports')
    alert_html = (
        "🤖 <b>[PHASE 1 SHADOW ENTRY]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Symbol:</b> <b>{sym}</b> (Simulated Fill)\n"
        f"• <b>Entry Price:</b> ₹{fill_price:,} <i>(+0.15% slippage collar)</i>\n"
        f"• <b>Initial SL:</b> ₹{initial_sl:,} (-{risk_pct}% | LOD Support)\n"
        f"• <b>Quantity:</b> {qty} shares (<b>1.0R Risk: ₹{initial_risk_inr:,.0f}</b> | Floor: ₹{effective_risk_dist:.1f}/sh)\n"
        f"• <b>Checklist:</b> {ck_note}\n"
        f"• <b>2.0R Target:</b> ₹{target_price:,}\n"
        f"• <b>Capital Exposure:</b> ₹{capital_invested:,}\n"
        f"• <b>SA Market Regime:</b> {reg_u}\n"
        f"• <b>Trigger Signature:</b> {trigger_name}\n"
        f"• <b>Window:</b> {now.strftime('%H:%M:%S')} IST <i>(09:30–10:15 AM Momentum Zone)</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>True swing/positional shadow trade. Zero live capital risked.</i>"
    )
    send_phase1_telegram_alert(alert_html, topic_name="reports")
    return True, entry_record


def update_shadow_trailing_and_exits(quotes_dict=None):
    """
    Evaluates simulated swing positions across multi-day holding periods:
    - Day 1: Structural LOD stop (full breathing room).
    - Day-1 Spurt Shield: +4.5% gain on volume -> trailed to breakeven.
    - Day 2+: Trailed along 10 EMA / 20 EMA.
    - Extensions: Parabolic 5 EMA exit & 30% profit cap.
    - Realistic Overnight Gap-Down Slippage: If market opens below SL on Day 2+, exits at Day Open.
    - Simulated stop-loss / target breach detection.
    """
    portfolio = load_shadow_portfolio()
    if not portfolio:
        return {"active_count": 0, "exits_count": 0, "updates_count": 0}

    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")

    # Fetch live quotes if not provided
    if quotes_dict is None:
        try:
            from order_engine import fetch_live_quote
            quotes_dict = {}
            for sym in list(portfolio.keys()):
                q, _ = fetch_live_quote(sym)
                if q:
                    quotes_dict[sym] = q
        except Exception:
            quotes_dict = {}

    trade_log = load_shadow_trade_log()
    exited_symbols = []
    updates_count = 0

    for sym, pos in list(portfolio.items()):
        q = quotes_dict.get(sym, {})
        ltp = float(q.get("ltp") or 0.0)
        day_open = float(q.get("day_open") or 0.0)
        day_high = float(q.get("day_high") or ltp)
        day_low = float(q.get("day_low") or ltp)

        if ltp <= 0:
            continue

        entry_p = pos["entry_price"]
        current_sl = pos["current_sl"]
        target_p = pos["target_price"]
        risk_per_share = max(1.0, float(pos.get("risk_per_share") or 1.0))
        qty = pos["quantity"]
        entry_date = pos.get("entry_date", today_str)

        # Edge Case Guard 4: Trading Days (Excluding Weekends)
        try:
            d_entry = datetime.strptime(entry_date, "%Y-%m-%d").date()
            d_curr = now.date()
            holding_days = count_trading_days(d_entry, d_curr)
        except Exception:
            holding_days = pos.get("holding_days", 1)
        pos["holding_days"] = holding_days

        # Update peak LTP and peak R
        # Day 1: Track peak observed POST-ENTRY (ignore pre-entry 09:15-09:30 morning spikes)
        # Day 2+: Today's entire trading session is post-entry, so session day_high is valid
        if holding_days == 1:
            highest_ltp = max(pos.get("highest_ltp", entry_p), ltp)
        else:
            highest_ltp = max(pos.get("highest_ltp", entry_p), day_high, ltp)
        initial_risk_inr = max(1.0, float(pos.get("initial_risk_inr") or pos.get("fixed_risk_inr") or (qty * risk_per_share)))
        highest_r = round(max(0.0, (highest_ltp - entry_p) * qty) / initial_risk_inr, 2)
        pos["highest_ltp"] = highest_ltp
        pos["highest_r"] = highest_r

        # Multi-Day Trailing Stop Engine
        new_sl = current_sl
        new_rule = pos.get("last_trail_rule", "🛑 INITIAL STOP LOSS")

        gain_pct = round(((ltp - entry_p) / entry_p) * 100.0, 2)
        peak_gain_pct = round(((highest_ltp - entry_p) / entry_p) * 100.0, 2)

        ema10 = float(q.get("ema10") or 0.0)
        ema20 = float(q.get("ema20") or 0.0)
        ema5 = float(q.get("ema5") or 0.0)

        # Edge Case Guard 5: Resolve true Daily EMAs (10 EMA, 20 EMA, 5 EMA) via order_engine for swing runners
        if ema10 <= 0 or ema20 <= 0 or ema5 <= 0:
            try:
                from order_engine import get_daily_emas_and_atr
                d_emas = get_daily_emas_and_atr(sym)
                if ema10 <= 0 and d_emas.get("ema10"):
                    ema10 = float(d_emas["ema10"])
                if ema20 <= 0 and d_emas.get("ema20"):
                    ema20 = float(d_emas["ema20"])
                if ema5 <= 0 and d_emas.get("ema5"):
                    ema5 = float(d_emas["ema5"])
            except Exception:
                pass

        if ema10 <= 0 or ema20 <= 0:
            c_meta = get_cached_symbol_metrics(sym)
            if c_meta:
                if ema10 <= 0:
                    ema10 = float(c_meta.get("ema10") or 0.0)
                if ema20 <= 0:
                    ema20 = float(c_meta.get("ema20") or 0.0)
                if ema5 <= 0:
                    ema5 = float(c_meta.get("ema5") or 0.0)

        # Multi-Stage Swing Trailing Stop Hierarchy (NO premature choking / NO premature liquidation)
        # 1. 🛡️ 30% PROFIT CAP (Milestone: +28% gain or 8.0R reached -> lock +25% profit)
        if peak_gain_pct >= 28.0 or highest_r >= 8.0:
            rec_sl = round_to_clean_int(entry_p * 1.25)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "🛡️ 30% PROFIT CAP (Lock +25% Gains)"

        # 2. ⚡ PARABOLIC 5 EMA (Vertical Momentum: R >= 4.0 -> trail closely under 5 EMA)
        elif highest_r >= 4.0 and ema5 > 0:
            rec_sl = round_to_clean_int(ema5 * 0.995)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "⚡ PARABOLIC 5 EMA TRAIL"

        # 3. 🎯 STAGE 4: R >= 3.0 (Lock at least +2.0R guaranteed profit while riding 10 EMA)
        elif highest_r >= 3.0:
            floor_2r = round_to_clean_int(entry_p + (2.0 * risk_per_share))
            ema10_trail = round_to_clean_int(ema10 * 0.992) if ema10 > 0 else 0
            rec_sl = max(floor_2r, ema10_trail)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "🎯 STAGE 4: +2.0R LOCKED (Riding 10 EMA)"

        # 4. 🎯 STAGE 3: R >= 2.0 (Lock at least +1.0R guaranteed profit on the orderbook)
        elif highest_r >= 2.0:
            floor_1r = round_to_clean_int(entry_p + (1.0 * risk_per_share))
            ema10_trail = round_to_clean_int(ema10 * 0.992) if ema10 > 0 else 0
            rec_sl = max(floor_1r, ema10_trail)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "🎯 STAGE 3: +1.0R LOCKED (Swing Runner Protected)"

        # 5. 🚀 DAY-1 SPURT SHIELD (Surge of +4.5% on Day 1 -> ratchet to breakeven +0.2%)
        elif holding_days == 1 and peak_gain_pct >= 4.5:
            rec_sl = round_to_clean_int(entry_p * 1.002)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "🚀 DAY-1 SPURT SHIELD (+4.5% Surge -> Breakeven)"

        # 6. 🟢 10 EMA SWING TRAIL (Day 2+ trending position with R >= 1.5)
        elif holding_days >= 2 and highest_r >= 1.5 and ema10 > 0:
            rec_sl = round_to_clean_int(ema10 * 0.992)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "🟢 10 EMA SWING TRAIL"

        # 7. 🟢 20 EMA STRUCTURAL TRAIL (Day 3+ wider base runner with R >= 1.0)
        elif holding_days >= 3 and highest_r >= 1.0 and ema20 > 0:
            rec_sl = round_to_clean_int(ema20 * 0.990)
            if rec_sl > new_sl:
                new_sl = rec_sl
                new_rule = "🟢 20 EMA STRUCTURAL TRAIL"

        if new_sl > current_sl:
            pos["current_sl"] = new_sl
            pos["last_trail_rule"] = new_rule
            updates_count += 1

        # Check Simulated Exit Breaches
        exit_triggered = False
        exit_price = ltp
        exit_reason = ""

        # Structural Exit: Low breached the current trailed stop-loss
        is_sl_breached = False
        if holding_days == 1:
            # On Day 1: If stop was ratcheted above initial LOD stop (e.g. Day-1 Spurt Shield to BE),
            # exit only if current live LTP hits or drops below the stop.
            # Otherwise (initial LOD stop strictly below morning low), any session day_low breach is a valid structural stop hit!
            is_trailed = (pos["current_sl"] > pos["initial_sl"])
            if is_trailed:
                is_sl_breached = (ltp <= pos["current_sl"])
            else:
                is_sl_breached = (day_low <= pos["current_sl"])
        else:
            # Day 2+: Today's entire session is post-entry, so any day_low breach is a valid structural stop hit
            is_sl_breached = (day_low <= pos["current_sl"])

        if is_sl_breached:
            exit_triggered = True
            # Edge Case Guard 6: Realistic Overnight Gap-Down Slippage
            if holding_days >= 2 and day_open > 0 and day_open < pos["current_sl"]:
                exit_price = round_to_clean_int(min(day_open, ltp, pos["current_sl"]) * 0.9985)
            else:
                exit_price = round_to_clean_int(min(pos["current_sl"], ltp) * 0.9985)
            exit_reason = pos["last_trail_rule"]

        if exit_triggered:
            initial_risk_inr = max(1.0, float(pos.get("initial_risk_inr") or pos.get("fixed_risk_inr") or (qty * risk_per_share)))
            realized_pnl = round_to_clean_int((exit_price - entry_p) * qty)
            realized_r = round(realized_pnl / initial_risk_inr, 2)
            giveback_r = round(max(0.0, highest_r - realized_r), 2)

            log_entry = {
                "symbol": sym,
                "entry_date": entry_date,
                "exit_date": today_str,
                "entry_time": pos.get("entry_time"),
                "exit_time": now.strftime("%H:%M:%S"),
                "entry_price": entry_p,
                "exit_price": exit_price,
                "quantity": qty,
                "initial_risk_inr": initial_risk_inr,
                "holding_days": holding_days,
                "realized_pnl_inr": realized_pnl,
                "realized_r": realized_r,
                "peak_r": highest_r,
                "giveback_r": giveback_r,
                "exit_reason": exit_reason,
                "sa_regime": pos.get("sa_regime", "EXPANSION"),
                "trigger_name": pos.get("trigger_name", "ORB Breakout")
            }

            trade_log.append(log_entry)
            exited_symbols.append(sym)

            # Dispatch Exit Telegram Card to Topic 11 ('reports')
            pnl_s = f"+₹{realized_pnl:,}" if realized_pnl >= 0 else f"-₹{abs(realized_pnl):,}"
            r_s = f"+{realized_r:.2f}R" if realized_r >= 0 else f"{realized_r:.2f}R"
            badge = "🟢 PROFIT EXIT" if realized_r >= 0 else "🛑 STOP-LOSS EXIT"

            exit_html = (
                f"🏁 <b>[PHASE 1 SHADOW EXIT] — {badge}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Symbol:</b> <b>{sym}</b>\n"
                f"• <b>Entry:</b> ₹{entry_p:,} ➔ <b>Exit:</b> ₹{exit_price:,}\n"
                f"• <b>Realized Result:</b> <b>{r_s} ({pnl_s})</b>\n"
                f"• <b>Peak R Achieved:</b> +{highest_r:.2f}R <i>(Give-back: -{giveback_r:.2f}R)</i>\n"
                f"• <b>Holding Duration:</b> {holding_days} trading days\n"
                f"• <b>Exit Reason:</b> {exit_reason}\n"
                f"• <b>SA Regime:</b> {pos.get('sa_regime')}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Logged directly into 30-Day Autonomous Benchmark Ledger.</i>"
            )
            send_phase1_telegram_alert(exit_html, topic_name="reports")

    # Prune exited positions
    for s in exited_symbols:
        portfolio.pop(s, None)

    save_shadow_portfolio(portfolio)
    save_shadow_trade_log(trade_log)

    return {
        "active_count": len(portfolio),
        "exits_count": len(exited_symbols),
        "updates_count": updates_count,
        "exited_symbols": exited_symbols
    }


def get_shadow_analytics():
    """
    Computes comprehensive 30-day statistical performance:
    Win Rate %, Profit Factor, Expectancy R, Avg Win vs Avg Loss, Max Drawdown in R.
    """
    trades = load_shadow_trade_log()
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate_pct": 0.0,
            "net_pnl_inr": 0,
            "net_r": 0.0,
            "gross_profit_r": 0.0,
            "gross_loss_r": 0.0,
            "profit_factor": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "expectancy_r": 0.0,
            "max_drawdown_r": 0.0,
            "rule_counts": {}
        }

    wins = [t for t in trades if t.get("realized_r", 0) > 0]
    losses = [t for t in trades if t.get("realized_r", 0) <= 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total_trades) * 100.0, 1)

    gross_profit_r = sum(t.get("realized_r", 0) for t in wins)
    gross_loss_r = abs(sum(t.get("realized_r", 0) for t in losses))

    net_r = round(gross_profit_r - gross_loss_r, 2)
    net_pnl = sum(t.get("realized_pnl_inr", 0) for t in trades)

    profit_factor = round(gross_profit_r / gross_loss_r, 2) if gross_loss_r > 0 else (round(gross_profit_r, 2) if gross_profit_r > 0 else 0.0)
    avg_win_r = round(gross_profit_r / win_count, 2) if win_count > 0 else 0.0
    avg_loss_r = round(gross_loss_r / loss_count, 2) if loss_count > 0 else 0.0

    # Mathematical Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
    win_pct_dec = win_count / total_trades
    loss_pct_dec = loss_count / total_trades
    expectancy_r = round((win_pct_dec * avg_win_r) - (loss_pct_dec * avg_loss_r), 2)

    # Max Drawdown calculation in R
    peak_cum = 0.0
    running_cum = 0.0
    max_dd = 0.0
    for t in trades:
        running_cum += t.get("realized_r", 0)
        peak_cum = max(peak_cum, running_cum)
        dd = peak_cum - running_cum
        max_dd = max(max_dd, dd)

    # Rule breakdown
    rules = {}
    for t in trades:
        r = t.get("exit_reason", "OTHER")
        rules[r] = rules.get(r, 0) + 1

    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate_pct": win_rate,
        "net_pnl_inr": net_pnl,
        "net_r": net_r,
        "gross_profit_r": round(gross_profit_r, 2),
        "gross_loss_r": round(gross_loss_r, 2),
        "profit_factor": profit_factor,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy_r": expectancy_r,
        "max_drawdown_r": round(max_dd, 2),
        "rule_counts": rules
    }


def generate_and_send_phase1_eod_report(notify=True):
    """
    Compiles and dispatches the daily Phase 1 EOD Report strictly at 15:35 IST to Topic 11 ('reports').
    Features Day 30 Maturity Banner when 30 days are reached.
    """
    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")

    portfolio = load_shadow_portfolio()
    trade_log = load_shadow_trade_log()
    analytics = get_shadow_analytics()

    # Calculate current business/trading day in 30-day evaluation
    try:
        d_start = datetime.strptime(START_DATE_STR, "%Y-%m-%d").date()
        d_curr = now.date()
        day_num = count_trading_days(d_start, d_curr)
    except Exception:
        day_num = 1

    # Fetch live quotes for open positions to calculate unrealized PnL
    unrealized_r = 0.0
    unrealized_pnl = 0
    open_lines = []

    try:
        from order_engine import fetch_live_quote
    except Exception:
        fetch_live_quote = None

    for sym, pos in portfolio.items():
        ltp = pos["entry_price"]
        if fetch_live_quote:
            try:
                q, _ = fetch_live_quote(sym)
                if q and q.get("ltp"):
                    ltp = float(q["ltp"])
            except Exception:
                pass

        pnl_pos = (ltp - pos["entry_price"]) * pos["quantity"]
        r_pos = (ltp - pos["entry_price"]) / pos["risk_per_share"]
        unrealized_pnl += pnl_pos
        unrealized_r += r_pos

        r_icon = "🟢" if r_pos >= 0 else "🔴"
        open_lines.append(
            f"• <b>{sym}</b>: Entry ₹{pos['entry_price']:,} ➔ LTP ₹{ltp:,.0f} | "
            f"SL: ₹{pos['current_sl']:,} | <b>{r_icon} {r_pos:+.2f}R</b> (Day {pos.get('holding_days', 1)})"
        )

    unrealized_r = round(unrealized_r, 2)
    unrealized_pnl = round_to_clean_int(unrealized_pnl)

    # Filter trades entered today
    today_entries = [p for p in portfolio.values() if p.get("entry_date") == today_str]
    entry_lines = []
    for e in today_entries:
        entry_lines.append(f"• <b>{e['symbol']}</b> | Fill: ₹{e['entry_price']:,} | SL: ₹{e['initial_sl']:,} | 1.0R (₹{e['fixed_risk_inr']:,}) | {e.get('sa_regime')}")

    # Filter trades exited today
    today_exits = [t for t in trade_log if t.get("exit_date") == today_str]
    exit_lines = []
    today_closed_r = 0.0
    for ex in today_exits:
        r_val = ex.get("realized_r", 0.0)
        today_closed_r += r_val
        r_str = f"+{r_val:.2f}R" if r_val >= 0 else f"{r_val:.2f}R"
        exit_lines.append(f"• <b>{ex['symbol']}</b> | {r_str} (₹{ex.get('realized_pnl_inr', 0):+,}) | {ex.get('exit_reason')}")

    today_closed_r = round(today_closed_r, 2)

    # Build EOD HTML Card
    lines = []
    if day_num >= EVALUATION_HORIZON_DAYS:
        lines.append("🏆 <b>[30-DAY AUTONOMOUS PILOT MATURE — READY FOR PHASE 2 REVIEW]</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    lines.extend([
        "🤖 <b>PHASE 1 AUTONOMOUS SHADOW ENGINE — EOD REPORT</b>",
        f"📅 <b>Day {day_num} of {EVALUATION_HORIZON_DAYS}</b> | Session: {now.strftime('%d-%b-%Y')} (15:35 IST)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>ACTIVE SWING PORTFOLIO HEALTH:</b>",
        f"• <b>Open Swing Holdings:</b> {len(portfolio)} positions",
        f"• <b>Unrealized P&L:</b> {'+' if unrealized_r >= 0 else ''}{unrealized_r:.2f}R (₹{unrealized_pnl:+,})",
        f"• <b>Today's Closed P&L:</b> {'+' if today_closed_r >= 0 else ''}{today_closed_r:.2f}R",
    ])

    if open_lines:
        lines.append("\n💼 <b>OPEN RUNNERS BREAKDOWN:</b>")
        lines.extend(open_lines[:8])  # Top 8 positions
        if len(open_lines) > 8:
            lines.append(f"<i>... and {len(open_lines) - 8} more open runners</i>")

    if entry_lines:
        lines.append(f"\n🚀 <b>TODAY'S NEW ENTRIES ({len(today_entries)}):</b>")
        lines.extend(entry_lines)
    else:
        lines.append("\n🚀 <b>TODAY'S NEW ENTRIES:</b> 0 (None triggered in 09:30-10:15 window)")

    if exit_lines:
        lines.append(f"\n🏁 <b>EXITS CLOSED TODAY ({len(today_exits)}):</b>")
        lines.extend(exit_lines)

    lines.append("\n📈 <b>30-DAY CUMULATIVE SCOREBOARD:</b>")
    lines.append(f"• <b>Total Trades Completed:</b> {analytics['total_trades']} trades")
    lines.append(f"• <b>Win Rate:</b> {analytics['win_rate_pct']}% ({analytics['win_count']}W / {analytics['loss_count']}L)")
    lines.append(f"• <b>Net Realized Profit:</b> <b>{'+' if analytics['net_r'] >= 0 else ''}{analytics['net_r']:.2f}R (₹{analytics['net_pnl_inr']:+,})</b>")
    lines.append(f"• <b>Profit Factor:</b> {analytics['profit_factor']}")
    lines.append(f"• <b>Avg Win / Avg Loss:</b> +{analytics['avg_win_r']:.2f}R / -{analytics['avg_loss_r']:.2f}R")
    lines.append(f"• <b>Expectancy per Trade:</b> {'+' if analytics['expectancy_r'] >= 0 else ''}{analytics['expectancy_r']:.2f}R")
    lines.append(f"• <b>Max Drawdown:</b> -{analytics['max_drawdown_r']:.2f}R")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Pure forward test. Uncapped by portfolio limits. 1R = ₹1,000. Zero real money at risk.</i>")

    report_html = "\n".join(lines)

    if notify:
        send_phase1_telegram_alert(report_html, topic_name="reports")

    # Persist snapshot
    snapshot = {
        "date": today_str,
        "day_num": day_num,
        "open_count": len(portfolio),
        "unrealized_r": unrealized_r,
        "unrealized_pnl": unrealized_pnl,
        "today_closed_r": today_closed_r,
        "today_entries_count": len(today_entries),
        "today_exits_count": len(today_exits),
        "cumulative_analytics": analytics
    }

    history = []
    if SHADOW_EOD_FILE.is_file():
        try:
            with open(SHADOW_EOD_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    # Replace today if already present
    history = [h for h in history if h.get("date") != today_str]
    history.append(snapshot)
    atomic_write_json(SHADOW_EOD_FILE, history)

    return report_html


def format_shadow_status_card():
    """Returns quick status card for Telegram /phase1 or /shadow command."""
    now = get_ist_now()
    portfolio = load_shadow_portfolio()
    analytics = get_shadow_analytics()

    try:
        d_start = datetime.strptime(START_DATE_STR, "%Y-%m-%d").date()
        d_curr = now.date()
        day_num = count_trading_days(d_start, d_curr)
    except Exception:
        day_num = 1

    lines = [
        "🤖 <b>PHASE 1 AUTONOMOUS SHADOW ENGINE STATUS</b>",
        f"📅 <b>Day {day_num} of {EVALUATION_HORIZON_DAYS}</b> | 30-Day Evaluation Active",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Active Swing Positions:</b> {len(portfolio)} open",
        f"• <b>Entry Window:</b> 09:30–10:15 AM IST ({'🟢 OPEN' if is_entry_window_active(now) else '🔒 CLOSED'})",
        f"• <b>Sizing Model:</b> Standardized Fixed Risk ($1R = ₹1,000)",
        f"• <b>Capacity Mode:</b> UNCAPPED (Capturing every valid setup)",
        f"• <b>Total Closed Trades:</b> {analytics['total_trades']} completed",
        f"• <b>Win Rate:</b> {analytics['win_rate_pct']}% ({analytics['win_count']}W / {analytics['loss_count']}L)",
        f"• <b>Net Realized P&L:</b> <b>{'+' if analytics['net_r'] >= 0 else ''}{analytics['net_r']:.2f}R (₹{analytics['net_pnl_inr']:+,})</b>",
        f"• <b>Profit Factor:</b> {analytics['profit_factor']}",
        f"• <b>Expectancy:</b> {'+' if analytics['expectancy_r'] >= 0 else ''}{analytics['expectancy_r']:.2f}R / trade",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>To view full EOD report:</i> <code>/shadowreport</code>\n"
        "💡 <i>To view open/closed trades:</i> <code>/shadowtrades</code>"
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"=== Jarvis Phase 1 Shadow Engine (Audited & Hardened) ===")
    print(f"Current IST: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"Entry Window Active (09:30-10:15 AM): {is_entry_window_active()}")
    card = format_shadow_status_card()
    print("\n" + card)
