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
import re
import sys
import json
import time
import html as html_lib
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
    ("India VIX", "Volatility", "NSE_INDEX|India VIX", "^INDIAVIX"),
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


def classify_bonde_multi_day_state(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Quantified Pradeep Bonde State Machine.
    Evaluates multi-day sequence, climax washouts, ignition sparks, and divergences.
    Returns: Dict containing state_code, state_label, state_action, allocation_pct, etc.
    """
    if not history:
        return {
            "state_code": "NEUTRAL",
            "state_label": "⚪ NEUTRAL / INSUFFICIENT DATA",
            "state_action": "Awaiting fresh breadth data.",
            "allocation_pct": 0,
            "trajectory_context": "No history available.",
            "ignition_trigger": "Watch for Day-1 Ignition trigger.",
            "tactical_rule": "Maintain neutral risk."
        }

    idx = len(history) - 1
    curr = history[idx]
    prev = history[idx - 1] if idx > 0 else curr
    prev2 = history[idx - 2] if idx > 1 else prev

    # Trailing consecutive streaks
    consec_green = 0
    consec_red = 0
    for d in reversed(history):
        if d['net_breadth'] > 0:
            if consec_red > 0: break
            consec_green += 1
        elif d['net_breadth'] < 0:
            if consec_green > 0: break
            consec_red += 1

    strip_color = "TEAL" if consec_green > 0 else "CLAY"
    strip_streak = consec_green if consec_green > 0 else consec_red
    strip_badge = f"🟢 TEAL (Day-{consec_green} Expansion Streak)" if consec_green > 0 else f"🔴 CLAY (Day-{consec_red} Distribution Streak)"

    # Check for recent climax washout in last 3 sessions
    recent_3 = history[max(0, idx - 2):idx + 1]
    climax_day = next((d for d in reversed(recent_3) if d['dn_4_cnt'] >= 400), None)
    had_climax = climax_day is not None

    if had_climax and climax_day:
        trajectory_context = f"Selling Climax occurred on {climax_day['date']} ({climax_day['dn_4_cnt']} stocks crashed 4%). Yesterday selling contracted to {curr['dn_4_cnt']}."
    elif consec_red >= 2:
        trajectory_context = f"Downtrend pressure active ({consec_red} consecutive red sessions). 4% Down: {curr['dn_4_cnt']} vs 4% Up: {curr['up_4_cnt']}."
    elif consec_green >= 2:
        trajectory_context = f"Bullish momentum wave ({consec_green} consecutive green sessions). 4% Up: {curr['up_4_cnt']} vs 4% Down: {curr['dn_4_cnt']}."
    else:
        trajectory_context = f"Transitional rotational market. 4% Thrust: {curr['up_4_cnt']} Up vs {curr['dn_4_cnt']} Down."

    ignition_trigger = "Watch for Day-1 Ignition trigger: 4% Gainers &gt; 150 &amp; 4% Losers &lt; 80."

    # 1. SELLING CLIMAX / WASHOUT (Extreme Panic)
    if curr['dn_4_cnt'] >= 400 or (had_climax and curr['ratio_5d'] < 0.60 and curr['net_breadth'] < -5.0):
        if curr['dn_4_cnt'] >= 500:
            state_code = "CLIMAX"
            state_label = "🔴 SELLING CLIMAX (Washout Peak)"
            state_action = "Panic liquidation peak (&gt;400 down). Do not short. Prepare buy watchlist for Day-1 Ignition."
            allocation_pct = 0
            tactical_rule = "Cash is King (0% allocation). Selling climax cleans out weak hands. Sit tight."
        else:
            state_code = "WASHOUT_CONT"
            state_label = "🔴 WASHOUT CONTINUATION"
            state_action = "Sellers exhausting after climax. Sit in cash (0% allocation). Watch for Day-1 Ignition spark."
            allocation_pct = 0
            tactical_rule = "Zero fresh breakouts. Wait for the Day-1 Ignition spark before deploying any capital."

    # 2. DAY-1 IGNITION REVERSAL (First spark off bottom)
    elif (prev['net_breadth'] < 0 or prev2['net_breadth'] < 0) and curr['up_4_cnt'] >= 150 and curr['dn_4_cnt'] <= 90 and curr['net_breadth'] >= 2.0:
        state_code = "IGNITION"
        state_label = "🟢 DAY-1 IGNITION REVERSAL"
        state_action = "First high-momentum thrust off bottom! Deploy 25-30% pilot size on Relative Strength leaders."
        allocation_pct = 25
        tactical_rule = "Take 2-3 Pilot trades (25% risk) in top Relative Strength leaders or Episodic Pivots (EP)."

    # 3. OVERHEATED / FROTH / DIVERGENCE (Cool-Off Imminent)
    elif (consec_green >= 4 and curr['ratio_5d'] >= 3.5) or (curr['nifty_chg'] > 0.4 and curr['bo_failure'] >= 65 and curr['up_4_cnt'] < 100):
        state_code = "OVERHEATED"
        state_label = "⚠️ OVERHEATED / DIVERGENCE (Cool-Off Imminent)"
        state_action = "Market stretched or stealth distribution. Do NOT chase breakouts. Trail stops tightly to 10 DEMA."
        allocation_pct = 25
        tactical_rule = "Do NOT buy late-stage breakouts. Trail stops to Daily Low / 10 DEMA. Sell 1/3 into strength."

    # 4. TREND EXPANSION (Sweet Spot)
    elif curr['ratio_5d'] >= 1.5 and curr['net_breadth'] > 0 and curr['bo_failure'] <= 50:
        state_code = "EXPANSION"
        state_label = "🟢 TREND EXPANSION (The Sweet Spot)"
        state_action = "Institutional tide strongly favorable. Deploy full 100% position size on A+ momentum breakouts."
        allocation_pct = 100
        tactical_rule = "Full 100% position sizing permitted. Aggressively buy high-volume ORB &amp; breakout setups."

    # 5. SELECTIVE ROTATION / CHOP
    elif 0.85 <= curr['ratio_5d'] <= 1.5:
        state_code = "SELECTIVE"
        state_label = "🟡 SELECTIVE ROTATION (Half Size)"
        state_action = "Mixed market tide. Deploy 50% position size. Demand 2x volume confirmation on breakouts."
        allocation_pct = 50
        tactical_rule = "Half position size (50% risk). Only take A+ setups with 2x volume and strong sector backing."

    # 6. DEFENSIVE DOWNTREND
    else:
        state_code = "DEFENSIVE"
        state_label = "🔴 DEFENSIVE / CASH IS KING"
        state_action = "Downtrend active (5D ratio &lt; 1.0). Zero fresh breakouts. Protect capital."
        allocation_pct = 0
        tactical_rule = "Cash preservation mode. Avoid buying breakouts. Trailing stops tightened."

    # Explicit 3-Way Detector Statuses
    if curr['dn_4_cnt'] >= 500:
        washout_status = f"🔴 PEAK CLIMAX ({curr['dn_4_cnt']} stocks down 4%)"
    elif had_climax and climax_day:
        washout_status = f"🔴 ACTIVE (Peak {climax_day['dn_4_cnt']} on {climax_day['date']}; now {curr['dn_4_cnt']})"
    elif curr['dn_4_cnt'] >= 300:
        washout_status = f"🟡 ELEVATED ({curr['dn_4_cnt']} stocks down 4%)"
    else:
        washout_status = "⚪ QUIET (Normal selling levels)"

    if state_code == "IGNITION":
        ignition_status = "🟢 TRIGGERED TODAY (Reversal spark active!)"
    elif had_climax or curr['ratio_5d'] < 1.0:
        ignition_status = "⚪ ARMED (Watching for &gt;150 Up / &lt;80 Down)"
    else:
        ignition_status = "⚪ STANDBY"

    if state_code == "OVERHEATED":
        froth_status = "⚠️ FROTH / DIVERGENCE (Cool-off imminent!)"
    elif curr['ratio_5d'] >= 2.5:
        froth_status = f"🟡 WARMING (5D Ratio {curr['ratio_5d']:.2f})"
    else:
        froth_status = f"⚪ QUIET (5D Ratio {curr['ratio_5d']:.2f} — No froth)"

    # Action Mandates for All 3 Timeframes (What To Do Today)
    if state_code in ("CLIMAX", "WASHOUT_CONT", "DEFENSIVE"):
        mandate_headline = "🛑 SIT ON HANDS / HOLD CASH"
        action_intra = "🟡 <i>Permitted with Caution</i> (Quick 3m ORB scalps only on RS leaders; strictly square off before 03:15 PM; zero overnight hold)."
        action_swing = "⛔ <b>DO NOT START NEW SWING TRADES</b> (Regime is Defensive / Washout. Wait for Day-1 Ignition confirmation spark)."
        action_positional = "⏸️ <b>PAUSED / PROTECT CAPITAL</b> (Market structure broken; wait for breadth to base)."
    elif state_code == "IGNITION":
        mandate_headline = "🟢 PROCEED WITH PILOT TRADES (25% Risk)"
        action_intra = "🟢 <i>Active &amp; Favored</i> (Trade 3m ORB opening breakouts on high volume with conviction)."
        action_swing = "🟢 <b>START PILOT SWING TRADES (25% Capital)</b> (Deploy on 1-2 top Relative Strength leaders or Episodic Pivots)."
        action_positional = "👀 <b>WATCHLIST BUILDING</b> (Identify multi-month base breakout candidates for accumulation)."
    elif state_code == "EXPANSION":
        mandate_headline = "🚀 FULL STEAM AHEAD (100% Risk Allocation)"
        action_intra = "🟢 <i>Highly Favorable</i> (Run full 3m ORB scanner; trade opening breakouts aggressively)."
        action_swing = "🟢 <b>FULL SWING ACTIVE (100% Capital)</b> (Deploy across up to 5 positions; press winners and trail to 10 DEMA)."
        action_positional = "🟢 <b>ACCUMULATE / ADD</b> (Add to core institutional compounders in leading sectors)."
    elif state_code == "OVERHEATED":
        mandate_headline = "⚠️ HARVEST PROFITS / DO NOT CHASE HIGHS"
        action_intra = "⚠️ <i>Fade Gap-Ups / Scalp Only</i> (High fakeout risk on morning breakouts; take quick profits)."
        action_swing = "⛔ <b>DO NOT START NEW SWING POSITIONS</b> (Trail stops to daily low / 10 DEMA; sell 1/3 into strength)."
        action_positional = "⏸️ <b>HOLD &amp; TRAIL</b> (Do not deploy fresh cash at range extremes)."
    else:  # SELECTIVE
        mandate_headline = "🟡 CHERRY-PICK A+ SETUPS ONLY (50% Risk)"
        action_intra = "🟡 <i>Selective Trading</i> (Require 2x volume confirmation on 3m ORB; quick profit taking)."
        action_swing = "🟡 <b>HALF-SIZE SWING (50% Risk)</b> (Take only top-tier A+ setups with strong sector backing)."
        action_positional = "⏸️ <b>SELECTIVE HOLD</b> (Hold only high-conviction names with tight stops)."

    return {
        "state_code": state_code,
        "state_label": state_label,
        "state_action": state_action,
        "allocation_pct": allocation_pct,
        "trajectory_context": trajectory_context,
        "ignition_trigger": ignition_trigger,
        "tactical_rule": tactical_rule,
        "washout_status": washout_status,
        "ignition_status": ignition_status,
        "froth_status": froth_status,
        "mandate_headline": mandate_headline,
        "action_intra": action_intra,
        "action_swing": action_swing,
        "action_positional": action_positional,
        "strip_color": strip_color,
        "strip_streak": strip_streak,
        "strip_badge": strip_badge
    }


def _parse_sheet_date(s: str) -> Optional[datetime]:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s)[:11].strip(), fmt)
        except Exception:
            continue
    return None


def _pctile(vals: List[float], v: float) -> float:
    """Share (0-100) of vals strictly below v."""
    vals = [x for x in vals if x is not None]
    return 100.0 * sum(1 for x in vals if x < v) / len(vals) if vals else 50.0


def _kedia_day_flags(x: Dict[str, Any], ref: List[Dict[str, Any]]) -> Tuple[bool, bool]:
    """(strong breadth day, breakdown day) for one session vs ~1y of prior sessions."""
    p4 = _pctile([y["up_4_pct"] for y in ref], x["up_4_pct"])
    pd4 = _pctile([y["dn_4_pct"] for y in ref], x["dn_4_pct"])
    strong = p4 >= 80.0 and x.get("bo_sf_ratio", 0) > 1.0 and x.get("vol_ratio", 0) >= 0.5
    brk = pd4 >= 80.0 and x.get("net_breadth", 0) < 0 and x.get("bd_sf_ratio", 0) > 1.0
    return strong, brk


def _kedia_stance(h: List[Dict[str, Any]]) -> str:
    """Sticky stance as of the last row of h (POSITIVE / WATCH_FOLLOW_THROUGH / STEP_ASIDE / SELECTIVE)."""
    ref = h[-251:-1]
    flags = [_kedia_day_flags(x, ref) for x in h[-3:]]
    if flags[-1][1]:
        return "STEP_ASIDE"
    n_strong = sum(1 for f in flags if f[0])
    if n_strong >= 2:
        return "POSITIVE"
    # Backtest 2024-26 vs his notes: he turns positive on rising breadth + one decent 4% day, even with volume
    # 0.3-0.5 (10 of 12 right), and waits on weak, dry bounces in a weak market (5 of 7 right).
    a = [x.get("pct_ab_10") for x in h[-6:]]
    if ref and all(v is not None for v in a):
        p80 = sorted(y["up_4_pct"] for y in ref)[int(len(ref) * 0.8)]
        mx20 = max((x.get("pct_ab_10") or 0.0) for x in h[-20:])
        if a[-1] >= 55.0 and a[-1] >= 0.85 * mx20:
            return "POSITIVE"                                   # trend / lockout: don't fight it
        if a[-1] >= 35.0 and a[-1] - min(a) >= 10.0 and a[-1] >= a[-2] - 2.0 \
                and any(x["up_4_pct"] >= p80 for x in h[-3:]):
            return "POSITIVE"                                   # rising breadth + a decent demand day
        if a[-1] < 30.0 and h[-1].get("vol_ratio", 1.0) < 0.5 \
                and not any(x["up_4_pct"] >= p80 for x in h[-5:]):
            return "WAIT"                                       # weak, dry bounce in a weak market
    if flags[-1][0]:
        return "WATCH_FOLLOW_THROUGH"
    return "SELECTIVE"


def kedia_sa_read(history: List[Dict[str, Any]], today: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Chhirag Kedia-style #SituationalAwareness read of the MBM V2.0 sheet (27 Nov 2026).
    Reads the last few sessions as a SEQUENCE and anticipates the next one, as he does:
      - where we are in the swing (decline leg / bounce day N / trend) from % above 10-DEMA (fallback: net 4% breadth)
      - thrust of each bounce day (4% breakouts), and whether volume did what it SHOULD have done
      - how far from an extreme (his 10-DEMA extremes ~4-6%; we use our own 1y low decile), i.e. room left
      - what today can look like (scenarios a/b) and the exact readings that would change the stance
    Stance is sticky and anchored to the session it was set. Pure function: facts + HTML lines.
    """
    out = {"available": False, "lines": []}
    h = [x for x in (history or []) if x.get("date")]
    if len(h) < 25:
        return out
    cur, prev = h[-1], h[-2]
    look = h[-251:-1]
    nxt = today or datetime.now()
    d_cur = _parse_sheet_date(cur["date"])

    # ---------- stance (sticky, anchored)
    code = _kedia_stance(h)
    since = cur["date"]
    for j in range(len(h) - 1, max(len(h) - 40, 25), -1):
        if _kedia_stance(h[:j]) != code:
            break
        since = h[j - 1]["date"]
    since_txt = f"No change in stance since {since}" if since != cur["date"] else f"Stance changes today ({cur['date']})"

    # ---------- where are we in the swing
    has10 = all(x.get("pct_ab_10") is not None for x in h[-25:])
    if has10:
        ser = [x["pct_ab_10"] for x in h]
    else:
        ser, c = [], 0.0
        for x in h:
            c += x.get("net_breadth", 0.0)
            ser.append(c)
    n = len(h)
    lo_i = min(range(n - 15, n), key=lambda i: ser[i])
    hi_i = max(range(max(0, lo_i - 25), lo_i + 1), key=lambda i: ser[i])
    bounce_days = n - 1 - lo_i
    near_top = has10 and ser[-1] >= 55.0 and ser[-1] >= 0.85 * max(ser[-20:])
    # his explicit extremes for stocks above the 10-DEMA: 5-6% (13% "is not an extreme yet"); 15% or below = approaching
    EXT, NEAR = 7.5, 15.0
    at_extreme = has10 and ser[lo_i] <= EXT
    near_extreme = has10 and ser[lo_i] <= NEAR

    up4s = sorted(x["up_4_pct"] for x in look)
    p80 = up4s[int(len(look) * 0.8)]
    # breadth-thrust bar on his ~2,500-stock sheet: he called "10% Monday, 17% Tuesday" a weak thrust (28-10-2026)
    p97 = max(25.0, up4s[min(len(look) - 1, int(len(look) * 0.97))])
    vr, vp = cur.get("vol_ratio", 0.0), prev.get("vol_ratio", 0.0)
    sf = cur.get("bo_sf_ratio", 0.0)

    lines_view, scen, setups = [], [], ""
    if has10:
        lines_view.append(
            f"Stocks above the 10-DEMA: <b>{ser[-1]:.0f}%</b>, down from {ser[hi_i]:.0f}% on {h[hi_i]['date']}"
            + (f", swing low {ser[lo_i]:.0f}% on {h[lo_i]['date']}." if bounce_days else ".")
            + (" That low is a genuine extreme (5-6% territory)." if at_extreme else
               " Approaching extremes, but not there yet: for a meaningful extreme we're looking at 5-6% or lower." if near_extreme else
               " This is a pullback, not an extreme: don't treat it as oversold.")
        )

    if near_top:
        phase = "TREND"
        lines_view.append("Breadth is near its recent highs. In a trend, don't anticipate pullbacks; let the market throw you out with a breakdown day.")
        scen = ["a) Gap-down or early dip: in a healthy trend these are entries in leaders.",
                "b) Gap-up: fine, but avoid chasing extended names in the first minutes; use alternative entries."]
        setups = "Breakouts and continuation in leaders; gap-downs in leaders are entries."
    elif bounce_days == 0:
        phase = "DECLINE"
        k = 0
        for i in range(n - 1, 0, -1):
            if ser[i] < ser[i - 1]:
                k += 1
            else:
                break
        lines_view.append(f"The decline continues: day {k} of falling breadth. No bounce attempt yet.")
        if at_extreme:
            scen = ["a) Sell-off in the first hour followed by a reversal: the ideal, highest-probability outcome from an extreme. This is where I'd act.",
                    "b) Muted or gap-up start: the spoiler. A premature bounce from here usually leads to another leg down."]
            setups = "Parabolic longs, momentum suppression and delayed EPs: enter quickly and trail to breakeven fast."
        else:
            scen = ["a) Further decline: likely, as readings are not at extremes. It creates the room a real bounce needs.",
                    "b) A pause or weak bounce: treat it as a trap. It only creates room for another leg down."]
            setups = "Wait and watch. EPs only, on their own strength; parabolic longs only once readings reach extremes."
    else:
        phase = f"BOUNCE_D{bounce_days}"
        legs = h[lo_i + 1:]
        thrust = ", ".join(f"{x['up_4_pct']:.1f}% on {x['date'][:6]}" for x in legs[-4:])
        thrust_any = any(x["up_4_pct"] >= p97 for x in legs)
        decent_any = any(x["up_4_pct"] >= p80 for x in legs)
        vol_conf = vr >= max(0.5, h[lo_i + 1].get("vol_ratio", 0.0) + 0.05)
        strong_any = thrust_any and vol_conf
        lines_view.append(
            f"Day {bounce_days} of the bounce from the {h[lo_i]['date']} low. 4% breakouts: {thrust}. "
            + ("That is a breadth thrust." if thrust_any else
               f"Decent, but not a breadth thrust: that needs {p97:.0f}% or more." if decent_any else
               f"The thrust is weak: no day reached {p80:.1f}%, let alone the {p97:.0f}% a breadth thrust needs.")
        )
        if bounce_days == 1:
            scen = ["a) Follow-through: a second day of 4% breakouts, ideally above " + f"{p80:.1f}%, with volume rising. That makes the bounce real.",
                    "b) Fade or muted start: the rally attempt stalls. As long as the low holds, it stays a test, not a failure."]
            setups = "Don't chase the first day. Leaders that held up best during the pullback go first; EPs on their own strength."
        elif not strong_any:
            lines_view.append("As the initial bounce begins to exhaust, the real test starts now.")
            scen = [f"a) Pause or retest that holds above the swing low ({ser[lo_i]:.0f}% above 10-DEMA): constructive, and a better entry than chasing.",
                    "b) Breaking the swing low: the bounce has failed and the decline resumes. Expect it to be faster."]
            setups = "The initial oversold bounce is exhausting. Trade light, focus on leaders, and bring positions to risk-free quickly."
        else:
            scen = ["a) Gap-down or early dip: in a bounce with thrust, these are entries.",
                    "b) Extended gap-up: let it settle; FOMO buyers get trapped in the first minutes."]
            setups = "Breakouts in leaders and theme stocks; get more active as long as volume keeps confirming."

    # ---------- volume: what it did vs what it should have done
    if phase.startswith("BOUNCE") and bounce_days >= 2:
        v0 = h[lo_i + 1].get("vol_ratio", 0.0)
        if vr <= v0:
            lines_view.append(f"Volume, which should have picked up with the bounce, instead went from {v0:.2f} to <b>{vr:.2f}</b>. Participants lack confidence.")
        else:
            lines_view.append(f"Volume is picking up with the bounce ({v0:.2f} to <b>{vr:.2f}</b>): that is the confirmation I want.")
    else:
        move = "rose" if vr > vp + 0.02 else ("dropped" if vr < vp - 0.02 else "held")
        tail = ""
        if vr < 0.5:
            st = None
            for x in reversed(h):
                if x.get("vol_ratio", 1.0) < 0.5:
                    st = x
                else:
                    break
            if st is not None and st is not cur:
                tail = f", below 0.5 since {st['date']}"
        elif vr >= 1.0:
            tail = ", above 1: significant participation"
        note = (" Volume rose on a down day: that is selling pressure, not demand." if move == "rose" and cur.get("net_breadth", 0) < 0
                else " Low demand: small upticks mean little; I want 0.5 or more." if vr < 0.5 else "")
        lines_view.append(f"Volume {move} from {vp:.2f} to <b>{vr:.2f}</b>{tail}.{note}")
    lines_view.append(f"Breakout Success/Failure: <b>{sf:.2f}</b>" + (", above 1: breakouts held." if sf > 1.0 else ", below 1: breakouts are not being rewarded."))

    if cur.get("nifty_chg", 0.0) >= 0.3 and (cur["up_4_pct"] < p80 or vr < 0.5):
        lines_view.append("The index is up, but breadth and volume aren't: a handful of stocks are masking the lack of broad participation.")

    # ---------- calendar context
    ctx = []
    if d_cur is not None:
        gap_days = (nxt.date() - d_cur.date()).days
        if gap_days >= 3 and nxt.weekday() != 0:
            ctx.append("First session after a holiday: a gap-up can turn into a trap. Let the market settle before initiating trades.")
        elif gap_days >= 3:
            ctx.append("Start of the week: a strong move in either direction can set the tone for the next few days.")
    m, dd = nxt.month, nxt.day
    if m == 11 or (m == 12 and dd <= 15):
        ctx.append("Seasonality: November to mid-December is usually favourable. If the bounce is going to get support, this is the window.")
    elif m == 12:
        ctx.append("Seasonality: the last two weeks of December are usually thin, with holiday-season volume.")
    elif m in (1, 2):
        ctx.append("Seasonality: January and February often bring trend shifts (Budget season).")
    elif m == 3:
        ctx.append("Seasonality: March often leads to capitulation; early April can bring a bull swing.")

    # ---------- what changes it (concrete next-session readings)
    watch_up = f"4% breakouts at {p80:.1f}% or more, Success/Failure above 1 and volume at {max(0.5, vr + 0.1):.2f} or more"
    watch_dn = (f"stocks above the 10-DEMA back below {ser[lo_i]:.0f}%" if has10 and bounce_days else "a breakdown day (widespread 4% declines)")
    change = f"Turns positive on: {watch_up}, preferably on more than one day. Steps aside on: {watch_dn}."

    stance_txt = {
        "POSITIVE": "Shift towards a positive bias and get more active.",
        "WATCH_FOLLOW_THROUGH": "A strong breadth day, but only one. I want follow-through before changing stance.",
        "STEP_ASIDE": "Breakdown day: step aside from fresh breakouts and protect open positions.",
        "SELECTIVE": "Be selective: large caps and strong themes, avoid small caps.",
        "WAIT": "A weak, dry bounce in a weak market. Wait and watch: no fresh breakouts until thrust or volume shows up; EPs only on their own strength.",
    }[code]

    lines = ["🧭 <b>KEDIA-STYLE #SituationalAwareness</b> <i>(MBM V2.0, session " + str(cur["date"]) + ")</i>",
             "<b>OVERALL VIEW:</b>",
             f"• {since_txt}. {stance_txt}"]
    lines += [f"• {x}" for x in lines_view]
    lines += [f"• {x}" for x in ctx]
    lines += ["<b>HOW TODAY CAN PLAY OUT:</b>"] + [f"• {x}" for x in scen]
    lines += [f"<b>SETUPS:</b> {setups}", f"<b>WHAT CHANGES IT:</b> <i>{change}</i>"]
    out.update({"available": True, "stance_code": code, "stance_since": since, "phase": phase,
                "bounce_days": bounce_days, "at_extreme": bool(at_extreme),
                "pct_ab_10": ser[-1] if has10 else None, "swing_low_pct_ab_10": ser[lo_i] if has10 else None,
                "up4_p80_1y": p80, "bo_sf_ratio": sf, "vol_ratio": vr, "lines": lines})
    return out


def classify_trend_regime(a50: Optional[float], a200: Optional[float], net10: Optional[float],
                          up4_pct: float = 0.0, dn4_pct: float = 0.0) -> Dict[str, Any]:
    """
    Trend-health regime from Market Breadth V2.0 history (2004-2026, 5,665 sessions).
    a50/a200 = % of universe above 50/200 DEMA; net10 = 10-session mean of Net Breadth (pct pts).
    Stats are historical 20-session forward Nifty returns (descriptive, overlapping windows).
    """
    if a200 is None or a50 is None:
        return {"trend_regime": "UNAVAILABLE", "trend_edge": "", "trend_overlay": ""}

    if a200 <= 20.0 or a50 <= 15.0:
        regime = "WASHOUT"
        edge = "Nifty +1.7% / Smallcap +3.8% avg next 20d; wait for thrust to turn (net10 >= -3: Nifty +2.1% to +3.1%)"
    elif a200 < 40.0:
        regime = "DEAD ZONE"
        edge = "No edge: Nifty -0.2% / Smallcap -1.3% avg next 20d (55% / 47% positive); size down"
        if net10 is not None and net10 > 3.0:
            edge += "; thrust > +3 lifts Nifty to ~+1.0%"
    elif a200 < 60.0:
        regime = "REBUILD"
        edge = "Mildly positive, unstable across eras; trade selectively"
    else:
        regime = "STRONG"
        edge = "Nifty +0.7% / Smallcap +1.7% avg next 20d"
        if a50 >= 80.0:
            regime = "STRONG (a50 >= 80)"
            edge = "Nifty +1.9% / Smallcap +3.1% avg next 20d (68% / 79% positive)"

    overlay = ""
    if up4_pct >= 30.0:
        overlay = "Exhaustion: >=30% stocks up 4% (Nifty -0.6% next 20d); do not chase"
    elif dn4_pct >= 30.0:
        overlay = "Capitulation not a floor yet: >=30% stocks down 4% (Nifty -0.3% next 20d)"
    return {"trend_regime": regime, "trend_edge": edge, "trend_overlay": overlay,
            "pct_ab_50": round(a50, 1), "pct_ab_200": round(a200, 1),
            "net_breadth_10d": None if net10 is None else round(net10, 2)}


def extract_bonde_breadth_metrics(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Parses Chhirag Kedia's Market Breadth V2.0.xlsm (Stockbee / Pradeep Bonde SA Engine).
    Builds multi-day sequence history and classifies the quantified market state.
    """
    if not file_path.is_file():
        print(f"⚠️ Breadth file {file_path.name} not found.")
        return None

    try:
        wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        ws_b = wb['Breadth']
        ws_m = wb['Market Map']

        history = []
        # Scan recent rows (rows 5600 to 7000) to collect sequence history
        for idx, r in enumerate(ws_b.iter_rows(min_row=5600, max_row=7000, values_only=True), start=5600):
            if r[0] is not None and str(r[0]).strip() not in ('', 'None'):
                date_raw = r[0]
                if hasattr(date_raw, 'strftime'):
                    date_str = date_raw.strftime("%d-%b-%Y")
                else:
                    date_str = str(date_raw)[:10]

                nifty_chg = float(r[1] or 0.0) * 100.0
                universe = int(r[3] or 2505)
                up_4_pct = float(r[4] or 0.0) * 100.0
                dn_4_pct = float(r[5] or 0.0) * 100.0
                up_4_cnt = int(round(up_4_pct * universe / 100.0))
                dn_4_cnt = int(round(dn_4_pct * universe / 100.0))
                net_breadth = float(r[6] or 0.0)
                ratio_5d = float(r[7] or 0.0)
                ratio_10d = float(r[8] or 0.0)
                above_vol_pct = float(r[9] or 0.0) * 100.0
                below_vol_pct = float(r[10] or 0.0) * 100.0
                vol_ratio = float(r[11] or 0.0)
                range_lt3_pct = float(r[12] or 0.0) * 100.0
                volatility = float(r[13] or 0.0)
                range_gt5_pct = float(r[14] or 0.0) * 100.0
                close_uh_pct = float(r[15] or 0.0) * 100.0
                close_lh_pct = float(r[16] or 0.0) * 100.0
                uh_lh_ratio = float(r[17] or 0.0)
                bo_sustained = float(r[21] or 0.0) * 100.0
                bo_failure = float(r[22] or 0.0) * 100.0
                bo_sf_ratio = float(r[23] or 0.0)
                bd_sustained = float(r[26] or 0.0) * 100.0
                bd_failure = float(r[27] or 0.0) * 100.0
                bd_sf_ratio = float(r[28] or 0.0)

                history.append({
                    "row_idx": idx,
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
                    "bd_sf_ratio": bd_sf_ratio
                })

        if not history:
            wb.close()
            return None

        # % of universe above 10/20/50 DEMA per session (Data sheet), for the Kedia sequence read
        try:
            ws_dq = wb['Data']
            hdr_q = [str(c).strip() for c in next(ws_dq.iter_rows(min_row=1, max_row=1, values_only=True))]
            iq = {k: hdr_q.index(f'Above {k} DEMA') for k in (10, 20, 50) if f'Above {k} DEMA' in hdr_q}
            dmap = {}
            for r in ws_dq.iter_rows(min_row=5590, max_row=7000, values_only=True):
                if hasattr(r[0], 'strftime') and r[3]:
                    u = float(r[3])
                    dmap[r[0].strftime("%d-%b-%Y")] = {k: float(r[i] or 0.0) / u * 100.0 for k, i in iq.items()}
            for hh in history:
                q = dmap.get(hh["date"])
                if q:
                    for k, v in q.items():
                        hh[f"pct_ab_{k}"] = v
        except Exception as e:
            print(f"⚠️ DEMA breadth history unavailable: {e}")

        last_item = history[-1]
        last_idx = last_item["row_idx"]

        # Fetch Sectoral 5-Day ROC from SBE sheet
        ws_sbe = wb['SBE']
        headers_sbe = [c for c in next(ws_sbe.iter_rows(max_row=1, values_only=True))]
        
        # Scan from row 5600 to 5700 for last non-empty row in SBE
        last_sbe_row = None
        for r in ws_sbe.iter_rows(min_row=5600, max_row=5700, values_only=True):
            if r[0] is not None and str(r[0]).strip() not in ('', 'None'):
                last_sbe_row = r

        sectors_roc = []
        if last_sbe_row:
            for c_idx in range(7, 45, 2):
                if c_idx < len(headers_sbe):
                    sec_name = str(headers_sbe[c_idx]).strip()
                    val = last_sbe_row[c_idx+1] if c_idx+1 < len(last_sbe_row) else None
                    if sec_name and val is not None:
                        try:
                            roc_pct = round(float(val) * 100.0, 2)
                            sectors_roc.append({"sector": sec_name, "roc_5d_pct": roc_pct})
                        except:
                            pass
        sectors_roc.sort(key=lambda x: x["roc_5d_pct"], reverse=True)

        # Fetch matching row in Market Map
        map_row = None
        for r in ws_m.iter_rows(min_row=last_idx, max_row=last_idx, values_only=True):
            map_row = r
            break

        # % above 50/200 DEMA from Data sheet (Breadth row N maps to Data row N-1)
        a50_pct = a200_pct = None
        high_vol_cnt = low_vol_cnt = None
        try:
            ws_d = wb['Data']
            hdr_d = [str(c).strip() for c in next(ws_d.iter_rows(min_row=1, max_row=1, values_only=True))]
            i50, i200 = hdr_d.index('Above 50 DEMA'), hdr_d.index('Above 200 DEMA')
            ihv = hdr_d.index('High Vol') if 'High Vol' in hdr_d else None
            ilv = hdr_d.index('Low Vol') if 'Low Vol' in hdr_d else None
            for r in ws_d.iter_rows(min_row=last_idx - 1, max_row=last_idx - 1, values_only=True):
                univ_d = float(r[3] or 0.0)
                if univ_d > 0 and hasattr(r[0], 'strftime') and r[0].strftime("%d-%b-%Y") == last_item["date"]:
                    a50_pct = float(r[i50] or 0.0) / univ_d * 100.0
                    a200_pct = float(r[i200] or 0.0) / univ_d * 100.0
                    # stock counts above / below average volume (same date-checked row)
                    if ihv is not None and r[ihv] is not None:
                        high_vol_cnt = int(r[ihv])
                    if ilv is not None and r[ilv] is not None:
                        low_vol_cnt = int(r[ilv])
        except Exception as e:
            print(f"⚠️ Trend regime inputs unavailable: {e}")
        # fall back to the Breadth-sheet percentages when the Data-sheet counts are unavailable
        if high_vol_cnt is None:
            high_vol_cnt = int(round(last_item["above_vol_pct"] * last_item["universe"] / 100.0))
        if low_vol_cnt is None:
            low_vol_cnt = int(round(last_item["below_vol_pct"] * last_item["universe"] / 100.0))
        last_item["high_vol_cnt"] = high_vol_cnt
        last_item["low_vol_cnt"] = low_vol_cnt
        recent_vr = [h["vol_ratio"] for h in history[-5:]]
        last_item["vol_ratio_5d_avg"] = round(sum(recent_vr) / len(recent_vr), 2) if recent_vr else None

        wb.close()

        nh_pct = float(map_row[6] or 0.0) * 100.0 if map_row else 0.0
        nl_pct = float(map_row[7] or 0.0) * 100.0 if map_row else 0.0
        nh_cnt = int(round(nh_pct * last_item["universe"] / 100.0))
        nl_cnt = int(round(nl_pct * last_item["universe"] / 100.0))
        net_nh_nl = float(map_row[8] or 0.0) if map_row else 0.0
        net_15_hl = float(map_row[9] or 0.0) if map_row else 0.0
        net_30_hl = float(map_row[10] or 0.0) if map_row else 0.0

        last_item.update({
            "nh_cnt": nh_cnt,
            "nh_pct": nh_pct,
            "nl_cnt": nl_cnt,
            "nl_pct": nl_pct,
            "net_nh_nl": net_nh_nl,
            "net_15_hl": net_15_hl,
            "net_30_hl": net_30_hl,
            "sectoral_5d_roc": {
                "ranking": sectors_roc,
                "top_10": sectors_roc[:10],
                "top_3": sectors_roc[:3],
                "bottom_3": sectors_roc[-3:] if len(sectors_roc) >= 3 else []
            }
        })

        # Run Multi-Day State Machine
        st_data = classify_bonde_multi_day_state(history)
        last_item.update(st_data)
        try:
            last_item["kedia_sa"] = kedia_sa_read(history)
        except Exception as e:
            print(f"⚠️ Kedia SA read unavailable: {e}")
            last_item["kedia_sa"] = {"available": False, "lines": []}

        net10 = None
        if len(history) >= 10:
            net10 = sum(h["net_breadth"] for h in history[-10:]) / 10.0
        last_item.update(classify_trend_regime(a50_pct, a200_pct, net10,
                                               last_item["up_4_pct"], last_item["dn_4_pct"]))
        last_item["uh_lh_net"] = last_item["uh_lh_ratio"]  # sheet value is a net score (UH%-LH%)*100, not a ratio

        return last_item
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
            stk_list = data.get("data", [])
            gappers = []
            for item in stk_list:
                meta = item.get("metadata", {})
                sym = meta.get("symbol")
                pchg = float(meta.get("pChange", 0.0) or 0.0)
                ltp = float(meta.get("lastPrice", 0.0) or 0.0)
                val = float(item.get("detail", {}).get("preOpenMarket", {}).get("totalTurnover", 0.0) or 0.0)
                if sym and pchg >= 0.8 and sym != "NIFTY 50":
                    gappers.append({"symbol": sym, "pChange": pchg, "lastPrice": ltp, "turnover": val})
            gappers.sort(key=lambda x: x["pChange"], reverse=True)
            return {
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged,
                "top_gappers": gappers[:4]
            }
    except Exception:
        return None


PRE_OPEN_GAP_SIEVE_FILE = BASE_DIR / "pre_open_gap_sieve.json"


def classify_pre_open_gaps(candidate_symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    09:12 AM Sniper Gap & Liquidity Bridge:
    Inspects indicative pre-open prices & opening auction gaps for top A+ candidates.
    Classifications:
      • 🟢 PRIME IGNITION (-0.5% to +1.8%): Tight risk, optimal 3m breakout probability.
      • 🔴 EXTENDED / CHASED (> +2.8%): High exhaustion gap trap risk. DO NOT BUY 3m ORB!
      • 🟡 UNDERSHOOT (< -1.5%): Heavy opening gap down. Must reclaim PDH before considering.
      • ⚪ CONSTRUCTIVE FLAT (+1.8% to +2.8% or -1.5% to -0.5%): Normal coiling opening.
    """
    if not candidate_symbols:
        # 1. Try candidates_merged.json (3-Check Sniper Shortlist)
        merged_file = BASE_DIR / "candidates_merged.json"
        if merged_file.is_file():
            try:
                with open(merged_file, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                    snipers = m_data.get("sniper_candidates", [])
                    candidate_symbols = [c["symbol"] for c in snipers if c.get("symbol")]
            except Exception:
                pass

        # 2. Fallback to candidates.json
        if not candidate_symbols:
            c_file = BASE_DIR / "candidates.json"
            if c_file.is_file():
                try:
                    with open(c_file, "r", encoding="utf-8") as f:
                        c_data = json.load(f)
                        candidate_symbols = [c["symbol"] for c in c_data.get("candidates", []) if c.get("symbol")]
                except Exception:
                    pass

        # 3. Fallback to watchlist.txt
        if not candidate_symbols and WATCHLIST_FILE.is_file():
            try:
                with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    candidate_symbols = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
            except Exception:
                pass

    if not candidate_symbols:
        return {"status": "no_candidates", "results": []}

    target_syms = list(dict.fromkeys(candidate_symbols))[:15]  # Deduplicate, top 15 max
    results = []

    # Try bulk Upstox quote if token is active
    cfg = load_config()
    upstox_token = cfg.get("upstox", {}).get("access_token", "").strip()
    quote_map = {}
    if upstox_token:
        try:
            inst_keys = [f"NSE_EQ|{s}" for s in target_syms]
            url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={','.join(inst_keys)}"
            headers = {"Authorization": f"Bearer {upstox_token}", "Accept": "application/json"}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json().get("data", {})
                for k, v in data.items():
                    s = v.get("symbol") or k.split("|")[-1]
                    ohlc = v.get("ohlc", {})
                    ltp = float(v.get("last_price", 0.0) or 0.0)
                    close = float(ohlc.get("close", 0.0) or ltp)
                    open_p = float(ohlc.get("open", 0.0) or ltp)
                    if close > 0:
                        quote_map[s.upper()] = {
                            "ltp": ltp,
                            "prev_close": close,
                            "open": open_p,
                            "source": "Upstox Live Quote"
                        }
        except Exception:
            pass

    for sym in target_syms:
        sym_u = sym.upper()
        ltp = 0.0
        prev_close = 0.0
        src = "None"

        if sym_u in quote_map:
            ltp = quote_map[sym_u]["ltp"]
            prev_close = quote_map[sym_u]["prev_close"]
            src = quote_map[sym_u]["source"]
        else:
            # Yahoo Finance Fallback
            try:
                url_y = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym_u}.NS?interval=1d&range=2d"
                req_y = urllib.request.Request(url_y, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req_y, timeout=4) as resp_y:
                    d_y = json.loads(resp_y.read().decode("utf-8"))
                    meta = d_y["chart"]["result"][0]["meta"]
                    ltp = float(meta.get("regularMarketPrice", 0.0) or 0.0)
                    prev_close = float(meta.get("chartPreviousClose") or meta.get("previousClose") or ltp)
                    src = "Yahoo Finance"
            except Exception:
                pass

        if prev_close > 0 and ltp > 0:
            gap_pct = round(((ltp - prev_close) / prev_close) * 100.0, 2)
            if -0.5 <= gap_pct <= 1.8:
                zone = "IGNITION"
                badge = "🟢 PRIME IGNITION"
                tag = "🔥 Prime 3m ORB Setup"
                action = "Ready for breakout above ORH / PDH"
            elif gap_pct > 2.8:
                zone = "EXTENDED"
                badge = "🔴 EXTENDED / CHASED"
                tag = "⚠️ Exhaustion Gap Trap"
                action = "DO NOT BUY 3m Breakout! Wait for 30m base / VWAP test"
            elif gap_pct < -1.5:
                zone = "UNDERSHOOT"
                badge = "🟡 UNDERSHOOT"
                tag = "🛡️ Opening Under Pressure"
                action = "Wait for reclaim of Previous Day High (PDH)"
            else:
                zone = "CONSTRUCTIVE"
                badge = "⚪ CONSTRUCTIVE FLAT"
                tag = "⚖️ Normal Range Opening"
                action = "Watch opening 3m candle volume confirmation"

            results.append({
                "symbol": sym_u,
                "ltp": round(ltp, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct": gap_pct,
                "zone": zone,
                "badge": badge,
                "tag": tag,
                "action": action,
                "source": src
            })
        else:
            results.append({
                "symbol": sym_u,
                "ltp": 0.0,
                "prev_close": 0.0,
                "gap_pct": 0.0,
                "zone": "CONSTRUCTIVE",
                "badge": "⚪ AWAITING PRINT",
                "tag": "Pre-open quote pending",
                "action": "Awaiting market quote",
                "source": "Pending"
            })

    # Sort results: Ignition first, then Constructive, then Undershoot, then Extended
    zone_order = {"IGNITION": 1, "CONSTRUCTIVE": 2, "UNDERSHOOT": 3, "EXTENDED": 4}
    results.sort(key=lambda x: (zone_order.get(x["zone"], 5), -x["gap_pct"]))

    out_payload = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "total_scanned": len(results),
        "ignition_count": sum(1 for r in results if r["zone"] == "IGNITION"),
        "extended_count": sum(1 for r in results if r["zone"] == "EXTENDED"),
        "undershoot_count": sum(1 for r in results if r["zone"] == "UNDERSHOOT"),
        "constructive_count": sum(1 for r in results if r["zone"] == "CONSTRUCTIVE"),
        "results": results
    }

    try:
        with open(PRE_OPEN_GAP_SIEVE_FILE, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=2)
    except Exception as ex_w:
        print(f"Notice writing pre_open_gap_sieve.json: {ex_w}")

    return out_payload


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

    if preopen_data and preopen_data.get("top_gappers"):
        gap_strs = [f"{g['symbol']} (+{g['pChange']:.1f}%)" for g in preopen_data["top_gappers"]]
        lines.append(f"⚡ <b>09:08 Pre-Open Gappers:</b> {', '.join(gap_strs)}")

    # 09:12 AM Sniper Gap & Liquidity Bridge
    gap_sieve = classify_pre_open_gaps()
    if gap_sieve and gap_sieve.get("results"):
        lines.append("")
        lines.append("🎯 <b>09:12 AM SNIPER GAP & LIQUIDITY BRIDGE:</b>")
        ign = [r for r in gap_sieve["results"] if r["zone"] == "IGNITION"]
        ext = [r for r in gap_sieve["results"] if r["zone"] == "EXTENDED"]
        und = [r for r in gap_sieve["results"] if r["zone"] == "UNDERSHOOT"]
        con = [r for r in gap_sieve["results"] if r["zone"] == "CONSTRUCTIVE"]

        if ign:
            ign_strs = [f"<b>{r['symbol']}</b> ({r['gap_pct']:+.1f}%)" for r in ign[:4]]
            lines.append(f"• 🟢 <b>Prime Ignition (-0.5% to +1.8%):</b> {', '.join(ign_strs)} — <i>Ready for 3m ORB</i>")
        if ext:
            ext_strs = [f"<b>{r['symbol']}</b> ({r['gap_pct']:+.1f}%)" for r in ext[:3]]
            lines.append(f"• 🔴 <b>Extended / Do Not Chase (>+2.8%):</b> {', '.join(ext_strs)} — <i>Wait for 30m base / VWAP</i>")
        if und:
            und_strs = [f"<b>{r['symbol']}</b> ({r['gap_pct']:+.1f}%)" for r in und[:3]]
            lines.append(f"• 🟡 <b>Undershoot (&lt;-1.5%):</b> {', '.join(und_strs)} — <i>Wait for PDH reclaim</i>")
        if con and not ign and not ext:
            con_strs = [f"<b>{r['symbol']}</b> ({r['gap_pct']:+.1f}%)" for r in con[:4]]
            lines.append(f"• ⚪ <b>Constructive Flat:</b> {', '.join(con_strs)} — <i>Watch volume at open</i>")

    vix_item = next((idx for idx in indices_results if idx["name"] == "India VIX"), None)
    if vix_item and vix_item["ltp"] > 0:
        vix_val = vix_item["ltp"]
        vix_chg = vix_item["change_pct"]
        if vix_val < 13.0:
            vix_regime = "Calm / Complacent ☀️"
        elif vix_val <= 16.5:
            vix_regime = "Normal Sweet Spot ⚖️"
        elif vix_val <= 20.0:
            vix_regime = "Elevated Turbulence ⚠️"
        else:
            vix_regime = "High Risk Spike 🚨"
        lines.append(f"🌊 <b>India VIX Volatility:</b> <code>{vix_val:.2f}</code> ({vix_chg:+.1f}% | {vix_regime})")

    # Chhirag Kedia-style #SituationalAwareness read (MBM V2.0 sheet)
    ksa = (bonde or {}).get("kedia_sa") or {}
    if ksa.get("available") and ksa.get("lines"):
        lines.append("")
        lines.extend(ksa["lines"])

    # Stockbee / Pradeep Bonde Market Breadth Section
    if bonde:
        lines.append("")
        lines.append("📊 <b>CHHIRAG KEDIA'S MARKET BREADTH MONITOR</b>")
        lines.append("<i>(Stockbee / Pradeep Bonde Situational Awareness)</i>")
        lines.append(f"🚦 <b>Bonde Market State:</b> <b>{bonde.get('state_label', bonde.get('regime_label', ''))}</b>")
        lines.append(f"💼 <b>Swing Capital Allocation:</b> <b>{bonde.get('allocation_pct', 0)}% Risk</b>")
        lines.append(f"🎯 <b>Action:</b> {bonde.get('state_action', '')}")
        lines.append(f"📈 <b>Trajectory:</b> {bonde.get('trajectory_context', '')}")
        if bonde.get("trend_regime") and bonde["trend_regime"] != "UNAVAILABLE":
            lines.append(f"🧭 <b>Trend Regime:</b> <b>{bonde['trend_regime']}</b> (50DMA {bonde['pct_ab_50']:.0f}% | 200DMA {bonde['pct_ab_200']:.0f}% | 10d net {bonde['net_breadth_10d']:+.1f})")
            lines.append(f"   <i>{bonde['trend_edge']}</i>")
            if bonde.get("trend_overlay"):
                lines.append(f"   ⚠️ {bonde['trend_overlay']}")
        if bonde.get("strip_badge"):
            lines.append(f"🧬 <b>Session Breadth Strip:</b> {bonde['strip_badge']}")
        lines.append("")
        lines.append("🛡️ <b>BONDE DETECTOR SIGNALS:</b>")
        lines.append(f"• <b>Washout Climax:</b> {bonde.get('washout_status', '⚪ QUIET')}")
        lines.append(f"• <b>Ignition Spark:</b> {bonde.get('ignition_status', '⚪ STANDBY')}")
        lines.append(f"• <b>Froth Exhaustion:</b> {bonde.get('froth_status', '⚪ QUIET')}")
        lines.append(f"🔔 <b>Turning Trigger:</b> <code>{bonde.get('ignition_trigger', '')}</code>")
        lines.append("")
        lines.append(f"📋 <b>LAST SESSION ROW METRICS ({bonde['date']} | Row #{bonde['row_idx']}):</b>")
        lines.append(f"• <b>4% Thrust:</b> 🟢 {bonde['up_4_cnt']} Up ({bonde['up_4_pct']:.1f}%) | 🔴 {bonde['dn_4_cnt']} Down ({bonde['dn_4_pct']:.1f}%)")
        lines.append(f"• <b>Net 4% Breadth:</b> <code>{bonde['net_breadth']:+.2f}%</code> {'🟢 Positive' if bonde['net_breadth'] > 0 else '🔴 Negative'}")
        lines.append(f"• <b>Ratios:</b> 5-Day: <b>{bonde['ratio_5d']:.2f}</b> | 10-Day: <b>{bonde['ratio_10d']:.2f}</b>")
        lines.append(f"• <b>52W NH vs NL:</b> {bonde['nh_cnt']} Highs ({bonde['nh_pct']:.1f}%) | {bonde['nl_cnt']} Lows ({bonde['nl_pct']:.1f}%)")
        lines.append(f"• <b>Net NH-NL:</b> <code>{bonde['net_nh_nl']:+.2f}%</code> | <b>Net 15% H-L:</b> <code>{bonde['net_15_hl']:+.2f}%</code>")
        lines.append(f"• <b>Short-Term Cycle Pulse:</b> 1-Month Net: <code>{bonde.get('net_30_hl', 0.0):+.2f}%</code> | 15-Day Net: <code>{bonde.get('net_15_hl', 0.0):+.2f}%</code>")
        lines.append(f"• <b>Breakout Quality:</b> {bonde['bo_sustained']:.1f}% Sustained | <b>{bonde['bo_failure']:.1f}% Failed</b> (S/F: {bonde['bo_sf_ratio']:.2f})")
        lines.append(f"• <b>Breakdown Quality:</b> {bonde['bd_sustained']:.1f}% Sustained | {bonde['bd_failure']:.1f}% Failed (S/F: {bonde['bd_sf_ratio']:.2f})")
        lines.append(f"• <b>Close UH/LH:</b> {bonde['close_uh_pct']:.1f}% Upper | {bonde['close_lh_pct']:.1f}% Lower (UH/LH net score: {bonde['uh_lh_net']:+.1f}, range -100..+100)")
        vol_r = bonde.get('vol_ratio', 0.0)
        vol_state = "Capitulation Blowout 💥" if vol_r >= 1.50 and bonde.get('dn_4_cnt', 0) >= 300 else ("Institutional Surge 🚀" if vol_r >= 1.20 else ("Subdued / Dry 💤" if vol_r < 0.40 else "Normal Baseline ⚖️"))
        vr5 = bonde.get('vol_ratio_5d_avg')
        vr5_txt = ""
        if vr5:
            vr5_trend = "building ↑" if vol_r > vr5 * 1.10 else ("drying up ↓" if vol_r < vr5 * 0.90 else "steady →")
            vr5_txt = f" · 5-day avg {vr5:.2f} ({vr5_trend})"
        hv_c, lv_c = bonde.get('high_vol_cnt'), bonde.get('low_vol_cnt')
        hv_txt = f"{hv_c} stocks above avg vol ({bonde['above_vol_pct']:.1f}%)" if hv_c is not None else f"{bonde['above_vol_pct']:.1f}% above avg vol"
        lv_txt = f"{lv_c} below ({bonde['below_vol_pct']:.1f}%)" if lv_c is not None else f"{bonde['below_vol_pct']:.1f}% below"
        lines.append(f"• 📦 <b>Volume:</b> {hv_txt} · {lv_txt}")
        lines.append(f"   Vol ratio <code>{vol_r:.2f}</code> — {vol_state}{vr5_txt}")

        # Top 10 Subsector / Industry Leaders based on Fresh High Clusters (Breadth Ledger)
        cluster_leaders = []
        try:
            from breadth_ledger_parser import fetch_breadth_ledger_data, get_top_subsectors_by_cluster
            bl_data = fetch_breadth_ledger_data(max_age_minutes=60)
            if bl_data:
                cluster_leaders = get_top_subsectors_by_cluster(bl_data, top_n=10, min_stocks=3)
        except Exception:
            cluster_leaders = []

        if cluster_leaders:
            lines.append("")
            lines.append("🏆 <b>TOP 10 SUBSECTOR LEADERS (Fresh High Cluster Density):</b>")
            lines.append("<i>(Breadth Ledger: Share of stocks at 3-Month Highs today)</i>")
            for rank, item in enumerate(cluster_leaders, 1):
                badge = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank}"))
                s_name = item['industry']
                share_3m = item['share_3m_pct']
                h3 = item['high_3m_count']
                n = item['total_stocks']
                leaders_str = ", ".join(item['leaders'][:3])
                icon = "🚀" if share_3m >= 40.0 else ("🟢" if share_3m >= 20.0 else "⚪")
                lead_txt = f" | {leaders_str}" if leaders_str else ""
                lines.append(f"• {badge} <b>{s_name}:</b> <code>{h3}/{n}</code> at 3M High (<b>{share_3m:.1f}%</b>) {icon}{lead_txt}")

            top_sec_names = " and ".join([item['industry'] for item in cluster_leaders[:2]])
            lines.append(f"• 💡 <b>Cluster Mandate:</b> Institutional accumulation heaviest in <b>{top_sec_names}</b>. Prioritize watchlist breakout setups in these leading cluster subsectors.")
        else:
            # Fallback to SBE 5D ROC if Breadth Ledger API unavailable
            sec_data = bonde.get("sectoral_5d_roc", {})
            top_10 = sec_data.get("top_10", [])
            laggards = sec_data.get("bottom_3", [])
            if top_10:
                lines.append("")
                lines.append("🏆 <b>TOP 10 SUBSECTOR LEADERS (5-Day ROC Ranking):</b>")
                for rank, item in enumerate(top_10, 1):
                    s_name = item['sector']
                    roc = item['roc_5d_pct']
                    sign = "+" if roc > 0 else ""
                    icon = "🚀" if roc >= 3.0 else ("🟢" if roc > 0 else ("🔴" if roc < 0 else "⚪"))
                    badge = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank}"))
                    lines.append(f"• {badge} <b>{s_name}:</b> <code>{sign}{roc:.2f}%</code> {icon}")
                if laggards:
                    lag_strs = [f"{item['sector']} ({item['roc_5d_pct']:+.2f}%)" for item in laggards]
                    lines.append(f"• 🔻 <b>Laggards:</b> {' | '.join(lag_strs)}")
                top_sec_names = " and ".join([item['sector'] for item in top_10[:2]])
                lines.append(f"• 💡 <b>Leadership Mandate:</b> Primary institutional momentum clustered in <b>{top_sec_names}</b>. Prioritize watchlist breakout setups strictly in these top 10 subsectors.")

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

    # Breadth Ledger 90D/30% Narrow Range (NR) Momentum Setups
    try:
        from scan_nr_momo import scan_nr_momentum_candidates
        nr_summary = scan_nr_momentum_candidates(max_workers=15)
        t1_nr = nr_summary.get("tier1_candidates", [])
        t2_nr = nr_summary.get("tier2_candidates", [])

        if t1_nr or t2_nr:
            lines.append("")
            lines.append("🎯 <b>90D MOMO NARROW RANGE (NR) SNIPER SETUPS:</b>")
            lines.append("<i>Filtered for NR4 / NR7 / Inside Day Coils &bull; Minimum LOD Risk</i>")
            if t1_nr:
                lines.append("<b>🚪 Tier 1 Doorstep Coils (≤3% from High):</b>")
                for c in t1_nr[:6]:
                    d_txt = f"-{c['dist_52w_pct']:.1f}%" if c.get('dist_52w_pct') is not None else "3M High"
                    flag = " 👑" if c.get('is_fresh_3m') else ""
                    tag = c.get('nr_tags', ['NR'])[0] if c.get('nr_tags') else 'NR'
                    lines.append(f"• <b>{c['symbol']}</b>: <code>{tag}</code> ({c.get('daily_range_pct', 0):.1f}% rng) | <code>{d_txt}</code> ({c.get('industry', 'Equity')}){flag}")
            if t2_nr:
                lines.append("<b>🚀 Tier 2 Launchpad Coils (3-7% from High):</b>")
                for c in t2_nr[:4]:
                    d_txt = f"-{c['dist_52w_pct']:.1f}%" if c.get('dist_52w_pct') is not None else "Launchpad"
                    tag = c.get('nr_tags', ['NR'])[0] if c.get('nr_tags') else 'NR'
                    lines.append(f"• <b>{c['symbol']}</b>: <code>{tag}</code> ({c.get('daily_range_pct', 0):.1f}% rng) | <code>{d_txt}</code>")
        else:
            from breadth_ledger_parser import fetch_breadth_ledger_data, get_90d_momo_candidates
            bl_data = fetch_breadth_ledger_data(max_age_minutes=60)
            if bl_data:
                c_res = get_90d_momo_candidates(bl_data)
                t1 = [c for c in c_res["actionable_candidates"] if c["tier"] == "TIER_1_DOORSTEP"][:5]
                if t1:
                    lines.append("")
                    lines.append("🔥 <b>90D MOMENTUM DOORSTEP CANDIDATES (Gained ≥30% in 90D):</b>")
                    for c in t1:
                        d_txt = f"-{c['dist_52w_pct']:.1f}%" if c['dist_52w_pct'] is not None else "3M High"
                        flag = " 👑" if c['is_fresh_3m'] else ""
                        lines.append(f"• <b>{c['symbol']}</b>: <code>{d_txt}</code> from 52W High ({c['industry']} | {c['gain_tier']}){flag}")
    except Exception as e:
        print(f"Notice: Pre-market NR momo scan exception: {e}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if bonde and bonde.get("mandate_headline"):
        lines.append("🎯 <b>EXECUTIVE ACTION ORDER (WHAT TO DO TODAY):</b>")
        lines.append(f"• <b>Mandate:</b> <b>{bonde['mandate_headline']}</b>")
        lines.append(f"• <b>Intraday (09:15-15:15):</b> {bonde['action_intra']}")
        lines.append(f"• <b>Swing (1-10 Days):</b> {bonde['action_swing']}")
        lines.append(f"• <b>Positional (Weeks):</b> {bonde['action_positional']}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    lines.append("💡 <b>TACTICAL PLAYBOOK (09:15 AM BELL):</b>")
    if bonde and bonde.get("tactical_rule"):
        lines.append(f"• <b>Bonde Playbook:</b> {bonde['tactical_rule']}")

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


_SA_SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def _tg_visible_len(html_text: str) -> int:
    """Length Telegram counts against its 4096 limit: text after tags/entities are parsed, in UTF-16 units."""
    visible = html_lib.unescape(re.sub(r"<[^>]+>", "", html_text))
    return len(visible.encode("utf-16-le")) // 2


def chunk_telegram_html(msg_html: str, limit: int = 3800) -> List[str]:
    """Split an HTML card into messages of at most `limit` visible chars (Telegram max 4096).

    Packs whole lines (each card line closes its own tags) and, when a message is full, cuts at its last ━━━
    separator, else its last blank line, else the last line — as long as the message is at least half full,
    so no tiny leftover messages. A card that fits is sent unchanged.
    """
    if _tg_visible_len(msg_html) <= limit:
        return [msg_html]

    def best_cut(cur: List[str]) -> int:
        for marker in (lambda l: l.strip() == _SA_SEP, lambda l: not l.strip()):
            for i in range(len(cur) - 1, 0, -1):
                if marker(cur[i]) and _tg_visible_len("\n".join(cur[:i])) >= limit // 2:
                    return i
        return len(cur)

    chunks: List[str] = []
    cur: List[str] = []
    for line in msg_html.split("\n"):
        if cur and _tg_visible_len("\n".join(cur + [line])) > limit:
            cut = best_cut(cur)
            chunks.append("\n".join(cur[:cut]))
            rest = cur[cut:]
            if rest and rest[0].strip() == _SA_SEP:   # the separator at the cut is not repeated on the next message
                rest = rest[1:]
            cur = rest
        cur.append(line)
    if cur:
        chunks.append("\n".join(cur))
    return [c.strip() for c in chunks if c.strip()]


def send_telegram_alert(msg_html: str, config: Dict[str, Any]) -> Tuple[bool, str]:
    """Dispatches the pre-market summary to Telegram chat, safely chunking if > 4000 chars."""
    tg_cfg = config.get("telegram", {})
    if not tg_cfg.get("enabled", True):
        return False, "Telegram disabled in config"

    bot_token = tg_cfg.get("bot_token", "").strip()
    chat_id = tg_cfg.get("chat_id", "").strip()
    group_id = tg_cfg.get("group_id", "").strip()
    topics = tg_cfg.get("topics", {})
    thread_id = topics.get("reports") if group_id else None
    target_chat = group_id if (group_id and thread_id) else chat_id

    if not bot_token or not target_chat:
        return False, "Bot token or chat ID missing in config"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Telegram hard limit: 4096 chars per message. Chunk safely if needed.
    chunks = chunk_telegram_html(msg_html)

    all_ok = True
    last_err = ""
    for c in chunks:
        if not c.strip():
            continue
        payload = {
            "chat_id": target_chat,
            "text": c,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if not res_data.get("ok"):
                    all_ok = False
                    last_err = str(res_data)
        except Exception as e:
            all_ok = False
            last_err = str(e)
            try:  # keep Telegram's own reason (e.g. "message is too long", "can't parse entities")
                if hasattr(e, "read"):
                    last_err += " — " + e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            last_err += f" [chunk {chunks.index(c) + 1}/{len(chunks)}, {_tg_visible_len(c)} visible chars]"

    if all_ok:
        return True, "Delivered"
    return False, last_err


def main():
    if "--pre-open-sieve" in sys.argv or "--gap-sieve" in sys.argv:
        if not is_market_day(datetime.now()) and "--force" not in sys.argv and "--test" not in sys.argv:
            print("ℹ️ Gap sieve skipped: weekend or NSE holiday (no pre-open session). Use --force to override.")
            return
        print("=" * 65)
        print("🎯 JARVIS 09:12 AM SNIPER GAP & LIQUIDITY SIEVE")
        print("=" * 65)
        res = classify_pre_open_gaps()
        print(f"Scanned: {res.get('total_scanned')} candidates")
        print(f"Prime Ignition (🟢): {res.get('ignition_count')}")
        print(f"Extended Trap (🔴): {res.get('extended_count')}")
        print(f"Undershoot (🟡): {res.get('undershoot_count')}")
        for r in res.get("results", []):
            print(f"  • {r['symbol']}: {r['gap_pct']:+.2f}% | {r['badge']} -> {r['action']}")
        return

    force_run = "--force" in sys.argv or "--test" in sys.argv
    now_dt = datetime.now()
    cfg = load_config()

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
        print(f"\n🚦 Stockbee State  : {bonde.get('state_label', '')}")
        print(f"🎯 Action Mandate  : {bonde.get('mandate_headline', '')}")
        print(f"💼 Allocation      : {bonde.get('allocation_pct', 0)}% Risk")
        print(f"🎯 State Guidance  : {bonde.get('state_action', '')}")
        print(f"📈 Trajectory      : {bonde.get('trajectory_context', '')}")
        print(f"🛡️ Detectors       : Washout={bonde.get('washout_status')} | Ignition={bonde.get('ignition_status')} | Froth={bonde.get('froth_status')}")
        print(f"📋 Last Breadth Row: {bonde['date']} (Row #{bonde['row_idx']})")
        print(f"   • 4% Thrust     : {bonde['up_4_cnt']} Up ({bonde['up_4_pct']:.1f}%) | {bonde['dn_4_cnt']} Down ({bonde['dn_4_pct']:.1f}%)")
        print(f"   • Net 4% Breadth: {bonde['net_breadth']:+.2f}%")
        print(f"   • 5D / 10D Ratio: {bonde['ratio_5d']:.2f} / {bonde['ratio_10d']:.2f}")
        print(f"   • 52W NH / NL   : {bonde['nh_cnt']} Highs | {bonde['nl_cnt']} Lows (Net: {bonde['net_nh_nl']:+.2f}%)")
        print(f"   • BO Failure %  : {bonde['bo_failure']:.1f}%")
        print(f"   • Volume        : {bonde.get('high_vol_cnt', '?')} above avg ({bonde['above_vol_pct']:.1f}%) | "
              f"{bonde.get('low_vol_cnt', '?')} below ({bonde['below_vol_pct']:.1f}%) | ratio {bonde.get('vol_ratio', 0.0):.2f}"
              + (f" (5D avg {bonde['vol_ratio_5d_avg']:.2f})" if bonde.get('vol_ratio_5d_avg') else ""))

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

    # Save market regime state for scanner & tablet dashboard
    try:
        regime_file = BASE_DIR / "market_regime.json"
        risk_cfg = cfg.get("risk_parameters", {})
        alloc_pct = bonde.get("allocation_pct", 0) if bonde else 0
        swing_multiplier = alloc_pct / 100.0
        base_swing_risk = risk_cfg.get("swing", {}).get("base_risk_per_trade", 10000)
        swing_risk = int(base_swing_risk * swing_multiplier)

        vol_r = bonde.get("vol_ratio", 0.50) if bonde else 0.50
        vol_st = "PANIC_CAPITULATION" if vol_r >= 1.50 and (bonde and bonde.get("dn_4_cnt", 0) >= 300) else (
            "INSTITUTIONAL_THRUST" if vol_r >= 1.50 and (bonde and bonde.get("up_4_cnt", 0) >= 200) else (
            "ABOVE_AVERAGE" if vol_r >= 1.00 else (
            "NORMAL_BASELINE" if vol_r >= 0.40 else "DRY_CHOP"
        )))
        bo_sf_r = bonde.get("bo_sf_ratio", 1.0) if bonde else 1.0

        regime_payload = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "state_code": bonde.get("state_code", "WASHOUT") if bonde else "WASHOUT",
            "state_label": bonde.get("state_label", "") if bonde else "",
            "guidance": bonde.get("state_action", "") if bonde else "",
            "swing_allocation_pct": alloc_pct,
            "swing_risk_per_trade": swing_risk,
            "intraday_risk_per_trade": risk_cfg.get("intraday", {}).get("max_risk_per_trade", 1000),
            "intraday_max_daily_loss": risk_cfg.get("intraday", {}).get("max_daily_loss", 2000),
            "intraday_max_open_trades": risk_cfg.get("intraday", {}).get("max_open_trades", 2),
            "fakeout_warning": (f"HIGH FAKEOUT RISK: {float(bonde.get('bo_failure', 0.0) or 0.0):.0f}% of recent long breakouts failed "
                                f"(S/F {float(bo_sf_r):.2f})." if bonde else "HIGH FAKEOUT RISK: breakout failure rate unavailable.")
                               if alloc_pct == 0 else "NORMAL EXECUTION",
            "breakout_quality": {
                "bo_sf_ratio": bo_sf_r,
                "bo_sustained_pct": bonde.get("bo_sustained", 0.0) if bonde else 0.0,
                "bo_failure_pct": bonde.get("bo_failure", 0.0) if bonde else 0.0,
                "uh_lh_ratio": bonde.get("uh_lh_ratio", 1.0) if bonde else 1.0,
                "trap_active": (bo_sf_r < 1.0)
            },
            "volume_telemetry": {
                "vol_ratio": vol_r,
                "vol_state": vol_st,
                "above_vol_pct": bonde.get("above_vol_pct", 0.0) if bonde else 0.0,
                "below_vol_pct": bonde.get("below_vol_pct", 0.0) if bonde else 0.0,
                "vol_description": f"Institutional Vol Ratio: {vol_r:.2f} ({vol_st})"
            },
            "breadth_snapshot": {
                "date": bonde.get("date") if bonde else "",
                "up_4_count": bonde.get("up_4_cnt") if bonde else 0,
                "dn_4_count": bonde.get("dn_4_cnt") if bonde else 0,
                "net_breadth": bonde.get("net_breadth") if bonde else 0,
                "ratio_5d": bonde.get("ratio_5d") if bonde else 0,
                "ratio_10d": bonde.get("ratio_10d") if bonde else 0
            }
        }
        with open(regime_file, "w", encoding="utf-8") as f:
            json.dump(regime_payload, f, indent=2)
        print(f"💾 Synchronized {regime_file.name} (Allocation: {alloc_pct}%)")

        # Save complete 09:14 SA summary and Telegram alert card for Web Dashboard & Tablet
        sa_summary_file = BASE_DIR / "pre_market_summary.json"
        sa_payload = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": bonde.get("date") if bonde else datetime.now().strftime("%d-%b-%Y"),
            "bias": summary.get("bias", ""),
            "nifty_ltp": summary.get("nifty_ltp"),
            "nifty_chg_pct": summary.get("nifty_chg_pct"),
            "advances": summary.get("advances", 0),
            "declines": summary.get("declines", 0),
            "top_sector": summary.get("top_sector"),
            "worst_sector": summary.get("worst_sector"),
            "benchmarks": summary.get("benchmarks", []),
            "sectorals": summary.get("sectorals", []),
            "bonde_breadth": bonde,
            "telegram_msg_html": msg_html
        }
        with open(sa_summary_file, "w", encoding="utf-8") as saf:
            json.dump(sa_payload, saf, indent=2)
        print(f"💾 Synchronized {sa_summary_file.name} (Full 09:14 SA Card & Telegram Alert Saved)")
    except Exception as e:
        print(f"⚠️ Error updating market_regime.json: {e}")

    print("-" * 65)
    print("📱 Dispatching Pre-Open Alert to Telegram...")
    ok, err = send_telegram_alert(msg_html, cfg)
    if ok:
        print("✅ Telegram Pre-Open Situational Awareness Card delivered successfully!")
    else:
        print(f"❌ Telegram dispatch notice: {err}")

    print("=" * 65)


if __name__ == "__main__":
    main()
