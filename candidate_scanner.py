#!/usr/bin/env python3
"""
⚡ JARVIS EOD SWING CANDIDATE SCANNER — DUAL-TIER VCP COIL ENGINE
=============================================================================
Pradeep Bonde / Stockbee / Mark Minervini Multi-Day Pre-Breakout Screener.
Identifies institutional swing setups poised for tomorrow's 3-Minute ORB + PDH Breakout:
1. Trend Alignment       : Price above 20 EMA and 50 EMA (Stage 2 Institutional Uptrend).
2. Volatility Contraction: 3 to 5-day consolidation range within ≤ 2.2× to 2.5× ATR (coiled spring).
3. Relative Volume (RVOL): Volume expansion ≥ 1.3× average OR dry volume supply exhaustion (≤0.75×).
4. Dual-Tier Pivot Engine:
   - TIER 1 [🔥 PIVOT DOORSTEP] : Sits ≤ 2.2% from 20D High (or ≤ 1.0× ATR). Immediate 20D breakout ignition.
   - TIER 2 [🚀 BASE LAUNCHPAD] : Sits 2.2% to 5.0% from 20D High (or ≤ 1.5× ATR) & ≤ 2.2% from PDH.
                                  Early pocket coil off 10/20 EMA with tighter Day Low SL & multi-R runway!
5. Non-Extended Setup    : Daily change % between -2.0% and +3.5% (NOT chasing +8% extended moves!).
6. Institutional Liq     : Minimum ₹5 Crore daily turnover on NSE Equity.

Saves clean ranked setups to 'candidates.txt' & 'candidates.json' for manual review.
DOES NOT touch 'watchlist.txt' — user reviews charts and promotes via 1-tap Telegram buttons!
"""

import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
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
PRE_MARKET_FILE = BASE_DIR / "pre_market_summary.json"
CANDIDATES_FILE = BASE_DIR / "candidates.txt"
CANDIDATES_JSON = BASE_DIR / "candidates.json"

IST = timezone(timedelta(hours=5, minutes=30))

INDUSTRY_TO_SECTOR = {
    "Automobile and Auto Components": "Nifty Auto",
    "Healthcare": "Nifty Pharma",
    "Information Technology": "Nifty IT",
    "Metals & Mining": "Nifty Metal",
    "Realty": "Nifty Realty",
    "Financial Services": "Nifty Bank",
    "Power": "Nifty Energy",
    "Oil Gas & Consumable Fuels": "Nifty Energy",
    "Fast Moving Consumer Goods": "Nifty FMCG",
    "Capital Goods": "Nifty Infra",
    "Construction": "Nifty Infra",
    "Media": "Nifty Media"
}


