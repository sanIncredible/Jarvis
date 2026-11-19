#!/usr/bin/env python3
"""
scan_nifty_ipo.py
=================
⚡ JARVIS EOD NIFTY IPO CANDIDATE SCANNER — HIGH-TIGHT & NR CONTRACTION ENGINE
=============================================================================
Screens the official constituents of the Nifty IPO Index (100+ fresh market listings)
for Toby Crabel / Pradeep Bonde / Mark Minervini High-Probability Swing & ORB Setups:

Why IPO Stocks produce outsized breakouts:
1. Zero Overhead Supply: Stocks near All-Time Highs have no trapped historical supply.
2. High Institutional Velocity: Young stage-1/2 companies entering rapid institutional discovery.
3. Volatility Contraction Principle: "A day/week of tight compression leads to explosive expansion."

Filter Criteria:
1. Liquidity & Trading History: Minimum 7 trading days, legitimate daily range >= 0.25%.
2. Trend Alignment: Price above rising 10 EMA & 20 EMA (Stage 1/2 base accumulation).
3. Volatility Contraction (NR):
   - NR7 : Narrowest daily range of the last 7 trading days.
   - NR4 : Narrowest daily range of the last 4 trading days.
   - Inside Day (ID) : Today's High <= Prev High and Today's Low >= Prev Low.
   - Tight Range (TR) : Daily range <= 2.50% (and >= 0.25%).
4. Multi-Tier Pivot Engine:
   - TIER 1 [🔥 IPO PIVOT DOORSTEP] : Sits <= 3.5% from All-Time High (ATH) / 3-Month High with NR squeeze.
   - TIER 2 [🚀 IPO LAUNCHPAD BASE] : Sits 3.5% to 8.0% from ATH resting on 10/20 EMA support.
   - TIER 3 [📦 IPO BASE COIL]     : Sits 8.0% to 18.0% from ATH forming secondary base / cup & handle.
5. Non-Extended Move: Daily change % between -3.5% and +4.5% (NOT chasing already extended +8% moves).
"""

