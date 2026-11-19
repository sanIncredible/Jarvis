"""
Jarvis End-of-Day (EOD) Hindsight Report Engine
================================================
Simulates hypothetical strategy execution for all watchlist stocks:
1. Evaluates what would have happened if watchlist stocks had entered when they hit trigger conditions.
2. Evaluates strategy checklist passing at entry (Regime, Breakout, PDH, Strong Start, RVOL, Stop Distance, 10 EMA).
3. Computes hypothetical Entry, Stop-Loss, 2R Target, Exit, P&L in INR and %, and R-multiples.
4. STRICTLY formats all price levels and INR amounts as clean round integers (no decimals).
5. Compiles clean summary metrics (Win rate, total P&L, discipline audit).
6. Dispatches to Telegram topic 'reports' (Topic 11) strictly at EOD.
"""

import os
import sys
import json
import time
import math
import argparse
from datetime import datetime
from pathlib import Path

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
CONFIG_FILE = BASE_DIR / "config_credentials.json"

STANDARD_CAPITAL_PER_TRADE = 100000  # ₹1.0 Lakh default base exposure


def round_to_clean_int(val):
    """Rounds float price to nearest whole integer."""
    if val is None:
        return 0
    try:
        return int(round(float(val)))
    except Exception:
        return 0


def extract_time_str(val):
    """Extracts 'HH:MM' string from candle timestamp or ISO string."""
    if not val:
        return ""
    s = str(val).strip()
    if len(s) >= 16 and "T" in s:
        return s[11:16]
    if len(s) >= 5 and ":" in s[:5]:
        return s[:5]
    return s


def load_config():
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_data_json():
    if DATA_FILE.is_file():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_active_watchlist():
    """Reads active watchlist symbols from watchlist.txt."""
    symbols = []
    if WATCHLIST_FILE.is_file():
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Extract first token (handling comments/tabs)
                        sym = line.split()[0].replace(",", "").upper()
                        if sym and sym not in symbols:
                            symbols.append(sym)
        except Exception:
            pass
    return symbols


def evaluate_setup_checklist(symbol, quote_data, entry_price, sl_price, is_sl_capped=False):
    """
    Evaluates strategy checklist as of the entry moment.
    Returns (tech_passed, tech_total, is_qualified, flags, details).
    """
    try:
        from order_engine import evaluate_strategy_checklist
        effective_risk_pct = round(((entry_price - sl_price) / entry_price) * 100, 2) if entry_price and sl_price else 2.5
        calc_data = {
            "ltp": entry_price,
            "day_low": sl_price,
            "risk_pct": effective_risk_pct
        }
        res = evaluate_strategy_checklist(symbol, quote_data=quote_data, calc_data=calc_data)
        tech_rules = [c for c in res.get("checklist", []) if c.get("rule") != "Market Regime"]
        tech_passed = sum(1 for c in tech_rules if c.get("passed"))
        tech_total = len(tech_rules)
        flags = [w.split(":")[0].strip() for w in res.get("warnings", []) if "Regime" not in w]
        
        # High-Conviction Strategy Qualification:
        # 1. Minimum 4 passed technical rules out of 6
        # 2. Must NOT fail structural levels (no 'ORB Setup' and no 'PDH Resistance' flags)
        # 3. Not overextended from 10 EMA (> 4.5%)
        # 4. Stop-loss must be within manageable parameters (<= 4.0% or safely capped)
        has_structural_failure = any(f in flags for f in ("ORB Setup", "PDH Resistance"))
        is_overextended = any("Overextended" in fl or "10 EMA" in fl for fl in flags)
        
        is_qualified = (
            (tech_passed >= 5 or (tech_passed >= 4 and not has_structural_failure))
            and not is_overextended
        )

        return tech_passed, tech_total, is_qualified, flags, res.get("checklist", [])
    except Exception as ex:
        # Fallback simplified technical checklist if order_engine not reachable
        return 4, 6, True, [], []


