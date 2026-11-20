import concurrent.futures
# -*- coding: utf-8 -*-
"""
Upstox Pro 3-Minute TF Watchlist Scanner — Samsung Galaxy Tablet Edition
100% Faithful Implementation of TradingView Pine Script:
'Swing Data + Strong Start RVOL Dashboard' (MikeC / finallynitin)

Dual-Mode Tablet Support:
1. Interactive Terminal: Stocks numbered [1] to [16] — type number + Enter to open TradingView App!
2. Local Web Dashboard: Runs on http://localhost:5000 — 1-tap touch buttons to open TradingView App!
"""

import os
import sys
import json
import time
import socket
import threading
import webbrowser
import http.server
import socketserver
import urllib.request
import urllib.parse
import tempfile
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now():
    """Returns current datetime strictly in Indian Standard Time (IST), timezone-naive for arithmetic."""
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    from upstox_websocket_feed import UpstoxWebSocketFeed
    UPSTOX_WS_AVAILABLE = True
except Exception:
    UpstoxWebSocketFeed = None
    UPSTOX_WS_AVAILABLE = False

ACTIVE_WS_FEED = [None]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config_credentials.json")
REFRESH_SECONDS = 180  # 3 minutes

# Watchlist symbols
WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "SBIN", "HDFCBANK",
    "MARUTI", "ITC", "ICICIBANK", "AXISBANK", "LT",
    "VIJAYA", "LICHSGFIN", "INOXWIND", "WESTLIFE", "BELRISE", "URBANCO"
]

# Common NSE Instrument Keys Mapping (Upstox Format: NSE_EQ|ISIN or NSE_EQ|SYMBOL)
SYMBOL_TO_ISIN = {
    "RELIANCE": "INE002A01018",
    "TCS": "INE467B01029",
    "INFY": "INE009A01021",
    "SBIN": "INE062A01020",
    "HDFCBANK": "INE040A01034",
    "MARUTI": "INE585B01010",
    "ITC": "INE154A01025",
    "ICICIBANK": "INE090A01021",
    "AXISBANK": "INE238A01034",
    "LT": "INE018A01030",
    "VIJAYA": "INE043W01024",
    "LICHSGFIN": "INE115A01026",
    "INOXWIND": "INE066P01011",
    "WESTLIFE": "INE274F01020",
    "BELRISE": "INE894V01022",
    "URBANCO": "INE01ZZ01010",
    "PARAGMILK": "INE883N01014",
    "ADANIPOWER": "INE814H01029",
    "OAL": "INE959C01023",
    "EIMCOELECO": "INE158B01016",
    "SAREGAMA": "INE979A01025",
    "GRAPHITE": "INE371A01025",
    "PINELABS": "INE15B701018",
    "CYIENT": "INE136B01020",
    "NRAIL": "INE740D01017",
    "AEQUS": "INE947N01017",
    "HONASA": "INE0J5401028",
    "ABDL": "INE552Z01027",
    "JINDWORLD": "INE247D01039",
    "LOTUSDEV": "INE0V9Q01010",
    "TDPOWERSYS": "INE419M01035",
    "ECLERX": "INE738I01010",
    "AEGISLOG": "INE208C01025",
    "SYRMA": "INE0DYJ01015",
    "KIRLOSENG": "INE146L01010",
    "CASTROL": "INE172A01027",
    "CASTROLIND": "INE172A01027",
    "AEROFLEX": "INE024001021",
    "MMP": "INE511Y01018",
    "WHEELS": "INE715A01015",
    "SOLARA": "INE624Z01016",
    "TBOTEK": "INE07VO01018",
    "SOMANYCERA": "INE355A01028",
    "PITTIENG": "INE374C01012",
    "BLUEJET": "INE0BCJ01022",
    "BLACKBUCK": "INE0OH201010",
    "PARAS": "INE045601015",
    "GOCLCORP": "INE079A01024",
    "BBOX": "INE220B01022",
    "ACMESOLAR": "INE620Z01019",
    "KRN": "INE0C9501010",
    "NOVARTIND": "INE234A01025",
    "INDEGENE": "INE065X01017",
    "INDGN": "INE065X01017",
}

INDEX_MAPPING = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY50": "NSE_INDEX|Nifty 50",
    "CNXNIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "NIFTYBANK": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
}


SYMBOL_ALIASES = {
    "JAYNECOND": "JAYNECOIND",
    "DALTACORP": "DELTACORP",
    "SAMBHAV": "SAMBHV",
    "HBLPOWER": "HBLENGINE",
    "INDEGENE": "INDGN",
}