def load_sector_leaders():
    """Loads sectoral performance ranking from pre_market_summary.json without penalizing unmapped sectors."""
    if not PRE_MARKET_FILE.is_file():
        return {}, set()
    try:
        with open(PRE_MARKET_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            sector_perf = {s["name"]: float(s.get("change_pct", 0.0)) for s in d.get("sectorals", [])}
            ranked = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
            top_3 = set(r[0] for r in ranked[:3] if r[1] > 0)
            return sector_perf, top_3
    except Exception:
        return {}, set()


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


def calc_ema(values, period):
    """Calculates Exponential Moving Average across a list of numeric values."""
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for val in values[period:]:
        ema = (val * k) + (ema * (1.0 - k))
    return ema


def scan_nifty500_candidates(
    top_n=25,
    max_range_pct=2.85,
    max_from_high_pct=2.20,
    min_turnover_cr=5.0
):
    """
    Multi-Tier Pre-Breakout & Pullback Screener (Nifty 500):
    - Stage 1: Fast bulk Upstox snapshot to eliminate illiquid, penny, or extended runners.
    - Stage 2: Concurrent multi-day historical candles via Yahoo Finance (25 threads) evaluating:
      1. Stage 2 Trend (Price >= 0.99*20 EMA, 20 EMA >= 0.985*50 EMA)
      2. Dual-Timeframe VCP (5D VCP <= 2.50x OR 3D VCP <= 1.25x OR Inside Day)
      3. Volume Dry-Up (VDU <= 0.60x) & Institutional Surge (RVOL >= 1.30x)
      4. Multi-Tier Setups:
         - Tier 1 (🔥 Pivot Doorstep): <= 2.2% from 20D High / <= 1.0x ATR with tight coil
         - Tier 2 (🚀 Base Launchpad): <= 5.0% from 20D High and <= 2.2% from PDH
         - Tier 3 (🛡️ EMA Pullback Coil): Leaders resting at rising 10/20 EMA support
      5. 52-Week / 3-Month High Blue Sky Proximity
    """
    cfg = load_config()
    ignored_symbols = set(s.upper() for s in cfg.get("ignored_symbols", ["MOTHERSON"]))
    token = cfg.get("upstox", {}).get("access_token", "").strip()
    if not token:
        return {"status": "error", "message": "Upstox access token missing in config_credentials.json"}

    constituents = load_nifty500_constituents()
    if not constituents:
        return {"status": "error", "message": "nifty500_constituents.json not found"}

    sym_to_meta = {c["symbol"].upper(): c for c in constituents if c.get("symbol")}
    isin_to_meta = {c["isin"].upper(): c for c in constituents if c.get("isin")}
    keys = [f"NSE_EQ|{c['isin']}" for c in constituents if c.get("isin")]

    sector_perf, top_3_sectors = load_sector_leaders()

    # --- STAGE 1: Bulk Snapshot from Upstox ---
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

    # Intraday pacing factor for RVOL calculation
    now_ist = get_ist_now()
    m_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    m_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if now_ist < m_open or now_ist >= m_close:
        pacing_factor = 1.0
    else:
        elapsed_mins = max(15.0, (now_ist - m_open).total_seconds() / 60.0)
        pacing_factor = round(375.0 / elapsed_mins, 2)

    stage1_shortlist = []
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
        dist_from_high_pct = round(((high - ltp) / high) * 100.0, 2)
        bar_range = high - low
        close_loc = round((ltp - low) / bar_range, 2) if bar_range > 0 else 0.5

        # Stage 1 Pre-Filter (Discard extended & wide-range runners):
        # 1. Non-Extended Move: -2.5% <= change_pct <= +3.5% (Not extended chasing!)
        # 2. Narrow / Coiled Bar: daily_range_pct <= max_range_pct (<= 2.85%)
        # 3. Sitting Near Today's High: dist_from_high_pct <= max_from_high_pct (<= 2.2%)
        # 4. Closing in Upper Half: close_loc >= 0.42 (or >= 0.35 if ultra-tight bar <= 1.5%)
        min_loc = 0.35 if daily_range_pct <= 1.50 else 0.42
        if (-2.5 <= change_pct <= 3.5) and daily_range_pct <= max_range_pct and dist_from_high_pct <= max_from_high_pct and close_loc >= min_loc:
            raw_sym = q.get("symbol", "").replace("NSE_EQ:", "").replace("NSE_EQ|", "").strip().upper()
            meta = sym_to_meta.get(raw_sym, {})
            if not meta:
                clean_key = key.replace("NSE_EQ:", "").replace("NSE_EQ|", "").strip().upper()
                meta = isin_to_meta.get(clean_key, {})
            sym = meta.get("symbol", raw_sym)
            if sym.upper() in ignored_symbols:
                continue
            name = meta.get("name", sym)
            industry = meta.get("industry", "Equity")
            stage1_shortlist.append({
                "symbol": sym,
                "name": name,
                "industry": industry,
                "ltp": ltp,
                "vol": vol,
                "turnover_cr": turnover_cr,
                "daily_range_pct": daily_range_pct,
                "change_pct": change_pct,
                "dist_from_high_pct": dist_from_high_pct,
                "close_loc": close_loc,
                "day_high": high,
                "day_low": low,
                "day_open": op,
                "prev_close": pc
            })

    # --- STAGE 2: Multi-Day Historical Candles via Yahoo Finance ---
    def analyze_candidate(item):
        sym = item["symbol"]
        y_sym = "TMPV" if sym == "TATAMOTORS" else sym
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y_sym}.NS?range=3mo&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                res = data["chart"]["result"][0]
                quotes = res["indicators"]["quote"][0]
                closes = quotes.get("close", [])
                highs = quotes.get("high", [])
                lows = quotes.get("low", [])
                volumes = quotes.get("volume", [])

                valid = [(c, h, l, v) for c, h, l, v in zip(closes, highs, lows, volumes) if c is not None and h is not None and l is not None and v is not None]
                if len(valid) < 30:
                    return None

                c_list = [v[0] for v in valid]
                h_list = [v[1] for v in valid]
                l_list = [v[2] for v in valid]
                v_list = [v[3] for v in valid]

                # Inject live Upstox tick data into latest forming bar for 100% precision
                h_list[-1] = max(h_list[-1], item["day_high"])
                l_list[-1] = min(l_list[-1], item["day_low"])
                c_list[-1] = item["ltp"]
                v_list[-1] = item["vol"]
                ltp = item["ltp"]

                # CRITERION 1: Trend Alignment (Stage 2 Institutional Uptrend)
                ema20 = calc_ema(c_list, 20)
                ema50 = calc_ema(c_list, 50)
                trend_ok = (ltp >= ema20 * 0.99) and (ema20 >= ema50 * 0.985)
                if not trend_ok:
                    return None  # Disqualified: Not Stage 2 uptrend

                # ATR 14
                trs = []
                for i in range(1, len(valid)):
                    tr = max(h_list[i] - l_list[i], abs(h_list[i] - c_list[i-1]), abs(l_list[i] - c_list[i-1]))
                    trs.append(tr)
                atr14 = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else (h_list[-1] - l_list[-1])

                # CRITERION 2: Volatility Contraction (VCP / Tightness)
                h_5d = max(h_list[-5:])
                l_5d = min(l_list[-5:])
                range_5d = h_5d - l_5d
                vcp_ratio_5d = round(range_5d / atr14, 2) if atr14 > 0 else 9.9

                h_3d = max(h_list[-3:])
                l_3d = min(l_list[-3:])
                range_3d = h_3d - l_3d
                vcp_ratio_3d = round(range_3d / atr14, 2) if atr14 > 0 else 9.9

                # Inside Day identification (high compression)
                is_inside_day = len(h_list) >= 2 and h_list[-1] <= h_list[-2] and l_list[-1] >= l_list[-2]

                # CRITERION 3: Resistance Pivot & High Proximity
                pivot_20d = max(h_list[-20:])
                dist_pivot_20d_pct = round(((pivot_20d - ltp) / pivot_20d) * 100.0, 2)
                dist_pivot_atr = round((pivot_20d - ltp) / atr14, 2) if atr14 > 0 else 9.9
                pdh = h_list[-2] if len(h_list) >= 2 else h_list[-1]
                dist_pdh_pct = round(((pdh - ltp) / pdh) * 100.0, 2)

                # 52-Week / 3-Month High Blue Sky Proximity
                high_3m = max(h_list)
                dist_3m_high_pct = round(((high_3m - ltp) / high_3m) * 100.0, 2)
                is_near_3m_high = dist_3m_high_pct <= 2.50

                # 10/20 EMA Pullback Proximity
                dist_ema10_pct = round(((ltp - calc_ema(c_list, 10)) / ltp) * 100.0, 2)
                dist_ema20_pct = round(((ltp - ema20) / ltp) * 100.0, 2)

                is_tier1 = False
                is_tier2 = False
                is_tier3 = False
                tier_label = ""
                coil_tag = ""

                # TIER 1: 🔥 PIVOT DOORSTEP (Direct 20D Breakout Ignition)
                # Allows tight 5D VCP (<=2.5x), OR tight 3D VCP (<=1.25x), OR Inside Day
                if (dist_pivot_20d_pct <= 2.20 or dist_pivot_atr <= 1.00) and (vcp_ratio_5d <= 2.50 or vcp_ratio_3d <= 1.25 or is_inside_day):
                    is_tier1 = True
                    tier_label = "TIER 1"
                    coil_tag = "🔥 PIVOT DOORSTEP" if (vcp_ratio_5d <= 1.60 or vcp_ratio_3d <= 1.00) else "⚡ PIVOT IGNITION"

                # TIER 2: 🚀 BASE LAUNCHPAD (10/20 EMA Pocket Coil)
                # Sits 2.2% to 5.0% from 20D High, near PDH (<= 2.2%), with tight 5D/3D VCP
                elif (dist_pivot_20d_pct <= 5.00 or dist_pivot_atr <= 1.50) and (abs(dist_pdh_pct) <= 2.20) and (vcp_ratio_5d <= 2.50 or vcp_ratio_3d <= 1.35):
                    is_tier2 = True
                    tier_label = "TIER 2"
                    coil_tag = "🚀 BASE LAUNCHPAD"

                # TIER 3: 🛡️ EMA PULLBACK COIL (Leader resting on rising 10/20 EMA Support)
                elif (abs(dist_ema10_pct) <= 1.50 or abs(dist_ema20_pct) <= 1.50) and (vcp_ratio_3d <= 1.35 or is_inside_day):
                    is_tier3 = True
                    tier_label = "TIER 3"
                    coil_tag = "🛡️ EMA PULLBACK COIL"

                if not (is_tier1 or is_tier2 or is_tier3):
                    return None  # Disqualified: Not at breakout doorstep, launchpad base, or EMA shelf

                # CRITERION 5: Relative Volume (RVOL)
                avg_vol_20 = sum(v_list[-20:]) / 20.0 if len(v_list) >= 20 else 1.0
                live_vol = item["vol"]
                proj_vol = live_vol * pacing_factor
                proj_rvol = round(proj_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

                # VDU (Volume Dry-Up) Supply Exhaustion
                is_vdu = proj_rvol <= 0.60

                # Quantified Scoring:
                score = 70.0
                if is_tier1:
                    score += 15.0  # Immediate breakout doorstep priority
                elif is_tier2:
                    score += 10.0  # Launchpad base bonus
                elif is_tier3:
                    score += 8.0   # EMA pullback shelf bonus

                if is_near_3m_high:
                    score += 10.0  # Zero overhead resistance blue sky bonus
                if is_vdu:
                    score += 8.0   # Supply exhaustion bonus
                if is_inside_day:
                    score += 6.0   # Range contraction coil bonus

                # Contraction scoring (uses tighter of 5D or 3D)
                score += max(0.0, (2.2 - min(vcp_ratio_5d, vcp_ratio_3d * 1.8)) * 12.0)
                # Tighter daily range = higher score
                score += max(0.0, (2.0 - item["daily_range_pct"]) * 8.0)
                # Closeness to 20-day high = higher breakout ignition potential
                score += max(0.0, (2.0 - dist_pivot_20d_pct) * 8.0)
                # Closeness to PDH = immediate morning ORB trigger potential
                score += max(0.0, (1.5 - abs(dist_pdh_pct)) * 8.0)

                # Volume tagging
                if is_vdu:
                    vol_tag = f"🧊 RVOL {proj_rvol}x (VDU Supply Dry-Up)"
                elif proj_rvol >= 1.30:
                    score += min(15.0, (proj_rvol - 1.0) * 8.0)
                    vol_tag = f"🔥 RVOL {proj_rvol}x (Surge)"
                elif proj_rvol <= 0.75:
                    score += 8.0
                    vol_tag = f"🧊 RVOL {proj_rvol}x (Dry Vol)"
                else:
                    vol_tag = f"⚪ RVOL {proj_rvol}x (Normal)"

                # Liquidity boost
                if item["turnover_cr"] >= 25.0:
                    score += 5.0

                # CRITERION 6: Sector Tailwind Overlay (NEVER penalizes or removes unmapped stocks!)
                ind = item.get("industry", "Equity")
                mapped_sec = INDUSTRY_TO_SECTOR.get(ind)
                sec_chg = sector_perf.get(mapped_sec)

                if mapped_sec and mapped_sec in top_3_sectors:
                    sector_tag = f"⭐ {mapped_sec.replace('Nifty ', '')} Leader ({sec_chg:+.1f}%)"
                    sector_score = 10.0
                elif mapped_sec and sec_chg is not None and sec_chg > 0:
                    sector_tag = f"📈 {mapped_sec.replace('Nifty ', '')} ({sec_chg:+.1f}%)"
                    sector_score = 5.0
                elif mapped_sec and sec_chg is not None:
                    sector_tag = f"⚪ {mapped_sec.replace('Nifty ', '')} ({sec_chg:+.1f}%)"
                    sector_score = 2.0
                else:
                    # Non-sector / unmapped industry: keep industry name, award baseline score (NEVER DISQUALIFIED!)
                    sector_tag = f"🏢 {ind}"
                    sector_score = 3.0

                score += sector_score

                flags = []
                if is_near_3m_high:
                    flags.append("👑 52W High")
                if is_vdu:
                    flags.append("🧊 VDU")
                if is_inside_day:
                    flags.append("📦 Inside Day")

                res_item = dict(item)
                res_item.update({
                    "tier": tier_label,
                    "ema20": round(ema20, 2),
                    "ema50": round(ema50, 2),
                    "atr14": round(atr14, 2),
                    "vcp_ratio_5d": vcp_ratio_5d,
                    "vcp_ratio_3d": vcp_ratio_3d,
                    "is_inside_day": is_inside_day,
                    "is_vdu": is_vdu,
                    "is_near_3m_high": is_near_3m_high,
                    "flags": flags,
                    "pivot_20d": round(pivot_20d, 2),
                    "dist_pivot_20d_pct": dist_pivot_20d_pct,
                    "dist_pivot_atr": dist_pivot_atr,
                    "pdh": round(pdh, 2),
                    "dist_pdh_pct": dist_pdh_pct,
                    "proj_rvol": proj_rvol,
                    "vol_tag": vol_tag,
                    "sector_tag": sector_tag,
                    "sector_score": sector_score,
                    "score": round(score, 1),
                    "coil_tag": coil_tag
                })
                return res_item
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=25) as executor:
        stage2_results = list(executor.map(analyze_candidate, stage1_shortlist))

    qualified = [r for r in stage2_results if r is not None]
    qualified.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = qualified[:top_n]

    # Leading Sector Definitions from Market Breadth & Tape Analysis
    LEADING_SECTOR_MAP = {
        "Information Technology": "⭐ IT Leader (Stage 2 Uptrend)",
        "Healthcare": "⭐ Pharma Leader (Stage 2 Uptrend)",
        "Automobile and Auto Components": "📈 Auto Leader (Stage 1 Reclaim)",
        "Realty": "🚀 Realty Leader (Stage 1 Turnaround)",
        "Fast Moving Consumer Goods": "🚀 FMCG Leader (Thrust Rebound)",
        "Capital Goods": "🚀 Infra/CapGoods Leader (Stage 1 Breakout)",
        "Construction": "🚀 Infra Leader (Stage 1 Breakout)",
        "Media": "🎯 Media Leader (Base Turnaround)"
    }

    # Apply Base-Anchored / Stretch & Sectoral Picks Partitioning
    for c in top_candidates:
        ltp = c.get("ltp", 0.0)
        ema20 = c.get("ema20", ltp)
        dist_ema20_pct = round(((ltp - ema20) / ltp) * 100.0, 2) if ltp > 0 else 0.0
        c["dist_ema20_pct"] = dist_ema20_pct
        ind = c.get("industry", "")
        sec_leader_tag = LEADING_SECTOR_MAP.get(ind)

        # Base-Anchored vs Extended sub-tiering
        tier_base = c.get("tier", "TIER 1")
        if tier_base == "TIER 1":
            if dist_ema20_pct <= 4.50:
                c["tier"] = "TIER 1A"
                c["tier_label"] = "Tier 1A: Base-Anchored Doorstep"
                c["stretch_status"] = "LOW_STRETCH"
            elif dist_ema20_pct <= 5.50:
                c["tier"] = "TIER 1B"
                c["tier_label"] = "Tier 1B: Mid-Base Consolidation"
                c["stretch_status"] = "MID_STRETCH"
            else:
                c["tier"] = "TIER 1C"
                c["tier_label"] = "Tier 1C: Extended Flagpole"
                c["stretch_status"] = "HIGH_STRETCH"

        # Sectoral Picks Classification: Leading Sector + Base-Anchored (dist_ema20 <= 4.5% or Tier 2/3)
        if sec_leader_tag and (dist_ema20_pct <= 4.50 or c.get("tier") in ("TIER 2", "TIER 3", "TIER 1A")):
            c["is_sectoral_pick"] = True
            c["tier"] = "SECTORAL PICKS"
            c["tier_label"] = f"Sectoral Picks: {sec_leader_tag.split('(')[0].strip()}"
            c["coil_tag"] = "🎯 SECTORAL BASE"
            c["sector_tag"] = sec_leader_tag
            if "🎯 Sector Leader" not in c.get("flags", []):
                c.setdefault("flags", []).insert(0, "🎯 Sector Leader")

    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    lines = [
        f"# JARVIS PRE-BREAKOUT SWING CANDIDATES (NIFTY 500) — {now_str}",
        "# Setup: Multi-Tier Coils, Pullbacks & Sectoral Rotation Picks (Price >= 20 EMA, Dual VCP, Min ₹5.0 Cr)",
        "# Strategy: Tomorrow's 3m ORB + PDH Breakout with Day Low SL (NOT Extended!)",
        "# Tiers: [🌟 SECTORAL PICKS] | [🔥 TIER 1A: Base-Anchored] | [⚡ TIER 1B: Mid-Base] | [🚩 TIER 1C: Extended] | [🚀 TIER 2] | [🛡️ TIER 3]",
        "# Badges: 👑 52W High Doorstep | 🧊 VDU Supply Dry-Up | 📦 Inside Day Compression | 🎯 Sector Leader",
        "# Review on TradingView and tap button or use `/add <SYMBOL>` in Telegram to promote to watchlist.txt",
        "# ==========================================================================================",
        ""
    ]
    for c in top_candidates:
        flag_str = f" | {' '.join(c.get('flags', []))}" if c.get('flags') else ""
        lines.append(
            f"{c['symbol']}  # ₹{c['ltp']:,.2f} | [{c['tier']}] {c['coil_tag']}{flag_str} | 20D Dist: {c['dist_pivot_20d_pct']:+.2f}% ({c['dist_pivot_atr']}x ATR) | "
            f"PDH Dist: {c['dist_pdh_pct']:+.2f}% | 5D/3D VCP: {c['vcp_ratio_5d']}x/{c.get('vcp_ratio_3d', 'N/A')}x ATR | Range: {c['daily_range_pct']:.2f}% | {c['vol_tag']} | {c.get('sector_tag', c.get('industry', 'Equity'))} | Move: {c['change_pct']:+.1f}% | ₹{c['turnover_cr']:,.1f} Cr"
        )

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    with open(CANDIDATES_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": now_str,
            "count": len(top_candidates),
            "strategy": "Multi-Tier Stage 2 VCP Pre-Breakout & Sectoral Base Engine",
            "sectoral_count": sum(1 for c in top_candidates if c.get("tier") == "SECTORAL PICKS"),
            "tier1a_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 1A"),
            "tier1b_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 1B"),
            "tier1c_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 1C"),
            "tier2_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 2"),
            "tier3_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 3"),
            "candidates": top_candidates
        }, f, indent=2)

    return {
        "status": "success",
        "updated_at": now_str,
        "count": len(top_candidates),
        "tier1_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 1"),
        "tier2_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 2"),
        "total_scanned": len(all_quotes),
        "stage1_passed": len(stage1_shortlist),
        "candidates": top_candidates
    }


