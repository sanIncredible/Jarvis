#!/usr/bin/env python3
"""
⚡ JARVIS MULTI-BROKER MTF & EQUITY ORDER ENGINE
================================================
Supports dynamic order placement across multiple Indian brokers via Telegram:
1. Brokers Supported:
   - Upstox API v2 : MTF (Margin Trading Facility), Delivery (D), Intraday (I)
   - DhanHQ API v2 : MTF (Margin Trading Facility / Pay Later), Delivery (CNC), Intraday (INTRADAY)
   - Zerodha Kite  : Delivery (CNC), Intraday (MIS)

2. Sizing Modes:
   - Aggressive   : ₹1,50,000 (1.5L exposure)
   - Moderate     : ₹1,00,000 (1.0L exposure - Default)
   - Conservative : ₹50,000   (50K / 50% Risk exposure)
   - Custom Size  : e.g. 75k, 200000

3. Stop-Loss Calculation:
   - LOD (Low of Day): Uses intraday Low with slight structural buffer.
   - Regime-Guided   : Adjusts capital & SL based on market_regime.json.
"""

import os
import sys
import csv
import json
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config_credentials.json"
ORDERS_LOG_FILE = SCRIPT_DIR / "orders_log.json"
REGIME_FILE = SCRIPT_DIR / "market_regime.json"
POSITIONAL_REGIME_FILE = SCRIPT_DIR / "daily_positional_regime.json"
DHAN_CACHE_FILE = SCRIPT_DIR / "dhan_nse_cache.json"
DATA_FILE = SCRIPT_DIR / "data.json"
SERVER_IP = "80.225.210.222"

IST = timezone(timedelta(hours=5, minutes=30))


def round_to_tick(price, tick=0.05):
    """Rounds price strictly to a valid Indian exchange tick size multiple (default ₹0.05)."""
    if price is None:
        return 0.0
    try:
        p = float(price)
        return round(round(p / tick) * tick, 2)
    except Exception:
        return 0.0


def is_market_open():
    """Returns True if current time is within normal market hours (09:15 - 15:30 IST, Mon-Fri)."""
    now = get_ist_now()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

# Standard Sizing Presets
MODE_SIZES = {
    "agg": 150000,
    "aggressive": 150000,
    "1.5l": 150000,
    "150k": 150000,
    "mod": 100000,
    "moderate": 100000,
    "1l": 100000,
    "100k": 100000,
    "low": 50000,
    "conservative": 50000,
    "50k": 50000,
    "risk50": 50000,
    "0.5l": 50000,
}

SUPPORTED_BROKERS = ("upstox", "dhan", "zerodha")

# Common Trader Nicknames & Symbol Aliases (Auto-mapped to official NSE EQ symbols)
COMMON_SYMBOL_ALIASES = {
    "RIL": "RELIANCE",
    "RELIANCEIND": "RELIANCE",
    "SBI": "SBIN",
    "SBIBK": "SBIN",
    "HDFC": "HDFCBANK",
    "HDFCBK": "HDFCBANK",
    "KOTAK": "KOTAKBANK",
    "KOTAKBK": "KOTAKBANK",
    "ICICI": "ICICIBANK",
    "ICICIBK": "ICICIBANK",
    "AXIS": "AXISBANK",
    "AXISBK": "AXISBANK",
    "BHARTI": "BHARTIARTL",
    "AIRTEL": "BHARTIARTL",
    "INFOSYS": "INFY",
    "MM": "M&M",
    "TATAMOTOR": "TATAMOTORS",
    "BAJAJAUTO": "BAJAJ-AUTO",
    "LT": "LT",
    "L&T": "LT",
    "JAYNECOND": "JAYNECOIND",
    "DALTACORP": "DELTACORP",
    "SAMBHAV": "SAMBHV",
    "HBLPOWER": "HBLENGINE",
    "INDEGENE": "INDGN",
    "INDGEN": "INDGN",
    "JIO": "JIOFIN",
}


def resolve_symbol(symbol: str) -> str:
    """Normalizes symbol string and resolves trader nicknames / aliases to official NSE symbol."""
    if not symbol:
        return ""
    s_clean = symbol.strip().upper().replace("NSE:", "").replace(".NS", "")
    return COMMON_SYMBOL_ALIASES.get(s_clean, s_clean)


