#!/usr/bin/env python3
"""
scan_nr_momo.py
===============
Filters Breadth Ledger 90D/30% Momentum Candidates for Narrow Range (NR) Coils:
- NR7 : Narrowest daily range of the last 7 trading days (Highest-conviction volatility explosion).
- NR4 : Narrowest daily range of the last 4 trading days.
- Inside Day (ID) : Today's High <= Yesterday's High and Today's Low >= Yesterday's Low.
- Tight Range (TR) : Daily range <= 2.2% of stock price.

Why this fits 3m ORB:
- Compresses structural risk: Low of Day (LOD) stop is extremely tight (< 1.5% to 2.0%).
- Maximum position sizing: Tight stop allows deploying full ₹1.0L/₹1.5L MTF allocation with minimal absolute risk.
- Volatility Expansion: Follows Toby Crabel / Mark Minervini principle: "Day of contraction leads to day of expansion".
"""

import sys
import json
import argparse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
MOMO_JSON = BASE_DIR / "candidates_90d_momo.json"
OUT_NR_JSON = BASE_DIR / "candidates_90d_nr.json"
OUT_NR_TXT = BASE_DIR / "candidates_90d_nr.txt"


def fetch_daily_candles(symbol: str) -> Optional[List[Dict[str, float]]]:
    """Fetches last 10 daily candles from Yahoo Finance."""
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_sym}.NS?interval=1d&range=12d"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
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
                    # Filter out zero-range, flat, or pre-market unformed bars
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


