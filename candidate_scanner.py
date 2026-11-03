#!/usr/bin/env python3
"""
⚡ JARVIS EOD SWING CANDIDATE SCANNER (NIFTY 500)
=================================================
Scans the liquid Nifty 500 universe using Upstox Pro batch quote API.
Identifies institutional momentum setups based on Pradeep Bonde / Stockbee criteria:
1. Turnover Filter  : Minimum ₹5 Crore daily turnover (no illiquid traps).
2. Thrust Expansion : Gain of +1.5% to +12.0%.
3. Closes near High : Price within 2.0% of Day High (buying into close).
4. Strong Start     : Opened > Prev Close and held above low buffer.

Saves clean filtered tickers to 'candidates.txt' with metadata for manual review.
DOES NOT touch 'watchlist.txt' — user reviews and adds manually or via Telegram buttons!
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


def scan_nifty500_candidates(top_n=20, min_turnover_cr=5.0, min_gain_pct=1.5, max_gain_pct=12.0, max_from_high_pct=2.0):
    """
    Queries Upstox batch quotes for Nifty 500 and returns ranked candidates.
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

    candidates = []
    for key, q in all_quotes.items():
        ltp = float(q.get("last_price", 0) or 0)
        vol = float(q.get("volume", 0) or 0)
        net_change = float(q.get("net_change", 0) or 0)
        ohlc = q.get("ohlc", {})
        high = float(ohlc.get("high", 0) or 0)
        low = float(ohlc.get("low", 0) or 0)
        op = float(ohlc.get("open", 0) or 0)

        pc = round(ltp - net_change, 2)
        if ltp <= 20 or pc <= 0 or high <= 0 or vol <= 0:
            continue

        turnover_cr = round((vol * ltp) / 10000000.0, 2)
        if turnover_cr < min_turnover_cr:
            continue

        gain_pct = round((net_change / pc) * 100.0, 2)
        dist_from_high_pct = round(((high - ltp) / high) * 100.0, 2)
        range_pct = round(((high - low) / low) * 100.0, 2) if low > 0 else 0.0

        # Technical criteria
        if gain_pct >= min_gain_pct and gain_pct <= max_gain_pct and dist_from_high_pct <= max_from_high_pct:
            raw_sym = q.get("symbol", "").replace("NSE_EQ:", "").strip()
            sym = isin_to_meta.get(key, {}).get("symbol", raw_sym)
            name = isin_to_meta.get(key, {}).get("name", sym)
            industry = isin_to_meta.get(key, {}).get("industry", "Equity")

            is_strong_start = (op >= pc) and (low >= pc * 0.995)

            # Institutional Setup Scoring (0 - 120)
            score = 50.0
            score += min(25.0, gain_pct * 3.5)
            score += max(0.0, (max_from_high_pct - dist_from_high_pct) * 10.0)
            if is_strong_start:
                score += 15.0
            if turnover_cr >= 25.0:
                score += 10.0
            if turnover_cr >= 100.0:
                score += 5.0

            candidates.append({
                "symbol": sym,
                "name": name,
                "industry": industry,
                "ltp": ltp,
                "gain_pct": gain_pct,
                "dist_from_high_pct": dist_from_high_pct,
                "range_pct": range_pct,
                "turnover_cr": turnover_cr,
                "is_strong_start": is_strong_start,
                "score": round(score, 1),
                "day_high": high,
                "day_low": low,
                "day_open": op,
                "prev_close": pc
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:top_n]

    # Save to candidates.txt (with clean format for user review)
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    lines = [
        f"# JARVIS EOD SWING CANDIDATES (NIFTY 500) — {now_str}",
        f"# Filtered from {len(all_quotes)} stocks | Min Turnover: ₹{min_turnover_cr} Cr | Close near High (≤{max_from_high_pct}%)",
        "# Review on TradingView and use `/add <SYMBOL>` in Telegram to promote to watchlist.txt",
        "# =============================================================================",
        ""
    ]
    for c in top_candidates:
        ss_tag = "A+ STRONG START" if c["is_strong_start"] else "NORMAL"
        lines.append(f"{c['symbol']}  # ₹{c['ltp']:,.2f} (+{c['gain_pct']:.1f}%) | {c['dist_from_high_pct']:.2f}% from High | Turnover: ₹{c['turnover_cr']:,.1f} Cr | {ss_tag} | {c['industry']}")

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Save structured candidates.json
    with open(CANDIDATES_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": now_str,
            "count": len(top_candidates),
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
    Formats an executive Telegram review card with 1-tap [➕ Add SYM] inline buttons.
    """
    if res.get("status") != "success":
        return f"⚠️ <b>Candidate Scan Notice:</b> {res.get('message', 'Scan failed')}", None

    candidates = res.get("candidates", [])
    if not candidates:
        return "ℹ️ <b>No candidates met today's swing thrust & tightness threshold.</b>", None

    now_str = res.get("updated_at", get_ist_now().strftime("%H:%M:%S IST"))

    lines = [
        "🎯 <b>JARVIS EOD SWING CANDIDATES (NIFTY 500)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"<i>Scanned {res.get('total_scanned', 500)} liquid stocks • Saved to candidates.txt</i>\n"
    ]

    for i, c in enumerate(candidates[:max_display], 1):
        sym = c["symbol"]
        ss_icon = "⭐" if c["is_strong_start"] else "📈"
        tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
        lines.append(
            f"<b>{i}.</b> {ss_icon} {tv_link} (₹{c['ltp']:,.2f})\n"
            f"   • Gain: 🟢 <b>+{c['gain_pct']:.1f}%</b> | <b>{c['dist_from_high_pct']:.2f}%</b> from High\n"
            f"   • Turnover: ₹{c['turnover_cr']:,.1f} Cr | {c['industry']}"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Review charts above. Tap below to add vetted stocks to your live watchlist:</i>")

    # Generate 1-tap [➕ Add SYM] inline buttons
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
    print("=" * 65)
    print("⚡ SCANNING NIFTY 500 SWING CANDIDATES...")
    print("=" * 65)
    res = scan_nifty500_candidates()
    if res.get("status") == "success":
        print(f"✅ Successfully filtered {res['count']} candidates from {res['total_scanned']} stocks!")
        print(f"📁 Saved to: {CANDIDATES_FILE.name}")
        for i, c in enumerate(res["candidates"], 1):
            ss = "YES (A+)" if c["is_strong_start"] else "NO"
            print(f"{i:<2}. {c['symbol']:<12} ₹{c['ltp']:<9.2f} +{c['gain_pct']:<5.1f}% ({c['dist_from_high_pct']:.2f}% from High) | ₹{c['turnover_cr']:<6.1f} Cr | {ss}")
    else:
        print(f"❌ Error: {res.get('message')}")