def get_ist_now():
    """Returns current datetime in IST."""
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def load_config():
    """Loads configuration credentials."""
    for c_path in [CONFIG_FILE, SCRIPT_DIR / "credentials.json"]:
        if c_path.is_file():
            try:
                with open(c_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def save_config(cfg):
    """Saves updated configuration safely."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def get_default_broker():
    """Gets default broker from config (defaults to upstox)."""
    cfg = load_config()
    b = cfg.get("default_broker", "").strip().lower()
    return b if b in SUPPORTED_BROKERS else "upstox"


def set_default_broker(broker_name):
    """Sets default broker in config."""
    b = broker_name.strip().lower()
    if b not in SUPPORTED_BROKERS:
        return False, f"Unsupported broker: {broker_name}. Choose from: {', '.join(SUPPORTED_BROKERS)}"
    cfg = load_config()
    cfg["default_broker"] = b
    if save_config(cfg):
        return True, b
    return False, "Failed to save configuration"


def load_market_regime():
    """Loads current market regime state."""
    for r_path in [REGIME_FILE, POSITIONAL_REGIME_FILE]:
        if r_path.is_file():
            try:
                with open(r_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def parse_size_mode(mode_arg):
    """
    Parses mode argument to exposure amount in INR.
    Supports 'agg', 'mod', 'low', '1.5L', '1L', '50k', '75k', or raw numbers.
    """
    if not mode_arg:
        return 100000, "Moderate (₹1.0L)"

    m_clean = str(mode_arg).strip().lower().replace("₹", "").replace(",", "")

    if m_clean in MODE_SIZES:
        amt = MODE_SIZES[m_clean]
        if amt >= 150000:
            return amt, f"Aggressive (₹{amt/100000:.1f}L)"
        elif amt >= 100000:
            return amt, f"Moderate (₹{amt/100000:.1f}L)"
        else:
            return amt, f"Conservative (₹{amt/1000:.0f}K)"

    if m_clean.endswith("k"):
        try:
            val = float(m_clean[:-1]) * 1000
            return int(val), f"Custom (₹{int(val):,})"
        except ValueError:
            pass
    elif m_clean.endswith("l"):
        try:
            val = float(m_clean[:-1]) * 100000
            return int(val), f"Custom (₹{int(val):,})"
        except ValueError:
            pass

    try:
        val = float(m_clean)
        return int(val), f"Custom (₹{int(val):,})"
    except ValueError:
        return 100000, "Moderate (₹1.0L - Default)"


def resolve_dhan_security_id(symbol):
    """Resolves symbol to Dhan securityId from local cache or Dhan scrip master."""
    sym_u = resolve_symbol(symbol).strip().upper()
    if DHAN_CACHE_FILE.is_file():
        try:
            with open(DHAN_CACHE_FILE, "r", encoding="utf-8") as f:
                c = json.load(f)
                if sym_u in c:
                    return c[sym_u]
        except Exception:
            pass

    # Download Dhan scrip master CSV if not cached
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            lines = resp.read().decode("utf-8").splitlines()
        reader = csv.DictReader(lines)
        c = {
            row["SEM_TRADING_SYMBOL"]: row["SEM_SMST_SECURITY_ID"]
            for row in reader
            if row.get("SEM_EXM_EXCH_ID") == "NSE" and row.get("SEM_SERIES") == "EQ"
        }
        with open(DHAN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(c, f)
        return c.get(sym_u)
    except Exception as e:
        print(f"Error resolving Dhan securityId: {e}")
        return None


def fetch_live_quote(symbol):
    """
    Fetches live quote for a symbol from Upstox API v2 with automatic fallback.
    Returns dict with ltp, day_low, day_high, prev_close, instrument_key.
    """
    symbol = resolve_symbol(symbol)
    try:
        from upstox_tablet_scanner import get_instrument_key
        instrument_key = get_instrument_key(symbol)
    except Exception:
        instrument_key = f"NSE_EQ|{symbol.upper()}"

    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()

    if token:
        encoded_key = urllib.parse.quote(instrument_key)
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded_key}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Jarvis-Order-Engine"
        })

        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                quote_map = data.get("data", {})
                first_q = next(iter(quote_map.values()), {}) if quote_map else {}

                ltp = first_q.get("last_price")
                ohlc = first_q.get("ohlc", {})
                day_low = ohlc.get("low")
                day_high = ohlc.get("high")
                day_open = ohlc.get("open")
                prev_close = ohlc.get("close") or first_q.get("prev_close")

                if ltp and ltp > 0:
                    return {
                        "symbol": symbol.upper(),
                        "instrument_key": instrument_key,
                        "ltp": float(ltp),
                        "day_low": float(day_low) if day_low else float(ltp * 0.985),
                        "day_high": float(day_high) if day_high else float(ltp),
                        "day_open": float(day_open) if day_open else float(ltp),
                        "prev_close": float(prev_close) if prev_close else float(ltp),
                        "timestamp": first_q.get("timestamp"),
                        "source": "Upstox Live Quote"
                    }, None
        except Exception:
            pass

    # Fallback 1: data.json scanner cache
    sc_data = get_symbol_scanner_data(symbol)
    if sc_data and sc_data.get("ltp"):
        return {
            "symbol": symbol.upper(),
            "instrument_key": instrument_key,
            "ltp": float(sc_data["ltp"]),
            "day_low": float(sc_data.get("day_low") or sc_data["ltp"] * 0.985),
            "day_high": float(sc_data.get("day_high") or sc_data["ltp"]),
            "day_open": float(sc_data.get("day_open") or sc_data["ltp"]),
            "prev_close": float(sc_data.get("prev_close") or sc_data["ltp"]),
            "source": "Scanner Cache (data.json)"
        }, None

    # Fallback 2: Yahoo Finance API
    try:
        clean_s = symbol.upper().replace(".NS", "").replace("NSE:", "")
        yf_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_s}.NS?interval=1d&range=1d"
        req_yf = urllib.request.Request(yf_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req_yf, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            meta = data["chart"]["result"][0]["meta"]
            ltp = meta.get("regularMarketPrice")
            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
            day_high = meta.get("regularMarketDayHigh") or ltp
            day_low = meta.get("regularMarketDayLow") or (ltp * 0.985 if ltp else 0)

            if ltp and ltp > 0:
                return {
                    "symbol": symbol.upper(),
                    "instrument_key": instrument_key,
                    "ltp": float(ltp),
                    "day_low": float(day_low) if day_low else float(ltp * 0.985),
                    "day_high": float(day_high) if day_high else float(ltp),
                    "day_open": float(ltp),
                    "prev_close": float(prev_close) if prev_close else float(ltp),
                    "source": "Yahoo Finance (Market Feed)"
                }, None
    except Exception as ex:
        return None, f"Quote fetch failed across all sources: {ex}"

    return None, f"Could not retrieve quote for {symbol}"


def get_symbol_scanner_data(symbol):
    """Retrieves 3m ORB, SS, PDH, and RVOL metrics from data.json if available."""
    if DATA_FILE.is_file():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            for s in d.get("stocks", []):
                if s.get("symbol", "").upper() == symbol.upper():
                    return s
        except Exception:
            pass
    return None


def evaluate_strategy_checklist(symbol, quote_data=None, calc_data=None):
    """
    Evaluates 7 core strategy rules:
    1. Regime Health (Macro & Bonde Breadth)
    2. Dynamic ORB High Breakout (LTP > ORB High)
    3. Previous Day High (PDH) Cleared
    4. Strong Start (SS) Signature
    5. Relative Volume (RVOL) Participation
    6. Stop-Loss / LOD Risk Proximity (<= 4.0% risk)
    7. 10 EMA Extension / Stretch (< 3.5%)
    """
    sc_data = get_symbol_scanner_data(symbol)
    regime = load_market_regime()
    state_code = str(regime.get("state_code") or regime.get("regime_code") or "NORMAL").upper()
    state_label = regime.get("state_label") or regime.get("regime_badge") or state_code
    alloc_pct = regime.get("swing_allocation_pct", 100)

    ltp = (calc_data or {}).get("ltp") or (quote_data or {}).get("ltp") or (sc_data or {}).get("ltp", 0)
    day_low = (calc_data or {}).get("day_low") or (quote_data or {}).get("day_low") or (sc_data or {}).get("day_low", 0)
    risk_pct = (calc_data or {}).get("risk_pct")
    if risk_pct is None and ltp and day_low:
        risk_pct = round(((ltp - day_low) / ltp) * 100, 2)

    checklist = []
    warnings = []

    # 1. Regime Permission
    is_defensive = state_code in ("DEFENSIVE", "DEFENSIVE_WATERFALL", "CLIMAX", "WASHOUT", "CHOP") or alloc_pct == 0
    if is_defensive:
        checklist.append({
            "rule": "Market Regime",
            "passed": False,
            "badge": "⚠️",
            "text": f"⚠️ <b>Regime:</b> {state_code} (Caution: Defensive Breadth)",
            "detail": "80%+ of breakouts fail in this regime. Capital preservation active."
        })
        warnings.append(f"Regime Warning: Market state is {state_code} (0% swing allocation). High breakout failure risk.")
    else:
        checklist.append({
            "rule": "Market Regime",
            "passed": True,
            "badge": "✅",
            "text": f"✅ <b>Regime:</b> {state_code} (Supportive)",
            "detail": "Market breadth is supportive of long setups."
        })

    # 2. Dynamic ORB Breakout
    orb_status = sc_data.get("orb_status") if sc_data else None
    orb_high = sc_data.get("orb_high") if sc_data else None
    if sc_data and orb_status:
        if orb_status in ("H", "L➔H") or (orb_high and ltp > orb_high):
            lbl = "Above ORB High" if orb_status == "H" else "Reversal L➔H Breakout"
            checklist.append({
                "rule": "ORB Breakout",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>ORB:</b> {lbl} (₹{orb_high:.1f})" if orb_high else f"✅ <b>ORB:</b> {lbl}",
                "detail": "Trading above Opening Range High"
            })
        else:
            checklist.append({
                "rule": "ORB Breakout",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>ORB:</b> Below ORB-H (₹{orb_high:.1f})" if orb_high else f"⚠️ <b>ORB:</b> In Range ({orb_status})",
                "detail": "Price has not broken above Opening Range High"
            })
            warnings.append(f"ORB Setup: Stock has not broken above Opening Range High (ORB: {orb_status}).")
    else:
        day_high = (quote_data or {}).get("day_high", ltp)
        if ltp and day_high and ltp >= day_high * 0.992:
            checklist.append({
                "rule": "Day High",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Day High:</b> Trading near High of Day (₹{day_high:.1f})",
                "detail": "Trading near daily high"
            })
        else:
            checklist.append({
                "rule": "Day High",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Day High:</b> Below Day High (₹{day_high:.1f})",
                "detail": "Not trading near daily high"
            })
            warnings.append(f"Day High: Not trading near high of day (Day High: ₹{day_high:.1f}).")

    # 3. Previous Day High (PDH) Cleared
    pdh = sc_data.get("pdh") if sc_data else None
    pdh_broken = sc_data.get("pdh_broken") if sc_data else False
    if sc_data and pdh:
        if pdh_broken or (ltp and ltp > pdh):
            checklist.append({
                "rule": "PDH Cleared",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>PDH:</b> Cleared Prev Day High (₹{pdh:.1f})",
                "detail": "Overhead daily resistance taken out"
            })
        else:
            dist = round(((pdh - ltp) / ltp) * 100, 1) if ltp else 0
            checklist.append({
                "rule": "PDH Cleared",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>PDH:</b> Below Prev Day High (₹{pdh:.1f} | -{dist}%)",
                "detail": "Overhead daily resistance ahead"
            })
            warnings.append(f"PDH Resistance: Below Previous Day High (₹{pdh:.1f}, -{dist}% away).")
    elif quote_data and quote_data.get("prev_close"):
        pc = quote_data["prev_close"]
        if ltp > pc:
            cg = round(((ltp - pc) / pc) * 100, 1)
            checklist.append({
                "rule": "Day Trend",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Day Trend:</b> Above Prev Close (+{cg}%)",
                "detail": "Positive daily momentum"
            })
        else:
            cg = round(((ltp - pc) / pc) * 100, 1)
            checklist.append({
                "rule": "Day Trend",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Day Trend:</b> Below Prev Close ({cg}%)",
                "detail": "Negative daily momentum"
            })
            warnings.append(f"Day Trend: Stock is trading below yesterday's close ({cg}%).")

    # 4. Strong Start (SS) Signature
    is_ss = sc_data.get("is_ss") if sc_data else None
    if is_ss is None and quote_data:
        o = quote_data.get("day_open", ltp)
        l = quote_data.get("day_low", ltp)
        pc = quote_data.get("prev_close", ltp)
        is_ss = (o > pc) and (l >= pc * 0.995)
    if is_ss:
        checklist.append({
            "rule": "Strong Start",
            "passed": True,
            "badge": "✅",
            "text": "✅ <b>Strong Start:</b> Confirmed (Held above Prev Close)",
            "detail": "Pine Script SS criteria satisfied"
        })
    else:
        checklist.append({
            "rule": "Strong Start",
            "passed": False,
            "badge": "⚠️",
            "text": "⚠️ <b>Strong Start:</b> Not Qualified",
            "detail": "Opened below PC or breached low buffer"
        })
        warnings.append("Strong Start: Did not qualify as Strong Start today (opened weak or broke low buffer).")

    # 5. Relative Volume (RVOL) Participation
    rvol = sc_data.get("rvol") if sc_data else None
    if rvol is not None:
        if rvol >= 1.0:
            checklist.append({
                "rule": "Volume Surge",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Volume:</b> RVOL {rvol:.2f}x (Institutional Surge)",
                "detail": "Volume exceeding 20-day baseline"
            })
        elif rvol >= 0.75:
            checklist.append({
                "rule": "Volume Surge",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Volume:</b> RVOL {rvol:.2f}x (Moderate Volume)",
                "detail": "Volume near daily baseline"
            })
        else:
            checklist.append({
                "rule": "Volume Surge",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Volume:</b> RVOL {rvol:.2f}x (Low Participation)",
                "detail": "Volume below institutional participation threshold"
            })
            warnings.append(f"Volume: Low relative volume (RVOL {rvol:.2f}x under 1.0x baseline).")

    # 6. Stop-Loss / LOD Risk Proximity
    if risk_pct is not None:
        if risk_pct <= 3.0:
            checklist.append({
                "rule": "Stop Distance",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Stop Distance:</b> {risk_pct:.1f}% (Tight Risk under 3%)",
                "detail": "Clean structural risk to Day Low"
            })
        elif risk_pct <= 4.0:
            checklist.append({
                "rule": "Stop Distance",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Stop Distance:</b> {risk_pct:.1f}% (Acceptable within 4%)",
                "detail": "Reasonable distance to Day Low"
            })
        else:
            checklist.append({
                "rule": "Stop Distance",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Stop Distance:</b> {risk_pct:.1f}% (WIDE over 4.0% limit)",
                "detail": "Excessive distance to LOD stop-loss"
            })
            warnings.append(f"Wide Stop-Loss: Distance to Day Low is {risk_pct:.1f}% (over 4.0% optimal threshold). High drawdown risk.")

    # 7. 10 EMA Stretch / Overextension
    stretch_pct = sc_data.get("stretch_pct") if sc_data else None
    if stretch_pct is not None:
        sign = "+" if stretch_pct >= 0 else ""
        if stretch_pct <= 3.0:
            checklist.append({
                "rule": "10 EMA Stretch",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Healthy Entry)",
                "detail": "Healthy entry near 10 EMA"
            })
        elif stretch_pct <= 4.5:
            checklist.append({
                "rule": "10 EMA Stretch",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Moderate)",
                "detail": "Moderately extended from 10 EMA"
            })
        else:
            checklist.append({
                "rule": "10 EMA Stretch",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Extended over 4.5%)",
                "detail": "Price extended from short term moving average"
            })
            warnings.append(f"Overextended: Price is stretched {sign}{stretch_pct:.1f}% above 10 EMA. Consider waiting for pullback.")

    passed_count = sum(1 for c in checklist if c.get("passed"))
    total_count = len(checklist)

    return {
        "checklist": checklist,
        "warnings": warnings,
        "passed_count": passed_count,
        "total_count": total_count,
        "is_all_passed": len(warnings) == 0,
        "scanner_signal": sc_data.get("signal") if sc_data else None
    }


def calculate_order_sizing(quote_data, mode_arg="mod", sl_mode="lod"):
    """
    Calculates quantity, stop loss, exposure, risk parameters, and strategy checklist.
    """
    symbol = quote_data["symbol"]
    ltp = quote_data["ltp"]
    day_low = quote_data["day_low"]

    base_size, mode_label = parse_size_mode(mode_arg)
    regime = load_market_regime()
    regime_code = regime.get("state_code") or regime.get("regime_code", "NORMAL")
    regime_label = regime.get("state_label") or regime.get("regime_badge", "NORMAL")
    alloc_pct = regime.get("swing_allocation_pct", 100)

    effective_size = base_size
    regime_note = ""

    if sl_mode.lower() in ("regime", "reg"):
        cfg = load_config()
        multipliers = cfg.get("risk_parameters", {}).get("swing", {}).get("regime_multipliers", {})
        mult = multipliers.get(regime_code, 1.0)
        effective_size = int(base_size * mult)
        if mult < 1.0:
            regime_note = f"⚠️ Regime Multiplier ({mult}x applied due to {regime_code})"
        if effective_size < 25000:
            effective_size = 25000

    # P2.1 Defensive Regime Auto-Cap: strictly limit exposure to ₹50k max during defensive/cash breadth regimes
    is_defensive = str(regime_code).upper() in ("DEFENSIVE", "DEFENSIVE_WATERFALL", "CLIMAX", "WASHOUT", "CHOP") or alloc_pct == 0
    if is_defensive:
        if effective_size > 50000:
            effective_size = 50000
            mode_label = f"{mode_label} [DEFENSIVE CAP: ₹50k]"
            cap_msg = f"🛡️ Defensive Regime ({regime_code}): Exposure capped to ₹50,000 max (Capital Preservation)"
            regime_note = f"{regime_note} | {cap_msg}" if regime_note else cap_msg

    quantity = int(effective_size / ltp)
    if quantity == 0 and effective_size >= ltp:
        quantity = 1

    actual_exposure = round(quantity * ltp, 2)

    buffer = max(0.10, round(day_low * 0.0005, 2))
    sl_price = round(day_low - buffer, 2)

    if sl_price >= ltp:
        sl_price = round(ltp * 0.985, 2)

    risk_per_share = round(ltp - sl_price, 2)
    risk_pct = round((risk_per_share / ltp) * 100, 2)

    if risk_pct > 4.0 and sl_mode.lower() in ("regime", "reg"):
        sl_price = round(ltp * 0.975, 2)
        risk_per_share = round(ltp - sl_price, 2)
        risk_pct = round((risk_per_share / ltp) * 100, 2)
        regime_note += " (SL capped at 2.5% to protect capital)"

    total_risk_inr = round(risk_per_share * quantity, 2)

    checklist_eval = evaluate_strategy_checklist(symbol, quote_data=quote_data, calc_data={
        "ltp": ltp,
        "day_low": day_low,
        "risk_pct": risk_pct
    })

    return {
        "symbol": symbol,
        "instrument_key": quote_data["instrument_key"],
        "ltp": ltp,
        "quantity": quantity,
        "mode_label": mode_label,
        "target_size": base_size,
        "actual_exposure": actual_exposure,
        "stop_loss": sl_price,
        "day_low": day_low,
        "risk_per_share": risk_per_share,
        "risk_pct": risk_pct,
        "total_risk_inr": total_risk_inr,
        "regime_code": regime_code,
        "regime_label": regime_label,
        "regime_note": regime_note,
        "sl_mode": sl_mode.upper(),
        "checklist": checklist_eval
    }


# ---------------------------------------------------------
# Broker Placement Adapters
# ---------------------------------------------------------
def place_upstox_mtf_order(instrument_key, quantity, order_type="MARKET", price=0.0):
    """Submits MTF Order directly to Upstox API v2."""
    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()
    if not token:
        return False, "Upstox access token missing in config_credentials.json"

    url = "https://api.upstox.com/v2/order/place"
    market_open = is_market_open()
    payload = {
        "quantity": int(quantity),
        "product": "MTF",
        "validity": "DAY",
        "price": float(price) if order_type.upper() == "LIMIT" else 0.0,
        "tag": "JARVIS_MTF",
        "instrument_token": instrument_key,
        "order_type": order_type.upper(),
        "transaction_type": "BUY",
        "disclosed_quantity": 0,
        "trigger_price": 0.0,
        "is_amo": not market_open
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                order_id = data.get("data", {}).get("order_id", "N/A")
                return True, order_id
            else:
                errors = data.get("errors", [])
                err_msg = errors[0].get("message") if errors else (data.get("message") or "Order placement failed")
                return False, err_msg
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            errors = err_json.get("errors", [])
            err_msg = errors[0].get("message") if errors else (err_json.get("message") or f"HTTP {he.code}: {he.reason}")
            return False, err_msg
        except Exception:
            return False, f"Upstox HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Order error: {str(e)}"


def place_dhan_mtf_order(symbol, quantity, order_type="MARKET", price=0.0):
    """Submits MTF Order directly to DhanHQ API v2."""
    cfg = load_config()
    dhan = cfg.get("dhan", {})
    client_id = dhan.get("client_id", "").strip()
    token = dhan.get("access_token", "").strip()

    if not client_id or not token:
        return False, "Dhan client_id or access_token missing in config_credentials.json"

    sec_id = resolve_dhan_security_id(symbol)
    if not sec_id:
        return False, f"Could not map securityId for {symbol} in Dhan instrument master"

    market_open = is_market_open()
    url = "https://api.dhan.co/v2/orders"
    payload = {
        "dhanClientId": client_id,
        "transactionType": "BUY",
        "exchangeSegment": "NSE_EQ",
        "productType": "MTF",
        "orderType": order_type.upper(),
        "validity": "DAY",
        "securityId": str(sec_id),
        "quantity": int(quantity),
        "price": float(price) if order_type.upper() == "LIMIT" else 0.0,
        "triggerPrice": 0.0,
        "afterMarketOrder": not market_open
    }
    if not market_open:
        payload["amoTime"] = "OPEN"

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            order_id = data.get("orderId")
            order_status = data.get("orderStatus", "SUBMITTED")
            if order_id:
                return True, f"{order_id} ({order_status})"
            err_msg = data.get("errorMessage") or data.get("message") or data.get("remarks") or "Order placement failed"
            return False, err_msg
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            err_msg = (
                err_json.get("errorMessage")
                or err_json.get("message")
                or err_json.get("remarks")
                or f"HTTP {he.code}: {he.reason}"
            )
            err_code = err_json.get("errorCode", "")
            if "Invalid IP" in err_msg or err_code == "DH-905":
                err_msg = (
                    f"DH-905 (Invalid IP): Dhan access token was generated before static IP ({SERVER_IP}) was registered. "
                    "Please generate a fresh token at web.dhan.co and paste it into Telegram (/dhan <TOKEN>)."
                )
            return False, err_msg
        except Exception:
            return False, f"Dhan HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Dhan error: {str(e)}"


def place_zerodha_order(symbol, quantity, order_type="MARKET", product="CNC", price=0.0):
    """Submits Order directly to Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    api_key = kite.get("api_key", "").strip()
    token = kite.get("access_token", "").strip()

    if not api_key or not token:
        return False, "Zerodha api_key or access_token missing in config_credentials.json"

    url = "https://api.kite.trade/orders/regular"
    payload = {
        "tradingsymbol": symbol.upper(),
        "exchange": "NSE",
        "transaction_type": "BUY",
        "order_type": order_type.upper(),
        "quantity": int(quantity),
        "product": product.upper(),
        "validity": "DAY",
        "price": float(price) if order_type.upper() == "LIMIT" else 0.0,
        "tag": "JARVIS"
    }

    req_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Jarvis-Order-Engine"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                order_id = data.get("data", {}).get("order_id", "N/A")
                return True, order_id
            return False, data.get("message", "Order placement failed")
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            return False, err_json.get("message", f"HTTP {he.code}: {he.reason}")
        except Exception:
            return False, f"Zerodha HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Zerodha error: {str(e)}"


def log_executed_order(order_record):
    """Logs order record to orders_log.json for trade journal persistence."""
    orders = []
    if ORDERS_LOG_FILE.is_file():
        try:
            with open(ORDERS_LOG_FILE, "r", encoding="utf-8") as f:
                orders = json.load(f)
        except Exception:
            orders = []

    orders.append(order_record)

    try:
        with open(ORDERS_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f, indent=2)
    except Exception as e:
        print(f"Error logging order: {e}")


def place_upstox_stop_loss_order(instrument_key, quantity, sl_price, product="MTF", transaction_type="SELL"):
    """Submits a hard Stop-Loss Limit order (SELL for long, BUY for short) directly to Upstox API v2."""
    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()
    if not token:
        return False, "Upstox access token missing in config_credentials.json"

    url = "https://api.upstox.com/v2/order/place"
    market_open = is_market_open()
    trigger_p = round_to_tick(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        # 0.2% limit buffer below trigger strictly rounded to 0.05 tick size
        limit_price = round_to_tick(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = round_to_tick(trigger_p - 0.05)
    else:
        # BUY SL (for short positions): limit buffer above trigger
        limit_price = round_to_tick(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = round_to_tick(trigger_p + 0.05)

    payload = {
        "quantity": int(quantity),
        "product": product.upper(),
        "validity": "DAY",
        "price": float(limit_price),
        "tag": "JARVIS_SL",
        "instrument_token": instrument_key,
        "order_type": "SL",
        "transaction_type": tt,
        "disclosed_quantity": 0,
        "trigger_price": float(trigger_p),
        "is_amo": not market_open
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                oid = data.get("data", {}).get("order_id", "N/A")
                return True, oid
            errors = data.get("errors", [])
            err_msg = errors[0].get("message") if errors else (data.get("message") or "Upstox SL placement failed")
            return False, err_msg
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            errors = err_json.get("errors", [])
            err_msg = errors[0].get("message") if errors else (err_json.get("message") or f"HTTP {he.code}")
            return False, err_msg
        except Exception:
            return False, f"Upstox HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Upstox SL error: {str(e)}"


def place_dhan_stop_loss_order(symbol, quantity, sl_price, product="MTF", transaction_type="SELL"):
    """Submits a hard Stop-Loss Limit order directly to DhanHQ API v2."""
    cfg = load_config()
    dhan = cfg.get("dhan", {})
    client_id = dhan.get("client_id", "").strip()
    token = dhan.get("access_token", "").strip()
    if not client_id or not token:
        return False, "Dhan credentials missing in config_credentials.json"

    sec_id = resolve_dhan_security_id(symbol)
    if not sec_id:
        return False, f"Could not map securityId for {symbol} on Dhan"

    market_open = is_market_open()
    trigger_p = round_to_tick(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_price = round_to_tick(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = round_to_tick(trigger_p - 0.05)
    else:
        limit_price = round_to_tick(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = round_to_tick(trigger_p + 0.05)

    url = "https://api.dhan.co/v2/orders"
    payload = {
        "dhanClientId": client_id,
        "transactionType": tt,
        "exchangeSegment": "NSE_EQ",
        "productType": product.upper(),
        "orderType": "STOP_LOSS",
        "validity": "DAY",
        "securityId": str(sec_id),
        "quantity": int(quantity),
        "price": float(limit_price),
        "triggerPrice": float(trigger_p),
        "afterMarketOrder": not market_open
    }
    if not market_open:
        payload["amoTime"] = "OPEN"

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            order_id = data.get("orderId")
            if order_id:
                return True, str(order_id)
            err_msg = data.get("errorMessage") or data.get("message") or "Dhan SL placement failed"
            return False, err_msg
    except Exception as e:
        return False, f"Dhan SL error: {str(e)}"


def place_zerodha_stop_loss_order(symbol, quantity, sl_price, product="CNC", transaction_type="SELL"):
    """Submits a hard Stop-Loss Limit order directly to Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    api_key = kite.get("api_key", "").strip()
    token = kite.get("access_token", "").strip()
    if not api_key or not token:
        return False, "Zerodha credentials missing in config_credentials.json"

    trigger_p = round_to_tick(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_price = round_to_tick(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = round_to_tick(trigger_p - 0.05)
    else:
        limit_price = round_to_tick(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = round_to_tick(trigger_p + 0.05)

    url = "https://api.kite.trade/orders/regular"
    payload = {
        "tradingsymbol": symbol.upper(),
        "exchange": "NSE",
        "transaction_type": tt,
        "order_type": "SL",
        "quantity": int(quantity),
        "product": product.upper(),
        "validity": "DAY",
        "price": float(limit_price),
        "trigger_price": float(trigger_p),
        "tag": "JARVIS_SL"
    }
    req_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                return True, data.get("data", {}).get("order_id", "N/A")
            return False, data.get("message", "Zerodha SL placement failed")
    except Exception as e:
        return False, f"Zerodha SL error: {str(e)}"


def place_broker_stop_loss(broker, symbol, quantity, sl_price, instrument_key=None, product="MTF", transaction_type="SELL"):
    """Dispatches hard Stop-Loss Limit order (SELL for long, BUY for short) to designated broker."""
    b = (broker or "").strip().lower()
    if b == "upstox":
        inst_key = instrument_key or resolve_instrument_key(symbol)
        if not inst_key:
            return False, f"Could not resolve instrument key for {symbol}"
        return place_upstox_stop_loss_order(inst_key, quantity, sl_price, product=product, transaction_type=transaction_type)
    elif b == "dhan":
        return place_dhan_stop_loss_order(symbol, quantity, sl_price, product=product, transaction_type=transaction_type)
    elif b == "zerodha":
        return place_zerodha_stop_loss_order(symbol, quantity, sl_price, product="CNC", transaction_type=transaction_type)
    return False, f"Unsupported broker for Stop-Loss: {broker}"


# ---------------------------------------------------------
# Atomic Order Modification & Pending Order Queries (P1)
# ---------------------------------------------------------
def modify_upstox_stop_loss_order(order_id, quantity, trigger_price, limit_price):
    """Atomically modifies an existing pending Stop-Loss order on Upstox API v2."""
    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()
    if not token:
        return False, "Upstox access token missing"

    url = "https://api.upstox.com/v2/order/modify"
    payload = {
        "order_id": str(order_id),
        "quantity": int(quantity),
        "validity": "DAY",
        "price": float(limit_price),
        "order_type": "SL",
        "disclosed_quantity": 0,
        "trigger_price": float(trigger_price)
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="PUT", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                oid = data.get("data", {}).get("order_id", order_id)
                return True, oid
            errors = data.get("errors", [])
            err_msg = errors[0].get("message") if errors else (data.get("message") or "Upstox SL modification failed")
            return False, err_msg
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            errors = err_json.get("errors", [])
            err_msg = errors[0].get("message") if errors else (err_json.get("message") or f"HTTP {he.code}")
            return False, err_msg
        except Exception:
            return False, f"Upstox HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Upstox modify SL error: {str(e)}"


def modify_dhan_stop_loss_order(order_id, quantity, trigger_price, limit_price):
    """Atomically modifies an existing pending Stop-Loss order on DhanHQ API v2."""
    cfg = load_config()
    dhan = cfg.get("dhan", {})
    client_id = dhan.get("client_id", "").strip()
    token = dhan.get("access_token", "").strip()
    if not client_id or not token:
        return False, "Dhan credentials missing"

    url = f"https://api.dhan.co/v2/orders/{order_id}"
    payload = {
        "orderId": str(order_id),
        "orderType": "STOP_LOSS",
        "legName": "ENTRY_LEG",
        "quantity": int(quantity),
        "price": float(limit_price),
        "triggerPrice": float(trigger_price),
        "disclosedQuantity": 0,
        "validity": "DAY"
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="PUT", headers={
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            ret_oid = data.get("orderId") or order_id
            if ret_oid and data.get("orderStatus") in ("TRANSIT", "PENDING", None):
                return True, str(ret_oid)
            err_msg = data.get("errorMessage") or data.get("remarks") or data.get("message") or "Dhan SL modify failed"
            return False, err_msg
    except Exception as e:
        return False, f"Dhan modify SL error: {str(e)}"


def modify_zerodha_stop_loss_order(order_id, quantity, trigger_price, limit_price):
    """Atomically modifies an existing pending Stop-Loss order on Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    api_key = kite.get("api_key", "").strip()
    token = kite.get("access_token", "").strip()
    if not api_key or not token:
        return False, "Zerodha credentials missing"

    url = f"https://api.kite.trade/orders/regular/{order_id}"
    payload = {
        "order_id": str(order_id),
        "quantity": int(quantity),
        "price": float(limit_price),
        "trigger_price": float(trigger_price),
        "order_type": "SL",
        "validity": "DAY"
    }
    req_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="PUT", headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                ret_oid = data.get("data", {}).get("order_id", order_id)
                return True, ret_oid
            return False, data.get("message", "Zerodha SL modify failed")
    except Exception as e:
        return False, f"Zerodha modify SL error: {str(e)}"


def modify_broker_stop_loss(broker, order_id, quantity, new_sl_price, transaction_type="SELL"):
    """Atomically modifies a pending Stop-Loss order on designated broker."""
    b = (broker or "").strip().lower()
    trigger_p = round_to_tick(new_sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_price = round_to_tick(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = round_to_tick(trigger_p - 0.05)
    else:
        limit_price = round_to_tick(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = round_to_tick(trigger_p + 0.05)

    if b == "upstox":
        return modify_upstox_stop_loss_order(order_id, quantity, trigger_p, limit_price)
    elif b == "dhan":
        return modify_dhan_stop_loss_order(order_id, quantity, trigger_p, limit_price)
    elif b == "zerodha":
        return modify_zerodha_stop_loss_order(order_id, quantity, trigger_p, limit_price)
    return False, f"Unsupported broker for modify SL: {broker}"



# ---------------------------------------------------------
# Good-Till-Triggered (GTT / Forever Orders) Engine
# Permanent 1-Year Stop-Loss Protection (Zero Daily Expiry)
# ---------------------------------------------------------
def place_zerodha_gtt_stop_loss(symbol, quantity, sl_price, exchange="NSE", product="CNC", transaction_type="SELL"):
    """Submits a permanent 1-year GTT Stop-Loss trigger directly to Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    ak = kite.get("api_key", "").strip()
    tok = kite.get("access_token", "").strip()
    if not (ak and tok):
        return False, "Zerodha credentials missing in config_credentials.json"

    sym_u = (symbol or "").strip().upper()
    trigger_p = round_to_tick(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_p = round_to_tick(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = round_to_tick(trigger_p - 0.05)
    else:
        limit_p = round_to_tick(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = round_to_tick(trigger_p + 0.05)

    q, _ = fetch_live_quote(sym_u)
    ltp = float(q.get("ltp", 0) or trigger_p) if q else trigger_p

    condition = {
        "exchange": exchange.upper(),
        "tradingsymbol": sym_u,
        "trigger_values": [float(trigger_p)],
        "last_price": float(ltp)
    }
    orders = [{
        "exchange": exchange.upper(),
        "tradingsymbol": sym_u,
        "transaction_type": tt,
        "quantity": int(quantity),
        "order_type": "LIMIT",
        "product": product.upper(),
        "price": float(limit_p)
    }]

    payload = {
        "type": "single",
        "condition": json.dumps(condition),
        "orders": json.dumps(orders)
    }

    req_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request("https://api.kite.trade/gtt/triggers", data=req_data, method="POST", headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {ak}:{tok}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                trig_id = str(data.get("data", {}).get("trigger_id", "N/A"))
                return True, trig_id
            return False, data.get("message", "Zerodha GTT placement failed")
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            return False, err_json.get("message", f"HTTP {he.code}")
        except Exception:
            return False, f"Zerodha HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Zerodha GTT error: {str(e)}"


def modify_zerodha_gtt_stop_loss(trigger_id, symbol, quantity, new_sl_price, exchange="NSE", product="CNC", transaction_type="SELL"):
    """Atomically modifies an existing GTT Stop-Loss trigger on Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    ak = kite.get("api_key", "").strip()
    tok = kite.get("access_token", "").strip()
    if not (ak and tok):
        return False, "Zerodha credentials missing"

    sym_u = (symbol or "").strip().upper()
    trigger_p = round_to_tick(new_sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_p = round_to_tick(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = round_to_tick(trigger_p - 0.05)
    else:
        limit_p = round_to_tick(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = round_to_tick(trigger_p + 0.05)

    q, _ = fetch_live_quote(sym_u)
    ltp = float(q.get("ltp", 0) or trigger_p) if q else trigger_p

    condition = {
        "exchange": exchange.upper(),
        "tradingsymbol": sym_u,
        "trigger_values": [float(trigger_p)],
        "last_price": float(ltp)
    }
    orders = [{
        "exchange": exchange.upper(),
        "tradingsymbol": sym_u,
        "transaction_type": tt,
        "quantity": int(quantity),
        "order_type": "LIMIT",
        "product": product.upper(),
        "price": float(limit_p)
    }]

    payload = {
        "type": "single",
        "condition": json.dumps(condition),
        "orders": json.dumps(orders)
    }

    req_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(f"https://api.kite.trade/gtt/triggers/{trigger_id}", data=req_data, method="PUT", headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {ak}:{tok}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                ret_id = str(data.get("data", {}).get("trigger_id", trigger_id))
                return True, ret_id
            return False, data.get("message", "Zerodha GTT modify failed")
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            return False, err_json.get("message", f"HTTP {he.code}")
        except Exception:
            return False, f"Zerodha HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Zerodha GTT modify error: {str(e)}"


def cancel_zerodha_gtt_order(trigger_id):
    """Cancels an active GTT trigger on Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    ak = kite.get("api_key", "").strip()
    tok = kite.get("access_token", "").strip()
    if not (ak and tok):
        return False, "Zerodha credentials missing"

    req = urllib.request.Request(f"https://api.kite.trade/gtt/triggers/{trigger_id}", method="DELETE", headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {ak}:{tok}",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return (data.get("status") == "success"), str(trigger_id)
    except Exception as e:
        return False, str(e)


def place_dhan_forever_stop_loss(symbol, quantity, sl_price, product="MTF", transaction_type="SELL"):
    """Submits a permanent 1-year Forever Order (GTT) Stop-Loss directly to DhanHQ API v2."""
    cfg = load_config()
    dhan = cfg.get("dhan", {})
    cid = dhan.get("client_id", "").strip()
    tok = dhan.get("access_token", "").strip()
    if not (cid and tok):
        return False, "Dhan credentials missing in config_credentials.json"

    sym_u = (symbol or "").strip().upper()
    sec_id = resolve_dhan_security_id(sym_u)
    if not sec_id:
        return False, f"Could not map securityId for {sym_u} on Dhan"

    trigger_p = round_to_tick(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_p = round_to_tick(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = round_to_tick(trigger_p - 0.05)
    else:
        limit_p = round_to_tick(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = round_to_tick(trigger_p + 0.05)

    payload = {
        "dhanClientId": cid,
        "orderFlag": "SINGLE",
        "transactionType": tt,
        "exchangeSegment": "NSE_EQ",
        "productType": product.upper(),
        "orderType": "LIMIT",
        "validity": "DAY",
        "securityId": str(sec_id),
        "quantity": int(quantity),
        "price": float(limit_p),
        "triggerPrice": float(trigger_p)
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("https://api.dhan.co/v2/forever/orders", data=req_data, method="POST", headers={
        "access-token": tok,
        "client-id": cid,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            oid = data.get("orderId")
            if oid and data.get("orderStatus") in ("PENDING", "TRANSIT", "CONFIRMED", "ACTIVE"):
                return True, str(oid)
            err = data.get("errorMessage") or data.get("message") or "Dhan Forever Order failed"
            return False, err
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            return False, err_json.get("errorMessage") or err_json.get("message") or f"HTTP {he.code}"
        except Exception:
            return False, f"Dhan HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Dhan Forever order error: {str(e)}"


def modify_dhan_forever_stop_loss(order_id, quantity, new_sl_price, transaction_type="SELL"):
    """Atomically modifies an existing Forever Order (GTT) on DhanHQ API v2."""
    cfg = load_config()
    dhan = cfg.get("dhan", {})
    cid = dhan.get("client_id", "").strip()
    tok = dhan.get("access_token", "").strip()
    if not (cid and tok):
        return False, "Dhan credentials missing"

    trigger_p = round_to_tick(new_sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_p = round_to_tick(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = round_to_tick(trigger_p - 0.05)
    else:
        limit_p = round_to_tick(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = round_to_tick(trigger_p + 0.05)

    payload = {
        "dhanClientId": cid,
        "orderId": str(order_id),
        "orderFlag": "SINGLE",
        "legName": "STOP_LOSS_LEG",
        "orderType": "LIMIT",
        "transactionType": tt,
        "quantity": int(quantity),
        "price": float(limit_p),
        "triggerPrice": float(trigger_p),
        "disclosedQuantity": 0,
        "validity": "DAY"
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"https://api.dhan.co/v2/forever/orders/{order_id}", data=req_data, method="PUT", headers={
        "access-token": tok,
        "client-id": cid,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            oid = data.get("orderId") or order_id
            if oid and data.get("orderStatus") in ("PENDING", "TRANSIT", "CONFIRMED", "ACTIVE", None):
                return True, str(oid)
            err = data.get("errorMessage") or data.get("message") or "Dhan Forever modify failed"
            return False, err
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            return False, err_json.get("errorMessage") or err_json.get("message") or f"HTTP {he.code}"
        except Exception:
            return False, f"Dhan HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Dhan Forever modify error: {str(e)}"


def cancel_dhan_forever_order(order_id):
    """Cancels an active Forever Order (GTT) on DhanHQ API v2."""
    cfg = load_config()
    dhan = cfg.get("dhan", {})
    cid = dhan.get("client_id", "").strip()
    tok = dhan.get("access_token", "").strip()
    if not (cid and tok):
        return False, "Dhan credentials missing"

    req = urllib.request.Request(f"https://api.dhan.co/v2/forever/orders/{order_id}", method="DELETE", headers={
        "access-token": tok,
        "client-id": cid,
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return True, str(order_id)
    except Exception as e:
        return False, str(e)


def place_upstox_gtt_stop_loss(instrument_key, quantity, sl_price, product="MTF", transaction_type="SELL"):
    """Submits a permanent 1-year GTT Stop-Loss directly to Upstox API v3."""
    cfg = load_config()
    tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if not tok:
        return False, "Upstox access token missing"

    trigger_p = round_to_tick(sl_price)
    tt = transaction_type.upper()
    trig_type = "BELOW" if tt == "SELL" else "ABOVE"
    prod_code = "D" if product.upper() in ("CNC", "DELIVERY", "D") else "MTF"

    payload = {
        "type": "SINGLE",
        "quantity": int(quantity),
        "product": prod_code,
        "rules": [
            {
                "strategy": "ENTRY",
                "trigger_type": trig_type,
                "trigger_price": float(trigger_p)
            }
        ],
        "instrument_token": instrument_key,
        "transaction_type": tt
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("https://api.upstox.com/v3/order/gtt/place", data=req_data, method="POST", headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                gtt_id = data.get("data", {}).get("gtt_order_id", "N/A")
                return True, str(gtt_id)
            errors = data.get("errors", [])
            err_msg = errors[0].get("message") if errors else (data.get("message") or "Upstox GTT placement failed")
            return False, err_msg
    except Exception as e:
        return False, f"Upstox GTT error: {str(e)}"


def cancel_upstox_gtt_order(gtt_id):
    """Cancels an active GTT order on Upstox API v3."""
    cfg = load_config()
    tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if not tok:
        return False, "Upstox token missing"

    req = urllib.request.Request(f"https://api.upstox.com/v3/order/gtt/cancel/{gtt_id}", method="DELETE", headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return (data.get("status") == "success"), str(gtt_id)
    except Exception as e:
        return False, str(e)


def place_broker_gtt_stop_loss(broker, symbol, quantity, sl_price, instrument_key=None, product="MTF", transaction_type="SELL", exchange="NSE"):
    """Unified dispatcher: submits a permanent 1-year GTT Stop-Loss to designated broker."""
    b = (broker or "").strip().lower()
    if b == "zerodha":
        return place_zerodha_gtt_stop_loss(symbol, quantity, sl_price, exchange=exchange, product="CNC" if product.upper() in ("CNC", "DELIVERY") else "MTF", transaction_type=transaction_type)
    elif b == "dhan":
        return place_dhan_forever_stop_loss(symbol, quantity, sl_price, product=product, transaction_type=transaction_type)
    elif b == "upstox":
        inst_k = instrument_key or resolve_instrument_key(symbol)
        if not inst_k:
            return False, f"Could not resolve instrument key for {symbol}"
        return place_upstox_gtt_stop_loss(inst_k, quantity, sl_price, product=product, transaction_type=transaction_type)
    return False, f"Unsupported broker for GTT: {broker}"


def modify_broker_gtt_stop_loss(broker, order_id, quantity, new_sl_price, symbol=None, transaction_type="SELL", exchange="NSE", product="CNC"):
    """Unified dispatcher: atomically modifies an existing GTT Stop-Loss on designated broker."""
    b = (broker or "").strip().lower()
    if b == "zerodha":
        return modify_zerodha_gtt_stop_loss(order_id, symbol or "", quantity, new_sl_price, exchange=exchange, product=product, transaction_type=transaction_type)
    elif b == "dhan":
        return modify_dhan_forever_stop_loss(order_id, quantity, new_sl_price, transaction_type=transaction_type)
    elif b == "upstox":
        return False, "Upstox GTT modify not yet implemented"
    return False, f"Unsupported broker for modify GTT: {broker}"


def cancel_broker_gtt_order(broker, order_id):
    """Unified dispatcher: cancels an active GTT order on designated broker."""
    b = (broker or "").strip().lower()
    if b == "zerodha":
        return cancel_zerodha_gtt_order(order_id)
    elif b == "dhan":
        return cancel_dhan_forever_order(order_id)
    elif b == "upstox":
        return cancel_upstox_gtt_order(order_id)
    return False, f"Unsupported broker: {broker}"


def get_pending_gtt_order(symbol, broker=None):
    """
    Inspects live broker GTT triggers (Zerodha GTT, Dhan Forever Orders, Upstox v3 GTT)
    for an active Stop-Loss for the given symbol.
    Returns:
        dict: {"order_id": ..., "broker": ..., "quantity": ..., "trigger_price": ..., "price": ..., "transaction_type": ..., "status": ..., "is_gtt": True} or None
    """
    sym_u = (symbol or "").strip().upper()
    cfg = load_config()
    brokers_to_check = [broker.lower()] if broker else ["zerodha", "dhan", "upstox"]

    for b in brokers_to_check:
        try:
            if b == "zerodha":
                kite = cfg.get("zerodha", {})
                ak = kite.get("api_key", "").strip()
                tok = kite.get("access_token", "").strip()
                if not (ak and tok):
                    continue
                url = "https://api.kite.trade/gtt/triggers"
                req = urllib.request.Request(url, headers={
                    "X-Kite-Version": "3",
                    "Authorization": f"token {ak}:{tok}",
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req, timeout=6) as resp:
                    d = json.loads(resp.read().decode())
                    for trig in d.get("data", []):
                        if str(trig.get("status", "")).lower() == "active":
                            cond = trig.get("condition", {})
                            ts = str(cond.get("tradingsymbol", "")).upper()
                            if sym_u and (ts == sym_u or sym_u in ts):
                                trig_vals = cond.get("trigger_values", [])
                                trig_p = trig_vals[0] if trig_vals else 0.0
                                ords = trig.get("orders", [])
                                qty = ords[0].get("quantity", 0) if ords else 0
                                lim_p = ords[0].get("price", 0.0) if ords else 0.0
                                tx_type = ords[0].get("transaction_type", "SELL") if ords else "SELL"
                                return {
                                    "order_id": str(trig.get("id")),
                                    "broker": "ZERODHA",
                                    "quantity": int(qty),
                                    "trigger_price": float(trig_p),
                                    "price": float(lim_p),
                                    "transaction_type": str(tx_type).upper(),
                                    "status": "ACTIVE_GTT",
                                    "order_type": "GTT",
                                    "is_gtt": True
                                }

            elif b == "dhan":
                dhan = cfg.get("dhan", {})
                cid = dhan.get("client_id", "").strip()
                tok = dhan.get("access_token", "").strip()
                sec_id = str(resolve_dhan_security_id(sym_u) or "")
                if not (cid and tok):
                    continue
                url = "https://api.dhan.co/v2/forever/orders"
                req = urllib.request.Request(url, headers={
                    "access-token": tok,
                    "client-id": cid,
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req, timeout=6) as resp:
                    d = json.loads(resp.read().decode())
                    if isinstance(d, list):
                        for ord_item in d:
                            st = str(ord_item.get("orderStatus", "")).upper()
                            sid = str(ord_item.get("securityId", ""))
                            trad_sym = str(ord_item.get("tradingSymbol", "")).upper()
                            if st in ("TRANSIT", "PENDING", "ACTIVE", "CONFIRMED"):
                                if (sec_id and sid == sec_id) or (sym_u and sym_u in trad_sym):
                                    return {
                                        "order_id": str(ord_item.get("orderId")),
                                        "broker": "DHAN",
                                        "quantity": int(ord_item.get("quantity", 0)),
                                        "trigger_price": float(ord_item.get("triggerPrice", 0) or 0),
                                        "price": float(ord_item.get("price", 0) or 0),
                                        "transaction_type": str(ord_item.get("transactionType", "SELL")).upper(),
                                        "status": "ACTIVE_GTT",
                                        "order_type": "FOREVER_GTT",
                                        "is_gtt": True
                                    }

            elif b == "upstox":
                upstox = cfg.get("upstox", {})
                tok = upstox.get("access_token", "").strip()
                if not tok:
                    continue
                url = "https://api.upstox.com/v3/order/gtt"
                req = urllib.request.Request(url, headers={
                    "Authorization": f"Bearer {tok}",
                    "Accept": "application/json",
                    "User-Agent": "Jarvis-Order-Engine"
                })
                with urllib.request.urlopen(req, timeout=6) as resp:
                    d = json.loads(resp.read().decode())
                    for ord_item in d.get("data", []):
                        st = str(ord_item.get("status", "")).upper()
                        if st in ("ACTIVE", "OPEN", "TRIGGER_PENDING"):
                            inst = str(ord_item.get("instrument_token", "")).upper()
                            trad_sym = str(ord_item.get("trading_symbol", "")).upper()
                            if sym_u in inst or sym_u in trad_sym:
                                rules = ord_item.get("rules", [])
                                trig_p = rules[0].get("trigger_price", 0.0) if rules else 0.0
                                return {
                                    "order_id": str(ord_item.get("gtt_order_id", ord_item.get("order_id", ""))),
                                    "broker": "UPSTOX",
                                    "quantity": int(ord_item.get("quantity", 0)),
                                    "trigger_price": float(trig_p),
                                    "price": float(ord_item.get("price", trig_p)),
                                    "transaction_type": str(ord_item.get("transaction_type", "SELL")).upper(),
                                    "status": "ACTIVE_GTT",
                                    "order_type": "GTT",
                                    "is_gtt": True
                                }
        except Exception:
            pass
    return None

def get_pending_stop_loss_order(symbol, broker=None):
    """
    Inspects live broker stop-loss protection for the given symbol.
    Checks permanent GTT triggers FIRST (Zerodha GTT, Dhan Forever Orders, Upstox GTT).
    Falls back to regular exchange DAY orders if no GTT trigger is found.
    """
    sym_u = (symbol or "").strip().upper()

    # 1. Check GTT first (permanent 1-year broker-level stop loss)
    gtt = get_pending_gtt_order(sym_u, broker=broker)
    if gtt:
        return gtt

    # 2. Fall back to regular exchange DAY orderbook
    cfg = load_config()
    brokers_to_check = [broker.lower()] if broker else ["upstox", "dhan", "zerodha"]

    for b in brokers_to_check:
        try:
            if b == "upstox":
                token = cfg.get("upstox", {}).get("access_token", "").strip()
                if not token:
                    continue
                url = "https://api.upstox.com/v2/order/retrieve-all"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    d = json.loads(resp.read().decode())
                    for ord_item in d.get("data", []):
                        st = str(ord_item.get("status", "")).lower()
                        ot = str(ord_item.get("order_type", "")).upper()
                        if st in ("trigger pending", "open", "put order req received") and ot in ("SL", "SL-M"):
                            inst = str(ord_item.get("instrument_token", "")).upper()
                            trad_sym = str(ord_item.get("trading_symbol", "")).upper()
                            if sym_u in inst or sym_u in trad_sym:
                                return {
                                    "order_id": str(ord_item.get("order_id")),
                                    "broker": "UPSTOX",
                                    "quantity": int(ord_item.get("quantity", 0)),
                                    "trigger_price": float(ord_item.get("trigger_price", 0) or 0),
                                    "price": float(ord_item.get("price", 0) or 0),
                                    "order_type": ot,
                                    "transaction_type": str(ord_item.get("transaction_type", "SELL")).upper(),
                                    "status": st
                                }

            elif b == "dhan":
                dhan = cfg.get("dhan", {})
                cid = dhan.get("client_id", "").strip()
                token = dhan.get("access_token", "").strip()
                sec_id = str(resolve_dhan_security_id(sym_u) or "")
                if not (cid and token):
                    continue
                url = "https://api.dhan.co/v2/orders"
                req = urllib.request.Request(url, headers={"access-token": token, "client-id": cid, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    d = json.loads(resp.read().decode())
                    if isinstance(d, list):
                        for ord_item in d:
                            st = str(ord_item.get("orderStatus", "")).upper()
                            ot = str(ord_item.get("orderType", "")).upper()
                            sid = str(ord_item.get("securityId", ""))
                            trad_sym = str(ord_item.get("tradingSymbol", "")).upper()
                            if st in ("TRANSIT", "PENDING", "TRIGGER_PENDING") and ot in ("STOP_LOSS", "SL", "STOP_LOSS_MARKET"):
                                if (sec_id and sid == sec_id) or (sym_u and sym_u in trad_sym):
                                    return {
                                        "order_id": str(ord_item.get("orderId")),
                                        "broker": "DHAN",
                                        "quantity": int(ord_item.get("quantity", 0)),
                                        "trigger_price": float(ord_item.get("triggerPrice", 0) or 0),
                                        "price": float(ord_item.get("price", 0) or 0),
                                        "order_type": ot,
                                        "transaction_type": str(ord_item.get("transactionType", "SELL")).upper(),
                                        "status": st
                                    }

            elif b == "zerodha":
                kite = cfg.get("zerodha", {})
                ak = kite.get("api_key", "").strip()
                token = kite.get("access_token", "").strip()
                if not (ak and token):
                    continue
                url = "https://api.kite.trade/orders"
                req = urllib.request.Request(url, headers={
                    "X-Kite-Version": "3",
                    "Authorization": f"token {ak}:{token}",
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req, timeout=8) as resp:
                    d = json.loads(resp.read().decode())
                    orders = d.get("data", [])
                    for ord_item in orders:
                        st = str(ord_item.get("status", "")).upper()
                        ot = str(ord_item.get("order_type", "")).upper()
                        ts = str(ord_item.get("tradingsymbol", "")).upper()
                        if st in ("TRIGGER PENDING", "OPEN") and ot in ("SL", "SL-M"):
                            if sym_u and (ts == sym_u or sym_u in ts):
                                return {
                                    "order_id": str(ord_item.get("order_id")),
                                    "broker": "ZERODHA",
                                    "quantity": int(ord_item.get("quantity", 0)),
                                    "trigger_price": float(ord_item.get("trigger_price", 0) or 0),
                                    "price": float(ord_item.get("price", 0) or 0),
                                    "order_type": ot,
                                    "transaction_type": str(ord_item.get("transaction_type", "SELL")).upper(),
                                    "status": st
                                }
        except Exception:
            pass
    return None


def cancel_broker_order(broker, order_id):
    """Cancels a pending order on the designated broker."""
    b = (broker or "").strip().lower()
    cfg = load_config()
    try:
        if b == "upstox":
            token = cfg.get("upstox", {}).get("access_token", "").strip()
            if not token:
                return False, "Upstox token missing"
            url = f"https://api.upstox.com/v2/order/cancel?order_id={order_id}"
            req = urllib.request.Request(url, method="DELETE", headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                return (data.get("status") == "success"), data.get("data", {}).get("order_id", order_id)

        elif b == "dhan":
            dhan = cfg.get("dhan", {})
            cid = dhan.get("client_id", "").strip()
            token = dhan.get("access_token", "").strip()
            if not cid or not token:
                return False, "Dhan credentials missing"
            url = f"https://api.dhan.co/v2/orders/{order_id}"
            req = urllib.request.Request(url, method="DELETE", headers={
                "access-token": token,
                "client-id": cid,
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                return True, data.get("orderId", order_id)

        elif b == "zerodha":
            kite = cfg.get("zerodha", {})
            ak = kite.get("api_key", "").strip()
            token = kite.get("access_token", "").strip()
            if not ak or not token:
                return False, "Zerodha credentials missing"
            url = f"https://api.kite.trade/orders/regular/{order_id}"
            req = urllib.request.Request(url, method="DELETE", headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {ak}:{token}"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                return (data.get("status") == "success"), data.get("data", {}).get("order_id", order_id)
    except Exception as e:
        return False, str(e)
    return False, f"Unsupported broker: {broker}"


def cancel_symbol_stop_loss(symbol, broker=None):
    """
    Cancels any pending stop-loss orders (both GTT triggers and DAY orders) for symbol upon exit.
    1. Cancels active GTT trigger via cancel_broker_gtt_order.
    2. Checks orders_log.json for stored sl_order_id.
    3. Queries broker orderbook and cancels any trigger-pending sell orders.
    """
    sym_u = symbol.strip().upper()
    cfg = load_config()
    target_broker = (broker or get_default_broker()).strip().lower()
    cancelled = []

    # 0. Cancel active GTT trigger if present
    try:
        active_gtt = get_pending_gtt_order(sym_u, broker=target_broker)
        if active_gtt and active_gtt.get("order_id"):
            gtt_b = active_gtt.get("broker", target_broker).lower()
            ok_gtt, gtt_oid = cancel_broker_gtt_order(gtt_b, active_gtt["order_id"])
            if ok_gtt:
                cancelled.append(f"GTT:{gtt_oid}")
    except Exception:
        pass

    # 1. Cancel recorded SL order ID from orders_log.json
    if ORDERS_LOG_FILE.is_file():
        try:
            with open(ORDERS_LOG_FILE, "r", encoding="utf-8") as f:
                orders = json.load(f)
            updated = False
            for o in orders:
                if o.get("symbol") == sym_u and o.get("sl_order_id") and o.get("sl_status") == "PLACED":
                    sl_oid = o["sl_order_id"]
                    b_target = o.get("broker", target_broker).lower()
                    ok, _ = cancel_broker_order(b_target, sl_oid)
                    if ok:
                        o["sl_status"] = "CANCELLED"
                        cancelled.append(sl_oid)
                        updated = True
            if updated:
                with open(ORDERS_LOG_FILE, "w", encoding="utf-8") as f:
                    json.dump(orders, f, indent=2)
        except Exception:
            pass

    # 2. Query broker orderbook to cancel any dangling trigger-pending sell orders
    try:
        if target_broker == "upstox":
            token = cfg.get("upstox", {}).get("access_token", "").strip()
            if token:
                url = "https://api.upstox.com/v2/order/retrieve-all"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    d = json.loads(resp.read().decode())
                    for ord_item in d.get("data", []):
                        st = str(ord_item.get("status", "")).lower()
                        tt = str(ord_item.get("transaction_type", "")).upper()
                        oid = ord_item.get("order_id")
                        if st in ("trigger pending", "open", "put order req received") and tt == "SELL":
                            inst = ord_item.get("instrument_token", "")
                            trad_sym = ord_item.get("trading_symbol", "")
                            if sym_u in inst or sym_u in trad_sym:
                                if oid and oid not in cancelled:
                                    cancel_broker_order("upstox", oid)
                                    cancelled.append(oid)
        elif target_broker == "dhan":
            dhan = cfg.get("dhan", {})
            cid = dhan.get("client_id", "").strip()
            token = dhan.get("access_token", "").strip()
            sec_id = str(resolve_dhan_security_id(sym_u) or "")
            if cid and token:
                url = "https://api.dhan.co/v2/orders"
                req = urllib.request.Request(url, headers={"access-token": token, "client-id": cid, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    d = json.loads(resp.read().decode())
                    if isinstance(d, list):
                        for ord_item in d:
                            st = str(ord_item.get("orderStatus", "")).upper()
                            tt = str(ord_item.get("transactionType", "")).upper()
                            sid = str(ord_item.get("securityId", ""))
                            oid = ord_item.get("orderId")
                            if st in ("TRANSIT", "PENDING", "TRIGGER_PENDING") and tt == "SELL":
                                if sec_id and sid == sec_id:
                                    if oid and oid not in cancelled:
                                        cancel_broker_order("dhan", oid)
                                        cancelled.append(oid)
    except Exception:
        pass

    return cancelled


def execute_broker_order(symbol, mode_arg="mod", sl_mode="lod", broker=None):
    """
    Executes full pipeline across any requested broker:
    Upstox (MTF), Dhan (MTF), or Zerodha (CNC).
    """
    symbol = resolve_symbol(symbol)
    target_broker = (broker or get_default_broker()).strip().lower()
    if target_broker not in SUPPORTED_BROKERS:
        target_broker = "upstox"

    quote_data, err = fetch_live_quote(symbol)
    if not quote_data:
        return False, err

    calc = calculate_order_sizing(quote_data, mode_arg=mode_arg, sl_mode=sl_mode)
    if calc["quantity"] <= 0:
        return False, f"Calculated quantity is 0. LTP (₹{calc['ltp']}) exceeds allocated size (₹{calc['target_size']:,})."

    product_label = "MTF"
    # Execute at designated broker
    if target_broker == "upstox":
        success, resp = place_upstox_mtf_order(
            instrument_key=calc["instrument_key"],
            quantity=calc["quantity"],
            order_type="MARKET"
        )
    elif target_broker == "dhan":
        success, resp = place_dhan_mtf_order(
            symbol=symbol,
            quantity=calc["quantity"],
            order_type="MARKET"
        )
    elif target_broker == "zerodha":
        product_label = "CNC (Delivery)"
        success, resp = place_zerodha_order(
            symbol=symbol,
            quantity=calc["quantity"],
            order_type="MARKET",
            product="CNC"
        )
    else:
        return False, f"Unsupported broker: {target_broker}"

    now_ist = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    # Hard Broker Stop-Loss Placement
    sl_placed = False
    sl_order_id = None
    sl_error = None
    if success and calc.get("stop_loss") and float(calc["stop_loss"]) > 0:
        cfg = load_config()
        if cfg.get("auto_place_broker_sl", True):
            sl_ok, sl_res = place_broker_stop_loss(
                broker=target_broker,
                symbol=symbol,
                quantity=calc["quantity"],
                sl_price=calc["stop_loss"],
                instrument_key=calc.get("instrument_key"),
                product=product_label.split()[0]
            )
            sl_placed = sl_ok
            if sl_ok:
                sl_order_id = sl_res
            else:
                sl_error = sl_res

    calc["sl_placed"] = sl_placed
    calc["sl_order_id"] = sl_order_id
    calc["sl_error"] = sl_error

    record = {
        "timestamp": now_ist,
        "symbol": symbol.upper(),
        "broker": target_broker.upper(),
        "product": product_label,
        "action": "BUY",
        "quantity": calc["quantity"],
        "ltp": calc["ltp"],
        "exposure": calc["actual_exposure"],
        "stop_loss": calc["stop_loss"],
        "sl_order_id": sl_order_id,
        "sl_status": "PLACED" if sl_placed else ("FAILED" if sl_error else "SKIPPED"),
        "risk_pct": calc["risk_pct"],
        "total_risk_inr": calc["total_risk_inr"],
        "mode": calc["mode_label"],
        "status": "PLACED" if success else "FAILED",
        "order_id": resp if success else None,
        "error": resp if not success else None
    }

    log_executed_order(record)

    # Automatically add stock to watchlist.txt so scanner monitors it immediately
    try:
        from telegram_bot import read_watchlist_symbols, write_watchlist_symbols
        curr_syms = read_watchlist_symbols()
        if symbol.upper() not in curr_syms:
            curr_syms.append(symbol.upper())
            write_watchlist_symbols(curr_syms)
    except Exception:
        pass

    calc["order_id"] = resp if success else None
    calc["placed_at"] = now_ist
    calc["broker"] = target_broker.upper()
    calc["product_label"] = product_label

    return success, calc if success else resp


# ---------------------------------------------------------
# Multi-Broker Open Positions & Portfolio Retrieval
# ---------------------------------------------------------
def fetch_all_positions():
    """
    Fetches open positions across Upstox, Dhan, and Zerodha.
    Returns:
        positions: list of dicts with keys:
            symbol, broker, product, qty, avg_price, ltp, pnl, pnl_pct, exposure
        totals: dict with total_pnl, total_exposure, count
        broker_status: dict indicating which brokers were queried successfully
    """
    cfg = load_config()
    tracked_holdings = set(s.upper() for s in cfg.get("tracked_swing_holdings", ["KROSS", "NSE", "BHARTIHEXA", "TATACONSUM", "ENTERO"]))
    ignored_symbols = set(s.upper() for s in cfg.get("ignored_symbols", ["MOTHERSON"]))
    all_pos = []
    broker_status = {}

    # 1. Dhan Positions
    dhan = cfg.get("dhan", {})
    d_token = dhan.get("access_token", "").strip()
    d_client = dhan.get("client_id", "").strip()
    if d_token and d_client:
        try:
            req = urllib.request.Request(
                "https://api.dhan.co/v2/positions",
                headers={
                    "access-token": d_token,
                    "client-id": d_client,
                    "Accept": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                d_pos = json.loads(resp.read().decode())
                broker_status["dhan"] = f"OK ({len(d_pos)})"
                for p in d_pos:
                    net_qty = int(p.get("netQty", 0))
                    sym = p.get("tradingSymbol", "UNKNOWN").strip().upper()
                    if not sym or sym in ignored_symbols:
                        continue
                    prod_type = str(p.get("productType", "MTF")).upper()
                    if prod_type in ("CNC", "MTF") and net_qty < 0:
                        continue
                    if net_qty != 0:
                        buy_avg = float(p.get("buyAvg", 0) or p.get("costPrice", 0) or 0)
                        realized = float(p.get("realizedProfit", 0) or 0)
                        unrealized = float(p.get("unrealizedProfit", 0) or 0)
                        tot_pnl = realized + unrealized
                        # Estimate LTP from cost and unrealized pnl if available
                        ltp = buy_avg + (unrealized / net_qty) if net_qty != 0 and buy_avg > 0 else buy_avg
                        exposure = round(abs(net_qty) * ltp, 2)
                        pnl_pct = round((tot_pnl / (abs(net_qty) * buy_avg)) * 100, 2) if buy_avg > 0 else 0.0

                        all_pos.append({
                            "symbol": sym,
                            "broker": "DHAN",
                            "product": str(p.get("productType", "MTF")).upper(),
                            "qty": net_qty,
                            "avg_price": round(buy_avg, 2),
                            "ltp": round(ltp, 2),
                            "pnl": round(tot_pnl, 2),
                            "pnl_pct": pnl_pct,
                            "exposure": exposure,
                            "security_id": str(p.get("securityId", "")),
                            "exchange": p.get("exchangeSegment", "NSE_EQ"),
                            "position_type": p.get("positionType", "LONG")
                        })

                # Check Dhan holdings for designated swing positions
                if tracked_holdings:
                    try:
                        req_h = urllib.request.Request(
                            "https://api.dhan.co/v2/holdings",
                            headers={
                                "access-token": d_token,
                                "client-id": d_client,
                                "Accept": "application/json"
                            }
                        )
                        with urllib.request.urlopen(req_h, timeout=6) as resp_h:
                            d_holdings = json.loads(resp_h.read().decode())
                            if isinstance(d_holdings, list):
                                for h in d_holdings:
                                    sym = str(h.get("tradingSymbol", "")).strip().upper()
                                    if not sym or sym in ignored_symbols:
                                        continue
                                    if sym in tracked_holdings and not any(p["symbol"].upper() == sym and p["broker"] == "DHAN" for p in all_pos):
                                        qty = int(h.get("totalQty", 0))
                                        if qty > 0:
                                            buy_avg = float(h.get("avgCostPrice", 0.0) or 0.0)
                                            ltp = float(h.get("lastTradedPrice", buy_avg) or buy_avg)
                                            tot_pnl = round((ltp - buy_avg) * qty, 2)
                                            pnl_pct = round(((ltp - buy_avg) / buy_avg) * 100, 2) if buy_avg > 0 else 0.0
                                            exposure = round(qty * ltp, 2)
                                            mtf_q = int(h.get("mtf_qty", 0) or 0)
                                            prod_type = "MTF" if mtf_q > 0 else "CNC"
                                            all_pos.append({
                                                "symbol": sym,
                                                "broker": "DHAN",
                                                "product": prod_type,
                                                "qty": qty,
                                                "avg_price": round(buy_avg, 2),
                                                "ltp": round(ltp, 2),
                                                "pnl": round(tot_pnl, 2),
                                                "pnl_pct": pnl_pct,
                                                "exposure": exposure,
                                                "security_id": str(h.get("securityId", "")),
                                                "exchange": "NSE_EQ",
                                                "position_type": "LONG"
                                            })
                    except Exception:
                        pass
        except Exception as e:
            broker_status["dhan"] = f"Error ({e})"
    else:
        broker_status["dhan"] = "Not configured"

    # 2. Upstox Positions
    upstox = cfg.get("upstox", {})
    u_token = upstox.get("access_token", "").strip()
    if u_token:
        try:
            req = urllib.request.Request(
                "https://api.upstox.com/v2/portfolio/short-term-positions",
                headers={
                    "Authorization": f"Bearer {u_token}",
                    "Accept": "application/json",
                    "User-Agent": "Jarvis-Positions-Monitor"
                }
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                u_data = json.loads(resp.read().decode())
                u_pos = u_data.get("data", [])
                broker_status["upstox"] = f"OK ({len(u_pos)})"
                for p in u_pos:
                    net_qty = int(p.get("quantity", 0))
                    sym = p.get("trading_symbol", "UNKNOWN").strip().upper()
                    if not sym or sym in ignored_symbols:
                        continue
                    prod_type = str(p.get("product", "MTF")).upper()
                    if prod_type in ("CNC", "MTF") and net_qty < 0:
                        continue
                    if net_qty != 0:
                        avg_price = float(p.get("average_price", 0) or 0)
                        pnl = float(p.get("pnl", 0) or 0)
                        ltp = float(p.get("last_price", 0) or avg_price)
                        exposure = round(abs(net_qty) * ltp, 2)
                        pnl_pct = round((pnl / (abs(net_qty) * avg_price)) * 100, 2) if avg_price > 0 else 0.0

                        all_pos.append({
                            "symbol": sym,
                            "broker": "UPSTOX",
                            "product": str(p.get("product", "MTF")).upper(),
                            "qty": net_qty,
                            "avg_price": round(avg_price, 2),
                            "ltp": round(ltp, 2),
                            "pnl": round(pnl, 2),
                            "pnl_pct": pnl_pct,
                            "exposure": exposure,
                            "instrument_token": str(p.get("instrument_token", "")),
                            "exchange": p.get("exchange", "NSE_EQ")
                        })
        except Exception as e:
            broker_status["upstox"] = f"Error ({e})"
    else:
        broker_status["upstox"] = "Not configured"

    # 3. Zerodha Kite Positions
    zerodha = cfg.get("zerodha", {})
    z_key = zerodha.get("api_key", "").strip()
    z_token = zerodha.get("access_token", "").strip()
    if z_key and z_token:
        try:
            req = urllib.request.Request(
                "https://api.kite.trade/portfolio/positions",
                headers={
                    "X-Kite-Version": "3",
                    "Authorization": f"token {z_key}:{z_token}"
                }
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                z_data = json.loads(resp.read().decode())
                z_pos = z_data.get("data", {}).get("net", [])
                broker_status["zerodha"] = f"OK ({len(z_pos)})"
                for p in z_pos:
                    net_qty = int(p.get("quantity", 0))
                    sym = p.get("tradingsymbol", "UNKNOWN").strip().upper()
                    if not sym or sym in ignored_symbols:
                        continue
                    prod_type = str(p.get("product", "CNC")).upper()
                    seg = str(p.get("segment", "CASH")).upper()
                    # In Indian cash equity, retail swing positions are strictly LONG.
                    # Negative quantity in CNC/MTF represents an intraday sale/exit of a holding
                    # awaiting EOD settlement (e.g. MOTHERSON GTT triggered -> quantity: -501).
                    if (prod_type in ("CNC", "MTF") or seg == "CASH") and net_qty < 0:
                        continue
                    if net_qty != 0:
                        avg_price = float(p.get("average_price", 0) or 0)
                        pnl = float(p.get("pnl", 0) or 0)
                        ltp = float(p.get("last_price", 0) or avg_price)
                        exposure = round(abs(net_qty) * ltp, 2)
                        pnl_pct = round((pnl / (abs(net_qty) * avg_price)) * 100, 2) if avg_price > 0 else 0.0

                        all_pos.append({
                            "symbol": sym,
                            "broker": "ZERODHA",
                            "product": str(p.get("product", "CNC")).upper(),
                            "qty": net_qty,
                            "avg_price": round(avg_price, 2),
                            "ltp": round(ltp, 2),
                            "pnl": round(pnl, 2),
                            "pnl_pct": pnl_pct,
                            "exposure": exposure,
                            "exchange": p.get("exchange", "NSE"),
                            "instrument_token": str(p.get("instrument_token", ""))
                        })

                # Check Zerodha holdings for designated swing positions
                if tracked_holdings:
                    try:
                        req_h = urllib.request.Request(
                            "https://api.kite.trade/portfolio/holdings",
                            headers={
                                "X-Kite-Version": "3",
                                "Authorization": f"token {z_key}:{z_token}"
                            }
                        )
                        with urllib.request.urlopen(req_h, timeout=6) as resp_h:
                            z_hdata = json.loads(resp_h.read().decode())
                            z_holdings = z_hdata.get("data", [])
                            for h in z_holdings:
                                sym = str(h.get("tradingsymbol", "")).strip().upper()
                                if not sym or sym in ignored_symbols:
                                    continue
                                if sym in tracked_holdings and not any(p["symbol"].upper() == sym and p["broker"] == "ZERODHA" for p in all_pos):
                                    qty = int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
                                    if qty > 0:
                                        avg_price = float(h.get("average_price", 0.0) or 0.0)
                                        ltp = float(h.get("last_price", avg_price) or avg_price)
                                        tot_pnl = float(h.get("pnl", 0.0) or round((ltp - avg_price) * qty, 2))
                                        pnl_pct = round((tot_pnl / (qty * avg_price)) * 100, 2) if avg_price > 0 else 0.0
                                        exposure = round(qty * ltp, 2)
                                        all_pos.append({
                                            "symbol": sym,
                                            "broker": "ZERODHA",
                                            "product": "CNC",
                                            "qty": qty,
                                            "avg_price": round(avg_price, 2),
                                            "ltp": round(ltp, 2),
                                            "pnl": round(tot_pnl, 2),
                                            "pnl_pct": pnl_pct,
                                            "exposure": exposure,
                                            "exchange": h.get("exchange", "NSE"),
                                            "instrument_token": str(h.get("instrument_token", "")),
                                            "position_type": "LONG"
                                        })
                    except Exception:
                        pass
        except Exception as e:
            broker_status["zerodha"] = f"Error ({e})"
    else:
        broker_status["zerodha"] = "Not configured"

    # 4. Enrich positions with active Stop-Loss & Value at Risk (VaR)
    logged_trades = get_open_trades_from_logs()
    total_var = 0.0

    for p in all_pos:
        sym_u = p["symbol"].upper()
        buy_avg = float(p.get("avg_price", 0) or 0)
        qty = int(p.get("qty", 0) or 0)
        is_short = qty < 0
        log_meta = logged_trades.get(sym_u, {})
        sl = float(log_meta.get("stop_loss", 0) or 0)

        # Fallback structural SL if not logged
        if sl <= 0 and buy_avg > 0:
            if is_short:
                if "CE" in sym_u or "PE" in sym_u or "NIFTY" in sym_u:
                    sl = round(buy_avg * 1.30, 2)
                else:
                    sl = round(buy_avg * 1.025, 2)
            else:
                if "CE" in sym_u or "PE" in sym_u or "NIFTY" in sym_u:
                    sl = round(buy_avg * 0.70, 2)
                else:
                    sl = round(buy_avg * 0.975, 2)

        if is_short:
            # For short positions: SL is above entry. Risk is (sl - buy_avg) * abs(qty).
            # Breakeven / risk-free is reached when SL has been trailed to <= entry.
            if sl <= buy_avg and sl > 0:
                var_inr = 0.0
                var_pct = 0.0
            else:
                var_inr = max(0.0, round((sl - buy_avg) * abs(qty), 2)) if buy_avg > 0 else 0.0
                var_pct = round(((sl - buy_avg) / buy_avg) * 100, 2) if buy_avg > 0 else 0.0
        else:
            # For long positions: SL is below entry. Risk is (buy_avg - sl) * qty.
            # Breakeven / risk-free is reached when SL has been trailed to >= entry.
            if sl >= buy_avg and buy_avg > 0:
                var_inr = 0.0
                var_pct = 0.0
            else:
                var_inr = max(0.0, round((buy_avg - sl) * qty, 2)) if buy_avg > 0 else 0.0
                var_pct = round(((buy_avg - sl) / buy_avg) * 100, 2) if buy_avg > 0 else 0.0

        p["stop_loss"] = sl
        p["value_at_risk"] = var_inr
        p["var_pct"] = var_pct
        p["is_risk_free"] = bool(var_inr <= 0)
        p["is_short"] = is_short
        p["position_type"] = "SHORT" if is_short else "LONG"
        total_var += var_inr

    total_pnl = sum(p["pnl"] for p in all_pos)
    total_exposure = sum(p["exposure"] for p in all_pos)
    total_var_pct = round((total_var / total_exposure) * 100, 2) if total_exposure > 0 else 0.0

    totals = {
        "count": len(all_pos),
        "total_pnl": round(total_pnl, 2),
        "total_exposure": round(total_exposure, 2),
        "total_var": round(total_var, 2),
        "total_var_pct": total_var_pct
    }

    return all_pos, totals, broker_status


def execute_broker_exit(symbol, broker=None, exit_qty=None, qty_ratio="all"):
    """
    Executes a market exit order (SELL for long, BUY for short) for an open position across Dhan, Upstox, or Zerodha.
    Args:
        symbol: trading symbol (e.g. 'ABDL', 'MOTHERSON', 'NSE')
        broker: optional broker filter ('DHAN', 'UPSTOX', 'ZERODHA')
        exit_qty: explicit integer quantity to exit (optional)
        qty_ratio: 'all' (100%), 'half' (50%), or int
    Returns:
        (success: bool, result: dict or str)
    """
    cfg = load_config()
    all_pos, totals, _ = fetch_all_positions()

    sym_clean = symbol.strip().upper()
    target_pos = None

    for p in all_pos:
        p_sym = p["symbol"].upper()
        if p_sym == sym_clean or p_sym.startswith(sym_clean) or sym_clean.startswith(p_sym):
            if broker and p["broker"].upper() != broker.strip().upper():
                continue
            target_pos = p
            break

    if not target_pos:
        b_str = f" on {broker}" if broker else ""
        return False, f"No open position found for {symbol}{b_str}."

    net_qty = target_pos["qty"]
    if net_qty == 0:
        return False, f"Position for {target_pos['symbol']} has 0 quantity."

    trans_type = "SELL" if net_qty > 0 else "BUY"
    abs_qty = abs(net_qty)

    if exit_qty is not None and int(exit_qty) > 0:
        actual_exit_qty = min(abs_qty, int(exit_qty))
    elif str(qty_ratio).lower() in ("half", "50%", "50"):
        actual_exit_qty = max(1, abs_qty // 2)
    else:
        actual_exit_qty = abs_qty

    b = target_pos["broker"].upper()
    prod = target_pos.get("product", "MTF")

    # 1. Dhan Exit
    if b == "DHAN":
        dhan = cfg.get("dhan", {})
        client_id = dhan.get("client_id", "").strip()
        token = dhan.get("access_token", "").strip()
        if not client_id or not token:
            return False, "Dhan credentials missing in config_credentials.json"

        sec_id = target_pos.get("security_id") or resolve_dhan_security_id(target_pos["symbol"])
        if not sec_id:
            return False, f"Could not find securityId for {target_pos['symbol']} on Dhan"

        exch_seg = target_pos.get("exchange", "NSE_EQ")
        if not exch_seg:
            exch_seg = "NSE_EQ"

        payload = {
            "dhanClientId": client_id,
            "transactionType": trans_type,
            "exchangeSegment": exch_seg,
            "productType": prod if prod in ("MTF", "CNC", "MARGIN", "INTRADAY") else "MTF",
            "orderType": "MARKET",
            "validity": "DAY",
            "securityId": str(sec_id),
            "quantity": int(actual_exit_qty),
            "price": 0.0,
            "triggerPrice": 0.0,
            "afterMarketOrder": False
        }

        req = urllib.request.Request(
            "https://api.dhan.co/v2/orders",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "access-token": token,
                "client-id": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Jarvis-Order-Engine"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                order_id = data.get("orderId")
                status = data.get("orderStatus", "SUBMITTED")
                if order_id:
                    res_dict = {
                        "broker": "DHAN",
                        "symbol": target_pos["symbol"],
                        "order_id": order_id,
                        "status": status,
                        "quantity": actual_exit_qty,
                        "remaining_qty": abs_qty - actual_exit_qty,
                        "product": prod,
                        "trans_type": trans_type
                    }
                    # Automatically cancel open stop-loss orders to eliminate dangling short exposure
                    try:
                        cancelled_sl = cancel_symbol_stop_loss(target_pos["symbol"], broker=target_pos["broker"])
                        if cancelled_sl:
                            res_dict["cancelled_sl_orders"] = cancelled_sl
                    except Exception:
                        pass

                    log_executed_order({
                        "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
                        "action": "EXIT",
                        **res_dict
                    })
                    return True, res_dict
                err = data.get("errorMessage") or data.get("message") or "Order failed"
                return False, f"Dhan error: {err}"
        except urllib.error.HTTPError as he:
            try:
                err_data = json.loads(he.read().decode())
                msg = err_data.get("errorMessage") or err_data.get("message") or str(he)
                return False, f"Dhan HTTP {he.code}: {msg}"
            except Exception:
                return False, f"Dhan HTTP {he.code}: {he.reason}"
        except Exception as e:
            return False, f"Dhan exit error: {str(e)}"

    # 2. Zerodha Exit
    elif b == "ZERODHA":
        zerodha = cfg.get("zerodha", {})
        api_key = zerodha.get("api_key", "").strip()
        token = zerodha.get("access_token", "").strip()
        if not api_key or not token:
            return False, "Zerodha credentials missing in config_credentials.json"

        exch = target_pos.get("exchange", "NSE")
        payload = {
            "tradingsymbol": target_pos["symbol"],
            "exchange": exch,
            "transaction_type": trans_type,
            "order_type": "MARKET",
            "quantity": int(actual_exit_qty),
            "product": prod if prod in ("CNC", "MIS", "MTF", "NRML") else "CNC",
            "validity": "DAY",
            "tag": "JarvisExit"
        }

        req_data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.kite.trade/orders/regular",
            data=req_data,
            method="POST",
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {api_key}:{token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Jarvis-Order-Engine"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "success":
                    order_id = data.get("data", {}).get("order_id", "N/A")
                    res_dict = {
                        "broker": "ZERODHA",
                        "symbol": target_pos["symbol"],
                        "order_id": order_id,
                        "status": "SUBMITTED",
                        "quantity": actual_exit_qty,
                        "remaining_qty": abs_qty - actual_exit_qty,
                        "product": prod,
                        "trans_type": trans_type
                    }
                    # Automatically cancel open stop-loss orders to eliminate dangling short exposure
                    try:
                        cancelled_sl = cancel_symbol_stop_loss(target_pos["symbol"], broker=target_pos["broker"])
                        if cancelled_sl:
                            res_dict["cancelled_sl_orders"] = cancelled_sl
                    except Exception:
                        pass

                    log_executed_order({
                        "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
                        "action": "EXIT",
                        **res_dict
                    })
                    return True, res_dict
                return False, data.get("message", "Zerodha exit failed")
        except urllib.error.HTTPError as he:
            try:
                err_data = json.loads(he.read().decode())
                return False, err_data.get("message", f"Zerodha HTTP {he.code}: {he.reason}")
            except Exception:
                return False, f"Zerodha HTTP {he.code}: {he.reason}"
        except Exception as e:
            return False, f"Zerodha exit error: {str(e)}"

    # 3. Upstox Exit
    elif b == "UPSTOX":
        upstox = cfg.get("upstox", {})
        token = upstox.get("access_token", "").strip()
        if not token:
            return False, "Upstox token missing in config_credentials.json"

        instrument_token = target_pos.get("instrument_token")
        if not instrument_token:
            instrument_token = resolve_instrument_key(target_pos["symbol"])
            if not instrument_token:
                return False, f"Could not map Upstox instrument key for {target_pos['symbol']}"

        upstox_product = "MTF" if prod == "MTF" else ("D" if prod in ("CNC", "DELIVERY") else "I")

        payload = {
            "quantity": int(actual_exit_qty),
            "product": upstox_product,
            "validity": "DAY",
            "price": 0.0,
            "tag": "JarvisExit",
            "instrument_token": instrument_token,
            "order_type": "MARKET",
            "transaction_type": trans_type,
            "disclosed_quantity": 0,
            "trigger_price": 0.0,
            "is_amo": False
        }

        req = urllib.request.Request(
            "https://api.upstox.com/v2/order/place",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "success":
                    order_id = data.get("data", {}).get("order_id", "N/A")
                    res_dict = {
                        "broker": "UPSTOX",
                        "symbol": target_pos["symbol"],
                        "order_id": order_id,
                        "status": "SUBMITTED",
                        "quantity": actual_exit_qty,
                        "remaining_qty": abs_qty - actual_exit_qty,
                        "product": prod,
                        "trans_type": trans_type
                    }
                    # Automatically cancel open stop-loss orders to eliminate dangling short exposure
                    try:
                        cancelled_sl = cancel_symbol_stop_loss(target_pos["symbol"], broker=target_pos["broker"])
                        if cancelled_sl:
                            res_dict["cancelled_sl_orders"] = cancelled_sl
                    except Exception:
                        pass

                    log_executed_order({
                        "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
                        "action": "EXIT",
                        **res_dict
                    })
                    return True, res_dict
                errors = data.get("errors", [])
                err = errors[0].get("message") if errors else (data.get("message") or "Exit failed")
                return False, f"Upstox error: {err}"
        except urllib.error.HTTPError as he:
            try:
                err_data = json.loads(he.read().decode())
                errors = err_data.get("errors", [])
                err = errors[0].get("message") if errors else (err_data.get("message") or str(he))
                return False, f"Upstox HTTP {he.code}: {err}"
            except Exception:
                return False, f"Upstox HTTP {he.code}: {he.reason}"
        except Exception as e:
            return False, f"Upstox exit error: {str(e)}"

    return False, f"Unsupported broker: {b}"


# ---------------------------------------------------------
# Trailing Stop-Loss & Risk Breakeven Recommendation Engine
# ---------------------------------------------------------
def get_open_trades_from_logs():
    """
    Reads open trades from orders_log.json, Journal.xlsx, and TradeTrackerPro.xlsx.
    Returns: dict keyed by uppercase symbol with trade metadata (entry, sl, target, qty, date, etc.)
    """
    logged_trades = {}

    # 1. Check orders_log.json
    if ORDERS_LOG_FILE.is_file():
        try:
            with open(ORDERS_LOG_FILE, "r", encoding="utf-8") as f:
                orders = json.load(f)
            for o in orders:
                sym = str(o.get("symbol", "")).upper()
                action = str(o.get("action", "")).upper()
                status = str(o.get("status", "")).upper()
                if not sym or status not in ("PLACED", "SUBMITTED"):
                    continue
                if action == "BUY":
                    logged_trades[sym] = {
                        "source": "orders_log.json",
                        "symbol": sym,
                        "broker": o.get("broker", "UNKNOWN"),
                        "product": o.get("product", "MTF"),
                        "entry_price": float(o.get("ltp", 0) or 0),
                        "stop_loss": float(o.get("stop_loss", 0) or 0),
                        "qty": int(o.get("quantity", 0) or 0),
                        "timestamp": o.get("timestamp", ""),
                        "mode": o.get("mode", "MODERATE")
                    }
                elif action == "EXIT":
                    if sym in logged_trades:
                        rem_qty = o.get("remaining_qty", 0)
                        if rem_qty <= 0:
                            logged_trades.pop(sym, None)
                        else:
                            logged_trades[sym]["qty"] = rem_qty
        except Exception as e:
            print(f"Notice reading orders_log.json: {e}")

    # 2. Check active Journal.xlsx
    for x_path in [SCRIPT_DIR / "Journal.xlsx"]:
        if not x_path.is_file():
            continue
        try:
            import openpyxl
            wb = openpyxl.load_workbook(x_path, data_only=True)
            if "Trade Journal" in wb.sheetnames:
                ws = wb["Trade Journal"]
                for r in list(ws.iter_rows(values_only=True))[1:]:
                    if not r or len(r) < 11:
                        continue
                    sym = str(r[2] or "").strip().upper()
                    status = str(r[10] or "").upper()
                    exit_p = r[8]
                    if sym and "CLOSED" not in status and (exit_p is None or exit_p == 0 or exit_p == ""):
                        entry_p = float(r[4] or 0)
                        sl_p = float(r[5] or 0)
                        target_p = float(r[6] or 0)
                        qty = int(float(r[7] or 0))
                        logged_trades[sym] = {
                            "source": x_path.name,
                            "symbol": sym,
                            "broker": "JOURNAL",
                            "product": "SWING",
                            "entry_price": entry_p,
                            "stop_loss": sl_p,
                            "target": target_p,
                            "qty": qty,
                            "date": str(r[1] or ""),
                            "status": status
                        }
        except Exception:
            pass

    # 3. Check tracked_holdings.json
    tracked_file = SCRIPT_DIR / "tracked_holdings.json"
    if tracked_file.is_file():
        try:
            with open(tracked_file, "r", encoding="utf-8") as f:
                th_data = json.load(f)
            for sym, meta in th_data.items():
                sym_u = sym.strip().upper()
                if sym_u not in logged_trades:
                    logged_trades[sym_u] = {
                        "source": "tracked_holdings.json",
                        "symbol": sym_u,
                        "broker": meta.get("broker", "UNKNOWN"),
                        "product": "CNC",
                        "stop_loss": float(meta.get("sl", 0) or 0),
                        "target": float(meta.get("target", 0) or 0),
                        "notes": meta.get("notes", "")
                    }
                else:
                    if not logged_trades[sym_u].get("stop_loss") and meta.get("sl"):
                        logged_trades[sym_u]["stop_loss"] = float(meta["sl"])
                    if not logged_trades[sym_u].get("target") and meta.get("target"):
                        logged_trades[sym_u]["target"] = float(meta["target"])
        except Exception:
            pass

    return logged_trades


_DAILY_EMA_ATR_CACHE = {}  # (symbol, date_str) -> dict


def get_daily_emas_and_atr(symbol, token=None):
    """
    Fetches daily candle history from Upstox and computes:
    - 10 EMA (Jeff Sun short-term momentum trailing guide)
    - 20 EMA (Secondary trend baseline)
    - 50 SMA (Institutional structural trend)
    - ATR 14 (Average True Range daily volatility)
    """
    sym = (symbol or "").strip().upper()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    cache_key = (sym, today_iso)
    if cache_key in _DAILY_EMA_ATR_CACHE:
        return _DAILY_EMA_ATR_CACHE[cache_key]

    res = {
        "ema10": None,
        "ema20": None,
        "sma50": None,
        "atr14": None
    }

    try:
        if not token:
            cfg = load_config()
            token = cfg.get("upstox", {}).get("access_token", "").strip()
        if not token:
            return res

        from upstox_tablet_scanner import get_instrument_key
        inst_key = get_instrument_key(sym)
        if not inst_key or not (inst_key.startswith("NSE_EQ|") or inst_key.startswith("NSE_INDEX|")):
            return res

        encoded = urllib.parse.quote(inst_key)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        from_str = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        url = f"https://api.upstox.com/v2/historical-candle/{encoded}/day/{today_iso}/{from_str}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as resp:
            d = json.loads(resp.read().decode("utf-8"))

        raw_candles = d.get("data", {}).get("candles", [])
        if raw_candles:
            chronological = list(reversed(raw_candles))
            closes = [float(c[4]) for c in chronological]

            def _calc_ema(vals, period):
                if not vals:
                    return None
                if len(vals) < period:
                    return vals[-1]
                k = 2.0 / (period + 1.0)
                e = sum(vals[:period]) / period
                for v in vals[period:]:
                    e = (v * k) + (e * (1.0 - k))
                return e

            ema10 = _calc_ema(closes, 10)
            ema20 = _calc_ema(closes, 20)
            sma50 = sum(closes[-50:]) / min(len(closes), 50) if closes else None

            trs = []
            for i in range(1, len(chronological)):
                h = float(chronological[i][2])
                l = float(chronological[i][3])
                pc = float(chronological[i-1][4])
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            atr14 = sum(trs[-14:]) / min(len(trs), 14) if trs else None

            res["ema10"] = round(ema10, 2) if ema10 is not None else None
            res["ema20"] = round(ema20, 2) if ema20 is not None else None
            res["sma50"] = round(sma50, 2) if sma50 is not None else None
            res["atr14"] = round(atr14, 2) if atr14 is not None else None

            _DAILY_EMA_ATR_CACHE[cache_key] = res
    except Exception:
        pass

    return res


def ratchet_stop_loss_to_breakeven(broker, symbol, quantity, entry_price, product="MTF", instrument_key=None):
    """
    Jeff Sun Trailing Automation:
    Ratchets the Stop-Loss up to Breakeven (+0.15% fee buffer) on the live broker.
    1. Cancels any existing lower stop-loss order.
    2. Submits new Stop-Loss limit order at breakeven price.
    3. Logs update in orders_log.json.
    """
    sym = (symbol or "").strip().upper()
    b = (broker or "").strip().lower()

    # Calculate Breakeven SL with tick size ₹0.05
    raw_be = entry_price * 1.0015
    breakeven_sl = round(round(raw_be / 0.05) * 0.05, 2)

    # Pre-Flight Guard: Check Live Quote to ensure LTP > breakeven_sl
    # (Mandatory Indian exchange rule: Sell Stop-Loss orders require Trigger Price < current LTP)
    q, _ = fetch_live_quote(sym)
    current_ltp = float(q.get("ltp", 0) or 0) if q else 0
    if current_ltp > 0 and current_ltp <= breakeven_sl:
        return False, {
            "status": "failed",
            "message": f"Cannot ratchet {sym} to Breakeven ₹{breakeven_sl:,.2f}: Current LTP (₹{current_ltp:,.2f}) is at or below Breakeven. Exchange rules require Trigger Price < LTP for Sell Stop-Loss orders.",
            "breakeven_sl": breakeven_sl,
            "current_ltp": current_ltp
        }

    # Step 1: Query live pending SL order on broker (GTT or regular)
    existing_sl = get_pending_stop_loss_order(sym, broker=b)
    ok = False
    res = None
    atomic_success = False

    if existing_sl:
        old_oid = existing_sl["order_id"]
        is_gtt = existing_sl.get("is_gtt", False)
        if is_gtt:
            # Atomically modify existing permanent GTT trigger directly
            mod_ok, mod_res = modify_broker_gtt_stop_loss(
                broker=b,
                order_id=old_oid,
                quantity=quantity,
                new_sl_price=breakeven_sl,
                symbol=sym,
                transaction_type="SELL",
                product=product
            )
            if mod_ok:
                ok = True
                atomic_success = True
                res = {"status": "success", "mode": "ATOMIC_GTT_MODIFY", "order_id": old_oid, "sl_price": breakeven_sl}
        else:
            # Modify regular exchange order
            mod_ok, mod_res = modify_broker_stop_loss(b, old_oid, quantity, breakeven_sl, transaction_type="SELL")
            if mod_ok:
                ok = True
                atomic_success = True
                res = {"status": "success", "mode": "ATOMIC_MODIFY", "order_id": old_oid, "sl_price": breakeven_sl}
            else:
                cancel_broker_order(b, old_oid)
                time.sleep(0.6)

    if not ok:
        # Step 2: Fresh GTT placement (preferred permanent 1-year stop-loss)
        place_ok, place_res = place_broker_gtt_stop_loss(
            broker=b,
            symbol=sym,
            quantity=quantity,
            sl_price=breakeven_sl,
            instrument_key=instrument_key,
            product=product,
            transaction_type="SELL"
        )
        if not place_ok:
            # Fall back to regular DAY stop-loss order if GTT placement is rejected
            place_ok, place_res = place_broker_stop_loss(
                broker=b,
                symbol=sym,
                quantity=quantity,
                sl_price=breakeven_sl,
                instrument_key=instrument_key,
                product=product,
                transaction_type="SELL"
            )
        ok = place_ok
        res = {"status": "success" if place_ok else "failed", "mode": "GTT_PLACE", "order_id": place_res if place_ok else None, "error": place_res if not place_ok else None, "sl_price": breakeven_sl}

    # Step 3: Update orders_log.json
    try:
        log_f = SCRIPT_DIR / "orders_log.json"
        if log_f.is_file():
            with open(log_f, "r", encoding="utf-8") as f:
                logs = json.load(f)
            updated = False
            for entry in reversed(logs):
                if entry.get("symbol", "").upper() == sym:
                    entry["breakeven_ratcheted"] = True
                    entry["stop_loss"] = breakeven_sl
                    entry["ratcheted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if ok:
                        oid = res.get("order_id") if isinstance(res, dict) else str(res)
                        if oid:
                            entry["sl_order_id"] = oid
                            entry["sl_status"] = "PENDING"
                    updated = True
                    break
            if updated:
                with open(log_f, "w", encoding="utf-8") as f:
                    json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"Notice updating orders_log: {e}")

    # Step 4: Update tracked_holdings.json if position is tracked
    if ok:
        try:
            th_f = SCRIPT_DIR / "tracked_holdings.json"
            if th_f.is_file():
                with open(th_f, "r", encoding="utf-8") as f:
                    th = json.load(f)
                if sym in th:
                    th[sym]["sl"] = breakeven_sl
                    mode_str = "Atomic Modify" if atomic_success else "Fresh SL"
                    oid_str = res.get("order_id", "N/A") if isinstance(res, dict) else str(res)
                    th[sym]["notes"] = f"{th[sym].get('broker', b.upper())} Holding | Breakeven Trailed ({mode_str} {oid_str})"
                    with open(th_f, "w", encoding="utf-8") as f:
                        json.dump(th, f, indent=2)
        except Exception as e:
            print(f"Notice updating tracked_holdings: {e}")

    return ok, {
        "status": "success" if ok else "failed",
        "symbol": sym,
        "entry_price": entry_price,
        "breakeven_sl": breakeven_sl,
        "broker": broker,
        "mode": "ATOMIC_MODIFY" if atomic_success else "FRESH_PLACE",
        "details": res
    }


def rearm_overnight_stop_losses(notify=True, force=False):
    """
    P0 GTT Permanent Stop-Loss Protection Engine:
    Reconciles all open positional trades against permanent 1-year GTT triggers
    (Zerodha GTT, Dhan Forever Orders, Upstox v3 GTT).
    GTT orders do NOT expire at 15:30 IST and remain active 24/7/365.
    If any open position lacks an active GTT order, automatically submits
    a fresh GTT Stop-Loss directly to the broker (can be done anytime, even when market is closed!).
    Eliminates frantic pre-market and market-open order placement activity!

    If market is closed and force=False, performs an audit report without submitting live orders
    (since Indian exchanges reject STOP_LOSS orders as AMO).
    Sends formatted notification card to Telegram Topics 'orders' and 'risk_trailing'.
    """
    market_open = is_market_open()
    all_pos, totals, broker_status = fetch_all_positions()

    tracked_holdings = {}
    try:
        th_f = SCRIPT_DIR / "tracked_holdings.json"
        if th_f.is_file():
            with open(th_f, "r", encoding="utf-8") as f:
                tracked_holdings = json.load(f)
    except Exception:
        pass

    orders_log = []
    try:
        ol_f = SCRIPT_DIR / "orders_log.json"
        if ol_f.is_file():
            with open(ol_f, "r", encoding="utf-8") as f:
                orders_log = json.load(f)
    except Exception:
        pass

    rearmed = []
    already_protected = []
    critical_alerts = []
    failed = []
    audit_only = []

    now_str = get_ist_now().strftime("%d %b %Y, %H:%M:%S IST")

    cfg_rearm = load_config()
    ignored_symbols_rearm = set(s.upper() for s in cfg_rearm.get("ignored_symbols", ["MOTHERSON"]))
    for p in all_pos:
        sym = p["symbol"].upper()
        if sym in ignored_symbols_rearm:
            continue
        broker = p.get("broker", "DHAN").upper()
        qty = int(p.get("qty", 0))
        if qty == 0:
            continue
        is_short = qty < 0
        abs_qty = abs(qty)
        avg_p = float(p.get("avg_price", 0) or 0)
        ltp = float(p.get("ltp", avg_p) or avg_p)
        prod = p.get("product", "CNC" if broker == "ZERODHA" else "MTF")
        tx_type = "SELL" if not is_short else "BUY"

        # Check if already has an active pending Stop-Loss order on broker
        pending_sl = get_pending_stop_loss_order(sym, broker=broker)
        if pending_sl:
            already_protected.append({
                "symbol": sym,
                "broker": broker,
                "qty": pending_sl.get("quantity", abs_qty),
                "sl": pending_sl.get("trigger_price", 0.0),
                "order_id": pending_sl.get("order_id", "N/A"),
                "status": pending_sl.get("status", "PENDING")
            })
            continue

        # Determine target SL
        target_sl = 0.0
        source_desc = "Structural"
        if sym in tracked_holdings and tracked_holdings[sym].get("sl"):
            target_sl = float(tracked_holdings[sym]["sl"])
            source_desc = "Tracked Holdings"
        if target_sl <= 0:
            for o in reversed(orders_log):
                if o.get("symbol", "").upper() == sym and float(o.get("stop_loss", 0) or 0) > 0:
                    target_sl = float(o["stop_loss"])
                    source_desc = "Orders Log"
                    break
        if target_sl <= 0 and avg_p > 0:
            if is_short:
                target_sl = round(avg_p * 1.025, 2)
            else:
                target_sl = round(avg_p * 0.975, 2)
            source_desc = "Default 2.5% SL"

        target_sl = round_to_tick(target_sl)

        # Pre-flight exchange rule validation against current LTP:
        if not is_short and ltp > 0 and ltp <= target_sl:
            critical_alerts.append({
                "symbol": sym,
                "broker": broker,
                "qty": abs_qty,
                "ltp": ltp,
                "target_sl": target_sl,
                "reason": f"LTP (₹{ltp:,.2f}) <= SL Trigger (₹{target_sl:,.2f}). Position is underwater past Stop-Loss!"
            })
            continue
        elif is_short and ltp > 0 and ltp >= target_sl:
            critical_alerts.append({
                "symbol": sym,
                "broker": broker,
                "qty": abs_qty,
                "ltp": ltp,
                "target_sl": target_sl,
                "reason": f"LTP (₹{ltp:,.2f}) >= SL Trigger (₹{target_sl:,.2f}). Short position is underwater past Stop-Loss!"
            })
            continue

        # GTT Advantage: GTT/Forever orders can be submitted 24/7 even when market is closed!
        # Place fresh GTT Stop-Loss directly on broker (valid for 1 year)
        ok, res = place_broker_gtt_stop_loss(
            broker=broker,
            symbol=sym,
            quantity=abs_qty,
            sl_price=target_sl,
            product=prod,
            transaction_type=tx_type
        )
        if not ok and market_open:
            # Fallback to regular SL order only during market hours
            ok, res = place_broker_stop_loss(
                broker=broker,
                symbol=sym,
                quantity=abs_qty,
                sl_price=target_sl,
                product=prod,
                transaction_type=tx_type
            )

        if ok:
            new_oid = str(res)
            rearmed.append({
                "symbol": sym,
                "broker": broker,
                "qty": abs_qty,
                "sl": target_sl,
                "order_id": new_oid,
                "source": source_desc
            })
            # Update orders_log.json
            try:
                ol_f = SCRIPT_DIR / "orders_log.json"
                if ol_f.is_file():
                    with open(ol_f, "r", encoding="utf-8") as f:
                        logs = json.load(f)
                else:
                    logs = []
                logs.append({
                    "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
                    "symbol": sym,
                    "broker": broker,
                    "product": prod,
                    "action": tx_type,
                    "quantity": abs_qty,
                    "ltp": ltp,
                    "exposure": round(abs_qty * ltp, 2),
                    "stop_loss": target_sl,
                    "sl_order_id": new_oid,
                    "sl_status": "PENDING",
                    "status": "REARMED",
                    "notes": f"Overnight Auto-Rearm ({source_desc})"
                })
                with open(ol_f, "w", encoding="utf-8") as f:
                    json.dump(logs, f, indent=2)
            except Exception as e:
                print(f"Notice updating orders_log on rearm: {e}")

            # Update tracked_holdings.json
            try:
                th_f = SCRIPT_DIR / "tracked_holdings.json"
                if th_f.is_file():
                    with open(th_f, "r", encoding="utf-8") as f:
                        th_data = json.load(f)
                else:
                    th_data = {}
                if sym not in th_data:
                    th_data[sym] = {"broker": broker}
                th_data[sym]["sl"] = target_sl
                th_data[sym]["notes"] = f"{broker} Holding | Rearmed Overnight SL (Order {new_oid})"
                with open(th_f, "w", encoding="utf-8") as f:
                    json.dump(th_data, f, indent=2)
            except Exception as e:
                print(f"Notice updating tracked_holdings on rearm: {e}")
        else:
            failed.append({
                "symbol": sym,
                "broker": broker,
                "qty": abs_qty,
                "target_sl": target_sl,
                "error": str(res)
            })

    # Build report card
    lines = [
        "🛡️ <b>JARVIS GTT STOP-LOSS PROTECTION AUDIT</b>",
        f"📅 <i>{now_str}</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ <b>Architecture: Permanent 1-Year GTT / Forever Orders</b>",
        "<i>Orders remain active 24/7 on broker cloud servers. Zero daily 15:30 expiration!</i>\n"
    ]

    if rearmed:
        lines.append(f"🔄 <b>Newly Placed Permanent GTT Orders ({len(rearmed)}):</b>")
        for r in rearmed:
            lines.append(f"• <b>{r['symbol']}</b> ({r['broker']}): Qty {r['qty']} @ SL ₹{r['sl']:,.2f} | GTT ID <code>{r['order_id']}</code> (<i>{r['source']}</i>)")
        lines.append("")

    if already_protected:
        lines.append(f"✅ <b>Already Protected (1-Year GTT Active) ({len(already_protected)}):</b>")
        for ap in already_protected:
            lines.append(f"• <b>{ap['symbol']}</b> ({ap['broker']}): Qty {ap['qty']} @ SL ₹{ap['sl']:,.2f} | GTT ID <code>{ap['order_id']}</code> (<i>Active 1-Year GTT</i>)")
        lines.append("")

    if critical_alerts:
        lines.append(f"🚨 <b>CRITICAL ALERTS — UNDERWATER ({len(critical_alerts)}):</b>")
        for ca in critical_alerts:
            lines.append(f"• <b>{ca['symbol']}</b> ({ca['broker']}): {ca['reason']}")
        lines.append("")

    if failed:
        lines.append(f"❌ <b>Placement Failed ({len(failed)}):</b>")
        for fld in failed:
            lines.append(f"• <b>{fld['symbol']}</b> ({fld['broker']}): ⚠️ {fld['error']}")
        lines.append("")

    if not rearmed and not audit_only and not already_protected and not failed and not critical_alerts:
        lines.append("💤 <b>No open swing positions detected across all configured brokers.</b>")
    else:
        tot_protected = len(rearmed) + len(already_protected)
        tot_positions = len(all_pos)
        lines.append(f"💼 <b>Total Positions:</b> {tot_positions} | <b>Protected:</b> {tot_protected} | <b>Pending Open:</b> {len(audit_only)}")

    report_text = "\n".join(lines)

    if notify:
        try:
            from telegram_bot import send_topic_alert
            send_topic_alert("orders", report_text)
            send_topic_alert("risk_trailing", report_text)
        except Exception as e:
            print(f"Notice: Failed to dispatch rearm card to Telegram: {e}")

    return {
        "status": "success",
        "market_open": market_open,
        "rearmed": rearmed,
        "audit_only": audit_only,
        "already_protected": already_protected,
        "critical_alerts": critical_alerts,
        "failed": failed,
        "report_text": report_text
    }


def get_all_open_positions_with_trailing_sl():
    """
    Consolidates ALL open positions across live brokers (Dhan, Zerodha, Upstox)
    and trade logs/journals, evaluating Trailing Stop-Loss & Risk Breakeven recommendations.
    Returns: list of enriched position dicts.
    """
    live_pos, totals, broker_status = fetch_all_positions()
    logged_trades = get_open_trades_from_logs()

    seen_symbols = set()
    enriched = []

    # 1. Process Live Broker Positions first
    for p in live_pos:
        sym = p["symbol"].upper()
        seen_symbols.add(sym)

        entry_p = float(p.get("avg_price", 0) or 0)
        ltp = float(p.get("ltp", 0) or entry_p)
        qty = int(p.get("qty", 0) or 0)
        pnl = float(p.get("pnl", 0) or 0)
        pnl_pct = float(p.get("pnl_pct", 0) or 0)
        broker = p.get("broker", "UNKNOWN")
        product = p.get("product", "MTF")

        # Check if trade log has initial SL or target
        log_meta = logged_trades.get(sym, {})
        initial_sl = float(log_meta.get("stop_loss", 0) or 0)
        target_p = float(log_meta.get("target", 0) or 0)

        # If initial SL not logged, derive structural SL from quote Day Low or 2.5% default
        if initial_sl <= 0 and entry_p > 0:
            if "CE" in sym or "PE" in sym or "NIFTY" in sym:
                initial_sl = round(entry_p * 0.70, 2)
            else:
                q, _ = fetch_live_quote(sym)
                dl = float(q.get("day_low", 0) or 0) if q else 0
                if 0 < dl < entry_p and ((entry_p - dl) / entry_p) <= 0.05:
                    initial_sl = round(dl, 2)
                else:
                    initial_sl = round(entry_p * 0.975, 2)

        if target_p <= 0 and entry_p > 0 and initial_sl > 0:
            target_p = round(entry_p + abs(entry_p - initial_sl) * 2.0, 2)

        risk_per_share = max(0.10, abs(entry_p - initial_sl)) if entry_p > 0 and initial_sl > 0 else 1.0
        r_multiple = round((ltp - entry_p) / risk_per_share, 2) if risk_per_share > 0 else 0.0
        dist_to_sl_pct = round(((ltp - initial_sl) / ltp) * 100, 2) if ltp > 0 and initial_sl > 0 else 99.0

        # Determine recommended trailing stop loss
        is_option = "CE" in sym or "PE" in sym or "NIFTY" in sym
        if is_option:
            if pnl_pct >= 100.0:
                recommended_sl = round(entry_p * 2.0, 2)
                action_badge = "⭐ BOOK 50% & TRAIL"
                action_text = f"Huge option gain (+{pnl_pct:.1f}%)! Book half and trail SL to ₹{recommended_sl:,.2f}"
            elif pnl_pct >= 40.0:
                recommended_sl = entry_p
                action_badge = "🟢 TRAIL TO COST"
                action_text = f"Solid gain (+{pnl_pct:.1f}%)! Trail SL to entry ₹{entry_p:,.2f} for risk-free trade"
            elif ltp <= initial_sl:
                recommended_sl = initial_sl
                action_badge = "🔴 EXIT — SL HIT"
                action_text = f"Option SL breached at ₹{initial_sl:,.2f}"
            else:
                recommended_sl = initial_sl
                action_badge = "✅ HOLD"
                action_text = f"Keep initial SL at ₹{initial_sl:,.2f}"
        else:
            if ltp <= initial_sl:
                recommended_sl = initial_sl
                action_badge = "🔴 EXIT — SL HIT"
                action_text = f"Stop-Loss breached! Market price ₹{ltp:,.2f} is below SL ₹{initial_sl:,.2f}"
            elif dist_to_sl_pct <= 1.0:
                recommended_sl = initial_sl
                action_badge = "🟡 DANGER — NEAR SL"
                action_text = f"Danger! Price is only {dist_to_sl_pct:.1f}% away from SL ₹{initial_sl:,.2f}"
            elif r_multiple >= 3.0 or pnl_pct >= 6.0:
                recommended_sl = round(entry_p + (risk_per_share * 1.5), 2)
                action_badge = "⭐ BOOK 50% & TRAIL"
                action_text = f"Up +{r_multiple:.1f}R! Book 50% partial profit and trail SL to ₹{recommended_sl:,.2f} (+1.5R)"
            elif r_multiple >= 1.8 or pnl_pct >= 3.0:
                recommended_sl = entry_p
                action_badge = "🟢 TRAIL TO COST"
                action_text = f"Up +{r_multiple:.1f}R (+{pnl_pct:.1f}%)! Move SL to Breakeven ₹{entry_p:,.2f} (Risk-Free!)"
            elif r_multiple >= 1.0 or pnl_pct >= 1.5:
                recommended_sl = round(entry_p - (risk_per_share * 0.5), 2)
                action_badge = "🔵 CUT RISK 50%"
                action_text = f"Up +{r_multiple:.1f}R. Trail SL up to ₹{recommended_sl:,.2f} to cut max risk by 50%"
            else:
                recommended_sl = initial_sl
                action_badge = "✅ HOLD — ON TRACK"
                action_text = f"Position healthy. Keep stop at ₹{initial_sl:,.2f} (Target: ₹{target_p:,.2f})"

        # Jeff Sun 10 EMA & 20 EMA Trailing Telemetry
        ema_info = get_daily_emas_and_atr(sym)
        ema10 = ema_info.get("ema10")
        ema20 = ema_info.get("ema20")
        sma50 = ema_info.get("sma50")
        atr14 = ema_info.get("atr14")

        dist_ema10_pct = round(((ltp - ema10) / ema10) * 100.0, 2) if ema10 and ltp else None
        dist_ema20_pct = round(((ltp - ema20) / ema20) * 100.0, 2) if ema20 and ltp else None
        atr_stretch = round((ltp - sma50) / atr14, 1) if sma50 and atr14 and atr14 > 0 and ltp else None

        jeff_badge = action_badge
        jeff_status = action_text

        if not is_option and ema10 and ltp:
            if ltp >= ema10:
                jeff_badge = "🟢 RIDE 10 EMA"
                jeff_status = f"Trending strong above 10 EMA (+{dist_ema10_pct:.1f}% buffer). Hold runner!"
            elif ema20 and ltp >= ema20:
                jeff_badge = "🟡 CAUTION — BELOW 10 EMA"
                jeff_status = f"Below 10 EMA ({dist_ema10_pct:.1f}%). Holding 20 EMA — Watch next-day 5m ORL!"
            else:
                jeff_badge = "🔴 EXIT WARNING"
                jeff_status = f"Trend broken below 10 & 20 EMA ({dist_ema10_pct:.1f}%). Prepare to exit on ORL undercut!"

            if atr_stretch and atr_stretch >= 3.0:
                jeff_status += f" | ⚠️ Extended (+{atr_stretch}x ATR from 50MA) — Tighten trail!"

        is_short = qty < 0
        raw_be = entry_p * (0.9985 if is_short else 1.0015)
        breakeven_p = round(round(raw_be / 0.05) * 0.05, 2)
        if not is_option and (r_multiple >= 1.5 or pnl_pct >= 2.5):
            if is_short:
                recommended_sl = min(recommended_sl, breakeven_p) if recommended_sl > 0 else breakeven_p
            else:
                recommended_sl = max(recommended_sl, breakeven_p)
            if "HOLD" in action_badge:
                action_badge = "🟢 TRAIL TO BREAKEVEN"
                action_text = f"Target milestone (+{r_multiple:.1f}R)! Move SL to Breakeven ₹{breakeven_p:,.2f} (Risk-Free!)"

        # Value at Risk (Current SL vs Recommended SL)
        if is_short:
            if initial_sl <= entry_p and initial_sl > 0:
                var_inr = 0.0
                var_pct = 0.0
            else:
                var_inr = max(0.0, round((initial_sl - entry_p) * abs(qty), 2)) if entry_p > 0 else 0.0
                var_pct = round(((initial_sl - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0

            if recommended_sl <= entry_p and recommended_sl > 0:
                rec_var_inr = 0.0
                rec_var_pct = 0.0
            else:
                rec_var_inr = max(0.0, round((recommended_sl - entry_p) * abs(qty), 2)) if entry_p > 0 else 0.0
                rec_var_pct = round(((recommended_sl - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
        else:
            if initial_sl >= entry_p and entry_p > 0:
                var_inr = 0.0
                var_pct = 0.0
            else:
                var_inr = max(0.0, round((entry_p - initial_sl) * qty, 2)) if entry_p > 0 else 0.0
                var_pct = round(((entry_p - initial_sl) / entry_p) * 100, 2) if entry_p > 0 else 0.0

            if recommended_sl >= entry_p and entry_p > 0:
                rec_var_inr = 0.0
                rec_var_pct = 0.0
            else:
                rec_var_inr = max(0.0, round((entry_p - recommended_sl) * qty, 2)) if entry_p > 0 else 0.0
                rec_var_pct = round(((entry_p - recommended_sl) / entry_p) * 100, 2) if entry_p > 0 else 0.0

        enriched.append({
            "symbol": sym,
            "broker": broker,
            "product": product,
            "source": "LIVE BROKER",
            "qty": qty,
            "entry_price": entry_p,
            "ltp": ltp,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "initial_sl": initial_sl,
            "target": target_p,
            "recommended_sl": recommended_sl,
            "breakeven_sl": breakeven_p,
            "value_at_risk": var_inr,
            "var_pct": var_pct,
            "rec_value_at_risk": rec_var_inr,
            "rec_var_pct": rec_var_pct,
            "is_risk_free": bool(var_inr <= 0),
            "r_multiple": r_multiple,
            "dist_to_sl_pct": dist_to_sl_pct,
            "action_badge": action_badge,
            "action_text": action_text,
            "ema10": ema10,
            "ema20": ema20,
            "sma50": sma50,
            "atr14": atr14,
            "dist_ema10_pct": dist_ema10_pct,
            "dist_ema20_pct": dist_ema20_pct,
            "atr_stretch": atr_stretch,
            "jeff_badge": jeff_badge,
            "jeff_status": jeff_status
        })

    # 2. Process any logged trades that are NOT already in live broker accounts
    for sym, log_item in logged_trades.items():
        if sym in seen_symbols:
            continue
        entry_p = float(log_item.get("entry_price", 0) or 0)
        qty = int(log_item.get("qty", 0) or 0)
        initial_sl = float(log_item.get("stop_loss", 0) or 0)
        target_p = float(log_item.get("target", 0) or 0)
        if entry_p <= 0 or qty <= 0:
            continue

        q, _ = fetch_live_quote(sym)
        ltp = float(q.get("ltp", 0) or entry_p) if q else entry_p
        pnl = round((ltp - entry_p) * qty, 2)
        pnl_pct = round(((ltp - entry_p) / entry_p) * 100, 2)

        if initial_sl <= 0:
            initial_sl = round(entry_p * 0.975, 2)
        if target_p <= 0:
            target_p = round(entry_p + abs(entry_p - initial_sl) * 2.0, 2)

        risk_per_share = max(0.10, abs(entry_p - initial_sl))
        r_multiple = round((ltp - entry_p) / risk_per_share, 2)
        dist_to_sl_pct = round(((ltp - initial_sl) / ltp) * 100, 2) if ltp > 0 else 99.0

        if ltp <= initial_sl:
            recommended_sl = initial_sl
            action_badge = "🔴 EXIT — SL HIT"
            action_text = f"Stop-Loss breached! Market price ₹{ltp:,.2f} is below SL ₹{initial_sl:,.2f}"
        elif dist_to_sl_pct <= 1.0:
            recommended_sl = initial_sl
            action_badge = "🟡 DANGER — NEAR SL"
            action_text = f"Danger! Price is only {dist_to_sl_pct:.1f}% away from SL ₹{initial_sl:,.2f}"
        elif r_multiple >= 3.0 or pnl_pct >= 6.0:
            recommended_sl = round(entry_p + (risk_per_share * 1.5), 2)
            action_badge = "⭐ BOOK 50% & TRAIL"
            action_text = f"Up +{r_multiple:.1f}R! Book 50% partial profit and trail SL to ₹{recommended_sl:,.2f}"
        elif r_multiple >= 1.8 or pnl_pct >= 3.0:
            recommended_sl = entry_p
            action_badge = "🟢 TRAIL TO COST"
            action_text = f"Up +{r_multiple:.1f}R! Move SL to Breakeven ₹{entry_p:,.2f} (Risk-Free!)"
        elif r_multiple >= 1.0 or pnl_pct >= 1.5:
            recommended_sl = round(entry_p - (risk_per_share * 0.5), 2)
            action_badge = "🔵 CUT RISK 50%"
            action_text = f"Up +{r_multiple:.1f}R. Trail SL up to ₹{recommended_sl:,.2f} to cut risk by 50%"
        else:
            recommended_sl = initial_sl
            action_badge = "✅ HOLD — ON TRACK"
            action_text = f"Position healthy. Keep stop at ₹{initial_sl:,.2f}"

        ema_info = get_daily_emas_and_atr(sym)
        ema10 = ema_info.get("ema10")
        ema20 = ema_info.get("ema20")
        sma50 = ema_info.get("sma50")
        atr14 = ema_info.get("atr14")

        dist_ema10_pct = round(((ltp - ema10) / ema10) * 100.0, 2) if ema10 and ltp else None
        dist_ema20_pct = round(((ltp - ema20) / ema20) * 100.0, 2) if ema20 and ltp else None
        atr_stretch = round((ltp - sma50) / atr14, 1) if sma50 and atr14 and atr14 > 0 and ltp else None

        jeff_badge = action_badge
        jeff_status = action_text

        if ema10 and ltp:
            if ltp >= ema10:
                jeff_badge = "🟢 RIDE 10 EMA"
                jeff_status = f"Trending strong above 10 EMA (+{dist_ema10_pct:.1f}% buffer). Hold runner!"
            elif ema20 and ltp >= ema20:
                jeff_badge = "🟡 CAUTION — BELOW 10 EMA"
                jeff_status = f"Below 10 EMA ({dist_ema10_pct:.1f}%). Holding 20 EMA — Watch next-day 5m ORL!"
            else:
                jeff_badge = "🔴 EXIT WARNING"
                jeff_status = f"Trend broken below 10 & 20 EMA ({dist_ema10_pct:.1f}%). Prepare to exit on ORL undercut!"

            if atr_stretch and atr_stretch >= 3.0:
                jeff_status += f" | ⚠️ Extended (+{atr_stretch}x ATR from 50MA) — Tighten trail!"

        raw_be = entry_p * 1.0015
        breakeven_p = round(round(raw_be / 0.05) * 0.05, 2)
        if r_multiple >= 1.5 or pnl_pct >= 2.5:
            recommended_sl = max(recommended_sl, breakeven_p)
            if "HOLD" in action_badge:
                action_badge = "🟢 TRAIL TO BREAKEVEN"
                action_text = f"Target milestone (+{r_multiple:.1f}R)! Move SL to Breakeven ₹{breakeven_p:,.2f} (Risk-Free!)"

        # Value at Risk (Current SL vs Recommended SL)
        if initial_sl >= entry_p:
            var_inr = 0.0
            var_pct = 0.0
        else:
            var_inr = round((entry_p - initial_sl) * qty, 2)
            var_pct = round(((entry_p - initial_sl) / entry_p) * 100, 2) if entry_p > 0 else 0.0

        if recommended_sl >= entry_p:
            rec_var_inr = 0.0
            rec_var_pct = 0.0
        else:
            rec_var_inr = round((entry_p - recommended_sl) * qty, 2)
            rec_var_pct = round(((entry_p - recommended_sl) / entry_p) * 100, 2) if entry_p > 0 else 0.0

        enriched.append({
            "symbol": sym,
            "broker": log_item.get("broker", "LOGGED"),
            "product": log_item.get("product", "LOG"),
            "source": log_item.get("source", "TRADE LOG"),
            "qty": qty,
            "entry_price": entry_p,
            "ltp": ltp,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "initial_sl": initial_sl,
            "target": target_p,
            "recommended_sl": recommended_sl,
            "breakeven_sl": breakeven_p,
            "value_at_risk": var_inr,
            "var_pct": var_pct,
            "rec_value_at_risk": rec_var_inr,
            "rec_var_pct": rec_var_pct,
            "is_risk_free": bool(var_inr <= 0),
            "r_multiple": r_multiple,
            "dist_to_sl_pct": dist_to_sl_pct,
            "action_badge": action_badge,
            "action_text": action_text,
            "ema10": ema10,
            "ema20": ema20,
            "sma50": sma50,
            "atr14": atr14,
            "dist_ema10_pct": dist_ema10_pct,
            "dist_ema20_pct": dist_ema20_pct,
            "atr_stretch": atr_stretch,
            "jeff_badge": jeff_badge,
            "jeff_status": jeff_status
        })

    return enriched


# ---------------------------------------------------------
# Multi-Broker Capital & Funds Management
# ---------------------------------------------------------
def fetch_broker_funds():
    """
    Queries live available cash and margin across Dhan, Upstox, and Zerodha.
    Returns:
        dict with broker breakdowns and combined totals.
    """
    cfg = load_config()
    funds = {
        "dhan": {"enabled": False, "available_cash": 0.0, "collateral": 0.0, "utilized": 0.0, "withdrawable": 0.0, "error": None},
        "upstox": {"enabled": False, "available_margin": 0.0, "used_margin": 0.0, "error": None},
        "zerodha": {"enabled": False, "available_cash": 0.0, "live_balance": 0.0, "collateral": 0.0, "utilized": 0.0, "error": None},
        "total_available_margin": 0.0
    }

    # 1. DhanHQ Margin & Funds
    dhan = cfg.get("dhan", {})
    d_token = dhan.get("access_token", "").strip()
    d_client = dhan.get("client_id", "").strip()
    if d_token and d_client:
        funds["dhan"]["enabled"] = True
        try:
            req = urllib.request.Request("https://api.dhan.co/v2/fundlimit", headers={
                "access-token": d_token,
                "client-id": d_client,
                "Accept": "application/json",
                "User-Agent": "Jarvis-Order-Engine"
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                avail = float(data.get("availabelBalance", 0) or data.get("availMargin", 0) or 0)
                funds["dhan"]["available_cash"] = round(avail, 2)
                funds["dhan"]["collateral"] = round(float(data.get("collateralAmount", 0) or 0), 2)
                funds["dhan"]["utilized"] = round(float(data.get("utilizedAmount", 0) or 0), 2)
                funds["dhan"]["withdrawable"] = round(float(data.get("withdrawableBalance", 0) or 0), 2)
                funds["total_available_margin"] += avail
        except Exception as e:
            funds["dhan"]["error"] = str(e)

    # 2. Upstox Pro Funds & Margin
    upstox = cfg.get("upstox", {})
    u_token = upstox.get("access_token", "").strip()
    if u_token:
        funds["upstox"]["enabled"] = True
        try:
            req = urllib.request.Request("https://api.upstox.com/v2/user/get-funds-and-margin", headers={
                "Authorization": f"Bearer {u_token}",
                "Accept": "application/json",
                "User-Agent": "Jarvis-Order-Engine"
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                eq = data.get("data", {}).get("equity", {})
                avail = float(eq.get("available_margin", 0) or 0)
                funds["upstox"]["available_margin"] = round(avail, 2)
                funds["upstox"]["used_margin"] = round(float(eq.get("used_margin", 0) or 0), 2)
                funds["total_available_margin"] += avail
        except Exception as e:
            funds["upstox"]["error"] = str(e)

    # 3. Zerodha Kite Funds & Margin
    zerodha = cfg.get("zerodha", {})
    z_key = zerodha.get("api_key", "").strip()
    z_token = zerodha.get("access_token", "").strip()
    if z_key and z_token:
        funds["zerodha"]["enabled"] = True
        try:
            req = urllib.request.Request("https://api.kite.trade/user/margins", headers={
                "Authorization": f"token {z_key}:{z_token}",
                "User-Agent": "Jarvis-Order-Engine"
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                eq = data.get("data", {}).get("equity", {})
                avail_data = eq.get("available", {})
                live_bal = float(avail_data.get("live_balance", 0) or avail_data.get("cash", 0) or 0)
                funds["zerodha"]["available_cash"] = round(float(avail_data.get("cash", 0) or 0), 2)
                funds["zerodha"]["live_balance"] = round(live_bal, 2)
                funds["zerodha"]["collateral"] = round(float(avail_data.get("collateral", 0) or 0), 2)
                funds["zerodha"]["utilized"] = round(float(eq.get("utilised", {}).get("debits", 0) or 0), 2)
                funds["total_available_margin"] += live_bal
        except Exception as e:
            funds["zerodha"]["error"] = str(e)

    funds["total_available_margin"] = round(funds["total_available_margin"], 2)
    return funds


if __name__ == "__main__":
    test_sym = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    b = sys.argv[2] if len(sys.argv) > 2 else get_default_broker()
    print(f"Testing quote and calculation for {test_sym} on {b.upper()}...")
    q, err = fetch_live_quote(test_sym)
    if err:
        print(f"❌ Error: {err}")
    else:
        print("✅ Quote received:", q)
        sizing = calculate_order_sizing(q, "agg", "lod")
        print("\n📊 Calculated Sizing:")
        for k, v in sizing.items():
            print(f"  {k}: {v}")
        if b == "dhan":
            sec_id = resolve_dhan_security_id(test_sym)
            print(f"  Dhan Security ID: {sec_id}")
