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
TRADE_LOG_CSV = SCRIPT_DIR / "trade_log.csv"
TRADE_LOG_JSON = SCRIPT_DIR / "trade_log.json"
SERVER_IP = "80.225.210.222"

IST = timezone(timedelta(hours=5, minutes=30))


def round_to_clean_int(price):
    """Rounds price strictly to a whole integer (no decimal part) for Sell GTT, Limit, or Trail SL."""
    if price is None:
        return 0
    try:
        p = float(price)
        return int(round(p))
    except Exception:
        return 0


def round_to_tick(price, tick=1.0):
    """
    Rounds price strictly to a clean integer (no decimal part)
    per user strategy preference for all orders, GTT, Limit, and Trail orders.
    """
    return round_to_clean_int(price)


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
    Parses mode argument to exposure or risk target amount in INR.
    Defaults to Institutional Risk-Normalized Sizing (₹1,000 Risk Target).
    Supports 'r500', 'r1k', 'r2k', 'agg', 'mod', '1.5L', '1L', '50k', '75k', or raw numbers.
    """
    if not mode_arg:
        return 1000, "Risk-Normalized (₹1,000 Risk Target - Default)"

    m_clean = str(mode_arg).strip().lower().replace("₹", "").replace(",", "")

    # Risk-Normalized Modes (Fixed INR Risk) - Priority Default
    if m_clean in ("r1k", "risk1k", "1k", "1k_risk", "mod", "default"):
        return 1000, "Risk-Normalized (₹1,000 Risk Target - Default)"
    if m_clean in ("r500", "risk500", "500", "500_risk"):
        return 500, "Risk-Normalized (₹500 Risk Target)"
    if m_clean in ("r2k", "risk2k", "2k", "2k_risk"):
        return 2000, "Risk-Normalized (₹2,000 Risk Target)"

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
        return 1000, "Risk-Normalized (₹1,000 Risk Target - Default)"


def resolve_dhan_security_id(symbol, download_if_missing=False):
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

    # Instant lookup from pre-compiled Master Symbol Registry
    try:
        from master_registry import get_master_symbol
        m_info = get_master_symbol(sym_u)
        if m_info and m_info.get("dhan_id"):
            return m_info["dhan_id"]
    except Exception:
        pass

    if not download_if_missing:
        return None

    # Download Dhan scrip master CSV if not cached and explicitly requested
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

    # Fallback 2: Yahoo Finance API (supports both NSE .NS and BSE .BO tickers like NSE.BO)
    clean_s = symbol.upper().replace(".NS", "").replace("NSE:", "").replace(".BO", "").replace("BSE:", "")
    for suffix in [".NS", ".BO"]:
        try:
            yf_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_s}{suffix}?interval=1d&range=1d"
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
                        "source": f"Yahoo Finance ({clean_s}{suffix})"
                    }, None
        except Exception:
            continue
    return None, f"Quote fetch failed across all sources for {symbol}"

    return None, f"Could not retrieve quote for {symbol}"


_ON_DEMAND_SCANNER_CACHE = {}  # {symbol: (timestamp, data_dict)}
_ON_DEMAND_CACHE_TTL = 45  # 45 seconds cache to keep interactive preview switches instant


def get_symbol_scanner_data(symbol):
    """
    Retrieves 3m ORB, SS, PDH, and RVOL metrics from data.json if available.
    If the stock is not in data.json (non-watchlist stock e.g. /buy RIL agg),
    dynamically calculates live 3m ORB, PDH, 10 EMA stretch, RVOL, and NR
    using Upstox API v2 (or fallback) so the user gets the identical rich banner.
    """
    if not symbol:
        return None

    sym_u = resolve_symbol(symbol).strip().upper()

    # 1. Fast cache check from data.json (watchlist stocks)
    if DATA_FILE.is_file():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            for s in d.get("stocks", []):
                s_sym = resolve_symbol(s.get("symbol", "")).strip().upper()
                if s_sym == sym_u:
                    return s
        except Exception:
            pass

    # 2. In-memory TTL cache for recently fetched non-watchlist stocks (45s TTL)
    now_ts = time.time()
    cached = _ON_DEMAND_SCANNER_CACHE.get(sym_u)
    if cached and (now_ts - cached[0]) < _ON_DEMAND_CACHE_TTL:
        return cached[1]

    # 3. Dynamic on-demand calculation for non-watchlist stocks (e.g. /buy RIL agg)
    try:
        from upstox_tablet_scanner import (
            load_upstox_token,
            fetch_upstox_symbol_data,
            fetch_fallback_data,
            compute_metrics
        )
        token = load_upstox_token()
        raw_stk = None
        if token:
            try:
                raw_stk = fetch_upstox_symbol_data(sym_u, token)
            except Exception:
                pass

        if not raw_stk or not raw_stk.get("ltp"):
            raw_stk = fetch_fallback_data(sym_u)

        if raw_stk and raw_stk.get("ltp"):
            metrics = compute_metrics(raw_stk)
            full_data = dict(raw_stk)
            full_data.update(metrics)

            c_highs = [c["h"] for c in raw_stk.get("candles", []) if isinstance(c, dict) and "h" in c]
            if not full_data.get("day_high"):
                full_data["day_high"] = max(c_highs) if c_highs else (raw_stk.get("ltp") or 0.0)

            # Map fields explicitly expected by evaluate_strategy_checklist
            if metrics.get("is_reversal"):
                full_data["orb_status"] = "L➔H"
            else:
                full_data["orb_status"] = metrics.get("orb_status")

            full_data["is_ss"] = bool(raw_stk.get("is_strong_start", False))
            full_data["is_narrow_prev_day"] = bool(raw_stk.get("is_narrow_prev_day", False))
            full_data["prev_range_ratio"] = raw_stk.get("prev_range_ratio")
            full_data["is_inside_day"] = bool(raw_stk.get("is_inside_day", False))
            full_data["rvol"] = round(raw_stk["rvol"], 2) if raw_stk.get("rvol") is not None else None
            full_data["symbol"] = sym_u

            _ON_DEMAND_SCANNER_CACHE[sym_u] = (now_ts, full_data)
            return full_data
    except Exception as e:
        print(f"Dynamic scanner telemetry calculation note for {symbol}: {e}")

    return None


def get_active_holding_info(symbol):
    """Checks if symbol is in active tracked holdings / open positions for Pyramiding."""
    sym = symbol.strip().upper()
    th_file = SCRIPT_DIR / "tracked_holdings.json"
    if th_file.is_file():
        try:
            with open(th_file, "r", encoding="utf-8") as f:
                th = json.load(f)
                if sym in th:
                    return th[sym]
        except Exception:
            pass
    return None


# ---------------------------------------------------------
# Sector & Industry Theme Clustering Engine
# ---------------------------------------------------------
SECTOR_THEME_RULES = [
    ('Pharma & Healthcare', '💊', ['pharma', 'health', 'medic', 'biotech', 'hospital', 'drug', 'diagnost', 'vijaya', 'fdc', 'cohance', 'hcare']),
    ('Banking & Financials', '🏦', ['bank', 'financ', 'nbfc', 'brok', 'invest', 'insur', 'amc', 'wealth', 'fin', 'sgfin']),
    ('Auto & Ancillaries', '🚗', ['auto', 'motor', 'tyre', 'wheel', 'ancilar', 'vehicle', 'ev ']),
    ('Electronics & EMS', '🔌', ['ems', 'electronic', 'semiconduct', 'pcb', 'cyientdlm', 'centum']),
    ('Defence & Aerospace', '🛡️', ['defen', 'aerospace', 'ship build', 'missile', 'naval', 'rostech', 'unimech', 'marine']),
    ('Capital Goods & Industrial', '⚙️', ['capital goods', 'industrial', 'power equip', 'machin', 'electr', 'engineer']),
    ('IT & Software', '💻', ['software', 'information tech', 'it enabled', 'tech', 'data', 'cloud', 'digital', 'saas']),
    ('Metals & Mining', '⛏️', ['metal', 'mining', 'steel', 'iron', 'alumin', 'zinc', 'copper']),
    ('Realty & Infra', '🏗️', ['realty', 'real estate', 'construct', 'infra', 'cement', 'pipe', 'housing']),
    ('FMCG & Consumption', '🛒', ['fmcg', 'consumer', 'food', 'beverag', 'jewel', 'retail', 'hotel', 'dairy', 'sugar', 'restaur', 'brew', 'distill', 'personal care', 'westlife', 'cupid', 'e- commerce', 'timex']),
    ('Chemicals & Fertilisers', '🧪', ['chemic', 'fertili', 'agric', 'pest']),
    ('Energy & Power', '⚡', ['power', 'oil', 'gas', 'energy', 'solar', 'renew', 'refin']),
    ('Textiles & Apparel', '🧵', ['textil', 'apparel', 'garment', 'fashion', 'cotton', 'yarn', 'fabric']),
    ('Logistics & Shipping', '🚢', ['logistic', 'freight', 'transport', 'shipping', 'port', 'courier', 'shadowfax']),
    ('Media & Telecom', '📡', ['media', 'telecom', 'entertain', 'broadcasting', 'publish', 'network', 'cable']),
    ('Services & Commercial', '💼', ['services', 'commercial', 'staffing', 'quess', 'innovision', 'urbanco', 'enginersin'])
]

_SECTOR_LOOKUP_CACHE = {}

def resolve_sector_theme(symbol, industry=None, quote_data=None):
    """
    Resolves symbol to institutional Sector/Theme and emoji icon.
    Checks memory cache, candidate files, Nifty 500 constituents, and keyword rules.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"theme": "General Equities", "icon": "🏢"}
    if sym in _SECTOR_LOOKUP_CACHE and not industry:
        return _SECTOR_LOOKUP_CACHE[sym]

    ind_str = str(industry or "").strip().lower()
    tag_str = ""
    name_str = ""

    # Check quote_data or candidate lists if industry not passed
    if not ind_str:
        q = quote_data or {}
        ind_str = str(q.get("industry") or "").strip().lower()
        tag_str = str(q.get("sector_tag") or "").strip().lower()
        name_str = str(q.get("name") or "").strip().lower()

    if not ind_str:
        for fpath in [SCRIPT_DIR / "candidates_merged.json", SCRIPT_DIR / "data.json"]:
            if fpath.is_file():
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        cd = json.load(f)
                    c_list = cd.get("candidates", []) or cd.get("merged_candidates", [])
                    for item in c_list:
                        if item.get("symbol", "").upper() == sym:
                            ind_str = str(item.get("industry") or "").strip().lower()
                            tag_str = str(item.get("sector_tag") or "").strip().lower()
                            name_str = str(item.get("name") or "").strip().lower()
                            break
                except Exception:
                    pass
            if ind_str:
                break

    if not ind_str:
        n500_f = SCRIPT_DIR / "nifty500_constituents.json"
        if n500_f.is_file():
            try:
                with open(n500_f, "r", encoding="utf-8") as f:
                    n500 = json.load(f)
                for item in n500:
                    if item.get("symbol", "").upper() == sym:
                        ind_str = str(item.get("industry") or "").strip().lower()
                        name_str = str(item.get("name") or "").strip().lower()
                        break
            except Exception:
                pass

    combined = f"{sym.lower()} {ind_str} {tag_str} {name_str}"
    resolved_theme = "General Equities"
    resolved_icon = "🏢"

    for theme, icon, kw_list in SECTOR_THEME_RULES:
        if any(kw in combined for kw in kw_list):
            resolved_theme = theme
            resolved_icon = icon
            break

    res = {"theme": resolved_theme, "icon": resolved_icon}
    _SECTOR_LOOKUP_CACHE[sym] = res
    return res


