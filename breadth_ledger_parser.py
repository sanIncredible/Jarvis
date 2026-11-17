"""
breadth_ledger_parser.py
========================
Parser and Scanner for The Breadth Ledger (markets.manasarora.com / Manas Arora).

Capabilities:
1. Broad Momentum Stocks Scanner:
   - Filters stocks by trading days lookback (5, 10, 20, 30, 60, 90, 125, 180, 250 days)
   - Filters by minimum gain percentage (10%, 15%, 20%, 25%, 30%, 40%, 50%, 75%, 100%)
   - Supports filtering across All tracked stocks or specific Industry
   - Ranks industries by momentum concentration (% of stocks meeting the criteria)

2. Fresh High Clusters:
   - Extracts industries where 1-month, 3-month, and 6-month fresh highs cluster
   - Returns the exact leading stock tickers in each cluster

3. 52-Week High Radar:
   - Extracts stocks within X% (e.g. 3%, 5%, 10%) of their 52-week all-time highs
"""

import sys
import json
import argparse
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

DATA_URL = "https://breadth-ledger.manas-arora.workers.dev/data.json"
CACHE_FILE = Path(__file__).resolve().parent / "breadth_ledger_cache.json"

LOOKBACK_BUCKETS = [5, 10, 20, 30, 60, 90, 125, 180, 250]
GAIN_THRESHOLDS = [10, 15, 20, 25, 30, 40, 50, 75, 100]

GAIN_LABELS = {
    1: "≥ 10%",
    2: "≥ 15%",
    3: "≥ 20%",
    4: "≥ 25%",
    5: "≥ 30%",
    6: "≥ 40%",
    7: "≥ 50%",
    8: "≥ 75%",
    9: "≥ 100%"
}


