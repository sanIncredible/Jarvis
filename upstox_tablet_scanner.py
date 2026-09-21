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

CONFIG_FILE = "config_credentials.json"
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
    "BELRISE": "INE00AA01018",
    "URBANCO": "INE01ZZ01010",
}

# ANSI Colors matching Pine Script Palette
GREEN = "\033[92m"        # Lime / Green (#0b8043)
RED = "\033[91m"          # Red (#cc2222)
ORANGE = "\033[38;5;214m" # Orange / Amber (#c77800)
YELLOW = "\033[93m"
CYAN = "\033[96m"
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
    """Loads active Upstox access token from environment, upstoxtoken.txt, or config file."""
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if token:
        return token

    if os.path.isfile("upstoxtoken.txt"):
        try:
            with open("upstoxtoken.txt", "r", encoding="utf-8") as f:
                tok = f.read().strip()
                if tok:
                    return tok
        except Exception:
            pass

    for cfg_path in [CONFIG_FILE, "credentials.json"]:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    tok = cfg.get("upstox", {}).get("access_token", "").strip()
                    if tok:
                        return tok
            except Exception:
                pass

    return None


def load_github_config():
    """Loads GitHub token and repo config from credentials file."""
    for cfg_path in [CONFIG_FILE, "credentials.json"]:
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
    """Pulls latest upstoxtoken.txt and watchlist.txt from GitHub repository over HTTPS (443)."""
    gh_cfg = load_github_config()
    if not gh_cfg or not gh_cfg.get("token"):
        return
    try:
        import base64
        token = gh_cfg["token"].strip()
        owner = gh_cfg.get("username", "sanIncredible").strip()
        repo = gh_cfg.get("repo", "Jarvis").strip()
        branch = gh_cfg.get("branch", "main").strip()

        for filename in ["upstoxtoken.txt", "watchlist.txt"]:
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
                            with open(filename, "w", encoding="utf-8") as f:
                                f.write(content_str)
            except Exception:
                pass
    except Exception:
        pass


def get_instrument_key(symbol):
    """Resolves instrument key for Upstox API queries."""
    isin = SYMBOL_TO_ISIN.get(symbol.upper())
    if isin:
        return f"NSE_EQ|{isin}"
    return f"NSE_EQ|{symbol.upper()}"