def resolve_isin_dynamic(symbol):
    """Dynamically resolves unknown symbol to ISIN from Upstox instruments cache."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstox_nse_cache.json")
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                c_map = json.load(f)
                if symbol in c_map:
                    return c_map[symbol]
        except Exception:
            pass
    try:
        import gzip
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(gzip.decompress(resp.read()).decode("utf-8"))
        c_map = {}
        for inst in data:
            if inst.get("segment") == "NSE_EQ" and inst.get("trading_symbol") and inst.get("isin"):
                c_map[inst["trading_symbol"]] = inst["isin"]
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(c_map, f)
        return c_map.get(symbol)
    except Exception:
        return None


def calculate_tod_volume_fraction(session_mins: float) -> float:
    """
    Continuous piecewise linear cumulative volume function F(m) for NSE trading day (09:15 to 15:30 IST, m in [0, 375]).
    Anchors:
      m = 0   (09:15 AM): F(0)   = 0.00  (Start of session, zero cumulative volume)
      m = 15  (09:30 AM): F(15)  = 0.10  (10.0% volume after opening 15-min discovery)
      m = 60  (10:15 AM): F(60)  = 0.25  (25.0% volume after 1st hour breakout prime window)
      m = 285 (14:00 PM): F(285) = 0.65  (65.0% volume through mid-day lull)
      m = 375 (15:30 PM): F(375) = 1.00  (100.0% volume at market close)
    Strictly continuous at all knot points with a safe floor of 0.01 (1%).
    """
    m = max(0.0, min(375.0, float(session_mins)))
    if m <= 15.0:
        pct = 0.00 + (m / 15.0) * 0.10
    elif m <= 60.0:
        pct = 0.10 + ((m - 15.0) / 45.0) * 0.15
    elif m <= 285.0:
        pct = 0.25 + ((m - 60.0) / 225.0) * 0.40
    else:
        pct = 0.65 + ((m - 285.0) / 90.0) * 0.35
    return max(0.01, round(pct, 4))

# ANSI Colors matching Pine Script Palette
GREEN = "\033[92m"        # Lime / Green (#0b8043)
RED = "\033[91m"          # Red (#cc2222)
ORANGE = "\033[38;5;214m" # Orange / Amber (#c77800)
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"
GRAY = "\033[90m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"
RESET = "\033[0m"

# Global cache for dual-mode access
data_lock = threading.Lock()
latest_results = []
last_scan_time = ""
active_web_port = 5000


def load_upstox_token():
    """Loads active Upstox access token from config_credentials.json, environment, or upstoxtoken.txt."""
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if token:
        return token

    # Primary source of truth: config_credentials.json
    for cfg_path in [CONFIG_FILE, os.path.join(SCRIPT_DIR, "config_credentials.json"), os.path.join(SCRIPT_DIR, "credentials.json"), "config_credentials.json", "credentials.json"]:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    tok = cfg.get("upstox", {}).get("access_token", "").strip()
                    if tok:
                        return tok
            except Exception:
                pass

    # Fallback to local txt file if present
    for txt_p in [os.path.join(SCRIPT_DIR, "upstoxtoken.txt"), "upstoxtoken.txt"]:
        if os.path.isfile(txt_p):
            try:
                with open(txt_p, "r", encoding="utf-8") as f:
                    tok = f.read().strip()
                    if tok:
                        return tok
            except Exception:
                pass

    return None


def load_github_config():
    """Loads GitHub token and repo config from credentials file."""
    for cfg_path in [CONFIG_FILE, os.path.join(SCRIPT_DIR, "config_credentials.json"), os.path.join(SCRIPT_DIR, "credentials.json"), "config_credentials.json", "credentials.json"]:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    gh = cfg.get("github")
                    if gh and gh.get("token"):
                        return gh
            except Exception:
                pass
    return None


def sync_remote_files_from_github():
    """Pulls latest watchlist.txt and self-updates upstox_tablet_scanner.py from GitHub over HTTPS (443)."""
    # Windows is the master workstation: NEVER overwrite local watchlist.txt from remote GitHub!
    if sys.platform == "win32":
        return

    gh_cfg = load_github_config()
    if not gh_cfg or not gh_cfg.get("token"):
        return
    try:
        import base64
        token = gh_cfg["token"].strip()
        owner = gh_cfg.get("username", "sanIncredible").strip()
        repo = gh_cfg.get("repo", "Jarvis").strip()
        branch = gh_cfg.get("branch", "main").strip()

        # 1. Sync watchlist data from GitHub
        for filename in ["watchlist.txt"]:
            # If local watchlist.txt was modified within the last 60 seconds (e.g. Telegram bot edit), don't overwrite!
            if os.path.isfile(filename):
                try:
                    if (time.time() - os.path.getmtime(filename)) < 60:
                        continue
                except Exception:
                    pass
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}?ref={branch}"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Jarvis-GitHub-Pull",
                "Accept": "application/vnd.github+json"
            })
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    content_b64 = data.get("content", "")
                    if content_b64:
                        content_str = base64.b64decode(content_b64).decode("utf-8").strip()
                        if content_str:
                            norm_content = content_str.replace("\r\n", "\n").replace("\r", "\n").strip()
                            remote_syms = [l.strip().upper() for l in norm_content.splitlines() if l.strip() and not l.startswith("#")]
                            # Authority policy: replace watchlist directly from remote master (don't merge old local symbols)
                            lines_out = [
                                "# Upstox 3m ORB Scanner Watchlist",
                                "# Add or remove NSE stock tickers below (one per line, or space/comma separated)",
                                ""
                            ] + remote_syms
                            with open(filename, "w", encoding="utf-8") as f:
                                f.write("\n".join(lines_out) + "\n")
            except Exception:
                pass

        # 2. Check for self-updates to upstox_tablet_scanner.py (only on tablet / non-Windows devices)
        if sys.platform != "win32":
            try:
                url_code = f"https://api.github.com/repos/{owner}/{repo}/contents/upstox_tablet_scanner.py?ref={branch}"
                req_c = urllib.request.Request(url_code, headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "Jarvis-GitHub-Pull",
                    "Accept": "application/vnd.github+json"
                })
                with urllib.request.urlopen(req_c, timeout=5) as resp_c:
                    data_c = json.loads(resp_c.read().decode("utf-8"))
                    code_b64 = data_c.get("content", "")
                    if code_b64:
                        new_code = base64.b64decode(code_b64).decode("utf-8")
                        this_file = os.path.abspath(__file__)
                        if os.path.isfile(this_file):
                            with open(this_file, "r", encoding="utf-8") as cf:
                                current_code = cf.read()
                            norm_current = current_code.replace("\r\n", "\n").strip()
                            norm_new = new_code.replace("\r\n", "\n").strip()
                            if norm_current and norm_new != norm_current:
                                # Validate Python syntax before applying
                                compile(new_code, this_file, "exec")
                                with open(this_file, "w", encoding="utf-8", newline="\n") as wf:
                                    wf.write(norm_new)
                                print("\n🔄 Updated scanner engine pulled from GitHub! Reloading process...")
                                time.sleep(1)
                                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------
# Telegram Instant Breakout Alert Engine
# ---------------------------------------------------------
sent_alerts = set()  # Tracks (symbol, alert_type, date_str) to prevent repetitive spam


def load_telegram_config():
    """Loads Telegram Bot token, Chat ID, Group ID, and Topic Mappings from environment or config file."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    group_id = os.getenv("TELEGRAM_GROUP_ID", "").strip()

    cfg_data = None
    for cfg_f in [CONFIG_FILE, os.path.join(SCRIPT_DIR, "config_credentials.json"), os.path.join(SCRIPT_DIR, "credentials.json"), "config_credentials.json", "credentials.json"]:
        if os.path.isfile(cfg_f):
            try:
                with open(cfg_f, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    break
            except Exception:
                pass

    if cfg_data and cfg_data.get("telegram"):
        tg = dict(cfg_data["telegram"])
        if token:
            tg["bot_token"] = token
        if chat_id:
            tg["chat_id"] = chat_id
        if group_id:
            tg["group_id"] = group_id
        return tg

    if token and chat_id:
        return {"enabled": True, "bot_token": token, "chat_id": chat_id, "group_id": group_id, "topics": {}}

    return None


def send_telegram_alert(message, parse_mode="HTML", reply_markup=None, topic_name="orb_signals"):
    """Sends a Telegram alert via HTTPS (Port 443) to designated topic or chat. Returns (success, response_or_error)."""
    tg_cfg = load_telegram_config()
    if not tg_cfg or not tg_cfg.get("enabled", True):
        return False, "Telegram alerts disabled or not configured"

    bot_token = tg_cfg.get("bot_token", "").strip()
    chat_id = str(tg_cfg.get("chat_id", "")).strip()
    group_id = str(tg_cfg.get("group_id", "")).strip()
    topics = tg_cfg.get("topics", {})

    target_chat = chat_id
    thread_id = None
    if group_id and topic_name and topic_name in topics:
        target_chat = group_id
        thread_id = topics[topic_name]

    if not bot_token or not target_chat:
        return False, "Missing bot_token or target chat_id"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
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
        with urllib.request.urlopen(req, timeout=8) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            return res_data.get("ok", False), res_data
    except Exception as e:
        return False, str(e)


def send_telegram_alert_async(message, parse_mode="HTML", reply_markup=None, topic_name="orb_signals"):
    """Dispatches Telegram alert asynchronously without blocking scanner loop."""
    def _worker():
        send_telegram_alert(message, parse_mode=parse_mode, reply_markup=reply_markup, topic_name=topic_name)
    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------
# Intraday Sector & Theme Cluster Surveillance
# ---------------------------------------------------------
_DAILY_THEME_BREAKOUTS = {}  # key: theme_name, value: list of {symbol, ltp, trigger, time}
_LAST_THEME_DATE = [None]

def get_theme_breakout_count(theme_name):
    """Returns number of stocks in this theme that have broken out today."""
    global _DAILY_THEME_BREAKOUTS
    return len(_DAILY_THEME_BREAKOUTS.get(theme_name, []))

def get_all_theme_breakouts():
    """Returns the dictionary of all today's theme breakouts."""
    global _DAILY_THEME_BREAKOUTS
    return dict(_DAILY_THEME_BREAKOUTS)


def evaluate_and_dispatch_alerts(results, current_time_str):
    """Evaluates scan results and dispatches rich Action Card Telegram alerts for newly triggered stocks."""
    global _DAILY_THEME_BREAKOUTS, _LAST_THEME_DATE
    today = get_ist_now().strftime("%Y-%m-%d")
    if _LAST_THEME_DATE[0] != today:
        _LAST_THEME_DATE[0] = today
        _DAILY_THEME_BREAKOUTS = {}

    t_clean = current_time_str.replace(" IST", "")
    if len(t_clean.split(":")) >= 2:
        t_clean = ":".join(t_clean.split(":")[:2]) + " IST"
    else:
        t_clean = current_time_str

    # Load active open holdings for Pyramiding detection
    open_holdings = {}
    for th_file in [
        "tracked_holdings.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracked_holdings.json")
    ]:
        if os.path.isfile(th_file):
            try:
                with open(th_file, "r", encoding="utf-8") as th_f:
                    open_holdings = json.load(th_f)
                break
            except Exception:
                pass

    new_breakouts = []
    new_coils = []
    active_breakout_setups = []
    for row in results:
        score, d, m = row
        sym = d.get("symbol")
        ltp = d.get("ltp")
        orb_h = d.get("orb_high")
        pdh = d.get("pdh")
        signal = m.get("signal", "")
        orb_status = m.get("orb_status")
        pdh_broken = m.get("pdh_broken")

        if not ltp or not orb_h:
            continue

        trigger_label = None
        alert_type = None

        # 0. Diamond Tier: Strict Criteria Setup (Narrow Prev Day + Strong Start + PDH Breakout)
        is_nr_stock = bool((d.get("prev_range_ratio") and d.get("prev_range_ratio") <= 0.75) or d.get("is_inside_day") or d.get("is_narrow_prev_day"))
        is_reversal_sig = bool(m.get("is_reversal"))

        if m.get("is_strict") or ("STRICT" in signal):
            alert_type = "ORB_STRICT_TIER1"
            if is_reversal_sig:
                trigger_label = "💎 STRICT (NR + REVERSAL + PDH)"
            else:
                trigger_label = "💎 STRICT (NR + SS + PDH Break)"

        # 1. Tier 0: Afternoon Spring Reversal (Coiled NR stock broke ORB Low earlier, now breaking ORB High & PDH)
        elif is_reversal_sig and pdh_broken and is_nr_stock:
            alert_type = "ORB_SPRING_REVERSAL"
            trigger_label = "💎 Spring Reversal (NR + L→H + PDH)"

        # 2. Bullish Reversal Breakout (Broke ORB Low first, now breaking ORB High)
        elif is_reversal_sig:
            alert_type = "ORB_REVERSAL"
            if pdh_broken:
                trigger_label = "🔄 Reversal + PDH"
            else:
                trigger_label = "🔄 Reversal (L→H)"

        # 2. Tier 1: Strong Start + ORB + PDH Breakout (Highest Conviction)
        elif "STRONG START + ORB + PDH" in signal:
            alert_type = "ORB_PDH_STRONG"
            trigger_label = "★ SS + ORB + PDH Break"

        # 3. Tier 2: Bullish Breakout (ORB + PDH)
        elif pdh_broken and orb_status == "H":
            alert_type = "ORB_PDH"
            trigger_label = "ORB + PDH Break"

        # 4. Tier 3: Pure ORB High Breakout
        elif orb_status == "H":
            alert_type = "ORB_HIGH"
            trigger_label = "ORB High Break"

        # 5. Pre-Breakout Coiling Setup (Coiling within 0.05% to 0.60% below ORB High or PDH)
        elif not alert_type and ltp and (orb_h or pdh) and orb_status != "H":
            is_coiling = False
            coil_anchor = ""
            coil_level = 0.0
            dist_pct = 0.0

            if orb_h and float(ltp) < float(orb_h):
                d_pct = ((float(orb_h) - float(ltp)) / float(orb_h)) * 100.0
                if 0.05 <= d_pct <= 0.60:
                    is_coiling = True
                    coil_anchor = "ORB High"
                    coil_level = float(orb_h)
                    dist_pct = d_pct
            elif pdh and float(ltp) < float(pdh):
                d_pct = ((float(pdh) - float(ltp)) / float(pdh)) * 100.0
                if 0.05 <= d_pct <= 0.60:
                    is_coiling = True
                    coil_anchor = "PDH"
                    coil_level = float(pdh)
                    dist_pct = d_pct

            if is_coiling:
                coil_key = (sym, "PRE_BREAKOUT_COIL", today)
                if coil_key not in sent_alerts:
                    sent_alerts.add(coil_key)
                    new_coils.append({
                        "sym": sym,
                        "ltp": float(ltp),
                        "anchor": coil_anchor,
                        "level": coil_level,
                        "dist_pct": round(dist_pct, 2),
                        "is_inside_day": bool(d.get("is_inside_day")),
                        "is_narrow": bool(d.get("is_narrow_prev_day")),
                        "day_low": float(d.get("day_low") or m.get("day_low") or (float(ltp) * 0.985))
                    })

        if alert_type and trigger_label:
            active_breakout_setups.append((sym, d, m, trigger_label))
            alert_key = (sym, alert_type, today)
            if alert_key not in sent_alerts:
                sent_alerts.add(alert_key)

                day_low = m.get("day_low") or d.get("day_low")
                atr14 = d.get("atr14")
                lod_dist = m.get("lod_dist")
                if lod_dist is None and day_low and atr14 and float(atr14) > 0:
                    lod_dist = round(((float(ltp) - float(day_low)) / float(atr14)) * 100.0)

                stretch_pct = m.get("stretch_pct")

                # P2 Adaptive LOD Stop Buffer (3m ATR)
                risk_pct = None
                sl_calc = day_low
                if day_low and ltp and float(ltp) > 0:
                    atr_val = atr14 or d.get("atr")
                    if atr_val and float(atr_val) > 0:
                        atr_f = float(atr_val)
                        atr_3m_approx = atr_f / 6.0 if atr_f > (float(ltp) * 0.015) else atr_f
                        adaptive_buf = max(1.0, round(atr_3m_approx * 0.25, 2))
                    else:
                        adaptive_buf = max(1.0, round(float(day_low) * 0.0020, 2))

                    stop_buffer = max(1.0, round(max(adaptive_buf, float(day_low) * 0.0015)))
                    sl_calc = round(float(day_low) - stop_buffer, 2)
                    if sl_calc >= float(ltp):
                        sl_calc = round(float(ltp) * 0.985, 2)
                    risk_pct = round(((float(ltp) - sl_calc) / float(ltp)) * 100.0, 1)

                is_gap_up = bool(m.get("is_gap_up") or d.get("is_gap_up"))
                gap_pct = m.get("gap_pct") if m.get("gap_pct") is not None else d.get("gap_pct")

                is_spring_rev = bool(alert_type == "ORB_SPRING_REVERSAL")
                if is_spring_rev and risk_pct and risk_pct > 2.0:
                    day_low = round(float(ltp) * 0.985, 2)
                    risk_pct = 1.5

                holding_info = open_holdings.get(sym)
                is_pyramid = holding_info is not None

                day_high_raw = float(d.get("day_high") or d.get("high") or ltp)

                # Sector Theme Resolution & Cluster Tracking
                from order_engine import resolve_sector_theme
                t_info = resolve_sector_theme(sym, industry=d.get("industry"), quote_data=d)
                theme_name = t_info.get("theme", "General Equities")
                theme_icon = t_info.get("icon", "🏢")

                if theme_name not in _DAILY_THEME_BREAKOUTS:
                    _DAILY_THEME_BREAKOUTS[theme_name] = []
                if not any(x.get("symbol") == sym for x in _DAILY_THEME_BREAKOUTS[theme_name]):
                    _DAILY_THEME_BREAKOUTS[theme_name].append({
                        "symbol": sym,
                        "ltp": float(ltp),
                        "trigger": trigger_label,
                        "time": t_clean
                    })
                theme_count = len(_DAILY_THEME_BREAKOUTS[theme_name])

                new_breakouts.append({
                    "sym": sym,
                    "ltp": float(ltp),
                    "trigger": trigger_label,
                    "is_strict": bool(m.get("is_strict") or ("STRICT" in signal)),
                    "is_spring_reversal": is_spring_rev,
                    "is_pyramid": is_pyramid,
                    "holding_info": holding_info,
                    "prev_range_ratio": d.get("prev_range_ratio"),
                    "is_inside_day": bool(d.get("is_inside_day")),
                    "day_high": day_high_raw,
                    "day_low": float(day_low) if day_low else None,
                    "risk_pct": risk_pct,
                    "lod_dist": lod_dist,
                    "stretch_pct": stretch_pct,
                    "is_gap_up": is_gap_up,
                    "gap_pct": gap_pct,
                    "theme": theme_name,
                    "theme_icon": theme_icon,
                    "theme_count": theme_count
                })

    # Dispatch Pre-Breakout Coil Alerts if any
    if new_coils:
        coil_lines = [
            f"⚡ <b>JARVIS PRE-BREAKOUT COIL ALERT — {t_clean}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>Setups coiling within 0.6% of breakout anchor on narrow compression:</i>\n"
        ]
        coil_kb = []
        for c in new_coils[:3]:
            s_sym = c["sym"]
            s_ltp = c["ltp"]
            s_anc = c["anchor"]
            s_lvl = c["level"]
            s_dist = c["dist_pct"]
            tv_link = f"https://in.tradingview.com/chart/?symbol=NSE:{s_sym}"

            comp_tag = "Narrow Inside Day" if c.get("is_inside_day") else ("NR Coiling" if c.get("is_narrow") else "Tight Range")
            coil_lines.append(
                f"🎯 <a href='{tv_link}'><b>{s_sym}</b></a> (₹{s_ltp:,.2f})\n"
                f"• Proximity : 🟡 Coiling {s_dist:.2f}% below {s_anc} (₹{s_lvl:,.2f})\n"
                f"• Structure : 🧱 {comp_tag}\n"
                f"• Action : Ready for ignition breakout above ₹{s_lvl:,.2f}\n"
            )
            coil_kb.append([
                {"text": f"📊 View {s_sym} Chart", "url": f"https://sanincredible.github.io/Jarvis/?symbol={s_sym}"},
                {"text": f"📈 TV App", "url": f"https://in.tradingview.com/chart/?symbol=NSE:{s_sym}"}
            ])
            coil_kb.append([
                {"text": f"🎯 Buy {s_sym} (1k Risk)", "callback_data": f"buy_risk:{s_sym}:1k"},
                {"text": f"🎯 Buy {s_sym} (2k Risk)", "callback_data": f"buy_risk:{s_sym}:2k"}
            ])
        coil_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        coil_lines.append("📊 <a href='https://sanincredible.github.io/Jarvis/'>Open Live Dashboard</a>")
        coil_markup = {"inline_keyboard": coil_kb} if coil_kb else None
        send_telegram_alert_async("\n".join(coil_lines), reply_markup=coil_markup)

    # Check regime state to protect against discipline leak / FOMO in RED markets
    is_defensive = False
    regime_label = ""
    scode = "EXPANSION"
    for r_f in [
        "positional_market_regime.json",
        "market_regime.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "positional_market_regime.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_regime.json")
    ]:
        if os.path.isfile(r_f):
            try:
                with open(r_f, "r", encoding="utf-8") as rf:
                    rdata = json.load(rf)
                    scode = str(rdata.get("state_code") or rdata.get("regime_code") or "").upper()
                    alloc = rdata.get("swing_allocation_pct", 100)
                    if alloc == 0 or scode in ("DEFENSIVE", "DEFENSIVE_WATERFALL", "CLIMAX", "WASHOUT", "CHOP"):
                        is_defensive = True
                    regime_label = rdata.get("state_label") or rdata.get("regime_badge") or scode
                break
            except Exception:
                pass

    # Phase 1 Autonomous Shadow Execution Engine Trigger Hook (09:30 - 10:15 AM)
    # Evaluates all active qualifying breakout setups decoupled from Telegram alert deduplication!
    now_ist = get_ist_now()
    is_prime_shadow_window = (now_ist.weekday() < 5 and ((now_ist.hour == 9 and now_ist.minute >= 30) or (now_ist.hour == 10 and now_ist.minute <= 15)))
    if is_prime_shadow_window and active_breakout_setups:
        try:
            from shadow_execution_engine import evaluate_and_record_shadow_entry

            # Multi-factor priority tie-breaker for concurrent triggers:
            # Sort candidate setups by: (Soft Score DESC, RVOL DESC, Risk % ASC, Stretch % ASC)
            def get_setup_sort_key(item):
                s_sym, s_d, s_m, s_trig = item
                s_ltp = float(s_d.get("ltp") or 0.0)
                s_dl = float(s_m.get("day_low") or s_d.get("day_low") or (s_ltp * 0.985 if s_ltp > 0 else 0.0))
                risk_pct_v = round(((s_ltp - s_dl) / s_ltp) * 100, 2) if s_ltp > 0 else 99.0
                rvol_v = float(s_d.get("rvol") or s_m.get("rvol") or 0.0)
                stretch_v = float(s_d.get("stretch_pct") or 0.0)
                try:
                    from order_engine import evaluate_strategy_checklist
                    fq = {**s_d, **s_m, "ltp": s_ltp, "day_low": s_dl}
                    ck = evaluate_strategy_checklist(s_sym, quote_data=fq, calc_data={"ltp": s_ltp, "day_low": s_dl, "risk_pct": risk_pct_v})
                    score = int(ck.get("soft_score", 0)) if ck.get("hard_gates_passed") else -1
                except Exception:
                    score = 0
                return (score, rvol_v, -risk_pct_v, -stretch_v)

            sorted_setups = sorted(active_breakout_setups, key=get_setup_sort_key, reverse=True)
            now_epoch = time.time()
            for s_sym, s_d, s_m, s_trig in sorted_setups:
                # 1. Feed-Level Global Heartbeat Watchdog Check
                if ACTIVE_WS_FEED[0] is not None:
                    try:
                        f_stat = ACTIVE_WS_FEED[0].get_feed_status()
                        if f_stat.get("is_feed_stale"):
                            gap_s = f_stat.get("seconds_since_msg", 0.0)
                            print(f"⚠️ [Watchdog] Skipping entry for {s_sym}: Global WebSocket feed stale ({gap_s:.1f}s silence > 30s limit)")
                            try:
                                from shadow_execution_engine import record_rejected_signal
                                record_rejected_signal(s_sym, "FEED_STALE", f"Global WebSocket feed stale ({gap_s:.1f}s silence)", quote_data=s_d)
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass

                # 2. Per-Symbol Exchange Recency Watchdog Guard (30-second limit on exchange trade time)
                exch_tick_t = float(s_d.get("exchange_tick_time") or s_d.get("last_tick_time") or s_d.get("timestamp") or 0.0)
                if exch_tick_t > 0:
                    age_s = now_epoch - exch_tick_t
                    if age_s < -5.0:
                        print(f"⚠️ [Clock Skew] Exchange timestamp is {-age_s:.1f}s in future for {s_sym}! Check system clock sync.")
                    elif age_s > 30.0:
                        print(f"⚠️ [Watchdog] Skipping entry for {s_sym}: Symbol exchange tick stale ({age_s:.1f}s > 30s limit)")
                        try:
                            from shadow_execution_engine import record_rejected_signal
                            record_rejected_signal(s_sym, "FEED_STALE", f"Symbol exchange tick stale ({age_s:.1f}s old)", quote_data=s_d)
                        except Exception:
                            pass
                        continue

                s_ltp = float(s_d.get("ltp") or 0.0)
                s_dl = float(s_m.get("day_low") or s_d.get("day_low") or (s_ltp * 0.985 if s_ltp > 0 else 0.0))
                full_quote_data = {**s_d, **s_m, "ltp": s_ltp, "day_low": s_dl}
                evaluate_and_record_shadow_entry(
                    symbol=s_sym,
                    quote_data=full_quote_data,
                    trigger_price=s_ltp,
                    day_low=s_dl,
                    regime_code=scode if scode else ("DEFENSIVE" if is_defensive else "EXPANSION"),
                    trigger_name=s_trig or "ORB Breakout"
                )
        except Exception as shadow_err:
            print(f"Notice on Phase 1 shadow entry: {shadow_err}")

    if not new_breakouts:
        return

    # Upgrade 5: Event-Driven Real-Time Watchlist Breadth Circuit Breaker
    adv_cnt = 0
    dec_cnt = 0
    for _, d, _ in results:
        ltp_val = float(d.get("ltp") or 0.0)
        pc_val = float(d.get("prev_close") or 0.0)
        if ltp_val > 0 and pc_val > 0:
            if ltp_val > pc_val:
                adv_cnt += 1
            elif ltp_val < pc_val:
                dec_cnt += 1

    tot_tr = adv_cnt + dec_cnt
    b_ratio = (adv_cnt / tot_tr) if tot_tr > 0 else 1.0
    is_circuit_breaker = False
    if tot_tr >= 5 and b_ratio < 0.35:
        is_circuit_breaker = True
        is_defensive = True
        regime_label = f"BREADTH FLUSH ({adv_cnt}/{tot_tr} Adv)"

    # Build Streamlined Action Card (Optimized for iPhone 15 Pro Max: ~38-42 chars/line)
    if is_circuit_breaker:
        lines = [
            f"⚡ <b>JARVIS BREAKOUT ALERT — {t_clean}</b>",
            f"🚨 <b>CIRCUIT BREAKER: {regime_label}</b>",
            f"⚠️ <i>{dec_cnt}/{tot_tr} stocks declining. SCALPS ONLY!</i>",
            "━━━━━━━━━━━━━━━━━━━━━━"
        ]
    elif is_defensive:
        lines = [
            f"⚡ <b>JARVIS BREAKOUT ALERT — {t_clean}</b>",
            f"⛔ <b>DEFENSIVE REGIME ({regime_label})</b>",
            "⚠️ <i>80%+ breakouts fail. SCALPS ONLY!</i>",
            "━━━━━━━━━━━━━━━━━━━━━━"
        ]
    else:
        lines = [
            f"⚡ <b>JARVIS BREAKOUT ALERT — {t_clean}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━"
        ]

    # Check for active Theme Clusters (>= 3 breakouts in same sector)
    cluster_themes = set()
    for b in new_breakouts:
        if b.get("theme_count", 0) >= 3 and b.get("theme") and b.get("theme") != "General Equities":
            cluster_themes.add((b["theme"], b.get("theme_icon", "🏢"), b["theme_count"]))
    
    if cluster_themes:
        for ct_name, ct_icon, ct_count in sorted(cluster_themes):
            lines.append(f"🔥 <b>THEME CLUSTER: {ct_icon} {ct_name} ({ct_count}+ Breakouts)</b>")
            lines.append("<i>⚡ Institutional group sponsorship active! (>75% follow-through)</i>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    for i, b in enumerate(new_breakouts):
        if i > 0:
            lines.append("")  # Blank separation between stock cards

        sym = b["sym"]
        ltp = b["ltp"]
        day_low = b["day_low"]
        risk_pct = b["risk_pct"]
        lod_dist = b["lod_dist"]
        stretch_pct = b["stretch_pct"]

        is_strict_stock = b.get("is_strict")
        is_pyramid = b.get("is_pyramid")
        holding_info = b.get("holding_info") or {}

        # 1. Cockpit Header Badge & Direct Chart Link
        if is_pyramid and is_strict_stock:
            icon = "🔺💎"
            tag = "PYRAMID • STRICT"
        elif is_pyramid:
            icon = "🔺"
            tag = "PYRAMID ADD-ON"
        elif b.get("is_spring_reversal"):
            icon = "💎🔄"
            tag = "SPRING REVERSAL"
        elif is_strict_stock:
            icon = "💎"
            tag = "STRICT PLAYBOOK"
        elif lod_dist is not None and lod_dist > 100:
            icon = "⚠️"
            tag = "EXTENDED BO"
        else:
            icon = "🚀"
            tag = b["trigger"].replace(" Breakout", "").replace(" Break", "")

        tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
        lines.append(f"{icon} {tv_link} (₹{ltp:,.2f}) • <b>{tag}</b>")

        # 2. Pyramiding Active Position Summary (if applicable)
        if is_pyramid:
            h_qty = holding_info.get("qty", 0)
            h_entry = float(holding_info.get("entry_price") or 0.0)
            pnl_s = ""
            if h_entry > 0:
                p_pct = round(((ltp - h_entry) / h_entry) * 100.0, 1)
                pnl_s = f" ({p_pct:+.1f}%)"
            lines.append(f"├ 💼 Hold: <b>{h_qty} shs @ ₹{h_entry:,.0f}</b>{pnl_s}")

        # 3. Structure & Trigger Pills
        pr_ratio = b.get("prev_range_ratio")
        is_in = b.get("is_inside_day")
        nr_str = ""
        if pr_ratio is not None or is_in:
            if is_in and pr_ratio is not None:
                nr_str = f"NR {pr_ratio:.2f}x 📦"
            elif is_in:
                nr_str = "Inside Day 📦"
            else:
                nr_str = f"NR {pr_ratio:.2f}x"
                if pr_ratio <= 0.75:
                    nr_str += " 📦"

        gap_str = ""
        if b.get("is_gap_up") and b.get("gap_pct") is not None:
            sign = "+" if b["gap_pct"] > 0 else ""
            gap_str = f"Gap {sign}{b['gap_pct']}%"

        trig_short = b["trigger"].replace(" Breakout", "").replace(" Break", "").replace(" + ", "+")

        struct_parts = []
        if nr_str:
            struct_parts.append(f"📏 {nr_str}")
        if gap_str:
            struct_parts.append(f"🚀 {gap_str}")
        if trig_short:
            struct_parts.append(f"⚡ {trig_short}")
        if not struct_parts:
            struct_parts.append(f"⚡ {b['trigger']}")

        lines.append("├ " + " • ".join(struct_parts))

        # Sector Theme & Institutional Cluster Pill
        b_theme = b.get("theme")
        b_icon = b.get("theme_icon", "🏢")
        b_tcnt = b.get("theme_count", 1)
        if b_theme and b_theme != "General Equities":
            if b_tcnt >= 3:
                lines.append(f"├ {b_icon} <b>Theme:</b> {b_theme} • 🔥 <b>Cluster #{b_tcnt} (Sponsor)</b>")
            elif b_tcnt == 2:
                lines.append(f"├ {b_icon} <b>Theme:</b> {b_theme} • ⚡ <b>Dual Run #{b_tcnt}</b>")
            else:
                lines.append(f"├ {b_icon} <b>Theme:</b> {b_theme}")

        # Upper Wick Quality Check
        day_h_val = b.get("day_high")
        if day_h_val and day_low and day_h_val > day_low:
            u_wick = max(0.0, day_h_val - ltp)
            c_rng = day_h_val - day_low
            w_pct = (u_wick / c_rng) * 100.0 if c_rng > 0 else 0.0
            if w_pct > 40.0:
                lines.append(f"├ ⚠️ <b>Upper Wick: {w_pct:.0f}%</b> (Rejection risk! Wait for high reclaim)")

        # 4. Risk, LoD Distance & 10 EMA Pills
        risk_parts = []
        if day_low is not None:
            sl_val_s = f"₹{day_low:,.0f}" if (day_low % 1 == 0) else f"₹{day_low:,.2f}"
            r_pct_s = f"{risk_pct:.0f}%" if (risk_pct is not None and risk_pct % 1 == 0) else (f"{risk_pct:.1f}%" if risk_pct is not None else "")
            if r_pct_s:
                risk_parts.append(f"🛑 {sl_val_s} (-{r_pct_s})")
            else:
                risk_parts.append(f"🛑 {sl_val_s}")
        else:
            risk_parts.append("🛑 N/A")

        if lod_dist is not None:
            if lod_dist <= 70:
                risk_parts.append(f"🟢 LoD {lod_dist}%")
            elif lod_dist <= 100:
                risk_parts.append(f"⚪ LoD {lod_dist}%")
            else:
                risk_parts.append(f"⚠️ LoD {lod_dist}%")

        if stretch_pct is not None:
            sign = "+" if stretch_pct > 0 else ""
            str_val = f"{stretch_pct:.1f}%"
            if stretch_pct <= 0.6:
                risk_parts.append(f"🟢 10E {sign}{str_val}")
            elif stretch_pct <= 1.5:
                risk_parts.append(f"⚪ 10E {sign}{str_val}")
            else:
                risk_parts.append(f"⚠️ 10E {sign}{str_val}")

        lines.append("└ " + " • ".join(risk_parts))

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 <a href='https://sanincredible.github.io/Jarvis/'>Open 3m Terminal Dashboard</a>")

    # Interactive 1-Tap Buy Buttons for Triggered Breakouts (iPhone 2-Column Grid)
    kb_buttons = []
    if new_breakouts:
        for b in new_breakouts[:3]:
            sym = b["sym"]
            is_pyr = b.get("is_pyramid")
            kb_buttons.append([
                {"text": f"📊 View {sym} Chart", "url": f"https://sanincredible.github.io/Jarvis/?symbol={sym}"},
                {"text": f"📈 TV App", "url": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"}
            ])
            if is_pyr:
                kb_buttons.append([
                    {"text": f"🔺 Pyramid {sym} (Risk-Free)", "callback_data": f"buy_prep:{sym}:rf:lod:default"},
                    {"text": f"🔺 Pyramid {sym} (1k Risk)", "callback_data": f"buy_prep:{sym}:r1k:lod:default"}
                ])
            elif is_defensive:
                kb_buttons.append([
                    {"text": f"🛡️ Scalp {sym} (1k Risk)", "callback_data": f"buy_prep:{sym}:r1k:lod:default"},
                    {"text": f"🛡️ Scalp {sym} (500 Risk)", "callback_data": f"buy_prep:{sym}:r500:lod:default"}
                ])
            else:
                kb_buttons.append([
                    {"text": f"🎯 Buy {sym} (1k Risk)", "callback_data": f"buy_prep:{sym}:r1k:lod:default"},
                    {"text": f"🎯 Buy {sym} (2k Risk)", "callback_data": f"buy_prep:{sym}:r2k:lod:default"}
                ])
                kb_buttons.append([
                    {"text": f"🛒 Buy {sym} (1.0L)", "callback_data": f"buy_prep:{sym}:1.0L:lod:default"},
                    {"text": f"🛒 Buy {sym} (50k)", "callback_data": f"buy_prep:{sym}:50k:lod:default"}
                ])
    reply_markup = {"inline_keyboard": kb_buttons} if kb_buttons else None

    full_msg = "\n".join(lines)
    send_telegram_alert_async(full_msg, reply_markup=reply_markup)


def get_instrument_key(symbol):
    """Resolves instrument key for Upstox API queries (stocks & indices)."""
    sym_u = symbol.strip().upper()
    sym_u = SYMBOL_ALIASES.get(sym_u, sym_u)
    if sym_u in INDEX_MAPPING:
        return INDEX_MAPPING[sym_u]
    isin = SYMBOL_TO_ISIN.get(sym_u)
    if not isin:
        isin = resolve_isin_dynamic(sym_u)
        if isin:
            SYMBOL_TO_ISIN[sym_u] = isin
    if isin:
        return f"NSE_EQ|{isin}"
    return f"NSE_EQ|{sym_u}"


def aggregate_1m_to_3m(candles_1m, target_date=None):
    """
    Aggregates Upstox 1-minute index candles into 3-minute ORB candles.
    Strictly filters candles for target_date (default: today IST) to prevent
    residual yesterday candles from contaminating morning 09:15-09:18 Bar 1 anchor calculation.
    """
    if target_date is None:
        target_date = get_ist_now().strftime("%Y-%m-%d")
    buckets = {}
    candles_1m_sorted = sorted(candles_1m, key=lambda c: str(c[0]))
    for c in candles_1m_sorted:
        ts = str(c[0])
        if target_date and not ts.startswith(target_date):
            continue
        try:
            dt = datetime.fromisoformat(ts)
            b_min = (dt.minute // 3) * 3
            b_dt = dt.replace(minute=b_min, second=0, microsecond=0)
            b_key = b_dt.isoformat()
            if b_key not in buckets:
                buckets[b_key] = [
                    b_key,
                    float(c[1]),  # open
                    float(c[2]),  # high
                    float(c[3]),  # low
                    float(c[4]),  # close
                    int(c[5]) if len(c) > 5 else 0  # volume
                ]
            else:
                b = buckets[b_key]
                b[2] = max(b[2], float(c[2]))  # high
                b[3] = min(b[3], float(c[3]))  # low
                b[4] = float(c[4])            # close (latest in interval)
                b[5] += int(c[5]) if len(c) > 5 else 0
        except Exception:
            continue
    return [buckets[k] for k in sorted(buckets.keys())]


DAILY_HIST_CACHE = {}  # (symbol, date_str) -> cached daily metrics (PDH, 50MA, ATR14, pivots)


def fetch_upstox_bulk_quotes(symbols, token):
    """
    Fetches live quotes for multiple symbols in a SINGLE batch HTTP call to Upstox API v2.
    Reduces latency from ~15s to ~150ms.
    """
    if not symbols or not token:
        return {}

    clean_syms = [SYMBOL_ALIASES.get(s.strip().upper(), s.strip().upper()) for s in symbols]
    key_map = {}
    inst_keys = []
    for s in clean_syms:
        k = get_instrument_key(s)
        inst_keys.append(k)
        key_map[k] = s
        key_map[k.replace("|", ":")] = s
        key_map[s] = s

    encoded_keys = urllib.parse.quote(",".join(inst_keys))
    url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded_keys}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    quotes = {}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            q_data = data.get("data", {})
            for k, v in q_data.items():
                matched_s = key_map.get(k) or key_map.get(k.replace(":", "|"))
                if not matched_s and ":" in k:
                    raw_s = k.split(":")[1]
                    matched_s = key_map.get(raw_s, raw_s)
                if matched_s:
                    quotes[matched_s.upper()] = v
    except Exception:
        pass
    return quotes


def fetch_upstox_symbol_data(symbol, token, prefetched_quote=None):
    """Fetches live market data and 3m candles from Upstox API v2 using bulk quote and daily cache."""
    symbol = SYMBOL_ALIASES.get(symbol.strip().upper(), symbol.strip().upper())
    inst_key = get_instrument_key(symbol)
    encoded_key = urllib.parse.quote(inst_key)
    is_index = inst_key.startswith("NSE_INDEX|")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    ltp = None
    prev_close = None
    day_open = None
    day_low = None
    day_high = None
    gap_pct = None
    is_gap_up = False
    pdh = None
    pdl = None
    prev_range = 0.0
    prev_range_ratio = None
    is_inside_day = False
    is_narrow_prev_day = False
    pivot_point = None
    pivot_r1 = None
    pivot_r2 = None
    rvol = None
    is_strong_start = False
    anchor_high = None
    anchor_low = None
    high_bar_num = None
    low_bar_num = None
    sma50 = None
    atr14 = None
    parsed_candles = []
    parsed_daily_candles = []

    try:
        # 1. Market Quote (Use prefetched bulk quote or query individual)
        d_quote = prefetched_quote
        if not d_quote:
            quote_url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded_key}"
            req_q = urllib.request.Request(quote_url, headers=headers)
            with urllib.request.urlopen(req_q, timeout=4) as resp:
                q_json = json.loads(resp.read().decode('utf-8'))
                q_data = q_json.get("data", {})
                key_in_data = inst_key.replace("|", ":")
                d_quote = q_data.get(key_in_data) or (list(q_data.values())[0] if q_data else {})

        if d_quote:
            ltp = float(d_quote.get("last_price", 0))
            ohlc = d_quote.get("ohlc", {})
            prev_close = float(ohlc.get("close", 0))
            day_open = float(ohlc.get("open", 0))
            day_low = float(ohlc.get("low", 0))
            day_high = float(ohlc.get("high", 0))

            # Pine Script: isStrongStart(o, l, pc) => o > pc and l >= pc * 0.995
            if day_open > prev_close and day_low >= (prev_close * 0.995):
                is_strong_start = True

        # 2. Intraday 3-Minute Candles (Pine Script f_orb() logic)
        # Use modern Upstox v3 historical candle route (with v2 fallback) and aggregate 1m to 3m
            raw_candles = []
            for c_url in [
                f"https://api.upstox.com/v3/historical-candle/intraday/{encoded_key}/minutes/1",
                f"https://api.upstox.com/v2/historical-candle/intraday/{encoded_key}/1minute"
            ]:
                try:
                    req_c = urllib.request.Request(c_url, headers=headers)
                    with urllib.request.urlopen(req_c, timeout=4) as resp:
                        c_json = json.loads(resp.read().decode('utf-8'))
                        raw_candles = c_json.get("data", {}).get("candles", [])
                        if raw_candles:
                            break
                except Exception:
                    continue

            if raw_candles:
                candles_3m = aggregate_1m_to_3m(raw_candles)

                highs_3m = [float(c[2]) for c in candles_3m]
                lows_3m = [float(c[3]) for c in candles_3m]
                if (day_low is None or day_low == 0) and lows_3m:
                    day_low = min(lows_3m)
                if (day_high is None or day_high == 0) and highs_3m:
                    day_high = max(highs_3m)

                parsed_candles = []
                for c in candles_3m:
                    ts_s = str(c[0])
                    t_lbl = ts_s[11:16] if len(ts_s) >= 16 else ts_s
                    parsed_candles.append({
                        "t": t_lbl,
                        "o": round(float(c[1]), 2),
                        "h": round(float(c[2]), 2),
                        "l": round(float(c[3]), 2),
                        "c": round(float(c[4]), 2),
                        "v": int(c[5]) if len(c) > 5 else 0
                    })

                if highs_3m and lows_3m:
                    anchor_high = highs_3m[0]  # Bar 1 (09:15 - 09:18 AM)
                    anchor_low = lows_3m[0]   # Bar 1 (09:15 - 09:18 AM)
                    high_bar_num = 1
                    low_bar_num = 1
                    high_locked = False
                    low_locked = False

                    for i in range(1, len(highs_3m)):
                        bar_idx = i + 1

                        # High anchor logic
                        if not high_locked:
                            if highs_3m[i] > anchor_high:
                                anchor_high = highs_3m[i]
                                high_bar_num = bar_idx
                            elif highs_3m[i] < highs_3m[i - 1]:
                                high_locked = True

                        # Low anchor logic
                        if not low_locked:
                            if lows_3m[i] < anchor_low:
                                anchor_low = lows_3m[i]
                                low_bar_num = bar_idx
                            elif lows_3m[i] > lows_3m[i - 1]:
                                low_locked = True

        # 3. Daily Candles (PDH, 20-Day RVOL, 50MA, ATR14, Daily Swing Chart)
        today_str = get_ist_now().strftime("%Y-%m-%d")
        from_str = (get_ist_now() - timedelta(days=90)).strftime("%Y-%m-%d")
        daily_url = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/day/{today_str}/{from_str}"
        req_d = urllib.request.Request(daily_url, headers=headers)
        with urllib.request.urlopen(req_d, timeout=4) as resp:
            d_json = json.loads(resp.read().decode('utf-8'))
            daily_raw = d_json.get("data", {}).get("candles", [])
            if daily_raw:
                # Check whether daily_raw[0] is today's candle or yesterday's candle
                first_candle_date = str(daily_raw[0][0])[:10]
                today_iso = get_ist_now().strftime("%Y-%m-%d")

                if first_candle_date == today_iso and len(daily_raw) >= 2:
                    yesterday_candle = daily_raw[1]
                    day_before_candle = daily_raw[2] if len(daily_raw) >= 3 else None
                else:
                    yesterday_candle = daily_raw[0]
                    day_before_candle = daily_raw[1] if len(daily_raw) >= 2 else None

                pdh = float(yesterday_candle[2])  # high[1] = high of yesterday
                pdl = float(yesterday_candle[3])  # low[1] = low of yesterday
                yh = pdh
                yl = pdl
                yc = float(yesterday_candle[4])
                prev_range = max(0.0, yh - yl)
                prev_range_pct = round((prev_range / yc) * 100.0, 2) if yc > 0 else 0.0

                is_inside_day = False
                if day_before_candle:
                    try:
                        dbh = float(day_before_candle[2])
                        dbl = float(day_before_candle[3])
                        is_inside_day = bool(yh <= dbh and yl >= dbl)
                    except Exception:
                        pass

                try:
                    prev_close = float(yesterday_candle[4])  # close[1] = close of yesterday
                    if day_open and day_low:
                        is_strong_start = (day_open > prev_close and day_low >= (prev_close * 0.995))
                except Exception:
                    pass

                if (day_open is None or day_open == 0) and parsed_candles:
                    day_open = parsed_candles[0].get("o")
                if day_open and prev_close and prev_close > 0:
                    gap_pct = round(((float(day_open) - float(prev_close)) / float(prev_close)) * 100.0, 2)
                    is_gap_up = bool(gap_pct >= 1.0 or (pdh and float(day_open) > float(pdh) * 1.002))

                # Classic Floor Pivot Points: P = (H + L + C) / 3, R1 = 2*P - L, R2 = P + (H - L)
                try:
                    pivot_point = round((yh + yl + yc) / 3.0, 2)
                    pivot_r1 = round(2.0 * pivot_point - yl, 2)
                    pivot_r2 = round(pivot_point + (yh - yl), 2)
                except Exception:
                    pivot_point = None
                    pivot_r1 = None
                    pivot_r2 = None

                vols = [float(c[5]) for c in daily_raw]
                closes = [float(c[4]) for c in daily_raw]
                highs = [float(c[2]) for c in daily_raw]
                lows = [float(c[3]) for c in daily_raw]

                # Parse daily candles chronologically for D timeframe chart
                daily_sorted = sorted(daily_raw, key=lambda c: str(c[0]))
                parsed_daily_candles = []
                for c in daily_sorted:
                    ts_s = str(c[0])
                    try:
                        d_lbl = datetime.fromisoformat(ts_s).strftime("%d %b")
                    except Exception:
                        d_lbl = ts_s[5:10]
                    parsed_daily_candles.append({
                        "t": d_lbl,
                        "o": round(float(c[1]), 2),
                        "h": round(float(c[2]), 2),
                        "l": round(float(c[3]), 2),
                        "c": round(float(c[4]), 2),
                        "v": int(c[5]) if len(c) > 5 else 0
                    })

                # If today's candle is not yet in historical daily candles, synthesize and append today's live daily bar!
                if first_candle_date != today_iso and (parsed_candles or ltp is not None):
                    t_lbl = get_ist_now().strftime("%d %b")
                    t_open = parsed_candles[0]["o"] if parsed_candles else (day_open or ltp)
                    p_highs = [c["h"] for c in parsed_candles]
                    if ohlc.get("high"):
                        p_highs.append(float(ohlc.get("high")))
                    if ltp is not None:
                        p_highs.append(float(ltp))
                    t_high = max(p_highs) if p_highs else ltp

                    p_lows = [c["l"] for c in parsed_candles]
                    if ohlc.get("low"):
                        p_lows.append(float(ohlc.get("low")))
                    if ltp is not None:
                        p_lows.append(float(ltp))
                    t_low = min(p_lows) if p_lows else ltp

                    t_close = ltp
                    t_vol = sum(c.get("v", 0) for c in parsed_candles) or int(d_quote.get("volume", 0) or 0)
                    parsed_daily_candles.append({
                        "t": t_lbl,
                        "o": round(float(t_open), 2),
                        "h": round(float(t_high), 2),
                        "l": round(float(t_low), 2),
                        "c": round(float(t_close), 2),
                        "v": int(t_vol)
                    })

                # Pine Script Parity: Compute Time-of-Day Adjusted RVOL to eliminate the 09:30 AM volume distortion
                if len(vols) >= 21:
                    avg_v = sum(vols[1:21]) / 20.0
                    if avg_v > 0:
                        raw_rvol = vols[0] / avg_v
                        # Continuous Time-of-Day expected volume fraction F(m) starting at 0.0 at 09:15 AM
                        now_dt = get_ist_now()
                        session_mins = max(1, min(375, (now_dt.hour * 60 + now_dt.minute) - (9 * 60 + 15)))
                        expected_pct = calculate_tod_volume_fraction(session_mins)
                        expected_vol = avg_v * expected_pct
                        rvol_tod = round(vols[0] / expected_vol, 2) if expected_vol > 0 else raw_rvol
                        # Time-of-day normalized relative volume
                        rvol = round(rvol_tod, 2)

                if len(closes) >= 50:
                    sma50 = sum(closes[:50]) / 50.0

                if len(closes) >= 15:
                    trs = []
                    for idx in range(14):
                        tr = max(
                            highs[idx] - lows[idx],
                            abs(highs[idx] - closes[idx + 1]),
                            abs(lows[idx] - closes[idx + 1])
                        )
                        trs.append(tr)
                    atr14 = sum(trs) / 14.0

                if atr14 and atr14 > 0:
                    prev_range_ratio = round(prev_range / atr14, 2)
                    is_nr = bool(prev_range_ratio <= 0.75)
                else:
                    is_nr = bool(prev_range_pct <= 2.5)
                is_narrow_prev_day = bool(is_nr or is_inside_day)

    except Exception:
        return None

    if ltp is None or prev_close is None:
        return None

    return {
        "symbol": symbol,
        "ltp": ltp,
        "prev_close": prev_close,
        "day_open": day_open,
        "day_low": day_low,
        "day_high": day_high if day_high else (max(highs_3m) if highs_3m else ltp),
        "gap_pct": gap_pct,
        "is_gap_up": is_gap_up,
        "pdh": pdh,
        "pdl": pdl,
        "prev_range": prev_range,
        "prev_range_ratio": prev_range_ratio,
        "is_inside_day": is_inside_day,
        "is_narrow_prev_day": is_narrow_prev_day,
        "pivot": pivot_point,
        "r1": pivot_r1,
        "r2": pivot_r2,
        "rvol": rvol,
        "is_strong_start": is_strong_start,
        "orb_high": anchor_high,
        "orb_low": anchor_low,
        "high_bar_num": high_bar_num,
        "low_bar_num": low_bar_num,
        "sma50": sma50,
        "atr14": atr14,
        "candles": parsed_candles,
        "candles_3m": parsed_candles,
        "candles_d": parsed_daily_candles,
        "source": "UPSTOX"
    }


def fetch_fallback_data(symbol):
    """Fallback to Yahoo Finance if Upstox token is expired or offline."""
    clean_sym = symbol.strip().upper()
    if clean_sym in ("NIFTY", "NIFTY 50", "NIFTY50", "CNXNIFTY"):
        ticker = "^NSEI"
    elif clean_sym in ("BANKNIFTY", "NIFTYBANK"):
        ticker = "^NSEBANK"
    elif not clean_sym.endswith(".NS") and not clean_sym.endswith(".BO"):
        ticker = clean_sym + ".NS"
    else:
        ticker = clean_sym

    headers = {"User-Agent": "Mozilla/5.0"}
    ltp = None
    prev_close = None
    day_open = None
    day_low = None
    gap_pct = None
    is_gap_up = False
    pdh = None
    pdl = None
    prev_range = 0.0
    prev_range_ratio = None
    is_inside_day = False
    is_narrow_prev_day = False
    rvol = None
    is_strong_start = False
    anchor_high = None
    anchor_low = None
    high_bar_num = None
    low_bar_num = None
    sma50 = None
    atr14 = None
    parsed_candles = []
    parsed_daily_candles = []

    try:
        url_daily = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo"
        req = urllib.request.Request(url_daily, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))['chart']['result'][0]
            meta = data['meta']
            quote = data['indicators']['quote'][0]
            ltp = meta.get('regularMarketPrice')
            prev_close = meta.get('chartPreviousClose')
            highs = [h for h in quote.get('high', []) if h is not None]
            lows = [l for l in quote.get('low', []) if l is not None]
            closes = [c for c in quote.get('close', []) if c is not None]
            vols = [v for v in quote.get('volume', []) if v is not None]
            opens = [o for o in quote.get('open', []) if o is not None]

            # Daily Candles for D Timeframe Chart
            ts_daily = data.get('timestamp', [])
            opens_d = quote.get('open', [])
            highs_d = quote.get('high', [])
            lows_d = quote.get('low', [])
            closes_d = quote.get('close', [])
            vols_d = quote.get('volume', [])

            for i in range(len(ts_daily)):
                od = opens_d[i] if i < len(opens_d) else None
                hd = highs_d[i] if i < len(highs_d) else None
                ld = lows_d[i] if i < len(lows_d) else None
                cd = closes_d[i] if i < len(closes_d) else None
                vd = vols_d[i] if i < len(vols_d) else 0
                if None not in (od, hd, ld, cd):
                    d_str = datetime.fromtimestamp(ts_daily[i], tz=timezone.utc).strftime('%d %b')
                    parsed_daily_candles.append({
                        "t": d_str,
                        "o": round(float(od), 2),
                        "h": round(float(hd), 2),
                        "l": round(float(ld), 2),
                        "c": round(float(cd), 2),
                        "v": int(vd or 0)
                    })

            # If today's bar is missing or has None values during live market hours, synthesize and append today's bar
            today_lbl = get_ist_now().strftime("%d %b")
            has_today = any(c.get("t") == today_lbl for c in parsed_daily_candles)
            if not has_today and ltp is not None and parsed_candles:
                t_open = parsed_candles[0]["o"] if parsed_candles else (opens[-1] if opens else ltp)
                p_highs = [c["h"] for c in parsed_candles]
                if ltp is not None:
                    p_highs.append(float(ltp))
                t_high = max(p_highs) if p_highs else ltp

                p_lows = [c["l"] for c in parsed_candles]
                if ltp is not None:
                    p_lows.append(float(ltp))
                t_low = min(p_lows) if p_lows else ltp

                t_close = ltp
                t_vol = sum(c.get("v", 0) for c in parsed_candles) or (vols[-1] if vols else 0)
                parsed_daily_candles.append({
                    "t": today_lbl,
                    "o": round(float(t_open), 2),
                    "h": round(float(t_high), 2),
                    "l": round(float(t_low), 2),
                    "c": round(float(t_close), 2),
                    "v": int(t_vol)
                })

            if len(highs) >= 2:
                pdh = highs[-2]
                pdl = lows[-2]
                yh = pdh
                yl = pdl
                yc = closes[-2]
                prev_range = max(0.0, yh - yl)
                prev_range_pct = round((prev_range / yc) * 100.0, 2) if yc > 0 else 0.0

            if len(highs) >= 3:
                dbh = highs[-3]
                dbl = lows[-3]
                is_inside_day = bool(yh <= dbh and yl >= dbl)

            if opens and lows and prev_close:
                day_open = opens[-1]
                day_low = lows[-1]
                if opens[-1] > prev_close and lows[-1] >= (prev_close * 0.995):
                    is_strong_start = True
                gap_pct = round(((float(day_open) - float(prev_close)) / float(prev_close)) * 100.0, 2)
                is_gap_up = bool(gap_pct >= 1.0 or (pdh and float(day_open) > float(pdh) * 1.002))

            if len(vols) >= 21:
                avg_vol = sum(vols[-21:-1]) / 20.0
                if avg_vol > 0:
                    raw_rvol = vols[-1] / avg_vol
                    now_dt = get_ist_now()
                    session_mins = max(1, min(375, (now_dt.hour * 60 + now_dt.minute) - (9 * 60 + 15)))
                    expected_pct = calculate_tod_volume_fraction(session_mins)
                    expected_vol = avg_vol * expected_pct
                    rvol_tod = round(vols[-1] / expected_vol, 2) if expected_vol > 0 else raw_rvol
                    rvol = round(rvol_tod, 2)

            if len(closes) >= 50:
                sma50 = sum(closes[-50:]) / 50.0

            if len(closes) >= 15:
                trs = []
                for i in range(len(closes) - 14, len(closes)):
                    tr = max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1])
                    )
                    trs.append(tr)
                atr14 = sum(trs) / 14.0

            if atr14 and atr14 > 0:
                prev_range_ratio = round(prev_range / atr14, 2)
                is_nr = bool(prev_range_ratio <= 0.75)
            else:
                is_nr = bool(prev_range_pct <= 2.5)
            is_narrow_prev_day = bool(is_nr or is_inside_day)

        url_1m = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        req_1m = urllib.request.Request(url_1m, headers=headers)
        with urllib.request.urlopen(req_1m, timeout=5) as resp:
            data_1m = json.loads(resp.read().decode('utf-8'))['chart']['result'][0]
            q1m = data_1m['indicators']['quote'][0]
            ts_list = data_1m.get('timestamp', [])
            opens_1m = q1m.get('open', [])
            highs_1m = q1m.get('high', [])
            lows_1m = q1m.get('low', [])
            closes_1m = q1m.get('close', [])
            vols_1m = q1m.get('volume', [])

            valid_bars = []
            for i in range(len(ts_list)):
                o = opens_1m[i] if i < len(opens_1m) else None
                h = highs_1m[i] if i < len(highs_1m) else None
                l = lows_1m[i] if i < len(lows_1m) else None
                c = closes_1m[i] if i < len(closes_1m) else None
                v = vols_1m[i] if i < len(vols_1m) else 0
                if o is not None and h is not None and l is not None and c is not None:
                    valid_bars.append((ts_list[i], o, h, l, c, v or 0))

            parsed_candles = []
            for i in range(0, len(valid_bars), 3):
                chunk = valid_bars[i:i + 3]
                ts_first = chunk[0][0]
                t_str = datetime.fromtimestamp(ts_first + 19800, tz=timezone.utc).strftime('%H:%M')
                o_val = round(float(chunk[0][1]), 2)
                h_val = round(max(b[2] for b in chunk), 2)
                l_val = round(min(b[3] for b in chunk), 2)
                c_val = round(float(chunk[-1][4]), 2)
                v_val = sum(b[5] for b in chunk)
                parsed_candles.append({
                    "t": t_str,
                    "o": o_val,
                    "h": h_val,
                    "l": l_val,
                    "c": c_val,
                    "v": int(v_val)
                })

            if parsed_candles:
                h_3m = [c["h"] for c in parsed_candles]
                l_3m = [c["l"] for c in parsed_candles]
                anchor_high = h_3m[0]
                anchor_low = l_3m[0]
                high_bar_num = 1
                low_bar_num = 1
                high_locked = False
                low_locked = False

                for i in range(1, len(h_3m)):
                    bar_idx = i + 1

                    # High anchor logic
                    if not high_locked:
                        if h_3m[i] > anchor_high:
                            anchor_high = h_3m[i]
                            high_bar_num = bar_idx
                        elif h_3m[i] < h_3m[i - 1]:
                            high_locked = True

                    # Low anchor logic
                    if not low_locked:
                        if l_3m[i] < anchor_low:
                            anchor_low = l_3m[i]
                            low_bar_num = bar_idx
                        elif l_3m[i] > l_3m[i - 1]:
                            low_locked = True

    except Exception:
        pass

    day_low = min(l_3m) if (parsed_candles and l_3m) else (anchor_low if anchor_low else None)
    day_high = max(h_3m) if (parsed_candles and h_3m) else (anchor_high if anchor_high else ltp)

    if (day_open is None or day_open == 0) and parsed_candles:
        day_open = parsed_candles[0].get("o")
        if day_open and prev_close and prev_close > 0:
            gap_pct = round(((float(day_open) - float(prev_close)) / float(prev_close)) * 100.0, 2)
            is_gap_up = bool(gap_pct >= 1.0 or (pdh and float(day_open) > float(pdh) * 1.002))

    return {
        "symbol": symbol,
        "ltp": ltp,
        "prev_close": prev_close,
        "day_open": day_open,
        "day_low": day_low,
        "day_high": day_high,
        "gap_pct": gap_pct,
        "is_gap_up": is_gap_up,
        "pdh": pdh,
        "pdl": pdl,
        "prev_range": prev_range,
        "prev_range_ratio": prev_range_ratio,
        "is_inside_day": is_inside_day,
        "is_narrow_prev_day": is_narrow_prev_day,
        "rvol": rvol,
        "is_strong_start": is_strong_start,
        "orb_high": anchor_high,
        "orb_low": anchor_low,
        "high_bar_num": high_bar_num,
        "low_bar_num": low_bar_num,
        "sma50": sma50,
        "atr14": atr14,
        "candles": parsed_candles,
        "candles_3m": parsed_candles,
        "candles_d": parsed_daily_candles,
        "source": "FALLBACK"
    }


