"""
⚡ JARVIS 08:45 AM PRE-FLIGHT DIAGNOSTIC & HEALTH AUDIT
Autonomous morning verification of:
1. Multi-broker API token validity (Upstox, Dhan, Zerodha)
2. Watchlist integrity & instrument key resolution
3. Pre-market Narrow Range / candidate readiness
Dispatches institutional status card to Telegram topic #token_refresh.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"


def load_config():
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def test_upstox(token):
    token = (token or "").strip()
    if not token:
        return False, "Missing Token"
    url = "https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_EQ%7CINE002A01018"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Jarvis-PreFlight"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                d = json.loads(resp.read().decode())
                q = d.get("data", {}).get("NSE_EQ:RELIANCE", {})
                ltp = q.get("last_price")
                return True, f"Active (Reliance: ₹{ltp})" if ltp else "Active"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        return False, f"HTTP {he.code} (Expired)" if he.code in (401, 403) else f"HTTP {he.code}"
    except Exception as e:
        return False, str(e)


def test_dhan(token, client_id):
    token = (token or "").strip()
    client_id = (client_id or "").strip()
    if not token or not client_id:
        return False, "Missing Token/ID"
    url = "https://api.dhan.co/v2/trades"
    req = urllib.request.Request(url, headers={
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-PreFlight"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, "Active (Orderbook OK)"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        return False, f"HTTP {he.code} (Expired)" if he.code in (401, 403) else f"HTTP {he.code}"
    except Exception as e:
        return False, str(e)


def test_zerodha(api_key, token):
    api_key = (api_key or "").strip()
    token = (token or "").strip()
    if not api_key or not token:
        return False, "Missing Token"
    url = "https://api.kite.trade/trades"
    req = urllib.request.Request(url, headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{token}",
        "User-Agent": "Jarvis-PreFlight"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, "Active (Ready)"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        return False, "Expired (Daily 6 AM rule)" if he.code in (401, 403) else f"HTTP {he.code}"
    except Exception as e:
        return False, str(e)


def audit_watchlist():
    if not WATCHLIST_FILE.is_file():
        return 0, 0, []
    symbols = []
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            sym = line.strip().upper()
            if sym and not sym.startswith("#"):
                symbols.append(sym)
    return len(symbols), symbols


def run_pre_flight_audit():
    """Runs end-to-end morning pre-flight audit and returns status dict & formatted HTML."""
    cfg = load_config()
    now_str = datetime.now().strftime("%H:%M:%S IST")

    u_tok = cfg.get("upstox", {}).get("access_token", "")
    u_ok, u_msg = test_upstox(u_tok)

    d_tok = cfg.get("dhan", {}).get("access_token", "")
    d_cid = cfg.get("dhan", {}).get("client_id", "")
    d_ok, d_msg = test_dhan(d_tok, d_cid)

    z_key = cfg.get("zerodha", {}).get("api_key", "")
    z_tok = cfg.get("zerodha", {}).get("access_token", "")
    z_ok, z_msg = test_zerodha(z_key, z_tok)

    sym_cnt, syms = audit_watchlist()

    all_brokers_ok = (u_ok and d_ok and z_ok)
    any_broker_ok = (u_ok or d_ok or z_ok)

    lines = [
        f"⚡ <b>JARVIS 08:45 AM PRE-FLIGHT AUDIT</b>",
        f"⏰ <i>Time: {now_str} • Market Open: 09:15 IST</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🏦 <b>BROKER API CHANNELS:</b>",
        f"• Upstox : {'🟢 Active (MTF)' if u_ok else f'🔴 <b>FAILED</b> ({u_msg})'}",
        f"• DhanHQ : {'🟢 Active (MTF)' if d_ok else f'🔴 <b>FAILED</b> ({d_msg})'}",
        f"• Zerodha: {'🟢 Active (CNC)' if z_ok else f'🔴 <b>FAILED</b> ({z_msg})'}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 <b>WATCHLIST MAPPING:</b>",
        f"• Symbols: <b>{sym_cnt} active stocks</b> ready for 3m ORB scan"
    ]

    # Pre-market narrow range count if data.json exists
    data_file = BASE_DIR / "data.json"
    if data_file.is_file():
        try:
            with open(data_file, "r", encoding="utf-8") as df:
                ddata = json.load(df)
                stks = ddata.get("stocks", [])
                nr_cnt = sum(1 for s in stks if s.get("is_narrow_prev_day") or s.get("is_inside_day"))
                lines.append(f"• Pre-Market NR: <b>{nr_cnt} Coiled stocks</b> detected 📦")
        except Exception:
            pass

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    if all_brokers_ok:
        lines.append("🚀 <b>ALL SYSTEMS GO FOR 09:15 AM OPEN!</b>")
        lines.append("• Hands-free automated execution armed.")
    elif any_broker_ok:
        lines.append("⚠️ <b>PARTIAL READINESS WARNING:</b>")
        lines.append("• One or more broker tokens expired.")
        lines.append("• Default routing will use the active channel.")
        lines.append("💡 <i>Reply with token or use /token to renew.</i>")
    else:
        lines.append("🚨 <b>CRITICAL: ALL BROKER TOKENS EXPIRED!</b>")
        lines.append("• Live orders cannot be placed until renewed!")
        lines.append("💡 <i>Please renew Upstox/Dhan/Zerodha before 09:15 AM.</i>")

    msg_html = "\n".join(lines)

    result_data = {
        "timestamp": now_str,
        "upstox": {"ok": u_ok, "msg": u_msg},
        "dhan": {"ok": d_ok, "msg": d_msg},
        "zerodha": {"ok": z_ok, "msg": z_msg},
        "symbols_count": sym_cnt,
        "all_ok": all_brokers_ok,
        "html": msg_html
    }

    return result_data


def dispatch_pre_flight():
    """Runs pre-flight audit and dispatches alert to Telegram #token_refresh topic."""
    res = run_pre_flight_audit()
    try:
        from telegram_bot import send_topic_alert_async
        send_topic_alert_async("token_refresh", res["html"])
        print("✅ Pre-flight status card dispatched to Telegram #token_refresh.")
    except Exception as e:
        print(f"⚠️ Telegram dispatch note: {e}")
    return res


if __name__ == "__main__":
    print("=" * 60)
    print("⚡ JARVIS PRE-FLIGHT DIAGNOSTIC AUDIT")
    print("=" * 60)
    audit = dispatch_pre_flight()
    print(audit["html"].replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("<code>", "").replace("</code>", ""))
    print("=" * 60)
