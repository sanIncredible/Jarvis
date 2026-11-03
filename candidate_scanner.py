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
    top_n=20,
    max_range_pct=2.60,
    max_from_high_pct=2.20,
    min_turnover_cr=5.0
):
    """
    Two-Stage Dual-Tier Screener:
    - Stage 1: Fast bulk Upstox snapshot to eliminate illiquid, penny, or extended runners.
    - Stage 2: Concurrent multi-day historical candles via Yahoo Finance (25 threads) evaluating:
      1. Stage 2 Trend (Price > 20 EMA > 50 EMA)
      2. Volatility Contraction Pattern (5D VCP <= 2.5x ATR14)
      3. Relative Volume (RVOL)
      4. Dual-Tier Resistance Proximity:
         - Tier 1 (🔥 Pivot Doorstep): <= 2.2% from 20D High or <= 1.0x ATR
         - Tier 2 (🚀 Base Launchpad): <= 5.0% from 20D High and <= 2.2% from PDH
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
        # 1. Non-Extended Move: -2.0% <= change_pct <= +3.5% (Not +8% chasing!)
        # 2. Narrow Range Bar: daily_range_pct <= max_range_pct (<= 2.6%)
        # 3. Sitting Near Today's High: dist_from_high_pct <= max_from_high_pct (<= 2.2%)
        # 4. Closing in Upper Half: close_loc >= 0.45
        if (-2.0 <= change_pct <= 3.5) and daily_range_pct <= max_range_pct and dist_from_high_pct <= max_from_high_pct and close_loc >= 0.45:
            raw_sym = q.get("symbol", "").replace("NSE_EQ:", "").strip()
            sym = isin_to_meta.get(key, {}).get("symbol", raw_sym)
            name = isin_to_meta.get(key, {}).get("name", sym)
            industry = isin_to_meta.get(key, {}).get("industry", "Equity")
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

                # VCP condition: 5-day range <= 2.50x ATR (or 3-day <= 1.40x ATR)
                if vcp_ratio_5d > 2.50 and vcp_ratio_3d > 1.40:
                    return None  # Disqualified: Wide swing / volatile

                # CRITERION 3 & 4: Dual-Tier Resistance Pivot Proximity (20D Pivot & PDH)
                pivot_20d = max(h_list[-20:])
                dist_pivot_20d_pct = round(((pivot_20d - ltp) / pivot_20d) * 100.0, 2)
                dist_pivot_atr = round((pivot_20d - ltp) / atr14, 2) if atr14 > 0 else 9.9
                pdh = h_list[-2] if len(h_list) >= 2 else h_list[-1]
                dist_pdh_pct = round(((pdh - ltp) / pdh) * 100.0, 2)

                is_tier1 = False
                is_tier2 = False
                tier_label = ""
                coil_tag = ""

                # TIER 1: 🔥 PIVOT DOORSTEP (Direct 20D Breakout Ignition)
                # Sits within <= 2.2% of 20D High OR within <= 1.0x ATR, with 5D VCP <= 2.50x ATR
                if (dist_pivot_20d_pct <= 2.20 or dist_pivot_atr <= 1.00) and vcp_ratio_5d <= 2.50:
                    is_tier1 = True
                    tier_label = "TIER 1"
                    coil_tag = "🔥 PIVOT DOORSTEP" if vcp_ratio_5d <= 1.60 else "⚡ PIVOT IGNITION"

                # TIER 2: 🚀 BASE LAUNCHPAD (10/20 EMA Pocket Coil — Early Asymmetrical R:R)
                # Sits 2.2% to 5.0% from 20D High (or <= 1.5x ATR), sitting near PDH (<= 2.2%), with tight VCP (<= 2.40x ATR)
                elif (dist_pivot_20d_pct <= 5.00 or dist_pivot_atr <= 1.50) and (abs(dist_pdh_pct) <= 2.20) and vcp_ratio_5d <= 2.40:
                    is_tier2 = True
                    tier_label = "TIER 2"
                    coil_tag = "🚀 BASE LAUNCHPAD"

                if not (is_tier1 or is_tier2):
                    return None  # Disqualified: Too far from resistance or not coiled

                # CRITERION 5: Relative Volume (RVOL)
                avg_vol_20 = sum(v_list[-20:]) / 20.0 if len(v_list) >= 20 else 1.0
                live_vol = item["vol"]
                proj_vol = live_vol * pacing_factor
                proj_rvol = round(proj_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

                # Quantified Scoring:
                score = 70.0
                if is_tier1:
                    score += 15.0  # Priority for immediate 20-day breakout
                else:
                    score += 10.0  # Pocket launchpad base bonus

                # Tighter 5D VCP = higher score
                score += max(0.0, (2.2 - vcp_ratio_5d) * 15.0)
                # Tighter daily range = higher score
                score += max(0.0, (2.0 - item["daily_range_pct"]) * 10.0)
                # Closeness to 20-day high = higher breakout ignition potential
                score += max(0.0, (2.0 - dist_pivot_20d_pct) * 8.0)
                # Closeness to PDH = immediate morning ORB trigger potential
                score += max(0.0, (1.5 - abs(dist_pdh_pct)) * 8.0)

                # Volume scoring: either volume expansion (>=1.3x) or supply dry-up (<=0.75x)
                if proj_rvol >= 1.3:
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

                res_item = dict(item)
                res_item.update({
                    "tier": tier_label,
                    "ema20": round(ema20, 2),
                    "ema50": round(ema50, 2),
                    "atr14": round(atr14, 2),
                    "vcp_ratio_5d": vcp_ratio_5d,
                    "vcp_ratio_3d": vcp_ratio_3d,
                    "pivot_20d": round(pivot_20d, 2),
                    "dist_pivot_20d_pct": dist_pivot_20d_pct,
                    "dist_pivot_atr": dist_pivot_atr,
                    "pdh": round(pdh, 2),
                    "dist_pdh_pct": dist_pdh_pct,
                    "proj_rvol": proj_rvol,
                    "vol_tag": vol_tag,
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

    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    lines = [
        f"# JARVIS PRE-BREAKOUT SWING CANDIDATES (NIFTY 500) — {now_str}",
        "# Setup: Dual-Tier VCP Coils (Stage 2 Uptrend: Price > 20 EMA > 50 EMA, 5D VCP <= 2.5x ATR, Min ₹5.0 Cr)",
        "# Strategy: Tomorrow's 3m ORB + PDH Breakout with Day Low SL (NOT Extended!)",
        "# Tiers: [TIER 1 = 🔥 Pivot Doorstep (<=2.2% from 20D)] | [TIER 2 = 🚀 Base Launchpad (2.2%-5.0% from 20D & near PDH)]",
        "# Review on TradingView and tap button or use `/add <SYMBOL>` in Telegram to promote to watchlist.txt",
        "# ==========================================================================================",
        ""
    ]
    for c in top_candidates:
        lines.append(
            f"{c['symbol']}  # ₹{c['ltp']:,.2f} | [{c['tier']}] {c['coil_tag']} | 20D Dist: {c['dist_pivot_20d_pct']:+.2f}% ({c['dist_pivot_atr']}x ATR) | "
            f"PDH Dist: {c['dist_pdh_pct']:+.2f}% | 5D VCP: {c['vcp_ratio_5d']}x ATR | Range: {c['daily_range_pct']:.2f}% | {c['vol_tag']} | Move: {c['change_pct']:+.1f}% | ₹{c['turnover_cr']:,.1f} Cr | {c['industry']}"
        )

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    with open(CANDIDATES_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": now_str,
            "count": len(top_candidates),
            "strategy": "Dual-Tier Stage 2 VCP Pre-Breakout Coil Engine",
            "tier1_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 1"),
            "tier2_count": sum(1 for c in top_candidates if c.get("tier") == "TIER 2"),
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


def format_candidates_telegram_card(res, max_display=10):
    """
    Formats rich Telegram review card showing Tier 1 Pivot Doorsteps and Tier 2 Base Launchpads with 1-tap Add buttons.
    """
    if res.get("status") != "success":
        return f"⚠️ <b>Candidate Scan Notice:</b> {res.get('message', 'Scan failed')}", None

    candidates = res.get("candidates", [])
    if not candidates:
        return "ℹ️ <b>No stocks met today's Stage 2 VCP Coil threshold (Trend > 20/50 EMA, 5D range ≤ 2.5x ATR & near pivot/PDH).</b>", None

    lines = [
        "🎯 <b>NIFTY 500 INSTITUTIONAL SWING CANDIDATES</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<i>Stage 2 VCP Coils poised for tomorrow's 3m ORB + PDH breakout</i>\n"
    ]

    tier1 = [c for c in candidates if c.get("tier") == "TIER 1"]
    tier2 = [c for c in candidates if c.get("tier") == "TIER 2"]

    if tier1:
        lines.append("🔥 <b>TIER 1: PIVOT DOORSTEP (Direct 20D Breakout)</b>")
        for i, c in enumerate(tier1[:6], 1):
            sym = c["symbol"]
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
            pdh_status = "Cleared!" if c["dist_pdh_pct"] < 0 else f"{c['dist_pdh_pct']:+.2f}%"
            lines.append(
                f"<b>{i}.</b> {c['coil_tag'][:2]} {tv_link} (₹{c['ltp']:,.2f})\n"
                f"   • Sits: <b>{c['dist_pivot_20d_pct']:+.2f}%</b> from 20D High | PDH: <b>{pdh_status}</b>\n"
                f"   • 5D VCP: <b>{c['vcp_ratio_5d']}x ATR</b> | {c['vol_tag']} | Move: {c['change_pct']:+.1f}% (₹{c['turnover_cr']:,.1f} Cr)"
            )
        lines.append("")

    if tier2:
        lines.append("🚀 <b>TIER 2: BASE LAUNCHPAD (10/20 EMA Pocket Coils)</b>")
        for i, c in enumerate(tier2[:4], 1):
            sym = c["symbol"]
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
            pdh_status = "Cleared!" if c["dist_pdh_pct"] < 0 else f"{c['dist_pdh_pct']:+.2f}%"
            lines.append(
                f"<b>{i}.</b> 🚀 {tv_link} (₹{c['ltp']:,.2f})\n"
                f"   • 20D Dist: <b>{c['dist_pivot_20d_pct']:+.2f}% ({c['dist_pivot_atr']}x ATR)</b> | PDH: <b>{pdh_status}</b>\n"
                f"   • 5D VCP: <b>{c['vcp_ratio_5d']}x ATR</b> | {c['vol_tag']} | Move: {c['change_pct']:+.1f}% (₹{c['turnover_cr']:,.1f} Cr)"
            )
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Tap below to add vetted candidates to tomorrow's 3m scanner:</i>")

    kb_rows = []
    btn_row = []
    display_candidates = (tier1[:6] + tier2[:4])[:max_display]
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


if __name__ == "__main__":
    print("=" * 85)
    print("⚡ SCANNING NIFTY 500 DUAL-TIER STAGE-2 VCP COIL CANDIDATES...")
    print("=" * 85)
    res = scan_nifty500_candidates()
    if res.get("status") == "success":
        print(f"✅ Filtered {res['count']} Setups from {res['total_scanned']} stocks (Tier 1: {res['tier1_count']} | Tier 2: {res['tier2_count']})!")
        print(f"📁 Saved to: {CANDIDATES_FILE.name}")
        for i, c in enumerate(res["candidates"], 1):
            print(
                f"{i:<2}. {c['symbol']:<12} ₹{c['ltp']:<9.2f} | [{c['tier']}] {c['coil_tag']:<18} | 20D Dist: {c['dist_pivot_20d_pct']:>+5.2f}% ({c['dist_pivot_atr']}x ATR) | "
                f"PDH: {c['dist_pdh_pct']:>+5.2f}% | 5D VCP: {c['vcp_ratio_5d']}x ATR | Range: {c['daily_range_pct']:.2f}% | {c['vol_tag']:<22} | Move: {c['change_pct']:+5.1f}% | ₹{c['turnover_cr']:<5.1f} Cr"
            )
    else:
        print(f"❌ Error: {res.get('message')}")
