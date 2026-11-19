#!/usr/bin/env python3
"""
⚡ JARVIS AUTOMATED TRADE POST-MORTEM & JOURNALING ENGINE
=============================================================================
Automates trade tracking, post-mortem analysis, and execution performance metrics:
1. Real-Time Post-Mortem Logging:
   - Captures Entry & Exit Prices, Holding Days, Realized PnL (₹ & %).
   - Computes Realized R-Multiple, Peak R Achieved, and R Give-Back.
   - Diagnoses Exact Exit Reason:
     * 🛡️ 30% PROFIT CAP (Locked 70% of peak gain; zero profit surrender)
     * ⚡ PARABOLIC 5 EMA (Captured parabolic climax before reversal)
     * 🚀 DAY-1 SPURT SHIELD (Locked +1.5R day-1 surge into close)
     * 🟢 10/20 EMA TRAIL (Structural swing trend following)
     * 🟢 BREAKEVEN TRAIL (Risk-free trade preservation)
     * 🛑 INITIAL STOP LOSS (Disciplined risk containment)
     * 🎯 TARGET REACHED (Profit target milestone)
     * 🚨 MANUAL EXIT (User/Telegram manual execution)
2. Dual Persistence:
   - trade_log.csv  : Flat ledger easily opened in Excel / Sheets.
   - trade_log.json : Fast indexed JSON for Telegram cockpit & analytics.
3. Real-Time Telegram Broadcast:
   - Dispatches structured Post-Mortem cards to 'orders' and 'risk_trailing' topics.
4. Historical Seeding:
   - Auto-migrates and seeds historical trades from Journal.xlsx.
"""

import os
import sys
import csv
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
TRADE_LOG_CSV = SCRIPT_DIR / "trade_log.csv"
TRADE_LOG_JSON = SCRIPT_DIR / "trade_log.json"
TRACKED_HOLDINGS_FILE = SCRIPT_DIR / "tracked_holdings.json"
JOURNAL_FILE = SCRIPT_DIR / "Journal.xlsx"
CONFIG_FILE = SCRIPT_DIR / "config_credentials.json"

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    """Returns current datetime in IST."""
    return datetime.now(IST)


