#!/usr/bin/env python3
"""
⚡ JARVIS EOD SWING CANDIDATE SCANNER — NARROW RANGE COIL ENGINE
=============================================================================
Pradeep Bonde / Stockbee Narrow Range & Compression Pre-Breakout Screener.
Identifies stocks setting up for tomorrow's 3-Minute ORB + PDH Breakout:
1. Narrow Range Day : Daily Range (High - Low) <= 1.85% (Volatility Contraction).
2. Coiled at Top    : Price closing in the upper half of today's bar (>= 0.55).
3. Sits at PDH Pivot: Distance from Day High <= 0.65% (Poised to break PDH tomorrow).
4. Not Extended     : Change % between -1.0% and +2.2% (Not chasing +8% extended moves!).
5. Institutional Liq: Minimum ₹5 Crore daily turnover on NSE Equity.

Saves clean ranked setups to 'candidates.txt' with metadata for manual review.
DOES NOT touch 'watchlist.txt' — user reviews charts and promotes via 1-tap Telegram buttons!
"""

import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
NIFTY500_FILE = BASE_DIR / "nifty500_constituents.json"
CANDIDATES_FILE = BASE_DIR / "candidates.txt"
CANDIDATES_JSON = BASE_DIR / "candidates.json"

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now():
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def load_config():
    if not CONFIG_FILE.is_file():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_nifty500_constituents():
    if not NIFTY500_FILE.is_file():
        return []
    with open(NIFTY500_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def scan_nifty500_candidates(top_n=20, max_range_pct=1.85, max_from_high_pct=0.65, min_turnover_cr=5.0):
    """
    Scans Nifty 500 for unextended, narrow range coil setups poised for tomorrow's ORB + PDH breakout.
    """
    cfg = load_config()
    token = cfg.get("upstox", {}).get("access_token", "").strip()
    if not token:
        return {"status": "error", "message": "Upstox access token missing in config_credentials.json"}

    constituents = load_nifty500_constituents()
    if not constituents:
        return {"status": "error", "message": "nifty500_constituents.json not found"}

    isin_to_meta = {f"NSE_EQ|{c['isin']}": c for c in constituents if c.get("isin")}
    keys = list(isin_to_meta.keys())

    chunk_size = 100
    chunks = [keys[i:i + chunk_size] for i in range(0, len(keys), chunk_size)]

    all_quotes = {}
    for chunk in chunks:
        keys_param = ",".join(chunk)
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={keys_param}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Jarvis-Candidate-Scanner"
        })
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                all_quotes.update(data.get("data", {}))
        except Exception:
            pass

    coils = []
    for key, q in all_quotes.items():
        ltp = float(q.get("last_price", 0) or 0)
        vol = float(q.get("volume", 0) or 0)
        net_change = float(q.get("net_change", 0) or 0)
        ohlc = q.get("ohlc", {})
        high = float(ohlc.get("high", 0) or 0)
        low = float(ohlc.get("low", 0) or 0)
        op = float(ohlc.get("open", 0) or 0)

        pc = round(ltp - net_change, 2)
        if ltp <= 50 or pc <= 0 or high <= 0 or low <= 0 or vol <= 0 or high <= low:
            continue

        turnover_cr = round((vol * ltp) / 10000000.0, 2)
        if turnover_cr < min_turnover_cr:
            continue

        daily_range_pct = round(((high - low) / pc) * 100.0, 2)
        change_pct = round((net_change / pc) * 100.0, 2)
        bar_range = high - low
        close_loc = round((ltp - low) / bar_range, 2) if bar_range > 0 else 0.5
        dist_from_high_pct = round(((high - ltp) / high) * 100.0, 2)

        # STRICT NARROW RANGE & COIL CRITERIA (NON-EXTENDED):
        # 1. Range contraction: daily_range_pct <= max_range_pct
        # 2. Not extended / exhausted: -1.0% <= change_pct <= +2.2%
        # 3. Closing in upper half of bar: close_loc >= 0.55
        # 4. Right at the doorstep of PDH: dist_from_high_pct <= max_from_high_pct
        if daily_range_pct <= max_range_pct and (-1.0 <= change_pct <= 2.2) and close_loc >= 0.55 and dist_from_high_pct <= max_from_high_pct:
            raw_sym = q.get("symbol", "").replace("NSE_EQ:", "").strip()
            sym = isin_to_meta.get(key, {}).get("symbol", raw_sym)
            name = isin_to_meta.get(key, {}).get("name", sym)
            industry = isin_to_meta.get(key, {}).get("industry", "Equity")

            # Scoring:
            # - Tighter range = higher compression score
            # - Close at the very top of bar = higher buying pressure
            # - Sits right on High = immediate breakout ignition potential
            score = 60.0
            score += max(0.0, (max_range_pct - daily_range_pct) * 20.0)
            score += (close_loc * 20.0)
            score += max(0.0, (max_from_high_pct - dist_from_high_pct) * 15.0)
            if turnover_cr >= 25.0:
                score += 10.0
            elif turnover_cr >= 10.0:
                score += 5.0

            coil_tag = "PRIME COIL" if daily_range_pct <= 1.20 else "NARROW CONSOLIDATION"

            coils.append({
                "symbol": sym,
                "name": name,
                "industry": industry,
                "ltp": ltp,
                "daily_range_pct": daily_range_pct,
                "change_pct": change_pct,
                "dist_from_high_pct": dist_from_high_pct,
                "close_loc": close_loc,
                "turnover_cr": turnover_cr,
                "score": round(score, 1),
                "coil_tag": coil_tag,
                "day_high": high,
                "day_low": low,
                "day_open": op,
                "prev_close": pc
            })

    coils.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = coils[:top_n]

    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    lines = [
        f"# JARVIS PRE-BREAKOUT SWING CANDIDATES (NIFTY 500) — {now_str}",
        f"# Setup: Narrow Range Coil (Range ≤ {max_range_pct}%, Sitting ≤ {max_from_high_pct}% from High, Min ₹{min_turnover_cr} Cr)",
        "# Strategy: Tomorrow's 3m ORB + PDH Breakout with Day Low SL (NOT Extended!)",
        "# Review on TradingView and tap button or use `/add <SYMBOL>` in Telegram to promote to watchlist.txt",
        "# ==========================================================================================",
        ""
    ]
    for c in top_candidates:
        lines.append(
            f"{c['symbol']}  # ₹{c['ltp']:,.2f} | Range: {c['daily_range_pct']:.2f}% | Today: {c['change_pct']:+.1f}% | "
            f"Pivot Dist: {c['dist_from_high_pct']:.2f}% | Close Top: {int(c['close_loc']*100)}% | ₹{c['turnover_cr']:,.1f} Cr | {c['coil_tag']} | {c['industry']}"
        )

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    with open(CANDIDATES_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": now_str,
            "count": len(top_candidates),
            "strategy": "3m ORB + PDH Pre-Breakout Narrow Coil",
            "candidates": top_candidates
        }, f, indent=2)

    return {
        "status": "success",
        "updated_at": now_str,
        "count": len(top_candidates),
        "total_scanned": len(all_quotes),
        "candidates": top_candidates
    }


