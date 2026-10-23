#!/usr/bin/env python3
"""
⚡ JARVIS PRE-OPEN SITUATIONAL AWARENESS ENGINE
=============================================================================
Automated 09:14 AM IST Pre-Market Pulse, Index RS & Stockbee Breadth Dispatcher.
- Evaluates Top 10 Indian Indices (Benchmark Market Cap + Key Sectorals).
- Ingests Chhirag Kedia's Market Breadth V2.0 (Stockbee / Pradeep Bonde SA Model).
- Dispatches Last Day Row Metrics (5D/10D ratios, 4% Thrust, NH-NL, BO Quality).
- Calculates Relative Strength, Market Breadth (Adv/Dec), and Pre-Open Bias.
- Dual-Mode Feed: Upstox API v2 Live Quotes + Yahoo Finance Instant Fallback.
- Pre-Open Indicative Price & Gap Discovery from NSE India.
- Dispatches Executive Situational Awareness Card to Telegram at 09:14 AM IST.
- Scheduled Mon-Fri via OCI Cloud VM Cron and Scanner Engine Daemon.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import requests
import openpyxl

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
BREADTH_WORKBOOK = BASE_DIR / "Market Breadth V2.0.xlsm"
ONEDRIVE_BREADTH_URL = "https://1drv.ms/x/c/b79afba86bb67443/UAFDdLZrqPuaIIC3KrAAAAAAAPhaElrsP5AP06s?download=1"

# Top 10 Indian Indices (Market Cap Benchmarks & Core Sectoral Engines)
TARGET_INDICES = [
    # (Display Name, Category, Upstox Instrument Key, Yahoo Finance Symbol)
    ("Nifty 50", "Benchmark", "NSE_INDEX|Nifty 50", "^NSEI"),
    ("Nifty Bank", "Benchmark", "NSE_INDEX|Nifty Bank", "^NSEBANK"),
    ("Nifty Midcap 100", "Market Cap", "NSE_INDEX|NIFTY MIDCAP 100", "^CRSLDX"),
    ("Nifty IT", "Sectoral", "NSE_INDEX|Nifty IT", "^CNXIT"),
    ("Nifty Auto", "Sectoral", "NSE_INDEX|Nifty Auto", "^CNXAUTO"),
    ("Nifty Pharma", "Sectoral", "NSE_INDEX|Nifty Pharma", "^CNXPHARMA"),
    ("Nifty Metal", "Sectoral", "NSE_INDEX|Nifty Metal", "^CNXMETAL"),
    ("Nifty FMCG", "Sectoral", "NSE_INDEX|Nifty FMCG", "^CNXFMCG"),
    ("Nifty Realty", "Sectoral", "NSE_INDEX|Nifty Realty", "^CNXREALTY"),
    ("Nifty Energy", "Sectoral", "NSE_INDEX|Nifty Energy", "^CNXENERGY"),
]

# Standard Indian Market Holidays 2026 (YYYY-MM-DD)
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-20",  # Id-Ul-Fitr
    "2026-03-27",  # Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-27",  # Bakri Id
    "2026-08-15",  # Independence Day
    "2026-09-04",  # Janmashtami
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-08",  # Diwali Laxmi Pujan
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-24",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}


def load_config() -> Dict[str, Any]:
    """Loads credentials from config_credentials.json."""
    if not CONFIG_FILE.is_file():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error reading {CONFIG_FILE.name}: {e}")
        return {}


def is_market_day(dt: Optional[datetime] = None) -> bool:
    """Returns True if today is a regular NSE trading day (Mon-Fri, non-holiday)."""
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    iso_date = dt.strftime("%Y-%m-%d")
    if iso_date in NSE_HOLIDAYS_2026:
        return False
    return True


def sync_market_breadth_from_onedrive(dest_file: Path, max_age_hours: int = 4) -> bool:
    """
    Downloads the latest Market Breadth V2.0.xlsm from OneDrive if local copy is older than max_age_hours.
    Falls back gracefully to existing local file if network fails.
    """
    if dest_file.is_file():
        file_age = time.time() - os.path.getmtime(dest_file)
        if file_age < max_age_hours * 3600:
            print(f"ℹ️ Local breadth workbook is fresh ({file_age / 60:.1f} mins old). Skipping download.")
            return True

    print("🌐 Checking OneDrive for latest Market Breadth V2.0 updates...")
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    })

    try:
        r = s.get(ONEDRIVE_BREADTH_URL, allow_redirects=True, timeout=12)
        if r.status_code == 200 and r.content[:2] == b'PK' and len(r.content) > 1000000:
            tmp_path = dest_file.with_suffix(".tmp")
            with open(tmp_path, "wb") as f:
                f.write(r.content)
            tmp_path.replace(dest_file)
            print(f"✅ Downloaded fresh Market Breadth workbook ({len(r.content):,} bytes) from cloud.")
            return True
        else:
            print(f"⚠️ OneDrive response {r.status_code}. Using local cached workbook.")
            return dest_file.is_file()
    except Exception as e:
        print(f"⚠️ OneDrive sync notice: {e}. Using local cached workbook.")
        return dest_file.is_file()


def extract_bonde_breadth_metrics(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Parses Chhirag Kedia's Market Breadth V2.0.xlsm (Stockbee / Pradeep Bonde SA Engine).
    Extracts the exact metrics for the last day row.
    """
    if not file_path.is_file():
        print(f"⚠️ Breadth file {file_path.name} not found.")
        return None

    try:
        wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        ws_b = wb['Breadth']
        ws_m = wb['Market Map']

        last_b_row = None
        last_b_idx = None
        # Scan recent rows (rows 5500 to 7000)
        for idx, r in enumerate(ws_b.iter_rows(min_row=5500, max_row=7000, values_only=True), start=5500):
            if r[0] is not None and str(r[0]).strip() not in ('', 'None'):
                last_b_row = r
                last_b_idx = idx

        if not last_b_row:
            wb.close()
            return None

        # Fetch matching row in Market Map
        map_row = None
        for r in ws_m.iter_rows(min_row=last_b_idx, max_row=last_b_idx, values_only=True):
            map_row = r
            break

        wb.close()

        # Parse metrics safely
        date_raw = last_b_row[0]
        if hasattr(date_raw, 'strftime'):
            date_str = date_raw.strftime("%d-%b-%Y")
        else:
            date_str = str(date_raw)[:10]

        nifty_chg = float(last_b_row[1] or 0.0) * 100.0
        universe = int(last_b_row[3] or 2505)
        up_4_pct = float(last_b_row[4] or 0.0) * 100.0
        dn_4_pct = float(last_b_row[5] or 0.0) * 100.0
        up_4_cnt = int(round(up_4_pct * universe / 100.0))
        dn_4_cnt = int(round(dn_4_pct * universe / 100.0))
        net_breadth = float(last_b_row[6] or 0.0)
        ratio_5d = float(last_b_row[7] or 0.0)
        ratio_10d = float(last_b_row[8] or 0.0)
        above_vol_pct = float(last_b_row[9] or 0.0) * 100.0
        below_vol_pct = float(last_b_row[10] or 0.0) * 100.0
        vol_ratio = float(last_b_row[11] or 0.0)
        range_lt3_pct = float(last_b_row[12] or 0.0) * 100.0
        volatility = float(last_b_row[13] or 0.0)
        range_gt5_pct = float(last_b_row[14] or 0.0) * 100.0
        close_uh_pct = float(last_b_row[15] or 0.0) * 100.0
        close_lh_pct = float(last_b_row[16] or 0.0) * 100.0
        uh_lh_ratio = float(last_b_row[17] or 0.0)
        bo_sustained = float(last_b_row[21] or 0.0) * 100.0
        bo_failure = float(last_b_row[22] or 0.0) * 100.0
        bo_sf_ratio = float(last_b_row[23] or 0.0)
        bd_sustained = float(last_b_row[26] or 0.0) * 100.0
        bd_failure = float(last_b_row[27] or 0.0) * 100.0
        bd_sf_ratio = float(last_b_row[28] or 0.0)

        # Market Map metrics
        nh_pct = float(map_row[6] or 0.0) * 100.0 if map_row else 0.0
        nl_pct = float(map_row[7] or 0.0) * 100.0 if map_row else 0.0
        nh_cnt = int(round(nh_pct * universe / 100.0))
        nl_cnt = int(round(nl_pct * universe / 100.0))
        net_nh_nl = float(map_row[8] or 0.0) if map_row else 0.0
        net_15_hl = float(map_row[9] or 0.0) if map_row else 0.0
        net_30_hl = float(map_row[10] or 0.0) if map_row else 0.0

        # Determine Regime Traffic Light (Stockbee Standard)
        if ratio_5d >= 2.0 and net_breadth > 0:
            regime_code = "GREEN"
            regime_label = "🟢 GREEN LIGHT (Aggressive Momentum)"
            regime_action = "High breakout follow-through. Deploy full swing capital (100% position size)."
        elif ratio_5d >= 1.0 or (ratio_5d >= 0.8 and net_breadth >= 0):
            regime_code = "YELLOW"
            regime_label = "🟡 YELLOW LIGHT (Selective / Half Size)"
            regime_action = "Mixed momentum. Allocate 50% risk. Require 2x volume confirmation and tight stops."
        else:
            regime_code = "RED"
            regime_label = "🔴 RED LIGHT (Defensive / Cash is King)"
            regime_action = "Heavy institutional distribution. Zero fresh breakout buying. Protect capital."

        return {
            "row_idx": last_b_idx,
            "date": date_str,
            "universe": universe,
            "nifty_chg": nifty_chg,
            "up_4_cnt": up_4_cnt,
            "up_4_pct": up_4_pct,
            "dn_4_cnt": dn_4_cnt,
            "dn_4_pct": dn_4_pct,
            "net_breadth": net_breadth,
            "ratio_5d": ratio_5d,
            "ratio_10d": ratio_10d,
            "above_vol_pct": above_vol_pct,
            "below_vol_pct": below_vol_pct,
            "vol_ratio": vol_ratio,
            "range_lt3_pct": range_lt3_pct,
            "range_gt5_pct": range_gt5_pct,
            "volatility": volatility,
            "close_uh_pct": close_uh_pct,
            "close_lh_pct": close_lh_pct,
            "uh_lh_ratio": uh_lh_ratio,
            "bo_sustained": bo_sustained,
            "bo_failure": bo_failure,
            "bo_sf_ratio": bo_sf_ratio,
            "bd_sustained": bd_sustained,
            "bd_failure": bd_failure,
            "bd_sf_ratio": bd_sf_ratio,
            "nh_cnt": nh_cnt,
            "nh_pct": nh_pct,
            "nl_cnt": nl_cnt,
            "nl_pct": nl_pct,
            "net_nh_nl": net_nh_nl,
            "net_15_hl": net_15_hl,
            "net_30_hl": net_30_hl,
            "regime_code": regime_code,
            "regime_label": regime_label,
            "regime_action": regime_action
        }
    except Exception as e:
        print(f"⚠️ Error reading breadth sheet: {e}")
        return None