def format_candidates_telegram_card(res, max_display=10, is_morning=False):
    """
    Formats rich Telegram review card showing Tier 1 Pivot Doorsteps and Tier 2 Base Launchpads with 1-tap Add buttons.
    """
    if res.get("status") != "success":
        return f"⚠️ <b>Candidate Scan Notice:</b> {res.get('message', 'Scan failed')}", None

    candidates = res.get("candidates", [])
    if not candidates:
        return "ℹ️ <b>No stocks met today's Stage 2 VCP Coil threshold (Trend > 20/50 EMA, 5D range ≤ 2.5x ATR & near pivot/PDH).</b>", None

    if is_morning:
        lines = [
            "☀️ <b>JARVIS 09:10 AM PRE-MARKET CANDIDATES BRIEFING</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "<i>Top Nifty 500 Stage-2 VCP setups primed for today's 3m ORB + PDH breakout</i>\n"
        ]
    else:
        lines = [
            "🎯 <b>NIFTY 500 INSTITUTIONAL SWING CANDIDATES</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "<i>Stage 2 VCP Coils poised for tomorrow's 3m ORB + PDH breakout</i>\n"
        ]

    sectoral = [c for c in candidates if c.get("tier") == "SECTORAL PICKS" or c.get("is_sectoral_pick")]
    tier1 = [c for c in candidates if "TIER 1" in (c.get("tier") or "") and not c.get("is_sectoral_pick")]
    tier2 = [c for c in candidates if "TIER 2" in (c.get("tier") or "") and not c.get("is_sectoral_pick")]
    tier3 = [c for c in candidates if "TIER 3" in (c.get("tier") or "") and not c.get("is_sectoral_pick")]

    if sectoral:
        lines.append("🌟 <b>SECTORAL PICKS: LEADING SECTOR BASES (≤4.5% 20 EMA)</b>")
        for i, c in enumerate(sectoral[:5], 1):
            sym = c["symbol"]
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
            pdh_status = "Cleared!" if c["dist_pdh_pct"] < 0 else f"{c['dist_pdh_pct']:+.2f}%"
            badge_str = f" • {' '.join(c.get('flags', []))}" if c.get('flags') else ""
            lines.append(
                f"<b>{i}.</b> 🎯 {tv_link} (₹{c['ltp']:,.2f}){badge_str}\n"
                f"   • Sits: <b>{c['dist_pivot_20d_pct']:+.2f}%</b> from 20D | 20 EMA: <b>{c.get('dist_ema20_pct', 0.0):+.2f}%</b>\n"
                f"   • VCP: <b>{c['vcp_ratio_5d']}x ATR</b> | {c.get('sector_tag', c.get('industry'))}"
            )
        lines.append("")

    if tier1:
        lines.append("🔥 <b>TIER 1: PIVOT DOORSTEP (Direct 20D Breakouts)</b>")
        for i, c in enumerate(tier1[:6], 1):
            sym = c["symbol"]
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
            pdh_status = "Cleared!" if c["dist_pdh_pct"] < 0 else f"{c['dist_pdh_pct']:+.2f}%"
            badge_str = f" • {' '.join(c.get('flags', []))}" if c.get('flags') else ""
            vcp_str = f"{c['vcp_ratio_5d']}x (5D) / {c.get('vcp_ratio_3d', 'N/A')}x (3D)"
            lines.append(
                f"<b>{i}.</b> {c['coil_tag'][:2]} {tv_link} (₹{c['ltp']:,.2f}){badge_str}\n"
                f"   • Sits: <b>{c['dist_pivot_20d_pct']:+.2f}%</b> from 20D High | PDH: <b>{pdh_status}</b>\n"
                f"   • VCP: <b>{vcp_str} ATR</b> | {c['vol_tag']}\n"
                f"   • Move: <b>{c['change_pct']:+.1f}%</b> (₹{c['turnover_cr']:,.1f} Cr) | Sector: <b>{c.get('sector_tag', c.get('industry', 'Equity'))}</b>"
            )
        lines.append("")

    if tier2:
        lines.append("🚀 <b>TIER 2: BASE LAUNCHPAD (10/20 EMA Pocket Coils)</b>")
        for i, c in enumerate(tier2[:3], 1):
            sym = c["symbol"]
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
            pdh_status = "Cleared!" if c["dist_pdh_pct"] < 0 else f"{c['dist_pdh_pct']:+.2f}%"
            badge_str = f" • {' '.join(c.get('flags', []))}" if c.get('flags') else ""
            lines.append(
                f"<b>{i}.</b> 🚀 {tv_link} (₹{c['ltp']:,.2f}){badge_str}\n"
                f"   • 20D Dist: <b>{c['dist_pivot_20d_pct']:+.2f}% ({c['dist_pivot_atr']}x ATR)</b> | PDH: <b>{pdh_status}</b>\n"
                f"   • 5D VCP: <b>{c['vcp_ratio_5d']}x ATR</b> | {c['vol_tag']} | Move: <b>{c['change_pct']:+.1f}%</b>\n"
                f"   • Sector: <b>{c.get('sector_tag', c.get('industry', 'Equity'))}</b>"
            )
        lines.append("")

    if tier3:
        lines.append("🛡️ <b>TIER 3: EMA PULLBACK COIL (10/20 EMA Support Shelf)</b>")
        for i, c in enumerate(tier3[:3], 1):
            sym = c["symbol"]
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
            badge_str = f" • {' '.join(c.get('flags', []))}" if c.get('flags') else ""
            lines.append(
                f"<b>{i}.</b> 🛡️ {tv_link} (₹{c['ltp']:,.2f}){badge_str}\n"
                f"   • Shelf: <b>Held 10/20 EMA Support</b> | 20D Dist: <b>{c['dist_pivot_20d_pct']:+.2f}%</b>\n"
                f"   • VCP: <b>{c.get('vcp_ratio_3d', 'N/A')}x (3D)</b> | {c['vol_tag']} | Move: <b>{c['change_pct']:+.1f}%</b>\n"
                f"   • Sector: <b>{c.get('sector_tag', c.get('industry', 'Equity'))}</b>"
            )
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Tap below to add vetted candidates to the 3m scanner watchlist:</i>")

    kb_rows = []
    display_candidates = (sectoral[:4] + tier1[:3] + tier2[:2] + tier3[:1])[:max_display]
    if display_candidates:
        kb_rows.append([{"text": "⚡ ➕ Add All Top 5 to Watchlist", "callback_data": "cand_add_top5"}])

    btn_row = []
    for c in display_candidates:
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


