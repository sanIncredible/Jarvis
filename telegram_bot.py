#!/usr/bin/env python3
"""
⚡ JARVIS TELEGRAM COMMAND BOT & AUTOMATION ENGINE
=================================================
Enables complete remote management of Jarvis via Telegram:
1. Watchlist Management:
   - /add <SYMBOL...>    : Add stock(s) to watchlist & push to GitHub/Dashboard
   - /remove <SYMBOL...> : Remove stock(s) from watchlist & push to GitHub/Dashboard
   - /watchlist or /list : View all active watchlist stocks with TradingView links
2. Token Management:
   - /token or /tokens   : Check live health of Upstox, Dhan, Zerodha tokens
   - /upstox <TOKEN>     : Update Upstox access token & test live quote
   - /dhan <TOKEN>       : Update Dhan access token & test orderbook
   - /zerodha <TOKEN>    : Update Zerodha access token & test trades
   - Smart Auto-Detect   : Simply paste any JWT or token -> auto-detects broker, saves & verifies!
3. Scanner & Market Control:
   - /scan or /refresh   : Trigger instant market scan & push fresh data to dashboard
   - /regime             : View current market regime & capital allocation guidance
   - /help or /start     : Show full command menu and interactive guide
4. Security:
   - Restricts commands strictly to the authorized Telegram Chat ID in config_credentials.json.
"""

import os
import sys
import json
import time
import base64
import threading
import urllib.request
import urllib.error
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
WATCHLIST_FILE = SCRIPT_DIR / "watchlist.txt"
UPSTOX_TOKEN_FILE = SCRIPT_DIR / "upstoxtoken.txt"

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now():
    """Returns current datetime in IST."""
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


