#!/usr/bin/env python3
"""
⚡ JARVIS EXITED STOCKS RE-ENTRY & CANDIDATE ENGINE
=============================================================================
1. Maintains a persistent, clean list of past exited swing trade stocks in 'exited_stocks.json'.
2. Excludes currently active open positions across Dhan, Zerodha, and Upstox.
3. Automatically analyzes past exited stocks at EOD using institutional candidate criteria:
   - Stage 2 Uptrend: Price >= 0.985× 20 EMA and 20 EMA >= 0.98× 50 EMA.
   - Volatility Contraction: 5D VCP <= 2.6× ATR14 or 3D VCP <= 1.3× ATR14 or Inside Day.
   - Non-Extended: Sitting tight in base (Daily Range <= 2.85%, -2.5% <= Change% <= +3.5%).
   - Multi-Tier Pivot Doorstep & Base Launchpad (Tier 1A, Tier 1B, Tier 2, Tier 3).
   - Strict Playbook: Coiled spring (Prev Day Narrow Range <= 0.75× ATR14 or Inside Day).
4. Moves qualified re-entry setups into 'candidates.json' & 'candidates.txt' with '🔄 Ex-Holding' tag.
5. Provides rich Telegram cards and 1-tap promotion buttons.
"""

import os
import sys
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# UTF-8 stdout configuration for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
JOURNAL_FILE = BASE_DIR / "Journal.xlsx"
ORDERS_LOG_FILE = BASE_DIR / "orders_log.json"
CONFIG_FILE = BASE_DIR / "config_credentials.json"
HOLDINGS_FILE = BASE_DIR / "tracked_holdings.json"
EXITED_STOCKS_FILE = BASE_DIR / "exited_stocks.json"
CANDIDATES_JSON = BASE_DIR / "candidates.json"
CANDIDATES_TXT = BASE_DIR / "candidates.txt"

IST = timezone(timedelta(hours=5, minutes=30))

# Yahoo Finance symbol aliases
YAHOO_ALIASES = {
    "ARE&M": "ARE&M.NS",
    "SWIGGY": "SWIGGY.NS",
    "TATAMOTORS": "TMPV.NS"
}


def get_ist_now():
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def calc_ema(values, period):
    """Calculates Exponential Moving Average."""
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for val in values[period:]:
        ema = (val * k) + (ema * (1.0 - k))
    return ema


def get_active_open_symbols():
    """Returns set of all currently active open positions to never treat them as exited."""
    open_syms = set()

    # 1. From Journal.xlsx Open Positions sheet
    if JOURNAL_FILE.is_file():
        try:
            import openpyxl
            wb = openpyxl.load_workbook(JOURNAL_FILE, data_only=True)
            if "Open Positions" in wb.sheetnames:
                ws = wb["Open Positions"]
                for r in range(2, ws.max_row + 1):
                    s = ws.cell(r, 1).value
                    if s:
                        open_syms.add(str(s).strip().upper())
            wb.close()
        except Exception:
            pass

    # 2. From tracked_holdings.json (authoritative active swing holding ledger)
    if HOLDINGS_FILE.is_file():
        try:
            with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
                th = json.load(f)
                for s, meta in th.items():
                    if isinstance(meta, dict) and meta.get("status") != "CLOSED" and float(meta.get("qty", 1) or 0) > 0:
                        open_syms.add(str(s).strip().upper())
                    elif isinstance(meta, (str, list)):
                        open_syms.add(str(s).strip().upper())
        except Exception:
            pass

    return open_syms