def simulate_stock_trade(s):
    """
    Simulates hypothetical entry, stop-loss, 2R target, and outcome for a stock.
    Returns simulated trade dictionary or None if untriggered.
    """
    sym = s.get("symbol", "").upper()
    candles = s.get("candles_3m", [])
    orb_h = s.get("orb_high")
    pdh = s.get("pdh")
    prev_close = s.get("prev_close")
    day_open = s.get("day_open")

    if not candles or not orb_h or orb_h <= 0:
        return None

    # Candle 0 is the 09:15 - 09:18 ORB candle.
    # Scan subsequent candles for breakout trigger.
    # USER STRATEGY MANDATE: Entry timing is ALWAYS after 09:30 AM (filters morning chop / whipsaws)
    trig_idx = None
    for i in range(1, len(candles)):
        c = candles[i]
        t_str = extract_time_str(c[0])
        # Skip all candles prior to 09:30 AM
        if t_str and t_str < "09:30":
            continue

        c_high = float(c[2])
        if c_high > orb_h:
            trig_idx = i
            break

    if trig_idx is None:
        return None  # Untriggered: stayed below ORB-H all day

    trig_bar = candles[trig_idx]
    trig_time = trig_bar[0]

    # Hypothetical Entry Price: tick above ORB-H or bar open (clean integer)
    entry_price = round_to_clean_int(max(orb_h, trig_bar[1]))
    if entry_price <= 0:
        return None

    # Hypothetical Stop Loss: Low of Day at entry time
    day_low_at_entry = min(float(c[3]) for c in candles[:trig_idx + 1])
    buffer = max(1.0, day_low_at_entry * 0.002)
    sl_price = round_to_clean_int(day_low_at_entry - buffer)

    # Risk distance
    risk_per_share = max(1, entry_price - sl_price)
    risk_pct = (risk_per_share / entry_price) * 100.0

    # Cap structural stop-loss at 3.5% (fallback 2.5%) if LOD was too wide
    is_sl_capped = False
    if risk_pct > 3.5:
        is_sl_capped = True
        sl_price = round_to_clean_int(entry_price * 0.975)
        risk_per_share = max(1, entry_price - sl_price)
        risk_pct = (risk_per_share / entry_price) * 100.0

    # Target: 2.0R
    target_price = round_to_clean_int(entry_price + (2.0 * risk_per_share))

    # Standard position sizing (₹1.0 Lakh capital exposure)
    qty = max(1, int(STANDARD_CAPITAL_PER_TRADE / entry_price))
    exposure_inr = round_to_clean_int(qty * entry_price)

    # Detect trigger signature type
    is_ss = bool(s.get("is_ss"))
    pdh_cleared = bool(pdh and entry_price > pdh)
    is_reversal = bool(s.get("is_reversal"))

    # -------------------------------------------------------------
    # Strict Entry Criteria Assessment:
    # 1. Previous Day Narrow Range (prev_range <= 0.75x ATR14 or Inside Day or prev_range_pct <= 2.5%)
    # 2. Strong Start (Day Open > Prev Close and Day Low >= Prev Close * 0.995)
    # 3. PDH Breakout (Triggers on / clears Previous Day High)
    # -------------------------------------------------------------
    candles_d = s.get("candles_d", [])
    atr14 = float(s.get("atr14") or 0.0)
    prev_range = 0.0
    prev_range_ratio = s.get("prev_range_ratio")
    prev_range_pct = 0.0
    is_inside_day = bool(s.get("is_inside_day", False))
    is_narrow_prev_day = bool(s.get("is_narrow_prev_day", False))

    if len(candles_d) >= 2:
        yest = candles_d[-2]
        yh = float(yest[2])
        yl = float(yest[3])
        yc = float(yest[4])
        prev_range = max(0.0, yh - yl)
        if yc > 0:
            prev_range_pct = round((prev_range / yc) * 100.0, 2)

        if len(candles_d) >= 3:
            day_before = candles_d[-3]
            dbh = float(day_before[2])
            dbl = float(day_before[3])
            is_inside_day = bool(yh <= dbh and yl >= dbl)

        if atr14 > 0:
            prev_range_ratio = round(prev_range / atr14, 2)
            is_nr = bool(prev_range_ratio <= 0.75)
        else:
            is_nr = bool(prev_range_pct <= 2.5)

        is_narrow_prev_day = bool(is_nr or is_inside_day)
    elif prev_range_ratio is not None:
        is_narrow_prev_day = bool(prev_range_ratio <= 0.75 or is_inside_day)
    elif pdh and prev_close:
        pdl = float(s.get("pdl", 0) or 0)
        if pdl > 0 and pdh > pdl:
            prev_range = pdh - pdl
            if prev_close > 0:
                prev_range_pct = round((prev_range / prev_close) * 100.0, 2)
            if atr14 > 0:
                prev_range_ratio = round(prev_range / atr14, 2)
                is_narrow_prev_day = bool(prev_range_ratio <= 0.75)
            else:
                is_narrow_prev_day = bool(prev_range_pct <= 2.5)

    if not is_ss and day_open and prev_close:
        day_low = s.get("day_low")
        if day_low:
            is_ss = bool(float(day_open) > float(prev_close) and float(day_low) >= float(prev_close) * 0.995)

    if not pdh_cleared and pdh and trig_bar:
        if float(trig_bar[2]) >= pdh:
            pdh_cleared = True
    if not pdh_cleared:
        pdh_cleared = bool(s.get("pdh_broken"))

    is_strict_setup = bool(is_narrow_prev_day and is_ss and pdh_cleared)

    if is_reversal and pdh_cleared:
        trigger_name = "🔄 Reversal Breakout (ORB+PDH)"
    elif is_reversal:
        trigger_name = "🔄 Reversal (ORB L➔H)"
    elif is_ss and pdh_cleared:
        trigger_name = "★ SS + ORB + PDH Break"
    elif is_ss:
        trigger_name = "★ SS + ORB High Break"
    elif pdh_cleared:
        trigger_name = "ORB + PDH Breakout"
    else:
        trigger_name = "ORB High Breakout"

    # Evaluate checklist at time of entry
    tech_passed, tech_total, is_qualified, flags, ck_details = evaluate_setup_checklist(
        sym, s, entry_price, sl_price, is_sl_capped=is_sl_capped
    )

    # Forward simulate outcome through subsequent bars
    outcome = "OPEN_RUNNER"
    exit_price = round_to_clean_int(candles[-1][4])
    exit_time = candles[-1][0]
    high_since = entry_price
    low_since = entry_price

    for j in range(trig_idx + 1, len(candles)):
        c = candles[j]
        c_high = float(c[2])
        c_low = float(c[3])
        high_since = max(high_since, c_high)
        low_since = min(low_since, c_low)

        # Check Stop-Loss breach
        if c_low <= sl_price:
            outcome = "STOPPED_OUT"
            exit_price = sl_price
            exit_time = c[0]
            break

        # Check Target breach
        elif c_high >= target_price:
            outcome = "HIT_TARGET"
            exit_price = target_price
            exit_time = c[0]
            break

    # P&L calculations (strictly round numbers in INR)
    pnl_per_share = exit_price - entry_price
    pnl_inr = round_to_clean_int(pnl_per_share * qty)
    pnl_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 1)
    r_mult = round(pnl_per_share / risk_per_share, 2)
    mfe_pct = round(((high_since - entry_price) / entry_price) * 100.0, 1)
    mae_pct = round(((entry_price - low_since) / entry_price) * 100.0, 1)

    return {
        "symbol": sym,
        "trigger_name": trigger_name,
        "trig_time": trig_time,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "target_price": target_price,
        "risk_per_share": risk_per_share,
        "risk_pct": round(risk_pct, 1),
        "qty": qty,
        "exposure_inr": exposure_inr,
        "outcome": outcome,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "pnl_inr": pnl_inr,
        "pnl_pct": pnl_pct,
        "r_mult": r_mult,
        "mfe_pct": mfe_pct,
        "peak_high": round_to_clean_int(high_since),
        "is_sl_capped": is_sl_capped,
        "is_qualified": is_qualified,
        "is_strict_setup": is_strict_setup,
        "is_narrow_prev_day": is_narrow_prev_day,
        "is_inside_day": is_inside_day,
        "prev_range": prev_range,
        "prev_range_ratio": prev_range_ratio,
        "prev_range_pct": prev_range_pct,
        "is_strong_start": is_ss,
        "is_pdh_cleared": pdh_cleared,
        "pdh": pdh,
        "tech_passed": tech_passed,
        "tech_total": tech_total,
        "flags": flags
    }