def send_morning_candidate_card():
    """
    Dispatches the 09:10 AM Pre-Market Candidate Briefing card to Telegram.
    Reads candidates.json (or triggers fresh scan if missing).
    """
    cfg = load_config()
    tg_token = cfg.get("telegram", {}).get("bot_token")
    tg_chat_id = cfg.get("telegram", {}).get("chat_id")
    if not tg_token or not tg_chat_id:
        print("❌ Telegram credentials missing in config_credentials.json")
        return False

    res = None
    if CANDIDATES_JSON.is_file():
        try:
            with open(CANDIDATES_JSON, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if cdata.get("candidates"):
                    res = {
                        "status": "success",
                        "updated_at": cdata.get("updated_at", ""),
                        "count": cdata.get("count", 0),
                        "candidates": cdata.get("candidates", [])
                    }
        except Exception as e:
            print(f"Error loading candidates.json: {e}")

    if not res or not res.get("candidates"):
        print("Candidates cache missing or empty. Running fresh scan...")
        res = scan_nifty500_candidates(top_n=15)

    text, reply_markup = format_candidates_telegram_card(res, max_display=10, is_morning=True)

    tg_group_id = cfg.get("telegram", {}).get("group_id")
    topics = cfg.get("telegram", {}).get("topics", {})
    thread_id = topics.get("reports") if tg_group_id else None
    target_chat = tg_group_id if (tg_group_id and thread_id) else tg_chat_id

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 200:
                print("✅ 09:10 AM Morning Candidate Briefing Card dispatched successfully to Telegram!")
                return True
            else:
                print(f"❌ Telegram API returned HTTP status {resp.status}")
                return False
    except Exception as e:
        print(f"❌ Failed to dispatch Telegram morning card: {e}")
        return False


def sync_candidates_to_github():
    """Pushes candidates.json and candidates.txt to GitHub via REST API and purges jsDelivr CDN."""
    cfg = load_config()
    gh_cfg = cfg.get("github", {})
    token = gh_cfg.get("token", "").strip()
    if not token:
        return False
    owner = gh_cfg.get("username", "sanIncredible").strip()
    repo = gh_cfg.get("repo", "Jarvis").strip()
    branch = gh_cfg.get("branch", "main").strip()

    import base64
    for file_path in [CANDIDATES_JSON, CANDIDATES_FILE]:
        if not file_path.is_file():
            continue
        fname = file_path.name
        try:
            with open(file_path, "rb") as f:
                content_b64 = base64.b64encode(f.read()).decode("ascii")
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{fname}"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Jarvis-Candidate-Scanner"
            }
            req = urllib.request.Request(f"{url}?ref={branch}", headers=headers)
            sha = None
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    d = json.loads(r.read().decode("utf-8"))
                    sha = d.get("sha")
            except Exception:
                pass

            payload = {
                "message": f"Auto EOD Candidate Scan ({fname})",
                "content": content_b64,
                "branch": branch
            }
            if sha:
                payload["sha"] = sha
            data = json.dumps(payload).encode("utf-8")
            put_req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
            with urllib.request.urlopen(put_req, timeout=10) as r:
                if r.status in (200, 201):
                    print(f"   ✅ GitHub synced: {fname}")
        except Exception as e:
            print(f"   ⚠️ GitHub sync notice for {fname}: {e}")

    try:
        purge_url = "https://purge.jsdelivr.net/gh/sanIncredible/Jarvis@main/candidates.json"
        p_req = urllib.request.Request(purge_url, headers={"User-Agent": "Jarvis-Purge"})
        with urllib.request.urlopen(p_req, timeout=4):
            pass
        print("   ⚡ jsDelivr CDN cache purged for candidates.json!")
    except Exception:
        pass
    return True