def format_candidates_telegram_card(res, max_display=10):
    """
    Formats rich Telegram review card showing tightness, narrow range %, and 1-tap Add buttons.
    """
    if res.get("status") != "success":
        return f"⚠️ <b>Candidate Scan Notice:</b> {res.get('message', 'Scan failed')}", None

    candidates = res.get("candidates", [])
    if not candidates:
        return "ℹ️ <b>No stocks met today's Narrow Range Coil threshold (≤1.8% range & close at high).</b>", None

    now_str = res.get("updated_at", get_ist_now().strftime("%H:%M:%S IST"))

    lines = [
        "🎯 <b>NIFTY 500 PRE-BREAKOUT COIL CANDIDATES</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<i>Narrow Range Day setups for tomorrow's 3m ORB + PDH breakout</i>\n"
    ]

    for i, c in enumerate(candidates[:max_display], 1):
        sym = c["symbol"]
        tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
        icon = "🟢" if c["daily_range_pct"] <= 1.20 else "⚪"
        lines.append(
            f"<b>{i}.</b> {icon} {tv_link} (₹{c['ltp']:,.2f})\n"
            f"   • Range: <b>{c['daily_range_pct']:.2f}%</b> (Tight!) | Move: {c['change_pct']:+.1f}%\n"
            f"   • Sits: <b>{c['dist_from_high_pct']:.2f}%</b> from High (PDH Pivot)\n"
            f"   • Close: <b>{int(c['close_loc']*100)}%</b> of bar | ₹{c['turnover_cr']:,.1f} Cr ({c['industry']})"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Unextended stocks! Tap below to add vetted candidates to tomorrow's 3m scanner:</i>")

    kb_rows = []
    btn_row = []
    for c in candidates[:max_display]:
        sym = c["symbol"]
        btn_row.append({"text": f"➕ Add {sym}", "callback_data": f"cand_add:{sym}"})
        if len(btn_row) == 2:
            kb_rows.append(btn_row)
            btn_row = []
    if btn_row:
        kb_rows.append(btn_row)

    kb_rows.append([
        {"text": "🔄 Rescan Candidates", "callback_data": "cand_refresh"},
        {"text": "📋 View Live Watchlist", "callback_data": "wl_show"}
    ])

    return "\n".join(lines), {"inline_keyboard": kb_rows}


if __name__ == "__main__":
    print("=" * 70)
    print("⚡ SCANNING NIFTY 500 NARROW RANGE COIL SETUPS (PRE-BREAKOUT)...")
    print("=" * 70)
    res = scan_nifty500_candidates()
    if res.get("status") == "success":
        print(f"✅ Filtered {res['count']} Narrow Range Coils from {res['total_scanned']} stocks!")
        print(f"📁 Saved to: {CANDIDATES_FILE.name}")
        for i, c in enumerate(res["candidates"], 1):
            print(f"{i:<2}. {c['symbol']:<12} ₹{c['ltp']:<9.2f} | Range: {c['daily_range_pct']:.2f}% | Move: {c['change_pct']:+5.1f}% | Dist: {c['dist_from_high_pct']:.2f}% | ₹{c['turnover_cr']:<6.1f} Cr | {c['coil_tag']}")
    else:
        print(f"❌ Error: {res.get('message')}")