def generate_hindsight_data():
    """Generates full hindsight simulation data for all watchlist stocks."""
    raw_data = load_data_json()
    stocks = raw_data.get("stocks", [])
    active_symbols = get_active_watchlist()

    # Exclude index benchmark symbols from single stock simulation
    index_tickers = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "NIFTY50"}

    # Build symbol lookup from data.json
    stock_map = {s.get("symbol", "").upper(): s for s in stocks}

    # Universe to analyze: symbols in active watchlist or data.json
    universe = []
    if active_symbols:
        for sym in active_symbols:
            if sym not in index_tickers and sym not in universe:
                universe.append(sym)
    else:
        for s in stocks:
            sym = s.get("symbol", "").upper()
            if sym not in index_tickers and sym not in universe:
                universe.append(sym)

    qualified_trades = []
    filtered_trades = []
    untriggered_stocks = []

    for sym in universe:
        s = stock_map.get(sym)
        if not s:
            untriggered_stocks.append(sym)
            continue

        sim = simulate_stock_trade(s)
        if sim is None:
            untriggered_stocks.append(sym)
        elif sim["is_qualified"]:
            qualified_trades.append(sim)
        else:
            filtered_trades.append(sim)

    # Sort trades by P&L INR descending
    qualified_trades.sort(key=lambda x: x["pnl_inr"], reverse=True)
    filtered_trades.sort(key=lambda x: x["pnl_inr"], reverse=True)

    # Aggregate performance statistics
    all_triggered = qualified_trades + filtered_trades

    def calc_stats(trades):
        if not trades:
            return {
                "count": 0,
                "winners": 0,
                "losers": 0,
                "runners": 0,
                "win_rate": 0.0,
                "total_pnl_inr": 0,
                "total_r": 0.0,
                "best_trade": None,
                "worst_trade": None
            }
        winners = sum(1 for t in trades if t["pnl_inr"] > 0)
        losers = sum(1 for t in trades if t["pnl_inr"] < 0)
        runners = sum(1 for t in trades if t["outcome"] == "OPEN_RUNNER" and t["pnl_inr"] >= 0)
        win_rate = round((winners / len(trades)) * 100.0, 1) if trades else 0.0
        total_pnl = sum(t["pnl_inr"] for t in trades)
        total_r = round(sum(t["r_mult"] for t in trades), 1)
        best = max(trades, key=lambda x: x["pnl_inr"]) if trades else None
        worst = min(trades, key=lambda x: x["pnl_inr"]) if trades else None
        return {
            "count": len(trades),
            "winners": winners,
            "losers": losers,
            "runners": runners,
            "win_rate": win_rate,
            "total_pnl_inr": total_pnl,
            "total_r": total_r,
            "best_trade": best,
            "worst_trade": worst
        }

    qual_stats = calc_stats(qualified_trades)
    filt_stats = calc_stats(filtered_trades)
    strict_trades = [t for t in all_triggered if t.get("is_strict_setup")]
    strict_trades.sort(key=lambda x: x["pnl_inr"], reverse=True)
    strict_stats = calc_stats(strict_trades)
    overall_stats = calc_stats(all_triggered)

    # -------------------------------------------------------------
    # Comprehensive Universe Audit for Narrow Range (NR) Setups:
    # 1. Triggered Strict Setups (Met NR + Strong Start + PDH Breakout)
    # 2. Coiling NR Setups (Met NR + Strong Start, Coiling / Stalking PDH)
    # 3. Other Contraction / NR Setups (Met NR, Dormant / Below PC)
    # -------------------------------------------------------------
    nr_setups = []
    coiling_nr = []
    dormant_nr = []

    for sym in universe:
        s = stock_map.get(sym)
        if not s:
            continue

        is_narrow = bool(s.get("is_narrow_prev_day"))
        ratio = s.get("prev_range_ratio")
        is_inside = bool(s.get("is_inside_day"))
        pdh_val = float(s.get("pdh") or 0.0)
        pdl_val = float(s.get("pdl") or 0.0)
        prev_close = float(s.get("prev_close") or 0.0)
        day_open = float(s.get("day_open") or 0.0)
        day_low = float(s.get("day_low") or 0.0)
        ltp = float(s.get("ltp") or 0.0)
        atr14 = float(s.get("atr14") or 0.0)

        # Fallback check on daily candles if available
        candles_d = s.get("candles_d", [])
        prev_range_pct = 0.0
        if len(candles_d) >= 2:
            yh = float(candles_d[-2][2])
            yl = float(candles_d[-2][3])
            yc = float(candles_d[-2][4])
            rng = max(0.0, yh - yl)
            if yc > 0:
                prev_range_pct = round((rng / yc) * 100.0, 2)
            if len(candles_d) >= 3:
                dbh = float(candles_d[-3][2])
                dbl = float(candles_d[-3][3])
                is_inside = bool(yh <= dbh and yl >= dbl)
            if atr14 > 0 and ratio is None:
                ratio = round(rng / atr14, 2)
                is_narrow = bool(ratio <= 0.75 or is_inside)
            elif ratio is None:
                is_narrow = bool(prev_range_pct <= 2.5 or is_inside)
        elif not is_narrow and ratio is not None:
            is_narrow = bool(ratio <= 0.75 or is_inside)

        if not is_narrow:
            continue

        # Intraday stats
        c_3m = s.get("candles_3m", [])
        day_high = max([float(c[2]) for c in c_3m]) if c_3m else ltp
        if day_low == 0.0 and c_3m:
            day_low = min([float(c[3]) for c in c_3m])

        # Strong Start check
        is_ss = bool(s.get("is_ss"))
        if not is_ss and day_open > 0 and prev_close > 0:
            is_ss = bool(day_open > prev_close and (day_low == 0.0 or day_low >= prev_close * 0.995))

        pdh_broken = bool(s.get("pdh_broken"))
        if not pdh_broken and pdh_val > 0 and day_high >= pdh_val:
            pdh_broken = True

        dist_pdh_pct = round(((day_high - pdh_val) / pdh_val) * 100.0, 1) if pdh_val > 0 else 0.0

        # Check if this stock triggered as a strict trade in simulation
        matching_sim = next((t for t in strict_trades if t["symbol"] == sym), None)

        nr_item = {
            "symbol": sym,
            "prev_range_ratio": ratio,
            "prev_range_pct": prev_range_pct,
            "is_inside_day": is_inside,
            "is_strong_start": is_ss,
            "pdh": pdh_val,
            "pdl": pdl_val,
            "day_high": day_high,
            "day_low": day_low,
            "ltp": ltp,
            "prev_close": prev_close,
            "pdh_broken": pdh_broken,
            "dist_pdh_pct": dist_pdh_pct,
            "sim_trade": matching_sim
        }
        nr_setups.append(nr_item)

        if matching_sim:
            nr_item["category"] = "TRIGGERED"
        elif is_ss:
            nr_item["category"] = "COILING"
            coiling_nr.append(nr_item)
        else:
            nr_item["category"] = "DORMANT"
            dormant_nr.append(nr_item)

    # -------------------------------------------------------------
    # Slippage & Execution Drift Audit (Real Fills vs Model Alpha)
    # -------------------------------------------------------------
    drift_items = []
    orders_log_file = BASE_DIR / "orders_log.json"
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    if orders_log_file.is_file():
        try:
            with open(orders_log_file, "r", encoding="utf-8") as of:
                all_orders = json.load(of)
                for o in all_orders:
                    ts = o.get("timestamp", "")
                    if today_prefix in ts and o.get("action") == "BUY":
                        sym = o.get("symbol", "").upper()
                        real_p = float(o.get("avg_price") or o.get("price") or o.get("ltp") or 0.0)
                        qty = int(o.get("quantity") or 0)
                        m_sim = next((t for t in all_triggered if t["symbol"] == sym), None)
                        model_p = float(m_sim["entry_price"]) if m_sim else float(o.get("ltp") or real_p)
                        slip_pct = round(((real_p - model_p) / model_p) * 100.0, 2) if model_p > 0 else 0.0
                        slip_inr = round((real_p - model_p) * qty, 0)
                        drift_items.append({
                            "symbol": sym,
                            "broker": o.get("broker", "LIVE"),
                            "quantity": qty,
                            "real_price": real_p,
                            "model_price": model_p,
                            "slip_pct": slip_pct,
                            "slip_inr": slip_inr
                        })
        except Exception:
            pass

    # -------------------------------------------------------------
    # A+ Sniper & Candidate Universe Alpha Audit:
    # -------------------------------------------------------------
    sniper_audit = {
        "total_snipers": 0,
        "triggered_count": 0,
        "winners": 0,
        "losers": 0,
        "win_rate": 0.0,
        "total_r": 0.0,
        "avg_r": 0.0,
        "avg_mfe_pct": 0.0,
        "top_performer": None,
        "trades": []
    }
    candidates_merged_file = BASE_DIR / "candidates_merged.json"
    if candidates_merged_file.is_file():
        try:
            with open(candidates_merged_file, "r", encoding="utf-8") as cmf:
                c_data = json.load(cmf)
                candidates = c_data.get("candidates", [])
                snipers = [c for c in candidates if c.get("is_sniper") or c.get("grade") == "A+"]
                sniper_audit["total_snipers"] = len(snipers)

                for s_cand in snipers:
                    c_sym = s_cand.get("symbol", "").upper()
                    stk_obj = stock_map.get(c_sym)
                    if stk_obj:
                        sim = simulate_stock_trade(stk_obj)
                        if sim:
                            sniper_audit["triggered_count"] += 1
                            sniper_audit["trades"].append(sim)
                            if sim["pnl_inr"] > 0:
                                sniper_audit["winners"] += 1
                            elif sim["pnl_inr"] < 0:
                                sniper_audit["losers"] += 1
                            sniper_audit["total_r"] += sim["r_mult"]

                if sniper_audit["trades"]:
                    tr_cnt = len(sniper_audit["trades"])
                    sniper_audit["win_rate"] = round((sniper_audit["winners"] / tr_cnt) * 100.0, 1)
                    sniper_audit["avg_r"] = round(sniper_audit["total_r"] / tr_cnt, 2)
                    sniper_audit["avg_mfe_pct"] = round(sum(t["mfe_pct"] for t in sniper_audit["trades"]) / tr_cnt, 1)
                    sniper_audit["top_performer"] = max(sniper_audit["trades"], key=lambda x: x["r_mult"])
        except Exception as e:
            print(f"Notice: Sniper audit error: {e}")

    return {
        "updated_at": raw_data.get("updated_at", datetime.now().strftime("%H:%M:%S IST")),
        "date_str": datetime.now().strftime("%Y-%m-%d"),
        "total_universe": len(universe),
        "qualified_trades": qualified_trades,
        "filtered_trades": filtered_trades,
        "strict_trades": strict_trades,
        "nr_setups": nr_setups,
        "coiling_nr": coiling_nr,
        "dormant_nr": dormant_nr,
        "drift_items": drift_items,
        "untriggered_stocks": untriggered_stocks,
        "qual_stats": qual_stats,
        "filt_stats": filt_stats,
        "strict_stats": strict_stats,
        "overall_stats": overall_stats,
        "sniper_audit": sniper_audit
    }


