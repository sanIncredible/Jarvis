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
import sys
import json
import time
import html
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
        "action_positional": action_positional
    }


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
                "top_3": sectors_roc[:3],
                "bottom_3": sectors_roc[-3:] if len(sectors_roc) >= 3 else []
            }
        })

        # Run Multi-Day State Machine
        st_data = classify_bonde_multi_day_state(history)
        last_item.update(st_data)

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
            return {
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged
            }
    except Exception:
        return None


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


def make_box_table(rows: List[List[Any]], headers: List[str], col_widths: List[int], aligns: Optional[List[str]] = None) -> str:
    """
    Renders an exact monospaced Unicode box-drawing table for Telegram <pre> blocks.
    Fits cleanly within mobile screens and terminal consoles (~38-40 chars wide).
    Safely escapes HTML entities (<, >, &) so Telegram never rejects formatted text.
    """
    if aligns is None:
        aligns = ['left'] * len(headers)
    top = '┌' + '┬'.join('─' * (w + 2) for w in col_widths) + '┐'
    sep = '├' + '┼'.join('─' * (w + 2) for w in col_widths) + '┤'
    bot = '└' + '┴'.join('─' * (w + 2) for w in col_widths) + '┘'

    def pad_cell(val: Any, w: int, a: str) -> str:
        s = str(val)[:w]
        if a == 'right':
            raw = ' ' + s.rjust(w) + ' '
        elif a == 'center':
            raw = ' ' + s.center(w) + ' '
        else:
            raw = ' ' + s.ljust(w) + ' '
        return html.escape(raw)

    def render_row(vals: List[Any]) -> str:
        return '│' + '│'.join(pad_cell(v, w, a) for v, w, a in zip(vals, col_widths, aligns)) + '│'

    res = [top, render_row(headers), sep]
    for r in rows:
        res.append(render_row(r))
    res.append(bot)
    return '\n'.join(res)


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

    def clean_plain(txt: str) -> str:
        """Strips leading emojis/bullets for clean monospaced table display."""
        if not txt:
            return ""
        for pfx in ["🔴 ", "🟢 ", "⚪ ", "★ ", "⚠️ ", "• ", "🎯 ", "📊 ", "🚦 ", "💼 ", "📈 "]:
            txt = txt.replace(pfx, "")
        return txt.strip()

    # 7. Build Structured Tabular Telegram Message
    lines = [
        "⚡ <b>JARVIS PRE-OPEN SITUATIONAL AWARENESS</b>",
        f"📅 <code>{now_str}</code> (Pre-Market Pulse)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🎯 <b>EXECUTIVE REGIME &amp; INDICATIVE BIAS:</b>",
    ]

    # Table 1: Regime & Indicative Bias
    t1_rows = []
    if bonde:
        state_str = clean_plain(bonde.get('state_label', bonde.get('regime_label', 'NEUTRAL')))
        t1_rows.append(["Market State", state_str[:17]])
        t1_rows.append(["Swing Risk Alloc", f"{bonde.get('allocation_pct', 0)}% Risk"])
    bias_type = "Bull Gap " if ("Bullish" in bias_label or nifty_chg_pct > 0.15) else ("Bear Gap " if ("Gap-Down" in bias_label or nifty_chg_pct < -0.15) else "Flat Open ")
    bias_cell = f"{bias_type}({nifty_chg_pct:+.2f}%)"
    t1_rows.append(["Indicative Bias", bias_cell[:17]])
    t1_rows.append(["Indices (A : D)", f"{advances} Adv : {declines} Dec"])
    if preopen_data and preopen_data.get("advances") is not None and (preopen_data["advances"] + preopen_data["declines"]) > 0:
        t1_rows.append(["Nifty50 Pre-Open", f"{preopen_data['advances']} Adv : {preopen_data['declines']} Dec"])

    lines.append("<pre>")
    lines.append(make_box_table(t1_rows, ["METRIC", "STATUS / VALUE"], [16, 17], ["left", "left"]))
    lines.append("</pre>")

    # Stockbee / Pradeep Bonde Market Breadth Section
    if bonde:
        lines.append("")
        lines.append("🛡️ <b>BONDE DETECTOR SIGNALS &amp; TRIGGERS:</b>")
        w_raw = bonde.get('washout_status', 'QUIET')
        if "ACTIVE" in w_raw:
            w_val = f"ACTIVE ({bonde.get('peak_dn4_count', 0)}->{bonde.get('dn_4_cnt', 0)})" if bonde.get('peak_dn4_count') else "ACTIVE (Selling)"
        elif "TRIGGERED" in w_raw:
            w_val = "TRIGGERED"
        else:
            w_val = "QUIET"

        i_raw = bonde.get('ignition_status', 'STANDBY')
        if "ARMED" in i_raw:
            i_val = "ARMED (>150u/<80d)"
        elif "FIRED" in i_raw or "CONFIRMED" in i_raw:
            i_val = "FIRED (Day-1)"
        else:
            i_val = "STANDBY"

        f_raw = bonde.get('froth_status', 'QUIET')
        if "EXHAUSTION" in f_raw or "FROTH" in f_raw:
            f_val = "FROTH ALERT"
        else:
            f_val = f"QUIET (5D:{bonde.get('ratio_5d', 0):.2f})"

        t2_rows = [
            ["Washout Climax", w_val[:17]],
            ["Ignition Spark", i_val[:17]],
            ["Froth Exhaust",  f_val[:17]],
        ]
        lines.append("<pre>")
        lines.append(make_box_table(t2_rows, ["DETECTOR PULSE", "STATUS / TRIGGER"], [16, 17], ["left", "left"]))
        lines.append("</pre>")
        if bonde.get('ignition_trigger'):
            lines.append(f"🔔 <b>Turning Trigger:</b> <code>{bonde['ignition_trigger']}</code>")

        lines.append("")
        lines.append(f"📋 <b>LAST SESSION BREADTH &amp; QUALITY ({bonde['date']} | #{bonde['row_idx']}):</b>")
        t3_thrust = [
            ["4% Thrust", f"{bonde['up_4_cnt']}({bonde['up_4_pct']:.0f}%)", f"{bonde['dn_4_cnt']}({bonde['dn_4_pct']:.0f}%)"],
            ["52W High / Low", f"{bonde['nh_cnt']}({bonde['nh_pct']:.0f}%)", f"{bonde['nl_cnt']}({bonde['nl_pct']:.0f}%)"],
            ["Breakout Qual", f"{bonde['bo_sustained']:.0f}% Sus", f"{bonde['bo_failure']:.0f}% Fail"],
            ["Breakdown Qual", f"{bonde['bd_sustained']:.0f}% Sus", f"{bonde['bd_failure']:.0f}% Fail"],
            ["Close UH vs LH", f"{bonde['close_uh_pct']:.0f}% UH", f"{bonde['close_lh_pct']:.0f}% LH"],
        ]
        lines.append("<pre>")
        lines.append(make_box_table(t3_thrust, ["METRIC", "BULL", "BEAR"], [14, 9, 9], ["left", "right", "right"]))
        lines.append("</pre>")

        # Key Ratios Table
        vol_r = bonde.get('vol_ratio', 0.0)
        vol_state = "BLOWOUT" if vol_r >= 1.50 and bonde.get('dn_4_cnt', 0) >= 300 else ("SURGE" if vol_r >= 1.20 else ("DRY" if vol_r < 0.40 else "NORMAL"))
        t3_ratios = [
            ["Net 4% Breadth", f"{bonde['net_breadth']:+.2f}%", "BULL" if bonde['net_breadth'] > 0 else "BEAR"],
            ["5D / 10D Ratio", f"{bonde['ratio_5d']:.2f} / {bonde['ratio_10d']:.2f}", "PULSE"],
            ["Net 52W NH-NL", f"{bonde['net_nh_nl']:+.2f}%", "EXPAND" if bonde['net_nh_nl'] > 0 else "CONTRACT"],
            ["Volume Ratio", f"{vol_r:.2f}x", vol_state],
        ]
        lines.append("<pre>")
        lines.append(make_box_table(t3_ratios, ["KEY RATIO", "VALUE", "STATE"], [14, 11, 8], ["left", "right", "center"]))
        lines.append("</pre>")

        # 5-Day Sectoral 5D ROC Leaders (Kedia SBE Clumping)
        sec_data = bonde.get("sectoral_5d_roc", {})
        leaders = sec_data.get("top_3", [])
        laggards = sec_data.get("bottom_3", [])
        if leaders:
            lines.append("")
            lines.append("🏆 <b>5-DAY SECTORAL LEADERS (Kedia 5D ROC Clumping):</b>")
            t4_rows = []
            for idx, item in enumerate(leaders, 1):
                t4_rows.append([str(idx), item['sector'][:19], f"{item['roc_5d_pct']:+.2f}%"])
            if laggards:
                for item in laggards:
                    t4_rows.append(["L", item['sector'][:19], f"{item['roc_5d_pct']:+.2f}%"])
            lines.append("<pre>")
            lines.append(make_box_table(t4_rows, ["RK", "SECTOR (5D ROC)", "RETURN"], [3, 19, 9], ["center", "left", "right"]))
            lines.append("</pre>")
            top_sec_names = " and ".join([item['sector'] for item in leaders[:2]])
            lines.append(f"💡 <b>Sector Mandate:</b> Institutional accumulation active in <b>{top_sec_names}</b>. Prioritize watchlist breakout setups strictly in these sectors; avoid laggards.")
    lines.append("")
    lines.append("🏛 <b>BENCHMARKS &amp; SECTORAL MOMENTUM:</b>")
    t5_rows = []
    for b in benchmarks:
        t5_rows.append([b['name'][:15], f"{b['ltp']:,.1f}", f"{b['change_pct']:+.2f}%"])
    for s in sectorals[:4]:
        tag = "*" if (s == top_sector and s["change_pct"] > 0) else ("!" if (s == worst_sector and s["change_pct"] < 0) else "")
        t5_rows.append([(s['name'][:14] + tag), f"{s['ltp']:,.1f}", f"{s['change_pct']:+.2f}%"])
    lines.append("<pre>")
    lines.append(make_box_table(t5_rows, ["INDEX / SECTOR", "LTP (₹)", "CHG %"], [15, 9, 7], ["left", "right", "right"]))
    lines.append("</pre>")
    if top_sector and worst_sector:
        lines.append(f"• <i>*Leader: {top_sector['name']} ({top_sector['change_pct']:+.2f}%) | !Laggard: {worst_sector['name']} ({worst_sector['change_pct']:+.2f}%)</i>")

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
            "fakeout_warning": "HIGH FAKEOUT RISK: 80%+ of long breakouts fail in this regime." if alloc_pct == 0 else "NORMAL EXECUTION",
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
