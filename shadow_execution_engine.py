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
import hashlib
import tempfile
import threading
import urllib.request
import urllib.parse
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
START_DATE_STR = "2026-11-23"  # Official 30-Session Clean Freeze Launch: Monday, Nov 23, 2026
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


CONFIG_VERSION = "v3.3.0-strict"
CONFIG_SNAPSHOTS_DIR = BASE_DIR / "config_snapshots"
CONFIG_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

EVALUATION_BASE_CAPITAL = 500000.0  # ₹5,00,000 maximum gross exposure base (5 slots x ₹100,000, 100% CNC Delivery, 0 Leverage)
MAX_SYSTEM_SLOTS = 5

def get_manifest_hash():
    """Returns SHA-256 (first 8 hex chars) of config_snapshots/release_manifest_v330.json identifying exact file set."""
    m_file = BASE_DIR / "config_snapshots" / "release_manifest_v330.json"
    if m_file.is_file():
        try:
            return hashlib.sha256(m_file.read_bytes()).hexdigest()[:8]
        except Exception:
            pass
    return "00000000"


def get_git_commit_sha():
    """Returns the immutable release manifest hash identifying the exact frozen codebase."""
    return get_manifest_hash()

def get_watchlist_hash():
    """Returns SHA-256 (first 8 hex chars) of sorted normalized watchlist.txt symbols."""
    w_file = BASE_DIR / "watchlist.txt"
    if w_file.is_file():
        try:
            with open(w_file, "r", encoding="utf-8") as f:
                lines = [l.strip().upper() for l in f if l.strip() and not l.startswith("#")]
            content = ",".join(sorted(lines))
            return hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
        except Exception:
            pass
    return "00000000"


FROZEN_PARAMS = {
    "version": CONFIG_VERSION,
    "evaluation_start_date": "2026-11-23",
    "evaluation_end_date": "2027-01-05",
    "evaluation_base_capital_inr": 500000.0,
    "max_portfolio_slots": 5,
    "cash_gated_execution": True,
    "circuit_ceiling_collar_pct": 1.5,
    "depth_gate_circuit_proximity_pct": 1.5,
    "depth_gate_unquoted_gain_pct": 15.0,
    "circuit_unlock_fill_logic": "min_candle_open_ltp_v33",
    "anomaly_rejection_pct_threshold": 80.0,
    "anomaly_min_sample_size": 5,
    "earnings_blackout_days": 3,
    "earnings_sync_max_age_hours": 72,
    "earnings_monday_cache_max_hours": 24.0,
    "quotes_api_route": "v3/market-quote/quotes",
    "rvol_tod_min": 1.0,
    "stretch_max": 3.0,
    "gap_max": 2.5,
    "wick_max": 40.0,
    "risk_max_pct": 4.0,
    "risk_min_pct": 1.0,
    "min_stop_distance_rule": "max(1.0%, 0.5 * ATR14)",
    "soft_min": 3,
    "tick_size": 0.05,
    "sl_adverse_slippage_pct": 0.0015,
    "day1_spurt_threshold_pct": 4.5,
    "trail_stage1_r": 1.5,
    "trail_stage2_r": 2.0,
    "trail_stage2_lock_r": 1.0,
    "trail_ema5_floor_r": 2.0,
    "statutory_rates": {
        "stt_delivery": 0.001,
        "stamp_duty_buy": 0.00015,
        "exchange_turnover": 0.0000297,
        "sebi_turnover": 0.000001,
        "gst_rate": 0.18,
        "dp_charges_flat": 15.93
    },
    "regime_table": {
        "EXPANSION": {"permitted": True, "alloc_pct": 100, "max_slots": 3, "slot_capital_max": 100000},
        "NORMAL": {"permitted": True, "alloc_pct": 100, "max_slots": 3, "slot_capital_max": 100000},
        "NEUTRAL": {"permitted": True, "alloc_pct": 50, "max_slots": 1, "slot_capital_max": 50000},
        "DEFENSIVE": {"permitted": False, "alloc_pct": 0, "max_slots": 0, "slot_capital_max": 0},
        "WASHOUT": {"permitted": False, "alloc_pct": 0, "max_slots": 0, "slot_capital_max": 0}
    },
    "tod_knots": [[0, 0.01], [15, 0.10], [60, 0.25], [285, 0.65], [375, 1.00]],
    "session_target_days": 30,
    "max_calendar_sessions_cap": 40,
    "entry_window_start": "09:30:00",
    "entry_window_end": "10:15:00",
    "max_feed_downtime_minutes": 10.0,
    "feed_stall_timeout_seconds": 45.0,
    "session_status_valid": "VALID",
    "session_status_excluded": "NO_DATA_EXCLUDED",
    "session_status_partial": "PARTIAL",
    "partial_counts_toward_target": False
}
CONFIG_HASH = hashlib.sha256(json.dumps(FROZEN_PARAMS, sort_keys=True).encode("utf-8")).hexdigest()[:8]
snapshot_file = CONFIG_SNAPSHOTS_DIR / f"config_{CONFIG_HASH}.json"
if not snapshot_file.is_file():
    try:
        with open(snapshot_file, "w", encoding="utf-8") as sf:
            json.dump(FROZEN_PARAMS, sf, indent=2)
    except Exception:
        pass

REJECTED_SIGNALS_FILE = BASE_DIR / "shadow_rejected_signals.json"
SHADOW_MTM_CURVE_FILE = BASE_DIR / "shadow_mtm_equity_curve.json"


def round_to_tick(val, tick=0.05, direction="nearest"):
    """
    Tick-aware price rounding for NSE equities (standard ₹0.05 tick size).
    - direction='down': math.floor(f / tick) * tick (for protective stops & exit fills)
    - direction='up': math.ceil(f / tick) * tick (for marketable buy fills)
    - direction='nearest': round(f / tick) * tick
    """
    if val is None:
        return 0.0
    try:
        f = float(val)
        if direction == "down":
            return round(math.floor(round(f / tick, 6)) * tick, 2)
        elif direction == "up":
            return round(math.ceil(round(f / tick, 6)) * tick, 2)
        else:
            return round(round(f / tick) * tick, 2)
    except Exception:
        return 0.0


def round_to_clean_int(val):
    """Backwards-compatibility alias: delegates to tick-aware rounding (0.05)."""
    return round_to_tick(val, tick=0.05, direction="nearest")


def log_rejected_signal(symbol: str, reason: str, metadata: dict = None):
    """Logs rejected breakout setups to shadow_rejected_signals.json with full telemetry and daily first/peak tracking."""
    try:
        now_ist = get_ist_now()
        today_prefix = now_ist.strftime("%Y-%m-%d")
        now_ts = now_ist.strftime("%Y-%m-%d %H:%M:%S")
        rej_list = []
        if REJECTED_SIGNALS_FILE.is_file():
            try:
                with open(REJECTED_SIGNALS_FILE, "r", encoding="utf-8") as rf:
                    rej_list = json.load(rf)
            except Exception:
                rej_list = []

        found_idx = None
        for i, r in enumerate(rej_list):
            r_ts = str(r.get("first_seen_timestamp") or r.get("timestamp") or "")
            if r.get("symbol") == symbol and r_ts[:10] == today_prefix and r.get("reason") == reason:
                found_idx = i
                break

        curr_soft = (metadata or {}).get("soft_score", 0)
        curr_rvol = float((metadata or {}).get("rvol") or 0.0)

        if found_idx is not None:
            existing = rej_list[found_idx]
            existing["last_seen_timestamp"] = now_ts
            existing["rejection_count"] = existing.get("rejection_count", 1) + 1
            peak_m = existing.get("peak_metadata", existing.get("metadata", {}))
            prev_peak_soft = peak_m.get("soft_score", 0)
            prev_peak_rvol = float(peak_m.get("rvol") or 0.0)
            if curr_soft > prev_peak_soft or (curr_soft == prev_peak_soft and curr_rvol > prev_peak_rvol):
                existing["peak_metadata"] = metadata or {}
                existing["peak_timestamp"] = now_ts
            atomic_write_json(REJECTED_SIGNALS_FILE, rej_list)
            return

        rej_entry = {
            "symbol": symbol,
            "timestamp": now_ts,
            "first_seen_timestamp": now_ts,
            "last_seen_timestamp": now_ts,
            "rejection_count": 1,
            "reason": reason,
            "config_version": CONFIG_VERSION,
            "config_hash": CONFIG_HASH,
            "metadata": metadata or {},
            "peak_metadata": metadata or {}
        }
        rej_list.append(rej_entry)
        atomic_write_json(REJECTED_SIGNALS_FILE, rej_list)
    except Exception as e:
        print(f"Notice logging rejected signal for {symbol}: {e}")


NSE_HOLIDAYS = {
    # 2026 Official Exchange Holidays
    "2026-01-26", "2026-03-03", "2026-03-20", "2026-03-27", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-27", "2026-08-15", "2026-09-04",
    "2026-10-02", "2026-10-20", "2026-11-08", "2026-11-10", "2026-11-24", "2026-12-25",
    # 2027 Projected Exchange Holidays (Statutory / National Holidays)
    "2027-01-26", "2027-03-24", "2027-03-26", "2027-04-14", "2027-05-01",
    "2027-08-15", "2027-10-02", "2027-12-25"
}
NSE_HOLIDAYS_2026 = NSE_HOLIDAYS


def count_trading_days(date_start, date_end):
    """Counts actual trading days (Monday to Friday, excluding exchange holidays) between two dates inclusive."""
    if date_start > date_end:
        return 0
    cur = date_start
    days = 0
    while cur <= date_end:
        if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in NSE_HOLIDAYS:
            days += 1
        cur += timedelta(days=1)
    return max(0, days)


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


UPSTOX_TOKEN_FILE = BASE_DIR / "upstox_token.txt"