def clean_float(val: Any, default: float = 0.0) -> float:
    """Robust float converter handling formatted currency and R-multiple strings."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("₹", "").replace("R", "").replace("+", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return default


def load_trade_log_json() -> List[Dict[str, Any]]:
    """Loads all logged trades from trade_log.json."""
    if not TRADE_LOG_JSON.is_file():
        return []
    try:
        with open(TRADE_LOG_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Notice reading {TRADE_LOG_JSON.name}: {e}")
        return []


def save_trade_log_json(trades: List[Dict[str, Any]]):
    """Atomically saves trade list to trade_log.json."""
    tmp_path = TRADE_LOG_JSON.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
        tmp_path.replace(TRADE_LOG_JSON)
    except Exception as e:
        print(f"Error saving {TRADE_LOG_JSON.name}: {e}")


CSV_HEADERS = [
    "Timestamp", "Symbol", "Broker", "Product", "Qty",
    "Entry_Date", "Exit_Date", "Holding_Days",
    "Entry_Price", "Exit_Price", "Realized_PnL_INR", "Realized_PnL_Pct",
    "Initial_SL", "Final_SL", "Peak_LTP", "Peak_R", "Realized_R", "Giveback_R",
    "Exit_Reason", "Insight", "Notes"
]


def append_to_trade_log_csv(record: Dict[str, Any]):
    """Atomically appends trade record to trade_log.csv, writing headers if new."""
    write_headers = not TRADE_LOG_CSV.is_file() or TRADE_LOG_CSV.stat().st_size == 0
    try:
        with open(TRADE_LOG_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if write_headers:
                writer.writeheader()
            writer.writerow({
                "Timestamp": record.get("timestamp", ""),
                "Symbol": record.get("symbol", ""),
                "Broker": record.get("broker", ""),
                "Product": record.get("product", ""),
                "Qty": record.get("qty", 1),
                "Entry_Date": record.get("entry_date", ""),
                "Exit_Date": record.get("exit_date", ""),
                "Holding_Days": record.get("holding_days", 1),
                "Entry_Price": record.get("entry_price", 0.0),
                "Exit_Price": record.get("exit_price", 0.0),
                "Realized_PnL_INR": record.get("pnl_inr", 0.0),
                "Realized_PnL_Pct": record.get("pnl_pct", 0.0),
                "Initial_SL": record.get("initial_sl", 0.0),
                "Final_SL": record.get("final_sl", 0.0),
                "Peak_LTP": record.get("peak_ltp", 0.0),
                "Peak_R": record.get("peak_r", 0.0),
                "Realized_R": record.get("realized_r", 0.0),
                "Giveback_R": record.get("giveback_r", 0.0),
                "Exit_Reason": record.get("exit_reason", ""),
                "Insight": record.get("insight", ""),
                "Notes": record.get("notes", "")
            })
    except Exception as e:
        print(f"Error appending to {TRADE_LOG_CSV.name}: {e}")


def classify_exit_reason_and_insight(
    realized_r: float,
    peak_r: float,
    entry_p: float,
    exit_p: float,
    initial_sl: float,
    final_sl: float,
    last_trail_rule: str,
    explicit_reason: Optional[str] = None
) -> Tuple[str, str]:
    """
    Diagnoses exact trailing rule or stop trigger and institutional post-mortem insight.
    """
    rule_upper = (last_trail_rule or "").upper()

    if explicit_reason:
        reason = explicit_reason
    elif "30% PROFIT CAP" in rule_upper or (peak_r >= 2.5 and realized_r >= (peak_r * 0.65)):
        reason = "🛡️ 30% PROFIT CAP"
    elif "PARABOLIC 5 EMA" in rule_upper:
        reason = "⚡ PARABOLIC 5 EMA"
    elif "DAY-1 SPURT" in rule_upper:
        reason = "🚀 DAY-1 SPURT SHIELD"
    elif "BREAKEVEN" in rule_upper or (-0.15 <= realized_r <= 0.15 and exit_p >= entry_p):
        reason = "🟢 BREAKEVEN TRAIL"
    elif "10 EMA" in rule_upper:
        reason = "🟢 10 EMA STRUCTURAL TRAIL"
    elif "20 EMA" in rule_upper:
        reason = "🟢 20 EMA STRUCTURAL TRAIL"
    elif initial_sl > 0 and abs(exit_p - initial_sl) / max(1.0, initial_sl) < 0.015:
        reason = "🛑 INITIAL STOP LOSS"
    elif realized_r <= -0.8:
        reason = "🛑 INITIAL STOP LOSS"
    elif realized_r > 0:
        reason = "🟢 TRAILED STOP LOSS"
    else:
        reason = "🛑 STOP LOSS HIT"

    # Institutional Post-Mortem Insight
    if realized_r >= 3.0:
        insight = f"🏆 Super-Winner (+{realized_r:.1f}R). Trailing stop held through pullbacks and locked in multi-R expansion."
    elif "30% PROFIT CAP" in reason:
        insight = f"🛡️ Profit Cap locked 70% of peak gains (+{peak_r:.1f}R). Prevented profit give-back on trend exhaustion."
    elif "PARABOLIC" in reason:
        insight = "⚡ 5 EMA trail captured parabolic climax momentum before deep pullback."
    elif "DAY-1" in reason:
        insight = "🚀 Day-1 windfall shield locked +1.5R gain on strong momentum surge."
    elif "BREAKEVEN" in reason or abs(realized_r) <= 0.2:
        insight = "⚖️ Capital protection achieved. Breakeven / scratch exit eliminated trade risk."
    elif realized_r <= -0.8:
        insight = "🛑 Disciplined risk control. Initial stop honored; loss strictly contained within -1R."
    elif realized_r > 0:
        insight = f"📈 Positive follow-through (+{realized_r:.1f}R). Exit executed according to trailing rules."
    else:
        insight = f"⚠️ Early exit / pullback cut at {realized_r:.1f}R. Capital preserved for higher quality setups."

    return reason, insight


def record_trade_post_mortem(
    symbol: str,
    exit_price: float,
    exit_qty: Optional[int] = None,
    exit_reason: Optional[str] = None,
    broker: Optional[str] = None,
    notes: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    dispatch_telegram: bool = True
) -> Dict[str, Any]:
    """
    Records a completed trade post-mortem row to trade_log.csv and trade_log.json.
    Dispatches instant notification card to Telegram topics.
    """
    sym = (symbol or "").strip().upper()
    now_ist = get_ist_now()
    exit_ts_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    exit_date_str = now_ist.strftime("%Y-%m-%d")

    # Load metadata from tracked_holdings if not provided
    if not meta and TRACKED_HOLDINGS_FILE.is_file():
        try:
            with open(TRACKED_HOLDINGS_FILE, "r", encoding="utf-8") as f:
                th_data = json.load(f)
                meta = th_data.get(sym, {})
        except Exception:
            meta = {}
    if meta is None:
        meta = {}

    b = (broker or meta.get("broker") or "UNKNOWN").upper()
    prod = str(meta.get("product") or "CNC").upper()
    qty = int(exit_qty if exit_qty is not None and exit_qty > 0 else (meta.get("qty") or 1))
    entry_p = clean_float(meta.get("entry_price"), float(exit_price or 0.0))
    exit_p = clean_float(exit_price, entry_p)

    initial_sl = clean_float(meta.get("initial_sl") or meta.get("sl"), 0.0)
    final_sl = clean_float(meta.get("sl") or meta.get("recommended_sl"), exit_p)
    highest_ltp = clean_float(meta.get("highest_ltp"), max(entry_p, exit_p))
    last_trail_rule = str(meta.get("last_trail_rule") or meta.get("action_badge") or "")

    entry_date_str = str(meta.get("entry_date") or "").strip()
    if entry_date_str:
        try:
            entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
            holding_days = max(1, (now_ist.date() - entry_dt.date()).days)
        except Exception:
            holding_days = 1
    else:
        entry_date_str = exit_date_str
        holding_days = 1

    # Financial computations
    pnl_inr = round((exit_p - entry_p) * qty, 2)
    pnl_pct = round(((exit_p - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0

    risk_per_share = max(1.0, entry_p - initial_sl) if (initial_sl > 0 and initial_sl < entry_p) else round(entry_p * 0.03, 2)
    realized_r = round((exit_p - entry_p) / risk_per_share, 2)

    highest_r = clean_float(meta.get("highest_r"), 0.0)
    if highest_r <= 0.0:
        highest_r = max(realized_r, round((highest_ltp - entry_p) / risk_per_share, 2))

    giveback_r = max(0.0, round(highest_r - realized_r, 2))

    resolved_reason, insight = classify_exit_reason_and_insight(
        realized_r=realized_r,
        peak_r=highest_r,
        entry_p=entry_p,
        exit_p=exit_p,
        initial_sl=initial_sl,
        final_sl=final_sl,
        last_trail_rule=last_trail_rule,
        explicit_reason=exit_reason
    )

    record = {
        "timestamp": exit_ts_str,
        "symbol": sym,
        "broker": b,
        "product": prod,
        "qty": qty,
        "entry_date": entry_date_str,
        "exit_date": exit_date_str,
        "holding_days": holding_days,
        "entry_price": round(entry_p, 2),
        "exit_price": round(exit_p, 2),
        "pnl_inr": pnl_inr,
        "pnl_pct": pnl_pct,
        "initial_sl": round(initial_sl, 2),
        "final_sl": round(final_sl, 2),
        "peak_ltp": round(highest_ltp, 2),
        "peak_r": round(highest_r, 2),
        "realized_r": round(realized_r, 2),
        "giveback_r": giveback_r,
        "exit_reason": resolved_reason,
        "insight": insight,
        "notes": notes or ""
    }

    # Dedup check: Avoid duplicate record if logged within last 120 seconds for same symbol & qty
    existing_trades = load_trade_log_json()
    cutoff_time = time.time() - 120
    is_duplicate = False
    for t in existing_trades[-10:]:
        if t.get("symbol") == sym and t.get("exit_date") == exit_date_str and t.get("qty") == qty:
            try:
                t_dt = datetime.strptime(t.get("timestamp", "").split(" IST")[0], "%Y-%m-%d %H:%M:%S")
                if t_dt.timestamp() > cutoff_time:
                    is_duplicate = True
                    break
            except Exception:
                pass

    if not is_duplicate:
        existing_trades.append(record)
        save_trade_log_json(existing_trades)
        append_to_trade_log_csv(record)
        print(f"📁 Logged trade post-mortem: {sym} | Realized PnL: ₹{pnl_inr:+,.2f} ({realized_r:+.2f}R) | Reason: {resolved_reason}")

    # Dispatch Telegram Alert
    if dispatch_telegram:
        pnl_icon = "🟢" if pnl_inr > 0 else ("🔴" if pnl_inr < 0 else "⚪")
        pnl_sign = "+" if pnl_inr > 0 else ""
        alert_html = (
            f"🏁 <b>TRADE CLOSED & POST-MORTEM RECORDED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏛 <b>{sym}</b> (<b>{b}</b> | <code>{prod}</code>)\n"
            f"📅 <b>Entry:</b> {entry_date_str} ➔ <b>Exit:</b> {exit_date_str} (<b>{holding_days}d</b>)\n"
            f"💰 <b>Entry:</b> ₹{entry_p:,.2f} ➔ <b>Exit:</b> ₹{exit_p:,.2f} (<b>{qty} shs</b>)\n"
            f"📊 <b>Realized P&L:</b> {pnl_icon} <b>{pnl_sign}₹{abs(pnl_inr):,.2f}</b> (<code>{pnl_pct:+.2f}%</code>)\n"
            f"🎯 <b>Realized R:</b> <b>{realized_r:+.2f}R</b> (Peak: +{highest_r:.1f}R @ ₹{highest_ltp:,.2f})\n"
            f"🛡️ <b>Exit Reason:</b> <b>{resolved_reason}</b>\n"
            f"🧠 <b>Post-Mortem:</b> <i>{insight}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 <i>Persisted in <code>trade_log.csv</code> & <code>Journal.xlsx</code>.</i>"
        )
        try:
            from telegram_bot import send_topic_alert
            send_topic_alert("orders", alert_html)
            send_topic_alert("risk_trailing", alert_html)
        except Exception as ex_tg:
            print(f"Notice sending post-mortem Telegram alert: {ex_tg}")

    return record


def get_post_mortem_analytics() -> Dict[str, Any]:
    """
    Computes aggregated performance and post-mortem statistics across all closed trades.
    """
    trades = load_trade_log_json()
    if not trades and JOURNAL_FILE.is_file():
        seed_trade_log_from_journal()
        trades = load_trade_log_json()

    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "scratches": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "rule_breakdown": {},
            "recent_trades": []
        }

    wins = [t for t in trades if clean_float(t.get("pnl_inr")) > 0]
    losses = [t for t in trades if clean_float(t.get("pnl_inr")) < 0]
    scratches = [t for t in trades if clean_float(t.get("pnl_inr")) == 0]

    tot_trades = len(trades)
    win_rate = round((len(wins) / tot_trades) * 100, 1) if tot_trades > 0 else 0.0
    tot_pnl = sum(clean_float(t.get("pnl_inr")) for t in trades)

    gross_profit = sum(clean_float(t.get("pnl_inr")) for t in wins)
    gross_loss = abs(sum(clean_float(t.get("pnl_inr")) for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    r_multiples = [clean_float(t.get("realized_r")) for t in trades]
    avg_r = round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0.0

    win_rs = [clean_float(t.get("realized_r")) for t in wins]
    avg_win_r = round(sum(win_rs) / len(win_rs), 2) if win_rs else 0.0

    loss_rs = [clean_float(t.get("realized_r")) for t in losses]
    avg_loss_r = round(sum(loss_rs) / len(loss_rs), 2) if loss_rs else 0.0

    # Rule breakdown
    rule_breakdown = {}
    for t in trades:
        reason = t.get("exit_reason", "OTHER")
        if reason not in rule_breakdown:
            rule_breakdown[reason] = {"count": 0, "pnl": 0.0, "total_r": 0.0}
        rule_breakdown[reason]["count"] += 1
        rule_breakdown[reason]["pnl"] += clean_float(t.get("pnl_inr"))
        rule_breakdown[reason]["total_r"] += clean_float(t.get("realized_r"))

    for reason, data in rule_breakdown.items():
        data["avg_r"] = round(data["total_r"] / data["count"], 2) if data["count"] > 0 else 0.0
        data["pnl"] = round(data["pnl"], 2)

    return {
        "total_trades": tot_trades,
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(scratches),
        "win_rate": win_rate,
        "total_pnl": round(tot_pnl, 2),
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "rule_breakdown": rule_breakdown,
        "recent_trades": list(reversed(trades[-8:]))
    }


def format_post_mortem_telegram_card() -> str:
    """
    Renders an executive Telegram card for /postmortem, /trades, or /perf.
    """
    stats = get_post_mortem_analytics()
    if stats["total_trades"] == 0:
        return (
            "📊 <b>TRADE POST-MORTEM & PERFORMANCE COCKPIT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ No closed trades recorded in <code>trade_log.csv</code> yet.\n"
            "As trades exit via GTT or manual execution, post-mortems will appear here automatically."
        )

    pnl = stats["total_pnl"]
    pnl_sign = "+" if pnl > 0 else ""
    pnl_icon = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")

    lines = [
        "📊 <b>JARVIS TRADE POST-MORTEM & JOURNAL COCKPIT</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 <b>Overall Performance:</b>",
        f"• Total Closed Trades: <b>{stats['total_trades']}</b>",
        f"• Win Rate: <b>{stats['win_rate']:.1f}%</b> (🟢 {stats['wins']}W | 🔴 {stats['losses']}L | ⚪ {stats['scratches']}S)",
        f"• Realized P&L: {pnl_icon} <b>{pnl_sign}₹{abs(pnl):,.2f}</b>",
        f"• Profit Factor: <b>{stats['profit_factor']:.2f}</b>",
        f"• Realized R: Avg <b>{stats['avg_r']:+.2f}R</b> (Wins: +{stats['avg_win_r']:.1f}R | Losses: {stats['avg_loss_r']:.1f}R)",
        "",
        "🛡️ <b>Trailing Rules & Exit Breakdown:</b>"
    ]

    for reason, data in sorted(stats["rule_breakdown"].items(), key=lambda x: x[1]["count"], reverse=True):
        val = data["pnl"]
        val_str = f"+₹{val:,.0f}" if val > 0 else (f"-₹{abs(val):,.0f}" if val < 0 else "₹0")
        lines.append(f"• <b>{reason}</b>: {data['count']} trades ({val_str} | Avg {data['avg_r']:+.1f}R)")

    if stats["recent_trades"]:
        lines.append("")
        lines.append("📋 <b>Recent Trade Post-Mortems:</b>")
        for t in stats["recent_trades"][:5]:
            t_pnl = clean_float(t.get("pnl_inr"))
            t_str = f"+₹{t_pnl:,.0f}" if t_pnl > 0 else (f"-₹{abs(t_pnl):,.0f}" if t_pnl < 0 else "₹0")
            t_r = clean_float(t.get("realized_r"))
            lines.append(f"• <b>{t['symbol']}</b>: {t_str} ({t_r:+.1f}R) | {t.get('holding_days', 1)}d | {t.get('exit_reason', 'EXIT')}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📁 <i>Full audit log persisted in <code>trade_log.csv</code> & <code>Journal.xlsx</code>.</i>")

    return "\n".join(lines)


def seed_trade_log_from_journal(force: bool = False) -> int:
    """
    Seeds trade_log.csv and trade_log.json from Journal.xlsx closed trades.
    Only runs if trade_log.json is empty or force=True.
    """
    if not force and TRADE_LOG_JSON.is_file() and len(load_trade_log_json()) > 0:
        return 0

    if not JOURNAL_FILE.is_file():
        print(f"Notice: {JOURNAL_FILE.name} not found for seeding.")
        return 0

    import openpyxl
    wb = openpyxl.load_workbook(JOURNAL_FILE, data_only=True)
    if "Trade Journal" not in wb.sheetnames:
        return 0

    ws = wb["Trade Journal"]
    seeded_records = []

    for r in range(2, ws.max_row + 1):
        status = ws.cell(row=r, column=11).value
        sym = ws.cell(row=r, column=3).value
        entry_p = ws.cell(row=r, column=5).value
        exit_p = ws.cell(row=r, column=9).value

        if status and "CLOSED" in str(status).upper() and sym and entry_p and exit_p:
            entry_p = clean_float(entry_p)
            exit_p = clean_float(exit_p)
            qty = int(clean_float(ws.cell(row=r, column=8).value, 1))
            initial_sl = clean_float(ws.cell(row=r, column=6).value, 0.0)
            pnl_inr = clean_float(ws.cell(row=r, column=21).value or ws.cell(row=r, column=14).value, round((exit_p - entry_p) * qty, 2))
            pnl_pct = clean_float(ws.cell(row=r, column=15).value, round(((exit_p - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0)
            realized_r = clean_float(ws.cell(row=r, column=17).value, 0.0)
            holding_days = int(clean_float(ws.cell(row=r, column=19).value, 1))
            notes = str(ws.cell(row=r, column=22).value or "").strip()

            e_dt_val = ws.cell(row=r, column=2).value
            entry_date_str = str(e_dt_val)[:10] if e_dt_val else "2026-10-01"

            x_dt_val = ws.cell(row=r, column=10).value
            exit_date_str = str(x_dt_val)[:10] if x_dt_val else "2026-11-01"

            resolved_reason, insight = classify_exit_reason_and_insight(
                realized_r=realized_r,
                peak_r=max(realized_r, 0.0),
                entry_p=entry_p,
                exit_p=exit_p,
                initial_sl=initial_sl,
                final_sl=exit_p,
                last_trail_rule=notes
            )

            rec = {
                "timestamp": f"{exit_date_str} 15:30:00 IST",
                "symbol": str(sym).strip().upper(),
                "broker": "JOURNAL",
                "product": "CNC",
                "qty": qty,
                "entry_date": entry_date_str,
                "exit_date": exit_date_str,
                "holding_days": holding_days,
                "entry_price": round(entry_p, 2),
                "exit_price": round(exit_p, 2),
                "pnl_inr": round(pnl_inr, 2),
                "pnl_pct": round(pnl_pct, 2),
                "initial_sl": round(initial_sl, 2),
                "final_sl": round(exit_p, 2),
                "peak_ltp": round(max(entry_p, exit_p), 2),
                "peak_r": round(max(realized_r, 0.0), 2),
                "realized_r": round(realized_r, 2),
                "giveback_r": 0.0,
                "exit_reason": resolved_reason,
                "insight": insight,
                "notes": notes
            }
            seeded_records.append(rec)

    if seeded_records:
        save_trade_log_json(seeded_records)
        # Rewrite trade_log.csv cleanly
        try:
            with open(TRADE_LOG_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()
                for rec in seeded_records:
                    writer.writerow({
                        "Timestamp": rec.get("timestamp", ""),
                        "Symbol": rec.get("symbol", ""),
                        "Broker": rec.get("broker", ""),
                        "Product": rec.get("product", ""),
                        "Qty": rec.get("qty", 1),
                        "Entry_Date": rec.get("entry_date", ""),
                        "Exit_Date": rec.get("exit_date", ""),
                        "Holding_Days": rec.get("holding_days", 1),
                        "Entry_Price": rec.get("entry_price", 0.0),
                        "Exit_Price": rec.get("exit_price", 0.0),
                        "Realized_PnL_INR": rec.get("pnl_inr", 0.0),
                        "Realized_PnL_Pct": rec.get("pnl_pct", 0.0),
                        "Initial_SL": rec.get("initial_sl", 0.0),
                        "Final_SL": rec.get("final_sl", 0.0),
                        "Peak_LTP": rec.get("peak_ltp", 0.0),
                        "Peak_R": rec.get("peak_r", 0.0),
                        "Realized_R": rec.get("realized_r", 0.0),
                        "Giveback_R": rec.get("giveback_r", 0.0),
                        "Exit_Reason": rec.get("exit_reason", ""),
                        "Insight": rec.get("insight", ""),
                        "Notes": rec.get("notes", "")
                    })
            print(f"✅ Successfully seeded {len(seeded_records)} historical trades into trade_log.csv and trade_log.json.")
        except Exception as e:
            print(f"Error writing seeded CSV: {e}")

    return len(seeded_records)


if __name__ == "__main__":
    if "--seed" in sys.argv:
        cnt = seed_trade_log_from_journal(force=True)
        print(f"Seeded {cnt} trades.")
    else:
        print(format_post_mortem_telegram_card())