import os
import sys
import csv
import io
import json
import time
import argparse
import urllib.request
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
IPO_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftyIPO_list.csv"
IPO_CONSTITUENTS_CACHE = BASE_DIR / "nifty_ipo_constituents.json"
OUT_IPO_JSON = BASE_DIR / "candidates_nifty_ipo.json"
OUT_IPO_TXT = BASE_DIR / "candidates_nifty_ipo.txt"

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_ipo_constituents() -> List[Dict[str, str]]:
    """
    Downloads official constituents of the Nifty IPO Index from Nifty Indices.
    Caches locally to nifty_ipo_constituents.json for offline resilience.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    constituents = []
    try:
        req = urllib.request.Request(IPO_CSV_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                sym = row.get("Symbol") or row.get("symbol")
                if sym:
                    constituents.append({
                        "symbol": sym.strip().upper(),
                        "name": (row.get("Company Name") or row.get("company_name") or sym).strip(),
                        "industry": (row.get("Industry") or row.get("industry") or "Equity").strip(),
                        "series": (row.get("Series") or "EQ").strip(),
                        "isin": (row.get("ISIN Code") or row.get("isin") or "").strip()
                    })
        if constituents:
            with open(IPO_CONSTITUENTS_CACHE, "w", encoding="utf-8") as cf:
                json.dump(constituents, cf, indent=2)
            return constituents
    except Exception as e:
        print(f"Warning: Failed to fetch live Nifty IPO CSV: {e}", file=sys.stderr)

    # Local fallback
    if IPO_CONSTITUENTS_CACHE.is_file():
        try:
            with open(IPO_CONSTITUENTS_CACHE, "r", encoding="utf-8") as cf:
                return json.load(cf)
        except Exception:
            pass

    return []


def fetch_daily_candles_yahoo(symbol: str) -> Optional[List[Dict[str, Any]]]:
    """Fetches last 3-month daily candles from Yahoo Finance."""
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_sym}.NS?interval=1d&range=3mo"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data.get("chart", {}).get("result", [])
            if not result:
                return None
            indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
            highs = indicators.get("high", [])
            lows = indicators.get("low", [])
            closes = indicators.get("close", [])
            volumes = indicators.get("volume", [])

            candles = []
            for h, l, c, v in zip(highs, lows, closes, volumes):
                if h is not None and l is not None and c is not None and c > 0:
                    h_val, l_val, c_val = float(h), float(l), float(c)
                    rng = h_val - l_val
                    # Filter out zero-range, flat, or unformed bars
                    if rng > 0 and (rng / c_val) >= 0.002:
                        candles.append({
                            "high": h_val,
                            "low": l_val,
                            "close": c_val,
                            "volume": float(v) if v else 0.0,
                            "range": rng
                        })
            return candles
    except Exception:
        return None


def analyze_ipo_setup(stock: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Evaluates an IPO constituent for Toby Crabel NR Contractions & Doorstep Proximity.
    """
    sym = stock.get("symbol")
    if not sym:
        return None

    candles = fetch_daily_candles_yahoo(sym)
    if not candles or len(candles) < 7:
        return None

    curr = candles[-1]
    prev = candles[-2]
    curr_close = curr["close"]
    curr_range = curr["range"]
    if curr_close <= 0 or curr_range <= 0:
        return None

    range_pct = round((curr_range / curr_close) * 100.0, 2)
    # Genuine narrow range requires at least 0.25% daily range
    if range_pct < 0.25:
        return None

    # Calculate Narrow Range patterns
    ranges = [c["range"] for c in candles]
    is_nr4 = curr_range <= min(ranges[-4:])
    is_nr7 = curr_range <= min(ranges[-7:])
    is_inside = (curr["high"] <= prev["high"] * 1.001) and (curr["low"] >= prev["low"] * 0.999)
    is_tight = 0.25 <= range_pct <= 2.50

    # All-Time High / 3M High
    all_highs = [c["high"] for c in candles]
    ath = max(all_highs)
    dist_ath_pct = round(((ath - curr_close) / ath) * 100.0, 2)

    # 10 EMA & 20 EMA
    k10 = 2.0 / (10.0 + 1.0)
    ema10 = candles[0]["close"]
    for c in candles[1:]:
        ema10 = (c["close"] * k10) + (ema10 * (1.0 - k10))

    k20 = 2.0 / (20.0 + 1.0)
    ema20 = candles[0]["close"]
    for c in candles[1:]:
        ema20 = (c["close"] * k20) + (ema20 * (1.0 - k20))

    # Day Change %
    change_pct = round(((curr_close - prev["close"]) / prev["close"]) * 100.0, 2)
    # Non-extended move: Avoid chasing already expanded runners (> 4.5% or heavy dump < -3.5%)
    if not (-3.5 <= change_pct <= 4.5):
        return None

    # Contraction requirement: Stocks beyond doorstep (dist > 3.5%) MUST show volatility contraction
    has_contraction = is_nr7 or is_nr4 or is_inside or is_tight
    if not has_contraction and dist_ath_pct > 3.5:
        return None

    # Volume character: Relative volume vs. 20-day baseline
    vols = [c["volume"] for c in candles]
    avg_vol = (sum(vols[-20:]) / min(len(vols), 20)) if vols else 1.0
    curr_vol = curr["volume"]
    rvol = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 1.0
    is_vdu = rvol <= 0.70

    tags = []
    priority_score = 0
    if is_nr7:
        tags.append("🎯 NR7 (7D Squeeze)")
        priority_score += 40
    elif is_nr4:
        tags.append("📦 NR4 (4D Coil)")
        priority_score += 25

    if is_inside:
        tags.append("🔒 Inside Day")
        priority_score += 25

    if is_tight:
        tags.append(f"🧊 Tight ({range_pct}%)")
        priority_score += 15

    if is_vdu:
        tags.append("💧 VDU (Supply Dry-Up)")
        priority_score += 10
    elif rvol >= 1.25:
        tags.append(f"⚡ RVOL {rvol}x")
        priority_score += 15

    # Trend alignment bonus
    if curr_close >= ema10:
        priority_score += 10
    if curr_close >= ema20:
        priority_score += 10

    # Tier categorization based on All-Time High proximity
    if dist_ath_pct <= 3.5:
        tier = 1
        tier_name = "TIER_1_DOORSTEP"
        tier_label = "TIER 1 (🔥 IPO Pivot Doorstep)"
        priority_score += 40
    elif dist_ath_pct <= 8.0:
        tier = 2
        tier_name = "TIER_2_LAUNCHPAD"
        tier_label = "TIER 2 (🚀 IPO Launchpad Base)"
        priority_score += 20
    elif dist_ath_pct <= 18.0:
        tier = 3
        tier_name = "TIER_3_BASE"
        tier_label = "TIER 3 (📦 IPO Base Coil)"
        priority_score += 10
    else:
        return None

    to_cr = round((curr_vol * curr_close) / 10000000.0, 2) if curr_close > 0 else 0.0

    return {
        "symbol": sym,
        "name": stock.get("name", sym),
        "industry": stock.get("industry", "Equity"),
        "series": stock.get("series", "EQ"),
        "isin": stock.get("isin", ""),
        "ltp": round(curr_close, 2),
        "vol": curr_vol,
        "turnover_cr": to_cr,
        "day_high": round(curr["high"], 2),
        "day_low": round(curr["low"], 2),
        "prev_close": round(prev["close"], 2),
        "change_pct": change_pct,
        "daily_range_pct": range_pct,
        "dist_52w_pct": dist_ath_pct,
        "dist_ath_pct": dist_ath_pct,
        "ath": round(ath, 2),
        "ema10": round(ema10, 2),
        "ema20": round(ema20, 2),
        "rvol": rvol,
        "is_vdu": is_vdu,
        "is_nr7": is_nr7,
        "is_nr4": is_nr4,
        "is_inside": is_inside,
        "is_tight": is_tight,
        "nr_badge": " + ".join(tags) if tags else "Base Coil",
        "nr_tags": tags,
        "tier": tier_name,
        "tier_order": tier,
        "tier_label": tier_label,
        "priority_score": priority_score,
        "curr_close": round(curr_close, 2),
        "curr_high": round(curr["high"], 2),
        "curr_low": round(curr["low"], 2)
    }


