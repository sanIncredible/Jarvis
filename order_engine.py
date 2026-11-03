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
            "text": "✅ <b>Strong Start:</b> Confirmed (Held > Prev Close)",
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
            warnings.append(f"Volume: Low relative volume (RVOL {rvol:.2f}x < 1.0x).")

    # 6. Stop-Loss / LOD Risk Proximity
    if risk_pct is not None:
        if risk_pct <= 3.0:
            checklist.append({
                "rule": "Stop Distance",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Stop Distance:</b> {risk_pct:.1f}% (Tight Risk < 3%)",
                "detail": "Clean structural risk to Day Low"
            })
        elif risk_pct <= 4.0:
            checklist.append({
                "rule": "Stop Distance",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Stop Distance:</b> {risk_pct:.1f}% (Acceptable <= 4%)",
                "detail": "Reasonable distance to Day Low"
            })
        else:
            checklist.append({
                "rule": "Stop Distance",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Stop Distance:</b> {risk_pct:.1f}% (WIDE > 4.0% limit)",
                "detail": "Excessive distance to LOD stop-loss"
            })
            warnings.append(f"Wide Stop-Loss: Distance to Day Low is {risk_pct:.1f}% (> 4.0% optimal threshold). High drawdown risk.")

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
                "text": f"⚠️ <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Extended > 4.5%)",
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
                    if net_qty != 0:
                        sym = p.get("tradingSymbol", "UNKNOWN")
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
                    if net_qty != 0:
                        sym = p.get("trading_symbol", "UNKNOWN")
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
                    if net_qty != 0:
                        sym = p.get("tradingsymbol", "UNKNOWN")
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
        except Exception as e:
            broker_status["zerodha"] = f"Error ({e})"
    else:
        broker_status["zerodha"] = "Not configured"

    total_pnl = sum(p["pnl"] for p in all_pos)
    total_exposure = sum(p["exposure"] for p in all_pos)

    totals = {
        "count": len(all_pos),
        "total_pnl": round(total_pnl, 2),
        "total_exposure": round(total_exposure, 2)
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

    return logged_trades


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
            "r_multiple": r_multiple,
            "dist_to_sl_pct": dist_to_sl_pct,
            "action_badge": action_badge,
            "action_text": action_text
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
            "r_multiple": r_multiple,
            "dist_to_sl_pct": dist_to_sl_pct,
            "action_badge": action_badge,
            "action_text": action_text
        })

    return enriched


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