def fetch_yahoo_index_quote(yahoo_sym: str) -> Optional[Dict[str, Any]]:
    """Fetches quote data for an index from Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            ltp = float(meta.get("regularMarketPrice", 0.0))
            prev_close = float(meta.get("chartPreviousClose") or meta.get("previousClose") or ltp)
            change = ltp - prev_close
            change_pct = (change / prev_close * 100.0) if prev_close else 0.0
            return {
                "ltp": ltp,
                "prev_close": prev_close,
                "change": change,
                "change_pct": change_pct,
                "source": "Yahoo"
            }
    except Exception as e:
        return None


def fetch_upstox_indices_quotes(token: str) -> Dict[str, Dict[str, Any]]:
    """Fetches multi-quote index prices from Upstox API v2."""
    if not token:
        return {}

    instrument_keys = [item[2] for item in TARGET_INDICES if item[2].startswith("NSE_INDEX")]
    keys_param = urllib.parse.quote(",".join(instrument_keys), safe=",")
    url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={keys_param}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    )

    results = {}
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("status") == "success":
                data_dict = res_data.get("data", {})
                for name, cat, upstox_key, yahoo_sym in TARGET_INDICES:
                    q = data_dict.get(upstox_key)
                    if not q:
                        clean_sym = upstox_key.split("|")[-1]
                        for k, v in data_dict.items():
                            if clean_sym.lower() in k.lower():
                                q = v
                                break
                    if q:
                        ltp = float(q.get("last_price", 0.0))
                        prev_close = float(q.get("ohlc", {}).get("close") or q.get("prev_close") or ltp)
                        change = float(q.get("net_change") or (ltp - prev_close))
                        change_pct = (change / prev_close * 100.0) if prev_close else 0.0
                        results[name] = {
                            "ltp": ltp,
                            "prev_close": prev_close,
                            "change": change,
                            "change_pct": change_pct,
                            "source": "Upstox"
                        }
    except Exception as e:
        print(f"⚠️ Upstox index quote batch error: {e}")

    return results


def fetch_nse_preopen_nifty() -> Optional[Dict[str, Any]]:
    """Fetches indicative pre-market data from NSE India pre-open feed if available."""
    url = "https://www.nseindia.com/api/market-data-pre-open?key=NIFTY"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
    }

    try:
        session = urllib.request.build_opener()
        # Initialize cookie session with home page
        home_req = urllib.request.Request("https://www.nseindia.com", headers=headers)
        with session.open(home_req, timeout=3) as _:
            pass

        req = urllib.request.Request(url, headers=headers)
        with session.open(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            advances = data.get("advances", 0)
            declines = data.get("declines", 0)
            unchanged = data.get("unchanged", 0)
            return {
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged
            }
    except Exception:
        return None


def get_watchlist_count() -> int:
    """Returns the number of active symbols in watchlist.txt."""
    if not WATCHLIST_FILE.is_file():
        return 0
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            symbols = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
            return len(symbols)
    except Exception:
        return 0


def compile_pre_market_summary() -> Tuple[Dict[str, Any], str]:
    """
    Compiles situational awareness data, Bonde breadth metrics, and builds rich Telegram HTML alert message.
    Returns: (summary_dict, formatted_html_message)
    """
    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()

    # 1. Fetch indices via Upstox first
    upstox_data = fetch_upstox_indices_quotes(token)

    # 2. Complete missing indices via Yahoo Finance fallback
    indices_results = []
    for name, cat, upstox_key, yahoo_sym in TARGET_INDICES:
        item = upstox_data.get(name)
        if not item:
            item = fetch_yahoo_index_quote(yahoo_sym)
        if not item:
            # Neutral default fallback if feed offline
            item = {"ltp": 0.0, "prev_close": 0.0, "change": 0.0, "change_pct": 0.0, "source": "Offline"}

        indices_results.append({
            "name": name,
            "category": cat,
            "ltp": item["ltp"],
            "prev_close": item["prev_close"],
            "change": item["change"],
            "change_pct": item["change_pct"],
            "source": item.get("source", "")
        })

    # 3. Categorize into Benchmark vs Sectorals
    benchmarks = [idx for idx in indices_results if idx["category"] in ("Benchmark", "Market Cap")]
    sectorals = [idx for idx in indices_results if idx["category"] == "Sectoral"]

    # Sort sectorals by relative strength (% change descending)
    sectorals.sort(key=lambda x: x["change_pct"], reverse=True)

    # 4. Market Breadth across Top 10 Indices
    advances = sum(1 for idx in indices_results if idx["change_pct"] > 0)
    declines = sum(1 for idx in indices_results if idx["change_pct"] < 0)
    unchanged = sum(1 for idx in indices_results if idx["change_pct"] == 0)

    # Pre-open Nifty 50 specific metrics
    nifty50 = next((idx for idx in indices_results if idx["name"] == "Nifty 50"), None)
    nifty_chg_pct = nifty50["change_pct"] if nifty50 else 0.0
    nifty_ltp = nifty50["ltp"] if nifty50 else 0.0

    # 5. Determine Indicative Market Bias
    if nifty_chg_pct >= 0.40:
        bias_label = f"🟢 Strong Bullish Gap-Up (+{nifty_chg_pct:.2f}%)"
        bias_advice = "Expect early momentum. Guard against chasing overextension; buy deep pullbacks to 10 EMA."
    elif 0.10 <= nifty_chg_pct < 0.40:
        bias_label = f"🟢 Mild Bullish Bias (+{nifty_chg_pct:.2f}%)"
        bias_advice = "Constructive opening. Watch Strong Start (SS) candidates breaking yesterday's high (PDH)."
    elif -0.10 < nifty_chg_pct < 0.10:
        bias_label = f"⚪ Flat / Neutral Open ({nifty_chg_pct:+.2f}%)"
        bias_advice = "Balanced inventory. Prime conditions for the 3-Minute ORB breakout strategy after 09:18 AM."
    elif -0.40 < nifty_chg_pct <= -0.10:
        bias_label = f"🔴 Mild Bearish Bias ({nifty_chg_pct:.2f}%)"
        bias_advice = "Defensive open. Be selective with long breakouts; demand Strong Start or strong sector backing."
    else:
        bias_label = f"🔴 Significant Gap-Down ({nifty_chg_pct:.2f}%)"
        bias_advice = "Risk-off regime. Avoid chasing opening candles. Wait for ORB anchor low stabilization."

    # Sector leaders and laggards
    top_sector = sectorals[0] if sectorals else None
    worst_sector = sectorals[-1] if sectorals else None

    # Check Nifty pre-open market breadth if available
    preopen_data = fetch_nse_preopen_nifty()
    watchlist_count = get_watchlist_count()

    # 6. Ingest Stockbee / Pradeep Bonde Market Breadth Sheet (Chhirag Kedia V2.0)
    sync_market_breadth_from_onedrive(BREADTH_WORKBOOK, max_age_hours=4)
    bonde = extract_bonde_breadth_metrics(BREADTH_WORKBOOK)

    now_dt = datetime.now()
    now_str = now_dt.strftime("%d %b %Y | %H:%M IST")

    # 7. Build Rich HTML Telegram Message
    lines = [
        f"⚡ <b>JARVIS PRE-OPEN SITUATIONAL AWARENESS</b>",
        f"📅 <code>{now_str}</code> (Pre-Market Pulse)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>Indicative Bias:</b> {bias_label}",
        f"📊 <b>Top 10 Indices Breadth:</b> 🟢 {advances} Adv | 🔴 {declines} Dec" + (f" | ⚪ {unchanged} Flat" if unchanged else ""),
    ]

    if preopen_data and preopen_data.get("advances") is not None and (preopen_data["advances"] + preopen_data["declines"]) > 0:
        lines.append(f"🏛 <b>Nifty 50 Pre-Open Fills:</b> 🟢 {preopen_data['advances']} Adv | 🔴 {preopen_data['declines']} Dec")

    # Stockbee / Pradeep Bonde Market Breadth Section
    if bonde:
        lines.append("")
        lines.append("📊 <b>CHHIRAG KEDIA'S MARKET BREADTH MONITOR</b>")
        lines.append("<i>(Stockbee / Pradeep Bonde Situational Awareness)</i>")
        lines.append(f"🚦 <b>Market Regime:</b> <b>{bonde['regime_label']}</b>")
        lines.append(f"📅 <b>Last Session:</b> <code>{bonde['date']}</code> (Row #{bonde['row_idx']} | Univ: {bonde['universe']})")
        lines.append("")
        lines.append("📋 <b>LAST DAY BREADTH ROW METRICS:</b>")
        lines.append(f"• <b>4% Thrust:</b> 🟢 {bonde['up_4_cnt']} Up ({bonde['up_4_pct']:.1f}%) | 🔴 {bonde['dn_4_cnt']} Down ({bonde['dn_4_pct']:.1f}%)")
        lines.append(f"• <b>Net 4% Breadth:</b> <code>{bonde['net_breadth']:+.2f}%</code> {'🟢 Positive' if bonde['net_breadth'] > 0 else '🔴 Negative'}")
        lines.append(f"• <b>Ratios:</b> 5-Day: <b>{bonde['ratio_5d']:.2f}</b> | 10-Day: <b>{bonde['ratio_10d']:.2f}</b>")
        lines.append(f"• <b>52W NH vs NL:</b> {bonde['nh_cnt']} Highs ({bonde['nh_pct']:.1f}%) | {bonde['nl_cnt']} Lows ({bonde['nl_pct']:.1f}%)")
        lines.append(f"• <b>Net NH-NL:</b> <code>{bonde['net_nh_nl']:+.2f}%</code> | <b>Net 15% H-L:</b> <code>{bonde['net_15_hl']:+.2f}%</code>")
        lines.append(f"• <b>Breakout Quality:</b> {bonde['bo_sustained']:.1f}% Sustained | <b>{bonde['bo_failure']:.1f}% Failed</b> (S/F: {bonde['bo_sf_ratio']:.2f})")
        lines.append(f"• <b>Breakdown Quality:</b> {bonde['bd_sustained']:.1f}% Sustained | {bonde['bd_failure']:.1f}% Failed (S/F: {bonde['bd_sf_ratio']:.2f})")
        lines.append(f"• <b>Volume Ratio:</b> {bonde['vol_ratio']:.2f} (Above: {bonde['above_vol_pct']:.1f}% | Below: {bonde['below_vol_pct']:.1f}%)")
        lines.append(f"• <b>Close UH/LH:</b> {bonde['close_uh_pct']:.1f}% Upper | {bonde['close_lh_pct']:.1f}% Lower (UH/LH: {bonde['uh_lh_ratio']:+.1f}%)")

    lines.append("")
    lines.append("🏛 <b>BENCHMARK &amp; MARKET CAP INDICES:</b>")
    for b in benchmarks:
        icon = "🟢" if b["change_pct"] > 0 else ("🔴" if b["change_pct"] < 0 else "⚪")
        sign = "+" if b["change_pct"] > 0 else ""
        lines.append(f"• <b>{b['name']}</b>: ₹{b['ltp']:,.2f} ({sign}{b['change']:,.2f} | {sign}{b['change_pct']:.2f}%) {icon}")

    lines.append("")
    lines.append("🏭 <b>SECTORAL RELATIVE STRENGTH:</b>")
    for s in sectorals:
        icon = "🟢" if s["change_pct"] > 0 else ("🔴" if s["change_pct"] < 0 else "⚪")
        sign = "+" if s["change_pct"] > 0 else ""
        tag = ""
        if s == top_sector and s["change_pct"] > 0:
            tag = " ★ <b>[Leading]</b>"
        elif s == worst_sector and s["change_pct"] < 0:
            tag = " ⚠️ <i>[Lagging]</i>"
        lines.append(f"• <b>{s['name']}</b>: {sign}{s['change_pct']:.2f}% {icon}{tag}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <b>TACTICAL PLAYBOOK (09:15 AM BELL):</b>")

    # Integrate Bonde Regime with Tactical Playbook
    if bonde and bonde.get("regime_code") == "RED":
        lines.append("• <b>Bonde Regime:</b> 🔴 <b>DEFENSIVE / CASH IS KING.</b> 5D Ratio &lt; 1.0 &amp; Net Breadth negative. Strictly avoid chasing morning gap-up breakouts.")
    elif bonde and bonde.get("regime_code") == "YELLOW":
        lines.append("• <b>Bonde Regime:</b> 🟡 <b>SELECTIVE / HALF-SIZE.</b> Allocate 50% normal risk. Require 2x volume confirmation on breakout entries.")
    elif bonde and bonde.get("regime_code") == "GREEN":
        lines.append("• <b>Bonde Regime:</b> 🟢 <b>AGGRESSIVE MOMENTUM.</b> Market tide favorable. Deploy full 100% position sizing on A+ setups.")

    if top_sector and worst_sector:
        lines.append(f"• <b>Rotation:</b> Focus intraday long candidates in <b>{top_sector['name']}</b> ({top_sector['change_pct']:+.2f}%). Avoid laggards in <b>{worst_sector['name']}</b>.")
    lines.append(f"• <b>Index Guidance:</b> {bias_advice}")
    lines.append(f"• <b>Scanner Status:</b> 🟢 Ready ({watchlist_count} stocks loaded for 3m ORB). First candle completes at <b>09:18 AM</b>.")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 <a href='https://sanincredible.github.io/Jarvis/'>Open Live 3M Terminal Dashboard</a>")

    msg_html = "\n".join(lines)

    summary_data = {
        "timestamp": now_str,
        "bias": bias_label,
        "nifty_ltp": nifty_ltp,
        "nifty_chg_pct": nifty_chg_pct,
        "advances": advances,
        "declines": declines,
        "top_sector": top_sector["name"] if top_sector else None,
        "worst_sector": worst_sector["name"] if worst_sector else None,
        "benchmarks": benchmarks,
        "sectorals": sectorals,
        "bonde_breadth": bonde
    }

    return summary_data, msg_html


def send_telegram_alert(msg_html: str, config: Dict[str, Any]) -> Tuple[bool, str]:
    """Dispatches the pre-market summary to Telegram chat."""
    tg_cfg = config.get("telegram", {})
    if not tg_cfg.get("enabled", True):
        return False, "Telegram disabled in config"

    bot_token = tg_cfg.get("bot_token", "").strip()
    chat_id = tg_cfg.get("chat_id", "").strip()
    if not bot_token or not chat_id:
        return False, "Bot token or chat ID missing in config"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("ok"):
                return True, "Delivered"
            return False, str(res_data)
    except Exception as e:
        return False, str(e)


def main():
    force_run = "--force" in sys.argv or "--test" in sys.argv
    now_dt = datetime.now()

    print("=" * 65)
    print(f"⚡ JARVIS 09:14 AM PRE-OPEN SITUATIONAL AWARENESS")
    print(f"⏰ Execution Time: {now_dt.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 65)

    # Check if market day (skip weekends and NSE holidays unless force flag provided)
    if not is_market_day(now_dt) and not force_run:
        print(f"ℹ️ Today ({now_dt.strftime('%A, %d %b %Y')}) is a Weekend or NSE Trading Holiday.")
        print("   Skipping pre-market summary dispatch. Use --test or --force to override.")
        sys.exit(0)

    print("🔍 Fetching market indices & Stockbee breadth data...")
    summary, msg_html = compile_pre_market_summary()

    # Print summary to terminal
    print(f"\n📊 Indicative Bias: {summary['bias']}")
    print(f"📈 Top 10 Indices Breadth: {summary['advances']} Advancers | {summary['declines']} Decliners")

    bonde = summary.get("bonde_breadth")
    if bonde:
        print(f"\n🚦 Stockbee Regime : {bonde['regime_label']}")
        print(f"📋 Last Breadth Row: {bonde['date']} (Row #{bonde['row_idx']})")
        print(f"   • 4% Thrust     : {bonde['up_4_cnt']} Up ({bonde['up_4_pct']:.1f}%) | {bonde['dn_4_cnt']} Down ({bonde['dn_4_pct']:.1f}%)")
        print(f"   • Net 4% Breadth: {bonde['net_breadth']:+.2f}%")
        print(f"   • 5D / 10D Ratio: {bonde['ratio_5d']:.2f} / {bonde['ratio_10d']:.2f}")
        print(f"   • 52W NH / NL   : {bonde['nh_cnt']} Highs | {bonde['nl_cnt']} Lows (Net: {bonde['net_nh_nl']:+.2f}%)")
        print(f"   • BO Failure %  : {bonde['bo_failure']:.1f}%")

    if summary["top_sector"]:
        print(f"\n🚀 Leading Sector : {summary['top_sector']}")
    if summary["worst_sector"]:
        print(f"🔻 Lagging Sector: {summary['worst_sector']}")

    print("\n🏛 Benchmarks:")
    for b in summary["benchmarks"]:
        print(f"  • {b['name']:18}: ₹{b['ltp']:>10,.2f} ({b['change_pct']:>+6.2f}%) [{b['source']}]")

    print("\n🏭 Sectoral Relative Strength (Ranked):")
    for s in summary["sectorals"]:
        print(f"  • {s['name']:18}: {s['change_pct']:>+6.2f}% [{s['source']}]")

    print("-" * 65)
    print("📱 Dispatching Pre-Open Alert to Telegram...")
    cfg = load_config()
    ok, err = send_telegram_alert(msg_html, cfg)
    if ok:
        print("✅ Telegram Pre-Open Situational Awareness Card delivered successfully!")
    else:
        print(f"❌ Telegram dispatch notice: {err}")

    print("=" * 65)


if __name__ == "__main__":
    main()