def fetch_breadth_ledger_data(max_age_minutes: int = 15) -> Optional[Dict[str, Any]]:
    """Fetches real-time JSON from Breadth Ledger API with local caching."""
    import time

    if CACHE_FILE.exists():
        age_min = (time.time() - CACHE_FILE.stat().st_mtime) / 60.0
        if age_min < max_age_minutes:
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    req = urllib.request.Request(
        DATA_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
    except Exception as e:
        print(f"⚠️ Error fetching Breadth Ledger data: {e}", file=sys.stderr)
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return None


def get_broad_momentum_stocks(
    data: Dict[str, Any],
    lookback_days: int = 5,
    min_gain_pct: int = 10,
    industry: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parses data['momo'] to identify individual stocks that gained at least min_gain_pct
    over the lookback_days window.
    """
    momo = data.get("momo", {})
    lb_list = momo.get("lb", LOOKBACK_BUCKETS)
    th_list = momo.get("th", GAIN_THRESHOLDS)

    # Find closest valid lookback
    if lookback_days not in lb_list:
        closest_lb = min(lb_list, key=lambda x: abs(x - lookback_days))
        li = lb_list.index(closest_lb)
        actual_lb = closest_lb
    else:
        li = lb_list.index(lookback_days)
        actual_lb = lookback_days

    # Find closest valid gain threshold
    if min_gain_pct not in th_list:
        valid_th = [t for t in th_list if t <= min_gain_pct]
        closest_th = valid_th[-1] if valid_th else th_list[0]
        k = th_list.index(closest_th) + 1
        actual_gain = closest_th
    else:
        k = th_list.index(min_gain_pct) + 1
        actual_gain = min_gain_pct

    groups = momo.get("groups", [])
    matched_stocks = []
    industry_stats = []

    for g in groups:
        ind_name = g.get("industry", "Unknown")
        if industry and industry.lower() not in ind_name.lower():
            continue

        raw_stocks = g.get("stocks", [])
        total_in_ind = len(raw_stocks)
        hits_in_ind = 0

        for sym, code in raw_stocks:
            if len(code) > li and code[li] != "-":
                bucket_val = int(code[li])
                if bucket_val >= k:
                    hits_in_ind += 1
                    matched_stocks.append({
                        "symbol": sym,
                        "industry": ind_name,
                        "lookback_days": actual_lb,
                        "min_gain_threshold": actual_gain,
                        "gain_tier": GAIN_LABELS.get(bucket_val, f"≥ {actual_gain}%"),
                        "bucket_score": bucket_val
                    })

        if total_in_ind > 0:
            share_pct = round((hits_in_ind / total_in_ind) * 100.0, 1)
            industry_stats.append({
                "industry": ind_name,
                "hits": hits_in_ind,
                "total": total_in_ind,
                "share_pct": share_pct
            })

    # Sort matched stocks by bucket score descending, then symbol
    matched_stocks.sort(key=lambda x: (x["bucket_score"], x["symbol"]), reverse=True)
    # Sort industry stats by share percentage descending
    industry_stats.sort(key=lambda x: (x["share_pct"], x["hits"]), reverse=True)

    return {
        "as_of": data.get("asOf"),
        "lookback_days": actual_lb,
        "min_gain_pct": actual_gain,
        "filter_industry": industry or "ALL",
        "total_hits": len(matched_stocks),
        "stocks": matched_stocks,
        "industry_rankings": industry_stats
    }


def get_fresh_high_clusters(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts industries where 1M and 3M highs cluster, with constituent stocks."""
    clusters = data.get("clusters", [])
    results = []
    for c in clusters:
        results.append({
            "industry": c.get("industry"),
            "tracked_count": c.get("n", 0),
            "high_1m_count": c.get("h1", 0),
            "high_3m_count": c.get("h3", 0),
            "high_6m_count": c.get("h6", 0),
            "leading_stocks": c.get("names", [])
        })
    return results


def get_52w_high_radar(data: Dict[str, Any], max_dist_pct: float = 3.0) -> List[Dict[str, Any]]:
    """Extracts stocks within max_dist_pct of their 52W high."""
    near = data.get("near", [])
    results = []
    for item in near:
        if len(item) >= 4:
            sym, dist, high_flag, ind = item[0], abs(float(item[1])), item[2], item[3]
            if dist <= max_dist_pct:
                results.append({
                    "symbol": sym,
                    "distance_pct": dist,
                    "high_flag": "52W High Today" if dist == 0 else f"-{dist:.1f}% from 52W High",
                    "industry": ind
                })
    results.sort(key=lambda x: x["distance_pct"])
    return results


def main():
    parser = argparse.ArgumentParser(description="Breadth Ledger (Manas Arora) Stock Parser")
    parser.add_argument("--days", type=int, default=5, help="Lookback trading days: 5, 10, 20, 30, 60, 90, 125, 180, 250 (default: 5)")
    parser.add_argument("--gain", type=int, default=10, help="Min gain %: 10, 15, 20, 25, 30, 40, 50, 75, 100 (default: 10)")
    parser.add_argument("--industry", type=str, default=None, help="Filter by industry name (e.g. 'Bank', 'Auto', 'Defense')")
    parser.add_argument("--clusters", action="store_true", help="Display Where Fresh Highs Cluster")
    parser.add_argument("--near", type=float, default=None, help="Display stocks within X%% of 52W High (e.g. --near 3.0)")
    parser.add_argument("--tv", action="store_true", help="Output comma-separated symbols for TradingView / Watchlist import")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    data = fetch_breadth_ledger_data()
    if not data:
        print("❌ Failed to fetch data from Breadth Ledger API.")
        sys.exit(1)

    as_of = data.get("asOf", "")

    # 1. 52W High Radar
    if args.near is not None:
        radar = get_52w_high_radar(data, max_dist_pct=args.near)
        if args.tv:
            print(",".join([f"NSE:{r['symbol']}" for r in radar]))
            return
        print(f"🎯 52-WEEK HIGH RADAR (Within -{args.near:.1f}% of 52W High | {as_of}):")
        print(f"Found {len(radar)} stocks:")
        for r in radar[:30]:
            print(f"  • {r['symbol']:12} | {r['distance_pct']:.1f}% off 52W High | [{r['industry']}]")
        if len(radar) > 30:
            print(f"  ... and {len(radar) - 30} more stocks.")
        return

    # 2. Fresh High Clusters
    if args.clusters:
        clusters = get_fresh_high_clusters(data)
        print(f"🧬 WHERE FRESH HIGHS CLUSTER ({as_of}):")
        for c in clusters:
            if c["high_3m_count"] > 0:
                print(f"• {c['industry']} ({c['tracked_count']} stocks tracked):")
                print(f"   3-Month Highs: {c['high_3m_count']} | 1-Month Highs: {c['high_1m_count']}")
                print(f"   Leaders: {', '.join(c['leading_stocks'])}")
        return

    # 3. Broad Momentum Stocks
    res = get_broad_momentum_stocks(data, lookback_days=args.days, min_gain_pct=args.gain, industry=args.industry)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    if args.tv:
        syms = [f"NSE:{s['symbol']}" for s in res["stocks"]]
        print(",".join(syms))
        return

    print("=" * 70)
    print(f"🚀 BREADTH LEDGER: BROAD MOMENTUM SCANNER")
    print(f"📅 As Of: {res['as_of']}")
    print(f"⚙️ Test Filter: Gained ≥ {res['min_gain_pct']}% over last {res['lookback_days']} trading days")
    print(f"🏢 Industry Scope: {res['filter_industry']}")
    print(f"🎯 Matched Stocks: {res['total_hits']}")
    print("=" * 70)

    # Top Industries by Momentum Concentration
    print("\n📊 INDUSTRY MOMENTUM RANKINGS (Share of stocks meeting test):")
    for ind in res["industry_rankings"][:10]:
        if ind["hits"] > 0:
            bar_len = int(ind["share_pct"] / 4)
            bar = "█" * bar_len
            print(f"  • {ind['industry']:<26} : {ind['hits']:>2}/{ind['total']:<2} stocks ({ind['share_pct']:>5.1f}%) {bar}")

    # Top Individual Stocks
    print(f"\n📈 INDIVIDUAL MOMENTUM STOCKS ({min(len(res['stocks']), 35)} shown):")
    for s in res["stocks"][:35]:
        print(f"  • {s['symbol']:<12} | {s['gain_tier']:<8} | [{s['industry']}]")

    if len(res["stocks"]) > 35:
        print(f"  ... and {len(res['stocks']) - 35} more stocks.")

    print("\n💡 TIP: Run with --tv to generate copy-paste list for TradingView or Jarvis watchlist.")


if __name__ == "__main__":
    main()