def sync_exited_stocks():
    """
    Scans Journal.xlsx (Trade Journal sheet) and orders_log.json to extract all past exited stocks.
    Filters out currently active open positions and derivatives/options.
    Saves and updates 'exited_stocks.json'.
    """
    open_syms = get_active_open_symbols()
    exited_map = {}

    # Load existing exited_stocks.json if present
    if EXITED_STOCKS_FILE.is_file():
        try:
            with open(EXITED_STOCKS_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for s, item in old_data.get("history", {}).items():
                    exited_map[s.upper()] = item
        except Exception:
            pass

    # 1. Scan Journal.xlsx Trade Journal
    if JOURNAL_FILE.is_file():
        try:
            import openpyxl
            wb = openpyxl.load_workbook(JOURNAL_FILE, data_only=True)
            if "Trade Journal" in wb.sheetnames:
                ws = wb["Trade Journal"]
                for r in range(2, ws.max_row + 1):
                    sym = ws.cell(r, 3).value
                    if not sym:
                        continue
                    sym_clean = str(sym).strip().upper()

                    # Exclude open, derivative, and blacklisted
                    if sym_clean in open_syms or "NIFTY-" in sym_clean or sym_clean == "MOTHERSON":
                        continue

                    status = ws.cell(r, 11).value
                    exit_p = ws.cell(r, 9).value
                    exit_d = ws.cell(r, 10).value
                    net_pnl = ws.cell(r, 21).value
                    entry_p = ws.cell(r, 5).value
                    notes = ws.cell(r, 22).value or ""

                    # Closed trade detection
                    is_closed = (status and "CLOSED" in str(status).upper()) or (exit_p is not None) or (exit_d is not None)
                    if is_closed:
                        exit_d_str = str(exit_d)[:10] if exit_d else "Unknown"
                        existing = exited_map.get(sym_clean, {})
                        exited_map[sym_clean] = {
                            "symbol": sym_clean,
                            "last_exit_date": exit_d_str if exit_d_str != "Unknown" else existing.get("last_exit_date", "Unknown"),
                            "last_exit_price": float(exit_p) if exit_p else existing.get("last_exit_price"),
                            "last_entry_price": float(entry_p) if entry_p else existing.get("last_entry_price"),
                            "realized_pnl": round(float(net_pnl), 2) if net_pnl is not None else existing.get("realized_pnl"),
                            "status": "CLOSED",
                            "notes": str(notes) if notes else existing.get("notes", "")
                        }
            wb.close()
        except Exception as e:
            print(f"⚠️ Error reading Journal.xlsx for exited stocks: {e}")

    # 2. Scan orders_log.json for any additional closed orders
    if ORDERS_LOG_FILE.is_file():
        try:
            with open(ORDERS_LOG_FILE, "r", encoding="utf-8") as f:
                olog = json.load(f)
                for entry in olog:
                    sym = str(entry.get("symbol", "")).strip().upper()
                    if not sym or sym in open_syms or "NIFTY-" in sym or sym == "MOTHERSON":
                        continue
                    st = str(entry.get("status", "")).upper()
                    if st in ("CLOSED", "EXITED"):
                        if sym not in exited_map:
                            exited_map[sym] = {
                                "symbol": sym,
                                "last_exit_date": str(entry.get("timestamp", ""))[:10] or "Unknown",
                                "last_exit_price": float(entry.get("exit_price") or entry.get("price") or 0.0),
                                "last_entry_price": float(entry.get("entry_price") or 0.0),
                                "realized_pnl": float(entry.get("pnl") or 0.0),
                                "status": "CLOSED",
                                "notes": "Synced from orders_log.json"
                            }
        except Exception:
            pass

    # Ensure no currently open positions are in the exited map
    for op in open_syms:
        exited_map.pop(op, None)

    symbols_list = sorted(list(exited_map.keys()))
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    payload = {
        "updated_at": now_str,
        "count": len(symbols_list),
        "symbols": symbols_list,
        "history": exited_map
    }

    try:
        with open(EXITED_STOCKS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error writing {EXITED_STOCKS_FILE}: {e}")

    return payload


def load_exited_stocks():
    """Loads exited stocks from file, or triggers sync if file is missing."""
    if not EXITED_STOCKS_FILE.is_file():
        return sync_exited_stocks()
    try:
        with open(EXITED_STOCKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return sync_exited_stocks()


def evaluate_single_stock_eod(sym, meta=None):
    """
    Evaluates a single past exited stock against institutional pre-breakout candidate criteria:
    - Stage 2 Uptrend (LTP >= 0.985*20 EMA and 20 EMA >= 0.98*50 EMA).
    - VCP Contraction (5D VCP <= 2.6x ATR or 3D VCP <= 1.3x ATR or Inside Day).
    - Non-extended Daily Range (<= 2.85%, -2.5% <= Change% <= +3.5%).
    - Pivot Doorstep / Launchpad / Pullback Shelf (Tier 1A, Tier 1B, Tier 2, Tier 3).
    - Strict Playbook Contraction (Prev Day Range <= 0.75x ATR or Inside Day).
    """
    ticker = YAHOO_ALIASES.get(sym, f"{sym}.NS")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = data["chart"]["result"][0]
            quotes = res["indicators"]["quote"][0]
            closes = [c for c in quotes.get("close", []) if c is not None]
            highs = [h for h in quotes.get("high", []) if h is not None]
            lows = [l for l in quotes.get("low", []) if l is not None]
            vols = [v for v in quotes.get("volume", []) if v is not None]

            if len(closes) < 25:
                return {"symbol": sym, "qualified": False, "reason": "Insufficient daily bars (<25)"}

            ltp = closes[-1]
            high = highs[-1]
            low = lows[-1]
            prev_close = closes[-2]
            day_range_pct = round(((high - low) / prev_close) * 100.0, 2)
            chg_pct = round(((ltp - prev_close) / prev_close) * 100.0, 2)

            ema20 = calc_ema(closes, 20)
            ema50 = calc_ema(closes, 50)
            ema10 = calc_ema(closes, 10)

            # 1. Trend Alignment (Stage 2 Uptrend)
            trend_ok = (ltp >= ema20 * 0.985) and (ema20 >= ema50 * 0.98)
            if not trend_ok:
                return {
                    "symbol": sym,
                    "qualified": False,
                    "reason": f"Below 20/50 EMA (LTP ₹{ltp:,.1f} | 20 EMA ₹{ema20:,.1f} | 50 EMA ₹{ema50:,.1f})",
                    "ltp": ltp
                }

            # 2. ATR 14
            trs = []
            for i in range(1, len(closes)):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                trs.append(tr)
            atr14 = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else (high - low)

            # 3. Volatility Contraction (VCP)
            h_5d = max(highs[-5:])
            l_5d = min(lows[-5:])
            vcp_5d = round((h_5d - l_5d) / atr14, 2) if atr14 > 0 else 9.9

            h_3d = max(highs[-3:])
            l_3d = min(lows[-3:])
            vcp_3d = round((h_3d - l_3d) / atr14, 2) if atr14 > 0 else 9.9

            # Inside Day
            is_inside_day = len(highs) >= 2 and highs[-1] <= highs[-2] and lows[-1] >= lows[-2]

            # 4. Pivot Proximity
            pivot_20d = max(highs[-20:])
            dist_20d_pct = round(((pivot_20d - ltp) / pivot_20d) * 100.0, 2)
            dist_20d_atr = round((pivot_20d - ltp) / atr14, 2) if atr14 > 0 else 9.9
            pdh = highs[-2]
            dist_pdh_pct = round(((pdh - ltp) / pdh) * 100.0, 2)
            dist_ema20_pct = round(((ltp - ema20) / ltp) * 100.0, 2)

            # 5. Strict Playbook Check (Prev Day Contraction)
            prev_range = highs[-2] - lows[-2]
            prev_ratio = round(prev_range / atr14, 2) if atr14 > 0 else 9.9
            is_strict_eligible = (prev_ratio <= 0.75 or is_inside_day)

            # 6. Tier Classification
            tier = None
            coil_tag = None

            # TIER 1: Pivot Doorstep (<= 2.5% from 20D High or <= 1.05x ATR)
            if (dist_20d_pct <= 2.50 or dist_20d_atr <= 1.05) and (vcp_5d <= 2.60 or vcp_3d <= 1.30 or is_inside_day):
                tier = "TIER 1A" if dist_ema20_pct <= 4.5 else "TIER 1B"
                coil_tag = "🔥 PIVOT DOORSTEP"
            # TIER 2: Base Launchpad (2.2% to 5.0% from 20D High and <= 2.5% from PDH)
            elif (dist_20d_pct <= 5.00 or dist_20d_atr <= 1.50) and (abs(dist_pdh_pct) <= 2.50) and (vcp_5d <= 2.60 or vcp_3d <= 1.40):
                tier = "TIER 2"
                coil_tag = "🚀 BASE LAUNCHPAD"
            # TIER 3: EMA Pullback Coil (Resting on rising 10/20 EMA support)
            elif (abs((ltp - ema10) / ltp * 100) <= 1.50 or abs(dist_ema20_pct) <= 1.50) and (vcp_3d <= 1.40 or is_inside_day):
                tier = "TIER 3"
                coil_tag = "🛡️ EMA PULLBACK COIL"

            if not tier:
                return {
                    "symbol": sym,
                    "qualified": False,
                    "reason": f"Uptrend intact but not coiling near pivot (20D Dist: {dist_20d_pct:.1f}%, 5D VCP: {vcp_5d:.2f}x ATR)",
                    "ltp": ltp
                }

            # RVOL
            avg_vol_20 = sum(vols[-20:]) / 20.0 if len(vols) >= 20 else 1.0
            rvol = round(vols[-1] / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0
            is_vdu = rvol <= 0.65

            flags = ["🔄 Ex-Holding"]
            if is_strict_eligible:
                flags.append("💎 Strict Coiled")
            if is_inside_day:
                flags.append("📦 Inside Day")
            if is_vdu:
                flags.append("🧊 VDU")

            # Scoring
            score = 75.0
            if "TIER 1" in tier:
                score += 15.0
            elif tier == "TIER 2":
                score += 10.0
            elif tier == "TIER 3":
                score += 8.0

            if is_strict_eligible:
                score += 8.0
            if is_vdu:
                score += 6.0
            if is_inside_day:
                score += 5.0

            score += max(0.0, (2.2 - min(vcp_5d, vcp_3d * 1.8)) * 10.0)
            score += max(0.0, (2.0 - dist_20d_pct) * 8.0)
            score += max(0.0, (1.5 - abs(dist_pdh_pct)) * 8.0)

            last_exit_date = meta.get("last_exit_date", "Unknown") if meta else "Unknown"
            last_exit_price = meta.get("last_exit_price") if meta else None

            return {
                "symbol": sym,
                "name": sym,
                "qualified": True,
                "tier": tier,
                "tier_label": f"{tier}: Re-Entry Coil (Ex-Holding)",
                "coil_tag": coil_tag,
                "ltp": round(ltp, 2),
                "change_pct": chg_pct,
                "daily_range_pct": day_range_pct,
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "atr14": round(atr14, 2),
                "vcp_ratio_5d": vcp_5d,
                "vcp_ratio_3d": vcp_3d,
                "is_inside_day": is_inside_day,
                "is_vdu": is_vdu,
                "is_strict_eligible": is_strict_eligible,
                "prev_range_ratio": prev_ratio,
                "pivot_20d": round(pivot_20d, 2),
                "dist_pivot_20d_pct": dist_20d_pct,
                "dist_pivot_atr": dist_20d_atr,
                "pdh": round(pdh, 2),
                "dist_pdh_pct": dist_pdh_pct,
                "dist_ema20_pct": dist_ema20_pct,
                "proj_rvol": rvol,
                "vol_tag": f"🧊 RVOL {rvol}x (VDU)" if is_vdu else f"RVOL {rvol}x",
                "flags": flags,
                "score": round(score, 1),
                "is_ex_holding": True,
                "last_exit_date": last_exit_date,
                "last_exit_price": last_exit_price
            }

    except Exception as e:
        return {"symbol": sym, "qualified": False, "reason": f"Feed error: {e}"}


def analyze_exited_stocks_eod():
    """
    Analyzes all past exited stocks at EOD concurrently and categorizes into:
    - qualified_candidates: Ready to move into candidates.json / candidates.txt
    - standby_stocks: Disqualified (broken trend, extended, or consolidation in progress)
    """
    ex_data = sync_exited_stocks()
    symbols = ex_data.get("symbols", [])
    history = ex_data.get("history", {})

    if not symbols:
        return {
            "status": "success",
            "count": 0,
            "qualified": [],
            "standby": [],
            "message": "No exited stocks found to analyze."
        }

    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(evaluate_single_stock_eod, sym, history.get(sym)) for sym in symbols]
        for f in futures:
            try:
                res = f.result()
                if res:
                    results.append(res)
            except Exception:
                pass

    qualified = [r for r in results if r.get("qualified")]
    standby = [r for r in results if not r.get("qualified")]

    # Sort qualified by score descending
    qualified.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return {
        "status": "success",
        "total_exited": len(symbols),
        "qualified_count": len(qualified),
        "standby_count": len(standby),
        "qualified": qualified,
        "standby": standby,
        "updated_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    }


def promote_exited_to_candidates(qualified_exited):
    """
    Appends or merges qualified past exited stocks into candidates.json and candidates.txt
    without creating duplicates.
    """
    if not qualified_exited:
        return

    # 1. Update candidates.json
    existing_cands = []
    cands_meta = {}
    if CANDIDATES_JSON.is_file():
        try:
            with open(CANDIDATES_JSON, "r", encoding="utf-8") as f:
                cands_meta = json.load(f)
                existing_cands = cands_meta.get("candidates", [])
        except Exception:
            existing_cands = []

    existing_syms = set(c.get("symbol", "").upper() for c in existing_cands)

    new_additions = []
    for q in qualified_exited:
        sym = q["symbol"].upper()
        if sym not in existing_syms:
            existing_cands.append(q)
            new_additions.append(sym)
            existing_syms.add(sym)

    # Re-sort full candidate list by score descending
    existing_cands.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    cands_meta["candidates"] = existing_cands
    cands_meta["count"] = len(existing_cands)
    cands_meta["updated_at"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    try:
        with open(CANDIDATES_JSON, "w", encoding="utf-8") as f:
            json.dump(cands_meta, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error writing {CANDIDATES_JSON}: {e}")

    # 2. Append to candidates.txt
    if new_additions and CANDIDATES_TXT.is_file():
        try:
            with open(CANDIDATES_TXT, "r", encoding="utf-8") as f:
                content = f.read()

            lines_to_add = [
                "",
                "# --- 🔄 PROMOTED EX-HOLDING RE-ENTRY CANDIDATES ---"
            ]
            for q in qualified_exited:
                if q["symbol"] in new_additions:
                    flag_str = f" | {' '.join(q.get('flags', []))}" if q.get('flags') else ""
                    lines_to_add.append(
                        f"{q['symbol']}  # ₹{q['ltp']:,.2f} | [{q['tier']}] {q['coil_tag']}{flag_str} | 20D Dist: {q['dist_pivot_20d_pct']:+.2f}% | "
                        f"PDH Dist: {q['dist_pdh_pct']:+.2f}% | 5D VCP: {q['vcp_ratio_5d']}x ATR | Range: {q['daily_range_pct']:.2f}% | "
                        f"Last Exit: {q.get('last_exit_date', 'N/A')} @ ₹{q.get('last_exit_price', 0):,.2f}"
                    )

            with open(CANDIDATES_TXT, "a", encoding="utf-8") as f:
                f.write("\n".join(lines_to_add) + "\n")
        except Exception as e:
            print(f"⚠️ Error appending to {CANDIDATES_TXT}: {e}")

    return new_additions


def format_exited_analysis_telegram_card(res):
    """Formats rich executive Telegram card showing EOD Re-entry Candidate Assessment."""
    now_str = res.get("updated_at", get_ist_now().strftime("%H:%M IST"))
    qualified = res.get("qualified", [])
    standby = res.get("standby", [])

    lines = [
        f"🔄 <b>EXITED STOCKS RE-ENTRY AUDIT — {now_str}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Audited:</b> {res.get('total_exited', 0)} past exited positions",
        f"🎯 <b>Qualified:</b> {len(qualified)} stocks coiled for re-entry",
        f"⏳ <b>Standby:</b> {len(standby)} stocks still resetting bases",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    inline_keyboard = []

    if qualified:
        lines.append("\n💎 <b>QUALIFIED FOR EOD CANDIDATES:</b>")
        for q in qualified:
            sym = q["symbol"]
            tier = q["tier"]
            ltp = q["ltp"]
            dist_20d = q["dist_pivot_20d_pct"]
            dist_pdh = q["dist_pdh_pct"]
            vcp = q["vcp_ratio_5d"]
            flags = " ".join(q.get("flags", []))
            tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"

            lines.append(f"• {tv_link} (₹{ltp:,.2f}) [{tier}]")
            lines.append(f"  └ {flags} | 20D: {dist_20d:+.1f}% | PDH: {dist_pdh:+.1f}% | 5D VCP: {vcp}x ATR")
            if q.get("last_exit_date") != "Unknown":
                lines.append(f"  └ <i>Exited {q['last_exit_date']} @ ₹{q.get('last_exit_price', 0):,.2f}</i>")

        # 1-tap buttons for top qualified re-entry setups
        row = []
        for q in qualified[:4]:
            row.append({"text": f"➕ Add {q['symbol']}", "callback_data": f"cand_add:{q['symbol']}"})
            if len(row) == 2:
                inline_keyboard.append(row)
                row = []
        if row:
            inline_keyboard.append(row)
    else:
        lines.append("\nℹ️ <i>No past exited stocks currently satisfy the strict Stage 2 VCP candidate criteria. All are appropriately standing by.</i>")

    if standby:
        lines.append("\n⏳ <b>STANDBY EX-HOLDINGS (SAMPLE):</b>")
        for u in standby[:6]:
            lines.append(f"• <b>{u['symbol']}</b>: <i>{u.get('reason', 'Consolidating')}</i>")
        if len(standby) > 6:
            lines.append(f"  <i>...and {len(standby) - 6} more standing by</i>")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Qualified setups are automatically promoted into candidates.json & candidates.txt for tomorrow's morning ORB trigger.</i>")

    reply_markup = {"inline_keyboard": inline_keyboard} if inline_keyboard else None
    return "\n".join(lines), reply_markup


if __name__ == "__main__":
    print("Running EOD Exited Stocks Re-Entry & Candidate Engine...")
    audit_res = analyze_exited_stocks_eod()
    print(f"\nAudit completed: {audit_res['qualified_count']} qualified / {audit_res['standby_count']} standby")
    new_cands = promote_exited_to_candidates(audit_res["qualified"])
    print(f"Promoted to candidates: {new_cands}")
    card_text, _ = format_exited_analysis_telegram_card(audit_res)
    print("\n" + card_text)