def compute_metrics(d):
    """Calculates all Pine Script metrics from raw data."""
    ltp = d["ltp"]
    pc = d["prev_close"]
    orb_h = d["orb_high"]
    orb_l = d["orb_low"]
    pdh = d["pdh"]
    sma50 = d.get("sma50")
    atr14 = d.get("atr14")

    # 1. Chg %
    if ltp and pc:
        chg_pct = (ltp - pc) / pc * 100.0
    else:
        chg_pct = 0.0

    # Gap-Up Detection
    gap_pct = d.get("gap_pct")
    is_gap_up = bool(d.get("is_gap_up", False))
    day_open = d.get("day_open")
    if gap_pct is None and day_open and pc and pc > 0:
        gap_pct = round(((float(day_open) - float(pc)) / float(pc)) * 100.0, 2)
        is_gap_up = bool(gap_pct >= 1.0 or (pdh and float(day_open) > float(pdh) * 1.002))

    # 2. PDH Breakout (● Green if c > pdh, Red if c <= pdh)
    pdh_broken = bool(pdh and ltp > pdh)

    # 3. H% and L% (Pine Script lines 252-253)
    # swingHPct: % of close vs swing high: negative below, positive if broken above
    if orb_h and orb_h > 0:
        h_pct = 100.0 * (ltp - orb_h) / orb_h
    else:
        h_pct = None

    # swingLPct: % of close vs swing low: negative if broken below, positive above
    if orb_l and orb_l > 0:
        l_pct = 100.0 * (ltp - orb_l) / orb_l
    else:
        l_pct = None

    # 4. ORB Status (Pine Script line 247: c > wAH ? "H" : c < wAL ? "L" : "M")
    if orb_h and ltp > orb_h:
        orb_status = "H"
        orb_color = GREEN
    elif orb_l and ltp < orb_l:
        orb_status = "L"
        orb_color = RED
    else:
        orb_status = "M"
        orb_color = ORANGE

    # 5. ATR% Multiple of 50MA (Pine Script lines 83-88)
    atr_mult = None
    is_breach = False
    if sma50 and atr14 and ltp and sma50 > 0 and ltp > 0:
        atr_pct = (atr14 / ltp) * 100.0
        gain_50 = ((ltp - sma50) / sma50) * 100.0
        if atr_pct > 0:
            atr_mult = gain_50 / atr_pct
            is_breach = abs(atr_mult) >= 5.0

    # 6. Bar Tag: H{high_bar} L{low_bar} (Pine Script line 134)
    hb = d.get("high_bar_num")
    lb = d.get("low_bar_num")
    if hb and lb:
        tag = f"H{hb} L{lb}"
    elif hb:
        tag = f"H{hb}"
    elif lb:
        tag = f"L{lb}"
    else:
        tag = "--"

    # 6.5 Reversal Pattern Detection (Broke ORB Low first, now breaking ORB High)
    candles_3m = d.get("candles_3m") or d.get("candles") or []
    is_reversal = False
    reversal_type = None
    orb_low_break_time = None
    orb_high_break_time = None
    reversal_desc = None

    if orb_h and orb_l and candles_3m and orb_status == "H":
        # Check if any 3m bar had broken below ORB low earlier in the session
        low_break_idx = None
        for idx, c in enumerate(candles_3m):
            c_l = c.get("l") if isinstance(c, dict) else (float(c[3]) if len(c) > 3 else None)
            c_t = c.get("t") if isinstance(c, dict) else (str(c[0]) if len(c) > 0 else "")
            if c_l is not None and c_l < orb_l:
                low_break_idx = idx
                orb_low_break_time = c_t
                break

        if low_break_idx is not None:
            # Check when subsequent breakout above ORB high occurred
            for c in candles_3m[low_break_idx:]:
                c_h = c.get("h") if isinstance(c, dict) else (float(c[2]) if len(c) > 2 else None)
                c_t = c.get("t") if isinstance(c, dict) else (str(c[0]) if len(c) > 0 else "")
                if c_h is not None and c_h > orb_h:
                    orb_high_break_time = c_t
                    break

            is_reversal = True
            reversal_type = "L_TO_H"
            reversal_desc = f"Broke ORB Low ({orb_low_break_time or 'Early'}) → Broke ORB High ({orb_high_break_time or 'Late'})"

    # 7. Action Signal & Strict Setup Assessment
    is_narrow = bool(d.get("is_narrow_prev_day", False))
    is_ss = bool(d.get("is_strong_start", False))
    is_strict = bool(is_narrow and is_ss and pdh_broken and orb_status == "H")

    signal = "IN RANGE"
    sig_color = RESET
    if is_strict:
        if is_reversal:
            signal = "💎 STRICT: NR + REVERSAL BREAKOUT (ORB + PDH)"
            sig_color = f"{YELLOW}{BOLD}"
        else:
            signal = "💎 STRICT: NARROW + STRONG START + PDH BREAKOUT"
            sig_color = f"{YELLOW}{BOLD}"
    elif is_reversal:
        if d.get("is_strong_start") and pdh_broken:
            signal = "★ SS + REVERSAL BREAKOUT (ORB + PDH)"
            sig_color = f"{MAGENTA}{BOLD}"
        elif d.get("is_strong_start"):
            signal = "★ SS + REVERSAL (ORB LOW → HIGH)"
            sig_color = f"{MAGENTA}{BOLD}"
        elif pdh_broken:
            signal = "🔄 REVERSAL BREAKOUT (ORB + PDH)"
            sig_color = f"{MAGENTA}{BOLD}"
        else:
            signal = "🔄 REVERSAL (ORB LOW → HIGH)"
            sig_color = f"{MAGENTA}{BOLD}"
    elif d["is_strong_start"] and orb_status == "H" and pdh_broken:
        signal = "★ STRONG START + ORB + PDH BREAKOUT"
        sig_color = f"{GREEN}{BOLD}"
    elif d["is_strong_start"] and orb_status == "H":
        signal = "★ STRONG START + ORB BREAKOUT"
        sig_color = f"{GREEN}{BOLD}"
    elif orb_status == "H" and pdh_broken:
        signal = "BULLISH BREAKOUT (ORB + PDH)"
        sig_color = GREEN
    elif orb_status == "H":
        signal = "ABOVE ORB HIGH"
    # 8. Intraday 10 EMA & Overextension (% Stretch)
    ema10 = None
    if candles_3m:
        alpha = 2.0 / (10.0 + 1.0)
        # Seed EMA with day_open baseline to stabilize early morning warmup uncoupled from overnight gaps
        seed_p = float(d.get("day_open") or (candles_3m[0].get("o") if isinstance(candles_3m[0], dict) else candles_3m[0][1]) or 0.0)
        if seed_p > 0:
            ema10 = seed_p
        for c in candles_3m:
            close = c.get("c") if isinstance(c, dict) else float(c[4])
            if ema10 is None:
                ema10 = close
            else:
                ema10 = (close * alpha) + (ema10 * (1.0 - alpha))
        if ema10 is not None:
            ema10 = round(ema10, 2)
    if not ema10 and d.get("pivot"):
        ema10 = round(float(d.get("pivot")), 2)

    stretch_pct = None
    if ema10 and ltp:
        stretch_pct = round(((float(ltp) - ema10) / ema10) * 100.0, 2)

    # 9. LoD Dist (ATR-Normalized Low of Day Distance: (LTP - Day Low) / ATR14 * 100%)
    day_low = d.get("day_low")
    if day_low is None or day_low == 0:
        c_3m = d.get("candles_3m") or []
        if c_3m:
            c_lows = [c.get("l") for c in c_3m if isinstance(c, dict) and c.get("l") is not None]
            if c_lows:
                day_low = min(c_lows)
        elif orb_l:
            day_low = orb_l

    lod_dist = None
    if atr14 and atr14 > 0 and day_low is not None and ltp is not None:
        lod_dist = round(((float(ltp) - float(day_low)) / float(atr14)) * 100.0)

    return {
        "chg_pct": chg_pct,
        "gap_pct": gap_pct,
        "is_gap_up": is_gap_up,
        "pdh_broken": pdh_broken,
        "h_pct": h_pct,
        "l_pct": l_pct,
        "orb_status": orb_status,
        "orb_color": orb_color,
        "tag": tag,
        "atr_mult": atr_mult,
        "is_breach": is_breach,
        "is_strict": is_strict,
        "is_reversal": is_reversal,
        "reversal_type": reversal_type,
        "orb_low_break_time": orb_low_break_time,
        "orb_high_break_time": orb_high_break_time,
        "reversal_desc": reversal_desc,
        "signal": signal,
        "sig_color": sig_color,
        "ema10": ema10,
        "stretch_pct": stretch_pct,
        "day_low": round(day_low, 2) if day_low else None,
        "lod_dist": lod_dist
    }


