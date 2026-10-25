#!/usr/bin/env python3
"""
⚡ JARVIS DAILY POSITIONAL SWING REGIME DETECTOR
Institutional Breadth Engine based on Pradeep Bonde & Chhirag Kedia Master Model.
Evaluates 6 Institutional Layers to mandate exact swing risk, setup permissions, and stop rules.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
WORKBOOK_FILE = BASE_DIR / "Market Breadth V2.0.xlsm"
POSITIONAL_REGIME_FILE = BASE_DIR / "daily_positional_regime.json"
CONFIG_FILE = BASE_DIR / "config_credentials.json"

def load_latest_positional_metrics():
    """
    Reads the latest session metrics from Market Breadth V2.0.xlsm (or cached EOD).
    """
    if not WORKBOOK_FILE.is_file():
        raise FileNotFoundError(f"Master workbook not found: {WORKBOOK_FILE}")

    import openpyxl
    wb = openpyxl.load_workbook(WORKBOOK_FILE, data_only=True)
    ws_data = wb["Data"]

    headers = [c for c in next(ws_data.iter_rows(max_row=1, values_only=True))]
    col_map = {h: idx for idx, h in enumerate(headers) if h is not None}

    # Find last non-empty row
    last_row = None
    prev_row = None
    for r in ws_data.iter_rows(min_row=2, values_only=True):
        if r[0] is not None:
            prev_row = last_row
            last_row = r

    wb.close()

    if not last_row:
        raise ValueError("No data rows found in Data sheet.")

    def parse_val(r, col_name, default=0.0):
        idx = col_map.get(col_name)
        if idx is not None and idx < len(r) and r[idx] is not None:
            try:
                return float(r[idx])
            except:
                return default
        return default

    date_val = str(last_row[0])[:10]
    univ = parse_val(last_row, "Total Universe", 1.0)
    if univ <= 0: univ = 1.0

    nifty = parse_val(last_row, "Nifty 50", 0.0)
    smallcap = parse_val(last_row, "Small Cap 100", 0.0)
    u4 = parse_val(last_row, "4% Up", 0.0)
    d4 = parse_val(last_row, "4% Down", 0.0)
    
    bo = parse_val(last_row, "Breakouts", 0.0)
    bo_s = parse_val(last_row, "Breakout Sustained", 0.0)
    bo_f = parse_val(last_row, "Breakout Failure", 0.0)
    bo_sf = round(bo_s / bo_f, 2) if bo_f > 0 else (2.0 if bo_s > 0 else 1.0)
    
    bd = parse_val(last_row, "Breakdowns", 0.0)
    bd_s = parse_val(last_row, "Breakdown Sustained", 0.0)
    bd_f = parse_val(last_row, "Breakdown Failure", 0.0)
    bd_sf = round(bd_s / bd_f, 2) if bd_f > 0 else (2.0 if bd_s > 0 else 1.0)

    u15_5 = int(parse_val(last_row, "15% up in 5 days", 0.0))
    u25_20 = int(parse_val(last_row, "25% up in 20 days", 0.0))
    d25_20 = int(parse_val(last_row, "25% down in 20 days", 0.0))

    ab_10 = parse_val(last_row, "Above 10 DEMA", 0.0)
    ab_20 = parse_val(last_row, "Above 20 DEMA", 0.0)
    ab_50 = parse_val(last_row, "Above 50 DEMA", 0.0)
    ab_200 = parse_val(last_row, "Above 200 DEMA", 0.0)

    pct_ab_10 = round((ab_10 / univ) * 100, 1)
    pct_ab_20 = round((ab_20 / univ) * 100, 1)
    pct_ab_50 = round((ab_50 / univ) * 100, 1)
    pct_ab_200 = round((ab_200 / univ) * 100, 1)

    nh = int(parse_val(last_row, "52 Week High", 0.0))
    nl = int(parse_val(last_row, "52 Week Low", 0.0))
    net_nh_nl = nh - nl

    w15_wh = int(parse_val(last_row, "15% from 52WH", 0.0))
    w15_wl = int(parse_val(last_row, "15% from 52WL", 0.0))

    rng_5 = parse_val(last_row, "Range 5.01% +", 0.0)
    uh = parse_val(last_row, "Close Upper Half", 0.0)
    lh = parse_val(last_row, "Close Lower Half", 0.0)
    uh_lh = round(uh / lh, 2) if lh > 0 else 1.0

    high_vol = parse_val(last_row, "High Vol", 0.0)
    low_vol = parse_val(last_row, "Low Vol", 0.0)
    pct_high_vol = round((high_vol / univ) * 100, 1)
    pct_low_vol = round((low_vol / univ) * 100, 1)
    vol_ratio = round(high_vol / max(low_vol, 1.0), 2)

    return {
        "date": date_val,
        "universe": int(univ),
        "nifty": nifty,
        "smallcap": smallcap,
        "up_4": int(u4),
        "dn_4": int(d4),
        "net_thrust": int(u4 - d4),
        "breakouts": int(bo),
        "bo_sustained": int(bo_s),
        "bo_failed": int(bo_f),
        "bo_sf_ratio": bo_sf,
        "breakdowns": int(bd),
        "bd_sustained": int(bd_s),
        "bd_failed": int(bd_f),
        "bd_sf_ratio": bd_sf,
        "u15_5": u15_5,
        "u25_20": u25_20,
        "d25_20": d25_20,
        "pct_ab_10": pct_ab_10,
        "pct_ab_20": pct_ab_20,
        "pct_ab_50": pct_ab_50,
        "pct_ab_200": pct_ab_200,
        "nh_52": nh,
        "nl_52": nl,
        "net_nh_nl": net_nh_nl,
        "within_15_wh": w15_wh,
        "within_15_wl": w15_wl,
        "uh_lh_ratio": uh_lh,
        "high_vol": int(high_vol),
        "low_vol": int(low_vol),
        "pct_high_vol": pct_high_vol,
        "pct_low_vol": pct_low_vol,
        "vol_ratio": vol_ratio
    }


def evaluate_positional_regime(metrics: dict, cfg: dict) -> dict:
    """
    Synthesizes the 6 institutional layers into an actionable Positional Swing Directive.
    """
    u4 = metrics["up_4"]
    d4 = metrics["dn_4"]
    bo_sf = metrics["bo_sf_ratio"]
    pct_20 = metrics["pct_ab_20"]
    pct_50 = metrics["pct_ab_50"]
    u25_20 = metrics["u25_20"]
    d25_20 = metrics["d25_20"]
    net_nh = metrics["net_nh_nl"]
    vol_ratio = metrics.get("vol_ratio", 0.50)
    high_vol = metrics.get("high_vol", 0)
    low_vol = metrics.get("low_vol", 0)
    pct_high_vol = metrics.get("pct_high_vol", 0.0)
    pct_low_vol = metrics.get("pct_low_vol", 0.0)

    # Volume State Classification (Above Avg Vol > 1.5x 20 DMA vs Below Avg Vol < 0.5x 20 DMA)
    if vol_ratio >= 1.50:
        if d4 >= 300:
            vol_state = "PANIC_CAPITULATION"
            vol_desc = f"Institutional Capitulation Blowout! High Vol ({pct_high_vol}%) > 1.5x Low Vol ({pct_low_vol}%). Extreme panic flush."
        elif u4 >= 200:
            vol_state = "INSTITUTIONAL_THRUST_BLOWOUT"
            vol_desc = f"Institutional Buying Thrust Blowout! High Vol ({pct_high_vol}%) > 1.5x Low Vol ({pct_low_vol}%)."
        else:
            vol_state = "HEAVY_TURNOVER_SURGE"
            vol_desc = f"Broad institutional volume expansion across market (Vol Ratio: {vol_ratio})."
    elif vol_ratio >= 1.00:
        vol_state = "ABOVE_AVERAGE_ACTIVE"
        vol_desc = f"Above average institutional participation (Vol Ratio: {vol_ratio} >= 1.0)."
    elif vol_ratio >= 0.40:
        vol_state = "NORMAL_BASELINE"
        vol_desc = f"Normal institutional baseline (Vol Ratio: {vol_ratio})."
    else:
        vol_state = "DRY_CHOP_CONSOLIDATION"
        vol_desc = f"Subdued/dry volume (Vol Ratio: {vol_ratio} < 0.40). Retail churn."

    # Layer 1: Breakout Health
    if bo_sf >= 1.5:
        bo_health = "HIGH_CONVICTION"
        bo_desc = "Breakouts sticking aggressively (Top 40% closes dominate)."
    elif bo_sf >= 1.0:
        bo_health = "MODERATE"
        bo_desc = "Breakouts selective. Volume confirmation required."
    else:
        bo_health = "TRAP_FAILING"
        bo_desc = "Distribution day! 60%+ of breakout attempts are failing."

    # Layer 2: Rubber-Band & Structural Trend
    if pct_20 < 15.0:
        ma_state = "OVERSOLD_WASHED_OUT"
    elif pct_20 >= 75.0:
        ma_state = "OVERBOUGHT_EXTENDED"
    else:
        ma_state = "HEALTHY_RANGE"

    # Layer 3: Momentum Pipeline
    if u25_20 >= 100:
        mom_state = "ABUNDANT_LEADERS"
    elif u25_20 >= 40:
        mom_state = "MODERATE_LEADERS"
    else:
        mom_state = "DEFICIT_NO_FUEL"

    # =========================================================================
    # CORE MULTI-LAYER REGIME SYNTHESIS
    # =========================================================================
    # 1. Day-1 Ignition Thrust (Confirmed by Breakout Stickiness)
    if u4 >= 150 and bo_sf >= 1.2:
        regime = "DAY1_IGNITION_CONFIRMED"
        badge = "🟢 DAY-1 IGNITION REVERSAL (High Conviction)"
        multiplier = 0.25
        mandate = "TEST THE WATERS: Deploy 0.25R pilot risk into top 1-2 Relative Strength leaders."
        setups_allowed = ["3-Day ORB Continuation", "High RS Breakout", "Episodic Pivot"]
        setups_blocked = ["Extended Breakouts (>3 ATR from 20 EMA)"]
        stop_rule = "Daily Low of breakout day OR 1.5x ATR trailing."

    # 2. Fake Ignition Trap
    elif u4 >= 150 and bo_sf < 1.0:
        regime = "IGNITION_TRAP_FADING"
        badge = "⚠️ IGNITION TRAP (Breakouts Fading Intrabar)"
        multiplier = 0.0
        mandate = "HOLD CASH: High 4% count but breakouts being sold into. Do NOT chase. Wait for Day-2 close."
        setups_allowed = ["Intraday Scalps Only (Flat by 15:15)"]
        setups_blocked = ["All Overnight Positional Swings"]
        stop_rule = "Strict breakeven on open trades."

    # 3. Selling Climax Capitulation
    elif d4 >= 400 and pct_20 < 15.0:
        if vol_ratio >= 1.40:
            regime = "SELLING_CLIMAX_CAPITULATION_CONFIRMED"
            badge = "🔴 SELLING CLIMAX / VOLUME CAPITULATION LOW (High Reversal Odds)"
            multiplier = 0.0
            mandate = f"PREPARE WATCHLIST / ZERO RISK: Confirmed volume capitulation blowout (Vol Ratio: {vol_ratio} >= 1.40, {pct_high_vol}% panic volume). 90%+ historical bounce odds in 3-5 days. Do NOT short; prepare RS watchlist for Day-1 Ignition."
        else:
            regime = "SELLING_CLIMAX_WASHOUT"
            badge = "🔴 SELLING CLIMAX / LOW VOLUME BLEED"
            multiplier = 0.0
            mandate = f"HOLD CASH: Steep drop ({d4} down >=4%) but volume hasn't blown out (Vol Ratio: {vol_ratio} < 1.40). Risk of cascading bleed. Wait for Day-1 Ignition spark."
        setups_allowed = ["Building RS Watchlist", "Monitoring Capitulation Bounces"]
        setups_blocked = ["All Breakout Buys", "Short Selling (Risk of snapback)"]
        stop_rule = "N/A - 100% Cash."

    # 4. Trending Waterfall / Cascade
    elif d4 >= 400 or (pct_20 < 30.0 and d4 > u4 * 2):
        regime = "DEFENSIVE_WATERFALL"
        badge = "🛑 DEFENSIVE / SELLING CASCADE ACTIVE"
        multiplier = 0.0
        mandate = "CASH IS KING: Broad selling pressure active. 85%+ of long setups fail. Sit on hands."
        setups_allowed = ["Cash Preservation"]
        setups_blocked = ["All Long Swing Positions"]
        stop_rule = "Immediate exit at Stop Loss."

    # 5. Overheated Froth / Top Divergence
    elif pct_20 >= 75.0 and bo_sf <= 1.1:
        regime = "OVERBOUGHT_DIVERGENCE"
        badge = "⚠️ OVERBOUGHT TOP DIVERGENCE (Harvest Mode)"
        multiplier = 0.25
        mandate = "THROTTLE DOWN: Market extended but breakout failures surging. Sell 1/3 into strength. Tighten stops."
        setups_allowed = ["Trailing Winning Runners Only"]
        setups_blocked = ["New Breakout Buys"]
        stop_rule = "Daily Low / 10 EMA (Strict trailing)."

    # 6. Trend Expansion Sweet Spot
    elif bo_sf >= 1.3 and u25_20 >= 80 and pct_50 >= 50.0:
        regime = "EXPANSION_SWEET_SPOT"
        badge = "🚀 TREND EXPANSION (The Sweet Spot)"
        multiplier = 1.0
        mandate = "FULL STEAM AHEAD: Institutional tide supportive. Breakouts have low failure rates. 100% risk permitted."
        setups_allowed = ["High Tight Flag Breakouts", "VCP Base Breakouts", "Pullback to 10/20 EMA"]
        setups_blocked = []
        stop_rule = "Standard Swing SL (20 EMA or Swing Low)."

    # 7. Selective Rotation (Chop)
    else:
        regime = "SELECTIVE_ROTATION"
        badge = "🟡 SELECTIVE ROTATION (Half Size)"
        multiplier = 0.50
        mandate = "CHERRY-PICK A+ SETUPS: Choppy/selective market. Half risk (50%) only. Require 2x volume confirmation."
        setups_allowed = ["Top RS Leaders with 2x Volume", "ORB Breakouts"]
        setups_blocked = ["Secondary / Beta Laggards"]
        stop_rule = "Daily Low or 1R trailing."

    # Risk Parameters
    risk_cfg = cfg.get("risk_parameters", {})
    account_cap = risk_cfg.get("account_capital", 500000)
    swing_cfg = risk_cfg.get("swing", {})
    base_risk = swing_cfg.get("base_risk_per_trade", 10000)
    risk_allowed = int(base_risk * multiplier)

    return {
        "as_of_date": metrics["date"],
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "regime_code": regime,
        "regime_badge": badge,
        "mandate": mandate,
        "swing_allocation_pct": int(multiplier * 100),
        "swing_risk_per_trade": risk_allowed,
        "base_risk_per_trade": base_risk,
        "breakout_quality": {
            "health": bo_health,
            "description": bo_desc,
            "bo_sf_ratio": bo_sf,
            "sustained": metrics["bo_sustained"],
            "failed": metrics["bo_failed"],
            "total_attempted": metrics["breakouts"]
        },
        "volume_telemetry": {
            "vol_ratio": vol_ratio,
            "high_vol_count": high_vol,
            "low_vol_count": low_vol,
            "high_vol_pct": pct_high_vol,
            "low_vol_pct": pct_low_vol,
            "vol_state": vol_state,
            "vol_description": vol_desc
        },
        "institutional_layers": {
            "ma_breadth_20ema_pct": metrics["pct_ab_20"],
            "ma_breadth_50ema_pct": metrics["pct_ab_50"],
            "ma_status": ma_state,
            "momentum_leaders_25pct_20d": u25_20,
            "momentum_laggards_25pct_20d": d25_20,
            "momentum_status": mom_state,
            "net_52w_highs_lows": net_nh,
            "within_15pct_52wh": metrics["within_15_wh"],
            "within_15pct_52wl": metrics["within_15_wl"],
            "uh_lh_ratio": metrics["uh_lh_ratio"],
            "vol_ratio": vol_ratio,
            "vol_state": vol_state
        },
        "setups_allowed": setups_allowed,
        "setups_blocked": setups_blocked,
        "stop_loss_mandate": stop_rule
    }


def main():
    print("=" * 75)
    print("⚡ JARVIS DAILY POSITIONAL SWING REGIME DETECTOR")
    print(f"⏰ Execution: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 75)

    try:
        cfg = {}
        if CONFIG_FILE.is_file():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)

        metrics = load_latest_positional_metrics()
        verdict = evaluate_positional_regime(metrics, cfg)

        # Write to JSON
        with open(POSITIONAL_REGIME_FILE, "w", encoding="utf-8") as f:
            json.dump(verdict, f, indent=2)
        print(f"💾 Positional regime state saved: {POSITIONAL_REGIME_FILE.name}")

        print(f"\n📅 SESSION DATE : {verdict['as_of_date']}")
        print(f"🚦 REGIME STATE : {verdict['regime_badge']}")
        print(f"💰 ALLOCATION   : {verdict['swing_allocation_pct']}% Risk (₹{verdict['swing_risk_per_trade']:,} / trade)")
        print(f"📢 MANDATE      : {verdict['mandate']}")
        print(f"\n📊 BREAKOUT QUALITY:")
        print(f"   • BO S/F Ratio : {verdict['breakout_quality']['bo_sf_ratio']} ({verdict['breakout_quality']['health']})")
        print(f"   • Sustained/Fail: {verdict['breakout_quality']['sustained']} Sustained vs {verdict['breakout_quality']['failed']} Failed")
        print(f"\n🌊 VOLUME PARTICIPATION:")
        print(f"   • Vol Ratio    : {verdict['volume_telemetry']['vol_ratio']} ({verdict['volume_telemetry']['vol_state']})")
        print(f"   • High/Low Vol : {verdict['volume_telemetry']['high_vol_count']} ({verdict['volume_telemetry']['high_vol_pct']}%) High vs {verdict['volume_telemetry']['low_vol_count']} ({verdict['volume_telemetry']['low_vol_pct']}%) Low")
        print(f"   • Context      : {verdict['volume_telemetry']['vol_description']}")
        print(f"\n🏗️ INSTITUTIONAL LAYERS:")
        print(f"   • Above 20 EMA : {verdict['institutional_layers']['ma_breadth_20ema_pct']}% ({verdict['institutional_layers']['ma_status']})")
        print(f"   • Above 50 EMA : {verdict['institutional_layers']['ma_breadth_50ema_pct']}%")
        print(f"   • 25% in 20D   : {verdict['institutional_layers']['momentum_leaders_25pct_20d']} Leaders vs {verdict['institutional_layers']['momentum_laggards_25pct_20d']} Down")
        print(f"   • Net 52W H-L  : {verdict['institutional_layers']['net_52w_highs_lows']}")
        print(f"\n🛡️ SETUP PERMISSIONS:")
        print(f"   ✅ Allowed: {', '.join(verdict['setups_allowed'])}")
        if verdict['setups_blocked']:
            print(f"   ⛔ Blocked: {', '.join(verdict['setups_blocked'])}")
        print(f"   🛑 Stops  : {verdict['stop_loss_mandate']}")
        print("=" * 75)

    except Exception as e:
        print(f"❌ Error in positional swing detector: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