def fetch_upstox_symbol_data(symbol, token):
    """Fetches live market data and 3m candles from Upstox API v2."""
    inst_key = get_instrument_key(symbol)
    encoded_key = urllib.parse.quote(inst_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    ltp = None
    prev_close = None
    pdh = None
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
        # 1. Market Quote (LTP, PrevClose, Day OHLC)
        quote_url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded_key}"
        req_q = urllib.request.Request(quote_url, headers=headers)
        with urllib.request.urlopen(req_q, timeout=4) as resp:
            q_json = json.loads(resp.read().decode('utf-8'))
            key_in_data = inst_key.replace("|", ":")
            d_quote = q_json.get("data", {}).get(key_in_data, {})
            if d_quote:
                ltp = float(d_quote.get("last_price", 0))
                ohlc = d_quote.get("ohlc", {})
                prev_close = float(ohlc.get("close", 0))
                day_open = float(ohlc.get("open", 0))
                day_low = float(ohlc.get("low", 0))

                # Pine Script: isStrongStart(o, l, pc) => o > pc and l >= pc * 0.995
                if day_open > prev_close and day_low >= (prev_close * 0.995):
                    is_strong_start = True

        # 2. Intraday 3-Minute Candles (Pine Script f_orb() logic)
        candle_url = f"https://api.upstox.com/v2/historical-candle/intraday/{encoded_key}/3minute"
        req_c = urllib.request.Request(candle_url, headers=headers)
        with urllib.request.urlopen(req_c, timeout=4) as resp:
            c_json = json.loads(resp.read().decode('utf-8'))
            raw_candles = c_json.get("data", {}).get("candles", [])
            if raw_candles:
                # Guarantee chronological order: 09:15 AM opening candle is ALWAYS Bar 1
                candles_3m = sorted(raw_candles, key=lambda c: str(c[0]))

                highs_3m = [float(c[2]) for c in candles_3m]
                lows_3m = [float(c[3]) for c in candles_3m]

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
            if daily_raw and len(daily_raw) >= 2:
                pdh = float(daily_raw[1][2])  # high[1]

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

                # Pine Script: avgv = ta.sma(volume[1], 20), rvol = volume / avgv
                if len(vols) >= 21:
                    avg_v = sum(vols[1:21]) / 20.0
                    if avg_v > 0:
                        rvol = vols[0] / avg_v

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

    except Exception:
        return None

    if ltp is None or prev_close is None:
        return None

    return {
        "symbol": symbol,
        "ltp": ltp,
        "prev_close": prev_close,
        "pdh": pdh,
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
    if not clean_sym.endswith(".NS") and not clean_sym.endswith(".BO"):
        ticker = clean_sym + ".NS"
    else:
        ticker = clean_sym

    headers = {"User-Agent": "Mozilla/5.0"}
    ltp = None
    prev_close = None
    pdh = None
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

            if len(highs) >= 2:
                pdh = highs[-2]

            if opens and lows and prev_close:
                if opens[-1] > prev_close and lows[-1] >= (prev_close * 0.995):
                    is_strong_start = True

            if len(vols) >= 21:
                avg_vol = sum(vols[-21:-1]) / 20.0
                if avg_vol > 0:
                    rvol = vols[-1] / avg_vol

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

    return {
        "symbol": symbol,
        "ltp": ltp,
        "prev_close": prev_close,
        "pdh": pdh,
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

    # 7. Action Signal
    signal = "IN RANGE"
    sig_color = RESET
    if d["is_strong_start"] and orb_status == "H" and pdh_broken:
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
        sig_color = GREEN
    elif orb_status == "L":
        signal = "BELOW ORB LOW"
        sig_color = RED

    return {
        "chg_pct": chg_pct,
        "pdh_broken": pdh_broken,
        "h_pct": h_pct,
        "l_pct": l_pct,
        "orb_status": orb_status,
        "orb_color": orb_color,
        "tag": tag,
        "atr_mult": atr_mult,
        "is_breach": is_breach,
        "signal": signal,
        "sig_color": sig_color
    }


def compute_strength_score(d, m):
    """
    Computes institutional Strength Score for sorting in descending order:
    Tier 1: ★ Strong Start + ORB Breakout + PDH Breakout (Score: 1500 + H%*10 + Chg%)
    Tier 2: BULLISH BREAKOUT (ORB + PDH) (Score: 1300 + H%*10 + Chg%)
    Tier 3: ★ Strong Start + ORB Breakout (Score: 1200 + H%*10 + Chg%)
    Tier 4: ABOVE ORB HIGH (Score: 1000 + H%*10 + Chg%)
    Tier 5: IN RANGE (Score: 500 + H%*10 + Chg%)
    Tier 6: BELOW ORB LOW (Score: 100 if SS else 0 + H%*10 + Chg%)
    """
    orb_status = m.get("orb_status", "M")
    pdh_broken = m.get("pdh_broken", False)
    is_ss = d.get("is_strong_start", False)
    h_pct = m.get("h_pct") or 0.0
    chg_pct = m.get("chg_pct") or 0.0

    if is_ss and orb_status == "H" and pdh_broken:
        tier = 1500.0
    elif orb_status == "H" and pdh_broken:
        tier = 1300.0
    elif is_ss and orb_status == "H":
        tier = 1200.0
    elif orb_status == "H":
        tier = 1000.0
    elif orb_status == "M":
        tier = 500.0
    else:  # 'L'
        tier = 100.0 if is_ss else 0.0

    score = tier + (h_pct * 10.0) + chg_pct
    return round(score, 2)


def get_active_watchlist():
    """Loads active watchlist dynamically from watchlist.txt, config_credentials.json, or default WATCHLIST."""
    if os.path.isfile("watchlist.txt"):
        try:
            with open("watchlist.txt", "r", encoding="utf-8") as f:
                lines = [l.strip().upper().replace(",", " ") for l in f if l.strip() and not l.startswith("#")]
                syms = []
                for line in lines:
                    syms.extend(line.split())
                if syms:
                    return syms
        except Exception:
            pass

    for cfg_f in [CONFIG_FILE, "credentials.json"]:
        if os.path.isfile(cfg_f):
            try:
                with open(cfg_f, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    syms = cfg.get("watchlist")
                    if syms and isinstance(syms, list):
                        return [s.strip().upper() for s in syms if s.strip()]
            except Exception:
                pass

    return WATCHLIST


def scan_watchlist():
    """Scans all symbols in watchlist and returns results sorted by strength descending."""
    try:
        sync_remote_files_from_github()
    except Exception:
        pass
    token = load_upstox_token()
    results = []
    active_syms = get_active_watchlist()
    for sym in active_syms:
        d = None
        if token:
            d = fetch_upstox_symbol_data(sym, token)

        if not d or not d.get("ltp"):
            d = fetch_fallback_data(sym)

        if d and d.get("ltp") and d.get("prev_close"):
            m = compute_metrics(d)
            # Sort by institutional strength in descending order
            strength_score = compute_strength_score(d, m)
            m["strength_score"] = strength_score
            results.append((strength_score, d, m))

        time.sleep(0.08)

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

        orb_class = f"badge-{m['orb_status'].lower()}"
        orb_display = f'<span class="badge {orb_class}">{m["orb_status"]}</span>'

        sig_class = "badge-sig-bull" if "BREAKOUT" in m["signal"] or "ABOVE" in m["signal"] else "badge-sig"
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
        background: transparent;
        border: none;
        color: #787b86;
        font-size: 16px;
        cursor: pointer;
        padding: 2px 6px;
        line-height: 1;
    }}
    .popup-close:hover {{ color: #fff; }}
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
            <div style="display:flex; align-items:center; gap:8px;">
                <span id="popup-title" style="font-weight:bold; color:#2962ff; font-size:13px;">📈 Symbol (3m Dynamic ORB)</span>
                <!-- Timeframe Selector (3m vs Daily D) -->
                <div class="tf-selector">
                    <button id="tf-btn-3m" class="tf-btn active" onclick="switchTimeframe('3m')">3m</button>
                    <button id="tf-btn-d" class="tf-btn" onclick="switchTimeframe('D')">D</button>
                </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
                <span id="popup-badges" style="display:inline-flex; gap:4px; font-size:11px;"></span>
                <a id="popup-app-link" href="#" target="_blank" class="popup-btn-app" title="Launch native TradingView App">🚀 Open in TV App ↗</a>
                <button class="popup-close" onclick="hideChartPopup()">✕</button>
            </div>
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

        // Candlesticks
        const n = candles.length;
        const barSpacing = plotW / Math.max(n, 1);
        const barWidth = Math.max(Math.min(barSpacing * 0.75, 12), 2);

        let hoveredCandle = null;

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

            ctx.strokeStyle = col;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(cx, hY);
            ctx.lineTo(cx, lY);
            ctx.stroke();

            ctx.fillStyle = col;
            const bodyTop = Math.min(oY, cY);
            const bodyHeight = Math.max(Math.abs(cY - oY), 1.5);
            ctx.fillRect(cx - barWidth / 2, bodyTop, barWidth, bodyHeight);

            const step = Math.max(Math.floor(n / 6), 1);
            if (i === 0 || i === n - 1 || (i % step === 0)) {{
                ctx.fillStyle = "#787b86";
                ctx.font = "9px monospace";
                ctx.textAlign = "center";
                ctx.fillText(c.t, cx, H - 7);
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


def sync_file_to_github_api(gh_cfg, path, commit_msg):
    """Commits and pushes a file to GitHub repository using REST API (zero git CLI required on tablet)."""
    if not gh_cfg or not gh_cfg.get("token") or not os.path.isfile(path):
        return False
    try:
        import base64
        token = gh_cfg["token"].strip()
        owner = gh_cfg.get("username", "sanIncredible").strip()
        repo = gh_cfg.get("repo", "Jarvis").strip()
        branch = gh_cfg.get("branch", "main").strip()

        # Check existing sha to update or create
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        sha = None
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Python-Tablet-Scanner",
            "Accept": "application/vnd.github+json"
        })
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                sha = json.loads(resp.read().decode()).get("sha")
        except Exception:
            pass

        with open(path, "rb") as f:
            content_bytes = f.read()

        payload = {
            "message": commit_msg,
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "branch": branch
        }
        if sha:
            payload["sha"] = sha

        put_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        data = json.dumps(payload).encode("utf-8")
        put_req = urllib.request.Request(put_url, data=data, method="PUT", headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Python-Tablet-Scanner",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(put_req, timeout=12) as resp:
            return True
    except Exception:
        return False


def trigger_git_push_async():
    """Spawns a background thread to commit and push data.json via GitHub API or Git CLI."""
    gh_cfg = load_github_config()
    should_push = (gh_cfg and gh_cfg.get("auto_push")) or os.environ.get("AUTO_GIT_PUSH", "0") == "1" or os.path.isdir(".git")
    if not should_push:
        return

    def _worker():
        # 1. Try direct GitHub REST API sync (Zero git client required on tablet!)
        if gh_cfg and gh_cfg.get("token"):
            if os.path.isfile("index.html"):
                sync_file_to_github_api(gh_cfg, "index.html", "Init static dashboard shell index.html")
            now_t = get_ist_now().strftime("%H:%M:%S IST")
            pushed_api = sync_file_to_github_api(gh_cfg, "data.json", f"sync data.json {now_t}")
            if pushed_api:
                return

        # 2. Fallback to CLI git if installed
        try:
            if os.path.isdir(".git"):
                # If remote is not configured with token, embed token if available
                if gh_cfg and gh_cfg.get("token"):
                    tok = gh_cfg["token"].strip()
                    owner = gh_cfg.get("username", "sanIncredible").strip()
                    repo = gh_cfg.get("repo", "Jarvis").strip()
                    os.system(f'git remote set-url origin https://x-access-token:{tok}@github.com/{owner}/{repo}.git')
                os.system('git add data.json && git commit -m "sync data.json" && git push')
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def export_static_html(results, now_str, port):
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
                "chg_pct": round(m["chg_pct"], 2) if m.get("chg_pct") is not None else None,
                "pdh": d.get("pdh"),
                "pdh_broken": bool(m.get("pdh_broken", False)),
                "orb_high": d.get("orb_high"),
                "orb_low": d.get("orb_low"),
                "high_bar_num": d.get("high_bar_num"),
                "low_bar_num": d.get("low_bar_num"),
                "orb_status": m.get("orb_status"),
                "is_ss": bool(d.get("is_strong_start", False)),
                "rvol": round(d["rvol"], 2) if d.get("rvol") is not None else None,
                "signal": m.get("signal"),
                "strength_score": round(score, 1),
                "tag": m.get("tag"),
                "h_pct": round(m["h_pct"], 1) if m.get("h_pct") is not None else None,
                "l_pct": round(m["l_pct"], 1) if m.get("l_pct") is not None else None,
                "sma50": round(d["sma50"], 2) if d.get("sma50") is not None else None,
                "atr14": round(d["atr14"], 2) if d.get("atr14") is not None else None,
                "candles_3m": compact_3m,
                "candles_d": compact_d
            }
            stocks_payload.append(stk_data)

        payload = {
            "updated_at": now_str,
            "source": source_label,
            "stocks": stocks_payload
        }

        # 1. Write compact data.json in current directory
        json_content = json.dumps(payload, separators=(',', ':'))
        with open("data.json", "w", encoding="utf-8") as f:
            f.write(json_content)

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

        # 4. Trigger async git push
        trigger_git_push_async()
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

    if now < t_914:
        return 'WARMUP_914', t_914, max(1.0, (t_914 - now).total_seconds())
    elif now < t_915:
        return 'MARKET_OPEN_915', t_915, max(1.0, (t_915 - now).total_seconds())
    elif now < t_1530:
        t_918 = now.replace(hour=9, minute=18, second=2, microsecond=0)
        if now < t_918:
            return 'CANDLE_CLOSE_3M', t_918, max(1.0, (t_918 - now).total_seconds())

        wait_secs, target_dt = get_next_candle_target(now=now, buffer_seconds=2)
        if target_dt > t_1530:
            target_dt = t_1530.replace(second=2)
            wait_secs = max(1.0, (target_dt - now).total_seconds())
        return 'CANDLE_CLOSE_3M', target_dt, wait_secs
    else:
        nxt_914 = get_next_trading_day_914(now)
        return 'EOD_SLEEP', nxt_914, max(1.0, (nxt_914 - now).total_seconds())


def live_terminal_timer():
    """Continuously prints live ticking countdown aligned to the current market lifecycle."""
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
                    else:
                        prompt_txt = f"\r\033[K[🏁 Market Closed | Next Session in {h:02d}h {m:02d}m] 👉 Enter # (1-16) or 'r': "

                    sys.stdout.write(prompt_txt)
                    sys.stdout.flush()
                except Exception:
                    pass
        time.sleep(1)


def get_next_candle_target(now=None, buffer_seconds=2):
    """Calculates exact timestamp for next 3m candle close (e.g. 09:18:02, 09:21:02, 09:24:02)."""
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


def run_upstox_scanner(once=False, auto_open_web=False):
    """Main dashboard execution loop with market session state machine."""
    global latest_results, last_scan_time, active_web_port, next_refresh_timestamp, current_market_event

    # Start background web server (for 1-tap browser view)
    server_thread = threading.Thread(target=start_web_server, daemon=True)
    server_thread.start()
    server_ready_event.wait(timeout=1.5)

    # Initial baseline scan (so table is populated immediately)
    now_dt = get_ist_now()
    now_str = now_dt.strftime('%H:%M:%S IST')
    results = scan_watchlist()

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
    def periodic_scanner():
        global latest_results, last_scan_time, next_refresh_timestamp, current_market_event
        while not stop_scanner_event.is_set():
            now = get_ist_now()
            evt, target, wait = get_next_market_event(now)
            current_market_event = evt
            next_refresh_timestamp = time.time() + wait

            # Sleep until target event
            while wait > 0 and not stop_scanner_event.is_set():
                time.sleep(min(1.0, wait))
                wait = (target - get_ist_now()).total_seconds()

            if stop_scanner_event.is_set():
                break

            # Target reached: perform scan / warmup
            new_res = scan_watchlist()
            cur_time = get_ist_now().strftime('%H:%M:%S IST')

            # Determine next target event
            nxt_now = get_ist_now()
            nxt_evt, nxt_target, nxt_wait = get_next_market_event(nxt_now)
            current_market_event = nxt_evt
            next_refresh_timestamp = time.time() + nxt_wait
            next_str = nxt_target.strftime('%H:%M:%S IST')

            with data_lock:
                latest_results = new_res
                last_scan_time = cur_time

            export_static_html(new_res, cur_time, active_web_port)

            clear_screen()
            print_terminal_view(new_res, cur_time, active_web_port, next_str)

    scanner_thread = threading.Thread(target=periodic_scanner, daemon=True)
    scanner_thread.start()

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
