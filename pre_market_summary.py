#!/usr/bin/env python3
"""
⚡ JARVIS PRE-OPEN SITUATIONAL AWARENESS ENGINE
=============================================================================
Automated 09:14 AM IST Pre-Market Pulse & Index Relative Strength Dispatcher.
- Evaluates Top 10 Indian Indices (Benchmark Market Cap + Key Sectorals).
- Calculates Relative Strength, Market Breadth (Adv/Dec), and Pre-Open Bias.
- Dual-Mode Feed: Upstox API v2 Live Quotes + Yahoo Finance Instant Fallback.
- Pre-Open Indicative Price & Gap Discovery from NSE India.
- Dispatches Executive Situational Awareness Card to Telegram at 09:14 AM IST.
- Scheduled Mon-Fri via OCI Cloud VM Cron and Scanner Engine Daemon.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

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


def fetch_yahoo_index_quote(yahoo_sym: str) -> Optional[Dict[str, Any]]:
    """Fetches quote data for an index from Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            ltp = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if ltp is not None and prev is not None:
                chg = round(ltp - prev, 2)
                chg_pct = round((chg / prev) * 100.0, 2) if prev > 0 else 0.0
                return {
                    "ltp": float(ltp),
                    "prev_close": float(prev),
                    "change": chg,
                    "change_pct": chg_pct,
                    "source": "Yahoo Finance"
                }
    except Exception:
        pass
    return None


def fetch_upstox_indices_quotes(token: str) -> Dict[str, Dict[str, Any]]:
    """Fetches batch quote data for all target indices from Upstox API v2."""
    if not token:
        return {}
    key_to_name = {k: name for name, _, k, _ in TARGET_INDICES}
    keys_str = ",".join([k for _, _, k, _ in TARGET_INDICES])
    encoded_keys = urllib.parse.quote(keys_str)
    url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded_keys}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Jarvis-PreMarket"
    }
    req = urllib.request.Request(url, headers=headers)
    out = {}
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            d_map = data.get("data", {})
            for key, name in key_to_name.items():
                raw_k = key.replace("|", ":")
                if raw_k in d_map:
                    item = d_map[raw_k]
                    ltp = item.get("last_price")
                    ohlc = item.get("ohlc", {})
                    prev = ohlc.get("close") or ltp
                    if ltp is not None and prev is not None:
                        chg = round(float(ltp) - float(prev), 2)
                        chg_pct = round((chg / float(prev)) * 100.0, 2) if prev > 0 else 0.0
                        out[name] = {
                            "ltp": float(ltp),
                            "prev_close": float(prev),
                            "change": chg,
                            "change_pct": chg_pct,
                            "source": "Upstox Pro API"
                        }
    except Exception:
        pass
    return out


def fetch_nse_preopen_nifty() -> Optional[Dict[str, Any]]:
    """Fetches settled pre-open Nifty 50 indicative discovery from NSE India."""
    url = "https://www.nseindia.com/api/market-data-pre-open?key=NIFTY"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req_cookie = urllib.request.Request("https://www.nseindia.com", headers=headers)
        with urllib.request.urlopen(req_cookie, timeout=4) as resp1:
            cookies = resp1.headers.get_all("Set-Cookie")
            cookie_str = "; ".join([c.split(";")[0] for c in cookies]) if cookies else ""
        if cookie_str:
            headers["Cookie"] = cookie_str
        req2 = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req2, timeout=4) as resp2:
            data = json.loads(resp2.read().decode("utf-8"))
            adv = data.get("advances", 0)
            dec = data.get("declines", 0)
            unc = data.get("unchanged", 0)
            return {"advances": adv, "declines": dec, "unchanged": unc}
    except Exception:
        pass
    return None


def get_watchlist_count() -> int:
    """Reads total active symbols loaded in watchlist.txt."""
    if not WATCHLIST_FILE.is_file():
        return 0
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            syms = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            return len(syms)
    except Exception:
        return 0


def compile_pre_market_summary() -> Tuple[Dict[str, Any], str]:
    """
    Compiles situational awareness data and builds rich Telegram HTML alert message.
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
    nifty_chg_pts = nifty50["change"] if nifty50 else 0.0
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

    now_dt = datetime.now()
    now_str = now_dt.strftime("%d %b %Y | %H:%M IST")

    # 6. Build Rich HTML Telegram Message
    lines = [
        f"⚡ <b>JARVIS PRE-OPEN SITUATIONAL AWARENESS</b>",
        f"📅 <code>{now_str}</code> (Pre-Market Pulse)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>Indicative Bias:</b> {bias_label}",
        f"📊 <b>Top 10 Indices Breadth:</b> 🟢 {advances} Adv | 🔴 {declines} Dec" + (f" | ⚪ {unchanged} Flat" if unchanged else ""),
    ]

    if preopen_data and preopen_data.get("advances") is not None and (preopen_data["advances"] + preopen_data["declines"]) > 0:
        lines.append(f"🏛 <b>Nifty 50 Pre-Open Fills:</b> 🟢 {preopen_data['advances']} Adv | 🔴 {preopen_data['declines']} Dec")

    lines.append("")
    lines.append("🏛 <b>BENCHMARK & MARKET CAP INDICES:</b>")
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
    if top_sector and worst_sector:
        lines.append(f"• <b>Rotation:</b> Focus intraday long candidates in <b>{top_sector['name']}</b> ({top_sector['change_pct']:+.2f}%). Avoid laggards in <b>{worst_sector['name']}</b>.")
    lines.append(f"• <b>Game Plan:</b> {bias_advice}")
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
        "sectorals": sectorals
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

    print("🔍 Fetching market indices & relative strength data...")
    summary, msg_html = compile_pre_market_summary()

    # Print summary to terminal
    print(f"\n📊 Indicative Bias: {summary['bias']}")
    print(f"📈 Top 10 Indices Breadth: {summary['advances']} Advancers | {summary['declines']} Decliners")
    if summary["top_sector"]:
        print(f"🚀 Leading Sector : {summary['top_sector']}")
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