def evaluate_strategy_checklist(symbol, quote_data=None, calc_data=None):
    """
    Evaluates 8 core strategy rules:
    1. Regime Health (Macro & Bonde Breadth)
    2. Dynamic ORB High Breakout (LTP > ORB High)
    3. Previous Day High (PDH) Cleared
    4. Strong Start (SS) Signature
    5. Relative Volume (RVOL) Participation
    6. Stop-Loss / LOD Risk Proximity (<= 4.0% risk)
    7. 10 EMA Extension / Stretch (< 3.5%)
    8. Previous Day Narrow Range (NR) & Contraction
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

    # 7. 10 EMA Stretch / Overextension (Institutional Calibration: Prime <= 0.6%, Normal <= 1.5%, Extended > 1.5%)
    stretch_pct = sc_data.get("stretch_pct") if sc_data else None
    if stretch_pct is not None:
        sign = "+" if stretch_pct >= 0 else ""
        if stretch_pct <= 0.6:
            checklist.append({
                "rule": "10 EMA Stretch",
                "passed": True,
                "badge": "🟢",
                "text": f"🟢 <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Prime Coil)",
                "detail": "Tight base coiling right at 10 EMA - Micro-risk entry"
            })
        elif stretch_pct <= 1.5:
            checklist.append({
                "rule": "10 EMA Stretch",
                "passed": True,
                "badge": "⚪",
                "text": f"⚪ <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Normal)",
                "detail": "Healthy 3m momentum expansion near 10 EMA"
            })
        else:
            checklist.append({
                "rule": "10 EMA Stretch",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>10 EMA Stretch:</b> {sign}{stretch_pct:.1f}% (Extended > 1.5%)",
                "detail": "Price overextended from 10 EMA - High trap / chase risk"
            })
            warnings.append(f"Overextended: Price is stretched {sign}{stretch_pct:.1f}% above 10 EMA (>1.5% limit). High trap / pullback risk.")

    # 8. Previous Day Narrow Range (NR) & Volatility Contraction
    prev_range_ratio = sc_data.get("prev_range_ratio") if sc_data else None
    is_inside_day = bool(sc_data.get("is_inside_day")) if sc_data else False
    is_narrow_prev = bool(sc_data.get("is_narrow_prev_day")) if sc_data else False
    if prev_range_ratio is not None or is_inside_day or is_narrow_prev:
        in_tag = " • Inside Day 📦" if is_inside_day else ""
        if (prev_range_ratio is not None and prev_range_ratio <= 0.75) or is_inside_day or is_narrow_prev:
            r_str = f"{prev_range_ratio:.2f}x ATR" if prev_range_ratio is not None else "Coiled"
            checklist.append({
                "rule": "Narrow Range (NR)",
                "passed": True,
                "badge": "💎",
                "text": f"💎 <b>Prev Day NR:</b> Coiled ({r_str}{in_tag})",
                "detail": "Previous session volatility contraction (NR / Inside Day) setup"
            })
        else:
            checklist.append({
                "rule": "Narrow Range (NR)",
                "passed": True,
                "badge": "⚪",
                "text": f"⚪ <b>Prev Day NR:</b> Normal Range ({prev_range_ratio:.2f}x ATR)",
                "detail": "Normal previous day range"
            })

    # 9. Opening Gap Extension Check (Qullamaggie 2.5% Rule)
    open_p = float(quote_data.get("open") or quote_data.get("open_price") or 0)
    prev_close = float(quote_data.get("prev_close") or quote_data.get("close") or 0)
    pdh = float(quote_data.get("prev_day_high") or (sc_data.get("pdh") if sc_data else 0) or 0)
    ref_trigger = pdh if pdh > 0 else prev_close

    if open_p > 0 and ref_trigger > 0:
        gap_ext_pct = ((open_p - ref_trigger) / ref_trigger) * 100.0
        if gap_ext_pct > 2.5:
            checklist.append({
                "rule": "Gap Extension",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Gap Extension:</b> +{gap_ext_pct:.1f}% (Extended > 2.5%)",
                "detail": "Large opening gap above breakout trigger - Risk of chase trap. Wait for 3m shelf pullback."
            })
            warnings.append(f"Gapped Extended: Open (+{gap_ext_pct:.1f}%) is > 2.5% above breakout trigger. Wait for 3m pullback shelf.")
        else:
            checklist.append({
                "rule": "Gap Extension",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Gap Extension:</b> +{max(0, gap_ext_pct):.1f}% (Controlled <= 2.5%)",
                "detail": "Healthy opening within 2.5% trigger threshold"
            })

    # 10. Candle Range Quality / Upper Wick Trap Check
    day_high_val = float(quote_data.get("day_high") or (calc_data or {}).get("day_high", 0) or 0)
    day_low_val = float(day_low or 0)
    if day_high_val > day_low_val and ltp > 0:
        total_candle_range = day_high_val - day_low_val
        upper_wick = max(0.0, day_high_val - ltp)
        upper_wick_pct = (upper_wick / total_candle_range) * 100.0 if total_candle_range > 0 else 0.0
        if upper_wick_pct > 40.0:
            checklist.append({
                "rule": "Candle Quality",
                "passed": False,
                "badge": "⚠️",
                "text": f"⚠️ <b>Candle Quality:</b> Upper Wick {upper_wick_pct:.0f}% (Rejection Risk)",
                "detail": "Price rejected from high by > 40% of range. Risk of false breakout / bull trap."
            })
            warnings.append(f"Upper Wick Trap: Rejection wick is {upper_wick_pct:.0f}% of range. Ensure price reclaims high before entry.")
        else:
            checklist.append({
                "rule": "Candle Quality",
                "passed": True,
                "badge": "✅",
                "text": f"✅ <b>Candle Quality:</b> Solid Close (Upper Wick: {upper_wick_pct:.0f}%)",
                "detail": "Price trading near the top of its range (controlled upper shadow <= 40%)"
            })

    # 11. Sector Theme Sponsorship / Group Momentum Check
    theme_info = resolve_sector_theme(symbol, quote_data=quote_data)
    theme_name = theme_info.get("theme", "General Equities")
    theme_icon = theme_info.get("icon", "🏢")

    theme_cnt = 1
    try:
        from upstox_tablet_scanner import get_theme_breakout_count
        theme_cnt = get_theme_breakout_count(theme_name)
    except Exception:
        theme_cnt = 1

    if theme_cnt >= 3:
        checklist.append({
            "rule": "Sector Theme",
            "passed": True,
            "badge": "🔥",
            "text": f"🔥 <b>Sector Theme:</b> {theme_icon} {theme_name} ({theme_cnt}+ Active Breakouts - SPONSORED)",
            "detail": f"High institutional group sponsorship ({theme_cnt} stocks breaking out in sync)"
        })
    elif theme_cnt >= 2:
        checklist.append({
            "rule": "Sector Theme",
            "passed": True,
            "badge": "⚡",
            "text": f"⚡ <b>Sector Theme:</b> {theme_icon} {theme_name} ({theme_cnt} Dual Breakouts)",
            "detail": f"Emerging sector momentum ({theme_cnt} stocks moving together)"
        })
    else:
        checklist.append({
            "rule": "Sector Theme",
            "passed": True,
            "badge": theme_icon,
            "text": f"{theme_icon} <b>Sector Theme:</b> {theme_name} (Single Runner)",
            "detail": f"Individual stock momentum in {theme_name}"
        })

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


def calculate_order_sizing(quote_data, mode_arg="mod", sl_mode="lod", **kwargs):
    """
    Calculates quantity, stop loss, exposure, risk parameters, and strategy checklist.
    Supports either quote dictionary or string symbol, with flexible size_mode/mode_arg keywords.
    """
    if "size_mode" in kwargs and (mode_arg == "mod" or not mode_arg):
        mode_arg = kwargs["size_mode"]
    if isinstance(quote_data, str):
        sym_s = quote_data.strip().upper()
        q, _ = fetch_live_quote(sym_s)
        quote_data = q if q else {"symbol": sym_s, "ltp": 100.0, "day_low": 98.0}

    symbol = quote_data.get("symbol", "")
    ltp = float(quote_data.get("ltp") or 0.0)
    day_low = float(quote_data.get("day_low") or (ltp * 0.985 if ltp > 0 else 0.0))

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

    # P2 Volatility-Adaptive Stop Buffer (3m ATR)
    sc_data = get_symbol_scanner_data(symbol) or {}
    atr_val = quote_data.get("atr_3m") or quote_data.get("atr14") or sc_data.get("atr14")
    if atr_val and float(atr_val) > 0:
        atr_f = float(atr_val)
        atr_3m_approx = atr_f / 6.0 if atr_f > (ltp * 0.015) else atr_f
        adaptive_buf = max(1.0, round(atr_3m_approx * 0.25, 2))
    else:
        adaptive_buf = max(1.0, round(day_low * 0.0020, 2))

    buffer = max(1.0, round(max(adaptive_buf, day_low * 0.0015)))
    sl_price = round_to_clean_int(day_low - buffer)

    if sl_price >= ltp:
        sl_price = round_to_clean_int(ltp * 0.985)

    risk_per_share = round(ltp - sl_price, 2)
    risk_pct = round((risk_per_share / ltp) * 100, 2)

    if risk_pct > 4.0 and sl_mode.lower() in ("regime", "reg"):
        sl_price = round_to_clean_int(ltp * 0.975)
        risk_per_share = round(ltp - sl_price, 2)
        risk_pct = round((risk_per_share / ltp) * 100, 2)
        regime_note += " (SL capped at 2.5% to protect capital)"

    # P1 Risk-Normalized Sizing (Default Target: ₹1,000 or ₹2,000 INR Risk)
    m_clean = str(mode_arg).strip().lower()
    is_risk_norm = m_clean in ("r500", "risk500", "500", "r1k", "risk1k", "1k", "1k_risk", "r2k", "risk2k", "2k", "2k_risk", "mod", "default", "")

    if is_risk_norm:
        if m_clean in ("r500", "risk500", "500"):
            target_risk_inr = 500
        elif m_clean in ("r2k", "risk2k", "2k", "2k_risk"):
            target_risk_inr = 2000
        else:
            target_risk_inr = 1000  # Default: ₹1,000 Risk Target
        
        rps = max(1.0, risk_per_share)
        # Institutional ATR-Normalized Risk Floor (prevents oversized positions on artificially tight stops)
        atr_14_f = float(atr_val) if (atr_val and float(atr_val) > 0) else (ltp * 0.02)
        effective_risk_dist = max(rps, atr_14_f * 0.75, 1.0)
        quantity = max(1, int(target_risk_inr // effective_risk_dist))
        actual_exposure = round(quantity * ltp, 2)
        total_risk_inr = round(risk_per_share * quantity, 2)
        mode_label = f"Risk-Normalized (₹{target_risk_inr:,} Target, ATR-Floored)"
    else:
        quantity = int(effective_size / ltp)
        if quantity == 0 and effective_size >= ltp:
            quantity = 1
        actual_exposure = round(quantity * ltp, 2)
        total_risk_inr = round(risk_per_share * quantity, 2)

    # P2.1 Defensive Regime Auto-Cap: strictly limit exposure to ₹50k max during defensive/cash breadth regimes
    is_defensive = str(regime_code).upper() in ("DEFENSIVE", "DEFENSIVE_WATERFALL", "CLIMAX", "WASHOUT", "CHOP") or alloc_pct == 0
    if is_defensive:
        if actual_exposure > 50000:
            quantity = max(1, int(50000 // ltp))
            actual_exposure = round(quantity * ltp, 2)
            total_risk_inr = round(risk_per_share * quantity, 2)
            mode_label = f"{mode_label} [DEFENSIVE CAP: ₹50k]"
            cap_msg = f"🛡️ Defensive Regime ({regime_code}): Exposure capped to ₹50,000 max (Capital Preservation)"
            regime_note = f"{regime_note} | {cap_msg}" if regime_note else cap_msg

    # Dynamic "Risk-Free" Pyramiding Sizing (House Money Equation)
    holding_info = get_active_holding_info(symbol)
    pyramid_data = None
    if holding_info:
        h_qty = int(holding_info.get("qty", 0))
        h_entry = float(holding_info.get("entry_price") or 0.0)
        h_broker = holding_info.get("broker", "HOLDING")
        if h_entry > 0 and h_qty > 0 and ltp > h_entry:
            unrealized_pnl = round((ltp - h_entry) * h_qty, 2)
            max_risk_allowed = round(unrealized_pnl * 0.50, 2)
            sl_dist = max(1.0, ltp - sl_price)
            risk_free_qty = max(1, int(max_risk_allowed / sl_dist))

            if str(mode_arg).lower() in ("rf", "riskfree", "risk_free", "pyr_rf"):
                quantity = risk_free_qty
                effective_size = int(quantity * ltp)
                actual_exposure = round(quantity * ltp, 2)
                total_risk_inr = round(risk_per_share * quantity, 2)
                mode_label = f"Risk-Free Pyramid ({quantity} shs)"

            pyramid_data = {
                "holding_qty": h_qty,
                "holding_entry": h_entry,
                "holding_broker": h_broker,
                "unrealized_pnl": unrealized_pnl,
                "max_risk_allowed": max_risk_allowed,
                "risk_free_qty": risk_free_qty,
                "is_profitable": True
            }

    checklist_eval = evaluate_strategy_checklist(symbol, quote_data=quote_data, calc_data={
        "ltp": ltp,
        "day_low": day_low,
        "risk_pct": risk_pct
    })

    return {
        "symbol": symbol,
        "instrument_key": quote_data.get("instrument_key", ""),
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
        "checklist": checklist_eval,
        "pyramid_data": pyramid_data
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
        "price": int(round_to_clean_int(price)) if order_type.upper() == "LIMIT" else 0,
        "tag": "JARVIS_MTF",
        "instrument_token": instrument_key,
        "order_type": order_type.upper(),
        "transaction_type": "BUY",
        "disclosed_quantity": 0,
        "trigger_price": 0,
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
        "price": int(round_to_clean_int(price)) if order_type.upper() == "LIMIT" else 0,
        "triggerPrice": 0,
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
        "price": int(round_to_clean_int(price)) if order_type.upper() == "LIMIT" else 0,
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
    trigger_p = round_to_clean_int(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        # Limit buffer strictly rounded to integer below trigger
        limit_price = round_to_clean_int(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = max(1, trigger_p - 1)
    else:
        # BUY SL (for short positions): limit buffer above trigger
        limit_price = round_to_clean_int(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = trigger_p + 1

    payload = {
        "quantity": int(quantity),
        "product": product.upper(),
        "validity": "DAY",
        "price": int(limit_price),
        "tag": "JARVIS_SL",
        "instrument_token": instrument_key,
        "order_type": "SL",
        "transaction_type": tt,
        "disclosed_quantity": 0,
        "trigger_price": int(trigger_p),
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
    trigger_p = round_to_clean_int(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_price = round_to_clean_int(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = max(1, trigger_p - 1)
    else:
        limit_price = round_to_clean_int(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = trigger_p + 1

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
        "price": int(limit_price),
        "triggerPrice": int(trigger_p),
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

    trigger_p = round_to_clean_int(sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_price = round_to_clean_int(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = max(1, trigger_p - 1)
    else:
        limit_price = round_to_clean_int(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = trigger_p + 1

    url = "https://api.kite.trade/orders/regular"
    payload = {
        "tradingsymbol": symbol.upper(),
        "exchange": "NSE",
        "transaction_type": tt,
        "order_type": "SL",
        "quantity": int(quantity),
        "product": product.upper(),
        "validity": "DAY",
        "price": int(limit_price),
        "trigger_price": int(trigger_p),
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
    clean_sl = round_to_clean_int(sl_price)
    if b == "upstox":
        inst_key = instrument_key or resolve_instrument_key(symbol)
        if not inst_key:
            return False, f"Could not resolve instrument key for {symbol}"
        return place_upstox_stop_loss_order(inst_key, quantity, clean_sl, product=product, transaction_type=transaction_type)
    elif b == "dhan":
        return place_dhan_stop_loss_order(symbol, quantity, clean_sl, product=product, transaction_type=transaction_type)
    elif b == "zerodha":
        return place_zerodha_stop_loss_order(symbol, quantity, clean_sl, product="CNC", transaction_type=transaction_type)
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
        "price": int(round_to_clean_int(limit_price)),
        "order_type": "SL",
        "disclosed_quantity": 0,
        "trigger_price": int(round_to_clean_int(trigger_price))
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
        "price": int(round_to_clean_int(limit_price)),
        "triggerPrice": int(round_to_clean_int(trigger_price)),
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
        "price": int(round_to_clean_int(limit_price)),
        "trigger_price": int(round_to_clean_int(trigger_price)),
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
    trigger_p = round_to_clean_int(new_sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_price = round_to_clean_int(trigger_p * 0.998)
        if limit_price >= trigger_p:
            limit_price = max(1, trigger_p - 1)
    else:
        limit_price = round_to_clean_int(trigger_p * 1.002)
        if limit_price <= trigger_p:
            limit_price = trigger_p + 1

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
def resolve_symbol_exchange(symbol, explicit_exchange=None):
    """
    Intelligently determines the primary trading exchange (NSE or BSE).
    1. Respects explicit exchange if passed (e.g. 'BSE' from live holding/position).
    2. Identifies securities exclusively traded on BSE (e.g. 'NSE' ticker).
    3. Defaults to 'NSE'.
    """
    if explicit_exchange and str(explicit_exchange).strip().upper() in ("BSE", "NSE"):
        return str(explicit_exchange).strip().upper()
    sym_u = (symbol or "").strip().upper()
    if sym_u in ("NSE", "BSE"):
        return "BSE"
    return "NSE"


def place_zerodha_gtt_stop_loss(symbol, quantity, sl_price, exchange=None, product="CNC", transaction_type="SELL"):
    """Submits a permanent 1-year GTT Stop-Loss trigger directly to Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    ak = kite.get("api_key", "").strip()
    tok = kite.get("access_token", "").strip()
    if not (ak and tok):
        return False, "Zerodha credentials missing in config_credentials.json"

    sym_u = (symbol or "").strip().upper()
    resolved_ex = resolve_symbol_exchange(sym_u, exchange)
    trigger_p = round_to_clean_int(sl_price)
    tt = transaction_type.upper()

    # Guard: prevent duplicate GTT triggers for the same scrip on Zerodha
    existing_gtt = get_pending_gtt_order(sym_u, broker="zerodha")
    if existing_gtt and existing_gtt.get("order_id"):
        old_trig = float(existing_gtt.get("trigger_price") or 0)
        if tt == "SELL" and old_trig >= trigger_p:
            return True, f"Active GTT {existing_gtt['order_id']} already protects {sym_u} at ₹{old_trig:,.0f} (duplicate prevented)"
        ok, m_res = modify_zerodha_gtt_stop_loss(
            existing_gtt["order_id"],
            sym_u,
            quantity,
            trigger_p,
            exchange=resolved_ex,
            product=product,
            transaction_type=tt
        )
        if ok:
            return True, f"Modified existing GTT {existing_gtt['order_id']} for {sym_u} (duplicate prevented)"
        return False, f"Existing GTT {existing_gtt['order_id']} modify failed: {m_res}"

    if tt == "SELL":
        limit_p = round_to_clean_int(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = max(1, trigger_p - 1)
    else:
        limit_p = round_to_clean_int(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = trigger_p + 1

    q, _ = fetch_live_quote(sym_u)
    ltp = float(q.get("ltp", 0) or 0) if q else 0.0
    if ltp <= trigger_p:
        try:
            req_h = urllib.request.Request("https://api.kite.trade/portfolio/holdings", headers={"X-Kite-Version": "3", "Authorization": f"token {ak}:{tok}"})
            with urllib.request.urlopen(req_h, timeout=5) as r:
                for h in json.loads(r.read().decode()).get("data", []):
                    if h.get("tradingsymbol") == sym_u and float(h.get("last_price", 0) or 0) > 0:
                        ltp = float(h["last_price"])
                        break
        except Exception:
            pass
    if ltp <= trigger_p:
        ltp = round(float(trigger_p) * 1.02, 2)

    condition = {
        "exchange": resolved_ex,
        "tradingsymbol": sym_u,
        "trigger_values": [int(trigger_p)],
        "last_price": float(ltp)
    }
    orders = [{
        "exchange": resolved_ex,
        "tradingsymbol": sym_u,
        "transaction_type": tt,
        "quantity": int(quantity),
        "order_type": "LIMIT",
        "product": product.upper(),
        "price": int(limit_p)
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


def modify_zerodha_gtt_stop_loss(trigger_id, symbol, quantity, new_sl_price, exchange=None, product="CNC", transaction_type="SELL"):
    """Atomically modifies an existing GTT Stop-Loss trigger on Zerodha Kite API."""
    cfg = load_config()
    kite = cfg.get("zerodha", {})
    ak = kite.get("api_key", "").strip()
    tok = kite.get("access_token", "").strip()
    if not (ak and tok):
        return False, "Zerodha credentials missing"

    sym_u = (symbol or "").strip().upper()
    resolved_ex = resolve_symbol_exchange(sym_u, exchange)
    trigger_p = round_to_clean_int(new_sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_p = round_to_clean_int(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = max(1, trigger_p - 1)
    else:
        limit_p = round_to_clean_int(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = trigger_p + 1

    q, _ = fetch_live_quote(sym_u)
    ltp = float(q.get("ltp", 0) or 0) if q else 0.0
    if ltp <= trigger_p:
        try:
            req_h = urllib.request.Request("https://api.kite.trade/portfolio/holdings", headers={"X-Kite-Version": "3", "Authorization": f"token {ak}:{tok}"})
            with urllib.request.urlopen(req_h, timeout=5) as r:
                for h in json.loads(r.read().decode()).get("data", []):
                    if h.get("tradingsymbol") == sym_u and float(h.get("last_price", 0) or 0) > 0:
                        ltp = float(h["last_price"])
                        break
        except Exception:
            pass
    if ltp <= trigger_p:
        ltp = round(float(trigger_p) * 1.02, 2)

    condition = {
        "exchange": resolved_ex,
        "tradingsymbol": sym_u,
        "trigger_values": [int(trigger_p)],
        "last_price": float(ltp)
    }
    orders = [{
        "exchange": resolved_ex,
        "tradingsymbol": sym_u,
        "transaction_type": tt,
        "quantity": int(quantity),
        "order_type": "LIMIT",
        "product": product.upper(),
        "price": int(limit_p)
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
            msg = err_json.get("message", f"HTTP {he.code}")
            if "no changes detected" in str(msg).lower():
                return True, str(trigger_id)
            return False, msg
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

    trigger_p = round_to_clean_int(sl_price)
    tt = transaction_type.upper()

    # Guard: prevent duplicate Forever Orders for the same scrip on Dhan
    existing_gtt = get_pending_gtt_order(sym_u, broker="dhan")
    if existing_gtt and existing_gtt.get("order_id"):
        old_trig = float(existing_gtt.get("trigger_price") or 0)
        if tt == "SELL" and old_trig >= trigger_p:
            return True, f"Active Dhan Forever order {existing_gtt['order_id']} already protects {sym_u} at ₹{old_trig:,.0f} (duplicate prevented)"
        ok, m_res = modify_dhan_forever_stop_loss(
            existing_gtt["order_id"],
            quantity,
            trigger_p,
            transaction_type=tt
        )
        if ok:
            return True, f"Modified existing Dhan Forever Order {existing_gtt['order_id']} for {sym_u} (duplicate prevented)"
        return False, f"Existing Dhan Forever order {existing_gtt['order_id']} modify failed: {m_res}"

    if tt == "SELL":
        limit_p = round_to_clean_int(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = max(1, trigger_p - 1)
    else:
        limit_p = round_to_clean_int(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = trigger_p + 1

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
        "price": int(limit_p),
        "triggerPrice": int(trigger_p)
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

    trigger_p = round_to_clean_int(new_sl_price)
    tt = transaction_type.upper()
    if tt == "SELL":
        limit_p = round_to_clean_int(trigger_p * 0.998)
        if limit_p >= trigger_p:
            limit_p = max(1, trigger_p - 1)
    else:
        limit_p = round_to_clean_int(trigger_p * 1.002)
        if limit_p <= trigger_p:
            limit_p = trigger_p + 1

    payload = {
        "dhanClientId": cid,
        "orderId": str(order_id),
        "orderFlag": "SINGLE",
        "legName": "STOP_LOSS_LEG",
        "orderType": "LIMIT",
        "transactionType": tt,
        "quantity": int(quantity),
        "price": int(limit_p),
        "triggerPrice": int(trigger_p),
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


def place_upstox_gtt_stop_loss(instrument_key, quantity, sl_price, product="MTF", transaction_type="SELL", symbol=None):
    """Submits a permanent 1-year GTT Stop-Loss directly to Upstox API v3."""
    cfg = load_config()
    tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if not tok:
        return False, "Upstox access token missing"

    trigger_p = round_to_clean_int(sl_price)
    tt = transaction_type.upper()
    trig_type = "BELOW" if tt == "SELL" else "ABOVE"
    prod_code = "D" if product.upper() in ("CNC", "DELIVERY", "D") else "MTF"

    # Guard: prevent duplicate GTT triggers for the same scrip on Upstox
    if symbol:
        existing_gtt = get_pending_gtt_order(symbol, broker="upstox")
        if existing_gtt and existing_gtt.get("order_id"):
            old_trig = float(existing_gtt.get("trigger_price") or 0)
            if tt == "SELL" and old_trig >= trigger_p:
                return True, f"Active Upstox GTT {existing_gtt['order_id']} already protects {symbol} at ₹{old_trig:,.0f} (duplicate prevented)"
            cancel_upstox_gtt_order(existing_gtt["order_id"])

    payload = {
        "type": "SINGLE",
        "quantity": int(quantity),
        "product": prod_code,
        "rules": [
            {
                "strategy": "ENTRY",
                "trigger_type": trig_type,
                "trigger_price": int(trigger_p)
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


def modify_upstox_gtt_stop_loss(gtt_id, quantity, new_sl_price, symbol=None, instrument_key=None, product="MTF", transaction_type="SELL"):
    """
    Modifies an active Upstox v3 GTT Stop-Loss order.
    Attempts PUT /v3/order/gtt/modify; if unsuccessful or rejected, automatically falls back
    to atomic replacement (cancel old GTT + place new higher GTT) to ensure the position is never left unprotected.
    """
    cfg = load_config()
    tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if not tok:
        return False, "Upstox access token missing"

    clean_sl = round_to_clean_int(new_sl_price)
    tt = transaction_type.upper()
    trig_type = "BELOW" if tt == "SELL" else "ABOVE"
    prod_code = "D" if product.upper() in ("CNC", "DELIVERY", "D") else "MTF"

    # Attempt 1: Native Upstox API v3 GTT modify endpoint
    try:
        payload = {
            "gtt_order_id": str(gtt_id),
            "type": "SINGLE",
            "quantity": int(quantity),
            "rules": [
                {
                    "strategy": "ENTRY",
                    "trigger_type": trig_type,
                    "trigger_price": int(clean_sl)
                }
            ]
        }
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request("https://api.upstox.com/v3/order/gtt/modify", data=req_data, method="PUT", headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Jarvis-Order-Engine"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                mod_id = data.get("data", {}).get("gtt_order_id", str(gtt_id))
                return True, str(mod_id)
    except Exception:
        pass

    # Attempt 2: Atomic cancel and place new GTT
    inst_k = instrument_key or (resolve_instrument_key(symbol) if symbol else None)
    if not inst_k and symbol:
        inst_k = resolve_instrument_key(symbol)

    if inst_k:
        cancel_upstox_gtt_order(gtt_id)
        time.sleep(0.3)
        return place_upstox_gtt_stop_loss(inst_k, quantity, clean_sl, product=prod_code, transaction_type=tt, symbol=symbol)

    return False, f"Upstox GTT modify failed and missing instrument key for fallback ({symbol or gtt_id})"


def place_broker_gtt_stop_loss(broker, symbol, quantity, sl_price, instrument_key=None, product="MTF", transaction_type="SELL", exchange="NSE"):
    """Unified dispatcher: submits a permanent 1-year GTT Stop-Loss to designated broker."""
    b = (broker or "").strip().lower()
    clean_sl = round_to_clean_int(sl_price)
    if b == "zerodha":
        return place_zerodha_gtt_stop_loss(symbol, quantity, clean_sl, exchange=exchange, product="CNC" if product.upper() in ("CNC", "DELIVERY") else "MTF", transaction_type=transaction_type)
    elif b == "dhan":
        return place_dhan_forever_stop_loss(symbol, quantity, clean_sl, product=product, transaction_type=transaction_type)
    elif b == "upstox":
        inst_k = instrument_key or resolve_instrument_key(symbol)
        if not inst_k:
            return False, f"Could not resolve instrument key for {symbol}"
        return place_upstox_gtt_stop_loss(inst_k, quantity, clean_sl, product=product, transaction_type=transaction_type, symbol=symbol)
    return False, f"Unsupported broker for GTT: {broker}"


def modify_broker_gtt_stop_loss(broker, order_id, quantity, new_sl_price, symbol=None, transaction_type="SELL", exchange="NSE", product="CNC"):
    """Unified dispatcher: atomically modifies an existing GTT Stop-Loss on designated broker."""
    b = (broker or "").strip().lower()
    clean_sl = round_to_clean_int(new_sl_price)
    if b == "zerodha":
        return modify_zerodha_gtt_stop_loss(order_id, symbol or "", quantity, clean_sl, exchange=exchange, product=product, transaction_type=transaction_type)
    elif b == "dhan":
        return modify_dhan_forever_stop_loss(order_id, quantity, clean_sl, transaction_type=transaction_type)
    elif b == "upstox":
        return modify_upstox_gtt_stop_loss(order_id, quantity, clean_sl, symbol=symbol, product=product, transaction_type=transaction_type)
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
                                ex_val = str(cond.get("exchange", "NSE")).upper()
                                ord_prod = str(ords[0].get("product", "CNC")).upper() if ords else "CNC"
                                return {
                                    "order_id": str(trig.get("id")),
                                    "broker": "ZERODHA",
                                    "quantity": int(qty),
                                    "trigger_price": float(trig_p),
                                    "price": float(lim_p),
                                    "transaction_type": str(tx_type).upper(),
                                    "exchange": ex_val,
                                    "product": ord_prod,
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


def update_tracked_holding_on_fill(symbol, broker, product, quantity, fill_price, sl_price, target_price=None):
    """
    Instantly updates tracked_holdings.json and config_credentials.json upon successful order fill.
    Eliminates the double-pyramid race condition and guarantees real-time sync with scanner & cockpit.
    """
    sym_u = (symbol or "").strip().upper()
    b_name = (broker or "").strip().upper()
    prod = "CNC" if b_name == "ZERODHA" else (product.split()[0].upper() if product else "MTF")
    qty = int(quantity)
    f_price = float(fill_price)
    clean_sl = float(sl_price) if sl_price else 0.0
    tgt_p = float(target_price) if target_price else (round(f_price + (abs(f_price - clean_sl) * 2.0), 2) if clean_sl > 0 else round(f_price * 1.05, 2))
    today_str = datetime.now().strftime("%Y-%m-%d")

    th_file = SCRIPT_DIR / "tracked_holdings.json"
    th_data = {}
    if th_file.is_file():
        try:
            with open(th_file, "r", encoding="utf-8") as f:
                th_data = json.load(f)
        except Exception:
            th_data = {}

    if sym_u in th_data:
        # Pyramiding fill: blend weighted average entry price
        old_qty = int(th_data[sym_u].get("qty", 0))
        old_entry = float(th_data[sym_u].get("entry_price", f_price) or f_price)
        total_qty = old_qty + qty
        new_avg = round(((old_qty * old_entry) + (qty * f_price)) / total_qty, 2) if total_qty > 0 else f_price
        old_sl = float(th_data[sym_u].get("sl", 0) or 0)
        new_sl = max(clean_sl, old_sl) if clean_sl > 0 else old_sl

        th_data[sym_u].update({
            "broker": b_name,
            "product": prod,
            "qty": total_qty,
            "entry_price": new_avg,
            "sl": new_sl,
            "target": tgt_p,
            "notes": f"{b_name} Holding | Pyramided (+{qty} shs @ ₹{f_price:,.2f})"
        })
    else:
        # Fresh initial position
        th_data[sym_u] = {
            "broker": b_name,
            "product": prod,
            "qty": qty,
            "entry_price": round(f_price, 2),
            "sl": clean_sl,
            "target": round(tgt_p, 2),
            "entry_date": today_str,
            "entry_ts": time.time(),
            "entry_time_ist": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "highest_ltp": float(f_price),
            "highest_r": 0.0,
            "notes": f"{b_name} {prod} Position (Live Executed)"
        }

    try:
        with open(th_file, "w", encoding="utf-8") as f:
            json.dump(th_data, f, indent=2)
    except Exception as e:
        print(f"Error persisting tracked_holdings.json on fill: {e}")


def update_tracked_holding_on_exit(symbol, remaining_qty, exit_price=None, exit_reason="🚨 MANUAL EXIT", broker=None, notes=None):
    """Updates or prunes symbol from tracked_holdings.json upon partial or full exit and records post-mortem."""
    sym_u = (symbol or "").strip().upper()
    th_file = SCRIPT_DIR / "tracked_holdings.json"
    if th_file.is_file():
        try:
            with open(th_file, "r", encoding="utf-8") as f:
                th_data = json.load(f)
            if sym_u in th_data:
                meta_saved = dict(th_data[sym_u])
                if remaining_qty <= 0:
                    del th_data[sym_u]
                    # Centralized Post-Mortem Logging on Exit
                    try:
                        from trade_post_mortem import record_trade_post_mortem
                        ex_p = float(exit_price or meta_saved.get("sl") or meta_saved.get("recommended_sl") or meta_saved.get("entry_price") or 0.0)
                        record_trade_post_mortem(
                            symbol=sym_u,
                            exit_price=ex_p,
                            exit_qty=int(meta_saved.get("qty", 1)),
                            exit_reason=exit_reason,
                            broker=broker or meta_saved.get("broker"),
                            notes=notes or "Position exited via execution engine",
                            meta=meta_saved
                        )
                    except Exception as ex_pm:
                        print(f"Notice logging post-mortem in update_tracked_holding_on_exit: {ex_pm}")
                else:
                    th_data[sym_u]["qty"] = int(remaining_qty)
                    th_data[sym_u]["notes"] = str(th_data[sym_u].get("notes", "")) + f" | Partial Exit ({remaining_qty} shs remaining)"
                with open(th_file, "w", encoding="utf-8") as f:
                    json.dump(th_data, f, indent=2)
        except Exception as e:
            print(f"Notice updating tracked_holdings on exit: {e}")


# ---------------------------------------------------------
# P7: Daily Drawdown Circuit Breaker ("Account Kill Switch")
# ---------------------------------------------------------
KILL_SWITCH_FILE = SCRIPT_DIR / "kill_switch.json"
MAX_DAILY_LOSS_DEFAULT = 4000.0  # ₹4,000 max daily loss limit (~2.5R to 4R)


def load_kill_switch_state():
    """Loads daily kill switch state. Automatically resets for fresh trading day."""
    today_str = get_ist_now().strftime("%Y-%m-%d")
    default_state = {
        "date": today_str,
        "is_tripped": False,
        "daily_realized_pnl": 0.0,
        "max_daily_loss_limit": MAX_DAILY_LOSS_DEFAULT,
        "tripped_at": None,
        "reason": None
    }
    if KILL_SWITCH_FILE.is_file():
        try:
            with open(KILL_SWITCH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today_str:
                return data
            # New trading day: save auto-reset state
            save_kill_switch_state(default_state)
            return default_state
        except Exception:
            pass
    return default_state


def save_kill_switch_state(state):
    """Persists kill switch state to disk safely."""
    try:
        with open(KILL_SWITCH_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving kill switch state: {e}")
        return False


def get_daily_realized_pnl():
    """Calculates cumulative realized P&L from orders_log.json for today."""
    today_str = get_ist_now().strftime("%Y-%m-%d")
    log_f = SCRIPT_DIR / "orders_log.json"
    realized_pnl = 0.0
    if not log_f.is_file():
        return 0.0
    try:
        with open(log_f, "r", encoding="utf-8") as f:
            logs = json.load(f)
        for entry in logs:
            ts = entry.get("timestamp", "")
            if ts.startswith(today_str) and entry.get("action") in ("EXIT", "SELL"):
                pnl_val = float(entry.get("pnl") or entry.get("realized_pnl") or 0.0)
                realized_pnl += pnl_val
    except Exception:
        pass
    return round(realized_pnl, 2)


def check_daily_kill_switch():
    """
    Evaluates whether the daily drawdown limit has been breached.
    Returns (is_tripped: bool, reason: str or None).
    """
    state = load_kill_switch_state()
    if state.get("is_tripped", False):
        return True, state.get("reason", "Daily Drawdown Kill Switch is ACTIVE")

    realized = get_daily_realized_pnl()
    state["daily_realized_pnl"] = realized
    limit = float(state.get("max_daily_loss_limit", MAX_DAILY_LOSS_DEFAULT))

    if realized <= -abs(limit):
        state["is_tripped"] = True
        state["tripped_at"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
        state["reason"] = f"Daily Loss Limit Breached: Realized P&L is -₹{abs(realized):,.0f} (Limit: -₹{limit:,.0f})"
        save_kill_switch_state(state)
        return True, state["reason"]

    save_kill_switch_state(state)
    return False, None


def reset_daily_kill_switch(manual=True):
    """Manually resets the kill switch if authorized by user."""
    state = load_kill_switch_state()
    state["is_tripped"] = False
    state["tripped_at"] = None
    state["reason"] = "Manually reset by user" if manual else None
    save_kill_switch_state(state)
    return True, "Kill switch has been reset. Trading enabled."


# ---------------------------------------------------------
# P4: Portfolio Heat Sieve & Exposure Capacity Guard
# ---------------------------------------------------------
MAX_PORTFOLIO_VAR_INR = 10000.0  # ₹10,000 max open Value at Risk (~2.0% on ₹5L capital)


def check_portfolio_risk_capacity(symbol=None, additional_risk_inr=1000):
    """
    Evaluates total open Value-at-Risk, total portfolio slots (max 10),
    active risk slots under fire against SA regime limits (Expansion: 5, Chop: 3, Washout: 1),
    and daily entry pacing.
    Returns (allowed: bool, details: dict or str).
    """
    try:
        cfg = load_config()
        swing_cfg = cfg.get("risk_parameters", {}).get("swing", {})
        max_total_slots = int(swing_cfg.get("total_portfolio_slots") or swing_cfg.get("max_open_positions") or 10)
        sa_limits = swing_cfg.get("sa_active_risk_slots", {
            "EXPANSION": 5, "IGNITION": 5, "SELECTIVE": 4, "CHOP": 3, "WASHOUT": 1, "CLIMAX": 1, "DEFENSIVE": 2, "NORMAL": 5
        })
        daily_limits = swing_cfg.get("daily_new_entry_limits", {
            "EXPANSION": 3, "IGNITION": 3, "SELECTIVE": 2, "CHOP": 1, "WASHOUT": 0, "CLIMAX": 0, "DEFENSIVE": 1, "NORMAL": 2
        })
        max_var = float(swing_cfg.get("max_portfolio_var_inr", MAX_PORTFOLIO_VAR_INR))

        live_pos, _, _ = fetch_all_positions()
        active_positions = [p for p in live_pos if int(p.get("qty", 0) or 0) > 0]
        total_open_count = len(active_positions)

        sym_clean = (symbol or "").strip().upper()
        is_existing = any(p["symbol"].upper() == sym_clean for p in active_positions)

        # Fetch metadata and tracked holdings to classify positions
        logged = get_open_trades_from_logs()
        th_file = SCRIPT_DIR / "tracked_holdings.json"
        th_data = {}
        if th_file.is_file():
            try:
                with open(th_file, "r", encoding="utf-8") as f:
                    th_data = json.load(f)
            except Exception:
                pass

        total_var = 0.0
        for p in active_positions:
            p_sym = p["symbol"].upper()
            p_qty = int(p.get("qty", 0) or 0)
            meta = logged.get(p_sym, {})
            th_meta = th_data.get(p_sym, {})

            p_entry = float(th_meta.get("entry_price") or meta.get("entry_price") or p.get("avg_price", 0) or 0)
            sl_candidates = [
                float(meta.get("stop_loss", 0) or 0),
                float(th_meta.get("sl", 0) or 0),
                float(th_meta.get("recommended_sl", 0) or 0)
            ]
            p_sl = max(sl_candidates) if sl_candidates else 0.0

            if p_sl > 0 and p_entry > p_sl:
                total_var += (p_entry - p_sl) * p_qty
            elif p_entry > 0 and p_sl <= 0:
                total_var += (p_entry * 0.02) * p_qty  # 2% fallback

        total_var = round(total_var, 2)

        # Determine SA market regime
        regime = load_market_regime()
        regime_code = str(regime.get("state_code") or regime.get("regime_code", "NORMAL")).upper()
        alloc_pct = regime.get("swing_allocation_pct", 100)
        is_defensive = regime_code in ("DEFENSIVE", "DEFENSIVE_WATERFALL", "CLIMAX", "WASHOUT", "CHOP") or alloc_pct == 0

        # Resolve SA active risk slot limit
        default_sa_slots = 3 if is_defensive else 5
        if "EXPANSION" in regime_code or "IGNITION" in regime_code:
            default_sa_slots = 5
        elif "CHOP" in regime_code:
            default_sa_slots = 3
        elif "WASHOUT" in regime_code or "CLIMAX" in regime_code:
            default_sa_slots = 1

        max_slots = int(sa_limits.get(regime_code, default_sa_slots))

        # Check daily entries today
        today_str = datetime.now().strftime("%Y-%m-%d")
        distinct_entries_today = set()
        if ORDERS_LOG_FILE.is_file():
            try:
                with open(ORDERS_LOG_FILE, "r", encoding="utf-8") as f:
                    olog = json.load(f)
                for o in olog:
                    odate = str(o.get("date") or o.get("timestamp") or "")[:10]
                    if odate == today_str and str(o.get("action", "")).upper() in ("BUY", "ENTRY"):
                        osym = str(o.get("symbol", "")).upper()
                        if osym:
                            distinct_entries_today.add(osym)
            except Exception:
                pass

        entries_today_count = len(distinct_entries_today)
        default_daily_limit = 1 if is_defensive else 2
        if "EXPANSION" in regime_code:
            default_daily_limit = 3
        elif "CHOP" in regime_code:
            default_daily_limit = 1
        elif "WASHOUT" in regime_code or "CLIMAX" in regime_code:
            default_daily_limit = 0

        max_daily_entries = int(daily_limits.get(regime_code, default_daily_limit))
        proj_var = total_var + float(additional_risk_inr or 0)

        # Evaluation of constraints
        blocked_reason = None

        # Check 1: Total Portfolio Capacity (Hard Ceiling: 10 Holdings)
        if not is_existing and total_open_count >= max_total_slots:
            blocked_reason = f"Portfolio total capacity saturated ({total_open_count}/{max_total_slots} open positions across brokers). Exit an open position before adding new exposure."
        
        # Check 2: SA Regime Active Capacity (Expansion: 5, Chop: 3, Washout: 1)
        elif not is_existing and total_open_count >= max_slots:
            blocked_reason = f"SA Regime Capacity Saturated: {total_open_count}/{max_slots} active positions in {regime_code} regime. Preserving capital against regime headwinds."

        # Check 3: Daily Entry Throttle (Pacing Guard against morning cluster risk)
        elif not is_existing and max_daily_entries == 0:
            blocked_reason = f"New entries locked in {regime_code} regime (Cash preservation mandate)."
        elif not is_existing and entries_today_count >= max_daily_entries:
            blocked_reason = f"Daily entry limit reached: {entries_today_count}/{max_daily_entries} new trades initiated today in {regime_code} regime (Pacing guard). Preserving capital against cluster risk."

        # Check 4: Total Open Value-at-Risk (VaR) Cap
        elif proj_var > max_var:
            blocked_reason = f"Portfolio Heat Saturated: Total Open VaR is ₹{total_var:,.0f} (+₹{additional_risk_inr:,.0f} would exceed ₹{max_var:,.0f} max limit)."

        # If evaluating for an actual order execution (symbol is provided), block with error message
        if symbol is not None and blocked_reason:
            return False, blocked_reason

        payload = {
            "allowed": (blocked_reason is None),
            "blocked_reason": blocked_reason,
            "open_count": total_open_count,
            "max_slots": max_slots,
            "max_total_slots": max_total_slots,
            "entries_today_count": entries_today_count,
            "max_daily_entries": max_daily_entries,
            "total_var": total_var,
            "proj_var": proj_var,
            "max_var": max_var,
            "headroom_var": max(0.0, max_var - total_var),
            "regime_code": regime_code,
            "is_defensive": is_defensive
        }

        return (blocked_reason is None), payload
    except Exception as e:
        return True, {"note": f"Capacity check bypassed on error: {e}"}


def execute_broker_order(symbol, mode_arg="mod", sl_mode="lod", broker=None):
    """
    Executes full pipeline across any requested broker:
    Upstox (MTF), Dhan (MTF), or Zerodha (CNC).
    Uses Marketable Limit Order (+0.3% max ceiling) to eliminate slippage on volatile breakouts.
    Guarded by P7 Kill Switch and P4 Portfolio Heat Sieve.
    """
    symbol = resolve_symbol(symbol)
    target_broker = (broker or get_default_broker()).strip().lower()
    if target_broker not in SUPPORTED_BROKERS:
        target_broker = "upstox"

    # P7: Daily Drawdown Kill Switch Pre-Flight Check
    is_killed, kill_reason = check_daily_kill_switch()
    if is_killed:
        return False, f"🚨 ORDER BLOCKED: {kill_reason}"

    quote_data, err = fetch_live_quote(symbol)
    if not quote_data:
        return False, err

    calc = calculate_order_sizing(quote_data, mode_arg=mode_arg, sl_mode=sl_mode)
    if calc["quantity"] <= 0:
        return False, f"Calculated quantity is 0. LTP (₹{calc['ltp']}) exceeds allocated size (₹{calc['target_size']:,})."

    # P4: Portfolio Heat Sieve Pre-Flight Check
    additional_risk = calc.get("total_risk_inr", 1000)
    heat_ok, heat_info = check_portfolio_risk_capacity(symbol=symbol, additional_risk_inr=additional_risk)
    if not heat_ok:
        return False, f"🛡️ ORDER BLOCKED: {heat_info}"

    product_label = "MTF"
    ltp = float(calc.get("ltp", 0) or 0)
    # Marketable Limit Order (+0.3% slippage protection ceiling): clean integer price without fractional decimals
    marketable_limit = round_to_clean_int(ltp * 1.003) if ltp > 0 else 0
    order_type = "LIMIT" if marketable_limit > 0 else "MARKET"
    order_price = int(marketable_limit) if marketable_limit > 0 else 0

    # Execute at designated broker
    if target_broker == "upstox":
        success, resp = place_upstox_mtf_order(
            instrument_key=calc["instrument_key"],
            quantity=calc["quantity"],
            order_type=order_type,
            price=order_price
        )
    elif target_broker == "dhan":
        success, resp = place_dhan_mtf_order(
            symbol=symbol,
            quantity=calc["quantity"],
            order_type=order_type,
            price=order_price
        )
    elif target_broker == "zerodha":
        product_label = "CNC (Delivery)"
        success, resp = place_zerodha_order(
            symbol=symbol,
            quantity=calc["quantity"],
            order_type=order_type,
            product="CNC",
            price=order_price
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
    calc["order_type"] = order_type
    calc["limit_price"] = order_price
    calc["slippage_cap"] = "+0.3% (Marketable Limit)"

    record = {
        "timestamp": now_ist,
        "symbol": symbol.upper(),
        "broker": target_broker.upper(),
        "product": product_label,
        "action": "BUY",
        "order_type": order_type,
        "limit_price": order_price,
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

    # Instantly update tracked_holdings.json & in-memory cache to prevent double-pyramid race
    if success:
        try:
            update_tracked_holding_on_fill(
                symbol=symbol,
                broker=target_broker,
                product=product_label,
                quantity=calc["quantity"],
                fill_price=calc["ltp"],
                sl_price=calc.get("stop_loss", 0),
                target_price=calc.get("target")
            )
        except Exception as e:
            print(f"Notice updating tracked holdings on fill: {e}")

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
    tracked_holdings = set()
    th_f = SCRIPT_DIR / "tracked_holdings.json"
    if th_f.is_file():
        try:
            with open(th_f, "r", encoding="utf-8") as f:
                tracked_holdings = set(s.upper() for s in json.load(f).keys())
        except Exception:
            pass
    ignored_symbols = set(s.upper() for s in cfg.get("ignored_symbols", ["MOTHERSON"]))
    
    # Auto-expand swing tracking symbols to include logged trades and active journal open trades
    auto_swing_symbols = set(tracked_holdings)
    try:
        logged_trades = get_open_trades_from_logs()
        auto_swing_symbols.update(logged_trades.keys())
    except Exception:
        pass
    try:
        j_file = SCRIPT_DIR / "Journal.xlsx"
        if j_file.is_file():
            import openpyxl
            wb_j = openpyxl.load_workbook(j_file, data_only=True)
            if "Trade Journal" in wb_j.sheetnames:
                for r in list(wb_j["Trade Journal"].iter_rows(values_only=True))[1:]:
                    if r and len(r) > 10 and r[2] and "OPEN" in str(r[10]).upper():
                        auto_swing_symbols.add(str(r[2]).strip().upper())
    except Exception:
        pass

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
                                    qty = int(h.get("totalQty", 0))
                                    mtf_q = int(h.get("mtf_qty", 0) or 0)
                                    is_swing = (mtf_q > 0) or (sym in auto_swing_symbols)
                                    if is_swing and qty > 0 and not any(p["symbol"].upper() == sym and p["broker"] == "DHAN" for p in all_pos):
                                        if qty > 0:
                                            buy_avg = float(h.get("avgCostPrice", 0.0) or 0.0)
                                            ltp = float(h.get("lastTradedPrice", buy_avg) or buy_avg)
                                            tot_pnl = round((ltp - buy_avg) * qty, 2)
                                            pnl_pct = round(((ltp - buy_avg) / buy_avg) * 100, 2) if buy_avg > 0 else 0.0
                                            exposure = round(qty * ltp, 2)
                                            prod_type = "MTF" if (mtf_q > 0 or sym in ("TATACONSUM", "INDGN", "GRAPHITE")) else "CNC"
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

                # Check Upstox long-term holdings for carry-forward swing trades
                try:
                    req_uh = urllib.request.Request(
                        "https://api.upstox.com/v2/portfolio/long-term-holdings",
                        headers={
                            "Authorization": f"Bearer {u_token}",
                            "Accept": "application/json",
                            "User-Agent": "Jarvis-Positions-Monitor"
                        }
                    )
                    with urllib.request.urlopen(req_uh, timeout=6) as resp_uh:
                        uh_data = json.loads(resp_uh.read().decode())
                        uh_holdings = uh_data.get("data", [])
                        for h in uh_holdings:
                            sym = str(h.get("trading_symbol", "")).strip().upper()
                            if not sym or sym in ignored_symbols:
                                continue
                            if (sym in auto_swing_symbols) and not any(p["symbol"].upper() == sym and p["broker"] == "UPSTOX" for p in all_pos):
                                qty = int(h.get("quantity", 0) or 0)
                                if qty > 0:
                                    avg_price = float(h.get("average_price", 0.0) or 0.0)
                                    ltp = float(h.get("last_price", avg_price) or avg_price)
                                    tot_pnl = float(h.get("pnl", 0.0) or round((ltp - avg_price) * qty, 2))
                                    pnl_pct = round((tot_pnl / (qty * avg_price)) * 100, 2) if avg_price > 0 else 0.0
                                    exposure = round(qty * ltp, 2)
                                    all_pos.append({
                                        "symbol": sym,
                                        "broker": "UPSTOX",
                                        "product": "CNC",
                                        "qty": qty,
                                        "avg_price": round(avg_price, 2),
                                        "ltp": round(ltp, 2),
                                        "pnl": round(tot_pnl, 2),
                                        "pnl_pct": pnl_pct,
                                        "exposure": exposure,
                                        "exchange": "NSE_EQ",
                                        "instrument_token": str(h.get("instrument_token", "")),
                                        "position_type": "LONG"
                                    })
                except Exception:
                    pass
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
                                cnc_q = int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
                                mtf_q = int(h.get("mtf", {}).get("quantity", 0) or 0) if isinstance(h.get("mtf"), dict) else 0
                                qty = cnc_q + mtf_q
                                is_swing = (mtf_q > 0) or (sym in auto_swing_symbols)
                                if is_swing and qty > 0 and not any(p["symbol"].upper() == sym and p["broker"] == "ZERODHA" for p in all_pos):
                                    prod_type = "MTF" if mtf_q > 0 else "CNC"
                                    avg_price = float(h.get("average_price", 0.0) or 0.0)
                                    ltp = float(h.get("last_price", avg_price) or avg_price)
                                    tot_pnl = float(h.get("pnl", 0.0) or round((ltp - avg_price) * qty, 2))
                                    pnl_pct = round((tot_pnl / (qty * avg_price)) * 100, 2) if avg_price > 0 else 0.0
                                    exposure = round(qty * ltp, 2)
                                    all_pos.append({
                                    "symbol": sym,
                                    "broker": "ZERODHA",
                                    "product": prod_type,
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

    # 3.9 Reconcile with Journal.xlsx to guarantee ALL previous open positions are always present
    # Even if a broker API token expired overnight or returned an error,
    # previous days' open swing positions stored in Journal.xlsx are NEVER dropped!
    try:
        from datetime import date, datetime
        j_path = SCRIPT_DIR / "Journal.xlsx"
        if j_path.is_file():
            import openpyxl
            wb_j = openpyxl.load_workbook(j_path, data_only=True)
            if "Trade Journal" in wb_j.sheetnames:
                ws_j = wb_j["Trade Journal"]
                for r in list(ws_j.iter_rows(values_only=True))[1:]:
                    if not r or len(r) < 11:
                        continue
                    sym = str(r[2] or "").strip().upper()
                    status = str(r[10] or "").upper()
                    if sym and "OPEN" in status and sym not in ignored_symbols:
                        # Determine originating broker
                        col22 = str(r[21] if len(r) > 21 else "").upper()
                        b_name = "ZERODHA" if "ZERODHA" in col22 else ("DHAN" if "DHAN" in col22 else ("UPSTOX" if "UPSTOX" in col22 else "BROKER"))
                        b_key = b_name.lower()

                        # BROKER TRUTH GUARD:
                        # If the broker's API is currently connected and healthy (status starts with 'OK'),
                        # then the broker API is the authoritative source of truth.
                        # Missing from live broker positions means the trade has already been CLOSED/EXITED!
                        # We must NEVER resurrect closed trades into active surveillance or dashboard!
                        if b_key in broker_status and broker_status[b_key].startswith("OK"):
                            continue
                        if b_key == "broker":
                            any_ok = any(st.startswith("OK") for st in broker_status.values())
                            any_err = any(st.startswith("Error") for st in broker_status.values())
                            if any_ok and not any_err:
                                continue

                        # If not already returned by live broker API, preserve it from Journal
                        if not any(p["symbol"].upper() == sym for p in all_pos):
                            entry_p = float(r[4] or 0)
                            sl_p = float(r[5] or 0)
                            tgt_p = float(r[6] or 0)
                            qty = int(float(r[7] or 0))
                            if qty > 0 and entry_p > 0:
                                prod_name = "MTF" if "MTF" in col22 else "CNC"
                                
                                q, _ = fetch_live_quote(sym)
                                ltp = float(q.get("ltp", 0) or entry_p) if q else entry_p
                                pnl = round((ltp - entry_p) * qty, 2)
                                pnl_pct = round(((ltp - entry_p) / entry_p) * 100, 2)
                                exposure = round(qty * ltp, 2)
                                
                                entry_dt = r[1]
                                holding_days = 1
                                if entry_dt:
                                    if hasattr(entry_dt, "date"):
                                        holding_days = max(1, (date.today() - entry_dt.date()).days)
                                    elif isinstance(entry_dt, str):
                                        try:
                                            d_parsed = datetime.strptime(entry_dt[:10], "%Y-%m-%d").date()
                                            holding_days = max(1, (date.today() - d_parsed).days)
                                        except Exception:
                                            pass

                                all_pos.append({
                                    "symbol": sym,
                                    "broker": b_name,
                                    "product": prod_name,
                                    "qty": qty,
                                    "avg_price": round(entry_p, 2),
                                    "ltp": round(ltp, 2),
                                    "pnl": round(pnl, 2),
                                    "pnl_pct": pnl_pct,
                                    "exposure": exposure,
                                    "stop_loss": sl_p,
                                    "target": tgt_p,
                                    "source": "JOURNAL (Carried Forward)",
                                    "entry_date": str(entry_dt or ""),
                                    "holding_days": holding_days,
                                    "exchange": "NSE"
                                })
    except Exception as ex_j:
        print(f"Notice reconciling journal open positions in fetch_all_positions: {ex_j}")

    # 4. Enrich positions with active Stop-Loss & Value at Risk (VaR)
    logged_trades = get_open_trades_from_logs()
    total_var = 0.0

    for p in all_pos:
        sym_u = p["symbol"].upper()
        buy_avg = float(p.get("avg_price", 0) or 0)
        qty = int(p.get("qty", 0) or 0)
        is_short = qty < 0
        log_meta = logged_trades.get(sym_u, {})
        sl = float(log_meta.get("stop_loss", 0) or p.get("stop_loss", 0) or 0)

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
        if "holding_days" not in p:
            e_dt_str = log_meta.get("date") or log_meta.get("timestamp")
            if e_dt_str:
                try:
                    from datetime import date, datetime
                    d_parsed = datetime.strptime(str(e_dt_str)[:10], "%Y-%m-%d").date()
                    p["holding_days"] = max(0, (date.today() - d_parsed).days)
                    p["entry_date"] = str(e_dt_str)[:10]
                except Exception:
                    p["holding_days"] = 0
            else:
                p["holding_days"] = 0
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
                    update_tracked_holding_on_exit(target_pos["symbol"], abs_qty - actual_exit_qty)
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
                    update_tracked_holding_on_exit(target_pos["symbol"], abs_qty - actual_exit_qty)
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
                    update_tracked_holding_on_exit(target_pos["symbol"], abs_qty - actual_exit_qty)
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
def reconcile_and_prune_exited_holdings(live_pos, broker_status):
    """
    Auto-prunes exited positions from tracked_holdings.json, orders_log.json,
    and config_credentials.json. If a broker is online and healthy, any previously
    tracked symbol for that broker that is NOT in live_pos has been closed/exited.
    """
    live_symbols_by_broker = {}
    for p in live_pos:
        b = str(p.get("broker", "")).upper()
        s = str(p.get("symbol", "")).upper()
        if b and s:
            live_symbols_by_broker.setdefault(b, set()).add(s)

    # 1. Prune tracked_holdings.json
    th_file = SCRIPT_DIR / "tracked_holdings.json"
    if th_file.is_file():
        try:
            with open(th_file, "r", encoding="utf-8") as f:
                th_data = json.load(f)
            modified = False
            for sym, meta in list(th_data.items()):
                b = str(meta.get("broker", "")).upper()
                b_key = b.lower()
                if b_key in broker_status and broker_status[b_key].startswith("OK"):
                    live_syms = live_symbols_by_broker.get(b, set())
                    if sym.upper() not in live_syms:
                        try:
                            from trade_post_mortem import record_trade_post_mortem
                            ex_p = float(meta.get("sl") or meta.get("recommended_sl") or meta.get("entry_price") or 0.0)
                            record_trade_post_mortem(
                                symbol=sym,
                                exit_price=ex_p,
                                exit_qty=int(meta.get("qty", 1)),
                                exit_reason=None,  # will resolve automatically from meta's last_trail_rule
                                broker=b,
                                notes=f"Auto-reconciled: GTT Stop-Loss executed on {b}",
                                meta=meta
                            )
                        except Exception as ex_pm:
                            print(f"Notice logging post-mortem in reconcile_and_prune_exited_holdings: {ex_pm}")
                        del th_data[sym]
                        modified = True
                        print(f"🧹 Auto-pruned exited holding {sym} ({b}) from tracked_holdings.json")
            if modified:
                with open(th_file, "w", encoding="utf-8") as f:
                    json.dump(th_data, f, indent=2)
        except Exception as e:
            print(f"Notice pruning tracked_holdings: {e}")

    # 2. Mark exited orders in orders_log.json
    if ORDERS_LOG_FILE.is_file():
        try:
            with open(ORDERS_LOG_FILE, "r", encoding="utf-8") as f:
                orders = json.load(f)
            modified = False
            for o in orders:
                sym = str(o.get("symbol", "")).upper()
                b = str(o.get("broker", "")).upper()
                b_key = b.lower()
                status = str(o.get("status", "")).upper()
                action = str(o.get("action", "")).upper()
                if status in ("PLACED", "SUBMITTED") and action == "BUY":
                    if b_key in broker_status and broker_status[b_key].startswith("OK"):
                        live_syms = live_symbols_by_broker.get(b, set())
                        if sym not in live_syms:
                            o["status"] = "EXITED"
                            o["notes"] = f"Auto-reconciled: position closed on {b} broker"
                            modified = True
                            print(f"🧹 Marked exited order for {sym} ({b}) in orders_log.json")
            if modified:
                with open(ORDERS_LOG_FILE, "w", encoding="utf-8") as f:
                    json.dump(orders, f, indent=2)
        except Exception as e:
            print(f"Notice pruning orders_log: {e}")

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
                if not sym:
                    continue
                if action in ("EXIT", "SELL"):
                    rem_qty = int(o.get("remaining_qty", 0) or 0)
                    sell_qty = int(o.get("quantity", 0) or 0)
                    if sym in logged_trades:
                        if rem_qty <= 0 or sell_qty >= logged_trades[sym]["qty"]:
                            logged_trades.pop(sym, None)
                        else:
                            logged_trades[sym]["qty"] -= sell_qty
                    continue
                if status not in ("PLACED", "SUBMITTED"):
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
                    th_sl = float(meta.get("sl", 0) or 0)
                    if th_sl > 0:
                        curr_sl = float(logged_trades[sym_u].get("stop_loss", 0) or 0)
                        # Active trailed SL in tracked_holdings takes precedence if tighter
                        if curr_sl == 0 or th_sl > curr_sl:
                            logged_trades[sym_u]["stop_loss"] = th_sl
                    if not logged_trades[sym_u].get("target") and meta.get("target"):
                        logged_trades[sym_u]["target"] = float(meta["target"])
        except Exception:
            pass

    # 4. Filter out any ignored/blacklisted symbols
    try:
        cfg = load_config()
        ignored_symbols = set(s.upper() for s in cfg.get("ignored_symbols", ["MOTHERSON"]))
        for ig in ignored_symbols:
            logged_trades.pop(ig, None)
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
        "ema5": None,
        "ema10": None,
        "ema20": None,
        "sma50": None,
        "atr14": None,
        "prev_day_low": None,
        "prev_day_close": None
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

            ema5 = _calc_ema(closes, 5)
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

            res["ema5"] = round(ema5, 2) if ema5 is not None else None
            res["ema10"] = round(ema10, 2) if ema10 is not None else None
            res["ema20"] = round(ema20, 2) if ema20 is not None else None
            res["sma50"] = round(sma50, 2) if sma50 is not None else None
            res["atr14"] = round(atr14, 2) if atr14 is not None else None
            res["prev_day_low"] = float(chronological[-2][3]) if len(chronological) >= 2 else (float(chronological[-1][3]) if chronological else None)
            res["prev_day_close"] = float(chronological[-2][4]) if len(chronological) >= 2 else (float(chronological[-1][4]) if chronological else None)

            _DAILY_EMA_ATR_CACHE[cache_key] = res
    except Exception:
        pass

    return res


def ratchet_broker_stop_loss(broker, symbol, quantity, new_sl_price, entry_price=None, product="MTF", instrument_key=None, exchange=None, ltp=None):
    """
    P3 Multi-Stage Trailing Stop-Loss Ratchet Engine:
    Ratchets the Stop-Loss up to new_sl_price on the live broker (Upstox, Dhan, Zerodha).
    Supports:
    - Stage 1: -0.5R (Cut risk 50%)
    - Stage 2: Breakeven (+0.15% fee buffer)
    - Stage 3: +1.0R (Lock in guaranteed 1R gain)
    - Stage 4: +2.0R / 10 EMA (Ride the trend)
    Atomically modifies existing GTT trigger or regular exchange stop-loss order.
    """
    sym = (symbol or "").strip().upper()
    b = (broker or "").strip().lower()

    target_sl = round_to_clean_int(new_sl_price)
    target_exchange = resolve_symbol_exchange(sym, exchange)

    # Pre-Flight Guard: Exchange Rule Trigger Price < LTP for Sell orders
    q, _ = fetch_live_quote(sym)
    current_ltp = float(q.get("ltp", 0) or 0) if q else float(ltp or 0)
    if current_ltp > 0 and current_ltp <= target_sl:
        return False, {
            "status": "failed",
            "message": f"Cannot ratchet {sym} to ₹{target_sl:,.0f}: Current LTP (₹{current_ltp:,.2f}) is at or below target SL. Exchange rules require Trigger Price < LTP for Sell Stop-Loss orders.",
            "target_sl": target_sl,
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
        old_trig = float(existing_sl.get("trigger_price") or 0)
        if old_trig >= target_sl:
            ok = True
            atomic_success = True
            res = {"status": "success", "mode": "ALREADY_AT_OR_ABOVE_TARGET", "order_id": old_oid, "sl_price": old_trig}
        elif is_gtt:
            # Atomically modify existing permanent GTT trigger directly
            gtt_ex = existing_sl.get("exchange") or target_exchange
            gtt_prod = existing_sl.get("product") or product
            mod_ok, mod_res = modify_broker_gtt_stop_loss(
                broker=b,
                order_id=old_oid,
                quantity=quantity,
                new_sl_price=target_sl,
                symbol=sym,
                transaction_type="SELL",
                exchange=gtt_ex,
                product=gtt_prod
            )
            if mod_ok:
                ok = True
                atomic_success = True
                new_oid = str(mod_res) if mod_res else old_oid
                res = {"status": "success", "mode": "ATOMIC_GTT_MODIFY", "order_id": new_oid, "sl_price": target_sl}
        else:
            # Modify regular exchange order
            mod_ok, mod_res = modify_broker_stop_loss(b, old_oid, quantity, target_sl, transaction_type="SELL")
            if mod_ok:
                ok = True
                atomic_success = True
                res = {"status": "success", "mode": "ATOMIC_MODIFY", "order_id": old_oid, "sl_price": target_sl}
            else:
                cancel_broker_order(b, old_oid)
                time.sleep(0.6)

    if not ok:
        # Step 2: Fresh GTT placement if no GTT trigger existed or modify failed
        place_ok, place_res = place_broker_gtt_stop_loss(
            broker=b,
            symbol=sym,
            quantity=quantity,
            sl_price=target_sl,
            instrument_key=instrument_key,
            product=product,
            transaction_type="SELL",
            exchange=target_exchange
        )
        if not place_ok:
            # Fall back to regular DAY stop-loss order if GTT placement is rejected
            place_ok, place_res = place_broker_stop_loss(
                broker=b,
                symbol=sym,
                quantity=quantity,
                sl_price=target_sl,
                instrument_key=instrument_key,
                product=product,
                transaction_type="SELL"
            )
        ok = place_ok
        res = {"status": "success" if place_ok else "failed", "mode": "GTT_PLACE", "order_id": place_res if place_ok else None, "error": place_res if not place_ok else None, "sl_price": target_sl}

    # Step 3: Update orders_log.json
    try:
        log_f = SCRIPT_DIR / "orders_log.json"
        if log_f.is_file():
            with open(log_f, "r", encoding="utf-8") as f:
                logs = json.load(f)
            updated = False
            for entry in reversed(logs):
                if entry.get("symbol", "").upper() == sym:
                    entry["stop_loss"] = target_sl
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
                    th[sym]["sl"] = target_sl
                    mode_str = "Atomic Modify" if atomic_success else "Fresh SL"
                    oid_str = res.get("order_id", "N/A") if isinstance(res, dict) else str(res)
                    th[sym]["notes"] = f"{th[sym].get('broker', b.upper())} Holding | Trailed to ₹{target_sl} ({mode_str} {oid_str})"
                    with open(th_f, "w", encoding="utf-8") as f:
                        json.dump(th, f, indent=2)
        except Exception as e:
            print(f"Notice updating tracked_holdings: {e}")

    return ok, {
        "status": "success" if ok else "failed",
        "symbol": sym,
        "entry_price": entry_price,
        "target_sl": target_sl,
        "sl_price": target_sl,
        "breakeven_sl": target_sl,
        "broker": broker,
        "mode": "ATOMIC_MODIFY" if atomic_success else "FRESH_PLACE",
        "details": res
    }


def ratchet_stop_loss_to_breakeven(broker, symbol, quantity, entry_price, product="MTF", instrument_key=None, exchange=None, ltp=None):
    """
    Ratchets Stop-Loss up to Breakeven (+0.15% fee buffer) on the live broker.
    Wraps ratchet_broker_stop_loss.
    """
    raw_be = entry_price * 1.0015
    breakeven_sl = round_to_clean_int(raw_be)
    return ratchet_broker_stop_loss(
        broker=broker,
        symbol=symbol,
        quantity=quantity,
        new_sl_price=breakeven_sl,
        entry_price=entry_price,
        product=product,
        instrument_key=instrument_key,
        exchange=exchange,
        ltp=ltp
    )


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
    trailed_up = []
    critical_alerts = []
    failed = []
    audit_only = []

    now_str = get_ist_now().strftime("%d %b %Y, %H:%M:%S IST")

    # Fetch dynamic trailing recommendations from trailing engine
    trailing_recommendations = {}
    try:
        enriched_pos = get_all_open_positions_with_trailing_sl()
        for ep in enriched_pos:
            ep_sym = str(ep.get("symbol", "")).upper()
            ep_rec = float(ep.get("recommended_sl", 0.0) or 0.0)
            if ep_sym and ep_rec > 0:
                trailing_recommendations[ep_sym] = ep_rec
    except Exception as e:
        print(f"Notice fetching trailing recommendations for rearm: {e}")

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

        # Determine target SL from trailing engine, tracked holdings, or log
        target_sl = 0.0
        source_desc = "Structural"
        if sym in trailing_recommendations and trailing_recommendations[sym] > 0:
            target_sl = trailing_recommendations[sym]
            source_desc = "Trailing Engine"
        elif sym in tracked_holdings and tracked_holdings[sym].get("sl"):
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
                target_sl = round_to_clean_int(avg_p * 1.025)
            else:
                target_sl = round_to_clean_int(avg_p * 0.975)
            source_desc = "Default 2.5% SL"

        target_sl = round_to_clean_int(target_sl)

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

        # Check if already has an active pending Stop-Loss order on broker
        pending_sl = get_pending_stop_loss_order(sym, broker=broker)
        if pending_sl:
            curr_sl = float(pending_sl.get("trigger_price", 0.0) or 0.0)
            # If target trailing SL has advanced higher than active broker SL, automatically ratchet and modify!
            if (not is_short and target_sl > curr_sl + 1.0) or (is_short and target_sl < curr_sl - 1.0):
                ratchet_ok, r_res = ratchet_broker_stop_loss(
                    broker=broker,
                    symbol=sym,
                    quantity=abs_qty,
                    new_sl_price=target_sl,
                    entry_price=avg_p,
                    product=prod,
                    ltp=ltp
                )
                if ratchet_ok:
                    trailed_up.append({
                        "symbol": sym,
                        "broker": broker,
                        "qty": abs_qty,
                        "old_sl": curr_sl,
                        "new_sl": target_sl,
                        "order_id": pending_sl.get("order_id", "N/A"),
                        "source": source_desc
                    })
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
                        th_data[sym]["notes"] = f"{broker} Holding | Trailed GTT Stop (SL: ₹{target_sl:,.0f})"
                        with open(th_f, "w", encoding="utf-8") as f:
                            json.dump(th_data, f, indent=2)
                    except Exception:
                        pass
                    continue
                else:
                    already_protected.append({
                        "symbol": sym,
                        "broker": broker,
                        "qty": pending_sl.get("quantity", abs_qty),
                        "sl": curr_sl,
                        "order_id": pending_sl.get("order_id", "N/A"),
                        "status": pending_sl.get("status", "PENDING")
                    })
                    continue
            else:
                already_protected.append({
                    "symbol": sym,
                    "broker": broker,
                    "qty": pending_sl.get("quantity", abs_qty),
                    "sl": curr_sl,
                    "order_id": pending_sl.get("order_id", "N/A"),
                    "status": pending_sl.get("status", "PENDING")
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

    if trailed_up:
        lines.append(f"📈 <b>Auto-Trailed Higher GTT Stops ({len(trailed_up)}):</b>")
        for tu in trailed_up:
            lines.append(f"• <b>{tu['symbol']}</b> ({tu['broker']}): Qty {tu['qty']} | SL raised: ₹{tu['old_sl']:,.0f} ➔ <b>₹{tu['new_sl']:,.0f}</b> | GTT ID <code>{tu['order_id']}</code> (<i>{tu['source']}</i>)")
        lines.append("")

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

    if not rearmed and not trailed_up and not audit_only and not already_protected and not failed and not critical_alerts:
        lines.append("💤 <b>No open swing positions detected across all configured brokers.</b>")
    else:
        tot_protected = len(rearmed) + len(already_protected) + len(trailed_up)
        tot_positions = len(all_pos)
        lines.append(f"💼 <b>Total Positions:</b> {tot_positions} | <b>Protected:</b> {tot_protected} | <b>Trailed Up:</b> {len(trailed_up)} | <b>Pending Open:</b> {len(audit_only)}")

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
        "trailed_up": trailed_up,
        "audit_only": audit_only,
        "already_protected": already_protected,
        "critical_alerts": critical_alerts,
        "failed": failed,
        "report_text": report_text
    }


_ORPHAN_TRACKER = {}  # key: (broker, symbol), value: first_detected_timestamp

def run_orphan_position_sentry(auto_rearm=True, grace_seconds=30):
    """
    Continuous 30-Second Sentry Fail-Safe:
    Inspects all live open positions across Upstox, Dhan, and Zerodha.
    If an open position (qty != 0) is detected with NO active GTT or Stop-Loss order on the exchange,
    tracks it. Once it has remained unprotected for > grace_seconds (default 30s):
    1. Immediately auto-submits a fresh GTT Stop-Loss to the broker.
    2. Sends high-priority Emergency Telegram Alert to 'orders' and 'risk_trailing' topics.
    3. Updates orders_log.json and tracked_holdings.json.
    """
    global _ORPHAN_TRACKER
    all_pos, totals, broker_status = fetch_all_positions()
    now_ts = time.time()
    orphans_rearmed = []
    orphans_pending_grace = []

    cfg = load_config()
    ignored = set(s.upper() for s in cfg.get("ignored_symbols", ["MOTHERSON"]))
    active_keys = set()

    for p in all_pos:
        sym = p.get("symbol", "").upper()
        if not sym or sym in ignored:
            continue
        broker = p.get("broker", "UPSTOX").upper()
        qty = int(p.get("qty", 0))
        if qty == 0:
            continue
        key = (broker, sym)
        active_keys.add(key)

        # Check broker for active pending Stop-Loss order (GTT or regular)
        pending_sl = get_pending_stop_loss_order(sym, broker=broker)
        if pending_sl:
            _ORPHAN_TRACKER.pop(key, None)
            continue

        # Position is UNPROTECTED
        if key not in _ORPHAN_TRACKER:
            _ORPHAN_TRACKER[key] = now_ts
            elapsed = 0
        else:
            elapsed = now_ts - _ORPHAN_TRACKER[key]

        avg_p = float(p.get("avg_price", 0) or 0)
        ltp = float(p.get("ltp", avg_p) or avg_p)
        prod = p.get("product", "MTF")
        tx_type = "SELL" if qty > 0 else "BUY"
        abs_qty = abs(qty)

        if elapsed < grace_seconds:
            orphans_pending_grace.append({
                "symbol": sym,
                "broker": broker,
                "qty": abs_qty,
                "elapsed": round(elapsed, 1)
            })
            continue

        # Elapsed >= grace_seconds: AUTO-REARM & ALERT
        target_sl = 0.0
        th_f = SCRIPT_DIR / "tracked_holdings.json"
        if th_f.is_file():
            try:
                with open(th_f, "r", encoding="utf-8") as f:
                    th = json.load(f)
                if sym in th and th[sym].get("sl"):
                    target_sl = float(th[sym]["sl"])
            except Exception:
                pass

        if target_sl <= 0 and avg_p > 0:
            target_sl = round_to_clean_int(avg_p * 0.975 if qty > 0 else avg_p * 1.025)

        target_sl = round_to_clean_int(target_sl)

        # Validate exchange rule LTP > target_sl
        if qty > 0 and ltp > 0 and ltp <= target_sl:
            target_sl = round_to_clean_int(ltp * 0.985)

        rearm_ok = False
        rearm_res = None
        if auto_rearm:
            rearm_ok, rearm_res = place_broker_gtt_stop_loss(
                broker=broker,
                symbol=sym,
                quantity=abs_qty,
                sl_price=target_sl,
                product=prod,
                transaction_type=tx_type
            )
            if not rearm_ok and is_market_open():
                rearm_ok, rearm_res = place_broker_stop_loss(
                    broker=broker,
                    symbol=sym,
                    quantity=abs_qty,
                    sl_price=target_sl,
                    product=prod,
                    transaction_type=tx_type
                )

        if rearm_ok:
            _ORPHAN_TRACKER.pop(key, None)
            oid = str(rearm_res)
            orphans_rearmed.append({
                "symbol": sym,
                "broker": broker,
                "qty": abs_qty,
                "sl": target_sl,
                "order_id": oid
            })
            alert_msg = (
                f"🚨 <b>ORPHAN POSITION AUTO-PROTECTED BY SENTRY</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>{sym}</b> on <b>{broker}</b> had NO active Stop-Loss for {int(elapsed)}s!\n"
                f"🛡️ <b>Emergency Action:</b> Auto-placed GTT Stop-Loss @ <b>₹{target_sl:,.0f}</b>\n"
                f"🎯 <b>Order ID:</b> <code>{oid}</code> | <b>Qty:</b> {abs_qty}\n"
                f"💡 <i>Capital is now fully safeguarded on the broker server.</i>"
            )
            try:
                from telegram_bot import send_topic_alert
                send_topic_alert("orders", alert_msg)
                send_topic_alert("risk_trailing", alert_msg)
            except Exception:
                pass

    # Clean up stale keys in tracker
    for k in list(_ORPHAN_TRACKER.keys()):
        if k not in active_keys:
            _ORPHAN_TRACKER.pop(k, None)

    return {
        "status": "success",
        "orphans_rearmed": orphans_rearmed,
        "orphans_pending_grace": orphans_pending_grace
    }


def audit_dead_money_positions(max_days=4, min_r=1.0):
    """
    Evaluates open swing positions for 'Dead Money' capital stagnation.
    If a trade has been held for >= max_days (default 4) and has failed
    to achieve at least min_r (default +1.0R), flags it for capital recycling.
    """
    positions = get_all_open_positions_with_trailing_sl()
    dead_positions = []
    today = datetime.now().date()

    for p in positions:
        sym = p.get("symbol", "").upper()
        entry_date_str = p.get("entry_date") or ""
        holding_days = 0
        if entry_date_str:
            try:
                ed = datetime.strptime(entry_date_str.split()[0], "%Y-%m-%d").date()
                holding_days = (today - ed).days
            except Exception:
                pass

        r_mult = float(p.get("r_multiple", 0) or 0)
        pnl_pct = float(p.get("pnl_pct", 0) or 0)

        if holding_days >= max_days and r_mult < min_r:
            dead_positions.append({
                "symbol": sym,
                "broker": p.get("broker", "UPSTOX"),
                "qty": p.get("qty", 0),
                "entry_price": p.get("entry_price", 0),
                "ltp": p.get("ltp", 0),
                "holding_days": holding_days,
                "r_multiple": r_mult,
                "pnl_pct": pnl_pct,
                "initial_sl": p.get("initial_sl", 0),
                "current_sl": p.get("recommended_sl", 0)
            })

    return dead_positions


def get_all_open_positions_with_trailing_sl():
    """
    Consolidates ALL open positions across live brokers (Dhan, Zerodha, Upstox)
    and trade logs/journals, evaluating Trailing Stop-Loss & Risk Breakeven recommendations.
    Returns: list of enriched position dicts.
    """
    live_pos, totals, broker_status = fetch_all_positions()
    try:
        reconcile_and_prune_exited_holdings(live_pos, broker_status)
    except Exception:
        pass
    logged_trades = get_open_trades_from_logs()
    th_file = SCRIPT_DIR / "tracked_holdings.json"
    tracked_holdings = {}
    if th_file.is_file():
        try:
            with open(th_file, "r", encoding="utf-8") as f:
                tracked_holdings = json.load(f)
        except Exception:
            tracked_holdings = {}
    th_dirty = False

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
        initial_sl = round_to_clean_int(log_meta.get("stop_loss", 0) or 0)
        target_p = round_to_clean_int(log_meta.get("target", 0) or 0)

        # If initial SL not logged, derive structural SL from quote Day Low or 2.5% default
        if initial_sl <= 0 and entry_p > 0:
            if "CE" in sym or "PE" in sym or "NIFTY" in sym:
                initial_sl = round_to_clean_int(entry_p * 0.70)
            else:
                q, _ = fetch_live_quote(sym)
                dl = float(q.get("day_low", 0) or 0) if q else 0
                if 0 < dl < entry_p and ((entry_p - dl) / entry_p) <= 0.05:
                    initial_sl = round_to_clean_int(dl)
                else:
                    initial_sl = round_to_clean_int(entry_p * 0.975)

        if target_p <= 0 and entry_p > 0 and initial_sl > 0:
            target_p = round_to_clean_int(entry_p + abs(entry_p - initial_sl) * 2.0)

        risk_per_share = max(0.10, abs(entry_p - initial_sl)) if entry_p > 0 and initial_sl > 0 else 1.0
        r_multiple = round((ltp - entry_p) / risk_per_share, 2) if risk_per_share > 0 else 0.0
        dist_to_sl_pct = round(((ltp - initial_sl) / ltp) * 100, 2) if ltp > 0 and initial_sl > 0 else 99.0

        # Jeff Sun 10 EMA & 20 EMA Trailing Telemetry
        ema_info = get_daily_emas_and_atr(sym)
        ema10 = ema_info.get("ema10")
        ema20 = ema_info.get("ema20")
        sma50 = ema_info.get("sma50")
        atr14 = ema_info.get("atr14")

        dist_ema10_pct = round(((ltp - ema10) / ema10) * 100.0, 2) if ema10 and ltp else None
        dist_ema20_pct = round(((ltp - ema20) / ema20) * 100.0, 2) if ema20 and ltp else None
        atr_stretch = round((ltp - sma50) / atr14, 1) if sma50 and atr14 and atr14 > 0 and ltp else None

        # Peak Price & R-Multiple Tracking (for 30% Give-Back Cap)
        th_entry = tracked_holdings.get(sym, {})
        highest_ltp = float(th_entry.get("highest_ltp", 0.0) or entry_p or ltp)
        if ltp > highest_ltp:
            highest_ltp = ltp
            if sym not in tracked_holdings:
                tracked_holdings[sym] = {"broker": broker, "qty": qty, "entry_price": entry_p}
            tracked_holdings[sym]["highest_ltp"] = round(highest_ltp, 2)
            tracked_holdings[sym]["highest_r"] = round(max(0.0, highest_ltp - entry_p) / risk_per_share, 2) if risk_per_share > 0 else 0.0
            th_dirty = True

        peak_gain = max(0.0, highest_ltp - entry_p)
        peak_r = round(peak_gain / risk_per_share, 2) if risk_per_share > 0 else 0.0

        # Determine recommended trailing stop loss
        is_option = "CE" in sym or "PE" in sym or "NIFTY" in sym
        if is_option:
            if pnl_pct >= 100.0:
                recommended_sl = round_to_clean_int(entry_p * 2.0)
                action_badge = "⭐ BOOK 50% & TRAIL"
                action_text = f"Huge option gain (+{pnl_pct:.1f}%)! Book half and trail SL to ₹{recommended_sl:,.0f}"
            elif pnl_pct >= 40.0:
                recommended_sl = round_to_clean_int(entry_p)
                action_badge = "🟢 TRAIL TO COST"
                action_text = f"Solid gain (+{pnl_pct:.1f}%)! Trail SL to entry ₹{entry_p:,.2f} for risk-free trade"
            elif ltp <= initial_sl:
                recommended_sl = round_to_clean_int(initial_sl)
                action_badge = "🔴 EXIT — SL HIT"
                action_text = f"Option SL breached at ₹{initial_sl:,.0f}"
            else:
                recommended_sl = round_to_clean_int(initial_sl)
                action_badge = "✅ HOLD"
                action_text = f"Keep initial SL at ₹{initial_sl:,.0f}"
        else:
            if ltp <= initial_sl:
                recommended_sl = round_to_clean_int(initial_sl)
                action_badge = "🔴 EXIT — SL HIT"
                action_text = f"Stop-Loss breached! Market price ₹{ltp:,.2f} is below SL ₹{initial_sl:,.0f}"
            elif dist_to_sl_pct <= 1.0:
                recommended_sl = round_to_clean_int(initial_sl)
                action_badge = "🟡 DANGER — NEAR SL"
                action_text = f"Danger! Price is only {dist_to_sl_pct:.1f}% away from SL ₹{initial_sl:,.0f}"
            elif r_multiple >= 3.0:
                # Stage 4: Trail full 100% position along 10 EMA or +2.0R locked profit (NO PARTIAL BOOKING)
                ema10_val = round_to_clean_int(ema10) if ema10 else 0
                r2_sl = round_to_clean_int(entry_p + (risk_per_share * 2.0))
                recommended_sl = max(r2_sl, ema10_val)
                if recommended_sl >= ltp:
                    recommended_sl = round_to_clean_int(ltp * 0.985)
                action_badge = "🚀 RIDE 10 EMA (+2.0R TRAIL)"
                action_text = f"Surging +{r_multiple:.1f}R! 100% runner riding 10 EMA (Trail SL: ₹{recommended_sl:,.0f}). No profit booked—letting winner run!"
            elif r_multiple >= 2.0:
                # Stage 3: Lock +1.0R guaranteed profit
                recommended_sl = round_to_clean_int(entry_p + (risk_per_share * 1.0))
                if recommended_sl >= ltp:
                    recommended_sl = round_to_clean_int(ltp * 0.985)
                action_badge = "🔒 LOCK +1.0R PROFIT"
                action_text = f"Up +{r_multiple:.1f}R! Move SL to ₹{recommended_sl:,.0f} (+1.0R locked profit). 100% runner preserved!"
            elif r_multiple >= 1.5:
                # Stage 2: Move to Breakeven (+0.15% fee buffer)
                recommended_sl = round_to_clean_int(entry_p * 1.0015)
                action_badge = "🟢 RISK-FREE (BREAKEVEN)"
                action_text = f"Up +{r_multiple:.1f}R! Move SL to Breakeven ₹{recommended_sl:,.0f} (100% Risk-Free!)"
            elif r_multiple >= 1.0:
                # Stage 1: Cut risk by 50%
                recommended_sl = round_to_clean_int(entry_p - (risk_per_share * 0.5))
                action_badge = "🔵 CUT RISK 50%"
                action_text = f"Up +{r_multiple:.1f}R. Trail SL up to ₹{recommended_sl:,.0f} (-0.5R) to cut initial risk by 50%."
            else:
                recommended_sl = round_to_clean_int(initial_sl)
                action_badge = "✅ HOLD — ON TRACK"
                action_text = f"Position healthy. Keep stop at ₹{initial_sl:,.0f} (Target: ₹{target_p:,.0f})"

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
        breakeven_p = round_to_clean_int(raw_be)
        if not is_option and (r_multiple >= 1.5 or pnl_pct >= 2.5):
            if is_short:
                recommended_sl = min(recommended_sl, breakeven_p) if recommended_sl > 0 else breakeven_p
            else:
                recommended_sl = max(recommended_sl, breakeven_p)
            if "HOLD" in action_badge:
                action_badge = "🟢 TRAIL TO BREAKEVEN"
                action_text = f"Target milestone (+{r_multiple:.1f}R)! Move SL to Breakeven ₹{breakeven_p:,.0f} (Risk-Free!)"

        # Rule A: 30% Peak Give-Back Cap (Guarantees locking 70% of peak gains once peak_r >= 2.5)
        if peak_r >= 2.5 and not is_option and not is_short:
            give_back_sl = round_to_clean_int(entry_p + (peak_gain * 0.70))
            if give_back_sl >= ltp:
                give_back_sl = round_to_clean_int(ltp * 0.985)
            if give_back_sl > recommended_sl:
                recommended_sl = give_back_sl
                action_badge = "🛡️ 30% PROFIT CAP"
                action_text = f"Peak reached +{peak_r:.1f}R (₹{highest_ltp:,.2f})! Locking 70% of peak gain (SL: ₹{give_back_sl:,.0f}). No give-back!"

        # Rule B: Parabolic Climax Switch (Tighten trail to 5 EMA when stretched >= 8.0% above 10 EMA)
        ema5 = ema_info.get("ema5")
        if not is_option and not is_short and dist_ema10_pct is not None and dist_ema10_pct >= 8.0 and ema5:
            parabolic_sl = round_to_clean_int(ema5)
            if parabolic_sl >= ltp:
                parabolic_sl = round_to_clean_int(ltp * 0.985)
            if parabolic_sl > recommended_sl:
                recommended_sl = parabolic_sl
                action_badge = "⚡ PARABOLIC 5 EMA TRAIL"
                action_text = f"Parabolic surge (+{dist_ema10_pct:.1f}% above 10 EMA)! Trail tightened to 5 EMA (₹{recommended_sl:,.0f}) to secure climax gains."

        # Rule C: Day-1 Spurt Shield (If entered today and intraday gain >= +2.5R, lock windfall into close)
        entry_date = th_entry.get("entry_date", "")
        today_str = datetime.now().strftime("%Y-%m-%d")
        if not is_option and not is_short and entry_date == today_str and r_multiple >= 2.5:
            day1_sl = round_to_clean_int(entry_p + (risk_per_share * 1.5))
            if day1_sl >= ltp:
                day1_sl = round_to_clean_int(ltp * 0.985)
            if day1_sl > recommended_sl:
                recommended_sl = day1_sl
                action_badge = "🚀 DAY-1 SPURT SHIELD"
                action_text = f"Day-1 Surge (+{r_multiple:.1f}R)! Locking +1.5R windfall gain (SL: ₹{day1_sl:,.0f}) into close."

        # Persist trailing rule & stop metadata to tracked_holdings for post-mortem analytics
        if sym in tracked_holdings:
            tracked_holdings[sym]["last_trail_rule"] = action_badge
            tracked_holdings[sym]["recommended_sl"] = recommended_sl
            if initial_sl > 0:
                tracked_holdings[sym]["initial_sl"] = initial_sl
            if target_p > 0:
                tracked_holdings[sym]["target"] = target_p
            th_dirty = True

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
            "exchange": p.get("exchange", "NSE"),
            "source": p.get("source", "LIVE BROKER"),
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
            "highest_ltp": highest_ltp,
            "highest_r": peak_r,
            "ema5": ema5,
            "jeff_badge": jeff_badge,
            "jeff_status": jeff_status
        })

    # 2. Process any logged trades that are NOT already in live broker accounts
    for sym, log_item in logged_trades.items():
        if sym in seen_symbols:
            continue
        # If the broker is connected and healthy, and didn't report this symbol,
        # it means the position has been exited in the broker! Never treat as open!
        broker_name = str(log_item.get("broker", "")).lower()
        if broker_name in broker_status and broker_status[broker_name].startswith("OK"):
            continue
        entry_p = float(log_item.get("entry_price", 0) or 0)
        qty = int(log_item.get("qty", 0) or 0)
        initial_sl = round_to_clean_int(log_item.get("stop_loss", 0) or 0)
        target_p = round_to_clean_int(log_item.get("target", 0) or 0)
        if entry_p <= 0 or qty <= 0:
            continue

        q, _ = fetch_live_quote(sym)
        ltp = float(q.get("ltp", 0) or entry_p) if q else entry_p
        pnl = round((ltp - entry_p) * qty, 2)
        pnl_pct = round(((ltp - entry_p) / entry_p) * 100, 2)

        if initial_sl <= 0:
            initial_sl = round_to_clean_int(entry_p * 0.975)
        if target_p <= 0:
            target_p = round_to_clean_int(entry_p + abs(entry_p - initial_sl) * 2.0)

        risk_per_share = max(0.10, abs(entry_p - initial_sl))
        r_multiple = round((ltp - entry_p) / risk_per_share, 2)
        dist_to_sl_pct = round(((ltp - initial_sl) / ltp) * 100, 2) if ltp > 0 else 99.0

        if ltp <= initial_sl:
            recommended_sl = round_to_clean_int(initial_sl)
            action_badge = "🔴 EXIT — SL HIT"
            action_text = f"Stop-Loss breached! Market price ₹{ltp:,.2f} is below SL ₹{initial_sl:,.0f}"
        elif dist_to_sl_pct <= 1.0:
            recommended_sl = round_to_clean_int(initial_sl)
            action_badge = "🟡 DANGER — NEAR SL"
            action_text = f"Danger! Price is only {dist_to_sl_pct:.1f}% away from SL ₹{initial_sl:,.0f}"
        elif r_multiple >= 3.0 or pnl_pct >= 6.0:
            recommended_sl = round_to_clean_int(entry_p + (risk_per_share * 1.5))
            action_badge = "⭐ BOOK 50% & TRAIL"
            action_text = f"Up +{r_multiple:.1f}R! Book 50% partial profit and trail SL to ₹{recommended_sl:,.0f}"
        elif r_multiple >= 1.8 or pnl_pct >= 3.0:
            recommended_sl = round_to_clean_int(entry_p)
            action_badge = "🟢 TRAIL TO COST"
            action_text = f"Up +{r_multiple:.1f}R! Move SL to Breakeven ₹{recommended_sl:,.0f} (Risk-Free!)"
        elif r_multiple >= 1.0 or pnl_pct >= 1.5:
            recommended_sl = round_to_clean_int(entry_p - (risk_per_share * 0.5))
            action_badge = "🔵 CUT RISK 50%"
            action_text = f"Up +{r_multiple:.1f}R. Trail SL up to ₹{recommended_sl:,.0f} to cut risk by 50%"
        else:
            recommended_sl = round_to_clean_int(initial_sl)
            action_badge = "✅ HOLD — ON TRACK"
            action_text = f"Position healthy. Keep stop at ₹{initial_sl:,.0f}"

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
        breakeven_p = round_to_clean_int(raw_be)
        if r_multiple >= 1.5 or pnl_pct >= 2.5:
            recommended_sl = max(recommended_sl, breakeven_p)
            if "HOLD" in action_badge:
                action_badge = "🟢 TRAIL TO BREAKEVEN"
                action_text = f"Target milestone (+{r_multiple:.1f}R)! Move SL to Breakeven ₹{breakeven_p:,.0f} (Risk-Free!)"

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
            "highest_ltp": highest_ltp,
            "highest_r": peak_r,
            "ema5": ema5,
            "jeff_badge": jeff_badge,
            "jeff_status": jeff_status
        })

    if th_dirty:
        try:
            with open(th_file, "w", encoding="utf-8") as f:
                json.dump(tracked_holdings, f, indent=2)
        except Exception:
            pass

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