def send_eod_candidate_card(res=None):
    """Dispatches the EOD Candidates Review card to Telegram with 1-tap watchlist add buttons."""
    cfg = load_config()
    tg_token = cfg.get("telegram", {}).get("bot_token")
    tg_chat_id = cfg.get("telegram", {}).get("chat_id")
    if not tg_token or not tg_chat_id:
        return False

    if not res:
        if CANDIDATES_JSON.is_file():
            try:
                with open(CANDIDATES_JSON, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    res = {"status": "success", "candidates": cdata.get("candidates", [])}
            except Exception:
                pass
    if not res or not res.get("candidates"):
        return False

    text, reply_markup = format_candidates_telegram_card(res, max_display=10, is_morning=False)

    tg_group_id = cfg.get("telegram", {}).get("group_id")
    topics = cfg.get("telegram", {}).get("topics", {})
    thread_id = topics.get("reports") if tg_group_id else None
    target_chat = tg_group_id if (tg_group_id and thread_id) else tg_chat_id

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 200:
                print("✅ EOD Candidate Review Card dispatched successfully to Telegram!")
                return True
    except Exception as e:
        print(f"⚠️ Telegram EOD card dispatch notice: {e}")
    return False


if __name__ == "__main__":
    if "--morning-card" in sys.argv:
        print("=" * 85)
        print("⚡ DISPATCHING 09:10 AM PRE-MARKET CANDIDATES BRIEFING CARD...")
        print("=" * 85)
        send_morning_candidate_card()
    else:
        print("=" * 85)
        print("⚡ SCANNING NIFTY 500 DUAL-TIER STAGE-2 VCP COIL CANDIDATES...")
        print("=" * 85)
        res = scan_nifty500_candidates()
        if res.get("status") == "success":
            print(f"✅ Filtered {res['count']} Setups from {res['total_scanned']} stocks (Sectoral: {res.get('sectoral_count', 0)} | Tier 1A: {res.get('tier1a_count', 0)} | Tier 1B: {res.get('tier1b_count', 0)} | Tier 1C: {res.get('tier1c_count', 0)} | Tier 2: {res.get('tier2_count', 0)} | Tier 3: {res.get('tier3_count', 0)})!")
            print(f"📁 Saved to: {CANDIDATES_FILE.name}")
            
            # Auto-sync to GitHub Cloud Repo & purge CDN
            sync_candidates_to_github()

            # Auto-dispatch EOD Telegram card if market closed or notified
            send_eod_candidate_card(res)

            for i, c in enumerate(res["candidates"], 1):
                print(
                    f"{i:<2}. {c['symbol']:<12} ₹{c['ltp']:<9.2f} | [{c['tier']}] {c['coil_tag']:<18} | 20D Dist: {c['dist_pivot_20d_pct']:>+5.2f}% ({c['dist_pivot_atr']}x ATR) | "
                    f"PDH: {c['dist_pdh_pct']:>+5.2f}% | 5D VCP: {c['vcp_ratio_5d']}x ATR | Range: {c['daily_range_pct']:.2f}% | {c['vol_tag']:<22} | Move: {c['change_pct']:+5.1f}% | ₹{c['turnover_cr']:<5.1f} Cr"
                )
        else:
            print(f"❌ Error: {res.get('message')}")
