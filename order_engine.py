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

IST = timezone(timedelta(hours=5, minutes=30))

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
    sym_u = symbol.strip().upper()
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
    Fetches live quote for a symbol from Upstox API v2.
    Returns dict with ltp, day_low, day_high, prev_close, instrument_key.
    """
    try:
        from upstox_tablet_scanner import get_instrument_key
        instrument_key = get_instrument_key(symbol)
    except Exception:
        instrument_key = f"NSE_EQ|{symbol.upper()}"

    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()

    if not token:
        return None, "Upstox access token not found in config_credentials.json"

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
            prev_close = ohlc.get("close") or first_q.get("prev_close")

            if not ltp or ltp <= 0:
                return None, f"Could not retrieve valid LTP for {symbol}"

            return {
                "symbol": symbol.upper(),
                "instrument_key": instrument_key,
                "ltp": float(ltp),
                "day_low": float(day_low) if day_low else float(ltp * 0.985),
                "day_high": float(day_high) if day_high else float(ltp),
                "prev_close": float(prev_close) if prev_close else float(ltp),
                "timestamp": first_q.get("timestamp")
            }, None

    except urllib.error.HTTPError as he:
        return None, f"Upstox Quote HTTP {he.code}: {he.reason}"
    except Exception as e:
        return None, f"Quote fetch error: {str(e)}"


def calculate_order_sizing(quote_data, mode_arg="mod", sl_mode="lod"):
    """
    Calculates quantity, stop loss, exposure, and risk parameters.
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
        "sl_mode": sl_mode.upper()
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
        "is_amo": False
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
                err_msg = errors[0].get("message") if errors else "Order placement failed"
                return False, err_msg
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            errors = err_json.get("errors", [])
            err_msg = errors[0].get("message") if errors else f"HTTP {he.code}: {he.reason}"
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
        "afterMarketOrder": False
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST", headers={
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-Order-Engine"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            order_id = data.get("orderId")
            order_status = data.get("orderStatus", "SUBMITTED")
            if order_id:
                return True, f"{order_id} ({order_status})"
            err_msg = data.get("message") or data.get("remarks") or "Order placement failed"
            return False, err_msg
    except urllib.error.HTTPError as he:
        try:
            err_json = json.loads(he.read().decode())
            err_msg = err_json.get("message") or err_json.get("remarks") or f"HTTP {he.code}: {he.reason}"
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