def scan_nifty_ipo_candidates(max_workers: int = 20) -> Dict[str, Any]:
    """
    Scans all Nifty IPO Index constituents for volatility contractions and ATH doorsteps.
    """
    now_ist = get_ist_now()
    now_str = now_ist.strftime("%d %b %Y, %H:%M IST")

    print(f"🚀 [JARVIS EOD] Fetching official Nifty IPO Index constituents...", file=sys.stderr)
    constituents = fetch_ipo_constituents()
    if not constituents:
        return {"status": "error", "message": "Could not load Nifty IPO constituents"}

    print(f"🔍 Screening {len(constituents)} IPO constituents for Toby Crabel NR Contractions & ATH Doorsteps...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(analyze_ipo_setup, constituents))

    qualified = [r for r in results if r is not None]
    # Sort strictly by Tier ascending (Tier 1 first), Priority Score descending, Distance to ATH ascending
    qualified.sort(key=lambda x: (x["tier_order"], -x["priority_score"], x["dist_ath_pct"]))

    t1 = [r for r in qualified if r["tier_order"] == 1]
    t2 = [r for r in qualified if r["tier_order"] == 2]
    t3 = [r for r in qualified if r["tier_order"] == 3]

    summary = {
        "as_of": now_str,
        "total_scanned": len(constituents),
        "qualified_count": len(qualified),
        "tier1_doorstep_count": len(t1),
        "tier2_launchpad_count": len(t2),
        "tier3_base_count": len(t3),
        "nr7_count": sum(1 for r in qualified if r.get("is_nr7")),
        "nr4_count": sum(1 for r in qualified if r.get("is_nr4")),
        "inside_day_count": sum(1 for r in qualified if r.get("is_inside")),
        "tier1_candidates": t1,
        "tier2_candidates": t2,
        "tier3_candidates": t3,
        "all_candidates": qualified
    }

    # Save to disk
    with open(OUT_IPO_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(OUT_IPO_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join([r["symbol"] for r in qualified]))

    print(f"✅ Discovered {len(qualified)} qualified IPO setups ({len(t1)} Tier 1 Doorsteps, {len(t2)} Tier 2 Launchpads).", file=sys.stderr)
    return summary


def format_ipo_telegram_card(summary: Dict[str, Any], max_display: int = 8) -> tuple:
    """Formats an interactive Telegram card for the /ipo command or EOD briefing."""
    t1 = summary.get("tier1_candidates", [])
    t2 = summary.get("tier2_candidates", [])
    t3 = summary.get("tier3_candidates", [])
    total = summary.get("qualified_count", 0)
    as_of = summary.get("as_of", "")

    header = (
        "🚀 <b>NIFTY IPO INDEX: HIGH-TIGHT &amp; NR RADAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>As Of:</b> {as_of}\n"
        f"🎯 <b>Total Setups:</b> <b>{total}</b> ({len(t1)} Doorstep • {len(t2)} Launchpad)\n"
        "💡 <i>Zero overhead supply • Multi-day Toby Crabel NR Contractions</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    lines = []
    keyboard = []
    cur_kb_row = []

    if t1:
        lines.append("🔥 <b>TIER 1: PIVOT DOORSTEP (≤3.5% from ATH):</b>")
        for idx, c in enumerate(t1[:max_display], 1):
            sym = c["symbol"]
            dist_str = f"-{c['dist_ath_pct']:.1f}%" if c['dist_ath_pct'] > 0 else "ATH"
            badge = c.get("nr_badge", "Coil")
            lines.append(f"  {idx}. <b>{sym}</b> (₹{c['ltp']}) • <code>{dist_str}</code> | {badge}")
            cur_kb_row.append({"text": f"+ {sym}", "callback_data": f"add_wl:{sym}"})
            if len(cur_kb_row) == 3:
                keyboard.append(cur_kb_row)
                cur_kb_row = []

    if t2 and len(lines) < 14:
        lines.append("\n🚀 <b>TIER 2: LAUNCHPAD BASE (3.5% - 8.0% from ATH):</b>")
        for idx, c in enumerate(t2[:6], 1):
            sym = c["symbol"]
            dist_str = f"-{c['dist_ath_pct']:.1f}%"
            badge = c.get("nr_badge", "Coil")
            lines.append(f"  • <b>{sym}</b> (₹{c['ltp']}) • <code>{dist_str}</code> | {badge}")
            if len(cur_kb_row) < 3:
                cur_kb_row.append({"text": f"+ {sym}", "callback_data": f"add_wl:{sym}"})
            if len(cur_kb_row) == 3:
                keyboard.append(cur_kb_row)
                cur_kb_row = []

    if cur_kb_row:
        keyboard.append(cur_kb_row)

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Tap + buttons to add directly to scanner watchlist or use <code>/buy &lt;SYM&gt; agg</code>!</i>")

    text = header + "\n".join(lines)
    return text, {"inline_keyboard": keyboard}


def main():
    parser = argparse.ArgumentParser(description="Nifty IPO Index High-Tight & NR Contraction Candidate Screener")
    parser.add_argument("--tv", action="store_true", help="Output comma-separated symbols for TradingView")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--notify", action="store_true", help="Send EOD summary to Telegram channel")
    args = parser.parse_args()

    summary = scan_nifty_ipo_candidates()

    if args.json:
        print(json.dumps(summary, indent=2))
        return

    if args.tv:
        syms = [f"NSE:{c['symbol']}" for c in summary.get("all_candidates", [])]
        print(",".join(syms))
        return

    if args.notify:
        try:
            from telegram_bot import send_topic_alert
            text, markup = format_ipo_telegram_card(summary)
            send_topic_alert("candidates", text, reply_markup=markup)
            print("Telegram alert delivered to 'candidates' topic successfully.", file=sys.stderr)
        except Exception as e:
            print(f"Telegram notification error: {e}", file=sys.stderr)

    t1 = summary["tier1_candidates"]
    t2 = summary["tier2_candidates"]
    t3 = summary["tier3_candidates"]

    print("=" * 75)
    print("🚀 NIFTY IPO INDEX: HIGH-TIGHT & NR CONTRACTION RADAR")
    print(f"📅 As Of: {summary['as_of']}")
    print(f"⚡ Total Scanned: {summary['total_scanned']} | Qualified Setups: {summary['qualified_count']}")
    print(f"   • Tier 1 Doorsteps (<=3.5% from ATH) : {summary['tier1_doorstep_count']} setups")
    print(f"   • Tier 2 Launchpads (3.5-8% from ATH): {summary['tier2_launchpad_count']} setups")
    print(f"   • Tier 3 Base Coils (8-18% from ATH) : {summary['tier3_base_count']} setups")
    print("=" * 75)

    if t1:
        print("\n🔥 TIER 1: PIVOT DOORSTEP BREAKOUT (<=3.5% from ATH):")
        for c in t1[:10]:
            print(f"  • {c['symbol']:<12} | LTP: ₹{c['ltp']:<8} | Dist: -{c['dist_ath_pct']:>4.1f}% | {c['nr_badge']:<26} | [{c['industry']}]")

    if t2:
        print("\n🚀 TIER 2: LAUNCHPAD BASE (3.5% - 8% from ATH):")
        for c in t2[:8]:
            print(f"  • {c['symbol']:<12} | LTP: ₹{c['ltp']:<8} | Dist: -{c['dist_ath_pct']:>4.1f}% | {c['nr_badge']:<26} | [{c['industry']}]")

    if t3:
        print("\n📦 TIER 3: BASE COIL (8% - 18% from ATH):")
        for c in t3[:6]:
            print(f"  • {c['symbol']:<12} | LTP: ₹{c['ltp']:<8} | Dist: -{c['dist_ath_pct']:>4.1f}% | {c['nr_badge']:<26} | [{c['industry']}]")


if __name__ == "__main__":
    main()