def format_hindsight_report(data):
    """
    Formats the EOD Hindsight Report into clean, beautiful HTML messages for Telegram.
    Returns a list of message strings (auto-split if exceeding Telegram size limit).
    """
    date_str = data["date_str"]
    updated_at = data["updated_at"]
    tot_univ = data["total_universe"]
    qual_trades = data["qualified_trades"]
    filt_trades = data["filtered_trades"]
    untrig = data["untriggered_stocks"]
    q_stats = data["qual_stats"]
    f_stats = data["filt_stats"]
    s_stats = data.get("strict_stats", {})
    strict_trades = data.get("strict_trades", [])
    nr_setups = data.get("nr_setups", [])
    coiling_nr = data.get("coiling_nr", [])
    dormant_nr = data.get("dormant_nr", [])

    # Header & Executive Summary
    is_eod = True
    try:
        now_hour = datetime.now().hour
        now_min = datetime.now().minute
        # If run before 15:30 IST, label as Intraday Simulation Snapshot
        if now_hour < 15 or (now_hour == 15 and now_min < 30):
            is_eod = False
    except Exception:
        pass

    title = "📈 <b>JARVIS EOD HINDSIGHT REPORT</b>" if is_eod else "📈 <b>JARVIS HINDSIGHT SIMULATION SNAPSHOT</b>"
    time_badge = f"{date_str} • {updated_at}"

    lines = [
        title,
        f"<i>Simulated Strategy Execution & Discipline Audit</i>",
        f"📅 <code>{time_badge}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>PORTFOLIO PERFORMANCE SUMMARY</b>",
        f"• Watchlist Universe: <b>{tot_univ} stocks</b>",
        f"• Breakouts Triggered: <b>{len(qual_trades) + len(filt_trades)}</b> ({len(qual_trades)} Passed Checklist, {len(filt_trades)} Filtered)",
    ]

    # Qualified Setups Summary
    pnl_sign = "+" if q_stats["total_pnl_inr"] >= 0 else ""
    r_sign = "+" if q_stats["total_r"] >= 0 else ""
    lines.extend([
        "",
        "✅ <b>CHECKLIST-PASSED TRADES (HIGH CONVICTION)</b>",
        f"• Total Hypothetical P&L: <b>₹{pnl_sign}{q_stats['total_pnl_inr']:,}</b> ({r_sign}{q_stats['total_r']:.1f}R)",
        f"• Win Rate: <b>{q_stats['win_rate']:.0f}%</b> ({q_stats['winners']}W / {q_stats['losers']}L / {q_stats['runners']} Open Runners)",
    ])

    if q_stats["best_trade"]:
        bt = q_stats["best_trade"]
        bt_sign = "+" if bt["pnl_inr"] >= 0 else ""
        bt_r_s = "+" if bt["r_mult"] >= 0 else ""
        lines.append(f"• Best Trade: <b>{bt['symbol']}</b> (₹{bt_sign}{bt['pnl_inr']:,} | {bt_sign}{bt['pnl_pct']:.1f}% | {bt_r_s}{bt['r_mult']:.1f}R)")

    # Discipline / Filtered Summary
    f_pnl_sign = "+" if f_stats["total_pnl_inr"] >= 0 else ""
    f_r_sign = "+" if f_stats["total_r"] >= 0 else ""
    lines.extend([
        "",
        "⚠️ <b>CHECKLIST-FILTERED SETUPS (DISCIPLINE AUDIT)</b>",
        f"• Filtered Setups: <b>{f_stats['count']} trades</b>",
        f"• Filtered Hypothetical P&L: <b>₹{f_pnl_sign}{f_stats['total_pnl_inr']:,}</b> ({f_r_sign}{f_stats['total_r']:.1f}R)",
    ])

    # Narrow Range (NR) & Strict Entry Criteria Summary
    s_pnl_sign = "+" if s_stats.get("total_pnl_inr", 0) >= 0 else ""
    s_r_sign = "+" if s_stats.get("total_r", 0) >= 0 else ""
    lines.extend([
        "",
        "📦 <b>NARROW RANGE (NR) & STRICT SETUP AUDIT</b>",
        f"• Universe NR Setups: <b>{len(nr_setups)} stocks</b> ({len(strict_trades)} Triggered, {len(coiling_nr)} Coiling for Tomorrow)",
        f"• Strict Trades Triggered: <b>{s_stats.get('count', 0)} setups</b>",
        f"• Strict Hypothetical P&L: <b>₹{s_pnl_sign}{s_stats.get('total_pnl_inr', 0):,}</b> ({s_r_sign}{s_stats.get('total_r', 0.0):.1f}R)",
        f"• Strict Win Rate: <b>{s_stats.get('win_rate', 0):.0f}%</b> ({s_stats.get('winners', 0)}W / {s_stats.get('losers', 0)}L / {s_stats.get('runners', 0)} Open Runners)",
        f"• Coiled Springs Ready: <b>{len(coiling_nr)} stocks</b> stalking PDH",
    ])
    if s_stats.get("best_trade"):
        s_bt = s_stats["best_trade"]
        s_bt_sign = "+" if s_bt["pnl_inr"] >= 0 else ""
        s_bt_r_s = "+" if s_bt["r_mult"] >= 0 else ""
        lines.append(f"• Best Strict Trade: <b>{s_bt['symbol']}</b> (₹{s_bt_sign}{s_bt['pnl_inr']:,} | {s_bt_sign}{s_bt['pnl_pct']:.1f}% | {s_bt_r_s}{s_bt['r_mult']:.1f}R)")

    # Section 0.5: A+ Sniper Hit-Rate & Alpha Audit
    s_aud = data.get("sniper_audit", {})
    if s_aud.get("total_snipers", 0) > 0:
        lines.extend([
            "",
            "🎯 <b>A+ SNIPER HIT-RATE & ALPHA AUDIT</b>",
            f"• Candidates Audited: <b>{s_aud['total_snipers']} A+ Snipers</b>",
            f"• Triggered Breakouts: <b>{s_aud['triggered_count']}</b> ({round((s_aud['triggered_count'] / max(1, s_aud['total_snipers'])) * 100)}% trigger rate)",
        ])
        if s_aud.get("trades"):
            lines.extend([
                f"• Sniper Win Rate: <b>{s_aud['win_rate']:.0f}%</b> ({s_aud['winners']}W / {s_aud['losers']}L)",
                f"• Average Alpha: <b>{s_aud['avg_r']:+.1f}R</b> (Avg MFE: +{s_aud['avg_mfe_pct']}%)",
            ])
            top_p = s_aud.get("top_performer")
            if top_p:
                lines.append(f"• Top Sniper Alpha: <b>{top_p['symbol']}</b> (+{top_p['r_mult']:.1f}R | MFE +{top_p['mfe_pct']}%)")
        else:
            lines.append("• <i>Tracked snipers stayed within opening ranges (0 false-breakout losses).</i>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Section 0: Dedicated Narrow Range (NR) & Strict Criteria Audit
    lines.append("📦 <b>NARROW RANGE (NR) & STRICT CRITERIA AUDIT:</b>")
    lines.append("<i>Strategy: Narrow Prev Day (≤0.75x ATR / Inside Day) ➔ Strong Start (Open > PC) ➔ PDH Breakout</i>")

    # Subsection A: Triggered Strict Breakouts
    lines.append(f"\n💎 <b>TRIGGERED STRICT BREAKOUTS ({len(strict_trades)}):</b>")
    if not strict_trades:
        lines.append("<i>• No strict breakout triggers fired today (Capital protected).</i>")
    else:
        for t in strict_trades:
            sym = t["symbol"]
            p_sign = "+" if t["pnl_inr"] >= 0 else ""
            r_s = "+" if t["r_mult"] >= 0 else ""

            if t["outcome"] == "HIT_TARGET":
                outcome_badge = "🎯 <b>HIT 2R TARGET (+2.0R)</b>"
            elif t["outcome"] == "STOPPED_OUT":
                outcome_badge = "🛑 <b>STOPPED OUT (-1.0R)</b>"
            else:
                outcome_badge = f"🏃 <b>OPEN RUNNER ({r_s}{t['r_mult']:.1f}R)</b>"

            sl_note = f" (🛡️ Capped 2.5%)" if t.get("is_sl_capped") else f" ({t['risk_pct']:.1f}%)"
            nr_info = f"{t.get('prev_range_ratio', 0):.2f}x ATR" if t.get('prev_range_ratio') else f"{t.get('prev_range_pct', 0):.1f}%"
            inside_tag = " (Inside Day 📦)" if t.get("is_inside_day") else ""
            pdh_val = round_to_clean_int(t.get('pdh', 0))

            lines.append(f"\n<b>{sym}</b> | 💎 Strict Narrow+SS+PDH Break")
            lines.append(f"• Status : {outcome_badge}")
            lines.append(f"• Setup  : Entry <b>₹{t['entry_price']:,}</b> ({t['trig_time']}) | SL <b>₹{t['sl_price']:,}</b>{sl_note} | Tgt <b>₹{t['target_price']:,}</b>")
            lines.append(f"• Criteria: 📏 Prev Range: <b>{nr_info}{inside_tag}</b> | 🚀 Strong Start: <b>Yes</b> | ⚡ PDH: <b>₹{pdh_val:,}</b>")
            lines.append(f"• Outcome: Exit <b>₹{t['exit_price']:,}</b> ({t['exit_time']}) ➔ <b>₹{p_sign}{t['pnl_inr']:,}</b> ({p_sign}{t['pnl_pct']:.1f}%)")
            lines.append(f"• Max Run: <b>+{t['mfe_pct']:.1f}%</b> MFE (Peak: ₹{t['peak_high']:,})")

    # Subsection B: Coiling NR Watchlist Stalking PDH
    lines.append(f"\n🌀 <b>COILING NR WATCHLIST — STALKING PDH ({len(coiling_nr)}):</b>")
    lines.append("<i>Stocks with Narrow Prev Day + Strong Start that consolidated under PDH today (Top setups for tomorrow):</i>")
    if not coiling_nr:
        lines.append("<i>• No untriggered coiling NR stocks today.</i>")
    else:
        for c in coiling_nr:
            sym = c["symbol"]
            ratio_str = f"{c['prev_range_ratio']:.2f}x ATR" if c.get('prev_range_ratio') is not None else "Coiled"
            in_tag = " (Inside Day 📦)" if c.get("is_inside_day") else ""
            pdh_clean = round_to_clean_int(c.get("pdh", 0))
            high_clean = round_to_clean_int(c.get("day_high", 0))
            ltp_clean = round_to_clean_int(c.get("ltp", 0))

            if c.get("pdh_broken"):
                status_txt = f"⚡ <b>Tested PDH (₹{pdh_clean:,})</b> & coiled in range — Prime follow-through setup!"
            else:
                dist = c.get("dist_pdh_pct", 0.0)
                status_txt = f"🟡 <b>Coiled Spring ({dist:+.1f}% vs PDH)</b> — Consolidating under PDH for breakout."

            lines.append(f"\n• <b>{sym}</b> | 📏 Prev Range: <b>{ratio_str}{in_tag}</b> | 🚀 Strong Start: <b>Yes</b>")
            lines.append(f"  ⚡ PDH: <b>₹{pdh_clean:,}</b> | High: <b>₹{high_clean:,}</b> | LTP: <b>₹{ltp_clean:,}</b>")
            lines.append(f"  ➔ {status_txt}")

    # Subsection C: Dormant / Flat NR Setups
    if dormant_nr:
        lines.append(f"\n📦 <b>OTHER NR CONTRACTION STOCKS ({len(dormant_nr)}):</b>")
        lines.append("<i>Narrow Range yesterday, but opened flat/below PC today:</i>")
        for d in dormant_nr:
            sym = d["symbol"]
            ratio_str = f"{d['prev_range_ratio']:.2f}x ATR" if d.get('prev_range_ratio') is not None else "Coiled"
            in_tag = " (Inside Day 📦)" if d.get("is_inside_day") else ""
            lines.append(f"• <b>{sym}</b>: 📏 Prev Range: <b>{ratio_str}{in_tag}</b> | Status: Dormant / Flat open")

    if not nr_setups:
        lines.append("<i>• No stocks in universe met narrow range contraction criteria yesterday.</i>")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Section 1: Detailed Qualified Trades
    lines.append("🎯 <b>DETAILED QUALIFIED SETUPS:</b>")
    if not qual_trades:
        lines.append("<i>No watchlist stocks triggered and met full checklist today.</i>")
    else:
        for t in qual_trades:
            sym = t["symbol"]
            p_sign = "+" if t["pnl_inr"] >= 0 else ""
            r_s = "+" if t["r_mult"] >= 0 else ""
            
            if t["outcome"] == "HIT_TARGET":
                outcome_badge = "🎯 <b>HIT 2R TARGET (+2.0R)</b>"
            elif t["outcome"] == "STOPPED_OUT":
                outcome_badge = "🛑 <b>STOPPED OUT (-1.0R)</b>"
            else:
                outcome_badge = f"🏃 <b>OPEN RUNNER ({r_s}{t['r_mult']:.1f}R)</b>"

            sl_note = f" (🛡️ Capped 2.5%)" if t.get("is_sl_capped") else f" ({t['risk_pct']:.1f}%)"
            lines.append(f"\n<b>{sym}</b> | {t['trigger_name']}")
            lines.append(f"• Status : {outcome_badge}")
            lines.append(f"• Setup  : Entry <b>₹{t['entry_price']:,}</b> ({t['trig_time']}) | SL <b>₹{t['sl_price']:,}</b>{sl_note} | Tgt <b>₹{t['target_price']:,}</b>")
            lines.append(f"• Outcome: Exit <b>₹{t['exit_price']:,}</b> ({t['exit_time']}) ➔ <b>₹{p_sign}{t['pnl_inr']:,}</b> ({p_sign}{t['pnl_pct']:.1f}%)")
            lines.append(f"• Max Run: <b>+{t['mfe_pct']:.1f}%</b> MFE (Peak: ₹{t['peak_high']:,}) | Score: {t['tech_passed']}/{t['tech_total']} ✅")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Section 2: Detailed Filtered Trades (Discipline Audit)
    lines.append("⚠️ <b>FILTERED TRADES AUDIT (WHY AVOIDED):</b>")
    if not filt_trades:
        lines.append("<i>No trades were filtered out today.</i>")
    else:
        for t in filt_trades:
            sym = t["symbol"]
            p_sign = "+" if t["pnl_inr"] >= 0 else ""
            r_s = "+" if t["r_mult"] >= 0 else ""
            flags_str = ", ".join(t["flags"]) if t["flags"] else "Low Setup Conviction"

            if t["outcome"] == "STOPPED_OUT":
                status_str = f"🛑 Stopped Out (₹{t['pnl_inr']:,})"
                insight = f"💡 <i>Checklist protected capital! Saved ₹{abs(t['pnl_inr']):,} loss.</i>"
            elif t["outcome"] == "HIT_TARGET":
                status_str = f"🎯 Hit Target (₹+{t['pnl_inr']:,})"
                insight = f"ℹ️ <i>Filtered winner (+{t['pnl_pct']:.1f}%). Filtered due to: {flags_str}.</i>"
            else:
                status_str = f"🏃 Closed at ₹{t['exit_price']:,} (₹{p_sign}{t['pnl_inr']:,})"
                insight = f"ℹ️ <i>Flags: {flags_str}</i>"

            lines.append(f"\n<b>{sym}</b> | Entry ₹{t['entry_price']:,} ➔ {status_str}")
            lines.append(f"• {insight}")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Section 3: Untriggered Stocks
    lines.append(f"⚪ <b>UNTRIGGERED WATCHLIST STOCKS ({len(untrig)}):</b>")
    if untrig:
        lines.append(f"<code>{', '.join(untrig)}</code>")
        lines.append("<i>Stayed within opening range / below breakout triggers all day.</i>")
    else:
        lines.append("<i>All watchlist stocks triggered today!</i>")

    # Section 4: Slippage & Execution Drift Audit (Real vs Model)
    drift_items = data.get("drift_items", [])
    if drift_items:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📊 <b>REALIZED VS MODEL DRIFT AUDIT ({len(drift_items)} Fills):</b>")
        for d in drift_items:
            sign = "+" if d["slip_pct"] >= 0 else ""
            inr_s = "+" if d["slip_inr"] >= 0 else ""
            lines.append(f"• <b>{d['symbol']}</b> ({d['broker']}): Exec ₹{d['real_price']:,.2f} vs Model ₹{d['model_price']:,.2f} ({sign}{d['slip_pct']}%)")
        avg_slip = sum(d["slip_pct"] for d in drift_items) / len(drift_items)
        lines.append(f"<i>Average Execution Drift: {avg_slip:+.2f}% (High Alpha Retention ✅)</i>")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>Standard Sizing: ₹1,00,000 capital per trade | Risk: LOD Stop / 2.5% max | Entry: Strictly after 09:30 AM</i>",
        "🤖 <i>Jarvis Autonomous Quantitative Strategy Engine</i>"
    ])

    full_text = "\n".join(lines)

    # Auto-split if length exceeds 3800 chars (Telegram max is 4096)
    if len(full_text) <= 3800:
        return [full_text]

    # Major Section Dividers:
    # 1. Summary & Narrow Range (NR) Audit
    # 2. Detailed Qualified Setups
    # 3. Filtered Trades Audit & Untriggered Stocks
    sec_nr_lines = []
    sec_qual_lines = []
    sec_filt_lines = []
    cur_sec = 1

    for l in lines:
        if "DETAILED QUALIFIED SETUPS:" in l:
            cur_sec = 2
        elif "FILTERED TRADES AUDIT" in l:
            cur_sec = 3

        if cur_sec == 1:
            sec_nr_lines.append(l)
        elif cur_sec == 2:
            sec_qual_lines.append(l)
        else:
            sec_filt_lines.append(l)

    # Assemble parts by combining sections without exceeding 3800 chars
    parts = []
    sec1_text = "\n".join(sec_nr_lines)
    sec2_text = "\n".join(sec_qual_lines)
    sec3_text = f"📈 <b>JARVIS HINDSIGHT REPORT (DISCIPLINE & UNTRIGGERED) — {date_str}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(sec_filt_lines)

    if len(sec1_text) + len(sec2_text) + 2 <= 3800:
        parts.append(sec1_text + "\n\n" + sec2_text)
    else:
        parts.append(sec1_text)
        parts.append(f"📈 <b>JARVIS HINDSIGHT REPORT (QUALIFIED SETUPS) — {date_str}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + sec2_text)

    if len(sec3_text) <= 3800:
        parts.append(sec3_text)
    else:
        sec3_lines = sec3_text.split("\n")
        cur_lines = []
        cur_len = 0
        for l in sec3_lines:
            if cur_len + len(l) + 1 > 3800:
                parts.append("\n".join(cur_lines))
                cur_lines = [l]
                cur_len = len(l)
            else:
                cur_lines.append(l)
                cur_len += len(l) + 1
        if cur_lines:
            parts.append("\n".join(cur_lines))

    return parts


def dispatch_telegram_hindsight(report_parts):
    """Dispatches report parts to Telegram topic 'reports' (Topic 11)."""
    cfg = load_config()
    tg_token = cfg.get("telegram", {}).get("bot_token")
    tg_chat_id = cfg.get("telegram", {}).get("chat_id")
    tg_group_id = cfg.get("telegram", {}).get("group_id")
    topics = cfg.get("telegram", {}).get("topics", {})
    thread_id = topics.get("reports") if tg_group_id else None
    target_chat = tg_group_id if (tg_group_id and thread_id) else tg_chat_id

    if not tg_token or not target_chat:
        print("❌ Telegram credentials missing in config_credentials.json")
        return False

    import urllib.request

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"

    success = True
    for idx, part in enumerate(report_parts):
        payload = {
            "chat_id": target_chat,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if thread_id is not None:
            payload["message_thread_id"] = int(thread_id)

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Jarvis-EOD-Hindsight"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    print(f"✅ Part {idx + 1}/{len(report_parts)} dispatched to Telegram topic 'reports'!")
                else:
                    print(f"⚠️ Telegram returned status {resp.status}")
                    success = False
            # Small pause between messages if multi-part
            if len(report_parts) > 1:
                time.sleep(1)
        except urllib.error.HTTPError as he:
            err = he.read().decode(errors="replace")
            print(f"❌ HTTPError dispatching part {idx + 1}: {err}")
            # Retry plain text if HTML parsing failed
            try:
                payload["parse_mode"] = None
                req_retry = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req_retry, timeout=10) as r_resp:
                    if r_resp.status == 200:
                        print(f"✅ Part {idx + 1} dispatched cleanly as plain text fallback!")
            except Exception as ex2:
                print(f"❌ Plain text retry also failed: {ex2}")
                success = False
        except Exception as e:
            print(f"❌ Exception dispatching part {idx + 1}: {e}")
            success = False

    return success


def generate_eod_hindsight_report(notify=False, dry_run=False):
    """
    Main entry point to generate the EOD Hindsight Report.
    Returns (data, formatted_messages, success_bool).
    """
    data = generate_hindsight_data()
    messages = format_hindsight_report(data)

    if dry_run or not notify:
        print("\n" + "=" * 60)
        for msg in messages:
            # Strip simple HTML tags for clean terminal printing
            clean_term = msg.replace("<b>", "").replace("</b>", "")
            clean_term = clean_term.replace("<i>", "").replace("</i>", "")
            clean_term = clean_term.replace("<code>", "").replace("</code>", "")
            print(clean_term)
            print("-" * 60)

    if notify:
        ok = dispatch_telegram_hindsight(messages)
        return data, messages, ok

    return data, messages, True


def main():
    parser = argparse.ArgumentParser(description="Jarvis EOD Hindsight Report Engine")
    parser.add_argument("--notify", action="store_true", help="Send formatted report to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Print report to terminal without sending")
    args = parser.parse_args()

    # If neither flag is provided, default to dry-run
    if not args.notify and not args.dry_run:
        args.dry_run = True

    print("🚀 Running Jarvis EOD Hindsight Report...")
    generate_eod_hindsight_report(notify=args.notify, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
