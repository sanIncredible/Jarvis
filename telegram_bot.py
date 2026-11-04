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
import socket
import threading
import urllib.request
import urllib.error
from pathlib import Path

# Ensure standard socket read timeout so cloud poller never hangs indefinitely
socket.setdefaulttimeout(30)
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


def get_telegram_extended_config():
    """Retrieves full Telegram configuration including group_id, authorized_chats, and topic mappings."""
    cfg = load_config()
    tg = cfg.get("telegram", {})
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or tg.get("bot_token", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip() or str(tg.get("chat_id", "")).strip()
    group_id = str(tg.get("group_id", "")).strip()
    authorized_chats = [str(c).strip() for c in tg.get("authorized_chats", [])]
    if chat_id and chat_id not in authorized_chats:
        authorized_chats.append(chat_id)
    if group_id and group_id not in authorized_chats:
        authorized_chats.append(group_id)
    topics = tg.get("topics", {})
    return {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "group_id": group_id,
        "authorized_chats": authorized_chats,
        "topics": topics
    }


def get_topic_target(topic_name):
    """
    Resolves the destination chat_id and message_thread_id for a given topic category.
    Returns (target_chat_id, thread_id).
    Falls back to (primary_chat_id, None) if group_id or topic is not configured.
    """
    ext = get_telegram_extended_config()
    group_id = ext.get("group_id")
    topics = ext.get("topics", {})
    thread_id = topics.get(topic_name)
    if group_id and thread_id is not None:
        return group_id, int(thread_id)
    return ext.get("chat_id"), None


# ---------------------------------------------------------
# Telegram Bot API Helpers
# ---------------------------------------------------------
def send_telegram_msg(chat_id, text, parse_mode="HTML", reply_markup=None, thread_id=None):
    """Sends a Telegram message to a specific chat and thread, falling back to plain text if markup parsing fails."""
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
    if thread_id is not None:
        payload["message_thread_id"] = int(thread_id)
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
    except urllib.error.HTTPError as he:
        err_body = he.read().decode(errors="replace")
        if he.code == 400 and parse_mode:
            # Fallback retry without parse_mode if entity parsing failed
            payload["parse_mode"] = None
            retry_data = json.dumps(payload).encode("utf-8")
            retry_req = urllib.request.Request(url, data=retry_data, headers={
                "Content-Type": "application/json",
                "User-Agent": "Jarvis-Telegram-Bot"
            })
            try:
                with urllib.request.urlopen(retry_req, timeout=10) as retry_resp:
                    return True, json.loads(retry_resp.read().decode())
            except Exception as e2:
                return False, f"{he} (fallback failed: {e2}) - {err_body}"
        return False, f"{he}: {err_body}"
    except Exception as e:
        return False, str(e)


def send_topic_alert(topic_name, text, parse_mode="HTML", reply_markup=None):
    """Sends an alert directly to the designated Telegram forum topic thread."""
    chat_id, thread_id = get_topic_target(topic_name)
    return send_telegram_msg(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup, thread_id=thread_id)


def send_topic_alert_async(topic_name, text, parse_mode="HTML", reply_markup=None):
    """Sends an alert directly to designated Telegram forum topic thread asynchronously."""
    def _worker():
        send_topic_alert(topic_name, text, parse_mode=parse_mode, reply_markup=reply_markup)
    threading.Thread(target=_worker, daemon=True).start()


def edit_telegram_msg(chat_id, message_id, text, parse_mode="HTML", reply_markup=None):
    """Edits an existing Telegram message in place, falling back to plain text if markup parsing fails."""
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
    except urllib.error.HTTPError as he:
        err_body = he.read().decode(errors="replace")
        if he.code == 400 and parse_mode:
            payload["parse_mode"] = None
            retry_data = json.dumps(payload).encode("utf-8")
            retry_req = urllib.request.Request(url, data=retry_data, headers={
                "Content-Type": "application/json",
                "User-Agent": "Jarvis-Telegram-Bot"
            })
            try:
                with urllib.request.urlopen(retry_req, timeout=10) as retry_resp:
                    return True, json.loads(retry_resp.read().decode())
            except Exception as e2:
                return False, f"{he} (fallback failed: {e2}) - {err_body}"
        return False, f"{he}: {err_body}"
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
        {"command": "funds", "description": "💳 Multi-broker available cash & MTF margin"},
        {"command": "candidates", "description": "🎯 Scan Nifty 500 swing breakout setups (candidates.txt)"},
        {"command": "trail", "description": "🎯 Trailing SL & Risk Breakeven recommendations"},
        {"command": "exit", "description": "🔴 Quick exit/square-off open positions"},
        {"command": "journal", "description": "📓 Reconcile broker trades into Journal.xlsx"},
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


def push_watchlist_to_github():
    """Pushes watchlist.txt immediately to GitHub repository via REST API."""
    try:
        from upstox_tablet_scanner import load_github_config, sync_file_to_github_api
        gh_cfg = load_github_config()
        if gh_cfg:
            syms = read_watchlist_symbols()
            return sync_file_to_github_api(gh_cfg, "watchlist.txt", f"Update watchlist via Telegram ({len(syms)} symbols)")
    except Exception as e:
        print(f"GitHub Watchlist Push notice: {e}")
    return False


def push_watchlist_and_data_to_github():
    """Pushes watchlist.txt and data.json to GitHub repository via REST API."""
    try:
        push_watchlist_to_github()
        from upstox_tablet_scanner import load_github_config, sync_file_to_github_api
        gh_cfg = load_github_config()
        if gh_cfg and (SCRIPT_DIR / "data.json").is_file():
            syms = read_watchlist_symbols()
            sync_file_to_github_api(gh_cfg, "data.json", f"Sync data.json via Telegram ({len(syms)} symbols)")
        return True
    except Exception as e:
        print(f"GitHub Push notice: {e}")
    return False


def trigger_immediate_rescan():
    """Runs a fresh scan and updates static html / data.json."""
    try:
        # Guarantee GitHub has latest watchlist first so scanner pull never reverts it
        push_watchlist_to_github()
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

    # Push watchlist to GitHub synchronously FIRST to guarantee persistence
    push_watchlist_to_github()

    # Trigger Rescan & Dashboard Sync in Background Thread
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
    push_watchlist_to_github()
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


def handle_candidates_command():
    """
    Scans liquid Nifty 500 stocks for institutional swing thrust setups,
    saving results to candidates.txt for manual vetting and returning an interactive review card.
    """
    try:
        from candidate_scanner import scan_nifty500_candidates, format_candidates_telegram_card
        res = scan_nifty500_candidates(top_n=15)
        text, markup = format_candidates_telegram_card(res, max_display=10)
        return text, markup
    except Exception as e:
        return f"⚠️ <b>Candidate Scanner Error:</b> {e}", None


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
        "• <code>/funds</code> or <code>/margin</code> — Live multi-broker available cash & MTF margin\n"
        "• <code>/trail</code> or <code>/sl</code> — Trailing SL & Risk Breakeven recommendations\n"
        "• <code>/exit &lt;SYM&gt; [50%|all]</code> — 1-Tap quick exit/square-off\n"
        "• <code>/journal</code> — Reconcile live broker fills into Journal.xlsx\n"
        "• <code>/broker</code> — View/switch default broker (Upstox/Dhan/Zerodha)\n\n"
        "📋 <b>Watchlist & Screening:</b>\n"
        "• <code>/candidates</code> or <code>/screen</code> — Scan Nifty 500 swing setups (saves to candidates.txt)\n"
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


def handle_funds_command():
    """
    Displays live cash, margin, and collateral status across DhanHQ, Upstox, and Zerodha.
    """
    from order_engine import fetch_broker_funds
    funds = fetch_broker_funds()

    lines = [
        "💳 <b>MULTI-BROKER CAPITAL & FUNDS STATUS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    # DhanHQ
    d = funds.get("dhan", {})
    if d.get("enabled"):
        if d.get("error"):
            lines.append(f"🟠 <b>DhanHQ (MTF):</b> ⚠️ <i>{d['error']}</i>")
        else:
            lines.append(
                f"🟠 <b>DhanHQ (MTF / Pay Later):</b>\n"
                f"  • Available Margin : <b>₹{d['available_cash']:,.2f}</b>\n"
                f"  • Collateral Amount: ₹{d['collateral']:,.2f}\n"
                f"  • Utilized Margin  : ₹{d['utilized']:,.2f}\n"
                f"  • Withdrawable Cash: ₹{d['withdrawable']:,.2f}"
            )
    else:
        lines.append("🟠 <b>DhanHQ:</b> ⚪ <i>Not Configured</i>")

    lines.append("")

    # Upstox Pro
    u = funds.get("upstox", {})
    if u.get("enabled"):
        if u.get("error"):
            lines.append(f"🔵 <b>Upstox Pro:</b> ⚠️ <i>{u['error']}</i>")
        else:
            lines.append(
                f"🔵 <b>Upstox Pro (MTF):</b>\n"
                f"  • Available Margin : <b>₹{u['available_margin']:,.2f}</b>\n"
                f"  • Used Margin      : ₹{u['used_margin']:,.2f}"
            )
    else:
        lines.append("🔵 <b>Upstox Pro:</b> ⚪ <i>Not Configured</i>")

    lines.append("")

    # Zerodha Kite
    z = funds.get("zerodha", {})
    if z.get("enabled"):
        if z.get("error"):
            lines.append(f"🟢 <b>Zerodha Kite:</b> ⚠️ <i>{z['error']}</i>")
        else:
            lines.append(
                f"🟢 <b>Zerodha Kite (CNC/MIS):</b>\n"
                f"  • Live Balance     : <b>₹{z['live_balance']:,.2f}</b>\n"
                f"  • Free Cash        : ₹{z['available_cash']:,.2f}\n"
                f"  • Collateral Margin: ₹{z['collateral']:,.2f}\n"
                f"  • Utilized Margin  : ₹{z['utilized']:,.2f}"
            )
    else:
        lines.append("🟢 <b>Zerodha Kite:</b> ⚪ <i>Not Configured</i>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    tot = funds.get("total_available_margin", 0.0)
    lines.append(f"💰 <b>Total Available Purchasing Power:</b> <b>₹{tot:,.2f}</b>")
    now_str = get_ist_now().strftime("%d %b %H:%M:%S IST")
    lines.append(f"🕒 <i>Updated: {now_str}</i>")

    markup = {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh Funds", "callback_data": "funds_refresh"},
                {"text": "📊 Live Positions", "callback_data": "pos_refresh"}
            ]
        ]
    }
    return "\n".join(lines), markup


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

    # Live Broker Funds Pre-Flight Advisory
    margin_advisory = ""
    try:
        from order_engine import fetch_broker_funds
        b_funds = fetch_broker_funds()
        b_info = b_funds.get(broker, {})
        avail_margin = float(b_info.get("available_margin") or b_info.get("available_cash") or b_info.get("live_balance") or 0.0)
        b_label += f" (Avail: ₹{avail_margin:,.0f})"
        if avail_margin > 0 and calc['actual_exposure'] > avail_margin:
            margin_advisory = f"\n⚠️ <b>Margin Notice:</b> Required ₹{calc['actual_exposure']:,} exceeds available margin (₹{avail_margin:,.0f}) on {broker.upper()}!\n"
    except Exception:
        pass

    checklist_data = calc.get("checklist", {})
    checklist_items = checklist_data.get("checklist", [])
    warnings = checklist_data.get("warnings", [])
    scanner_sig = checklist_data.get("scanner_signal")

    checklist_lines = [f"• {c['text']}" for c in checklist_items]
    checklist_block = "\n".join(checklist_lines)

    if warnings:
        warn_lines = "\n".join([
            f"  {i+1}. <i>{str(w).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</i>"
            for i, w in enumerate(warnings)
        ])
        alert_block = (
            f"\n🚨 <b>STRATEGY WARNINGS ({len(warnings)} Unsatisfied):</b>\n"
            f"{warn_lines}\n"
        )
    else:
        alert_block = "\n⭐ <b>A+ SETUP: All Strategy Checklist Rules Satisfied!</b>\n"

    sig_line = f"🏷️ <b>Scanner Signal:</b> <code>{scanner_sig}</code>\n" if scanner_sig else ""
    reg_note_safe = str(calc['regime_note']).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') if calc.get("regime_note") else ""
    reg_note_line = f"🛡️ <b>Regime Policy:</b> {reg_note_safe}\n" if reg_note_safe else ""

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
        f"{reg_note_line}"
        f"{sig_line}"
        f"{margin_advisory}"
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

            sl_p = float(p.get("stop_loss", 0) or 0)
            var_val = float(p.get("value_at_risk", 0) or 0)
            var_pct = float(p.get("var_pct", 0) or 0)

            if sl_p >= avg_p and avg_p > 0:
                var_str = "🟢 <b>₹0.00 (Risk-Free / Breakeven)</b>"
            elif var_val <= 0 and sl_p > 0:
                var_str = "🟢 <b>₹0.00 (Risk-Free)</b>"
            elif sl_p > 0:
                var_str = f"⚠️ <b>-₹{var_val:,.2f}</b> ({var_pct:.2f}%)"
            else:
                var_str = "<i>No SL set</i>"

            sl_str = f"₹{sl_p:,.2f}" if sl_p > 0 else "<i>Not set</i>"

            card = (
                f"{pnl_icon} <b>{sym}</b> [<code>{broker} • {prod}</code>]\n"
                f"  • <b>Qty:</b> {qty_sign}{qty} @ ₹{avg_p:,.2f} | <b>LTP:</b> ₹{ltp:,.2f}\n"
                f"  • <b>P&L:</b> {pnl_icon} <b>{pnl_str}</b> ({pct_sign}{pnl_pct:.2f}%)\n"
                f"  • <b>Exposure:</b> ₹{exposure:,.2f}\n"
                f"  • <b>Stop-Loss:</b> {sl_str} | <b>Value at Risk:</b> {var_str}"
            )
            lines.append(card)

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    tot_pnl = totals["total_pnl"]
    tot_pnl_icon = "🟢" if tot_pnl >= 0 else "🔴"
    tot_pnl_str = f"+₹{tot_pnl:,.2f}" if tot_pnl > 0 else (f"-₹{abs(tot_pnl):,.2f}" if tot_pnl < 0 else "₹0.00")

    tot_var = float(totals.get("total_var", 0.0) or 0.0)
    tot_var_pct = float(totals.get("total_var_pct", 0.0) or 0.0)
    var_icon = "🟢" if tot_var <= 0 else "🛡️"

    lines.append("💼 <b>PORTFOLIO TOTALS:</b>")
    lines.append(f"• <b>Open Positions:</b> {totals['count']}")
    lines.append(f"• <b>Total Net P&L:</b> {tot_pnl_icon} <b>{tot_pnl_str}</b>")
    lines.append(f"• <b>Total Exposure:</b> ₹{totals['total_exposure']:,.2f}")
    lines.append(f"• <b>Total Value at Risk (VaR):</b> {var_icon} <b>₹{tot_var:,.2f}</b> ({tot_var_pct:.2f}% of exposure)")
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

    kb_rows.append([
        {"text": "🎯 Trailing SL Cockpit", "callback_data": "trail_refresh"},
        {"text": "🔄 Refresh Positions", "callback_data": "pos_refresh"}
    ])
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


def handle_trailing_command():
    """
    Evaluates Trailing Stop-Loss & Risk Breakeven recommendations for ALL open positions
    across live brokers and trade logs, returning formatted summary card and action buttons.
    """
    from order_engine import get_all_open_positions_with_trailing_sl
    positions = get_all_open_positions_with_trailing_sl()

    now_str = get_ist_now().strftime("%d %b %H:%M:%S IST")

    lines = [
        "🎯 <b>JARVIS LIVE TRAILING SL & RISK COCKPIT</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if not positions:
        lines.append("💤 <b>No Open Positions Active</b>")
        lines.append("All multi-broker portfolios and trade logs are currently 100% in cash.")
    else:
        for p in positions:
            sym = p["symbol"]
            broker = p["broker"]
            prod = p["product"]
            source = p.get("source", "LIVE")
            entry_p = p["entry_price"]
            ltp = p["ltp"]
            pnl = p["pnl"]
            pnl_pct = p["pnl_pct"]
            r_mult = p["r_multiple"]
            rec_sl = p["recommended_sl"]
            init_sl = p["initial_sl"]
            badge = p["action_badge"]
            action_desc = p["action_text"]
            qty = p["qty"]

            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            pnl_str = f"+₹{pnl:,.2f}" if pnl > 0 else (f"-₹{abs(pnl):,.2f}" if pnl < 0 else "₹0.00")
            pct_sign = "+" if pnl_pct > 0 else ""
            r_sign = "+" if r_mult > 0 else ""

            src_tag = f" • <i>{source}</i>" if source != "LIVE BROKER" else ""
            ema_str = ""
            if p.get("ema10") and p.get("ema20"):
                ema_str = f"\n  • <b>10 EMA:</b> ₹{p['ema10']:,.2f} | <b>20 EMA:</b> ₹{p['ema20']:,.2f}"
                if p.get("atr14"):
                    ema_str += f" | <b>ATR:</b> ₹{p['atr14']:,.2f}"

            j_badge = p.get("jeff_badge", badge)
            j_status = p.get("jeff_status", action_desc)

            var_val = float(p.get("value_at_risk", 0.0) or 0.0)
            var_pct = float(p.get("var_pct", 0.0) or 0.0)
            if init_sl >= entry_p and entry_p > 0:
                var_str = "🟢 <b>₹0.00 (Risk-Free / Breakeven)</b>"
            elif var_val <= 0 and init_sl > 0:
                var_str = "🟢 <b>₹0.00 (Risk-Free)</b>"
            elif init_sl > 0:
                var_str = f"⚠️ <b>-₹{var_val:,.2f}</b> ({var_pct:.2f}%)"
            else:
                var_str = "<i>N/A</i>"

            rec_var_val = float(p.get("rec_value_at_risk", 0.0) or 0.0)
            rec_var_pct = float(p.get("rec_var_pct", 0.0) or 0.0)
            if rec_sl >= entry_p and entry_p > 0:
                rec_var_str = "🟢 ₹0.00 (Free Roll)"
            elif rec_var_val <= 0 and rec_sl > 0:
                rec_var_str = "🟢 ₹0.00"
            else:
                rec_var_str = f"⚠️ -₹{rec_var_val:,.2f} ({rec_var_pct:.2f}%)"

            lines.append(
                f"<b>{sym}</b> [<code>{broker} • {prod}</code>]{src_tag}\n"
                f"  • <b>Entry:</b> ₹{entry_p:,.2f} | <b>LTP:</b> ₹{ltp:,.2f} ({pct_sign}{pnl_pct:.2f}% | {r_sign}{r_mult:.1f}R)\n"
                f"  • <b>Stop-Loss:</b> ₹{init_sl:,.2f} ➔ <b>Rec Trail:</b> <b>₹{rec_sl:,.2f}</b>\n"
                f"  • <b>Value at Risk:</b> {var_str} (➔ Rec: {rec_var_str})\n"
                f"  • <b>Jeff Sun Trail:</b> <b>{j_badge}</b>\n"
                f"    <i>{j_status}</i>{ema_str}"
            )

    if positions:
        tot_var = sum(float(p.get("value_at_risk", 0.0) or 0.0) for p in positions)
        tot_exp = sum(float(p.get("exposure", 0.0) or (p.get("entry_price", 0.0) * p.get("qty", 0))) for p in positions)
        tot_var_pct = round((tot_var / tot_exp) * 100, 2) if tot_exp > 0 else 0.0
        var_icon = "🟢" if tot_var <= 0 else "🛡️"

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🛡️ <b>Portfolio Total Value at Risk:</b> {var_icon} <b>₹{tot_var:,.2f}</b> ({tot_var_pct:.2f}% of exposure)")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <b>Jeff Sun Momentum Trailing Framework:</b>")
    lines.append("• <b>Gain &ge; +1.5R (+2.5%):</b> Auto-Ratchet SL to Breakeven (+0.15% fee buffer)")
    lines.append("• <b>10 EMA Trailing:</b> Ride winners while daily close holds above 10 EMA")
    lines.append("• <b>Exit Trigger:</b> Daily Close &lt; 10 EMA + Next-Day 5m ORL Breakdown")
    lines.append("• <b>Overextension:</b> If stretch &ge; 3.0x ATR from 50MA, book partials & tighten")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕒 <i>Updated: {now_str}</i>")

    message_text = "\n".join(lines)

    kb_rows = [
        [
            {"text": "🔄 Refresh Trailing SL", "callback_data": "trail_refresh"},
            {"text": "📊 Live Positions", "callback_data": "pos_refresh"}
        ]
    ]

    if positions:
        for p in positions[:4]:
            b_code = p["broker"][:1].lower() if p.get("broker") else "u"
            sym = p["symbol"]
            short_s = sym[:8] if len(sym) > 8 else sym
            kb_rows.append([
                {"text": f"🛡️ Ratchet {short_s} to Cost", "callback_data": f"trail_be:{b_code}:{sym}"},
                {"text": f"🔴 Exit {short_s}", "callback_data": f"ex_p:{b_code}:{sym}"}
            ])

    reply_markup = {"inline_keyboard": kb_rows}

    return message_text, reply_markup


def handle_journal_command():
    """
    Triggers manual sync of broker executions and live positions into Journal.xlsx,
    recalculating all metrics, R-multiples, and open positions.
    """
    try:
        from sync_journal import run_eod_sync
        run_eod_sync()
        return (
            "✅ <b>TRADE JOURNAL RECONCILED & UPDATED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• Synced live broker fills from Dhan & Zerodha Kite.\n"
            "• Auto-reconciled all carried-forward live open positions.\n"
            "• Updated 'Trade Journal' & 'Open Positions' sheets.\n"
            "• Created timestamped backup in <code>backups/</code> folder.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Full executive report delivered above. Type <code>/positions</code> or <code>/trail</code> to view live cards.</i>"
        )
    except Exception as e:
        return f"⚠️ <b>Journal Sync Notice:</b> {e}"


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
            sl_broker_line = ""
            if res.get("sl_placed") and res.get("sl_order_id"):
                sl_broker_line = f"🛡️ <b>Broker Hard SL:</b> 🟢 Active @ ₹{res['stop_loss']} (ID: <code>{res['sl_order_id']}</code>)\n"
            elif res.get("sl_error"):
                sl_broker_line = f"⚠️ <b>Broker Hard SL:</b> <i>{res['sl_error']} (Tracked in software)</i>\n"

            sl_footer = "🛡️ <i>Hard Stop-Loss order placed in broker orderbook. Fully protected on exchange!</i>" if res.get("sl_placed") else f"💡 <i>Recommendation: Set GTT / SL-M trigger at ₹{res['stop_loss']} in {res['broker']} app. Added to scanner watchlist.</i>"

            return (
                f"🎉 <b>ORDER EXECUTED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Product:</b> {res['product_label']}\n"
                f"📈 <b>Quantity:</b> <b>{res['quantity']} shares</b> @ ₹{res['ltp']}\n"
                f"💰 <b>Exposure:</b> ₹{res['actual_exposure']:,} ({res['mode_label']})\n"
                f"🛑 <b>Stop Loss:</b> <b>₹{res['stop_loss']}</b> ({res['sl_mode']}: -{res['risk_pct']}%)\n"
                f"{sl_broker_line}"
                f"⚠️ <b>Risk at SL:</b> ₹{res['total_risk_inr']:,}\n"
                f"🌐 <b>Regime:</b> {res['regime_label']}\n"
                f"{warn_str}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{sl_footer}"
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
    cq_from = cq.get("from", {})
    user_id = cq_from.get("id")
    cq_msg = cq.get("message", {})
    chat_id = cq_msg.get("chat", {}).get("id")
    thread_id = cq_msg.get("message_thread_id")
    msg_id = cq_msg.get("message_id")

    ext = get_telegram_extended_config()
    auth_chats = ext.get("authorized_chats", [])
    primary_user_id = ext.get("chat_id")

    # Security check: in a group, only primary bot admin can execute interactive buttons
    is_group = str(chat_id).startswith("-")
    if is_group:
        if primary_user_id and str(user_id) != str(primary_user_id):
            answer_callback_query(cq_id, "⛔ Unauthorized: Only bot administrator can execute actions.", show_alert=True)
            return
    else:
        if primary_user_id and str(chat_id) != str(primary_user_id) and str(chat_id) not in auth_chats:
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
            sl_broker_line = ""
            if res.get("sl_placed") and res.get("sl_order_id"):
                sl_broker_line = f"🛡️ <b>Broker Hard SL:</b> 🟢 Active @ ₹{res['stop_loss']} (ID: <code>{res['sl_order_id']}</code>)\n"
            elif res.get("sl_error"):
                sl_broker_line = f"⚠️ <b>Broker Hard SL:</b> <i>{res['sl_error']} (Tracked in software)</i>\n"

            sl_footer = "🛡️ <i>Hard Stop-Loss order placed in broker orderbook. Fully protected on exchange!</i>" if res.get("sl_placed") else f"💡 <i>Recommendation: Set GTT / SL-M trigger at ₹{res['stop_loss']} in {res['broker']} app. Added to scanner watchlist.</i>"

            receipt = (
                f"🎉 <b>ORDER EXECUTED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Product:</b> {res['product_label']}\n"
                f"📈 <b>Quantity:</b> <b>{res['quantity']} shares</b> @ ₹{res['ltp']}\n"
                f"💰 <b>Exposure:</b> ₹{res['actual_exposure']:,} ({res['mode_label']})\n"
                f"🛑 <b>Stop Loss:</b> <b>₹{res['stop_loss']}</b> ({res['sl_mode']}: -{res['risk_pct']}%)\n"
                f"{sl_broker_line}"
                f"⚠️ <b>Risk at SL:</b> ₹{res['total_risk_inr']:,}\n"
                f"🌐 <b>Regime:</b> {res['regime_label']}\n"
                f"{warn_str}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{sl_footer}"
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
        # Ensure executed order receipt is mirrored to dedicated 'orders' topic if not already in orders topic
        orders_chat, orders_thread = get_topic_target("orders")
        if str(chat_id) != str(orders_chat) or (thread_id and thread_id != orders_thread):
            send_topic_alert("orders", receipt)

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
            sl_cancel_note = ""
            if res.get("cancelled_sl_orders"):
                c_str = ", ".join(res["cancelled_sl_orders"])
                sl_cancel_note = f"🛡️ <b>Cancelled Broker SL Orders:</b> <code>{c_str}</code> (No dangling exposure)\n"

            receipt = (
                f"🎉 <b>POSITION EXITED ON {res['broker']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Symbol:</b> {res['symbol']}\n"
                f"🎯 <b>Order ID:</b> <code>{res['order_id']}</code>\n"
                f"📦 <b>Sold Qty:</b> <b>{res['quantity']} shares</b> @ MARKET\n"
                f"💼 <b>Product:</b> {res['product']}\n"
                f"{rem_str}"
                f"{sl_cancel_note}"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Market order submitted to exchange. Tap below to see live portfolio:</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📊 View Updated Positions", "callback_data": "pos_refresh"}]
                ]
            }
            edit_telegram_msg(chat_id, msg_id, receipt, reply_markup=markup)
            # Mirror exit receipt to orders topic
            orders_chat, orders_thread = get_topic_target("orders")
            if str(chat_id) != str(orders_chat) or (thread_id and thread_id != orders_thread):
                send_topic_alert("orders", receipt)
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

    elif cq_data == "trail_refresh":
        answer_callback_query(cq_id, "Refreshing trailing SL recommendations...")
        text, markup = handle_trailing_command()
        edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)

    elif cq_data == "funds_refresh":
        answer_callback_query(cq_id, "Refreshing broker funds & margins...")
        text, markup = handle_funds_command()
        edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)

    elif cq_data == "cand_add_top5":
        cand_file = SCRIPT_DIR / "candidates.json"
        top5_syms = []
        if cand_file.is_file():
            try:
                with open(cand_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    cands = cdata.get("candidates", [])
                    tier1 = [c["symbol"] for c in cands if c.get("tier") == "TIER 1"]
                    tier2 = [c["symbol"] for c in cands if c.get("tier") == "TIER 2"]
                    top5_syms = (tier1 + tier2)[:5]
            except Exception as e:
                pass

        if not top5_syms:
            answer_callback_query(cq_id, "No candidates found in candidates.json!", show_alert=True)
        else:
            curr_syms = read_watchlist_symbols()
            added = []
            already = []
            for s in top5_syms:
                s_u = s.upper().strip()
                if s_u in curr_syms:
                    already.append(s_u)
                else:
                    curr_syms.append(s_u)
                    added.append(s_u)
            if added:
                write_watchlist_symbols(curr_syms)
                push_watchlist_to_github()
                threading.Thread(target=trigger_immediate_rescan, daemon=True).start()
                answer_callback_query(cq_id, f"✅ Added {len(added)} candidates to Watchlist!")
                send_telegram_msg(
                    chat_id,
                    f"✅ <b>PROMOTED TOP 5 CANDIDATES TO WATCHLIST</b>\n"
                    f"• <b>Added ({len(added)}):</b> {', '.join(added)}\n"
                    f"• <b>Total Watchlist Stocks:</b> {len(curr_syms)}\n"
                    f"• Immediate 3m ORB rescan & GitHub Cloud sync triggered!\n"
                    f"• 📊 <a href='https://sanincredible.github.io/Jarvis/'>View on Dashboard</a>",
                    thread_id=thread_id
                )
            else:
                answer_callback_query(cq_id, "All top 5 candidates are already in your watchlist!", show_alert=True)

    elif cq_data.startswith("cand_add:"):
        sym = cq_data.split(":")[1].upper()
        curr_syms = read_watchlist_symbols()
        if sym in curr_syms:
            answer_callback_query(cq_id, f"{sym} is already in your watchlist!", show_alert=True)
        else:
            curr_syms.append(sym)
            write_watchlist_symbols(curr_syms)
            push_watchlist_to_github()
            answer_callback_query(cq_id, f"✅ Added {sym} to live Watchlist!")
            threading.Thread(target=trigger_immediate_rescan, daemon=True).start()
            send_telegram_msg(
                chat_id,
                f"✅ <b>PROMOTED TO WATCHLIST: {sym}</b>\n"
                f"• Added to <code>watchlist.txt</code> ({len(curr_syms)} total stocks)\n"
                f"• Immediate 3m ORB rescan triggered!\n"
                f"• 📊 <a href='https://sanincredible.github.io/Jarvis/'>View on Dashboard</a>",
                thread_id=thread_id
            )

    elif cq_data == "cand_refresh":
        answer_callback_query(cq_id, "Rescanning Nifty 500 candidates...")
        from candidate_scanner import scan_nifty500_candidates, format_candidates_telegram_card
        res = scan_nifty500_candidates(top_n=15)
        text, markup = format_candidates_telegram_card(res, max_display=10)
        edit_telegram_msg(chat_id, msg_id, text, reply_markup=markup)

    elif cq_data == "wl_show":
        answer_callback_query(cq_id, "Opening watchlist...")
        text = handle_watchlist_command()
        send_telegram_msg(chat_id, text, thread_id=thread_id)

    elif cq_data.startswith("trail_be:"):
        parts = cq_data.split(":")
        b_code = parts[1]
        sym = parts[2].upper()
        answer_callback_query(cq_id, f"Ratcheting {sym} Stop-Loss to Breakeven...")
        from order_engine import get_all_open_positions_with_trailing_sl, ratchet_stop_loss_to_breakeven
        positions = get_all_open_positions_with_trailing_sl()
        target_pos = next((p for p in positions if p["symbol"].upper() == sym), None)
        if target_pos:
            ok, res = ratchet_stop_loss_to_breakeven(
                broker=target_pos["broker"],
                symbol=sym,
                quantity=target_pos["qty"],
                entry_price=target_pos["entry_price"],
                product=target_pos["product"]
            )
            be_sl = res.get("breakeven_sl", target_pos["entry_price"])
            if ok:
                answer_callback_query(cq_id, f"✅ {sym} SL moved to Breakeven ₹{be_sl:,.2f}!", show_alert=True)
                send_telegram_msg(
                    chat_id,
                    f"🛡️ <b>STOP-LOSS RATCHETED TO BREAKEVEN: {sym}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Broker:</b> {target_pos['broker']} ({target_pos['product']})\n"
                    f"• <b>Quantity:</b> {target_pos['qty']} shs\n"
                    f"• <b>Entry Price:</b> ₹{target_pos['entry_price']:,.2f}\n"
                    f"• <b>New Hard SL:</b> <b>₹{be_sl:,.2f}</b> (Entry + 0.15% brokerage buffer)\n"
                    f"• <b>Risk Status:</b> 🟢 <b>100% Risk-Free (Free Roll!)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💡 <i>Remaining shares are now riding the 10 EMA (₹{target_pos.get('ema10', 'N/A')}).</i>",
                    thread_id=thread_id
                )
            else:
                err_msg = res.get("message") or res.get("details") or "Broker error"
                answer_callback_query(cq_id, f"⚠️ Notice: {err_msg}", show_alert=True)
        else:
            answer_callback_query(cq_id, f"Position for {sym} not found or already closed.", show_alert=True)

    elif cq_data.startswith("buy_prep:"):
        parts = cq_data.split(":")
        symbol = parts[1] if len(parts) > 1 else ""
        mode = parts[2] if len(parts) > 2 else "mod"
        sl_mode = parts[3] if len(parts) > 3 else "lod"
        broker_arg = parts[4] if len(parts) > 4 else "default"

        from order_engine import get_default_broker
        broker = get_default_broker() if broker_arg == "default" else broker_arg

        answer_callback_query(cq_id, f"Opening order preview for {symbol}...")
        preview_text, markup = build_buy_preview(symbol, mode, sl_mode, broker)
        ok, res = send_telegram_msg(chat_id, preview_text, reply_markup=markup, thread_id=thread_id)
        if not ok:
            print(f"⚠️ Failed to send order preview for {symbol}: {res}", flush=True)


# ---------------------------------------------------------
# Core Message Dispatcher
# ---------------------------------------------------------
def dispatch_command(msg_text, from_chat_id, user_id=None, thread_id=None):
    """Processes incoming Telegram message and returns response text."""
    ext = get_telegram_extended_config()
    auth_chats = ext.get("authorized_chats", [])
    primary_user_id = ext.get("chat_id")

    # Security: strict chat/user validation
    is_group = str(from_chat_id).startswith("-")
    if is_group:
        if primary_user_id and str(user_id) != str(primary_user_id):
            print(f"⛔ Unauthorized user in group: incoming user_id={user_id} vs admin={primary_user_id}", flush=True)
            return f"⛔ <b>Unauthorized:</b> Access restricted to bot administrator."
    else:
        if primary_user_id and str(from_chat_id) != str(primary_user_id) and str(from_chat_id) not in auth_chats:
            print(f"⛔ Unauthorized access attempt: incoming chat_id={from_chat_id} vs primary={primary_user_id}", flush=True)
            return f"⛔ <b>Unauthorized:</b> Access restricted to bot administrator (Your Chat ID: <code>{from_chat_id}</code>)."

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

    if cmd in ("/start", "/help", "start", "help"):
        return handle_help_command()
    elif cmd in ("/add", "/addstock", "add", "addstock"):
        return handle_add_command(args)
    elif cmd in ("/remove", "/del", "/rm", "/delete", "remove", "del", "rm", "delete"):
        return handle_remove_command(args)
    elif cmd in ("/watchlist", "/list", "/stocks", "watchlist", "list", "stocks"):
        return handle_watchlist_command()
    elif cmd in ("/candidates", "/cand", "/screen", "/screener", "/eodscan", "/briefing", "candidates", "cand", "screen", "briefing"):
        return handle_candidates_command()
    elif cmd in ("/positions", "/pos", "/portfolio", "/pnl", "/holdings", "positions", "pos", "pnl"):
        return handle_positions_command()
    elif cmd in ("/trail", "/trailing", "/sl", "/trails", "trail", "trailing"):
        return handle_trailing_command()
    elif cmd in ("/funds", "/fund", "/margin", "/margins", "/cash", "/bal", "/balance", "funds", "fund", "margin", "cash"):
        return handle_funds_command()
    elif cmd in ("/exit", "/close", "/squareoff", "exit", "close"):
        return handle_exit_command(args)
    elif cmd in ("/journal", "/syncjournal", "/sync", "/eod", "/summary", "journal", "sync", "eod", "summary"):
        return handle_journal_command()
    elif cmd in ("/token", "/tokens", "/status", "/check", "token", "tokens", "status"):
        if args:
            sub_parts = args.split(maxsplit=1)
            sub_cmd = sub_parts[0].lower()
            sub_tok = sub_parts[1] if len(sub_parts) > 1 else ""
            if sub_cmd in ("upstox", "dhan", "zerodha"):
                return handle_update_token_command(sub_cmd, sub_tok)
        return handle_token_status_command()
    elif cmd in ("/upstox", "upstox"):
        return handle_update_token_command("upstox", args)
    elif cmd in ("/dhan", "dhan"):
        return handle_update_token_command("dhan", args)
    elif cmd in ("/zerodha", "zerodha"):
        return handle_update_token_command("zerodha", args)
    elif cmd in ("/buy", "/mtf", "/order", "buy", "order"):
        return handle_buy_command(args, from_chat_id)
    elif cmd in ("/broker", "/brokers", "broker"):
        return handle_broker_command(args)
    elif cmd in ("/scan", "/refresh", "scan", "refresh"):
        return handle_scan_command()
    elif cmd in ("/regime", "regime"):
        return handle_regime_command()
    elif cmd in ("/topics", "/topic", "/id"):
        group_id = ext.get("group_id", "Not configured")
        topics = ext.get("topics", {})
        topic_lines = "\n".join([f"• <b>{k}:</b> Topic ID <code>{v}</code>" for k, v in topics.items()])
        return (
            f"ℹ️ <b>TELEGRAM TOPIC CONFIGURATION</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Current Chat ID:</b> <code>{from_chat_id}</code>\n"
            f"• <b>Current Topic Thread:</b> <code>{thread_id or 'General / DM'}</code>\n"
            f"• <b>Sender User ID:</b> <code>{user_id}</code>\n"
            f"• <b>Supergroup ID:</b> <code>{group_id}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Topic Mappings:</b>\n{topic_lines}\n\n"
            "<i>Commands & alerts automatically route to their dedicated topic threads!</i>"
        )
    elif cmd == "/settopic":
        if not args or len(args.split()) < 2:
            return "<b>Usage:</b> <code>/settopic &lt;topic_name&gt; &lt;thread_id&gt;</code>\n<i>e.g. /settopic orb_signals 8</i>"
        parts = args.split()
        t_name = parts[0].lower()
        try:
            t_id = int(parts[1])
        except ValueError:
            return "❌ Thread ID must be an integer."
        cfg = load_config()
        if "telegram" not in cfg:
            cfg["telegram"] = {}
        if "topics" not in cfg["telegram"]:
            cfg["telegram"]["topics"] = {}
        cfg["telegram"]["topics"][t_name] = t_id
        if save_config(cfg):
            return f"✅ Topic <code>{t_name}</code> mapped to Thread ID <code>{t_id}</code>."
        else:
            return "❌ Failed to save config_credentials.json."
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
            print("Telegram Bot listener received stop signal.", flush=True)
            break

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates?timeout=15"
        if offset is not None:
            url += f"&offset={offset}"

        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Bot-Poller"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                updates = data.get("result", [])
                for u in updates:
                    offset = u["update_id"] + 1

                    try:
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
                        thread_id = msg.get("message_thread_id")
                        from_user = msg.get("from", {})
                        user_id = from_user.get("id")
                        text = msg.get("text", "")
                        sender = from_user.get("first_name", "User")

                        print(f"📩 [{get_ist_now().strftime('%H:%M:%S')}] Telegram from {sender} (ChatID: {chat_id}, Thread: {thread_id}): {text[:50]}", flush=True)

                        reply = dispatch_command(text, chat_id, user_id=user_id, thread_id=thread_id)
                        if reply:
                            if isinstance(reply, tuple):
                                ok, resp_data = send_telegram_msg(chat_id, reply[0], reply_markup=reply[1], thread_id=thread_id)
                            else:
                                ok, resp_data = send_telegram_msg(chat_id, reply, thread_id=thread_id)
                            if not ok:
                                print(f"⚠️ Failed to send Telegram reply to {chat_id} (thread {thread_id}): {resp_data}", flush=True)
                            else:
                                print(f"✅ Replied to {chat_id} (thread {thread_id}) for command: {text[:30]}", flush=True)
                    except Exception as item_ex:
                        print(f"❌ Error processing update {u.get('update_id')}: {item_ex}", flush=True)
                        import traceback
                        traceback.print_exc()

        except urllib.error.HTTPError as he:
            if he.code == 409:
                print("⚠️ Telegram 409 Conflict: another poller active. Sleeping 5s...", flush=True)
                time.sleep(5)
            else:
                print(f"⚠️ Telegram HTTPError {he.code}: {he}", flush=True)
                time.sleep(2)
        except Exception as e:
            # Handle socket timeout or transient network hiccups
            print(f"ℹ️ Telegram Poller notice: {type(e).__name__}: {e}", flush=True)
            time.sleep(2)


# ---------------------------------------------------------
# Background Thread Runner
# ---------------------------------------------------------
_sent_trailing_alerts = {}  # (symbol, alert_type) -> timestamp


def run_trailing_surveillance_worker():
    """
    Background autonomous surveillance loop running during market hours.
    Monitors live broker positions for Stop-Loss danger breaches and trailing milestone triggers,
    pushing instant actionable alerts to Telegram.
    """
    print("🛡️ Trailing & Risk Surveillance Worker started in background.")
    from order_engine import is_market_open, get_all_open_positions_with_trailing_sl

    while not _bot_stop_event.is_set():
        try:
            if is_market_open():
                positions = get_all_open_positions_with_trailing_sl()
                now_ts = time.time()
                bot_token, chat_id = get_telegram_config()

                if chat_id and positions:
                    for p in positions:
                        sym = p.get("symbol", "").upper()
                        ltp = float(p.get("ltp", 0) or 0)
                        entry_p = float(p.get("entry_price", 0) or 0)
                        sl = float(p.get("initial_sl", 0) or 0)
                        rec_sl = float(p.get("recommended_sl", 0) or 0)
                        dist_sl = float(p.get("dist_to_sl_pct", 99.0))
                        r_mult = float(p.get("r_multiple", 0.0))
                        pnl = float(p.get("pnl", 0.0))
                        pnl_pct = float(p.get("pnl_pct", 0.0))
                        broker = p.get("broker", "UNKNOWN")
                        prod = p.get("product", "MTF")
                        badge = p.get("action_badge", "")
                        qty = int(p.get("qty", 0) or 0)
                        b_code = broker[:1].lower() if broker else "u"

                        # 1. Danger SL Warning (Distance <= 0.85% or SL Hit)
                        if (dist_sl <= 0.85 or ltp <= sl or "SL HIT" in badge or "NEAR SL" in badge) and sl > 0 and ltp > 0:
                            alert_key = (sym, "DANGER_SL")
                            last_sent = _sent_trailing_alerts.get(alert_key, 0)
                            # Cooldown: 15 minutes unless SL breached
                            if (now_ts - last_sent > 900) or (ltp <= sl and now_ts - last_sent > 300):
                                is_hit = ltp <= sl
                                title = f"🔴 <b>STOP-LOSS BREACHED: {sym}!</b>" if is_hit else f"🚨 <b>RISK DANGER: {sym} NEAR SL!</b>"
                                status_desc = f"<b>CRITICAL:</b> LTP ₹{ltp:,.2f} is below Stop-Loss ₹{sl:,.2f}!" if is_hit else f"Price is only <b>{dist_sl:.2f}%</b> (₹{abs(ltp-sl):,.2f}) away from Stop-Loss ₹{sl:,.2f}."
                                var_inr = float(p.get("value_at_risk", 0.0) or 0.0)
                                var_str = "🟢 ₹0.00 (Risk-Free)" if var_inr <= 0 else f"⚠️ -₹{var_inr:,.2f}"

                                alert_msg = (
                                    f"{title}\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"📌 <b>Symbol:</b> {sym} ({broker} • {prod})\n"
                                    f"📈 <b>LTP:</b> ₹{ltp:,.2f} | <b>Stop-Loss:</b> ₹{sl:,.2f}\n"
                                    f"⚠️ <b>Buffer:</b> {dist_sl:.2f}% | <b>Value at Risk:</b> {var_str}\n"
                                    f"💼 <b>Open Qty:</b> {qty} shs | <b>P&L:</b> ₹{pnl:+,.2f} ({pnl_pct:+.1f}%)\n"
                                    f"🎯 <b>Action:</b> <b>{badge}</b>\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"💡 {status_desc}\n"
                                    "<i>Protect your capital and adhere to trade stops!</i>"
                                )
                                kb = [
                                    [{"text": f"🔴 Exit {sym} Now", "callback_data": f"ex_p:{b_code}:{sym}"}],
                                    [{"text": "🎯 Trailing Cockpit", "callback_data": "trail_refresh"}]
                                ]
                                send_topic_alert("risk_trailing", alert_msg, reply_markup={"inline_keyboard": kb})
                                _sent_trailing_alerts[alert_key] = now_ts

                        # 2. Super Winner (+3R or +6% gain) -> Book 50% AND ensure Breakeven Ratchet is applied
                        elif (r_mult >= 3.0 or pnl_pct >= 6.0) and r_mult > 0:
                            # Autonomous check: ensure SL is at least at Breakeven
                            raw_be = entry_p * 1.0015
                            from order_engine import round_to_tick
                            breakeven_sl = round_to_tick(raw_be)
                            if sl < breakeven_sl and entry_p > 0 and sl > 0:
                                ratchet_key = (sym, "AUTO_BREAKEVEN")
                                if now_ts - _sent_trailing_alerts.get(ratchet_key, 0) > 1800:
                                    _sent_trailing_alerts[ratchet_key] = now_ts
                                    from order_engine import ratchet_stop_loss_to_breakeven
                                    ratchet_stop_loss_to_breakeven(
                                        broker=broker,
                                        symbol=sym,
                                        quantity=qty,
                                        entry_price=entry_p,
                                        product=prod
                                    )

                            alert_key = (sym, "BOOK_3R")
                            last_sent = _sent_trailing_alerts.get(alert_key, 0)
                            if now_ts - last_sent > 3600:  # 1 hour cooldown
                                half_qty = max(1, qty // 2)
                                alert_msg = (
                                    f"⭐ <b>SUPER WINNER: {sym} SURGES +{r_mult:.1f}R!</b>\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"📌 <b>Symbol:</b> {sym} ({broker} • {prod})\n"
                                    f"📈 <b>LTP:</b> ₹{ltp:,.2f} (Entry: ₹{entry_p:,.2f})\n"
                                    f"🚀 <b>Gain:</b> <b>+{pnl_pct:.1f}%</b> (+{r_mult:.1f}R)\n"
                                    f"💰 <b>Unrealized P&L:</b> ₹{pnl:+,.2f}\n"
                                    f"🎯 <b>Guidance:</b> Book 50% profit now to lock in gains, trail rest to ₹{rec_sl:,.2f}!\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                                    "💡 <i>Tap below to execute partial exit immediately:</i>"
                                )
                                kb = [
                                    [{"text": f"🟡 Book 50% ({half_qty} shs)", "callback_data": f"ex_x:{b_code}:{sym}:half"}],
                                    [{"text": "🎯 Trailing Cockpit", "callback_data": "trail_refresh"}, {"text": f"🔴 Exit 100%", "callback_data": f"ex_p:{b_code}:{sym}"}]
                                ]
                                send_topic_alert("risk_trailing", alert_msg, reply_markup={"inline_keyboard": kb})
                                _sent_trailing_alerts[alert_key] = now_ts

                        # 3. JEFF SUN AUTOMATED BREAKEVEN RATCHET (+1.5R or +2.5% Gain)
                        elif (r_mult >= 1.5 or pnl_pct >= 2.5) and r_mult > 0 and entry_p > 0:
                            ratchet_key = (sym, "AUTO_BREAKEVEN")
                            last_sent = _sent_trailing_alerts.get(ratchet_key, 0)
                            if (now_ts - last_sent > 1800) and sl > 0:
                                from order_engine import round_to_tick, ratchet_stop_loss_to_breakeven
                                raw_be = entry_p * 1.0015
                                breakeven_sl = round_to_tick(raw_be)
                                if sl < breakeven_sl:
                                    # Set cooldown immediately so we NEVER hammer broker in a loop on failure!
                                    _sent_trailing_alerts[ratchet_key] = now_ts
                                    r_ok, r_res = ratchet_stop_loss_to_breakeven(
                                        broker=broker,
                                        symbol=sym,
                                        quantity=qty,
                                        entry_price=entry_p,
                                        product=prod
                                    )
                                    if r_ok:
                                        ema10_val = p.get("ema10", "N/A")
                                        alert_msg = (
                                            f"🛡️ <b>JEFF SUN AUTO-TRAIL: {sym} RATCHETED TO BREAKEVEN!</b>\n"
                                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                            f"🚀 <b>Target Milestone Reached:</b> <b>+{r_mult:.1f}R (+{pnl_pct:.1f}%)</b>\n"
                                            f"📌 <b>Symbol:</b> {sym} ({broker} • {prod} • {qty} shs)\n"
                                            f"📈 <b>LTP:</b> ₹{ltp:,.2f} (Entry: ₹{entry_p:,.2f})\n"
                                            f"🔒 <b>Broker Stop-Loss Ratcheted:</b> ₹{sl:,.2f} ➔ <b>₹{breakeven_sl:,.2f}</b>\n"
                                            f"💰 <b>Covered Buffer:</b> Entry + 0.15% fee buffer\n"
                                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                            "🎉 <b>Capital Risk is 100% ELIMINATED!</b>\n"
                                            "• The trade is now a guaranteed risk-free runner.\n"
                                            f"• <b>Trailing Guide:</b> Riding the <b>10 EMA</b> (₹{ema10_val}). Hold until daily close &lt; 10 EMA."
                                        )
                                        kb = [
                                            [{"text": f"🟡 Book 50% ({max(1, qty//2)} shs)", "callback_data": f"ex_x:{b_code}:{sym}:half"}],
                                            [{"text": "🎯 Trailing Cockpit", "callback_data": "trail_refresh"}, {"text": f"🔴 Exit {sym}", "callback_data": f"ex_p:{b_code}:{sym}"}]
                                        ]
                                        send_topic_alert("risk_trailing", alert_msg, reply_markup={"inline_keyboard": kb})
                                    else:
                                        err_details = r_res.get("details") or r_res.get("message") or "Broker SL rejection"
                                        send_topic_alert(
                                            "risk_trailing",
                                            f"⚠️ <b>AUTO-TRAIL NOTICE: {sym} Breakeven Ratchet Failed</b>\n"
                                            f"• <b>Symbol:</b> {sym} ({broker} • {prod})\n"
                                            f"• <b>Target SL:</b> ₹{breakeven_sl:,.2f}\n"
                                            f"• <b>Broker Feedback:</b> <code>{err_details}</code>\n"
                                            "<i>Cooldown active (30 mins). Will not retry immediately to prevent repeated broker orders.</i>"
                                        )
        except Exception:
            pass

        # Sleep 60s
        for _ in range(60):
            if _bot_stop_event.is_set():
                break
            time.sleep(1)


_bot_thread = None
_surveillance_thread = None
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

    global _surveillance_thread
    _surveillance_thread = threading.Thread(
        target=run_trailing_surveillance_worker,
        daemon=True,
        name="TrailingSurveillanceThread"
    )
    _surveillance_thread.start()

    return _bot_thread


if __name__ == "__main__":
    try:
        run_telegram_bot_loop()
    except KeyboardInterrupt:
        print("\nExiting Telegram Bot.")