# ---------------------------------------------------------
# Configuration & Credentials Management
# ---------------------------------------------------------
def load_config():
    """Loads configuration from config_credentials.json."""
    for c_path in [CONFIG_FILE, SCRIPT_DIR / "credentials.json"]:
        if c_path.is_file():
            try:
                with open(c_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def save_config(cfg):
    """Saves updated configuration to config_credentials.json safely."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"❌ Error saving config_credentials.json: {e}")
        return False


def get_telegram_config():
    """Retrieves bot token and authorized chat ID."""
    cfg = load_config()
    tg = cfg.get("telegram", {})
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or tg.get("bot_token", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip() or str(tg.get("chat_id", "")).strip()
    return bot_token, chat_id


# ---------------------------------------------------------
# Telegram Bot API Helpers
# ---------------------------------------------------------
def send_telegram_msg(chat_id, text, parse_mode="HTML", reply_markup=None):
    """Sends a Telegram message to a specific chat."""
    bot_token, _ = get_telegram_config()
    if not bot_token or not chat_id:
        return False, "Missing bot_token or chat_id"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-Telegram-Bot"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, json.loads(resp.read().decode())
    except Exception as e:
        return False, str(e)


def edit_telegram_msg(chat_id, message_id, text, parse_mode="HTML", reply_markup=None):
    """Edits an existing Telegram message in place."""
    bot_token, _ = get_telegram_config()
    if not bot_token or not chat_id or not message_id:
        return False, "Missing parameters"

    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-Telegram-Bot"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, json.loads(resp.read().decode())
    except Exception as e:
        return False, str(e)


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    """Acknowledges an inline keyboard button tap in Telegram."""
    bot_token, _ = get_telegram_config()
    if not bot_token or not callback_query_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert
    }
    if text:
        payload["text"] = text

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-Telegram-Bot"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True
    except Exception:
        return False


def register_telegram_commands():
    """Registers bot commands with Telegram API for autocomplete menu."""
    bot_token, _ = get_telegram_config()
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    commands = [
        {"command": "buy", "description": "🛒 Place MTF/Equity Order (Upstox/Dhan/Zerodha)"},
        {"command": "positions", "description": "📊 Live multi-broker positions & open P&L"},
        {"command": "exit", "description": "🔴 Quick exit/square-off open positions"},
        {"command": "broker", "description": "🏦 View or switch default broker (Upstox/Dhan/Zerodha)"},
        {"command": "watchlist", "description": "📋 View active watchlist & TV chart links"},
        {"command": "add", "description": "➕ Add stock ticker(s) to scanner watchlist"},
        {"command": "remove", "description": "➖ Remove stock ticker(s) from watchlist"},
        {"command": "token", "description": "🎟️ Check broker token health (Upstox/Dhan/Zerodha)"},
        {"command": "scan", "description": "⚡ Trigger instant market scan & cloud push"},
        {"command": "regime", "description": "🧭 View market regime & risk guidance"},
        {"command": "help", "description": "📖 Show complete command cockpit & manual"}
    ]
    data = json.dumps({"commands": commands}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-Telegram-Bot"
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True
    except Exception:
        return False


# ---------------------------------------------------------
# Watchlist Operations
# ---------------------------------------------------------
SYMBOL_ALIASES = {
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


def read_watchlist_symbols():
    """Reads all active symbols from watchlist.txt."""
    if not WATCHLIST_FILE.is_file():
        return []
    syms = []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                l = line.strip().upper()
                if not l or l.startswith("#"):
                    continue
                for s in l.replace(",", " ").split():
                    canonical = SYMBOL_ALIASES.get(s, s)
                    if canonical not in syms:
                        syms.append(canonical)
    except Exception as e:
        print(f"Error reading watchlist: {e}")
    return syms


def write_watchlist_symbols(symbols):
    """Writes updated symbols back to watchlist.txt cleanly."""
    lines = [
        "# Upstox 3m ORB Scanner Watchlist",
        "# Add or remove NSE stock tickers below (one per line, or space/comma separated)",
        ""
    ]
    seen = set()
    for s in symbols:
        s_u = s.strip().upper()
        if s_u and s_u not in seen and not s_u.startswith("#"):
            seen.add(s_u)
            lines.append(s_u)

    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        print(f"Error writing watchlist: {e}")
        return False


def push_watchlist_and_data_to_github():
    """Pushes watchlist.txt and data.json to GitHub repository via REST API."""
    try:
        from upstox_tablet_scanner import load_github_config, sync_file_to_github_api
        gh_cfg = load_github_config()
        if gh_cfg:
            syms = read_watchlist_symbols()
            sync_file_to_github_api(gh_cfg, "watchlist.txt", f"Update watchlist via Telegram ({len(syms)} symbols)")
            if (SCRIPT_DIR / "data.json").is_file():
                sync_file_to_github_api(gh_cfg, "data.json", f"Sync data.json via Telegram ({len(syms)} symbols)")
            return True
    except Exception as e:
        print(f"GitHub Push notice: {e}")
    return False


def trigger_immediate_rescan():
    """Runs a fresh scan and updates static html / data.json."""
    try:
        from upstox_tablet_scanner import scan_watchlist, export_static_html
        results = scan_watchlist()
        now_str = get_ist_now().strftime("%H:%M:%S IST")
        export_static_html(results, now_str, 5000)
        push_watchlist_and_data_to_github()
        return results
    except Exception as e:
        print(f"Immediate rescan note: {e}")
        return None


# ---------------------------------------------------------
# Token Health & Verification Engine
# ---------------------------------------------------------
def test_upstox_token(token):
    """Tests live Upstox access token by querying RELIANCE LTP."""
    token = token.strip()
    if not token:
        return False, "Token is empty"
    url = "https://api.upstox.com/v2/market-quote/ltp?instrument_key=NSE_EQ|INE002A01018"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Jarvis-Token-Checker"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                d = json.loads(resp.read().decode())
                data_obj = d.get("data", {})
                first_k = next(iter(data_obj.values()), {}) if data_obj else {}
                ltp = first_k.get("last_price")
                return True, f"Active (RELIANCE LTP: ₹{ltp})" if ltp else "Active"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        return False, f"HTTP {he.code} ({he.reason})"
    except Exception as e:
        return False, str(e)


def test_dhan_token(token, client_id):
    """Tests live Dhan access token by querying orderbook/trades."""
    token = token.strip()
    client_id = client_id.strip()
    if not token or not client_id:
        return False, "Missing token or client_id"
    url = "https://api.dhan.co/v2/trades"
    req = urllib.request.Request(url, headers={
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-Token-Checker"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, "Active (Orderbook OK)"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        if he.code == 401:
            return False, "Expired (Needs 30-day renewal)"
        return False, f"HTTP {he.code}"
    except Exception as e:
        return False, str(e)


def test_zerodha_token(api_key, token):
    """Tests live Zerodha Kite access token."""
    api_key = api_key.strip()
    token = token.strip()
    if not api_key or not token:
        return False, "Missing api_key or token"
    url = "https://api.kite.trade/trades"
    req = urllib.request.Request(url, headers={
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{token}",
        "User-Agent": "Jarvis-Token-Checker"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, "Active (Ready for trades)"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        if he.code in (401, 403):
            return False, "Expired (Daily 6 AM rule)"
        return False, f"HTTP {he.code}"
    except Exception as e:
        return False, str(e)


def detect_token_type(raw_token):
    """Intelligently detects whether a token string is Upstox, Dhan, or Zerodha."""
    raw_token = raw_token.strip()
    if raw_token.startswith("eyJ"):
        try:
            parts = raw_token.split(".")
            if len(parts) >= 2:
                payload = parts[1]
                payload += "=" * (-len(payload) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
                iss = str(data.get("iss", "")).lower()
                if "dhan" in iss:
                    return "dhan", data
                if "udapi" in iss or "upstox" in iss:
                    return "upstox", data
                if "sub" in data and len(str(data.get("sub", ""))) == 6:
                    return "upstox", data
        except Exception:
            pass
    # Zerodha tokens are 32-character hexadecimal/alphanumeric strings
    if len(raw_token) == 32 and raw_token.isalnum():
        return "zerodha", None
    return "unknown", None


def update_broker_token(broker_name, token):
    """Updates config_credentials.json (and upstoxtoken.txt if Upstox) and verifies immediately."""
    broker_name = broker_name.lower().strip()
    cfg = load_config()

    if broker_name == "upstox":
        cfg.setdefault("upstox", {})["access_token"] = token
        save_config(cfg)
        # Also write upstoxtoken.txt
        try:
            with open(UPSTOX_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(token)
        except Exception:
            pass
        ok, msg = test_upstox_token(token)
        return ok, broker_name, msg

    elif broker_name == "dhan":
        cfg.setdefault("dhan", {})["access_token"] = token
        save_config(cfg)
        cid = cfg.get("dhan", {}).get("client_id", "")
        ok, msg = test_dhan_token(token, cid)
        return ok, broker_name, msg

    elif broker_name == "zerodha":
        cfg.setdefault("zerodha", {})["access_token"] = token
        save_config(cfg)
        ak = cfg.get("zerodha", {}).get("api_key", "")
        ok, msg = test_zerodha_token(ak, token)
        return ok, broker_name, msg

    return False, broker_name, f"Unknown broker '{broker_name}'"


# ---------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------
def handle_add_command(args_text):
    """Handles /add <SYMBOL...>"""
    if not args_text.strip():
        return (
            "⚠️ <b>Usage:</b> <code>/add &lt;SYMBOL&gt;</code>\n"
            "Example: <code>/add TATAMOTORS</code> or <code>/add BEL, HAL, INFY</code>"
        )

    current_syms = read_watchlist_symbols()
    current_set = set(current_syms)

    raw_items = args_text.replace(",", " ").split()
    added = []
    already_present = []

    for item in raw_items:
        s_u = item.strip().upper()
        if not s_u or s_u.startswith("#"):
            continue
        canonical = SYMBOL_ALIASES.get(s_u, s_u)
        if canonical in current_set:
            already_present.append(canonical)
        else:
            current_syms.append(canonical)
            current_set.add(canonical)
            added.append(canonical)

    if not added and already_present:
        return f"ℹ️ Already in watchlist: <b>{', '.join(already_present)}</b> (Total: {len(current_syms)})"

    if not added:
        return "⚠️ No valid symbols provided to add."

    # Write updated list
    write_watchlist_symbols(current_syms)

    # Push to GitHub & Trigger Rescan in Background Thread
    threading.Thread(target=trigger_immediate_rescan, daemon=True).start()

    res = (
        f"✅ <b>Added to Watchlist ({len(added)}):</b> <b>{', '.join(added)}</b>\n"
        f"📋 <b>Total Stocks:</b> {len(current_syms)}\n"
    )
    if already_present:
        res += f"ℹ️ <i>Already present: {', '.join(already_present)}</i>\n"
    res += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>Background scan & GitHub Cloud sync triggered!</i>\n"
        "📊 <a href='https://sanincredible.github.io/Jarvis/'>Open Live Dashboard</a>"
    )
    return res


def handle_remove_command(args_text):
    """Handles /remove or /del <SYMBOL...>"""
    if not args_text.strip():
        return (
            "⚠️ <b>Usage:</b> <code>/remove &lt;SYMBOL&gt;</code>\n"
            "Example: <code>/remove PVRINOX</code> or <code>/del FSL, OAL</code>"
        )

    current_syms = read_watchlist_symbols()
    raw_items = [s.strip().upper() for s in args_text.replace(",", " ").split() if s.strip()]

    removed = []
    not_found = []

    for item in raw_items:
        canonical = SYMBOL_ALIASES.get(item, item)
        matched = None
        for s in current_syms:
            if s.upper() == canonical or s.upper() == item:
                matched = s
                break
        if matched:
            current_syms.remove(matched)
            removed.append(matched)
        else:
            not_found.append(item)

    if not removed and not_found:
        return f"⚠️ Symbol(s) not found in watchlist: <b>{', '.join(not_found)}</b>"

    write_watchlist_symbols(current_syms)

    # Push to GitHub & Trigger Rescan in Background Thread
    threading.Thread(target=trigger_immediate_rescan, daemon=True).start()

    res = (
        f"🗑️ <b>Removed from Watchlist:</b> <b>{', '.join(removed)}</b>\n"
        f"📋 <b>Remaining Stocks:</b> {len(current_syms)}\n"
    )
    if not_found:
        res += f"ℹ️ <i>Not in list: {', '.join(not_found)}</i>\n"
    res += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <a href='https://sanincredible.github.io/Jarvis/'>Open Live Dashboard</a>"
    )
    return res


def handle_watchlist_command():
    """Handles /watchlist or /list"""
    syms = read_watchlist_symbols()
    if not syms:
        return "📋 <b>Watchlist is currently empty.</b>\nAdd symbols using <code>/add &lt;SYMBOL&gt;</code>"

    lines = [
        f"📋 <b>ACTIVE WATCHLIST ({len(syms)} Stocks)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, s in enumerate(syms, 1):
        tv_link = f"https://in.tradingview.com/chart/?symbol=NSE:{s}"
        lines.append(f"<b>{idx}.</b> <a href='{tv_link}'>{s}</a>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Use /add &lt;SYM&gt; to add or /remove &lt;SYM&gt; to delete.</i>")
    lines.append("📊 <a href='https://sanincredible.github.io/Jarvis/'>Open Live Dashboard</a>")
    return "\n".join(lines)


def handle_token_status_command():
    """Handles /token, /tokens, or /status"""
    cfg = load_config()

    lines = [
        "⚡ <b>JARVIS BROKER TOKENS & SYSTEM STATUS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    # 1. Upstox
    u_tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if not u_tok and UPSTOX_TOKEN_FILE.is_file():
        try:
            with open(UPSTOX_TOKEN_FILE, "r", encoding="utf-8") as f:
                u_tok = f.read().strip()
        except Exception:
            pass
    if u_tok:
        ok_u, msg_u = test_upstox_token(u_tok)
        badge_u = "✅ ACTIVE" if ok_u else "❌ EXPIRED"
        lines.append(f"• <b>Upstox Feed :</b> {badge_u} ({msg_u})")
    else:
        lines.append("• <b>Upstox Feed :</b> ⚠️ NOT CONFIGURED")

    # 2. Dhan
    d_tok = cfg.get("dhan", {}).get("access_token", "").strip()
    d_cid = cfg.get("dhan", {}).get("client_id", "").strip()
    if d_tok and d_cid:
        ok_d, msg_d = test_dhan_token(d_tok, d_cid)
        badge_d = "✅ ACTIVE" if ok_d else "⚠️ EXPIRED"
        lines.append(f"• <b>DhanHQ     :</b> {badge_d} ({msg_d})")
    else:
        lines.append("• <b>DhanHQ     :</b> ⚠️ NOT CONFIGURED")

    # 3. Zerodha
    z_tok = cfg.get("zerodha", {}).get("access_token", "").strip()
    z_ak = cfg.get("zerodha", {}).get("api_key", "").strip()
    if z_tok and z_ak:
        ok_z, msg_z = test_zerodha_token(z_ak, z_tok)
        badge_z = "✅ ACTIVE" if ok_z else "⚠️ EXPIRED"
        lines.append(f"• <b>Zerodha Kite:</b> {badge_z} ({msg_z})")
    else:
        lines.append("• <b>Zerodha Kite:</b> ⚠️ NOT CONFIGURED")

    # Watchlist & Regime
    syms = read_watchlist_symbols()
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📋 <b>Watchlist  :</b> {len(syms)} active stocks")

    regime_file = SCRIPT_DIR / "market_regime.json"
    if regime_file.is_file():
        try:
            with open(regime_file, "r", encoding="utf-8") as f:
                r_data = json.load(f)
                r_label = r_data.get("state_label", "Unknown")
                lines.append(f"🧭 <b>Regime     :</b> {r_label}")
        except Exception:
            pass

    lines.append(f"🕒 <b>Checked At :</b> {get_ist_now().strftime('%H:%M:%S IST')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>To update: /upstox &lt;token&gt; or /dhan &lt;token&gt;</i>")
    return "\n".join(lines)


def handle_update_token_command(broker_name, token_str):
    """Handles explicit /upstox <token>, /dhan <token>, /zerodha <token>"""
    if not token_str.strip():
        return f"⚠️ <b>Usage:</b> <code>/{broker_name} &lt;TOKEN&gt;</code>"

    token_clean = token_str.strip()
    ok, b_name, msg = update_broker_token(broker_name, token_clean)

    if ok:
        return (
            f"✅ <b>{b_name.upper()} Token Successfully Updated & Verified!</b>\n"
            f"• <b>Status:</b> 🟢 ACTIVE\n"
            f"• <b>Verification:</b> {msg}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <i>The scanner engine has adopted the new credentials immediately.</i>"
        )
    else:
        return (
            f"⚠️ <b>{b_name.upper()} Token Saved, But Verification Notice:</b>\n"
            f"• <b>Test Result:</b> {msg}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Please verify that your broker session is active.</i>"
        )


def handle_pasted_token(raw_text):
    """Auto-detects and updates any pasted JWT token or Zerodha token."""
    b_type, meta = detect_token_type(raw_text)
    if b_type == "unknown":
        return None

    ok, b_name, msg = update_broker_token(b_type, raw_text.strip())
    status_icon = "🟢 ACTIVE" if ok else "⚠️ SAVED (Notice)"
    return (
        f"🤖 <b>Auto-Detected {b_name.upper()} Token!</b>\n"
        f"• <b>Status:</b> {status_icon}\n"
        f"• <b>Verification:</b> {msg}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <i>Credentials saved to config_credentials.json.</i>"
    )


def handle_scan_command():
    """Handles /scan or /refresh"""
    threading.Thread(target=trigger_immediate_rescan, daemon=True).start()
    return (
        "⚡ <b>Instant Market Scan Initiated!</b>\n"
        "Compiling 3m ORB, Institutional Scores, and PDH breaches across all watchlist stocks.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <a href='https://sanincredible.github.io/Jarvis/'>View Live Dashboard Results</a>"
    )


def handle_regime_command():
    """Handles /regime"""
    regime_file = SCRIPT_DIR / "market_regime.json"
    if not regime_file.is_file():
        return "🧭 Market regime file not yet generated. Run scanner to compile."

    try:
        with open(regime_file, "r", encoding="utf-8") as f:
            r = json.load(f)
        return (
            f"🧭 <b>CURRENT MARKET REGIME: {r.get('state_label', 'N/A')}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Guidance :</b> {r.get('guidance', 'N/A')}\n"
            f"• <b>Swing Alloc :</b> {r.get('swing_allocation_pct', 0)}%\n"
            f"• <b>Intra Risk  :</b> ₹{r.get('intraday_risk_per_trade', 1000):,}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 <i>Updated: {r.get('updated_at', 'Today')}</i>"
        )
    except Exception as e:
        return f"⚠️ Error loading regime: {e}"


def handle_help_command():
    """Handles /help or /start"""
    return (
        "⚡ <b>JARVIS TELEGRAM COMMAND COCKPIT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛒 <b>MTF Broker Orders:</b>\n"
        "• <code>/buy &lt;SYM&gt; [mode] [sl]</code> — Place MTF Order with LoD SL\n"
        "  - <code>/buy RELIANCE agg</code> — ₹1.5L Aggressive Size\n"
        "  - <code>/buy RELIANCE mod</code> — ₹1.0L Moderate Size (Default)\n"
        "  - <code>/buy RELIANCE 50k</code> — ₹50K Conservative / 50% Risk\n"
        "  - <code>/buy RELIANCE mod regime</code> — Regime Capped Risk SL\n"
        "  - <code>/buy RELIANCE agg confirm</code> — Instant 1-shot execution\n"
        "  - <i>Interactive buttons with LoD Stop-Loss & Risk calculation!</i>\n\n"
        "📊 <b>Positions & Portfolio:</b>\n"
        "• <code>/positions</code> or <code>/pos</code> — Live open positions & real-time P&L\n"
        "• <code>/exit &lt;SYM&gt; [50%|all]</code> — 1-Tap quick exit/square-off\n"
        "• <code>/broker</code> — View/switch default broker (Upstox/Dhan/Zerodha)\n\n"
        "📋 <b>Watchlist Commands:</b>\n"
        "• <code>/add &lt;SYMBOL...&gt;</code> — Add stock(s) to scanner watchlist\n"
        "• <code>/remove &lt;SYMBOL...&gt;</code> — Remove stock(s) from watchlist\n"
        "• <code>/watchlist</code> — Show full active watchlist & TV links\n\n"
        "🎟️ <b>Token Management:</b>\n"
        "• <code>/token</code> — Check live health of all broker tokens\n"
        "• <code>/upstox &lt;TOKEN&gt;</code> — Update Upstox token & test feed\n"
        "• <code>/dhan &lt;TOKEN&gt;</code> — Update DhanHQ access token\n"
        "• <code>/zerodha &lt;TOKEN&gt;</code> — Update Zerodha Kite token\n"
        "• <i>Tip: You can also just PASTE any token here directly!</i>\n\n"
        "⚡ <b>Scanner & Market:</b>\n"
        "• <code>/scan</code> — Trigger instant scan & push to cloud\n"
        "• <code>/regime</code> — Current market regime & risk allocation\n"
        "• <code>/status</code> — System, tokens & scanner status\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <a href='https://sanincredible.github.io/Jarvis/'>Open Live Web Dashboard</a>"
    )


def build_buy_preview(symbol, mode, sl_mode, broker):
    """Builds interactive preview text and inline keyboard for any broker."""
    from order_engine import fetch_live_quote, calculate_order_sizing

    quote_data, err = fetch_live_quote(symbol)
    if not quote_data:
        return f"❌ <b>Quote Failed for {symbol}:</b>\n{err}", None

    calc = calculate_order_sizing(quote_data, mode_arg=mode, sl_mode=sl_mode)
    if calc["quantity"] <= 0:
        return (
            f"❌ <b>Sizing Error for {symbol}:</b>\n"
            f"LTP (₹{calc['ltp']}) exceeds allocated size (₹{calc['target_size']:,}).\n"
            f"Cannot buy even 1 share with {calc['mode_label']} mode.",
            None
        )

    b_label = "Upstox MTF" if broker == "upstox" else ("DhanHQ MTF" if broker == "dhan" else "Zerodha CNC (Delivery)")
    regime_warning = f"\n{calc['regime_note']}" if calc.get("regime_note") else ""

    checklist_data = calc.get("checklist", {})
    checklist_items = checklist_data.get("checklist", [])
    warnings = checklist_data.get("warnings", [])
    scanner_sig = checklist_data.get("scanner_signal")

    checklist_lines = [f"• {c['text']}" for c in checklist_items]
    checklist_block = "\n".join(checklist_lines)

    if warnings:
        warn_lines = "\n".join([f"  {i+1}. <i>{w}</i>" for i, w in enumerate(warnings)])
        alert_block = (
            f"\n🚨 <b>STRATEGY WARNINGS ({len(warnings)} Unsatisfied):</b>\n"
            f"{warn_lines}\n"
        )
    else:
        alert_block = "\n⭐ <b>A+ SETUP: All Strategy Checklist Rules Satisfied!</b>\n"

    sig_line = f"🏷️ <b>Scanner Signal:</b> <code>{scanner_sig}</code>\n" if scanner_sig else ""

    canonical_sym = quote_data["symbol"]
    sym_display = f"{canonical_sym} (<i>{symbol}</i>)" if symbol.upper() != canonical_sym else canonical_sym

    preview_text = (
        "⚡ <b>JARVIS ORDER PREVIEW</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Symbol:</b> <b>{sym_display}</b> (NSE Equity)\n"
        f"🏦 <b>Selected Broker:</b> <b>{b_label}</b>\n"
        f"💰 <b>Size Mode:</b> {calc['mode_label']}\n"
        f"📈 <b>Live LTP:</b> ₹{calc['ltp']:.2f}\n"
        f"🎯 <b>Calculated Qty:</b> <b>{calc['quantity']} shares</b>\n"
        f"💼 <b>Actual Exposure:</b> ₹{calc['actual_exposure']:,}\n"
        f"🛑 <b>Stop Loss:</b> <b>₹{calc['stop_loss']}</b> ({calc['sl_mode']}: -{calc['risk_pct']}%)\n"
        f"⚠️ <b>Total Risk ₹:</b> ₹{calc['total_risk_inr']:,}\n"
        f"{sig_line}"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>STRATEGY CHECKLIST ({checklist_data.get('passed_count', 0)}/{checklist_data.get('total_count', 7)} Passed):</b>\n"
        f"{checklist_block}\n"
        f"{alert_block}"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Reply <code>/buy {canonical_sym} {mode} {broker} confirm</code> or tap below:</i>"
    )

    btn_icon = "⚠️" if warnings else "✅"
    warn_tag = f" ({len(warnings)} Warns)" if warnings else ""
    btn_text = f"{btn_icon} Execute on {broker.upper()} ({calc['quantity']} shs{warn_tag})"

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": btn_text, "callback_data": f"buy_exec:{canonical_sym}:{mode}:{sl_mode}:{broker}"}
            ],
            [
                {"text": f"{'👉 ' if broker == 'upstox' else ''}Upstox", "callback_data": f"buy_switch:{canonical_sym}:{mode}:{sl_mode}:upstox"},
                {"text": f"{'👉 ' if broker == 'dhan' else ''}DhanHQ", "callback_data": f"buy_switch:{canonical_sym}:{mode}:{sl_mode}:dhan"},
                {"text": f"{'👉 ' if broker == 'zerodha' else ''}Zerodha", "callback_data": f"buy_switch:{canonical_sym}:{mode}:{sl_mode}:zerodha"}
            ],
            [
                {"text": "❌ Cancel Order", "callback_data": f"buy_cancel:{canonical_sym}"}
            ]
        ]
    }

    return preview_text, reply_markup


def handle_broker_command(args):
    """Handles /broker command to view or switch default broker."""
    from order_engine import get_default_broker, set_default_broker, SUPPORTED_BROKERS, load_config
    arg = args.strip().lower()
    if arg:
        if arg in SUPPORTED_BROKERS:
            ok, b = set_default_broker(arg)
            if ok:
                b_name = "Upstox (MTF)" if b == "upstox" else ("DhanHQ (MTF)" if b == "dhan" else "Zerodha (CNC)")
                return f"✅ <b>Default Broker Updated:</b> Now set to <b>{b_name}</b> for all <code>/buy</code> orders!"
            return f"❌ Failed to set default broker: {b}"
        else:
            return f"❓ Unknown broker: <code>{arg}</code>. Supported brokers: <code>upstox</code>, <code>dhan</code>, <code>zerodha</code>."

    curr_broker = get_default_broker()
    cfg = load_config()
    u_ok = bool(cfg.get("upstox", {}).get("access_token"))
    d_ok = bool(cfg.get("dhan", {}).get("access_token"))
    z_ok = bool(cfg.get("zerodha", {}).get("access_token"))

    u_stat = "🟢 Active (MTF)" if u_ok else "⚠️ No Token"
    d_stat = "🟢 Active (MTF)" if d_ok else "⚠️ No Token"
    z_stat = "🟢 Active (CNC)" if z_ok else "⚠️ No Token"

    curr_display = "UPSTOX (MTF)" if curr_broker == "upstox" else ("DHANHQ (MTF)" if curr_broker == "dhan" else "ZERODHA (CNC)")

    return (
        f"🏦 <b>CURRENT DEFAULT BROKER: {curr_display}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Upstox</b>  : {u_stat} {'👈 [DEFAULT]' if curr_broker == 'upstox' else ''}\n"
        f"• <b>DhanHQ</b>  : {d_stat} {'👈 [DEFAULT]' if curr_broker == 'dhan' else ''}\n"
        f"• <b>Zerodha</b> : {z_stat} {'👈 [DEFAULT]' if curr_broker == 'zerodha' else ''}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>To switch default broker:</b>\n"
        "• <code>/broker upstox</code>\n"
        "• <code>/broker dhan</code>\n"
        "• <code>/broker zerodha</code>\n\n"
        "<i>Or specify directly when placing orders:</i>\n"
        "• <code>/buy INFY agg dhan</code>\n"
        "• <code>/buy RELIANCE mod upstox</code>\n"
        "• <code>/buy TCS 50k zerodha</code>"
    )


def handle_positions_command():
    """
    Fetches open positions across Upstox, Dhan, and Zerodha and returns
    formatted summary card with inline refresh keyboard.
    """
    from order_engine import fetch_all_positions

    positions, totals, broker_status = fetch_all_positions()

    now_str = get_ist_now().strftime("%d %b %H:%M:%S IST")

    # Format broker status summary
    status_parts = []
    for b in ("dhan", "upstox", "zerodha"):
        st = broker_status.get(b, "N/A")
        if "OK" in st:
            status_parts.append(f"{b.capitalize()} 🟢")
        elif "Not configured" in st:
            status_parts.append(f"{b.capitalize()} ⚪")
        else:
            status_parts.append(f"{b.capitalize()} ⚠️")
    status_str = " | ".join(status_parts)

    lines = [
        "📊 <b>JARVIS LIVE PORTFOLIO & POSITIONS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if not positions:
        lines.append("💤 <b>No Open Positions Active</b>")
        lines.append("All multi-broker portfolios are currently 100% in cash.")
    else:
        for p in positions:
            sym = p["symbol"]
            broker = p["broker"]
            prod = p["product"]
            qty = p["qty"]
            avg_p = p["avg_price"]
            ltp = p["ltp"]
            pnl = p["pnl"]
            pnl_pct = p["pnl_pct"]
            exposure = p["exposure"]

            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            pnl_str = f"+₹{pnl:,.2f}" if pnl > 0 else (f"-₹{abs(pnl):,.2f}" if pnl < 0 else "₹0.00")
            pct_sign = "+" if pnl_pct > 0 else ""
            qty_sign = "+" if qty > 0 else ""

            card = (
                f"{pnl_icon} <b>{sym}</b> [<code>{broker} • {prod}</code>]\n"
                f"  • <b>Qty:</b> {qty_sign}{qty} @ ₹{avg_p:,.2f} | <b>LTP:</b> ₹{ltp:,.2f}\n"
                f"  • <b>P&L:</b> {pnl_icon} <b>{pnl_str}</b> ({pct_sign}{pnl_pct:.2f}%)\n"
                f"  • <b>Exposure:</b> ₹{exposure:,.2f}"
            )
            lines.append(card)

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    tot_pnl = totals["total_pnl"]
    tot_pnl_icon = "🟢" if tot_pnl >= 0 else "🔴"
    tot_pnl_str = f"+₹{tot_pnl:,.2f}" if tot_pnl > 0 else (f"-₹{abs(tot_pnl):,.2f}" if tot_pnl < 0 else "₹0.00")

    lines.append("💼 <b>PORTFOLIO TOTALS:</b>")
    lines.append(f"• <b>Open Positions:</b> {totals['count']}")
    lines.append(f"• <b>Total Net P&L:</b> {tot_pnl_icon} <b>{tot_pnl_str}</b>")
    lines.append(f"• <b>Total Exposure:</b> ₹{totals['total_exposure']:,.2f}")
    lines.append(f"• <b>Brokers Synced:</b> {status_str}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕒 <i>Updated: {now_str}</i>")

    message_text = "\n".join(lines)

    # Build inline keyboard with exit buttons + refresh
    kb_rows = []
    if positions:
        exit_btns = []
        for p in positions:
            b_code = p["broker"][:1].lower()  # 'd', 'z', 'u'
            sym = p["symbol"]
            btn_label = f"🔴 Exit {sym[:10]}" if len(sym) > 10 else f"🔴 Exit {sym}"
            exit_btns.append({"text": btn_label, "callback_data": f"ex_p:{b_code}:{sym}"})

        for i in range(0, len(exit_btns), 2):
            kb_rows.append(exit_btns[i:i+2])

    kb_rows.append([{"text": "🔄 Refresh Positions", "callback_data": "pos_refresh"}])
    reply_markup = {"inline_keyboard": kb_rows}

    return message_text, reply_markup


def build_exit_preview(symbol, broker_code=None):
    """Builds confirmation card and 100%/50% exit buttons for a position."""
    from order_engine import fetch_all_positions
    all_pos, _, _ = fetch_all_positions()

    sym_clean = symbol.strip().upper()
    b_filter = {"d": "DHAN", "z": "ZERODHA", "u": "UPSTOX"}.get(broker_code, broker_code)
    if b_filter:
        b_filter = b_filter.upper()

    target_pos = None
    for p in all_pos:
        p_sym = p["symbol"].upper()
        if p_sym == sym_clean or p_sym.startswith(sym_clean) or sym_clean.startswith(p_sym):
            if b_filter and p["broker"].upper() != b_filter:
                continue
            target_pos = p
            break

    if not target_pos:
        return f"❌ <b>Position Not Found:</b> No active position found for <code>{symbol}</code>.", None

    sym = target_pos["symbol"]
    broker = target_pos["broker"]
    b_code = broker[:1].lower()
    abs_qty = abs(target_pos["qty"])
    half_qty = max(1, abs_qty // 2)
    ltp = target_pos["ltp"]
    pnl = target_pos["pnl"]
    pnl_pct = target_pos["pnl_pct"]
    prod = target_pos.get("product", "MTF")

    pnl_icon = "🟢" if pnl >= 0 else "🔴"
    pnl_str = f"+₹{pnl:,.2f}" if pnl > 0 else (f"-₹{abs(pnl):,.2f}" if pnl < 0 else "₹0.00")
    pct_sign = "+" if pnl_pct > 0 else ""
    est_val = round(abs_qty * ltp, 2)

    text = (
        "⚠️ <b>CONFIRM POSITION EXIT / SQUARE-OFF</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Symbol:</b> <b>{sym}</b>\n"
        f"🏦 <b>Broker:</b> <b>{broker}</b> ({prod})\n"
        f"📦 <b>Open Quantity:</b> <b>{abs_qty} shares</b>\n"
        f"📈 <b>Live LTP:</b> ₹{ltp:,.2f}\n"
        f"💰 <b>Total Est. Value:</b> ~₹{est_val:,.2f}\n"
        f"📊 <b>Unrealized P&L:</b> {pnl_icon} <b>{pnl_str}</b> ({pct_sign}{pnl_pct:.2f}%)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Select quantity to execute MARKET sell immediately:</i>"
    )

    btn_row1 = [
        {"text": f"🔴 Exit 100% ({abs_qty} shs)", "callback_data": f"ex_x:{b_code}:{sym}:all"}
    ]
    if abs_qty > 1:
        btn_row1.append({"text": f"🟡 Exit 50% ({half_qty} shs)", "callback_data": f"ex_x:{b_code}:{sym}:half"})

    reply_markup = {
        "inline_keyboard": [
            btn_row1,
            [
                {"text": "📊 Back to Positions", "callback_data": "pos_refresh"},
                {"text": "❌ Cancel", "callback_data": f"ex_c:{sym}"}
            ]
        ]
    }
    return text, reply_markup


def handle_exit_command(args):
    """
    Handles /exit or /close or /squareoff command.
    Syntax:
      /exit -> Shows list of open positions with 1-tap exit buttons
      /exit <SYM> [all|half|<qty>] [dhan|zerodha|upstox] [confirm]
    """
    from order_engine import execute_broker_exit
    if not args.strip():
        text, markup = handle_positions_command()
        intro = (
            "🔴 <b>JARVIS ONE-TAP POSITION EXIT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Tap any position button below to square off or type:</i>\n"
            "• <code>/exit MOTHERSON 100% confirm</code>\n"
            "• <code>/exit ABDL 50% confirm</code>\n\n"
        )
        return intro + text, markup

    tokens = [t.strip() for t in args.split() if t.strip()]
    raw_sym = tokens[0].upper()
    sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)

    ratio = "all"
    broker = None
    auto_confirm = False

    for tok in tokens[1:]:
        tok_lower = tok.lower()
        if tok_lower in ("confirm", "now", "exec", "yes"):
            auto_confirm = True
        elif tok_lower in ("all", "100%", "full", "100"):
            ratio = "all"
        elif tok_lower in ("half", "50%", "halfway", "50"):
            ratio = "half"
        elif tok_lower in ("dhan", "zerodha", "upstox"):
            broker = tok_lower
        elif tok.isdigit():
            ratio = int(tok)

    if auto_confirm:
        success, res = execute_broker_exit(sym, broker=broker, qty_ratio=ratio)
        if success:
            rem = res.get("remaining_qty", 0)
            rem_str = f"• <b>Remaining Qty:</b> {rem} shares\n" if rem > 0 else "• <b>Status:</b> Position Fully Closed (0 shares)\n"
            receipt = (
                f"🎉 <b>POSITION EXITED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Sold Qty:</b> <b>{res['quantity']} shares</b> @ MARKET\n"
                f"💼 <b>Product:</b> {res['product']}\n"
                f"{rem_str}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Market order submitted to exchange.</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📊 View Updated Positions", "callback_data": "pos_refresh"}]
                ]
            }
            return receipt, markup
        else:
            return (
                f"❌ <b>EXIT ORDER FAILED</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {sym}\n"
                f"⚠️ <b>Error:</b> {res}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Check token validity or broker terminal.</i>"
            )

    return build_exit_preview(sym, broker)


def handle_buy_command(args, from_chat_id):
    """
    Handles /buy or /mtf command across Upstox, Dhan, or Zerodha.
    Syntax: /buy <SYMBOL> [agg|mod|50k] [lod|regime] [upstox|dhan|zerodha] [confirm]
    """
    if not args:
        return (
            "🛒 <b>JARVIS MULTI-BROKER ORDER PLACEMENT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b> <code>/buy &lt;SYMBOL&gt; [mode] [sl] [broker] [confirm]</code>\n\n"
            "<b>Sizing Modes:</b>\n"
            "• <code>agg</code> / <code>1.5L</code> — Aggressive (₹1,50,000 exposure)\n"
            "• <code>mod</code> / <code>1L</code>   — Moderate (₹1,00,000 exposure - Default)\n"
            "• <code>50k</code> / <code>low</code>  — Conservative / 50% Risk (₹50,000 exposure)\n"
            "• Custom: e.g. <code>75k</code>, <code>200000</code>\n\n"
            "<b>Stop Loss Options:</b>\n"
            "• <code>lod</code> — Low of Day (Default)\n"
            "• <code>regime</code> — Adjusted based on Market Regime\n\n"
            "<b>Brokers Supported:</b>\n"
            "• <code>upstox</code> — Upstox MTF (Margin Trading Facility)\n"
            "• <code>dhan</code>   — DhanHQ MTF (Margin Trading Facility)\n"
            "• <code>zerodha</code>— Zerodha Kite (CNC Delivery)\n\n"
            "<b>Examples:</b>\n"
            "• <code>/buy RELIANCE</code> — Preview ₹1L on default broker\n"
            "• <code>/buy INFY agg dhan</code> — Preview ₹1.5L on DhanHQ MTF\n"
            "• <code>/buy TCS 50k zerodha</code> — Preview ₹50K on Zerodha\n"
            "• <code>/buy TATAMOTORS mod confirm</code> — Instant 1-shot execution\n"
            "• <code>/broker</code> — View/switch default broker\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>MTF enables 3x-4x broker leverage while capping your maximum capital exposure!</i>"
        )

    tokens = [t.strip() for t in args.split() if t.strip()]
    raw_sym = tokens[0].upper()
    symbol = SYMBOL_ALIASES.get(raw_sym, raw_sym)

    from order_engine import (
        MODE_SIZES,
        SUPPORTED_BROKERS,
        get_default_broker,
        execute_broker_order
    )

    broker = get_default_broker()
    mode = "mod"
    sl_mode = "lod"
    auto_confirm = False

    for tok in tokens[1:]:
        tok_lower = tok.lower()
        if tok_lower in ("confirm", "now", "exec", "execute", "yes"):
            auto_confirm = True
        elif tok_lower in ("lod", "daylow", "low_of_day"):
            sl_mode = "lod"
        elif tok_lower in ("regime", "reg", "market_regime"):
            sl_mode = "regime"
        elif tok_lower in SUPPORTED_BROKERS:
            broker = tok_lower
        elif tok_lower in MODE_SIZES or tok_lower.endswith("k") or tok_lower.endswith("l") or tok_lower.isdigit():
            mode = tok_lower

    if auto_confirm:
        success, res = execute_broker_order(symbol, mode_arg=mode, sl_mode=sl_mode, broker=broker)
        if success:
            warn_count = len(res.get("checklist", {}).get("warnings", []))
            warn_str = f"⚠️ <b>Checklist:</b> <i>Executed with {warn_count} strategy warnings</i>\n" if warn_count > 0 else "⭐ <b>Checklist:</b> <i>A+ Setup - All Rules Passed</i>\n"
            return (
                f"🎉 <b>ORDER EXECUTED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Product:</b> {res['product_label']}\n"
                f"📈 <b>Quantity:</b> <b>{res['quantity']} shares</b> @ ₹{res['ltp']}\n"
                f"💰 <b>Exposure:</b> ₹{res['actual_exposure']:,} ({res['mode_label']})\n"
                f"🛑 <b>Stop Loss:</b> <b>₹{res['stop_loss']}</b> ({res['sl_mode']}: -{res['risk_pct']}%)\n"
                f"⚠️ <b>Risk at SL:</b> ₹{res['total_risk_inr']:,}\n"
                f"🌐 <b>Regime:</b> {res['regime_label']}\n"
                f"{warn_str}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Recommendation: Set GTT / SL-M trigger at ₹{res['stop_loss']} in {res['broker']} app. Added to scanner watchlist.</i>"
            )
        else:
            return (
                f"❌ <b>ORDER FAILED AT {broker.upper()}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {symbol}\n"
                f"⚠️ <b>Error:</b> {res}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Check token validity (/token) or MTF eligibility of this stock on {broker.upper()}.</i>"
            )

    return build_buy_preview(symbol, mode, sl_mode, broker)


def handle_callback_query(cq):
    """Processes interactive inline keyboard button taps."""
    bot_token, authorized_chat_id = get_telegram_config()
    cq_id = cq.get("id")
    cq_data = cq.get("data", "")
    cq_msg = cq.get("message", {})
    chat_id = cq_msg.get("chat", {}).get("id")
    msg_id = cq_msg.get("message_id")

    if authorized_chat_id and str(chat_id) != str(authorized_chat_id):
        answer_callback_query(cq_id, "Unauthorized", show_alert=True)
        return

    if cq_data.startswith("buy_exec:"):
        parts = cq_data.split(":")
        symbol = parts[1] if len(parts) > 1 else ""
        mode = parts[2] if len(parts) > 2 else "mod"
        sl_mode = parts[3] if len(parts) > 3 else "lod"
        broker = parts[4] if len(parts) > 4 else "upstox"

        answer_callback_query(cq_id, f"Submitting order for {symbol} on {broker.upper()}...")

        from order_engine import execute_broker_order
        success, res = execute_broker_order(symbol, mode_arg=mode, sl_mode=sl_mode, broker=broker)

        if success:
            warn_count = len(res.get("checklist", {}).get("warnings", []))
            warn_str = f"⚠️ <b>Checklist:</b> <i>Executed with {warn_count} strategy warnings</i>\n" if warn_count > 0 else "⭐ <b>Checklist:</b> <i>A+ Setup - All Rules Passed</i>\n"
            receipt = (
                f"🎉 <b>ORDER EXECUTED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Product:</b> {res['product_label']}\n"
                f"📈 <b>Quantity:</b> <b>{res['quantity']} shares</b> @ ₹{res['ltp']}\n"
                f"💰 <b>Exposure:</b> ₹{res['actual_exposure']:,} ({res['mode_label']})\n"
                f"🛑 <b>Stop Loss:</b> <b>₹{res['stop_loss']}</b> ({res['sl_mode']}: -{res['risk_pct']}%)\n"
                f"⚠️ <b>Risk at SL:</b> ₹{res['total_risk_inr']:,}\n"
                f"🌐 <b>Regime:</b> {res['regime_label']}\n"
                f"{warn_str}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Recommendation: Set GTT / SL-M trigger at ₹{res['stop_loss']} in {res['broker']} app. Added to scanner watchlist.</i>"
            )
        else:
            receipt = (
                f"❌ <b>ORDER FAILED AT {broker.upper()}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {symbol}\n"
                f"⚠️ <b>Error:</b> {res}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Check token validity (/token) or MTF eligibility of this stock on {broker.upper()}.</i>"
            )

        edit_telegram_msg(chat_id, msg_id, receipt, reply_markup={"inline_keyboard": []})

    elif cq_data.startswith("buy_switch:"):
        parts = cq_data.split(":")
        symbol = parts[1] if len(parts) > 1 else ""
        mode = parts[2] if len(parts) > 2 else "mod"
        sl_mode = parts[3] if len(parts) > 3 else "lod"
        new_broker = parts[4] if len(parts) > 4 else "upstox"

        answer_callback_query(cq_id, f"Switched to {new_broker.upper()}")
        text, markup = build_buy_preview(symbol, mode, sl_mode, new_broker)
        if markup:
            edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)

    elif cq_data.startswith("buy_cancel"):
        sym = cq_data.split(":")[1] if ":" in cq_data else "Trade"
        answer_callback_query(cq_id, "Order cancelled")
        edit_telegram_msg(
            chat_id,
            msg_id,
            f"❌ <b>Order Cancelled:</b> Trade request for <b>{sym}</b> was discarded.",
            reply_markup={"inline_keyboard": []}
        )

    elif cq_data == "pos_refresh":
        answer_callback_query(cq_id, "Refreshing live positions...")
        text, markup = handle_positions_command()
        edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)

    elif cq_data.startswith("ex_p:"):
        parts = cq_data.split(":")
        b_code = parts[1]
        sym = ":".join(parts[2:])
        answer_callback_query(cq_id, f"Opening exit prompt for {sym}...")
        text, markup = build_exit_preview(sym, b_code)
        if markup:
            edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)
        else:
            answer_callback_query(cq_id, "Position no longer open", show_alert=True)

    elif cq_data.startswith("ex_x:"):
        parts = cq_data.split(":")
        b_code = parts[1]
        ratio = parts[-1]
        sym = ":".join(parts[2:-1]) if len(parts) > 3 else parts[2]
        b_name = {"d": "DHAN", "z": "ZERODHA", "u": "UPSTOX"}.get(b_code, "")

        answer_callback_query(cq_id, f"Executing market exit for {sym}...")

        from order_engine import execute_broker_exit
        success, res = execute_broker_exit(sym, broker=b_name, qty_ratio=ratio)
        if success:
            rem = res.get("remaining_qty", 0)
            rem_str = f"• <b>Remaining Qty:</b> {rem} shares\n" if rem > 0 else "• <b>Status:</b> Position Fully Closed (0 shares)\n"
            receipt = (
                f"🎉 <b>POSITION EXITED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Sold Qty:</b> <b>{res['quantity']} shares</b> @ MARKET\n"
                f"💼 <b>Product:</b> {res['product']}\n"
                f"{rem_str}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Market order submitted to exchange. Tap below to see live portfolio:</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📊 View Updated Positions", "callback_data": "pos_refresh"}]
                ]
            }
            edit_telegram_msg(chat_id, msg_id, receipt, reply_markup=markup)
        else:
            receipt = (
                f"❌ <b>EXIT ORDER FAILED</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {sym}\n"
                f"⚠️ <b>Error:</b> {res}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Check token validity or broker terminal.</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📊 Back to Positions", "callback_data": "pos_refresh"}]
                ]
            }
            edit_telegram_msg(chat_id, msg_id, receipt, reply_markup=markup)

    elif cq_data.startswith("ex_c:"):
        answer_callback_query(cq_id, "Exit cancelled")
        text, markup = handle_positions_command()
        edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)


# ---------------------------------------------------------
# Core Message Dispatcher
# ---------------------------------------------------------
def dispatch_command(msg_text, from_chat_id):
    """Processes incoming Telegram message and returns response text."""
    bot_token, authorized_chat_id = get_telegram_config()

    # Security: strict chat_id validation
    if authorized_chat_id and str(from_chat_id) != str(authorized_chat_id):
        print(f"⛔ Unauthorized access attempt from Chat ID: {from_chat_id}")
        return "⛔ <b>Unauthorized:</b> Access restricted to the bot administrator."

    text = msg_text.strip()
    if not text:
        return None

    # Handle direct pasted tokens first
    if text.startswith("eyJ") or (len(text) == 32 and text.isalnum() and not text.startswith("/")):
        auto_resp = handle_pasted_token(text)
        if auto_resp:
            return auto_resp

    # Normalize command
    cmd_parts = text.split(maxsplit=1)
    raw_cmd = cmd_parts[0].lower()
    args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

    # Remove bot username suffix if present (e.g. /add@Sannin_100M_bot -> /add)
    cmd = raw_cmd.split("@")[0]

    if cmd in ("/start", "/help"):
        return handle_help_command()
    elif cmd in ("/add", "/addstock"):
        return handle_add_command(args)
    elif cmd in ("/remove", "/del", "/rm", "/delete"):
        return handle_remove_command(args)
    elif cmd in ("/watchlist", "/list", "/stocks"):
        return handle_watchlist_command()
    elif cmd in ("/positions", "/pos", "/portfolio", "/pnl", "/holdings"):
        return handle_positions_command()
    elif cmd in ("/exit", "/close", "/squareoff"):
        return handle_exit_command(args)
    elif cmd in ("/token", "/tokens", "/status", "/check"):
        # Check if sub-command provided (e.g. /token upstox <token>)
        if args:
            sub_parts = args.split(maxsplit=1)
            sub_cmd = sub_parts[0].lower()
            sub_tok = sub_parts[1] if len(sub_parts) > 1 else ""
            if sub_cmd in ("upstox", "dhan", "zerodha"):
                return handle_update_token_command(sub_cmd, sub_tok)
        return handle_token_status_command()
    elif cmd == "/upstox":
        return handle_update_token_command("upstox", args)
    elif cmd == "/dhan":
        return handle_update_token_command("dhan", args)
    elif cmd == "/zerodha":
        return handle_update_token_command("zerodha", args)
    elif cmd in ("/buy", "/mtf", "/order"):
        return handle_buy_command(args, from_chat_id)
    elif cmd in ("/broker", "/brokers"):
        return handle_broker_command(args)
    elif cmd in ("/scan", "/refresh"):
        return handle_scan_command()
    elif cmd == "/regime":
        return handle_regime_command()
    else:
        return (
            f"❓ Unknown command: <code>{cmd}</code>\n"
            "Type <code>/help</code> to view available commands."
        )


# ---------------------------------------------------------
# Telegram Long-Polling Bot Loop
# ---------------------------------------------------------
def run_telegram_bot_loop(stop_event=None):
    """Runs long polling loop to receive and execute Telegram commands."""
    bot_token, authorized_chat_id = get_telegram_config()
    if not bot_token:
        print("⚠️ Telegram bot_token not configured. Bot listener not started.")
        return

    # Auto-register commands menu with Telegram API
    try:
        register_telegram_commands()
    except Exception:
        pass

    print("=" * 60)
    print("🤖 JARVIS TELEGRAM COMMAND ENGINE ACTIVE")
    print(f"   Chat ID: {authorized_chat_id or 'All (Unrestricted)'}")
    print("   Listening for /buy, /add, /remove, /watchlist, /token, /scan...")
    print("=" * 60)

    offset = None

    while True:
        if stop_event and stop_event.is_set():
            print("Telegram Bot listener received stop signal.")
            break

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates?timeout=20"
        if offset is not None:
            url += f"&offset={offset}"

        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Bot-Poller"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode())
                updates = data.get("result", [])
                for u in updates:
                    offset = u["update_id"] + 1

                    # Handle interactive inline keyboard clicks
                    cq = u.get("callback_query")
                    if cq:
                        handle_callback_query(cq)
                        continue

                    msg = u.get("message") or u.get("edited_message")
                    if not msg or not msg.get("text"):
                        continue
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")
                    text = msg.get("text", "")
                    sender = msg.get("from", {}).get("first_name", "User")

                    print(f"📩 [{get_ist_now().strftime('%H:%M:%S')}] Telegram from {sender} ({chat_id}): {text[:50]}")

                    reply = dispatch_command(text, chat_id)
                    if reply:
                        if isinstance(reply, tuple):
                            send_telegram_msg(chat_id, reply[0], reply_markup=reply[1])
                        else:
                            send_telegram_msg(chat_id, reply)

        except urllib.error.HTTPError as he:
            if he.code == 409:
                # Conflict: another instance of getUpdates is active
                time.sleep(5)
            else:
                time.sleep(2)
        except Exception:
            time.sleep(2)


# ---------------------------------------------------------
# Background Thread Runner
# ---------------------------------------------------------
_bot_thread = None
_bot_stop_event = None


def start_telegram_bot_thread():
    """Starts the Telegram bot as a daemon background thread."""
    global _bot_thread, _bot_stop_event
    if _bot_thread and _bot_thread.is_alive():
        return _bot_thread

    _bot_stop_event = threading.Event()
    _bot_thread = threading.Thread(
        target=run_telegram_bot_loop,
        args=(_bot_stop_event,),
        daemon=True,
        name="TelegramBotThread"
    )
    _bot_thread.start()
    return _bot_thread


if __name__ == "__main__":
    try:
        run_telegram_bot_loop()
    except KeyboardInterrupt:
        print("\nExiting Telegram Bot.")