def analyze_nr_setup(candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Evaluates whether a candidate qualifies as an NR4, NR7, or Inside Day."""
    sym = candidate.get("symbol")
    if not sym:
        return None

    candles = fetch_daily_candles(sym)
    if not candles or len(candles) < 7:
        return None

    curr = candles[-1]
    prev = candles[-2]
    curr_range = curr["range"]
    curr_close = curr["close"]
    if curr_close <= 0 or curr_range <= 0:
        return None

    range_pct = round((curr_range / curr_close) * 100.0, 2)
    # A genuine narrow range must have real trading activity (at least 0.25% daily range)
    if range_pct < 0.25:
        return None

    ranges = [c["range"] for c in candles]

    # NR4: Today's range is strictly <= minimum of last 4 days
    is_nr4 = curr_range <= min(ranges[-4:])
    # NR7: Today's range is strictly <= minimum of last 7 days
    is_nr7 = curr_range <= min(ranges[-7:])
    # Inside Day: Today's High <= Prev High and Today's Low >= Prev Low
    is_inside = (curr["high"] <= prev["high"] * 1.001) and (curr["low"] >= prev["low"] * 0.999)
    # Tight Range: Range <= 2.2% (and >= 0.25%)
    is_tight = 0.25 <= range_pct <= 2.20

    if not (is_nr4 or is_nr7 or is_inside or is_tight):
        return None

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

    tier_order = candidate.get("tier_order", 4)
    # Tier 1 Doorstep bonus
    if tier_order == 1:
        priority_score += 30
    elif tier_order == 2:
        priority_score += 15

    dist_52w = candidate.get("dist_52w_pct")
    if dist_52w is not None and dist_52w <= 1.5:
        priority_score += 15

    res = dict(candidate)
    res.update({
        "is_nr7": is_nr7,
        "is_nr4": is_nr4,
        "is_inside": is_inside,
        "is_tight": is_tight,
        "daily_range_pct": range_pct,
        "nr_tags": tags,
        "nr_badge": " + ".join(tags),
        "priority_score": priority_score,
        "curr_close": round(curr_close, 2),
        "curr_high": round(curr["high"], 2),
        "curr_low": round(curr["low"], 2)
    })
    return res


def scan_nr_momentum_candidates(max_workers: int = 15) -> Dict[str, Any]:
    """Loads 90D momentum candidates and runs concurrent NR contraction screening."""
    if not MOMO_JSON.is_file():
        # Fallback to generating it
        from breadth_ledger_parser import fetch_breadth_ledger_data, get_90d_momo_candidates
        d = fetch_breadth_ledger_data()
        c_res = get_90d_momo_candidates(d)
        with open(MOMO_JSON, "w", encoding="utf-8") as f:
            json.dump(c_res, f, indent=2)
    else:
        with open(MOMO_JSON, "r", encoding="utf-8") as f:
            c_res = json.load(f)

    candidates = c_res.get("candidates", [])
    actionable = [c for c in candidates if c.get("tier_order", 4) <= 3]

    print(f"🔍 Screening {len(actionable)} actionable 90D momentum candidates for NR contractions...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(analyze_nr_setup, actionable))

    nr_qualified = [r for r in results if r is not None]
    nr_qualified.sort(key=lambda x: (x["priority_score"], -x.get("dist_52w_pct", 999.0)), reverse=True)

    tier1_nr = [r for r in nr_qualified if r.get("tier_order") == 1]
    tier2_nr = [r for r in nr_qualified if r.get("tier_order") == 2]
    tier3_nr = [r for r in nr_qualified if r.get("tier_order") == 3]

    summary = {
        "as_of": c_res.get("as_of"),
        "total_scanned": len(actionable),
        "nr_qualified_count": len(nr_qualified),
        "tier1_doorstep_nr_count": len(tier1_nr),
        "tier2_launchpad_nr_count": len(tier2_nr),
        "tier3_base_nr_count": len(tier3_nr),
        "nr7_count": sum(1 for r in nr_qualified if r.get("is_nr7")),
        "nr4_count": sum(1 for r in nr_qualified if r.get("is_nr4")),
        "inside_day_count": sum(1 for r in nr_qualified if r.get("is_inside")),
        "tier1_candidates": tier1_nr,
        "tier2_candidates": tier2_nr,
        "tier3_candidates": tier3_nr,
        "all_nr_candidates": nr_qualified
    }

    # Save to disk
    with open(OUT_NR_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(OUT_NR_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join([r["symbol"] for r in nr_qualified]))

    return summary


def main():
    parser = argparse.ArgumentParser(description="NR4 / NR7 / Inside Day Screener for 90D Momentum Candidates")
    parser.add_argument("--tier1-only", action="store_true", help="Only show Tier 1 Doorstep setups")
    parser.add_argument("--tv", action="store_true", help="Output comma-separated symbols for TradingView")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    summary = scan_nr_momentum_candidates()

    if args.json:
        print(json.dumps(summary, indent=2))
        return

    cand_list = summary["tier1_candidates"] if args.tier1_only else summary["all_nr_candidates"]

    if args.tv:
        syms = [f"NSE:{c['symbol']}" for c in cand_list]
        print(",".join(syms))
        return

    print("=" * 75)
    print("🎯 90D MOMENTUM + NR CONTRACTION SNIPER LIST (For Tomorrow's 3m ORB)")
    print(f"📅 As Of: {summary['as_of']}")
    print(f"⚡ Total Actionable Scanned: {summary['total_scanned']} | Qualified NR Coils: {summary['nr_qualified_count']}")
    print(f"   • Tier 1 Doorsteps (≤3% from High) : {summary['tier1_doorstep_nr_count']} setups")
    print(f"   • Tier 2 Launchpads (3-7% from High) : {summary['tier2_launchpad_nr_count']} setups")
    print(f"   • Tier 3 Base Runways (7-12% High)  : {summary['tier3_base_nr_count']} setups")
    print("=" * 75)

    if summary["tier1_candidates"]:
        print("\n🔥 TIER 1: PIVOT DOORSTEP + NARROW RANGE COILS (Prime Tomorrow Triggers):")
        for c in summary["tier1_candidates"]:
            dist_str = f"-{c['dist_52w_pct']:.1f}%" if c['dist_52w_pct'] is not None else "At High"
            flag = " 👑" if c.get("is_fresh_3m") else ""
            print(f"  • {c['symbol']:<12} | {c['nr_badge']:<26} | Range: {c['daily_range_pct']:>4.2f}% | Dist: {dist_str:>6}{flag} | [{c['industry']}]")

    if summary["tier2_candidates"]:
        print("\n🚀 TIER 2: COIL LAUNCHPAD + NARROW RANGE (Secondary Base Watchlist):")
        for c in summary["tier2_candidates"][:8]:
            dist_str = f"-{c['dist_52w_pct']:.1f}%" if c['dist_52w_pct'] is not None else "At High"
            print(f"  • {c['symbol']:<12} | {c['nr_badge']:<26} | Range: {c['daily_range_pct']:>4.2f}% | Dist: {dist_str:>6} | [{c['industry']}]")

    if summary["tier3_candidates"]:
        print("\n📦 TIER 3: BASE RUNWAY + NARROW RANGE (Multi-Day Base Building):")
        for c in summary["tier3_candidates"][:5]:
            dist_str = f"-{c['dist_52w_pct']:.1f}%" if c['dist_52w_pct'] is not None else "At High"
            print(f"  • {c['symbol']:<12} | {c['nr_badge']:<26} | Range: {c['daily_range_pct']:>4.2f}% | Dist: {dist_str:>6} | [{c['industry']}]")

    print("\n💡 TIP: Use 1-tap buttons in Telegram or /add to load Tier 1 NR setups for tomorrow's 09:18 AM ORB!")


if __name__ == "__main__":
    main()