def compute_strength_score(d, m):
    """
    Computes institutional Strength Score for sorting in descending order:
    Tier 0 (Diamond Tier): 💎 STRICT (Narrow Prev Day + Strong Start + PDH Breakout + ORB High) -> Score: 1800 + H%*10 + Chg%
    Tier 1: ★ Strong Start + ORB Breakout + PDH Breakout (Score: 1500 + H%*10 + Chg%)
    Tier 1.5: 🔄 REVERSAL BREAKOUT (Score: 1400 if PDH else 1150 + H%*10 + Chg%)
    Tier 2: BULLISH BREAKOUT (ORB + PDH) (Score: 1300 + H%*10 + Chg%)
    Tier 3: ★ Strong Start + ORB Breakout (Score: 1200 + H%*10 + Chg%)
    Tier 4: ABOVE ORB HIGH (Score: 1000 + H%*10 + Chg%)
    Tier 5: IN RANGE (Score: 500 + H%*10 + Chg%)
    Tier 6: BELOW ORB LOW (Score: 100 if SS else 0 + H%*10 + Chg%)
    """
    orb_status = m.get("orb_status", "M")
    pdh_broken = m.get("pdh_broken", False)
    is_ss = d.get("is_strong_start", False)
    is_rev = m.get("is_reversal", False)
    is_strict = m.get("is_strict", False)
    h_pct = m.get("h_pct") or 0.0
    chg_pct = m.get("chg_pct") or 0.0

    if is_strict:
        tier = 1800.0
    elif is_ss and orb_status == "H" and pdh_broken:
        tier = 1500.0
    elif is_rev and pdh_broken:
        tier = 1400.0
    elif orb_status == "H" and pdh_broken:
        tier = 1300.0
    elif is_ss and orb_status == "H":
        tier = 1200.0
    elif is_rev:
        tier = 1150.0
    elif orb_status == "H":
        tier = 1000.0
    elif orb_status == "M":
        tier = 500.0
    else:  # 'L'
        tier = 100.0 if is_ss else 0.0

    score = tier + (h_pct * 10.0) + chg_pct
    return round(score, 2)


def get_active_watchlist():
    """Loads active watchlist strictly from watchlist.txt (user's manually curated watchlist)."""
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    candidates = ["watchlist.txt", os.path.join(script_dir, "watchlist.txt")]
    for w_path in candidates:
        if os.path.isfile(w_path):
            try:
                with open(w_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().replace("\r\n", "\n").replace("\r", "\n")
                    lines = [l.strip().upper().replace(",", " ") for l in content.split("\n") if l.strip() and not l.startswith("#")]
                    IGNORED_TOKENS = {"NSE", "BSE", "NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY", "CNX500"}
                    syms = []
                    for line in lines:
                        for s in line.split():
                            canonical = SYMBOL_ALIASES.get(s, s)
                            if canonical in IGNORED_TOKENS:
                                continue
                            syms.append(canonical)
                    if syms:
                        return list(dict.fromkeys(syms))
            except Exception:
                pass

    for cfg_f in [CONFIG_FILE, "credentials.json", os.path.join(script_dir, "config_credentials.json")]:
        if os.path.isfile(cfg_f):
            try:
                with open(cfg_f, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    syms = cfg.get("watchlist")
                    if syms and isinstance(syms, list):
                        IGNORED_TOKENS = {"NSE", "BSE", "NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY", "CNX500"}
                        return [SYMBOL_ALIASES.get(s.strip().upper(), s.strip().upper()) for s in syms if s.strip() and SYMBOL_ALIASES.get(s.strip().upper(), s.strip().upper()) not in IGNORED_TOKENS]
            except Exception:
                pass

    return WATCHLIST


def hot_resubscribe_websocket():
    """Instantly hot-subscribes active Upstox WebSocket feed to updated watchlist symbols."""
    try:
        feed = ACTIVE_WS_FEED[0]
        if feed and getattr(feed, "is_running", False):
            wl = get_active_watchlist()
            feed.update_symbols(wl)
            print(f"⚡ [WebSocket] Hot-resubscribe executed immediately for {len(wl)} instruments.")
            return True
    except Exception as e:
        print(f"⚠️ [WebSocket] Hot-resubscribe error: {e}")
    return False


def scan_watchlist():
    """Scans all symbols in watchlist and returns results sorted by strength descending."""
    try:
        sync_remote_files_from_github()
    except Exception:
        pass
    token = load_upstox_token()
    results = []
    active_syms = get_active_watchlist()
    if not active_syms:
        return []

    # 1. Instant Bulk Quotes in 1 single HTTP request (~150ms)
    bulk_quotes = {}
    if token:
        bulk_quotes = fetch_upstox_bulk_quotes(active_syms, token)

    # 2. Worker for concurrent symbol parsing
    def _fetch_symbol(sym):
        d = None
        if token:
            d = fetch_upstox_symbol_data(sym, token, prefetched_quote=bulk_quotes.get(sym.upper()))

        if not d or not d.get("ltp"):
            d = fetch_fallback_data(sym)

        if d and d.get("ltp") and d.get("prev_close"):
            m = compute_metrics(d)
            strength_score = compute_strength_score(d, m)
            m["strength_score"] = strength_score
            return (strength_score, d, m)
        return None

    # 3. Concurrent thread pool (8 threads) -> entire watchlist completes in < 1.5 seconds
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(active_syms))) as executor:
        futures = [executor.submit(_fetch_symbol, s) for s in active_syms]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                results.append(res)

    # Sort strictly based on strength, descending order
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def print_terminal_view(results, now_str, port, next_time_str=""):
    """Prints the ultra-clean numbered table to the terminal with 3m cycle status."""
    token = load_upstox_token()
    source_label = "UPSTOX PRO API (Direct Broker Feed)" if token else "STANDALONE MARKET FEED"
    next_info = f" | Next 3m Scan: {next_time_str}" if next_time_str else " | Refresh: 3m"

    print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}{CYAN}   ⚡ TRADINGVIEW PINE SCRIPT PARITY SCANNER — 3m DYNAMIC ORB & STRONG START [{now_str}]   {RESET}")
    print(f"{BOLD}{CYAN}   Feed: {source_label}{next_info} | Web View: http://127.0.0.1:{port}   {RESET}")
    print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════════════════════════════════════════{RESET}")

    cols = [
        f"{'#':<4}",
        f"{'SYMBOL':<10}",
        f"{'SS':^3}",
        f"{'PDH':^5}",
        f"{'H%':>7}",
        f"{'L%':>7}",
        f"{'ORB':^4}",
        f"{'TAG':^7}",
        "SIGNAL"
    ]
    header_line = " ".join(cols)
    print(header_line)
    print("─" * len(header_line))

    for idx, (_, d, m) in enumerate(results, start=1):
        sym = d["symbol"]

        # # Column (4 chars, e.g. [ 1] or [12])
        c_num = f"{GRAY}[{idx:>2}]{RESET}"

        # Symbol (10 chars, left) — OSC 8 Hidden Terminal Hyperlink
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"
        trailing_spaces = " " * max(0, 10 - len(sym))
        c_sym = f"\033]8;;{tv_url}\033\\{BOLD}{CYAN}{UNDERLINE}{sym}{RESET}\033]8;;\033\\{trailing_spaces}"

        # SS (3 chars, centered: ' ★ ' or ' - ')
        ss_char = "★" if d["is_strong_start"] else "-"
        ss_col = GREEN if d["is_strong_start"] else RESET
        c_ss = f" {ss_col}{ss_char}{RESET} "

        # PDH (5 chars, centered)
        pdh_col = GREEN if m["pdh_broken"] else RED
        c_pdh = f"  {pdh_col}●{RESET}  "

        # H% (7 chars, right)
        if m["h_pct"] is not None:
            h_s = f"{m['h_pct']:+.1f}%"
            h_col = GREEN if m["h_pct"] > 0 else RED
            c_h = f"{h_col}{h_s:>7}{RESET}"
        else:
            c_h = f"{'-':>7}"

        # L% (7 chars, right)
        if m["l_pct"] is not None:
            l_s = f"{m['l_pct']:+.1f}%"
            l_col = GREEN if m["l_pct"] > 0 else RED
            c_l = f"{l_col}{l_s:>7}{RESET}"
        else:
            c_l = f"{'-':>7}"

        # ORB (4 chars, centered)
        if m.get("is_reversal"):
            c_orb = f"{MAGENTA}{BOLD}L➔H{RESET} "
        else:
            c_orb = f" {m['orb_color']}{BOLD}{m['orb_status']}{RESET}  "

        # TAG (7 chars, centered)
        tag_s = m["tag"] if m["tag"] else "--"
        c_tag = f"{tag_s:^7}"

        # Signal
        c_sig = f"{m['sig_color']}{m['signal']}{RESET}"

        print(f"{c_num} {c_sym} {c_ss} {c_pdh} {c_h} {c_l} {c_orb} {c_tag} {c_sig}")

    print("─" * len(header_line))
    if next_time_str:
        print(f"{BOLD}{GREEN}⏱  3-MINUTE CYCLE ACTIVE: Next auto-scan at {next_time_str} (Hands-Free){RESET}")