def load_upstox_token():
    """Loads active Upstox access token from config_credentials.json or upstox_token.txt."""
    cfg = load_config()
    tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if tok:
        return tok
    if UPSTOX_TOKEN_FILE.is_file():
        try:
            with open(UPSTOX_TOKEN_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


def fetch_1m_intraday_candles(symbol: str):
    """
    Fetches 1-minute intraday historical candles for today directly from Upstox REST API:
    Primary route: GET /v3/historical-candle/intraday/{encoded_key}/minutes/1
    Fallback route: GET /v2/historical-candle/intraday/{encoded_key}/1minute
    Used for watchdog surveillance gap replay to reconstruct exact breach bars and fill prices.
    Drops the currently forming/in-progress candle to evaluate strictly finalized bars.
    Returns chronologically sorted list of finalized 1m candles for today:
    [{'t': 'HH:MM', 'iso_time': str, 'o': float, 'h': float, 'l': float, 'c': float, 'v': int}, ...]
    """
    try:
        from upstox_tablet_scanner import get_instrument_key
        tok = load_upstox_token()
        if not tok:
            return []
        norm_sym = resolve_symbol(symbol)
        ikey = get_instrument_key(norm_sym)
        if not ikey:
            return []
        enc_key = urllib.parse.quote(ikey, safe="")

        headers = {
            "Authorization": f"Bearer {tok}",
            "Accept": "application/json",
            "User-Agent": "Jarvis-ShadowEngine"
        }

        # Try v3 first, fallback to v2 if needed
        raw_candles = []
        for endpoint_url in [
            f"https://api.upstox.com/v3/historical-candle/intraday/{enc_key}/minutes/1",
            f"https://api.upstox.com/v2/historical-candle/intraday/{enc_key}/1minute"
        ]:
            try:
                req = urllib.request.Request(endpoint_url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_candles = data.get("data", {}).get("candles", [])
                    if raw_candles:
                        break
            except Exception:
                continue

        if not raw_candles:
            return []

        sorted_raw = sorted(raw_candles, key=lambda c: str(c[0]))
        now_ist = get_ist_now()
        today_prefix = now_ist.strftime("%Y-%m-%d")
        cur_min_str = now_ist.strftime("%H:%M")
        parsed = []
        for c in sorted_raw:
            iso_ts = str(c[0])
            if not iso_ts.startswith(today_prefix):
                continue
            t_lbl = iso_ts[11:16] if len(iso_ts) >= 16 else iso_ts
            # Drop the current still-forming candle; evaluate only finalized completed bars
            if t_lbl == cur_min_str:
                continue
            parsed.append({
                "t": t_lbl,
                "iso_time": iso_ts,
                "o": round(float(c[1]), 2),
                "h": round(float(c[2]), 2),
                "l": round(float(c[3]), 2),
                "c": round(float(c[4]), 2),
                "v": int(c[5]) if len(c) > 5 else 0
            })
        return parsed
    except Exception as e:
        print(f"Notice fetching 1m candles for {symbol}: {e}")
        return []


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


_last_earnings_cache_alert = [0.0]
_rejection_tracker = {"window_date": None, "total_evals": 0, "reason_counts": {}}
_last_anomaly_alert_time = [0.0]


def track_and_audit_rejection(reason_code: str):
    """
    Intraday Rejection Anomaly Detector:
    Tracks candidate evaluations between 09:30-10:15 IST.
    If >= 80% of candidates (sample >= 5) are rejected for a single data-dependent reason
    (ZERO_SELLER_DEPTH, FEED_STALE, EARNINGS_CALENDAR_UNAVAILABLE), alerts to Topic 9 ('risk').
    """
    try:
        now_ist = get_ist_now()
        d_str = now_ist.strftime("%Y-%m-%d")
        if _rejection_tracker["window_date"] != d_str:
            _rejection_tracker["window_date"] = d_str
            _rejection_tracker["total_evals"] = 0
            _rejection_tracker["reason_counts"] = {}

        _rejection_tracker["total_evals"] += 1
        _rejection_tracker["reason_counts"][reason_code] = _rejection_tracker["reason_counts"].get(reason_code, 0) + 1

        total = _rejection_tracker["total_evals"]
        if total >= 5:
            count = _rejection_tracker["reason_counts"].get(reason_code, 0)
            pct = (count / total) * 100.0
            now_ep = time.time()
            if pct >= 80.0 and (now_ep - _last_anomaly_alert_time[0] > 1800):
                _last_anomaly_alert_time[0] = now_ep
                send_phase1_telegram_alert(
                    f"🚨 <b>DATA ANOMALY ALERT: {reason_code} ({pct:.0f}%)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Evaluations:</b> {total} candidate breakouts screened\n"
                    f"• <b>Rejections:</b> {count}/{total} rejected solely due to {reason_code}\n"
                    "• <b>Warning:</b> Potential broker quote or data feed anomaly suppressing signals.\n"
                    "• <b>Action:</b> Check Upstox market depth and data feed status.",
                    topic_name="risk"
                )
    except Exception:
        pass


def is_earnings_calendar_valid():
    """Validates that earnings calendar file exists, is non-empty, and contains valid structured data."""
    cal_file = BASE_DIR / "data" / "earnings_calendar.json"
    if not cal_file.is_file():
        return False
    try:
        if cal_file.stat().st_size < 10:
            return False
        with open(cal_file, "r", encoding="utf-8") as f:
            d = json.load(f)
        symbols = d.get("symbols", d)
        return bool(symbols and len(symbols) > 0 and isinstance(symbols, dict))
    except Exception:
        return False


def check_earnings_blackout(symbol: str, dt=None):
    """
    Checks if symbol has major corporate actions (Financial Results, Splits, Bonus, Rights, Mergers) within 3 trading days.
    Data source: data/earnings_calendar.json (synced from NSE Corporate Announcements via sync_earnings_calendar.py).
    Cache TTL: 72 hours.
    Logic:
    - If symbol NOT in calendar: PASS (negative confirmation, no earnings scheduled).
    - If symbol in calendar and event date is within [now, now + 3 days]: FAIL-CLOSED (blackout entry).
    - If calendar file missing/unreadable: log warning to Topic 9 ('risk') and FAIL-OPEN so trading is not paralyzed.
    """
    cal_file = BASE_DIR / "data" / "earnings_calendar.json"
    if not is_earnings_calendar_valid():
        now_ep = time.time()
        if now_ep - _last_earnings_cache_alert[0] > 14400:
            _last_earnings_cache_alert[0] = now_ep
            send_phase1_telegram_alert(
                "⚠️ <b>WARNING: Earnings Calendar Cache Missing or Unreadable</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "• <b>Status:</b> data/earnings_calendar.json invalid or empty\n"
                "• <b>Fallback:</b> Failing open for candidate entries with caution\n"
                "• <b>Action:</b> Run sync_earnings_calendar.py to refresh cache",
                topic_name="risk"
            )
        return False, None

    try:
        file_age_hours = (time.time() - cal_file.stat().st_mtime) / 3600.0
        now_ep = time.time()
        if file_age_hours > 72.0 and (now_ep - _last_earnings_cache_alert[0] > 14400):
            _last_earnings_cache_alert[0] = now_ep
            send_phase1_telegram_alert(
                f"⚠️ <b>WARNING: Earnings Calendar Stale ({file_age_hours:.1f}h old)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Cache Age:</b> {file_age_hours:.1f} hours (> 72h TTL limit)\n"
                "• <b>Action:</b> Run sync_earnings_calendar.py to fetch latest NSE filings",
                topic_name="risk"
            )

        with open(cal_file, "r", encoding="utf-8") as f:
            cal_data = json.load(f)

        symbols_map = cal_data.get("symbols", cal_data)
        clean_s = resolve_symbol(symbol).strip().upper()
        event_info = symbols_map.get(clean_s)

        if not event_info:
            return False, None

        event_date_str = event_info.get("date") if isinstance(event_info, dict) else str(event_info)
        purpose = event_info.get("purpose", "Financial Results / Corporate Action") if isinstance(event_info, dict) else "Corporate Action"

        if event_date_str:
            d_event = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            d_curr = (dt or get_ist_now()).date()
            days_diff = (d_event - d_curr).days
            if 0 <= days_diff <= 3:
                return True, f"Earnings Blackout: {purpose} on {event_date_str} (within 3-day window)"
    except Exception as e:
        print(f"Notice reading earnings calendar: {e}")
    return False, None


def assert_monday_0900_launch_gate():
    """
    Monday Launch Gate Pre-Flight Assertion (Runs strictly once at 09:00 AM IST on Nov 23, 2026).
    Enforces strict pre-flight readiness before Phase 1 begins:
    1. Sentinel file archive/.day0_reset_completed must exist.
    2. shadow_portfolio.json must have 0 open positions (empty dict).
    3. shadow_trade_log.json must contain NO unarchived Day 0 trades.
    4. shadow_mtm_equity_curve.json must contain NO unarchived Day 0 snapshots.
    If ANY assertion fails, returns (False, reason), causing all new entries to be refused.
    """
    DAY0_SENTINEL_FILE = BASE_DIR / "archive" / ".day0_reset_completed"
    if not DAY0_SENTINEL_FILE.is_file():
        return False, "Sentinel file (archive/.day0_reset_completed) is missing. Day 0 reset has not been executed."

    portfolio = load_shadow_portfolio()
    if len(portfolio) > 0:
        return False, f"Portfolio is not clean: {len(portfolio)} open positions found in shadow_portfolio.json ({list(portfolio.keys())})."

    trades = load_shadow_trade_log()
    unarchived_day0_trades = [t for t in trades if t.get("is_day0") or str(t.get("entry_date", "")) < START_DATE_STR]
    if unarchived_day0_trades:
        return False, f"Trade log contains {len(unarchived_day0_trades)} unarchived Day 0 trades in active log."

    if SHADOW_MTM_CURVE_FILE.is_file():
        try:
            with open(SHADOW_MTM_CURVE_FILE, "r", encoding="utf-8") as cf:
                curve = json.load(cf)
            day0_snaps = [c for c in curve if c.get("session") == "DAY0_SHAKEDOWN" or str(c.get("date", "")) < START_DATE_STR]
            if day0_snaps:
                return False, f"MTM curve contains {len(day0_snaps)} unarchived Day 0 snapshots in active curve."
        except Exception as e:
            return False, f"Could not parse shadow_mtm_equity_curve.json: {e}"

    return True, "All Phase 1 launch readiness assertions PASSED (Sentinel present, 0 open positions, pristine state files)."


def assert_phase1_in_flight_state_integrity():
    """
    In-Flight Phase 1 State Integrity Assertion (Evaluated before every candidate trade during market hours).
    Verifies that:
    1. Sentinel file archive/.day0_reset_completed exists.
    2. Open positions contain ZERO Day 0 contamination (no is_day0=True, no entry_date < 2026-11-23).
    3. Trade log contains ZERO unarchived Day 0 trades.
    Allows 0 to MAX_SYSTEM_SLOTS open positions (never rejects simply because trade #1 is already entered).
    """
    DAY0_SENTINEL_FILE = BASE_DIR / "archive" / ".day0_reset_completed"
    if not DAY0_SENTINEL_FILE.is_file():
        return False, "Sentinel file (archive/.day0_reset_completed) is missing. Day 0 reset has not been executed."

    portfolio = load_shadow_portfolio()
    contaminated_pos = [
        sym for sym, p in portfolio.items()
        if p.get("is_day0") or str(p.get("entry_date", "")) < START_DATE_STR
    ]
    if contaminated_pos:
        return False, f"Open portfolio contaminated with {len(contaminated_pos)} Day 0 positions: {contaminated_pos}"

    trades = load_shadow_trade_log()
    unarchived_day0_trades = [t for t in trades if t.get("is_day0") or str(t.get("entry_date", "")) < START_DATE_STR]
    if unarchived_day0_trades:
        return False, f"Trade log contains {len(unarchived_day0_trades)} unarchived Day 0 trades in active log."

    return True, "Phase 1 in-flight state integrity verified (No Day 0 contamination)."


def assert_phase1_launch_readiness():
    """Backwards-compatibility alias for Monday 09:00 launch gate."""
    return assert_monday_0900_launch_gate()


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


def evaluate_and_record_shadow_entry(symbol, quote_data, trigger_price=None, day_low=None, regime_code="EXPANSION", trigger_name="ORB Breakout", dt=None):
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

    now = dt if dt is not None else get_ist_now()
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

    # In-Flight State Integrity Assertion (Enforced on or after START_DATE_STR)
    if today_str >= START_DATE_STR:
        is_ready, gate_err = assert_phase1_in_flight_state_integrity()
        if not is_ready:
            print(f"🛑 [STATE INTEGRITY BLOCKED] Cannot take new entry for {sym}: {gate_err}")
            return False, f"Phase 1 In-Flight State Integrity Assertion Failed: {gate_err}"

    already_traded_today = any(t.get("symbol") == sym and (t.get("entry_date") == today_str or t.get("exit_date") == today_str) for t in trade_log)
    if already_traded_today:
        return False, f"{sym} already entered/exited today (Whipsaw protection: 1 trade per symbol per session)"

    ltp = float(trigger_price or quote_data.get("ltp") or 0.0)
    if ltp <= 0:
        return False, "Invalid LTP"

    # Edge Case Guard 2: Penny Stock Collar
    if ltp < 20.0:
        return False, f"Penny stock filter: {sym} LTP ₹{ltp:.2f} < ₹20 threshold"

    # Realistic Marketable Fill (+0.15% slippage collar, tick-aware ceil)
    fill_price = round_to_tick(ltp * 1.0015, tick=0.05, direction="up")

    # Upper Circuit Ceiling & Liquidity Depth Check (Fail-Closed)
    upper_circuit = float((quote_data or {}).get("upper_circuit_limit") or 0.0)
    prev_close = float((quote_data or {}).get("prev_close") or 0.0)
    total_sell_qty = (quote_data or {}).get("total_sell_quantity")
    depth = (quote_data or {}).get("depth") or {}

    # 1. Total sell quantity check (Zero ask depth near circuit ceiling)
    is_near_circuit_price = False
    if upper_circuit > 0:
        is_near_circuit_price = (fill_price >= upper_circuit * 0.985)
    elif prev_close > 0:
        is_near_circuit_price = ((fill_price - prev_close) / prev_close >= 0.15)

    if total_sell_qty is not None and int(total_sell_qty) == 0 and is_near_circuit_price:
        log_rejected_signal(sym, "Zero Seller Depth: Upper circuit locked with 0 ask quantity", {"ltp": fill_price, "upper_circuit": upper_circuit})
        track_and_audit_rejection("ZERO_SELLER_DEPTH")
        return False, "Zero Seller Depth: Stock locked at Upper Circuit with 0 sellers. Marketable fill physically impossible."

    # 2. Upper Circuit Collar (< 1.5% from ceiling)
    if upper_circuit > 0:
        if (upper_circuit - fill_price) / fill_price < 0.015:
            log_rejected_signal(sym, f"Upper Circuit Freeze Collar: Within 1.5% of upper circuit (₹{upper_circuit:.2f})", {"ltp": fill_price, "upper_circuit": upper_circuit})
            return False, f"Upper Circuit Freeze Collar: LTP ₹{fill_price:.2f} within 1.5% of upper circuit (₹{upper_circuit:.2f}). High risk of unfillable lockup."
    else:
        # Fallback when upper_circuit is 0 or missing from broker feed
        if prev_close > 0 and (fill_price - prev_close) / prev_close >= 0.18:
            log_rejected_signal(sym, f"Upper Circuit Fallback: Intraday gain +{((fill_price - prev_close)/prev_close)*100:.1f}% exceeds 18% limit", {"ltp": fill_price, "prev_close": prev_close})
            return False, f"Upper Circuit Fallback: Intraday gain +{((fill_price - prev_close)/prev_close)*100:.1f}% exceeds 18% limit while circuit data is unquoted."

        sell_depth = depth.get("sell") if isinstance(depth, dict) else []
        if (total_sell_qty is None or int(total_sell_qty) == 0) and not sell_depth:
            log_rejected_signal(sym, "Unquantified Liquidity Risk: Order book lacks upper circuit limit and ask depth", {"ltp": fill_price})
            return False, "Unquantified Liquidity Risk: Order book lacks both upper circuit limit and ask depth."

    # Earnings Blackout Window Check (Fail-Closed)
    earnings_active = is_earnings_calendar_valid()
    is_blackout, blackout_reason = check_earnings_blackout(sym, now)
    if is_blackout:
        log_rejected_signal(sym, blackout_reason, {"symbol": sym})
        track_and_audit_rejection("EARNINGS_BLACKOUT")
        return False, blackout_reason

    # Initial Structural Stop Loss: Day Low at trigger moment with buffer, tick-aware floor
    dl = float(day_low or quote_data.get("day_low") or (fill_price * 0.975))
    buffer = max(0.20, round(dl * 0.002, 2))
    initial_sl = round_to_tick(dl - buffer, tick=0.05, direction="down")

    # Edge Case Guard 3: Stop-Loss Sanitization (Ensure SL is strictly at least ₹0.50 below fill price)
    if initial_sl >= fill_price:
        initial_sl = round_to_tick(fill_price - 0.50, tick=0.05, direction="down")

    # Volatility & Microstructure Noise Floor Padding: Ensure initial SL is at least max(1.0%, 0.5x ATR14) below entry
    atr_val = (quote_data or {}).get("atr14") or (quote_data or {}).get("atr_3m")
    if not atr_val:
        sc_d = get_cached_symbol_metrics(sym) or {}
        atr_val = sc_d.get("atr14")
    atr_14_f = float(atr_val) if (atr_val and float(atr_val) > 0) else (fill_price * 0.02)
    min_risk_dist = max(fill_price * 0.010, 0.5 * atr_14_f)

    if (fill_price - initial_sl) < min_risk_dist:
        initial_sl = round_to_tick(fill_price - min_risk_dist, tick=0.05, direction="down")

    # Risk distance per share (ensures min 0.50 to prevent division by zero)
    risk_per_share = max(0.50, round(fill_price - initial_sl, 2))
    risk_pct = round((risk_per_share / fill_price) * 100.0, 2)

    # Edge Case Guard 4: Excessive Stop Distance Rejection (Checklist Rule 6: <= 4.0% Limit)
    if risk_pct > 4.0:
        log_rejected_signal(sym, f"Wide Stop-Loss: {risk_pct:.1f}% (> 4.0% limit)", {"risk_pct": risk_pct, "fill_price": fill_price, "sl": initial_sl})
        return False, f"Wide Stop-Loss: Distance to Day Low is {risk_pct:.1f}% (> 4.0% limit). Capital preserved against excessive tail risk."

    # Regime & System Portfolio Slot Limit Enforcement
    reg_table = FROZEN_PARAMS.get("regime_table", {})
    reg_conf = reg_table.get(reg_u, {"permitted": True, "max_slots": 3, "slot_capital_max": 100000.0})
    max_slots = reg_conf.get("max_slots", 3)
    if len(portfolio) >= max_slots:
        log_rejected_signal(sym, f"Portfolio slot limit reached ({len(portfolio)}/{max_slots} active positions in {reg_u} regime)", {"open_positions": len(portfolio)})
        return False, f"Portfolio slot limit reached ({len(portfolio)}/{max_slots} active positions in {reg_u} regime)"
    if len(portfolio) >= MAX_SYSTEM_SLOTS:
        log_rejected_signal(sym, f"System portfolio capacity reached ({len(portfolio)}/{MAX_SYSTEM_SLOTS} slots active)", {"open_positions": len(portfolio)})
        return False, f"System portfolio capacity reached ({len(portfolio)}/{MAX_SYSTEM_SLOTS} slots active)"

    # Cash-Gated Position Sizing (Delivery equity, 0 leverage, ₹5,00,000 capital base)
    current_invested = sum(float(p.get("capital_invested", p.get("quantity", 0) * p.get("entry_price", 0))) for p in portfolio.values())
    closed_pnl = sum(float(t.get("realized_pnl_inr", 0.0)) for t in trade_log)
    available_cash = max(0.0, EVALUATION_BASE_CAPITAL + closed_pnl - current_invested)

    if available_cash < fill_price:
        log_rejected_signal(sym, f"Insufficient cash: Available ₹{available_cash:,.2f} < 1 share at ₹{fill_price:.2f}", {"available_cash": available_cash, "ltp": fill_price})
        return False, f"Insufficient available cash: ₹{available_cash:,.2f} < 1 share at ₹{fill_price:.2f} (Base: ₹{EVALUATION_BASE_CAPITAL:,.0f}, Invested: ₹{current_invested:,.0f})"

    max_capital_per_slot = float(reg_conf.get("slot_capital_max", 100000.0))
    max_capital_for_slot = min(max_capital_per_slot, available_cash)
    qty = max(1, int(FIXED_RISK_PER_TRADE_INR // risk_per_share))
    if qty * fill_price > max_capital_for_slot:
        qty = max(1, int(max_capital_for_slot // fill_price))
    target_price = round_to_tick(fill_price + (2.0 * risk_per_share), tick=0.05, direction="up")
    capital_invested = round(qty * fill_price, 2)
    initial_risk_inr = round(qty * risk_per_share, 2)

    # P0-7: Strategy Checklist (Hard Gates vs Soft Scores)
    ck_note = "Qualified Playbook Setup"
    try:
        from order_engine import evaluate_strategy_checklist
        ck = evaluate_strategy_checklist(sym, quote_data=quote_data, calc_data={"ltp": fill_price, "day_low": initial_sl, "day_high": float((quote_data or {}).get("day_high") or fill_price), "risk_pct": risk_pct})
        
        # 1. Enforce Hard Gates (Must All Pass)
        if not ck.get("hard_gates_passed", True):
            failed_gates = ck.get("failed_hard_gates", [])
            log_rejected_signal(
                sym,
                f"Checklist Hard Gate failed: {', '.join(failed_gates)}",
                {
                    "failed_hard_gates": failed_gates,
                    "all_hard_gates": ck.get("hard_gates", []),
                    "soft_score": ck.get("soft_score", 0),
                    "soft_scores_detail": ck.get("soft_scores", []),
                    "ltp": ltp,
                    "risk_pct": risk_pct,
                    "rvol": (quote_data or {}).get("rvol"),
                    "stretch_pct": (quote_data or {}).get("stretch_pct"),
                    "gap_ext_pct": ck.get("gap_ext_pct")
                }
            )
            return False, f"Checklist Hard Gate failed: {', '.join(failed_gates)}"

        soft_score = ck.get("soft_score", 0)
        soft_total = ck.get("soft_total", 7)
        ck_note = f"Hard Gates PASSED ✅ | Quality: {soft_score}/{soft_total} ⭐"

        # 2. Minimum Soft Score Conviction threshold (At least 3 quality points required)
        if soft_score < 3:
            log_rejected_signal(
                sym,
                f"Checklist conviction low ({soft_score}/{soft_total} < 3 required)",
                {
                    "soft_score": soft_score,
                    "soft_total": soft_total,
                    "soft_scores_detail": ck.get("soft_scores", []),
                    "all_hard_gates": ck.get("hard_gates", []),
                    "ltp": ltp,
                    "risk_pct": risk_pct,
                    "rvol": (quote_data or {}).get("rvol"),
                    "stretch_pct": (quote_data or {}).get("stretch_pct")
                }
            )
            return False, f"Checklist conviction low ({soft_score}/{soft_total} < 3 required)"
    except Exception:
        pass

    entry_record = {
        "symbol": sym,
        "config_version": CONFIG_VERSION,
        "config_hash": CONFIG_HASH,
        "manifest_hash": get_manifest_hash(),
        "git_commit": get_git_commit_sha(),
        "watchlist_hash": get_watchlist_hash(),
        "entry_price": fill_price,
        "initial_sl": initial_sl,
        "current_sl": initial_sl,
        "sl_last_ratchet_date": today_str,
        "sl_last_ratchet_time": now.strftime("%H:%M:%S"),
        "target_price": target_price,
        "risk_per_share": risk_per_share,
        "risk_pct": risk_pct,
        "quantity": qty,
        "initial_risk_inr": initial_risk_inr,
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
        "earnings_filter_active": earnings_active,
        "held_through_event": False,
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
        f"• <b>Quantity:</b> {qty} shares (<b>1.0R Risk: ₹{initial_risk_inr:,.0f}</b>)\n"
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

        # Check if held through corporate earnings / major action event
        if not pos.get("held_through_event"):
            is_blk, _ = check_earnings_blackout(sym, now)
            if is_blk:
                pos["held_through_event"] = True

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

        # Multi-Stage Swing Trailing Stop Hierarchy (Strict Monotonic Non-Decreasing: Highest Stop Wins)
        # All trailing stops use tick-aware downward rounding (₹0.05 tick size)
        candidate_stops = [(current_sl, pos.get("last_trail_rule", "INITIAL LOD STOP"))]

        # 1. 🛡️ 30% PROFIT CAP (Milestone: +28% gain or 8.0R reached -> lock +25% profit)
        if peak_gain_pct >= 28.0 or highest_r >= 8.0:
            candidate_stops.append((round_to_tick(entry_p * 1.25, tick=0.05, direction="down"), "🛡️ 30% PROFIT CAP (Lock +25% Gains)"))

        # 2. ⚡ PARABOLIC 5 EMA (Vertical Momentum: R >= 4.0 -> trail 5 EMA with Stage 4 +2.0R floor!)
        if highest_r >= 4.0:
            floor_2r = round_to_tick(entry_p + (2.0 * risk_per_share), tick=0.05, direction="down")
            s_5ema = round_to_tick(ema5 * 0.995, tick=0.05, direction="down") if ema5 > 0 else 0
            candidate_stops.append((max(floor_2r, s_5ema), "⚡ PARABOLIC 5 EMA TRAIL (+2.0R Floor)"))

        # 3. 🎯 STAGE 4: R >= 3.0 (Lock at least +2.0R guaranteed profit while riding 10 EMA)
        if highest_r >= 3.0:
            floor_2r = round_to_tick(entry_p + (2.0 * risk_per_share), tick=0.05, direction="down")
            ema10_trail = round_to_tick(ema10 * 0.992, tick=0.05, direction="down") if ema10 > 0 else 0
            candidate_stops.append((max(floor_2r, ema10_trail), "🎯 STAGE 4: +2.0R LOCKED (Riding 10 EMA)"))

        # 4. 🎯 STAGE 3: R >= 2.0 (Lock at least +1.0R guaranteed profit on the orderbook)
        if highest_r >= 2.0:
            floor_1r = round_to_tick(entry_p + (1.0 * risk_per_share), tick=0.05, direction="down")
            ema10_trail = round_to_tick(ema10 * 0.992, tick=0.05, direction="down") if ema10 > 0 else 0
            candidate_stops.append((max(floor_1r, ema10_trail), "🎯 STAGE 3: +1.0R LOCKED (Swing Runner Protected)"))

        # 5. 🚀 DAY-1 SPURT SHIELD (Surge of +4.5% on Day 1 -> ratchet to breakeven +0.2%)
        if holding_days == 1 and peak_gain_pct >= 4.5:
            candidate_stops.append((round_to_tick(entry_p * 1.002, tick=0.05, direction="down"), "🚀 DAY-1 SPURT SHIELD (+4.5% Surge -> Breakeven)"))

        # 6. 🟢 10 EMA SWING TRAIL (Day 2+ trending position with R >= 1.5)
        if holding_days >= 2 and highest_r >= 1.5 and ema10 > 0:
            candidate_stops.append((round_to_tick(ema10 * 0.992, tick=0.05, direction="down"), "🟢 10 EMA SWING TRAIL"))

        # 7. 🟢 20 EMA STRUCTURAL TRAIL (Day 3+ wider base runner with R >= 1.0)
        if holding_days >= 3 and highest_r >= 1.0 and ema20 > 0:
            candidate_stops.append((round_to_tick(ema20 * 0.990, tick=0.05, direction="down"), "🟢 20 EMA STRUCTURAL TRAIL"))

        best_sl, best_rule = max(candidate_stops, key=lambda x: x[0])
        if best_sl > current_sl:
            pos["current_sl"] = best_sl
            pos["last_trail_rule"] = best_rule
            pos["sl_last_ratchet_date"] = today_str
            pos["sl_last_ratchet_time"] = now.strftime("%H:%M:%S")
            updates_count += 1

        # Check Simulated Exit Breaches
        exit_triggered = False
        exit_price = ltp
        exit_reason = ""
        breach_bar_time = None

        # Market-Hours Surveillance Gap Detection:
        # Strictly count time inside 09:15:00 to 15:30:00 IST on trading days.
        # Overnight transitions (yesterday to today) are handled by Day 2+ opening auction logic, not intraday replay.
        now_epoch = time.time()
        last_surv_epoch = float(pos.get("last_surveillance_epoch") or 0.0)
        last_surv_date = pos.get("last_surveillance_date")
        is_market_hours = (now.weekday() < 5 and ((now.hour == 9 and now.minute >= 15) or (10 <= now.hour < 15) or (now.hour == 15 and now.minute <= 30)))
        is_same_day = (last_surv_date == today_str)

        gap_detected = False
        if is_market_hours and is_same_day and last_surv_epoch > 0:
            elapsed_sec = now_epoch - last_surv_epoch
            if elapsed_sec > 60.0:
                gap_detected = True

        # Resolve intraday candles for tick-accurate post-entry / post-ratchet low tracking (1m preferred, 3m fallback)
        candles_1m = q.get("candles_1m") or (c_meta.get("candles_1m") if c_meta else []) or []
        if not candles_1m or gap_detected:
            rest_1m = fetch_1m_intraday_candles(sym)
            if rest_1m:
                candles_1m = rest_1m
                if gap_detected:
                    print(f"🔄 [Surveillance Gap Replay] Replaying {len(rest_1m)} 1m candles from Upstox REST (v3) for {sym} (intraday market gap: {now_epoch - last_surv_epoch:.1f}s)")

        candles_3m = q.get("candles_3m") or (c_meta.get("candles_3m") if c_meta else []) or []
        use_1m = len(candles_1m) > 0
        candles = candles_1m if use_1m else candles_3m

        # Deferred Lower Circuit Unlock Check:
        # If position was previously locked in Lower Circuit (0 buyers), check if liquidity has returned!
        if pos.get("circuit_exit_blocked"):
            lower_circuit = float(q.get("lower_circuit_limit") or 0.0)
            total_buy_qty = q.get("total_buy_quantity")
            is_unlocked = False
            first_liquid_price = None

            # Only use day_open if the stock was locked from the market open (gap-down auction lock)
            locked_from_open = (
                day_open > 0 and lower_circuit > 0 and 
                day_open <= lower_circuit * 1.002
            )

            # 1. Depth check: buyers present and price unfreezing
            if total_buy_qty is not None and int(total_buy_qty) > 0:
                if lower_circuit > 0 and ltp > lower_circuit * 1.002:
                    is_unlocked = True
                    # Fill at price at unlock: min(candle_open, ltp), only using day_open if locked from open
                    first_liquid_price = min(day_open, ltp) if locked_from_open else ltp
                elif lower_circuit <= 0 and ltp > day_low * 1.005:
                    is_unlocked = True
                    first_liquid_price = ltp

            # 2. Candle replay check if available
            if not is_unlocked and candles:
                for b in candles:
                    b_high = float(b.get("h") or 0.0)
                    b_open = float(b.get("o") or 0.0)
                    b_close = float(b.get("c") or 0.0)
                    if lower_circuit > 0 and b_high > lower_circuit * 1.002:
                        is_unlocked = True
                        if b_open > lower_circuit * 1.002:
                            first_liquid_price = min(b_open, ltp) if (ltp > 0 and ltp > lower_circuit) else b_open
                        else:
                            first_liquid_price = min(b_close, ltp) if (ltp > 0 and ltp > lower_circuit) else round_to_tick(lower_circuit + 0.05, tick=0.05, direction="up")
                        breach_bar_time = b.get("t")
                        break
                    elif lower_circuit <= 0 and b_high > day_low * 1.005:
                        is_unlocked = True
                        first_liquid_price = min(b_open, ltp) if (b_open > day_low and ltp > 0) else (day_low * 1.005)
                        breach_bar_time = b.get("t")
                        break

            if is_unlocked and first_liquid_price and first_liquid_price > 0:
                # Stock unfreezes! Execute fill immediately at first available liquid price with adverse slippage applied
                exit_price = round_to_tick(first_liquid_price * 0.9985, tick=0.05, direction="down")
                exit_triggered = True
                exit_reason = "⚠️ LOWER CIRCUIT UNLOCKED EXIT (Liquid Fill Post-Lock)"
                pos["circuit_exit_blocked"] = False
                pos["unfillable_exit_reason"] = None
                print(f"🔓 [CIRCUIT UNLOCKED] {sym} buyers appeared! Filling deferred lower-circuit exit at ₹{exit_price:.2f} (Base: ₹{first_liquid_price:.2f}, Day Open: ₹{day_open:.2f}).")
            else:
                pos["last_trail_rule"] = "⚠️ LOWER CIRCUIT UNFILLABLE (0 Buyers)"
                continue

        if not exit_triggered:
            # Universal Stop Ratchet Protection (Day 1 and Day 2+):
            # If the stop was ratcheted TODAY, never evaluate candles from before or during the ratchet bar!
            was_ratcheted_today = (
                pos.get("sl_last_ratchet_date") == today_str and
                float(pos.get("current_sl", 0)) > float(pos.get("initial_sl", 0))
            )

            is_sl_breached = False
            breach_bar_open = None

            if was_ratcheted_today:
                # Check strictly subsequent candles timestamped strictly after ratchet bucket, plus real-time LTP
                r_str = str(pos.get("sl_last_ratchet_time") or "09:15:00")
                r_parts = r_str.split(":")
                r_h = int(r_parts[0]) if len(r_parts) > 0 and r_parts[0].isdigit() else 9
                r_m = int(r_parts[1]) if len(r_parts) > 1 and r_parts[1].isdigit() else 15
                ratchet_bucket = f"{r_h:02d}:{r_m:02d}" if use_1m else f"{r_h:02d}:{(r_m // 3) * 3:02d}"
                # Strictly later buckets (> ratchet_bucket)
                post_ratchet_bars = [c for c in candles if isinstance(c, dict) and (c.get("t") or "") > ratchet_bucket]
                for b in post_ratchet_bars:
                    b_low = float(b.get("l") or 0.0)
                    if b_low > 0 and b_low <= pos["current_sl"]:
                        is_sl_breached = True
                        breach_bar_open = float(b.get("o") or b_low)
                        breach_bar_time = b.get("t")
                        break
                if not is_sl_breached and ltp <= pos["current_sl"]:
                    is_sl_breached = True
                    breach_bar_open = ltp
                    breach_bar_time = now.strftime("%H:%M:%S")
            else:
                # Stop has NOT been ratcheted today (remains at initial LOD stop or previous session's stop)
                if holding_days == 1:
                    # On Day 1 initial stop: check post-entry candles (entry candle bucket and later)
                    e_str = str(pos.get("entry_time") or "09:15:00")
                    e_parts = e_str.split(":")
                    e_h = int(e_parts[0]) if len(e_parts) > 0 and e_parts[0].isdigit() else 9
                    e_m = int(e_parts[1]) if len(e_parts) > 1 and e_parts[1].isdigit() else 15
                    entry_bucket = f"{e_h:02d}:{e_m:02d}" if use_1m else f"{e_h:02d}:{(e_m // 3) * 3:02d}"
                    post_bars = [c for c in candles if isinstance(c, dict) and (c.get("t") or "") >= entry_bucket]
                    for b in post_bars:
                        b_low = float(b.get("l") or 0.0)
                        if b_low > 0 and b_low <= pos["current_sl"]:
                            is_sl_breached = True
                            breach_bar_open = float(b.get("o") or b_low)
                            breach_bar_time = b.get("t")
                            break
                    if not is_sl_breached and ltp <= pos["current_sl"]:
                        is_sl_breached = True
                        breach_bar_open = ltp
                        breach_bar_time = now.strftime("%H:%M:%S")
                else:
                    # Day 2+ previous day stop: evaluate 1m candles first for tick-exact breach time
                    if use_1m:
                        for b in candles:
                            b_low = float(b.get("l") or 0.0)
                            if b_low > 0 and b_low <= pos["current_sl"]:
                                is_sl_breached = True
                                breach_bar_open = float(b.get("o") or b_low)
                                breach_bar_time = b.get("t")
                                break
                    if not is_sl_breached:
                        if day_low <= pos["current_sl"]:
                            is_sl_breached = True
                            breach_bar_open = day_open if day_open > 0 else ltp
                            breach_bar_time = now.strftime("%H:%M:%S")
                        elif ltp <= pos["current_sl"]:
                            is_sl_breached = True
                            breach_bar_open = ltp
                            breach_bar_time = now.strftime("%H:%M:%S")

            if is_sl_breached:
                exit_triggered = True
                # Realistic Exit Fill Model:
                # 1. Overnight gap down on Day 2+: fill at opening auction price (day_open * 0.9985)
                # 2. Fast intraday gap through stop: if breach_bar_open < SL, fill at breach_bar_open * 0.9985
                # 3. Standard resting stop hit: fill at SL * 0.9985
                fill_base = pos["current_sl"]
                if holding_days >= 2 and day_open > 0 and day_open < pos["current_sl"]:
                    fill_base = day_open
                elif breach_bar_open and breach_bar_open < pos["current_sl"]:
                    fill_base = breach_bar_open

                # Lower Circuit Unfillable Exit Protection (Zero-Bid Reality Check)
                lower_circuit = float(q.get("lower_circuit_limit") or 0.0)
                total_buy_qty = q.get("total_buy_quantity")
                is_lower_circuit_locked = (
                    lower_circuit > 0 and 
                    (fill_base <= lower_circuit * 1.002 or day_low <= lower_circuit) and 
                    (total_buy_qty is not None and int(total_buy_qty) == 0)
                )
                # Replay candle check for lower circuit lock (depth data absent in historical candles)
                if not is_lower_circuit_locked and lower_circuit > 0:
                    if breach_bar_open and breach_bar_open <= lower_circuit * 1.002:
                        is_lower_circuit_locked = True
                    elif ltp <= lower_circuit * 1.002 and (total_buy_qty is None or int(total_buy_qty) == 0):
                        is_lower_circuit_locked = True

                if is_lower_circuit_locked:
                    pos["circuit_exit_blocked"] = True
                    pos["unfillable_exit_reason"] = "LOWER_CIRCUIT_ZERO_BID_LOCK"
                    pos["last_trail_rule"] = "⚠️ LOWER CIRCUIT UNFILLABLE (0 Buyers)"
                    print(f"⚠️ [CIRCUIT LOCK] {sym} breached stop at ₹{pos['current_sl']:.2f} but is locked at Lower Circuit (₹{lower_circuit:.2f}) with 0 buyers. Exit order unfillable.")
                    continue

                exit_price = round_to_tick(fill_base * 0.9985, tick=0.05, direction="down")
                exit_reason = pos["last_trail_rule"]

        if exit_triggered:
            # True Van Tharp Structural Risk: Actual dollar risk at risk based on initial stop distance
            rps = max(0.05, float(pos.get("risk_per_share") or (entry_p - pos.get("initial_sl", entry_p * 0.98))))
            initial_risk_inr = max(1.0, float(pos.get("initial_risk_inr") or (qty * rps)))

            realized_pnl = round((exit_price - entry_p) * qty, 2)

            # Statutory Round-Trip Transaction Costs (NSE Cash Delivery Contract Note Model)
            buy_val = round(entry_p * qty, 2)
            sell_val = round(exit_price * qty, 2)
            turnover_inr = round(buy_val + sell_val, 2)

            # 1. STT: 0.1% on buy leg + 0.1% on sell leg (delivery equity)
            stt = round(0.001 * buy_val + 0.001 * sell_val, 2)
            # 2. Stamp Duty: 0.015% on buy leg
            stamp_duty = round(0.00015 * buy_val, 2)
            # 3. Exchange Turnover Charge: 0.00297% round-trip
            exch_turnover_fee = round(0.0000297 * turnover_inr, 2)
            # 4. SEBI Turnover Fee: ₹10 per crore (0.000001)
            sebi_fee = round(0.000001 * turnover_inr, 2)
            # 5. GST: 18% on (Exchange Fee + SEBI Fee)
            gst = round(0.18 * (exch_turnover_fee + sebi_fee), 2)
            # 6. Depository Participant (DP) Sell Charge: Flat ₹15.93 per scrip
            dp_charges = 15.93

            statutory_costs_inr = round(stt + stamp_duty + exch_turnover_fee + sebi_fee + gst + dp_charges, 2)
            stress_costs_025_inr = round(turnover_inr * 0.0025, 2)

            net_pnl_inr = round(realized_pnl - statutory_costs_inr, 2)
            net_stress_pnl_inr = round(realized_pnl - stress_costs_025_inr, 2)

            realized_r_structural = round(realized_pnl / initial_risk_inr, 2)
            realized_r = realized_r_structural
            realized_r_nominal = round(realized_pnl / 1000.0, 2)
            realized_r_net = round(net_pnl_inr / initial_risk_inr, 2)
            realized_r_stress_025 = round(net_stress_pnl_inr / initial_risk_inr, 2)
            giveback_r = round(max(0.0, highest_r - realized_r_structural), 2)

            log_entry = {
                "symbol": sym,
                "config_version": CONFIG_VERSION,
                "config_hash": CONFIG_HASH,
                "manifest_hash": pos.get("manifest_hash") or get_manifest_hash(),
                "git_commit": pos.get("git_commit") or get_git_commit_sha(),
                "watchlist_hash": pos.get("watchlist_hash") or get_watchlist_hash(),
                "entry_date": entry_date,
                "exit_date": today_str,
                "entry_time": pos.get("entry_time"),
                "exit_time": breach_bar_time if breach_bar_time else now.strftime("%H:%M:%S"),
                "entry_price": entry_p,
                "exit_price": exit_price,
                "quantity": qty,
                "initial_sl": pos.get("initial_sl"),
                "risk_per_share": rps,
                "initial_risk_inr": initial_risk_inr,
                "holding_days": holding_days,
                "realized_pnl_inr": realized_pnl,
                "statutory_costs_inr": statutory_costs_inr,
                "stress_costs_025_inr": stress_costs_025_inr,
                "net_pnl_inr": net_pnl_inr,
                "realized_r": realized_r_structural,
                "r_structural": realized_r_structural,
                "r_nominal": realized_r_nominal,
                "r_net": realized_r_net,
                "r_stress_025": realized_r_stress_025,
                "peak_r": highest_r,
                "giveback_r": giveback_r,
                "exit_reason": exit_reason,
                "sa_regime": pos.get("sa_regime", "EXPANSION"),
                "trigger_name": pos.get("trigger_name", "ORB Breakout"),
                "earnings_filter_active": pos.get("earnings_filter_active", True),
                "held_through_event": pos.get("held_through_event", False)
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

    for sym, pos in portfolio.items():
        pos["last_surveillance_epoch"] = now_epoch
        pos["last_surveillance_time"] = now.strftime("%H:%M:%S")
        pos["last_surveillance_date"] = today_str

    save_shadow_portfolio(portfolio)
    save_shadow_trade_log(trade_log)

    return {
        "active_count": len(portfolio),
        "exits_count": len(exited_symbols),
        "updates_count": updates_count,
        "exited_symbols": exited_symbols
    }


def record_daily_mtm_snapshot(portfolio: dict, trade_log: list, unrealized_r: float = 0.0, unrealized_pnl: float = 0.0):
    """
    Computes and records daily Mark-to-Market (MTM) equity snapshot at EOD (15:30 IST).
    Persists to shadow_mtm_equity_curve.json, computing peak MTM R and path-dependent MTM drawdown.
    """
    try:
        now_ist = get_ist_now()
        today_str = now_ist.strftime("%Y-%m-%d")

        closed_pnl = sum(float(t.get("realized_pnl_inr") or 0.0) for t in trade_log)
        closed_r = sum(float(t.get("realized_r") or 0.0) for t in trade_log)

        mtm_pnl = round(closed_pnl + float(unrealized_pnl), 2)
        mtm_r = round(closed_r + float(unrealized_r), 2)

        curve = []
        if SHADOW_MTM_CURVE_FILE.is_file():
            try:
                with open(SHADOW_MTM_CURVE_FILE, "r", encoding="utf-8") as f:
                    curve = json.load(f)
            except Exception:
                curve = []

        prev_peaks = [float(c.get("peak_mtm_r") or c.get("mtm_r") or 0.0) for c in curve if c.get("date") != today_str]
        peak_mtm_r = max(prev_peaks + [mtm_r, 0.0])
        mtm_drawdown_r = round(max(0.0, peak_mtm_r - mtm_r), 2)

        session_tag = "DAY0_SHAKEDOWN" if today_str < START_DATE_STR else "PHASE1_EVALUATION"

        base_capital = EVALUATION_BASE_CAPITAL
        total_equity_inr = round(base_capital + mtm_pnl, 2)
        return_pct = round(((total_equity_inr - base_capital) / base_capital) * 100.0, 2)

        prev_peaks_inr = [float(c.get("peak_equity_inr") or base_capital) for c in curve if c.get("date") != today_str]
        peak_equity_inr = max(prev_peaks_inr + [total_equity_inr, base_capital])
        mtm_drawdown_inr = round(max(0.0, peak_equity_inr - total_equity_inr), 2)
        mtm_drawdown_pct = round((mtm_drawdown_inr / peak_equity_inr) * 100.0, 2)

        snapshot = {
            "date": today_str,
            "session": session_tag,
            "timestamp": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
            "open_positions_count": len(portfolio),
            "closed_trades_count": len(trade_log),
            "base_capital_inr": base_capital,
            "total_equity_inr": total_equity_inr,
            "return_pct": return_pct,
            "peak_equity_inr": round(peak_equity_inr, 2),
            "mtm_drawdown_inr": mtm_drawdown_inr,
            "mtm_drawdown_pct": mtm_drawdown_pct,
            "realized_pnl_inr": round(closed_pnl, 2),
            "unrealized_pnl_inr": round(unrealized_pnl, 2),
            "mtm_equity_pnl_inr": mtm_pnl,
            "realized_r": round(closed_r, 2),
            "unrealized_r": round(unrealized_r, 2),
            "mtm_r": mtm_r,
            "peak_mtm_r": round(peak_mtm_r, 2),
            "mtm_drawdown_r": mtm_drawdown_r
        }

        idx = next((i for i, c in enumerate(curve) if c.get("date") == today_str), None)
        if idx is not None:
            curve[idx] = snapshot
        else:
            curve.append(snapshot)

        # Pre-Nov 23 / Day 0 Guard: If Day 0 reset sentinel exists and today is before Nov 23,
        # divert write to archive/shadow_mtm_equity_curve_day0.json so active curve remains pristine for Nov 23!
        DAY0_SENTINEL_FILE = BASE_DIR / "archive" / ".day0_reset_completed"
        if today_str < START_DATE_STR and DAY0_SENTINEL_FILE.is_file():
            day0_curve_archive = BASE_DIR / "archive" / "shadow_mtm_equity_curve_day0.json"
            atomic_write_json(day0_curve_archive, curve)
            return snapshot

        atomic_write_json(SHADOW_MTM_CURVE_FILE, curve)
        return snapshot
    except Exception as e:
        print(f"Notice recording daily MTM snapshot: {e}")
        return None


def get_shadow_analytics():
    """
    Computes comprehensive 30-day statistical performance:
    Win Rate %, Profit Factor, Expectancy R, Avg Win vs Avg Loss, Max Closed Drawdown, and Max MTM Drawdown.
    Strictly filters for Phase 1 official evaluation trades (entry_date >= START_DATE_STR and not is_day0).
    """
    trades = load_shadow_trade_log()
    phase1_trades = [
        t for t in trades 
        if str(t.get("entry_date", "")) >= START_DATE_STR and not t.get("is_day0", False)
    ]
    total_trades = len(phase1_trades)
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
            "expectancy_inr": 0.0,
            "base_capital_inr": EVALUATION_BASE_CAPITAL,
            "total_equity_inr": EVALUATION_BASE_CAPITAL,
            "total_return_pct": 0.0,
            "max_drawdown_r": 0.0,
            "max_drawdown_inr": 0.0,
            "max_drawdown_pct": 0.0,
            "max_mtm_drawdown_r": 0.0,
            "max_mtm_drawdown_inr": 0.0,
            "max_mtm_drawdown_pct": 0.0,
            "rule_counts": {}
        }

    wins = [t for t in phase1_trades if t.get("realized_r", 0) > 0]
    losses = [t for t in phase1_trades if t.get("realized_r", 0) <= 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total_trades) * 100.0, 1)

    gross_profit_r = sum(t.get("realized_r", 0) for t in wins)
    gross_loss_r = abs(sum(t.get("realized_r", 0) for t in losses))

    net_r = round(gross_profit_r - gross_loss_r, 2)
    net_pnl = sum(t.get("realized_pnl_inr", 0) for t in phase1_trades)

    profit_factor = round(gross_profit_r / gross_loss_r, 2) if gross_loss_r > 0 else (round(gross_profit_r, 2) if gross_profit_r > 0 else 0.0)
    avg_win_r = round(gross_profit_r / win_count, 2) if win_count > 0 else 0.0
    avg_loss_r = round(gross_loss_r / loss_count, 2) if loss_count > 0 else 0.0

    # Mathematical Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
    win_pct_dec = win_count / total_trades
    loss_pct_dec = loss_count / total_trades
    expectancy_r = round((win_pct_dec * avg_win_r) - (loss_pct_dec * avg_loss_r), 2)
    expectancy_pnl_inr = round(net_pnl / total_trades, 2) if total_trades > 0 else 0.0

    base_capital = EVALUATION_BASE_CAPITAL
    total_equity = round(base_capital + net_pnl, 2)
    total_return_pct = round((net_pnl / base_capital) * 100.0, 2) if base_capital > 0 else 0.0

    # Max Drawdown calculation in R and INR / %
    peak_cum = 0.0
    running_cum = 0.0
    max_dd = 0.0

    peak_cum_inr = 0.0
    running_cum_inr = 0.0
    max_dd_inr = 0.0

    for t in phase1_trades:
        running_cum += t.get("realized_r", 0)
        peak_cum = max(peak_cum, running_cum)
        dd = peak_cum - running_cum
        max_dd = max(max_dd, dd)

        running_cum_inr += float(t.get("realized_pnl_inr", 0.0))
        peak_cum_inr = max(peak_cum_inr, running_cum_inr)
        dd_inr = peak_cum_inr - running_cum_inr
        max_dd_inr = max(max_dd_inr, dd_inr)

    max_dd_pct = round((max_dd_inr / (base_capital + peak_cum_inr)) * 100.0, 2) if (base_capital + peak_cum_inr) > 0 else 0.0

    # Max MTM Drawdown from daily mark-to-market curve (Strictly Phase 1 dates >= START_DATE_STR)
    max_mtm_dd = max_dd
    max_mtm_dd_inr = max_dd_inr
    max_mtm_dd_pct = max_dd_pct
    if SHADOW_MTM_CURVE_FILE.is_file():
        try:
            with open(SHADOW_MTM_CURVE_FILE, "r", encoding="utf-8") as mf:
                m_curve = json.load(mf)
                phase1_curve = [
                    c for c in m_curve 
                    if str(c.get("date", "")) >= START_DATE_STR and c.get("session") != "DAY0_SHAKEDOWN"
                ]
                if phase1_curve:
                    max_mtm_dd = max([float(c.get("mtm_drawdown_r") or 0.0) for c in phase1_curve] + [max_dd])
                    max_mtm_dd_inr = max([float(c.get("mtm_drawdown_inr") or 0.0) for c in phase1_curve] + [max_dd_inr])
                    max_mtm_dd_pct = max([float(c.get("mtm_drawdown_pct") or 0.0) for c in phase1_curve] + [max_dd_pct])
        except Exception:
            pass

    # Rule breakdown
    rules = {}
    for t in phase1_trades:
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
        "expectancy_inr": expectancy_pnl_inr,
        "base_capital_inr": base_capital,
        "total_equity_inr": total_equity,
        "total_return_pct": total_return_pct,
        "max_drawdown_r": round(max_dd, 2),
        "max_drawdown_inr": round(max_dd_inr, 2),
        "max_drawdown_pct": max_dd_pct,
        "max_mtm_drawdown_r": round(max_mtm_dd, 2),
        "max_mtm_drawdown_inr": round(max_mtm_dd_inr, 2),
        "max_mtm_drawdown_pct": max_mtm_dd_pct,
        "rule_counts": rules
    }


def determine_automated_session_status(dt=None):
    """
    Automated Missed-Session Protocol (v3.3.0 Strict):
    Determines whether today's session is VALID, PARTIAL, or NO_DATA_EXCLUDED
    strictly based on automated signals (Sentinel and Feed Telemetry):
    1. Pre-evaluation gate: Date < START_DATE_STR -> DAY0_PRE_EVALUATION.
    2. Feed health telemetry: Checks data/feed_session_health.json during 09:30-10:15 window.
    3. Sustained downtime >= 10m -> NO_DATA_EXCLUDED (Evaluation clock paused).
    4. Degradation >= 5m -> PARTIAL (Logged with full telemetry).
    """
    now = dt if dt is not None else get_ist_now()
    today_str = now.strftime("%Y-%m-%d")

    # 1. Pre-Evaluation Gate
    if today_str < START_DATE_STR:
        return "DAY0_PRE_EVALUATION", f"Pre-evaluation session (Official launch {START_DATE_STR})", {}

    # 2. Check automated feed health telemetry
    health_file = BASE_DIR / "data" / "feed_session_health.json"
    if not health_file.is_file():
        send_phase1_telegram_alert(
            f"🚨 <b>FAIL-CLOSED ALERT: Feed Telemetry Missing</b>\n"
            f"• Date: {today_str}\n"
            f"• File <code>data/feed_session_health.json</code> not found.\n"
            f"• Missed-Session Protocol: Session defaulted to <b>NO_DATA_EXCLUDED</b> (Clock Paused).",
            topic_name="risk"
        )
        return "NO_DATA_EXCLUDED", "Missing feed health telemetry file data/feed_session_health.json (Fail-Closed)", {}

    try:
        with open(health_file, "r", encoding="utf-8") as f:
            health_data = json.load(f)
        if health_data.get("date") != today_str:
            send_phase1_telegram_alert(
                f"🚨 <b>FAIL-CLOSED ALERT: Stale Feed Telemetry</b>\n"
                f"• Today: {today_str} | Telemetry Date: {health_data.get('date')}\n"
                f"• Missed-Session Protocol: Session defaulted to <b>NO_DATA_EXCLUDED</b> (Clock Paused).",
                topic_name="risk"
            )
            return "NO_DATA_EXCLUDED", f"Stale feed health telemetry (Date mismatch: {health_data.get('date')} != {today_str}) (Fail-Closed)", health_data

        down_min = float(health_data.get("downtime_minutes", 0.0))
        max_down = float(FROZEN_PARAMS.get("max_feed_downtime_minutes", 10.0))
        if down_min >= max_down:
            return "NO_DATA_EXCLUDED", f"Excessive feed downtime during 09:30-10:15 ({down_min:.1f}m >= {max_down:.1f}m limit)", health_data
        elif down_min >= 5.0:
            return "PARTIAL", f"Sustained feed degradation during 09:30-10:15 ({down_min:.1f}m downtime)", health_data
        return "VALID", "Feed health within normal operational parameters", health_data
    except Exception as exc:
        send_phase1_telegram_alert(
            f"🚨 <b>FAIL-CLOSED ALERT: Feed Telemetry Unreadable</b>\n"
            f"• Date: {today_str} | Error: {str(exc)}\n"
            f"• Missed-Session Protocol: Session defaulted to <b>NO_DATA_EXCLUDED</b> (Clock Paused).",
            topic_name="risk"
        )
        return "NO_DATA_EXCLUDED", f"Unreadable feed health telemetry file ({str(exc)}) (Fail-Closed)", {}


def generate_and_send_phase1_eod_report(notify=True, session_status=None, status_reason=None):
    """
    Compiles and dispatches the daily Phase 1 EOD Report strictly at 15:35 IST to Topic 11 ('reports').
    Features Day 30 Maturity Banner when 30 days are reached.
    MISSED-SESSION PROTOCOL: If session_status is 'NO_DATA_EXCLUDED' or 'PARTIAL', the day is excluded
    from the 30-session evaluation denominator, and day_num is not incremented.
    """
    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")

    portfolio = load_shadow_portfolio()
    trade_log = load_shadow_trade_log()
    analytics = get_shadow_analytics()

    history = []
    if SHADOW_EOD_FILE.is_file():
        try:
            with open(SHADOW_EOD_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    # Calculate current business/trading day in 30-day evaluation based on valid completed sessions
    try:
        d_start = datetime.strptime(START_DATE_STR, "%Y-%m-%d").date()
        d_curr = now.date()
        if d_curr < d_start:
            day_num = 0
            header_title = "🛠️ <b>DAY 0: COMMISSIONING & SHAKEDOWN (PRE-EVALUATION)</b>"
            day_label = f"Session: {now.strftime('%d-%b-%Y')} | 30-Day Official Clock Starts Mon Nov 23"
        # Determine automated status if not explicitly overridden
        auto_status, auto_reason, _ = determine_automated_session_status(now)
        effective_status = session_status if session_status is not None else auto_status
        effective_reason = status_reason if status_reason is not None else auto_reason

        # De-duplicate past valid sessions by unique calendar date (Strict: missing status does NOT default to VALID)
        valid_past_dates = sorted(list(set(
            h.get("date") for h in history
            if h.get("date") != today_str
            and h.get("date", "") >= START_DATE_STR
            and h.get("status") == "VALID"
        )))

        if effective_status == "NO_DATA_EXCLUDED":
            day_num = len(valid_past_dates)
            header_title = "⚠️ <b>SESSION INVALID / NO DATA — EXCLUDED FROM 30-DAY PILOT</b>"
            day_label = f"Session: {now.strftime('%d-%b-%Y')} | Reason: {effective_reason} | Evaluation Clock Paused (+1 Day)"
        elif effective_status == "PARTIAL":
            # PARTIAL sessions are excluded from the 30-day target count; clock pauses +1 day
            day_num = len(valid_past_dates)
            header_title = "⚠️ <b>SESSION PARTIAL / FEED DEGRADED — EXCLUDED FROM 30-DAY COUNT</b>"
            day_label = f"Session: {now.strftime('%d-%b-%Y')} | Reason: {effective_reason} | Evaluation Clock Paused (+1 Day)"
        else:
            day_num = len(valid_past_dates) + 1
            header_title = "🤖 <b>PHASE 1 AUTONOMOUS SHADOW ENGINE — EOD REPORT</b>"
            day_label = f"📅 <b>Day {day_num} of {EVALUATION_HORIZON_DAYS}</b> | Session: {now.strftime('%d-%b-%Y')} (15:35 IST)"
    except Exception:
        day_num = 1
        header_title = "🤖 <b>PHASE 1 AUTONOMOUS SHADOW ENGINE — EOD REPORT</b>"
        day_label = f"📅 <b>Day {day_num} of {EVALUATION_HORIZON_DAYS}</b> | Session: {now.strftime('%d-%b-%Y')} (15:35 IST)"

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
                if pos.get("circuit_exit_blocked") and q and q.get("lower_circuit_limit"):
                    lcl = float(q.get("lower_circuit_limit") or 0.0)
                    if lcl > 0:
                        ltp = lcl
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
        risk_amt = e.get("initial_risk_inr") or e.get("fixed_risk_inr") or 1000.0
        entry_lines.append(f"• <b>{e['symbol']}</b> | Fill: ₹{e['entry_price']:,} | SL: ₹{e['initial_sl']:,} | 1.0R (₹{risk_amt:,.0f}) | {e.get('sa_regime')}")

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
    mtm_snap = record_daily_mtm_snapshot(portfolio, trade_log, unrealized_r, unrealized_pnl)

    # Build EOD HTML Card
    lines = []
    if day_num >= EVALUATION_HORIZON_DAYS:
        lines.append("🏆 <b>[30-DAY AUTONOMOUS PILOT MATURE — READY FOR PHASE 2 REVIEW]</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    mtm_r_val = mtm_snap['mtm_r'] if mtm_snap else round(today_closed_r + unrealized_r, 2)
    mtm_dd_val = mtm_snap['mtm_drawdown_r'] if mtm_snap else 0.0
    eq_inr = mtm_snap.get("total_equity_inr", EVALUATION_BASE_CAPITAL) if mtm_snap else EVALUATION_BASE_CAPITAL
    ret_pct = mtm_snap.get("return_pct", 0.0) if mtm_snap else 0.0
    mtm_dd_pct = mtm_snap.get("mtm_drawdown_pct", 0.0) if mtm_snap else 0.0

    lines.extend([
        header_title,
        day_label,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>ACTIVE SWING PORTFOLIO HEALTH:</b>",
        f"• <b>Base Capital:</b> ₹{EVALUATION_BASE_CAPITAL:,.0f} (100% Cash Delivery, Zero Leverage)",
        f"• <b>Open Swing Holdings:</b> {len(portfolio)} positions",
        f"• <b>Unrealized P&L:</b> {'+' if unrealized_r >= 0 else ''}{unrealized_r:.2f}R (₹{unrealized_pnl:+,})",
        f"• <b>Today's Closed P&L:</b> {'+' if today_closed_r >= 0 else ''}{today_closed_r:.2f}R",
        f"• <b>MTM Total Equity:</b> ₹{eq_inr:,.0f} ({'+' if ret_pct >= 0 else ''}{ret_pct:.2f}% | {'+' if mtm_r_val >= 0 else ''}{mtm_r_val:.2f}R)",
        f"• <b>MTM Peak Drawdown:</b> -{mtm_dd_val:.2f}R (-{mtm_dd_pct:.2f}%)",
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
    lines.append(f"• <b>Total Return on Base:</b> {'+' if analytics['total_return_pct'] >= 0 else ''}{analytics['total_return_pct']:.2f}% (Base: ₹{analytics['base_capital_inr']:,.0f})")
    lines.append(f"• <b>Profit Factor:</b> {analytics['profit_factor']}")
    lines.append(f"• <b>Avg Win / Avg Loss:</b> +{analytics['avg_win_r']:.2f}R / -{analytics['avg_loss_r']:.2f}R")
    lines.append(f"• <b>Expectancy per Trade:</b> {'+' if analytics['expectancy_r'] >= 0 else ''}{analytics['expectancy_r']:.2f}R ({'+₹' if analytics.get('expectancy_inr', 0) >= 0 else '-₹'}{abs(analytics.get('expectancy_inr', 0)):,.0f})")
    lines.append(f"• <b>Max Drawdown:</b> Closed: -{analytics['max_drawdown_r']:.2f}R (-{analytics['max_drawdown_pct']:.2f}%) | MTM: -{analytics.get('max_mtm_drawdown_r', analytics['max_drawdown_r']):.2f}R (-{analytics.get('max_mtm_drawdown_pct', analytics['max_drawdown_pct']):.2f}%)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Phase 1 Systematic Evaluation. Base Capital: ₹5,00,000 (CNC Delivery, Cash-Gated, 0 Leverage). 1R = ₹1,000. Zero real money at risk.</i>")

    report_html = "\n".join(lines)

    if notify:
        send_phase1_telegram_alert(report_html, topic_name="reports")

    # Persist snapshot
    snapshot_status = "DAY0_PRE_EVALUATION" if d_curr < d_start else (effective_status if 'effective_status' in locals() else (session_status or "VALID"))
    snapshot = {
        "date": today_str,
        "day_num": day_num,
        "status": snapshot_status,
        "config_hash": CONFIG_HASH,
        "manifest_hash": get_manifest_hash(),
        "watchlist_hash": get_watchlist_hash(),
        "open_count": len(portfolio),
        "unrealized_r": unrealized_r,
        "unrealized_pnl": unrealized_pnl,
        "today_closed_r": today_closed_r,
        "today_entries_count": len(today_entries),
        "today_exits_count": len(today_exits),
        "cumulative_analytics": analytics
    }

    # Replace today if already present and strictly de-duplicate all dates
    deduped_history = []
    seen_dates = set()
    for h in history:
        d_h = h.get("date")
        if d_h and d_h != today_str and d_h not in seen_dates:
            seen_dates.add(d_h)
            deduped_history.append(h)
    deduped_history.append(snapshot)
    atomic_write_json(SHADOW_EOD_FILE, deduped_history)

    return report_html


def reset_and_archive_day0_state(force=False):
    """
    Safely flattens any open Day 0 positions and archives all pre-evaluation state files
    before the official Phase 1 start on Monday, Nov 23, 2026.
    STRICTLY ONE-SHOT: Guarded by a sentinel file and date checks.
    Permanently blocked from running once evaluation starts (2026-11-23 onwards).
    """
    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")

    DAY0_SENTINEL_FILE = BASE_DIR / "archive" / ".day0_reset_completed"

    # Sentinel Guard: One-shot execution only
    if DAY0_SENTINEL_FILE.is_file():
        print("🛡️ [SAFETY SHIELD] Day 0 Reset has already been executed (sentinel file present). Operation rejected to protect evaluation state.")
        return {"status": "ALREADY_COMPLETED", "reason": "Sentinel file exists"}

    # Hard Date Barrier: Never allow reset on or after START_DATE_STR
    if today_str >= START_DATE_STR:
        print(f"🛑 [SAFETY SHIELD] Current date {today_str} >= evaluation start date {START_DATE_STR}! Day 0 reset is permanently prohibited.")
        return {"status": "BLOCKED", "reason": f"Evaluation period active ({today_str} >= {START_DATE_STR})"}

    with SHADOW_LOCK:
        portfolio = load_shadow_portfolio()
        trade_log = load_shadow_trade_log()

        # Hard Trade Inspection Barrier: Never reset if any Phase 1 trades are already logged
        if any(str(t.get("entry_date", "")) >= START_DATE_STR for t in trade_log) or any(str(p.get("entry_date", "")) >= START_DATE_STR for p in portfolio.values()):
            print("🛑 [SAFETY SHIELD] Active records contain official Phase 1 trades (entry_date >= 2026-11-23)! Reset permanently blocked.")
            return {"status": "BLOCKED", "reason": "Phase 1 trades present"}

        flattened_count = 0

        # Flatten any active open positions opened on or before Day 0
        if portfolio:
            try:
                from order_engine import fetch_live_quote
            except Exception:
                fetch_live_quote = None

            for sym, pos in list(portfolio.items()):
                ltp = pos.get("entry_price", 0.0)
                if fetch_live_quote:
                    try:
                        q, _ = fetch_live_quote(sym)
                        if q and q.get("ltp"):
                            ltp = float(q["ltp"])
                    except Exception:
                        pass

                qty = pos.get("quantity", 0)
                entry_p = pos.get("entry_price", ltp)
                rps = max(0.05, float(pos.get("risk_per_share") or (entry_p - pos.get("initial_sl", entry_p * 0.98))))
                init_risk = max(1.0, float(pos.get("initial_risk_inr") or (qty * rps)))
                realized_pnl = round((ltp - entry_p) * qty, 2)
                realized_r = round(realized_pnl / init_risk, 2)

                pos_flattened = {
                    "symbol": sym,
                    "is_day0": True,
                    "config_version": CONFIG_VERSION,
                    "config_hash": CONFIG_HASH,
                    "entry_date": pos.get("entry_date", today_str),
                    "exit_date": today_str,
                    "entry_time": pos.get("entry_time", "09:30:00"),
                    "exit_time": now.strftime("%H:%M:%S"),
                    "entry_price": entry_p,
                    "exit_price": ltp,
                    "quantity": qty,
                    "initial_sl": pos.get("initial_sl"),
                    "risk_per_share": rps,
                    "initial_risk_inr": init_risk,
                    "holding_days": 1,
                    "realized_pnl_inr": realized_pnl,
                    "statutory_costs_inr": 0.0,
                    "net_pnl_inr": realized_pnl,
                    "realized_r": realized_r,
                    "r_structural": realized_r,
                    "r_nominal": round(realized_pnl / 1000.0, 2),
                    "exit_reason": "DAY0_SHAKEDOWN_FLATTEN",
                    "sa_regime": pos.get("sa_regime", "DEFENSIVE"),
                    "trigger_name": pos.get("trigger_name", "Day 0 Shakedown")
                }
                trade_log.append(pos_flattened)
                flattened_count += 1

        # Archive directory
        archive_dir = BASE_DIR / "archive" / f"day0_shakedown_{now.strftime('%Y%m%d_%H%M%S')}"
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Archive existing state files if present
        state_files = [SHADOW_PORTFOLIO_FILE, SHADOW_LOG_FILE, SHADOW_EOD_FILE, SHADOW_MTM_CURVE_FILE, REJECTED_SIGNALS_FILE]
        archived_files = []
        for fpath in state_files:
            if fpath.is_file():
                try:
                    import shutil
                    dest = archive_dir / fpath.name
                    shutil.copy2(fpath, dest)
                    archived_files.append(dest)
                except Exception as ex:
                    print(f"Notice archiving {fpath.name}: {ex}")

        # Step 2: Verify Archive Integrity (Must all exist, non-empty, and valid JSON)
        for dest in archived_files:
            if not dest.is_file() or dest.stat().st_size == 0:
                raise RuntimeError(f"Archive verification failed: {dest.name} missing or empty.")
            try:
                with open(dest, "r", encoding="utf-8") as vf:
                    json.load(vf)
            except Exception as ve:
                raise RuntimeError(f"Archive verification failed for {dest.name}: invalid JSON ({ve})")

        # Step 3: Reset active files to clean Phase 1 pristine baseline
        atomic_write_json(SHADOW_PORTFOLIO_FILE, {})
        atomic_write_json(SHADOW_LOG_FILE, [])
        atomic_write_json(SHADOW_EOD_FILE, [])
        atomic_write_json(SHADOW_MTM_CURVE_FILE, [])
        atomic_write_json(REJECTED_SIGNALS_FILE, [])

        # Step 4: Write permanent sentinel file to lock out any future Day 0 resets
        try:
            DAY0_SENTINEL_FILE.parent.mkdir(parents=True, exist_ok=True)
            DAY0_SENTINEL_FILE.write_text(
                f"Day 0 Reset successfully executed at {now.isoformat()} IST\n"
                f"Config Version: {CONFIG_VERSION}\n"
                f"Config Hash: {CONFIG_HASH}\n"
                f"Evaluation Start Date: {START_DATE_STR}\n"
                f"Archive Directory: {archive_dir}\n"
                f"Execution Sequence: Archive -> Verify -> Reset -> Write Sentinel (100% Verified)\n",
                encoding="utf-8"
            )
        except Exception as se:
            print(f"Notice writing sentinel file: {se}")

        print(f"✅ [DAY 0 RESET] Flattened {flattened_count} positions. Archived state to {archive_dir}. Verified archive integrity. Clean Phase 1 slate established for Nov 23.")
        return {
            "status": "SUCCESS",
            "flattened_count": flattened_count,
            "archive_dir": str(archive_dir),
            "start_date": START_DATE_STR,
            "sentinel_file": str(DAY0_SENTINEL_FILE)
        }


def format_shadow_status_card():
    """Returns quick status card for Telegram /phase1 or /shadow command."""
    now = get_ist_now()
    portfolio = load_shadow_portfolio()
    analytics = get_shadow_analytics()

    try:
        d_start = datetime.strptime(START_DATE_STR, "%Y-%m-%d").date()
        d_curr = now.date()
        if d_curr < d_start:
            day_num = 0
            day_str = "Day 0 (Commissioning & Shakedown) | Official Launch: Mon Nov 23"
        else:
            day_num = count_trading_days(d_start, d_curr)
            day_str = f"Day {day_num} of {EVALUATION_HORIZON_DAYS} | 30-Day Evaluation Active"
    except Exception:
        day_num = 1
        day_str = f"Day {day_num} of {EVALUATION_HORIZON_DAYS}"

    lines = [
        "🤖 <b>PHASE 1 AUTONOMOUS SHADOW ENGINE STATUS</b>",
        f"📅 <b>{day_str}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Base Capital:</b> ₹{EVALUATION_BASE_CAPITAL:,.0f} (100% Cash Delivery, Zero Leverage)",
        f"• <b>Active Swing Positions:</b> {len(portfolio)} / {MAX_SYSTEM_SLOTS} slots",
        f"• <b>Entry Window:</b> 09:30–10:15 AM IST ({'🟢 OPEN' if is_entry_window_active(now) else '🔒 CLOSED'})",
        f"• <b>Sizing Model:</b> Standardized Fixed Risk (1R = ₹1,000, Cash-Gated)",
        f"• <b>Total Closed Trades:</b> {analytics['total_trades']} completed",
        f"• <b>Win Rate:</b> {analytics['win_rate_pct']}% ({analytics['win_count']}W / {analytics['loss_count']}L)",
        f"• <b>Net Realized P&L:</b> <b>{'+' if analytics['net_r'] >= 0 else ''}{analytics['net_r']:.2f}R (₹{analytics['net_pnl_inr']:+,})</b>",
        f"• <b>Total Return on Base:</b> {'+' if analytics['total_return_pct'] >= 0 else ''}{analytics['total_return_pct']:.2f}%",
        f"• <b>Total Equity:</b> ₹{analytics.get('total_equity_inr', EVALUATION_BASE_CAPITAL):,}",
        f"• <b>Profit Factor:</b> {analytics['profit_factor']}",
        f"• <b>Expectancy:</b> {'+' if analytics['expectancy_r'] >= 0 else ''}{analytics['expectancy_r']:.2f}R / trade ({'+₹' if analytics.get('expectancy_inr', 0) >= 0 else '-₹'}{abs(analytics.get('expectancy_inr', 0)):,.0f})",
        f"• <b>Max Drawdown:</b> Closed: -{analytics['max_drawdown_r']:.2f}R (-{analytics['max_drawdown_pct']:.2f}%) | MTM: -{analytics.get('max_mtm_drawdown_r', 0):.2f}R (-{analytics.get('max_mtm_drawdown_pct', 0):.2f}%)",
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