def generate_html_dashboard(results, now_str, port):
    """Generates tablet touch-optimized HTML with direct 1-tap TradingView buttons, Timeframe switcher (3m/D), and real canvas charts."""
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    for idx_p in ["index.html", os.path.join(script_dir, "index.html")]:
        if os.path.isfile(idx_p):
            try:
                with open(idx_p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass

    rows_html = []
    charts_data = {}

    for idx, (_, d, m) in enumerate(results, start=1):
        sym = d["symbol"]
        is_ss = d["is_strong_start"]
        ss_display = '<span class="star">★</span>' if is_ss else '<span style="color:#787b86;">-</span>'

        pdh_display = '<span class="dot-green">●</span>' if m["pdh_broken"] else '<span class="dot-red">●</span>'

        h_val = f"{m['h_pct']:+.1f}%" if m["h_pct"] is not None else "-"
        h_class = "pos" if (m["h_pct"] and m["h_pct"] > 0) else "neg"

        l_val = f"{m['l_pct']:+.1f}%" if m["l_pct"] is not None else "-"
        l_class = "pos" if (m["l_pct"] and m["l_pct"] > 0) else "neg"

        if m.get("is_reversal"):
            orb_display = f'<span class="badge badge-sig-rev" title="{m.get("reversal_desc") or ""}">L➔H</span>'
        else:
            orb_class = f"badge-{m['orb_status'].lower()}"
            orb_display = f'<span class="badge {orb_class}">{m["orb_status"]}</span>'

        if m.get("is_strict") or ("STRICT" in m.get("signal", "")):
            sig_class = "badge-sig-strict"
        elif m.get("is_reversal"):
            sig_class = "badge-sig-rev"
        elif "BREAKOUT" in m["signal"] or "ABOVE" in m["signal"]:
            sig_class = "badge-sig-bull"
        else:
            sig_class = "badge-sig"
        sig_display = f'<span class="badge {sig_class}">{m["signal"]}</span>'

        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

        c_3m = d.get("candles_3m") or d.get("candles", [])
        c_d = d.get("candles_d", [])

        charts_data[sym] = {
            "symbol": sym,
            "ltp": d.get("ltp"),
            "prev_close": d.get("prev_close"),
            "chg_pct": m.get("chg_pct"),
            "pdh": d.get("pdh"),
            "pdh_broken": m.get("pdh_broken"),
            "orb_high": d.get("orb_high"),
            "orb_low": d.get("orb_low"),
            "high_bar_num": d.get("high_bar_num"),
            "low_bar_num": d.get("low_bar_num"),
            "orb_status": m.get("orb_status"),
            "is_strong_start": d.get("is_strong_start"),
            "rvol": d.get("rvol"),
            "signal": m.get("signal"),
            "sma50": d.get("sma50"),
            "atr14": d.get("atr14"),
            "candles": c_3m,
            "candles_3m": c_3m,
            "candles_d": c_d
        }

        row = f"""
        <tr onmouseenter="showChartPopup(event, '{sym}')" onmouseleave="scheduleHidePopup()">
            <td style="color:#787b86; text-align:center; font-weight:bold;">{idx}</td>
            <td>
                <div style="display:inline-flex; align-items:center; gap:6px;">
                    <a href="{tv_url}" class="btn-sym" title="Click to launch TradingView App">
                        📈 {sym}
                    </a>
                    <button class="btn-preview" onclick="showChartPopup(event, '{sym}', true)" title="Hover or tap to preview chart">👁</button>
                </div>
            </td>
            <td style="text-align:center;">{ss_display}</td>
            <td style="text-align:center;">{pdh_display}</td>
            <td class="{h_class}" style="text-align:right;">{h_val}</td>
            <td class="{l_class}" style="text-align:right;">{l_val}</td>
            <td style="text-align:center;">{orb_display}</td>
            <td style="text-align:center;" class="tag-txt">{m["tag"]}</td>
            <td>{sig_display}</td>
        </tr>
        """
        rows_html.append(row)

    table_rows = "".join(rows_html)
    charts_json = json.dumps(charts_data)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta http-equiv="refresh" content="180">
<title>⚡ Upstox 3m ORB Scanner — Galaxy Tablet</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
    body {{ background: #131722; color: #d1d4dc; padding: 12px; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #1e222d; border-radius: 8px; margin-bottom: 12px; border: 1px solid #2a2e39; }}
    .title {{ font-size: 15px; font-weight: bold; color: #2962ff; }}
    .meta {{ font-size: 12px; color: #787b86; text-align: right; }}
    .table-box {{ overflow-x: auto; background: #1e222d; border-radius: 8px; border: 1px solid #2a2e39; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 620px; }}
    th {{ background: #181b24; color: #787b86; font-size: 11px; text-transform: uppercase; padding: 10px 12px; letter-spacing: 0.5px; border-bottom: 1px solid #2a2e39; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #232733; font-size: 13px; vertical-align: middle; }}
    tr:hover {{ background: #262b3d; }}
    .btn-sym {{ display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; background: #2962ff; color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none; font-size: 14px; transition: transform 0.1s; box-shadow: 0 2px 4px rgba(0,0,0,0.3); }}
    .btn-sym:active {{ transform: scale(0.95); background: #1e4bd8; }}
    .star {{ color: #f59e0b; font-size: 16px; }}
    .dot-green {{ color: #089981; font-size: 15px; }}
    .dot-red {{ color: #f23645; font-size: 15px; }}
    .badge {{ display: inline-block; padding: 3px 7px; border-radius: 4px; font-weight: bold; font-size: 11px; }}
    .badge-h {{ background: rgba(8, 153, 129, 0.2); color: #089981; border: 1px solid #089981; }}
    .badge-l {{ background: rgba(242, 54, 69, 0.2); color: #f23645; border: 1px solid #f23645; }}
    .badge-m {{ background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid #f59e0b; }}
    .badge-sig {{ background: #2a2e39; color: #d1d4dc; font-size: 11px; padding: 3px 6px; border-radius: 4px; }}
    .badge-sig-bull {{ background: rgba(8, 153, 129, 0.25); color: #089981; border: 1px solid #089981; font-weight: bold; }}
    .tag-txt {{ font-family: monospace; font-size: 12px; color: #a3a6af; }}
    .pos {{ color: #089981; font-weight: bold; }}
    .neg {{ color: #f23645; font-weight: bold; }}
    .footer {{ margin-top: 10px; text-align: center; font-size: 11px; color: #787b86; }}

    /* Hover Preview Chart Styles */
    .btn-preview {{
        background: #2a2e39;
        color: #787b86;
        border: 1px solid #363a45;
        border-radius: 4px;
        padding: 6px 8px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.15s;
    }}
    .btn-preview:hover, .btn-preview:active {{
        background: #2962ff;
        color: #fff;
        border-color: #2962ff;
    }}
    .chart-popup {{
        display: none;
        position: fixed;
        z-index: 99999;
        width: 580px;
        max-width: 95vw;
        background: #181b24;
        border: 1px solid #2962ff;
        border-radius: 8px;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.85);
        overflow: hidden;
        flex-direction: column;
        pointer-events: auto;
    }}
    .popup-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #1e222d;
        padding: 8px 12px;
        font-weight: bold;
        font-size: 13px;
        color: #d1d4dc;
        border-bottom: 1px solid #2a2e39;
        flex-wrap: wrap;
        gap: 6px;
    }}
    .tf-selector {{
        display: inline-flex;
        background: #181b24;
        border: 1px solid #363a45;
        border-radius: 4px;
        overflow: hidden;
        margin-left: 6px;
    }}
    .tf-btn {{
        background: transparent;
        border: none;
        color: #787b86;
        padding: 2px 9px;
        font-size: 11px;
        font-weight: bold;
        cursor: pointer;
        transition: all 0.15s;
    }}
    .tf-btn:hover {{
        color: #fff;
    }}
    .tf-btn.active {{
        background: #2962ff;
        color: #fff;
    }}
    .popup-close {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        min-width: 32px;
        background: #2a2e39;
        color: #fff;
        border: 1px solid #363a45;
        border-radius: 6px;
        font-size: 16px;
        font-weight: bold;
        cursor: pointer;
        line-height: 1;
        flex-shrink: 0;
        transition: all 0.15s;
    }}
    .popup-close:hover, .popup-close:active {{
        background: #ef4444;
        border-color: #ef4444;
        color: #fff;
    }}
    .popup-btn-app {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 11px;
        color: #fff;
        text-decoration: none;
        font-weight: bold;
        background: #2962ff;
        padding: 4px 10px;
        border-radius: 4px;
        border: 1px solid #2962ff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.3);
    }}
    .popup-btn-app:hover {{ background: #1e4bd8; }}
    .popup-legend {{
        padding: 6px 12px;
        background: #141721;
        font-size: 11px;
        font-family: monospace;
        color: #8b949e;
        border-bottom: 1px solid #232733;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .popup-canvas-wrap {{
        position: relative;
        background: #131722;
        width: 100%;
        height: 330px;
    }}
    #popup-canvas {{
        display: block;
        width: 100%;
        height: 100%;
        cursor: crosshair;
    }}
</style>
</head>
<body>
    <div class="header">
        <div>
            <div class="title">⚡ Upstox 3m Dynamic ORB Scanner</div>
            <div style="font-size:11px; color:#a3a6af;">1-Tap TradingView Launcher — Samsung Galaxy Tablet</div>
        </div>
        <div class="meta">
            <div>Updated: <b>{now_str}</b></div>
            <div style="margin-top:3px; color:#2962ff; font-weight:bold; font-size:13px;">
                ⏱ Next Refresh: <span id="timer-display" style="color:#089981;">03:00</span>
            </div>
        </div>
    </div>

    <div class="table-box">
        <table>
            <thead>
                <tr>
                    <th style="width:35px; text-align:center;">#</th>
                    <th>Stock (Hover for Chart)</th>
                    <th style="text-align:center;">SS</th>
                    <th style="text-align:center;">PDH</th>
                    <th style="text-align:right;">H%</th>
                    <th style="text-align:right;">L%</th>
                    <th style="text-align:center;">ORB</th>
                    <th style="text-align:center;">TAG</th>
                    <th>Signal</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    <div class="footer">
        💡 Tip: Hover over any stock row (or tap 👁) to preview the live 3m chart. Tap blue button to launch TradingView app.
    </div>

    <!-- Floating Hover Chart Popup -->
    <div id="chart-popup" class="chart-popup" onmouseenter="cancelHidePopup()" onmouseleave="scheduleHidePopup()">
        <div class="popup-header">
            <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
                <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                    <span id="popup-title" style="font-weight:bold; color:#2962ff; font-size:13px;">📈 Symbol (3m Dynamic ORB)</span>
                    <div class="tf-selector">
                        <button id="tf-btn-3m" class="tf-btn active" onclick="switchTimeframe('3m')">3m</button>
                        <button id="tf-btn-d" class="tf-btn" onclick="switchTimeframe('D')">D</button>
                    </div>
                </div>
                <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
                    <a id="popup-app-link" href="#" target="_blank" class="popup-btn-app" title="Launch native TradingView App">🚀 Open in TV App ↗</a>
                    <button class="popup-close" onclick="hideChartPopup()">✕</button>
                </div>
            </div>
            <div id="popup-badges" style="display:flex; flex-wrap:wrap; gap:4px; font-size:11px; width:100%;"></div>
        </div>
        <div id="popup-legend" class="popup-legend">Hover or touch chart to inspect candle OHLC</div>
        <div class="popup-canvas-wrap">
            <canvas id="popup-canvas"></canvas>
        </div>
    </div>

    <script>
    let remSeconds = 180;
    const timerEl = document.getElementById('timer-display');
    setInterval(function() {{
        remSeconds--;
        if (remSeconds <= 0) {{
            if (timerEl) timerEl.innerText = "Refreshing...";
            location.reload();
        }} else {{
            const m = Math.floor(remSeconds / 60);
            const s = remSeconds % 60;
            if (timerEl) timerEl.innerText = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        }}
    }}, 1000);

    /* Live Chart Hover Popup Logic (HTML5 Canvas with 3m & D Timeframe support) */
    const CHARTS_DATA = {charts_json};
    let activeSym = "";
    let currentTimeframe = "3m";
    let popupTimer = null;
    const popup = document.getElementById('chart-popup');
    const popupTitle = document.getElementById('popup-title');
    const popupBadges = document.getElementById('popup-badges');
    const popupAppLink = document.getElementById('popup-app-link');
    const canvas = document.getElementById('popup-canvas');

    function switchTimeframe(tf) {{
        currentTimeframe = tf;
        const btn3m = document.getElementById('tf-btn-3m');
        const btnD = document.getElementById('tf-btn-d');
        if (btn3m && btnD) {{
            if (tf === 'D') {{
                btn3m.classList.remove('active');
                btnD.classList.add('active');
            }} else {{
                btn3m.classList.add('active');
                btnD.classList.remove('active');
            }}
        }}
        if (activeSym && CHARTS_DATA[activeSym]) {{
            updatePopupHeader(CHARTS_DATA[activeSym]);
            drawCanvasChart(canvas, CHARTS_DATA[activeSym]);
        }}
    }}

    function updatePopupHeader(data) {{
        if (!data) return;
        const isDaily = (currentTimeframe === 'D');
        popupTitle.innerText = "📈 " + data.symbol + (isDaily ? " (Daily Swing Chart)" : " (3m Dynamic ORB)");

        let bHtml = `<span class="badge" style="background:#2a2e39; color:#fff;">LTP: ₹${{Number(data.ltp).toFixed(2)}}</span>`;
        if (data.chg_pct !== undefined && data.chg_pct !== null) {{
            const col = data.chg_pct >= 0 ? '#089981' : '#f23645';
            const sign = data.chg_pct >= 0 ? '+' : '';
            bHtml += `<span class="badge" style="color:${{col}}; font-weight:bold;">${{sign}}${{data.chg_pct.toFixed(2)}}%</span>`;
        }}

        // Mark PDH in header
        if (data.pdh) {{
            const pdhCol = data.pdh_broken ? '#089981' : '#f23645';
            const pdhTxt = data.pdh_broken ? '● PDH Broken' : '● Below PDH';
            bHtml += `<span class="badge" style="border:1px solid #ffd700; color:#ffd700;" title="Previous Day High">📌 PDH: ₹${{Number(data.pdh).toFixed(1)}} (<span style="color:${{pdhCol}}">${{pdhTxt}}</span>)</span>`;
        }}

        if (!isDaily && data.orb_status) {{
            const col = data.orb_status === 'H' ? '#089981' : (data.orb_status === 'L' ? '#f23645' : '#f59e0b');
            bHtml += `<span class="badge" style="border:1px solid ${{col}}; color:${{col}};">ORB: ${{data.orb_status}}</span>`;
        }}

        if (data.is_strong_start) {{
            bHtml += `<span class="badge" style="background:rgba(245,158,11,0.2); color:#f59e0b; border:1px solid #f59e0b;">★ SS</span>`;
        }}

        popupBadges.innerHTML = bHtml;
    }}

    function drawCanvasChart(canvasEl, data, hoverX) {{
        if (!canvasEl) return;
        const ctx = canvasEl.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        const rect = canvasEl.getBoundingClientRect();
        const width = rect.width || 580;
        const height = rect.height || 330;

        if (canvasEl.width !== Math.floor(width * dpr) || canvasEl.height !== Math.floor(height * dpr)) {{
            canvasEl.width = Math.floor(width * dpr);
            canvasEl.height = Math.floor(height * dpr);
        }}
        ctx.resetTransform();
        ctx.scale(dpr, dpr);

        const W = width;
        const H = height;

        ctx.fillStyle = "#131722";
        ctx.fillRect(0, 0, W, H);

        const isDaily = (currentTimeframe === 'D');
        const candles = isDaily ? ((data && data.candles_d) ? data.candles_d : []) : ((data && (data.candles_3m || data.candles)) ? (data.candles_3m || data.candles) : []);

        if (!candles || candles.length === 0) {{
            ctx.fillStyle = "#787b86";
            ctx.font = "13px sans-serif";
            ctx.textAlign = "center";
            const emptyMsg = isDaily ? "No Daily candle data available" : "No 3m intraday candle data yet (Session starts 09:15 AM)";
            ctx.fillText(emptyMsg, W / 2, H / 2 - 10);
            if (data && data.ltp) {{
                ctx.fillStyle = "#089981";
                ctx.font = "bold 14px monospace";
                ctx.fillText("LTP: ₹" + Number(data.ltp).toFixed(2), W / 2, H / 2 + 15);
            }}
            return;
        }}

        const paddingRight = 68;
        const paddingBottom = 24;
        const paddingTop = 16;
        const paddingLeft = 8;
        const plotW = W - paddingLeft - paddingRight;
        const plotH = H - paddingTop - paddingBottom;
        const volH = plotH * 0.18;
        const pricePlotH = plotH - volH - 8;

        let minPrice = Infinity;
        let maxPrice = -Infinity;
        let maxVol = 0;

        for (let i = 0; i < candles.length; i++) {{
            const c = candles[i];
            if (c.l < minPrice) minPrice = c.l;
            if (c.h > maxPrice) maxPrice = c.h;
            if (c.v > maxVol) maxVol = c.v;
        }}

        // Always ensure PDH, LTP, and key levels are included in price bounds
        if (data.pdh) {{
            maxPrice = Math.max(maxPrice, data.pdh);
            minPrice = Math.min(minPrice, data.pdh);
        }}
        if (data.ltp) {{
            maxPrice = Math.max(maxPrice, data.ltp);
            minPrice = Math.min(minPrice, data.ltp);
        }}

        if (!isDaily) {{
            if (data.orb_high) maxPrice = Math.max(maxPrice, data.orb_high);
            if (data.orb_low) minPrice = Math.min(minPrice, data.orb_low);
        }} else {{
            if (data.sma50) {{
                maxPrice = Math.max(maxPrice, data.sma50);
                minPrice = Math.min(minPrice, data.sma50);
            }}
        }}

        const margin = (maxPrice - minPrice) * 0.08 || 1;
        minPrice -= margin;
        maxPrice += margin;
        const priceRange = maxPrice - minPrice;

        function getY(p) {{
            return paddingTop + (1 - (p - minPrice) / priceRange) * pricePlotH;
        }}
        function getP(y) {{
            return minPrice + (1 - (y - paddingTop) / pricePlotH) * priceRange;
        }}

        // Grid lines
        ctx.strokeStyle = "#1e222d";
        ctx.lineWidth = 1;
        ctx.setLineDash([]);
        ctx.fillStyle = "#787b86";
        ctx.font = "10px monospace";
        ctx.textAlign = "left";

        for (let i = 0; i <= 4; i++) {{
            const y = paddingTop + (i / 4) * pricePlotH;
            const p = getP(y);
            ctx.beginPath();
            ctx.moveTo(paddingLeft, y);
            ctx.lineTo(W - paddingRight, y);
            ctx.stroke();
            ctx.fillText(p.toFixed(1), W - paddingRight + 5, y + 3);
        }}

        function drawLevel(val, color, label, dash) {{
            if (!val || val < minPrice || val > maxPrice) return;
            const y = getY(val);
            ctx.save();
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.2;
            ctx.setLineDash(dash || [4, 3]);
            ctx.beginPath();
            ctx.moveTo(paddingLeft, y);
            ctx.lineTo(W - paddingRight, y);
            ctx.stroke();

            ctx.fillStyle = "rgba(19, 23, 34, 0.85)";
            const tagStr = label + " " + val.toFixed(1);
            ctx.font = "bold 9px monospace";
            const tw = ctx.measureText(tagStr).width;
            ctx.fillRect(paddingLeft + 4, y - 11, tw + 6, 12);
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.setLineDash([]);
            ctx.strokeRect(paddingLeft + 4, y - 11, tw + 6, 12);

            ctx.fillStyle = color;
            ctx.fillText(tagStr, paddingLeft + 7, y - 2);
            ctx.restore();
        }}

        // 3m Mode Overlays: Dynamic ORB High & Low
        if (!isDaily) {{
            if (data.orb_high) drawLevel(data.orb_high, "#00bcd4", "ORB-H", [4, 3]);
            if (data.orb_low) drawLevel(data.orb_low, "#ff9800", "ORB-L", [4, 3]);
        }}

        // Daily Mode Overlay: 50-Day SMA
        if (isDaily && data.sma50) {{
            drawLevel(data.sma50, "#ab47bc", "50 SMA", [5, 4]);
        }}

        // PDH Line (VIBRANT GOLD - CLEARLY MARKED)
        if (data.pdh && data.pdh >= minPrice && data.pdh <= maxPrice) {{
            const yPdh = getY(data.pdh);
            ctx.save();
            ctx.strokeStyle = "#ffd700";
            ctx.lineWidth = 1.8;
            ctx.setLineDash([5, 3]);
            ctx.beginPath();
            ctx.moveTo(paddingLeft, yPdh);
            ctx.lineTo(W - paddingRight, yPdh);
            ctx.stroke();

            // Left Pill Label
            const pdhTag = "📌 PDH: ₹" + Number(data.pdh).toFixed(1) + (data.pdh_broken ? " (BREACHED)" : "");
            ctx.font = "bold 10px monospace";
            const tw = ctx.measureText(pdhTag).width;
            ctx.fillStyle = "rgba(19, 23, 34, 0.9)";
            ctx.fillRect(paddingLeft + 4, yPdh - 13, tw + 8, 14);
            ctx.strokeStyle = "#ffd700";
            ctx.lineWidth = 1;
            ctx.setLineDash([]);
            ctx.strokeRect(paddingLeft + 4, yPdh - 13, tw + 8, 14);

            ctx.fillStyle = "#ffd700";
            ctx.fillText(pdhTag, paddingLeft + 8, yPdh - 3);

            // Right Axis Tag
            ctx.fillStyle = "#ffd700";
            ctx.fillRect(W - paddingRight + 2, yPdh - 7, paddingRight - 4, 15);
            ctx.fillStyle = "#000000";
            ctx.font = "bold 9px monospace";
            ctx.fillText("PDH " + Number(data.pdh).toFixed(0), W - paddingRight + 4, yPdh + 4);
            ctx.restore();
        }}

        // LTP Dotted Line
        if (data.ltp && data.ltp >= minPrice && data.ltp <= maxPrice) {{
            const yLtp = getY(data.ltp);
            ctx.save();
            ctx.strokeStyle = "rgba(41, 98, 255, 0.7)";
            ctx.lineWidth = 1;
            ctx.setLineDash([2, 2]);
            ctx.beginPath();
            ctx.moveTo(paddingLeft, yLtp);
            ctx.lineTo(W - paddingRight, yLtp);
            ctx.stroke();

            ctx.fillStyle = "#2962ff";
            ctx.fillRect(W - paddingRight + 2, yLtp - 8, paddingRight - 4, 16);
            ctx.fillStyle = "#ffffff";
            ctx.font = "bold 10px monospace";
            ctx.fillText(Number(data.ltp).toFixed(1), W - paddingRight + 5, yLtp + 4);
            ctx.restore();
        }}

        // Candlesticks (Default Green / Red)
        const n = candles.length;
        const maxBarSpacing = isDaily ? 20 : 15;
        const barSpacing = Math.min(plotW / Math.max(n, 1), maxBarSpacing);
        const barWidth = Math.max(Math.min(barSpacing * 0.75, 11), 2);

        let hoveredCandle = null;
        let lastLabelX = -999;

        for (let i = 0; i < n; i++) {{
            const c = candles[i];
            const cx = paddingLeft + i * barSpacing + barSpacing / 2;
            const oY = getY(c.o);
            const hY = getY(c.h);
            const lY = getY(c.l);
            const cY = getY(c.c);
            const isBull = c.c >= c.o;
            const col = isBull ? "#089981" : "#f23645";

            if (hoverX !== undefined && Math.abs(hoverX - cx) <= barSpacing / 2) {{
                hoveredCandle = Object.assign({{}}, c, {{ cx: cx, oY: oY, cY: cY, hY: hY, lY: lY, isBull: isBull }});
            }}

            const vH = maxVol > 0 ? (c.v / maxVol) * volH : 0;
            const vY = (H - paddingBottom) - vH;
            ctx.fillStyle = isBull ? "rgba(8, 153, 129, 0.25)" : "rgba(242, 54, 69, 0.25)";
            ctx.fillRect(cx - barWidth / 2, vY, barWidth, vH);

            // Wick
            ctx.strokeStyle = col;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(cx, hY);
            ctx.lineTo(cx, lY);
            ctx.stroke();

            // Body (Colored Fill)
            ctx.fillStyle = col;
            const bodyTop = Math.min(oY, cY);
            const bodyHeight = Math.max(Math.abs(cY - oY), 1.5);
            ctx.fillRect(cx - barWidth / 2, bodyTop, barWidth, bodyHeight);

            let labelText = c.t || '';
            if (labelText.includes('T')) {{
                labelText = isDaily ? labelText.split('T')[0] : (labelText.split('T')[1]?.substring(0, 5) || labelText);
            }} else if (labelText.length > 5 && !isDaily && labelText.includes(':')) {{
                labelText = labelText.substring(0, 5);
            }}

            const isFirst = (i === 0);
            const isLast = (i === n - 1);
            const hasEnoughSpace = (cx - lastLabelX >= 48);

            if ((isFirst || hasEnoughSpace) && (W - paddingRight - cx >= 15 || isLast)) {{
                ctx.fillStyle = "#787b86";
                ctx.font = "9px monospace";
                ctx.textAlign = "center";
                ctx.fillText(labelText, cx, H - 7);
                lastLabelX = cx;
            }}
        }}

        // Tooltip / Crosshair
        const legendEl = document.getElementById('popup-legend');
        const tfLabel = isDaily ? "Date" : "Time";
        if (hoveredCandle) {{
            ctx.save();
            ctx.strokeStyle = "rgba(209, 212, 220, 0.4)";
            ctx.setLineDash([3, 3]);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(hoveredCandle.cx, paddingTop);
            ctx.lineTo(hoveredCandle.cx, H - paddingBottom);
            ctx.stroke();
            ctx.restore();

            if (legendEl) {{
                const cColor = hoveredCandle.isBull ? '#089981' : '#f23645';
                legendEl.innerHTML = `<b>${{tfLabel}}: ${{hoveredCandle.t}}</b> | O: ₹${{hoveredCandle.o.toFixed(2)}} | H: ₹${{hoveredCandle.h.toFixed(2)}} | L: ₹${{hoveredCandle.l.toFixed(2)}} | <span style="color:${{cColor}};font-weight:bold;">C: ₹${{hoveredCandle.c.toFixed(2)}}</span> | Vol: ${{hoveredCandle.v.toLocaleString()}}`;
            }}
        }} else if (legendEl && candles.length) {{
            const last = candles[candles.length - 1];
            const cColor = last.c >= last.o ? '#089981' : '#f23645';
            legendEl.innerHTML = `Latest [${{tfLabel}}: <b>${{last.t}}</b>] | O: ₹${{last.o.toFixed(2)}} | H: ₹${{last.h.toFixed(2)}} | L: ₹${{last.l.toFixed(2)}} | <span style="color:${{cColor}};font-weight:bold;">C: ₹${{last.c.toFixed(2)}}</span> | Vol: ${{last.v.toLocaleString()}}`;
        }}
    }}

    function showChartPopup(e, sym, forceTap) {{
        if (popupTimer) {{
            clearTimeout(popupTimer);
            popupTimer = null;
        }}

        const popupWidth = Math.min(580, window.innerWidth - 20);
        const popupHeight = 390;
        let x = e.clientX || (window.innerWidth / 2 - popupWidth / 2);
        let y = e.clientY || (window.innerHeight / 2 - popupHeight / 2);

        let left = x + 15;
        let top = y - 40;

        if (left + popupWidth > window.innerWidth) {{
            left = x - popupWidth - 15;
        }}
        if (left < 10) left = 10;

        if (top + popupHeight > window.innerHeight) {{
            top = window.innerHeight - popupHeight - 15;
        }}
        if (top < 10) top = 10;

        popup.style.left = left + 'px';
        popup.style.top = top + 'px';
        popup.style.display = 'flex';

        activeSym = sym;
        const data = CHARTS_DATA[sym];

        popupAppLink.href = "https://in.tradingview.com/chart/?symbol=NSE:" + sym;

        if (data) {{
            updatePopupHeader(data);
            drawCanvasChart(canvas, data);
        }}
    }}

    canvas.addEventListener('mousemove', function(e) {{
        if (!activeSym || !CHARTS_DATA[activeSym]) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        drawCanvasChart(canvas, CHARTS_DATA[activeSym], x);
    }});
    canvas.addEventListener('mouseleave', function() {{
        if (!activeSym || !CHARTS_DATA[activeSym]) return;
        drawCanvasChart(canvas, CHARTS_DATA[activeSym]);
    }});
    canvas.addEventListener('touchmove', function(e) {{
        if (!activeSym || !CHARTS_DATA[activeSym]) return;
        if (e.touches && e.touches[0]) {{
            const rect = canvas.getBoundingClientRect();
            const x = e.touches[0].clientX - rect.left;
            drawCanvasChart(canvas, CHARTS_DATA[activeSym], x);
        }}
    }}, {{ passive: true }});

    function scheduleHidePopup() {{
        popupTimer = setTimeout(function() {{
            hideChartPopup();
        }}, 350);
    }}

    function cancelHidePopup() {{
        if (popupTimer) {{
            clearTimeout(popupTimer);
            popupTimer = null;
        }}
    }}

    function hideChartPopup() {{
        popup.style.display = 'none';
        if (popupTimer) {{
            clearTimeout(popupTimer);
            popupTimer = null;
        }}
    }}
    </script>
</body>
</html>
"""
    return html


class ThreadingHttpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ScannerHttpHandler(http.server.BaseHTTPRequestHandler):
    """Serves the live tablet web dashboard and data.json feed."""
    def log_message(self, format, *args):
        pass  # Suppress HTTP access logging to keep terminal clean

    def do_GET(self):
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        # Resolve file paths relative to script dir or current working dir
        script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()

        if self.path.startswith('/data.json'):
            for df in ["data.json", os.path.join(script_dir, "data.json")]:
                if os.path.isfile(df):
                    try:
                        with open(df, "rb") as f:
                            data_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Content-Length', str(len(data_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(data_bytes)
                        return
                    except Exception:
                        pass

        if self.path.startswith('/candidates.json'):
            for cf in ["candidates.json", os.path.join(script_dir, "candidates.json")]:
                if os.path.isfile(cf):
                    try:
                        with open(cf, "rb") as f:
                            cand_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Content-Length', str(len(cand_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(cand_bytes)
                        return
                    except Exception:
                        pass

        if self.path.startswith('/candidates_90d_nr.json') or self.path.startswith('/candidates_90d_momo.json'):
            target_f = "candidates_90d_nr.json" if self.path.startswith('/candidates_90d_nr.json') else "candidates_90d_momo.json"
            for cf in [target_f, os.path.join(script_dir, target_f)]:
                if os.path.isfile(cf):
                    try:
                        with open(cf, "rb") as f:
                            momo_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Content-Length', str(len(momo_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(momo_bytes)
                        return
                    except Exception:
                        pass

        if self.path.startswith('/candidates_nifty_ipo.json'):
            target_f = "candidates_nifty_ipo.json"
            for cf in [target_f, os.path.join(script_dir, target_f)]:
                if os.path.isfile(cf):
                    try:
                        with open(cf, "rb") as f:
                            ipo_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Content-Length', str(len(ipo_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(ipo_bytes)
                        return
                    except Exception:
                        pass

        if self.path.startswith('/candidates_ems.json'):
            target_f = "candidates_ems.json"
            for cf in [target_f, os.path.join(script_dir, target_f)]:
                if os.path.isfile(cf):
                    try:
                        with open(cf, "rb") as f:
                            ems_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Content-Length', str(len(ems_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(ems_bytes)
                        return
                    except Exception:
                        pass

        if self.path.startswith('/candidates_merged.json'):
            target_f = "candidates_merged.json"
            for cf in [target_f, os.path.join(script_dir, target_f)]:
                if os.path.isfile(cf):
                    try:
                        with open(cf, "rb") as f:
                            merged_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Content-Length', str(len(merged_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(merged_bytes)
                        return
                    except Exception:
                        pass

        # Always serve SOTA index.html on root / or /index.html
        if self.path in ('/', '/index.html') or self.path.startswith('/index.html'):
            for idx_f in ["index.html", os.path.join(script_dir, "index.html")]:
                if os.path.isfile(idx_f):
                    try:
                        with open(idx_f, "rb") as f:
                            index_bytes = f.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html; charset=utf-8')
                        self.send_header('Content-Length', str(len(index_bytes)))
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        self.wfile.write(index_bytes)
                        return
                    except Exception:
                        pass

        with data_lock:
            res_copy = list(latest_results)
            time_copy = str(last_scan_time)
            port_copy = active_web_port

        html_content = generate_html_dashboard(res_copy, time_copy, port_copy)
        encoded = html_content.encode('utf-8')

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Connection', 'close')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(encoded)


server_ready_event = threading.Event()


def start_web_server():
    """Starts the background HTTP server on the first available port (5000, 8080, etc.)."""
    global active_web_port
    ports_to_try = [5000, 8080, 8888, 5001, 8000]
    server = None
    for port in ports_to_try:
        try:
            # Bind to all interfaces ("") so 127.0.0.1, localhost, and tablet LAN IP work
            server = ThreadingHttpServer(("", port), ScannerHttpHandler)
            active_web_port = port
            break
        except Exception:
            continue

    server_ready_event.set()

    if server:
        try:
            server.serve_forever()
        except Exception:
            pass


def sync_file_to_github_api(gh_cfg, path, commit_msg, max_retries=2):
    """Commits and pushes a file to GitHub repository using REST API (zero git CLI required on tablet)."""
    full_path = path
    if not os.path.isabs(full_path):
        candidates = [full_path, os.path.join(SCRIPT_DIR, full_path)]
        for c in candidates:
            if os.path.isfile(c):
                full_path = c
                break
    if not gh_cfg or not gh_cfg.get("token") or not os.path.isfile(full_path):
        return False
    remote_path = os.path.basename(path).replace("\\", "/")
    try:
        import base64
        token = gh_cfg["token"].strip()
        owner = gh_cfg.get("username", "sanIncredible").strip()
        repo = gh_cfg.get("repo", "Jarvis").strip()
        branch = gh_cfg.get("branch", "main").strip()

        with open(full_path, "rb") as f:
            content_bytes = f.read()
        b64_content = base64.b64encode(content_bytes).decode("ascii")

        for attempt in range(max_retries + 1):
            # Check existing sha to update or create
            t_ms = int(time.time() * 1000)
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{remote_path}?ref={branch}&_t={t_ms}"
            sha = None
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Python-Tablet-Scanner",
                "Accept": "application/vnd.github+json",
                "Cache-Control": "no-cache"
            })
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    resp_json = json.loads(resp.read().decode())
                    sha = resp_json.get("sha")
                    remote_content = resp_json.get("content", "").replace("\n", "").strip()
                    # If content already matches remote repository exactly, treat as successful sync
                    if remote_content == b64_content:
                        return True
            except Exception:
                pass

            payload = {
                "message": commit_msg,
                "content": b64_content,
                "branch": branch
            }
            if sha:
                payload["sha"] = sha

            put_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{remote_path}"
            data = json.dumps(payload).encode("utf-8")
            put_req = urllib.request.Request(put_url, data=data, method="PUT", headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Python-Tablet-Scanner",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json"
            })
            try:
                with urllib.request.urlopen(put_req, timeout=12) as resp:
                    return True
            except urllib.error.HTTPError as he:
                if he.code == 409 and attempt < max_retries:
                    time.sleep(1.2)
                    continue
                return False
            except Exception:
                if attempt < max_retries:
                    time.sleep(1.0)
                    continue
                return False
    except Exception:
        return False


def purge_jsdelivr_cache():
    """Purges jsDelivr global edge CDN cache for data.json instantly (< 1s)."""
    try:
        url = "https://purge.jsdelivr.net/gh/sanIncredible/Jarvis@main/data.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-CDN-Purge"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            pass
    except Exception:
        pass


_last_git_push_ts = [0.0]
_git_push_lock = threading.Lock()


def trigger_git_push_async(force=False):
    """Spawns a background thread to commit and push data.json via GitHub API or Git CLI (throttled to max 1 per 18s unless force=True)."""
    gh_cfg = load_github_config()
    should_push = (gh_cfg and gh_cfg.get("auto_push")) or os.environ.get("AUTO_GIT_PUSH", "0") == "1" or os.path.isdir(".git")
    if not should_push:
        return

    now_ts = time.time()
    if not force and (now_ts - _last_git_push_ts[0]) < 18.0:
        return

    def _worker():
        if not _git_push_lock.acquire(blocking=False):
            return
        try:
            _last_git_push_ts[0] = time.time()
            # 1. Try direct GitHub REST API sync (Zero git client required on tablet!)
            if gh_cfg and gh_cfg.get("token"):
                if os.path.isfile("index.html"):
                    sync_file_to_github_api(gh_cfg, "index.html", "Init static dashboard shell index.html")
                now_t = get_ist_now().strftime("%H:%M:%S IST")
                pushed_api = sync_file_to_github_api(gh_cfg, "data.json", f"sync data.json {now_t}")
                if pushed_api:
                    purge_jsdelivr_cache()
                    return

            # 2. Fallback to CLI git if installed
            if os.path.isdir(".git"):
                if gh_cfg and gh_cfg.get("token"):
                    tok = gh_cfg["token"].strip()
                    owner = gh_cfg.get("username", "sanIncredible").strip()
                    repo = gh_cfg.get("repo", "Jarvis").strip()
                    os.system(f'git remote set-url origin https://x-access-token:{tok}@github.com/{owner}/{repo}.git')
                os.system('git add data.json && git commit -m "sync data.json" && git push')
                purge_jsdelivr_cache()
        except Exception:
            pass
        finally:
            _git_push_lock.release()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def export_static_html(results, now_str, port, force_cloud_push=False):
    """
    1. Generates compact data.json (~40KB) for low-latency git push & laptop infosec compliance.
    2. Saves standalone scanner_dashboard.html for offline local viewing on tablet.
    3. Triggers background git push if git repo is present.
    """
    try:
        # Build compact data.json payload
        source_label = "Upstox API v2"
        stocks_payload = []
        for idx, (score, d, m) in enumerate(results, start=1):
            if d.get("source") == "FALLBACK":
                source_label = "Yahoo Finance fallback"

            c_3m = d.get("candles_3m") or d.get("candles", [])
            # Preserve full trading day from 09:15 AM to 15:30 PM (125 3m bars)
            if len(c_3m) > 135:
                c_3m = c_3m[-135:]
            c_d = d.get("candles_d", [])
            if len(c_d) > 30:
                c_d = c_d[-30:]

            # Compact representation: [t, o, h, l, c, v] reduces JSON size by 60%
            compact_3m = [[c["t"], c["o"], c["h"], c["l"], c["c"], c.get("v", 0)] for c in c_3m]
            compact_d = [[c["t"], c["o"], c["h"], c["l"], c["c"], c.get("v", 0)] for c in c_d]

            stk_data = {
                "idx": idx,
                "symbol": d["symbol"],
                "ltp": d.get("ltp"),
                "prev_close": d.get("prev_close"),
                "day_open": d.get("day_open"),
                "gap_pct": m.get("gap_pct") if m.get("gap_pct") is not None else d.get("gap_pct"),
                "is_gap_up": bool(m.get("is_gap_up") or d.get("is_gap_up")),
                "chg_pct": round(m["chg_pct"], 2) if m.get("chg_pct") is not None else None,
                "pdh": d.get("pdh"),
                "pdh_broken": bool(m.get("pdh_broken", False)),
                "is_strict": bool(m.get("is_strict", False)),
                "is_narrow_prev_day": bool(d.get("is_narrow_prev_day", False)),
                "prev_range_ratio": d.get("prev_range_ratio"),
                "is_inside_day": bool(d.get("is_inside_day", False)),
                "pivot": d.get("pivot"),
                "day_low": m.get("day_low") or d.get("day_low"),
                "lod_dist": m.get("lod_dist"),
                "ema10": m.get("ema10"),
                "stretch_pct": m.get("stretch_pct"),
                "orb_high": d.get("orb_high"),
                "orb_low": d.get("orb_low"),
                "high_bar_num": d.get("high_bar_num"),
                "low_bar_num": d.get("low_bar_num"),
                "orb_status": "L➔H" if m.get("is_reversal") else m.get("orb_status"),
                "is_reversal": bool(m.get("is_reversal", False)),
                "reversal_desc": m.get("reversal_desc"),
                "orb_low_break_time": m.get("orb_low_break_time"),
                "orb_high_break_time": m.get("orb_high_break_time"),
                "is_ss": bool(d.get("is_strong_start", False)),
                "rvol": round(d["rvol"], 2) if d.get("rvol") is not None else None,
                "signal": m.get("signal"),
                "strength_score": round(score, 1),
                "tag": m.get("tag"),
                "h_pct": round(m["h_pct"], 1) if m.get("h_pct") is not None else None,
                "l_pct": round(m["l_pct"], 1) if m.get("l_pct") is not None else None,
                "sma50": round(d["sma50"], 2) if d.get("sma50") is not None else None,
                "atr14": round(d["atr14"], 2) if d.get("atr14") is not None else None,
                "atr_mult": round(m["atr_mult"], 2) if m.get("atr_mult") is not None else None,
                "is_breach": bool(m.get("is_breach", False)),
                "candles_3m": compact_3m,
                "candles_d": compact_d
            }
            stocks_payload.append(stk_data)

        # Load market regime if available
        script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        regime_data = {}
        for r_path in ["market_regime.json", os.path.join(script_dir, "market_regime.json")]:
            if os.path.isfile(r_path):
                try:
                    with open(r_path, "r", encoding="utf-8") as rf:
                        regime_data = json.load(rf)
                    break
                except Exception:
                    pass

        # Load 09:14 Situational Awareness pre-market summary if available
        sa_summary_data = {}
        for sa_p in ["pre_market_summary.json", os.path.join(script_dir, "pre_market_summary.json")]:
            if os.path.isfile(sa_p):
                try:
                    with open(sa_p, "r", encoding="utf-8") as saf:
                        sa_summary_data = json.load(saf)
                    break
                except Exception:
                    pass

        # Load candidates if available (ultra-light: only symbol and tier to keep git/network transfer light)
        candidates_payload = []
        for c_path in ["candidates.json", os.path.join(script_dir, "candidates.json")]:
            if os.path.isfile(c_path):
                try:
                    with open(c_path, "r", encoding="utf-8") as cf:
                        c_data = json.load(cf)
                        for c in c_data.get("candidates", []):
                            candidates_payload.append({
                                "symbol": c.get("symbol"),
                                "tier": c.get("tier", "TIER 1")
                            })
                    break
                except Exception:
                    pass

        # Load 90D/30% NR Momo candidates if available (prioritize NR Coils)
        momo_payload = []
        for nr_path in ["candidates_90d_nr.json", os.path.join(script_dir, "candidates_90d_nr.json")]:
            if os.path.isfile(nr_path):
                try:
                    with open(nr_path, "r", encoding="utf-8") as nf:
                        nr_data = json.load(nf)
                        t1 = nr_data.get("tier1_candidates", [])
                        t2 = nr_data.get("tier2_candidates", [])
                        t3 = nr_data.get("tier3_candidates", [])
                        for c in (t1 + t2 + t3):
                            rng_pct = float(c.get("daily_range_pct") or 0)
                            has_nr = c.get("is_nr7") or c.get("is_nr4") or c.get("is_inside") or c.get("is_tight")
                            if not has_nr or rng_pct < 0.25:
                                continue
                            momo_payload.append({
                                "symbol": c.get("symbol"),
                                "industry": c.get("industry"),
                                "gain_tier": c.get("gain_tier"),
                                "dist_52w_pct": c.get("dist_52w_pct"),
                                "is_fresh_3m": c.get("is_fresh_3m", False),
                                "tier": c.get("tier"),
                                "tier_order": c.get("tier_order", 1 if c.get("tier") == "TIER_1_DOORSTEP" else 2),
                                "is_nr7": c.get("is_nr7", False),
                                "is_nr4": c.get("is_nr4", False),
                                "is_inside": c.get("is_inside", False),
                                "is_tight": c.get("is_tight", False),
                                "daily_range_pct": rng_pct,
                                "nr_badge": c.get("nr_badge", ""),
                                "nr_tags": c.get("nr_tags", []),
                                "curr_close": c.get("curr_close")
                            })
                    if momo_payload:
                        break
                except Exception:
                    pass
        # Do not fallback to raw candidates_90d_momo.json without NR criteria;
        # the dashboard Momo tab strictly displays genuine Narrow Range (NR4/NR7/ID/Tight) coils.

        # Load Nifty IPO candidates if available
        ipo_payload = []
        for ipo_path in ["candidates_nifty_ipo.json", os.path.join(script_dir, "candidates_nifty_ipo.json")]:
            if os.path.isfile(ipo_path):
                try:
                    with open(ipo_path, "r", encoding="utf-8") as ipof:
                        ipo_data = json.load(ipof)
                        t1 = ipo_data.get("tier1_candidates", [])
                        t2 = ipo_data.get("tier2_candidates", [])
                        t3 = ipo_data.get("tier3_candidates", [])
                        for c in (t1 + t2 + t3):
                            ipo_payload.append({
                                "symbol": c.get("symbol"),
                                "name": c.get("name"),
                                "industry": c.get("industry"),
                                "ltp": c.get("ltp"),
                                "change_pct": c.get("change_pct"),
                                "dist_ath_pct": c.get("dist_ath_pct"),
                                "ath": c.get("ath"),
                                "tier": c.get("tier"),
                                "tier_order": c.get("tier_order", 1),
                                "is_nr7": c.get("is_nr7", False),
                                "is_nr4": c.get("is_nr4", False),
                                "is_inside": c.get("is_inside", False),
                                "is_tight": c.get("is_tight", False),
                                "daily_range_pct": c.get("daily_range_pct"),
                                "nr_badge": c.get("nr_badge", ""),
                                "nr_tags": c.get("nr_tags", [])
                            })
                    if ipo_payload:
                        break
                except Exception:
                    pass

        # Load Chirag Kedia Easy Money Scan (EMS) candidates if available
        ems_payload = []
        for ems_path in ["candidates_ems.json", os.path.join(script_dir, "candidates_ems.json")]:
            if os.path.isfile(ems_path):
                try:
                    with open(ems_path, "r", encoding="utf-8") as emsf:
                        ems_data = json.load(emsf)
                        t1 = ems_data.get("tier1_candidates", [])
                        t2 = ems_data.get("tier2_candidates", [])
                        t3 = ems_data.get("tier3_candidates", [])
                        for c in (t1 + t2 + t3):
                            ems_payload.append({
                                "symbol": c.get("symbol"),
                                "industry": c.get("industry"),
                                "tier": c.get("tier"),
                                "tier_order": c.get("tier_order", 1),
                                "triggers": c.get("triggers", []),
                                "trigger_badges": c.get("trigger_badges", []),
                                "triggers_count": c.get("triggers_count", 1),
                                "dist_52w_pct": c.get("dist_52w_pct"),
                                "rs_rating": c.get("rs_rating", 0),
                                "is_qm_coil": c.get("is_qm_coil", False),
                                "qm_details": c.get("qm_details"),
                                "coil_tag": c.get("coil_tag")
                            })
                    if ems_payload:
                        break
                except Exception:
                    pass

        # Load Unified Merged Candidates if available
        merged_payload = []
        for m_path in ["candidates_merged.json", os.path.join(script_dir, "candidates_merged.json")]:
            if os.path.isfile(m_path):
                try:
                    with open(m_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                        for c in m_data.get("candidates", []):
                            merged_payload.append({
                                "symbol": c.get("symbol"),
                                "industry": c.get("industry"),
                                "tier_order": c.get("tier_order", 1),
                                "tier": c.get("tier") or c.get("tier_label"),
                                "total_score": round(float(c.get("total_score", 0)), 1),
                                "sources": c.get("sources", [c.get("source", "eod")]),
                                "cross_list_bonus": c.get("cross_list_bonus", 0),
                                "dist_52w_pct": c.get("dist_52w_pct"),
                                "rs_rating": c.get("rs_rating", 0),
                                "ltp": c.get("ltp"),
                                "change_pct": c.get("change_pct"),
                                "coil_tag": c.get("coil_tag"),
                                "vol_tag": c.get("vol_tag"),
                                "flags": c.get("flags", []),
                                "is_sniper": c.get("is_sniper", False),
                                "is_blue_sky": c.get("is_blue_sky", False),
                                "is_qm_coil": c.get("is_qm_coil", False),
                                "qm_details": c.get("qm_details"),
                                "grade": c.get("grade", "B"),
                                "daily_range_pct": c.get("daily_range_pct")
                            })
                    if merged_payload:
                        break
                except Exception:
                    pass

        # Ingest candidates_exited.json if available
        exited_payload = []
        exited_standby_payload = []
        for ef in ["candidates_exited.json", os.path.join(script_dir, "candidates_exited.json")]:
            if os.path.isfile(ef):
                try:
                    with open(ef, "r", encoding="utf-8") as f_ex:
                        ex_data = json.load(f_ex)
                        exited_payload = ex_data.get("qualified", [])
                        exited_standby_payload = ex_data.get("standby", [])
                    if exited_payload or exited_standby_payload:
                        break
                except Exception:
                    pass

        payload = {
            "updated_at": now_str,
            "generated_at_ist": now_str,
            "updated_ts": int(time.time()),
            "timestamp_epoch_ms": int(time.time() * 1000),
            "source": source_label,
            "market_regime": regime_data,
            "pre_market_summary": sa_summary_data,
            "candidates": candidates_payload,
            "momo_candidates": momo_payload,
            "ipo_candidates": ipo_payload,
            "ems_candidates": ems_payload,
            "merged_candidates": merged_payload,
            "sniper_candidates": [c for c in merged_payload if c.get("is_sniper")],
            "qm_candidates": [c for c in merged_payload if c.get("is_qm_coil")],
            "exited_candidates": exited_payload,
            "exited_standby": exited_standby_payload,
            "active_themes": get_all_theme_breakouts(),
            "stocks": stocks_payload
        }

        # 1. Write compact data.json atomically to prevent race condition JSONDecodeError
        json_content = json.dumps(payload, separators=(',', ':'))
        script_dir_p = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        for df_path in [os.path.join(script_dir_p, "data.json"), "data.json"]:
            try:
                d_dir = os.path.dirname(os.path.abspath(df_path))
                with tempfile.NamedTemporaryFile("w", dir=d_dir, delete=False, encoding="utf-8") as tf:
                    tf.write(json_content)
                    temp_f = tf.name
                os.replace(temp_f, df_path)
            except Exception:
                try:
                    with open(df_path, "w", encoding="utf-8") as f:
                        f.write(json_content)
                except Exception:
                    pass

        # 2. Write standalone HTML dashboard for offline local viewing
        html_content = generate_html_dashboard(results, now_str, port)
        with open("scanner_dashboard.html", "w", encoding="utf-8") as f:
            f.write(html_content)

        # 3. Android tablet download directories
        for android_dir in ["/sdcard/Download", "/storage/emulated/0/Download"]:
            if os.path.isdir(android_dir):
                dest_json = os.path.join(android_dir, "data.json")
                with open(dest_json, "w", encoding="utf-8") as f:
                    f.write(json_content)
                dest_html = os.path.join(android_dir, "scanner_dashboard.html")
                with open(dest_html, "w", encoding="utf-8") as f:
                    f.write(html_content)

        # 4. Trigger async git push (throttled to 18s unless forced)
        trigger_git_push_async(force=force_cloud_push)
    except Exception:
        pass


def clear_screen():
    """Clears the console screen across Windows, Linux, and Android/Pydroid."""
    if os.name == 'nt':
        os.system('cls')
    else:
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()
        try:
            os.system('clear')
        except Exception:
            pass


next_refresh_timestamp = 0
stop_scanner_event = threading.Event()


next_refresh_timestamp = 0
current_market_event = 'CANDLE_CLOSE_3M'
stop_scanner_event = threading.Event()


def get_next_trading_day_914(now):
    """Calculates next 09:14:00 AM IST trading day (skips Saturday/Sunday)."""
    target = now.replace(hour=9, minute=14, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        target += timedelta(days=1)
    return target


def get_next_market_event(now):
    """
    Evaluates current IST time against the daily market lifecycle:
    - 'WARMUP_914': Weekday before 09:14:00 (sleeps until warmup)
    - 'MARKET_OPEN_915': Weekday 09:14:00 to 09:15:00 (warmup baselines ready)
    - 'CANDLE_CLOSE_3M': Weekday 09:15:00 to 15:30:00 (tracks 3m candles)
    - 'EOD_SLEEP': Weekday after 15:30:00 or Weekend (sleeps until next 09:14:00)
    """
    is_weekday = now.weekday() < 5
    if not is_weekday:
        nxt_914 = get_next_trading_day_914(now)
        return 'EOD_SLEEP', nxt_914, max(1.0, (nxt_914 - now).total_seconds())

    t_914 = now.replace(hour=9, minute=14, second=0, microsecond=0)
    t_915 = now.replace(hour=9, minute=15, second=0, microsecond=0)
    t_1530 = now.replace(hour=15, minute=30, second=0, microsecond=0)
    t_1535 = now.replace(hour=15, minute=35, second=5, microsecond=0)

    if now < t_914:
        return 'WARMUP_914', t_914, max(1.0, (t_914 - now).total_seconds())
    elif now < t_915:
        return 'MARKET_OPEN_915', t_915, max(1.0, (t_915 - now).total_seconds())
    elif now < t_1530:
        t_918 = now.replace(hour=9, minute=18, second=10, microsecond=0)
        if now < t_918:
            return 'CANDLE_CLOSE_3M', t_918, max(1.0, (t_918 - now).total_seconds())

        wait_secs, target_dt = get_next_candle_target(now=now, buffer_seconds=10)
        if target_dt > t_1530:
            target_dt = t_1530.replace(second=10)
            wait_secs = max(1.0, (target_dt - now).total_seconds())
        return 'CANDLE_CLOSE_3M', target_dt, wait_secs
    elif now < t_1535:
        return 'PHASE1_EOD_1535', t_1535, max(1.0, (t_1535 - now).total_seconds())
    else:
        nxt_914 = get_next_trading_day_914(now)
        return 'EOD_SLEEP', nxt_914, max(1.0, (nxt_914 - now).total_seconds())


def live_terminal_timer():
    """Continuously prints live ticking countdown aligned to the current market lifecycle."""
    if not sys.stdin.isatty():
        return  # Headless mode (systemd/cron) - disable interactive countdown prompt to keep logs clean
    while not stop_scanner_event.is_set():
        if next_refresh_timestamp > 0:
            rem = int(next_refresh_timestamp - time.time())
            if rem >= 0:
                m, s = divmod(rem, 60)
                h, m = divmod(m, 60)

                try:
                    if current_market_event == 'WARMUP_914':
                        prompt_txt = f"\r\033[K[🌙 Pre-Market | 09:14 Warmup in {h:02d}h {m:02d}m {s:02d}s] 👉 Enter # (1-16) or 'r': "
                    elif current_market_event == 'MARKET_OPEN_915':
                        prompt_txt = f"\r\033[K[⚡ 09:14 Warmup Done | Market Open in {m:02d}:{s:02d}] 👉 Enter # (1-16): "
                    elif current_market_event == 'CANDLE_CLOSE_3M':
                        prompt_txt = f"\r\033[K[⏱ 3m Candle Closes in {m:02d}:{s:02d}] 👉 Enter # (1-16) or 'w': "
                    elif current_market_event == 'PHASE1_EOD_1535':
                        prompt_txt = f"\r\033[K[🏁 Market Closed | 15:35 Phase 1 EOD Report in {m:02d}:{s:02d}] 👉 Enter # (1-16): "
                    else:
                        prompt_txt = f"\r\033[K[🏁 Market Closed | Next Session in {h:02d}h {m:02d}m] 👉 Enter # (1-16) or 'r': "

                    sys.stdout.write(prompt_txt)
                    sys.stdout.flush()
                except Exception:
                    pass
        time.sleep(1)


def get_next_candle_target(now=None, buffer_seconds=10):
    """Calculates exact timestamp for next 3m candle close (e.g. 09:18:10, 09:21:10, 09:24:10)."""
    if now is None:
        now = get_ist_now()
    minutes_to_add = (3 - (now.minute % 3)) % 3
    if minutes_to_add == 0 and now.second < buffer_seconds:
        target = now.replace(second=buffer_seconds, microsecond=0)
    else:
        if minutes_to_add == 0:
            minutes_to_add = 3
        target = (now + timedelta(minutes=minutes_to_add)).replace(second=buffer_seconds, microsecond=0)

    wait_secs = max(2.0, (target - now).total_seconds())
    return wait_secs, target


def check_market_clock_offset():
    """
    Checks system clock offset against Upstox server and exchange timestamps.
    Logs clock health, chrony/NTP sync status, and warns if drift > 2 seconds.
    """
    try:
        tok = load_upstox_token()
        if not tok:
            return 0.0
        ikey = get_instrument_key("RELIANCE")
        if not ikey:
            return 0.0
        enc = urllib.parse.quote(ikey, safe="")
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={enc}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json", "User-Agent": "Jarvis-ClockCheck"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=4) as resp:
            t1 = time.time()
            data = json.loads(resp.read().decode("utf-8"))
            first_item = list(data.get("data", {}).values())[0] if data.get("data") else {}
            ltt_ms = float(first_item.get("last_trade_time") or 0.0)
            if ltt_ms > 0:
                exch_sec = ltt_ms / 1000.0 if ltt_ms > 1e11 else ltt_ms
                mid_t = (t0 + t1) / 2.0
                offset = round(mid_t - exch_sec, 2)
                status_icon = "✅" if abs(offset) <= 2.0 else "⚠️"
                print(f"{status_icon} [CLOCK SYNC] VM System Clock vs Upstox Exchange Timestamp Offset: {offset:+.2f}s (HTTP Latency: {(t1 - t0)*1000:.1f}ms)")
                if abs(offset) > 5.0:
                    print(f"⚠️ [CLOCK SKEW WARNING] Clock drift is {abs(offset):.1f}s (> 5s)! Ensure chronyd or ntpd is active on this host.")
                return offset
    except Exception as e:
        print(f"Notice on clock offset check: {e}")
    return 0.0


def run_upstox_scanner(once=False, auto_open_web=False):
    """Main dashboard execution loop with market session state machine."""
    global latest_results, last_scan_time, active_web_port, next_refresh_timestamp, current_market_event

    # Check system clock offset against exchange clock at startup
    try:
        check_market_clock_offset()
    except Exception:
        pass

    # Start background web server (for 1-tap browser view)
    server_thread = threading.Thread(target=start_web_server, daemon=True)
    server_thread.start()
    server_ready_event.wait(timeout=1.5)

    # Initial baseline scan (so table is populated immediately)
    now_dt = get_ist_now()
    now_str = now_dt.strftime('%H:%M:%S IST')
    results = scan_watchlist()
    evaluate_and_dispatch_alerts(results, now_str)

    evt, target_dt, wait_secs = get_next_market_event(now_dt)
    current_market_event = evt
    next_refresh_timestamp = time.time() + wait_secs
    next_time_str = target_dt.strftime('%H:%M:%S IST')

    with data_lock:
        latest_results = results
        last_scan_time = now_str

    export_static_html(results, now_str, active_web_port)

    if not once:
        clear_screen()

    print_terminal_view(results, now_str, active_web_port, next_time_str)

    if auto_open_web:
        webbrowser.open(f"http://127.0.0.1:{active_web_port}")

    if once:
        return

    # Start live terminal countdown ticker
    timer_thread = threading.Thread(target=live_terminal_timer, daemon=True)
    timer_thread.start()

    # Background periodic scanner thread (orchestrates 09:14 warmup, 09:15 open, and 3m candles)
    _last_auto_gtt_date = [None]

    def check_and_run_auto_gtt_rearm(curr_now=None):
        """
        Automated 15:20 PM IST Overnight GTT Stop-Loss Rearm:
        Every trading day (Mon-Fri) at 15:20 IST, automatically audits all open positions
        across Upstox and Dhan, submitting permanent GTT stop-loss orders before the market close (15:30).
        """
        if curr_now is None:
            curr_now = get_ist_now()
        if curr_now.weekday() < 5 and curr_now.hour == 15 and 20 <= curr_now.minute <= 28:
            today_str = curr_now.strftime('%Y-%m-%d')
            if _last_auto_gtt_date[0] != today_str:
                _last_auto_gtt_date[0] = today_str
                try:
                    from order_engine import rearm_overnight_stop_losses
                    print(f"\n{YELLOW}🕒 15:20 PM IST: Triggering automated Overnight GTT Stop-Loss Rearm...{RESET}")
                    rearm_overnight_stop_losses(notify=True)
                except Exception as e:
                    print(f"Notice: Automated 15:20 GTT rearm exception: {e}")

    _last_orphan_sentry_time = [0.0]

    def check_and_run_orphan_sentry(curr_now=None):
        """
        Continuous Multi-Broker Orphan Position Sentry:
        Runs every 30 seconds during market hours (09:15-15:30 IST) across Upstox, Dhan, and Zerodha.
        Auto-places GTT Stop-Loss if any open position has been unhedged for >30 seconds.
        """
        now_ts = time.time()
        if now_ts - _last_orphan_sentry_time[0] < 30.0:
            return
        _last_orphan_sentry_time[0] = now_ts
        if curr_now is None:
            curr_now = get_ist_now()

        if curr_now.weekday() < 5:
            market_mins = curr_now.hour * 60 + curr_now.minute
            if 555 <= market_mins <= 930:  # 09:15 to 15:30 IST
                try:
                    from order_engine import run_orphan_position_sentry
                    run_orphan_position_sentry(auto_rearm=True, grace_seconds=30)
                except Exception:
                    pass

    _last_phase1_eod_date = [None]
    _last_day0_reset_date = [None]
    _last_launch_gate_date = [None]

    def check_and_run_monday_launch_gate(curr_now=None):
        """
        Pre-flight Launch Gate Assertion:
        Runs at 09:00 AM IST on Monday Nov 23, 2026 (and any session >= 2026-11-23).
        Asserts sentinel file present, 0 open positions, and empty/clean state files.
        Sends Telegram announcement if passed, or emergency alert if failed.
        """
        if curr_now is None:
            curr_now = get_ist_now()
        today_str = curr_now.strftime('%Y-%m-%d')
        if today_str >= "2026-11-23" and curr_now.weekday() < 5 and ((curr_now.hour == 9 and curr_now.minute >= 0) or curr_now.hour >= 10):
            if _last_launch_gate_date[0] != today_str:
                _last_launch_gate_date[0] = today_str
                try:
                    from shadow_execution_engine import assert_phase1_launch_readiness, send_phase1_telegram_alert
                    ready, msg = assert_phase1_launch_readiness()
                    if ready:
                        print(f"\n{GREEN}🚀 09:00 AM IST Monday Launch Gate PASSED: {msg}{RESET}")
                        send_phase1_telegram_alert(
                            f"🚀 <b>PHASE 1 LAUNCH GATE: PASSED</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• <b>Date:</b> {today_str} (Day 1 of 30)\n"
                            f"• <b>Status:</b> All Pre-Flight Assertions Verified\n"
                            f"• <b>Sentinel File:</b> Verified present\n"
                            f"• <b>Open Holdings:</b> 0 positions (Pristine Slate)\n"
                            f"• <b>Base Capital:</b> ₹5,00,000 (100% Cash Delivery, Zero Leverage)\n"
                            f"• <b>Trading Window:</b> 09:30–10:15 AM IST\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 <i>Autonomous shadow execution active. Ready for live signals.</i>",
                            topic_name="risk"
                        )
                    else:
                        print(f"\n{RED}🛑 09:00 AM IST Monday Launch Gate FAILED: {msg}{RESET}")
                        send_phase1_telegram_alert(
                            f"🛑 <b>CRITICAL: PHASE 1 LAUNCH GATE FAILED</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• <b>Date:</b> {today_str}\n"
                            f"• <b>Failure Reason:</b> {msg}\n"
                            f"• <b>Action:</b> Trading halted. All new entries rejected.\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"⚠️ <i>Please inspect archive and state files immediately.</i>",
                            topic_name="risk"
                        )
                except Exception as ex:
                    print(f"Notice on Launch Gate assertion: {ex}")

    def check_and_run_day0_flatten_and_archive(curr_now=None):
        """
        Flatten and archive Day 0 positions/state before Nov 23, 2026.
        Runs at 15:15 IST on Nov 20, 2026 (or any pre-Nov 23 session).
        """
        if curr_now is None:
            curr_now = get_ist_now()
        today_str = curr_now.strftime('%Y-%m-%d')
        if today_str < "2026-11-23" and curr_now.weekday() < 5 and ((curr_now.hour == 15 and curr_now.minute >= 15) or curr_now.hour >= 16):
            if _last_day0_reset_date[0] != today_str:
                _last_day0_reset_date[0] = today_str
                try:
                    from shadow_execution_engine import reset_and_archive_day0_state
                    print(f"\n{YELLOW}🛑 15:15 PM IST: Day 0 Shakedown Reset & Flatten Active -> Archiving state for Nov 23 Clean Launch...{RESET}")
                    reset_and_archive_day0_state(force=True)
                except Exception as e:
                    print(f"Notice on Day 0 reset: {e}")

    def check_and_run_phase1_eod_report(curr_now=None):
        """
        Automated 15:35 PM IST Phase 1 Autonomous Shadow Engine EOD Report:
        Dispatches full 30-day scoreboard, open runners, entries, and exits to Topic 11 ('reports').
        """
        if curr_now is None:
            curr_now = get_ist_now()
        if curr_now.weekday() < 5 and ((curr_now.hour == 15 and curr_now.minute >= 35) or curr_now.hour >= 16):
            today_str = curr_now.strftime('%Y-%m-%d')
            if _last_phase1_eod_date[0] != today_str:
                _last_phase1_eod_date[0] = today_str
                try:
                    from shadow_execution_engine import generate_and_send_phase1_eod_report
                    print(f"\n{YELLOW}🕒 15:35 PM IST: Generating Phase 1 Autonomous EOD Report...{RESET}")
                    generate_and_send_phase1_eod_report(notify=True)
                except Exception as e:
                    print(f"Notice: Phase 1 EOD report exception: {e}")

    def periodic_scanner():
        global latest_results, last_scan_time, next_refresh_timestamp, current_market_event, ACTIVE_WS_FEED
        last_wl_mtime = 0.0
        script_dir_local = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        wl_path = os.path.join(script_dir_local, "watchlist.txt") if os.path.isfile(os.path.join(script_dir_local, "watchlist.txt")) else "watchlist.txt"
        if os.path.isfile(wl_path):
            try:
                last_wl_mtime = os.path.getmtime(wl_path)
            except Exception:
                pass

        try:
            while not stop_scanner_event.is_set():
                now = get_ist_now()
                check_and_run_orphan_sentry(now)
                check_and_run_auto_gtt_rearm(now)
                check_and_run_day0_flatten_and_archive(now)
                check_and_run_monday_launch_gate(now)
                check_and_run_phase1_eod_report(now)
                try:
                    from shadow_execution_engine import update_shadow_trailing_and_exits
                    update_shadow_trailing_and_exits()
                except Exception:
                    pass
                evt, target, wait = get_next_market_event(now)
                current_market_event = evt
                next_refresh_timestamp = time.time() + wait

                # Dynamic window: strictly Mon-Fri 09:15:00 to 10:15:00 IST -> near-realtime WebSocket / fast pulses
                # After 10:15:00 IST -> 3-minute candle close polling
                tok = load_upstox_token()
                is_prime_window = (now.weekday() < 5 and ((now.hour == 9 and now.minute >= 15) or (now.hour == 10 and now.minute < 15)))
                poll_step = 2.0 if is_prime_window else 60.0

                # Manage WebSocket feed lifecycle for 09:15 - 10:15 AM prime window
                if is_prime_window and tok and UPSTOX_WS_AVAILABLE:
                    if ACTIVE_WS_FEED[0] is None or not ACTIVE_WS_FEED[0].is_running:
                        try:
                            print("⚡ [WebSocket] Launching Upstox V3 streaming market feed for prime window (09:15-10:15 IST)...")
                            ACTIVE_WS_FEED[0] = UpstoxWebSocketFeed(get_active_watchlist())
                            ACTIVE_WS_FEED[0].start()
                        except Exception as ws_err:
                            print(f"⚠️ [WebSocket] Streamer startup notice: {ws_err}")
                            ACTIVE_WS_FEED[0] = None
                elif not is_prime_window:
                    if ACTIVE_WS_FEED[0] is not None and ACTIVE_WS_FEED[0].is_running:
                        print("🔒 [WebSocket] 10:15 AM Prime window ended: stopping WebSocket streamer.")
                        try:
                            ACTIVE_WS_FEED[0].stop()
                        except Exception:
                            pass
                        ACTIVE_WS_FEED[0] = None

                while wait > 0 and not stop_scanner_event.is_set():
                    sleep_sec = min(poll_step, max(1.0, wait))
                    time.sleep(sleep_sec)
                    cur_loop_now = get_ist_now()
                    check_and_run_orphan_sentry(cur_loop_now)
                    check_and_run_auto_gtt_rearm(cur_loop_now)
                    check_and_run_day0_flatten_and_archive(cur_loop_now)
                    check_and_run_phase1_eod_report(cur_loop_now)
                    try:
                        from shadow_execution_engine import update_shadow_trailing_and_exits
                        update_shadow_trailing_and_exits()
                    except Exception:
                        pass
                    wait = (target - cur_loop_now).total_seconds()

                    # Instant hot-resubscribe if watchlist.txt was modified externally
                    try:
                        if os.path.isfile(wl_path):
                            cur_wl_mtime = os.path.getmtime(wl_path)
                            if last_wl_mtime and cur_wl_mtime != last_wl_mtime:
                                last_wl_mtime = cur_wl_mtime
                                print("⚡ [Watchlist] External update detected in watchlist.txt -> hot-resubscribing WebSocket...")
                                hot_resubscribe_websocket()
                            elif not last_wl_mtime:
                                last_wl_mtime = cur_wl_mtime
                    except Exception:
                        pass

                    # Near-realtime quote pulse during 09:15 - 10:15 AM: check for instant breakouts, coils, and live chart update
                    if is_prime_window and wait > 1.0:
                        try:
                            fast_quotes = {}
                            # Tier 1: Check in-memory decoded protobuf ticks from WebSocket (sub-millisecond)
                            if ACTIVE_WS_FEED[0] and ACTIVE_WS_FEED[0].is_healthy():
                                fast_quotes = ACTIVE_WS_FEED[0].get_all_latest_quotes()

                            # Tier 2: Resilient Fallback - if WS reconnecting/token refresh, fetch 3s bulk REST batch
                            if not fast_quotes and tok:
                                fast_quotes = fetch_upstox_bulk_quotes(get_active_watchlist(), tok)

                            if fast_quotes and latest_results:
                                updated_res = []
                                has_price_move = False
                                for score, d, m in latest_results:
                                    sym = d["symbol"]
                                    q = fast_quotes.get(sym.upper())
                                    if q:
                                        live_p = float(q.get("last_price") or q.get("ltp") or d.get("ltp") or 0.0)
                                        old_p = float(d.get("ltp") or live_p)
                                        if abs(live_p - old_p) >= 0.05:
                                            has_price_move = True
                                        d["ltp"] = live_p
                                        d["day_high"] = max(float(d.get("day_high") or live_p), live_p)
                                        if d.get("day_low"):
                                            d["day_low"] = min(float(d["day_low"]), live_p)
                                        else:
                                            d["day_low"] = live_p
                                        # Update 3m candle live tick if available
                                        c_3m = d.get("candles_3m") or d.get("candles") or []
                                        if c_3m:
                                            cur_loop_m = cur_loop_now.minute
                                            cur_bucket_m = (cur_loop_m // 3) * 3
                                            cur_bucket_str = f"{cur_loop_now.hour:02d}:{cur_bucket_m:02d}"
                                            last_c = c_3m[-1]
                                            last_t = last_c.get("t") if isinstance(last_c, dict) else (str(last_c[0])[-5:] if len(last_c) > 0 else "")
                                            if last_t and last_t < cur_bucket_str:
                                                prev_c_val = float(last_c.get("c") if isinstance(last_c, dict) else last_c[4])
                                                new_bar = {
                                                    "t": cur_bucket_str,
                                                    "o": prev_c_val,
                                                    "h": max(prev_c_val, live_p),
                                                    "l": min(prev_c_val, live_p),
                                                    "c": live_p,
                                                    "v": 0
                                                } if isinstance(last_c, dict) else [
                                                    cur_bucket_str,
                                                    prev_c_val,
                                                    max(prev_c_val, live_p),
                                                    min(prev_c_val, live_p),
                                                    live_p,
                                                    0
                                                ]
                                                c_3m.append(new_bar)
                                            else:
                                                if isinstance(last_c, dict):
                                                    last_c["c"] = live_p
                                                    last_c["h"] = max(last_c.get("h", live_p), live_p)
                                                    last_c["l"] = min(last_c.get("l", live_p), live_p)
                                                elif isinstance(last_c, list) and len(last_c) >= 5:
                                                    last_c[4] = live_p
                                                    last_c[2] = max(float(last_c[2]), live_p)
                                                    last_c[3] = min(float(last_c[3]), live_p)
                                        new_m = compute_metrics(d)
                                        new_score = compute_strength_score(d, new_m)
                                        new_m["strength_score"] = new_score
                                        updated_res.append((new_score, d, new_m))
                                    else:
                                        updated_res.append((score, d, m))

                                if updated_res and has_price_move:
                                    updated_res.sort(key=lambda x: x[0], reverse=True)
                                    cur_t = get_ist_now().strftime('%H:%M:%S IST')
                                    evaluate_and_dispatch_alerts(updated_res, cur_t)
                                    with data_lock:
                                        latest_results = updated_res
                                        last_scan_time = cur_t
                                    export_static_html(updated_res, cur_t, active_web_port)
                        except Exception:
                            pass

                if stop_scanner_event.is_set():
                    break

                # Target reached: perform scan / warmup
                new_res = scan_watchlist()
                cur_time = get_ist_now().strftime('%H:%M:%S IST')
                evaluate_and_dispatch_alerts(new_res, cur_time)
                check_and_run_auto_gtt_rearm()

                # Sync any newly added watchlist stocks to active WebSocket streamer
                if ACTIVE_WS_FEED[0] and ACTIVE_WS_FEED[0].is_running:
                    try:
                        ACTIVE_WS_FEED[0].update_symbols(get_active_watchlist())
                    except Exception:
                        pass

                # Determine next target event
                nxt_now = get_ist_now()
                nxt_evt, nxt_target, nxt_wait = get_next_market_event(nxt_now)
                current_market_event = nxt_evt
                next_refresh_timestamp = time.time() + nxt_wait
                next_str = nxt_target.strftime('%H:%M:%S IST')

                with data_lock:
                    latest_results = new_res
                    last_scan_time = cur_time

                export_static_html(new_res, cur_time, active_web_port, force_cloud_push=True)

                clear_screen()
                print_terminal_view(new_res, cur_time, active_web_port, next_str)
        finally:
            if ACTIVE_WS_FEED[0] is not None and ACTIVE_WS_FEED[0].is_running:
                try:
                    ACTIVE_WS_FEED[0].stop()
                except Exception:
                    pass
                ACTIVE_WS_FEED[0] = None

    scanner_thread = threading.Thread(target=periodic_scanner, daemon=True)
    scanner_thread.start()

    # Start Telegram Command Bot Engine (Always active on OCI VM / Linux, or on Windows if --bot passed)
    if sys.platform != "win32" or "--bot" in sys.argv:
        try:
            from telegram_bot import start_telegram_bot_thread
            start_telegram_bot_thread()
            print(f"{GREEN}🤖 Telegram Command Bot Daemon Active (Listening for /add, /remove, /watchlist, /token...){RESET}")
        except Exception as e:
            print(f"{YELLOW}ℹ️ Telegram Bot notice: {e}{RESET}")

    # If running headless under systemd (no interactive terminal), stay alive and wait for stop event
    if not sys.stdin.isatty():
        try:
            while not stop_scanner_event.is_set():
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            stop_scanner_event.set()
        return

    # Interactive input loop in terminal
    while True:
        try:
            cmd = input().strip()
            if not cmd:
                continue
            if cmd.lower() == 'q':
                stop_scanner_event.set()
                print("\nExiting scanner.")
                break
            elif cmd.lower() in ('w', 'web'):
                url = f"http://127.0.0.1:{active_web_port}"
                print(f"\n{GREEN}🌐 Opening Web Dashboard ({url}) in Chrome...{RESET}")
                webbrowser.open(url)
            elif cmd.lower() == 'r':
                with data_lock:
                    res_copy = list(latest_results)
                    t_copy = str(last_scan_time)
                next_str = (get_ist_now() + timedelta(seconds=REFRESH_SECONDS)).strftime('%H:%M:%S IST')
                clear_screen()
                print_terminal_view(res_copy, t_copy, active_web_port, next_str)
            elif cmd.isdigit():
                idx = int(cmd)
                with data_lock:
                    total_stocks = len(latest_results)
                    target_d = latest_results[idx - 1][1] if 1 <= idx <= total_stocks else None

                if target_d:
                    sym = target_d["symbol"]
                    chart_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"
                    print(f"\n{GREEN}🚀 Opening {sym} in TradingView App...{RESET}")
                    webbrowser.open(chart_url)
                else:
                    print(f"\n{YELLOW}⚠️ Please enter a number between 1 and {total_stocks}.{RESET}")
            else:
                print(f"\n{YELLOW}Type a number (e.g. 1) to open chart, 'w' for Chrome, 'q' to quit.{RESET}")
        except (EOFError, KeyboardInterrupt):
            stop_scanner_event.set()
            break


if __name__ == "__main__":
    if "--test-telegram" in sys.argv:
        print("📱 Testing Telegram Alert Dispatch...")
        tg_cfg = load_telegram_config()
        if not tg_cfg:
            print("❌ Telegram configuration not found in config_credentials.json or environment variables.")
            print("   Add your bot_token and chat_id under the 'telegram' key in config_credentials.json.")
            sys.exit(1)
        t_now = get_ist_now().strftime("%H:%M IST")
        test_msg = (
            f"⚡ <b>JARVIS BREAKOUT ALERT — {t_now}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <a href='https://in.tradingview.com/chart/?symbol=NSE:RELIANCE'><b>RELIANCE</b></a> (₹1,320.50)\n"
            "• Trigger : ★ SS + ORB + PDH Break\n"
            "• LoD Dist: 🟢 42% ATR (Ample Headroom)\n"
            "• Stop Loss: ₹1,310.00 (Day Low: 0.8% risk)\n"
            "• 10 EMA : 🟢 Prime Coil (+0.3%)\n"
            "• Chart : <a href='https://in.tradingview.com/chart/?symbol=NSE:RELIANCE'>Open TradingView ↗</a>\n\n"
            "⚠️ <a href='https://in.tradingview.com/chart/?symbol=NSE:SHILPAMED'><b>SHILPAMED</b></a> (₹1,040.00)\n"
            "• Trigger : ORB High Break\n"
            "• LoD Dist: ⚠️ 104% ATR (Range Exhausted — DO NOT CHASE!)\n"
            "• Stop Loss: ₹1,008.00 (Day Low: 3.1% risk — Too Wide)\n"
            "• 10 EMA : ⚪ Normal (+1.1%)\n"
            "• Chart : <a href='https://in.tradingview.com/chart/?symbol=NSE:SHILPAMED'>Open TradingView ↗</a>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 <a href='https://sanincredible.github.io/Jarvis/'>Open 3m Terminal Dashboard</a>"
        )
        ok, res = send_telegram_alert(test_msg)
        if ok:
            print("✅ Telegram test alert delivered successfully to your chat!")
        else:
            print(f"❌ Telegram delivery failed: {res}")
        sys.exit(0)

    if "--push" in sys.argv:
        print("📦 Pushing data.json to GitHub...")
        gh_cfg = load_github_config()
        if not gh_cfg:
            print("❌ GitHub configuration not found in credentials file.")
            sys.exit(1)
        if os.path.isfile("index.html"):
            sync_file_to_github_api(gh_cfg, "index.html", "Init static dashboard shell index.html")
        if os.path.isfile("watchlist.txt"):
            sync_file_to_github_api(gh_cfg, "watchlist.txt", "Update watchlist.txt")
        if os.path.isfile("upstox_tablet_scanner.py"):
            sync_file_to_github_api(gh_cfg, "upstox_tablet_scanner.py", "Update scanner code")
        now_str = get_ist_now().strftime("%H:%M:%S IST")
        ok = sync_file_to_github_api(gh_cfg, "data.json", f"market feed {now_str}")
        if ok:
            print("✅ Successfully pushed data.json to GitHub!")
        else:
            print("❌ Push failed. Ensure token has 'Contents: Read and write' permission.")
        sys.exit(0)

    once_mode = "--once" in sys.argv
    web_mode = "--web" in sys.argv
    run_upstox_scanner(once=once_mode, auto_open_web=web_mode)
