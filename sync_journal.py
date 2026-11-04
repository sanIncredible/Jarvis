#!/usr/bin/env python3
"""
⚡ JARVIS EOD TRADE JOURNAL AUTOMATOR (Zerodha Kite & DhanHQ -> Journal.xlsx)
=============================================================================
Automates End-of-Day trade journaling from Dhan and Zerodha Kite into Journal.xlsx.
- Eliminates manual typing of symbols, prices, quantities, and timestamps.
- Dual-Mode: Automatic Live Broker API (1-click) + Drop-in CSV Fallback.
- Reconciles raw fills into closed trades, open positions, and partial exits.
- Automatically calculates exact statutory charges (STT, Brokerage, GST, Stamp).
- Updates 'Trade Journal', 'Open Positions', 'Dashboard', and 'Calendar'.
- Dispatches an executive EOD Trade Summary Card to Telegram.
- Creates automated timestamped backups in backups/ before every write.
"""

import os
import sys
import json
import shutil
import glob
import csv
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import requests

# Set stdout encoding for Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
JOURNAL_FILE = BASE_DIR / "Journal.xlsx"
CONFIG_FILE = BASE_DIR / "config_credentials.json"
BACKUP_DIR = BASE_DIR / "backups"
UPSTOX_TOKEN_FILE = BASE_DIR / "upstoxtoken.txt"

# Colors for Excel & Formatting
GREEN_FILL = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
RED_FILL = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
YELLOW_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
BLUE_FILL = PatternFill(start_color="D1ECF1", end_color="D1ECF1", fill_type="solid")
HEADER_FILL = PatternFill(start_color="1A237E", end_color="1A237E", fill_type="solid")
WHITE_BOLD_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
BOLD_FONT = Font(name="Calibri", size=11, bold=True)
REGULAR_FONT = Font(name="Calibri", size=11)


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


def create_backup() -> Optional[Path]:
    """Creates a timestamped snapshot of Journal.xlsx in backups/ before any edits."""
    if not JOURNAL_FILE.is_file():
        print(f"❌ {JOURNAL_FILE.name} not found!")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"Journal_backup_{ts}.xlsx"
    try:
        shutil.copy2(JOURNAL_FILE, backup_path)
        print(f"🔒 Backup created: {backup_path.name}")
        # Automatically prune backups older than 14 days
        cutoff = time.time() - (14 * 86400)
        for old in BACKUP_DIR.glob("Journal_backup_*.xlsx"):
            if old.stat().st_mtime < cutoff:
                try:
                    old.unlink()
                except Exception:
                    pass
        return backup_path
    except Exception as e:
        print(f"⚠️ Backup creation failed: {e}")
        return None


# =============================================================================
# 1. BROKER FETCHERS: DHAN & ZERODHA KITE (API + CSV FALLBACK)
# =============================================================================

def fetch_dhan_executions(config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """
    Fetches today's completed trades and pending orders from DhanHQ API.
    Falls back to dhan_trades*.csv or orderbook*.csv if token is expired or unavailable.
    Returns: (trades_list, orders_list, source_description)
    """
    d_cfg = config.get("dhan", {})
    client_id = d_cfg.get("client_id", "").strip()
    access_token = d_cfg.get("access_token", "").strip()

    # 1. Try Live DhanHQ API
    if client_id and access_token and d_cfg.get("enabled", True):
        headers = {
            "access-token": access_token,
            "client-id": client_id,
            "Content-Type": "application/json"
        }
        try:
            r_trades = requests.get("https://api.dhan.co/v2/trades", headers=headers, timeout=8)
            if r_trades.status_code == 200:
                raw_trades = r_trades.json() if isinstance(r_trades.json(), list) else r_trades.json().get("data", [])
                
                # Fetch orders for pending SL detection
                r_orders = requests.get("https://api.dhan.co/v2/orders", headers=headers, timeout=8)
                raw_orders = r_orders.json() if r_orders.status_code == 200 and isinstance(r_orders.json(), list) else []

                norm_trades = []
                for t in raw_trades:
                    sym = (t.get("tradingSymbol") or t.get("customSymbol") or "").strip().upper()
                    norm_trades.append({
                        "broker": "Dhan",
                        "symbol": sym,
                        "side": (t.get("transactionType") or "").strip().upper(),
                        "qty": float(t.get("tradedQuantity", 0) or t.get("quantity", 0)),
                        "price": float(t.get("tradedPrice", 0) or t.get("price", 0)),
                        "time": str(t.get("exchangeTime") or t.get("createTime") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        "order_id": str(t.get("orderId", "")),
                        "product": str(t.get("productType", "CNC")).upper()
                    })

                print(f"✅ DhanHQ API: Successfully fetched {len(norm_trades)} executed trades.")
                return norm_trades, raw_orders, "DhanHQ Live API"
            elif r_trades.status_code == 401:
                print("ℹ️ Dhan token is expired (30-day validity). Checking for CSV fallback...")
            else:
                print(f"⚠️ Dhan API response: HTTP {r_trades.status_code}")
        except Exception as e:
            print(f"⚠️ Dhan API error: {e}")

    # 2. Check for Drop-in CSV files
    csv_patterns = ["*dhan*trades*.csv", "*trades*dhan*.csv", "*dhan*order*.csv", "Dhan_TradeBook*.csv"]
    for pat in csv_patterns:
        matches = list(BASE_DIR.glob(pat))
        if matches:
            target_csv = matches[0]
            print(f"📂 Found Dhan tradebook CSV: {target_csv.name}")
            return parse_dhan_csv(target_csv), [], f"Dhan CSV ({target_csv.name})"

    return [], [], "None"


def parse_dhan_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Parses exported Dhan Tradebook CSV."""
    trades = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictIndex = csv.DictReader(f)
            for row in reader:
                sym_key = next((k for k in row.keys() if "symbol" in k.lower() or "trading" in k.lower()), None)
                side_key = next((k for k in row.keys() if "type" in k.lower() or "side" in k.lower() or "action" in k.lower()), None)
                qty_key = next((k for k in row.keys() if "qty" in k.lower() or "quantity" in k.lower()), None)
                price_key = next((k for k in row.keys() if "price" in k.lower() or "rate" in k.lower() or "avg" in k.lower()), None)
                time_key = next((k for k in row.keys() if "time" in k.lower() or "date" in k.lower()), None)

                if sym_key and side_key and qty_key and price_key:
                    sym = str(row[sym_key]).strip().upper().replace("NSE:", "").replace("BSE:", "")
                    side = str(row[side_key]).strip().upper()
                    if "BUY" in side or side == "B":
                        side = "BUY"
                    elif "SELL" in side or side == "S":
                        side = "SELL"
                    qty = float(str(row[qty_key]).replace(",", "").strip() or 0)
                    price = float(str(row[price_key]).replace(",", "").replace("₹", "").strip() or 0)
                    t_str = str(row[time_key]).strip() if time_key else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if sym and qty > 0 and price > 0:
                        trades.append({
                            "broker": "Dhan",
                            "symbol": sym,
                            "side": side,
                            "qty": qty,
                            "price": price,
                            "time": t_str,
                            "order_id": "",
                            "product": "CNC"
                        })
    except Exception as e:
        print(f"⚠️ Error parsing Dhan CSV: {e}")
    return trades


def fetch_zerodha_executions(config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """
    Fetches today's completed trades and pending orders from Zerodha Kite Connect API.
    Falls back to kite_trades*.csv or tradebook*.csv if token is expired or unavailable.
    Returns: (trades_list, orders_list, source_description)
    """
    z_cfg = config.get("zerodha", {})
    api_key = z_cfg.get("api_key", "").strip()
    access_token = z_cfg.get("access_token", "").strip()

    # 1. Try Live Kite Connect API
    if api_key and access_token and z_cfg.get("enabled", True):
        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}"
        }
        try:
            r_trades = requests.get("https://api.kite.trade/trades", headers=headers, timeout=8)
            if r_trades.status_code == 200:
                raw_trades = r_trades.json().get("data", [])
                
                # Fetch orders for pending SL detection
                r_orders = requests.get("https://api.kite.trade/orders", headers=headers, timeout=8)
                raw_orders = r_orders.json().get("data", []) if r_orders.status_code == 200 else []

                norm_trades = []
                for t in raw_trades:
                    sym = (t.get("tradingsymbol") or "").strip().upper()
                    norm_trades.append({
                        "broker": "Zerodha",
                        "symbol": sym,
                        "side": (t.get("transaction_type") or "").strip().upper(),
                        "qty": float(t.get("quantity", 0)),
                        "price": float(t.get("average_price", 0) or t.get("price", 0)),
                        "time": str(t.get("fill_timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        "order_id": str(t.get("order_id", "")),
                        "product": str(t.get("product", "CNC")).upper()
                    })

                print(f"✅ Zerodha Kite API: Successfully fetched {len(norm_trades)} executed trades.")
                return norm_trades, raw_orders, "Zerodha Kite Live API"
            elif r_trades.status_code == 403:
                print("ℹ️ Zerodha token is expired (daily 6:00 AM expiry). Checking for CSV fallback...")
            else:
                print(f"⚠️ Zerodha API response: HTTP {r_trades.status_code}")
        except Exception as e:
            print(f"⚠️ Zerodha API error: {e}")

    # 2. Check for Drop-in CSV files
    csv_patterns = ["*kite*trades*.csv", "*trades*kite*.csv", "*tradebook*.csv", "trades.csv"]
    for pat in csv_patterns:
        matches = list(BASE_DIR.glob(pat))
        if matches:
            target_csv = matches[0]
            print(f"📂 Found Zerodha tradebook CSV: {target_csv.name}")
            return parse_zerodha_csv(target_csv), [], f"Zerodha CSV ({target_csv.name})"

    return [], [], "None"


def parse_zerodha_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Parses exported Zerodha Tradebook CSV."""
    trades = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym_key = next((k for k in row.keys() if "symbol" in k.lower() or "tradingsymbol" in k.lower()), None)
                side_key = next((k for k in row.keys() if "type" in k.lower() or "trade_type" in k.lower()), None)
                qty_key = next((k for k in row.keys() if "qty" in k.lower() or "quantity" in k.lower()), None)
                price_key = next((k for k in row.keys() if "price" in k.lower() or "rate" in k.lower()), None)
                time_key = next((k for k in row.keys() if "time" in k.lower() or "date" in k.lower()), None)

                if sym_key and side_key and qty_key and price_key:
                    sym = str(row[sym_key]).strip().upper()
                    side = str(row[side_key]).strip().upper()
                    qty = float(str(row[qty_key]).replace(",", "").strip() or 0)
                    price = float(str(row[price_key]).replace(",", "").replace("₹", "").strip() or 0)
                    t_str = str(row[time_key]).strip() if time_key else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if sym and qty > 0 and price > 0:
                        trades.append({
                            "broker": "Zerodha",
                            "symbol": sym,
                            "side": side,
                            "qty": qty,
                            "price": price,
                            "time": t_str,
                            "order_id": "",
                            "product": "CNC"
                        })
    except Exception as e:
        print(f"⚠️ Error parsing Zerodha CSV: {e}")
    return trades


# =============================================================================
# 2. TRADE AGGREGATION & POSITION MATCHING ENGINE
# =============================================================================

def aggregate_fills_by_symbol(fills: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Groups individual executions/fills into volume-weighted averages for BUY and SELL sides.
    Handles partial fills cleanly:
    e.g. 100 @ 1320 + 200 @ 1326 -> 300 @ 1324.00
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    for f in fills:
        sym = f["symbol"]
        side = f["side"]
        qty = f["qty"]
        price = f["price"]

        if sym not in grouped:
            grouped[sym] = {
                "symbol": sym,
                "buy_qty": 0.0,
                "buy_val": 0.0,
                "sell_qty": 0.0,
                "sell_val": 0.0,
                "earliest_time": f["time"],
                "brokers": set()
            }

        grouped[sym]["brokers"].add(f["broker"])
        if side == "BUY":
            grouped[sym]["buy_qty"] += qty
            grouped[sym]["buy_val"] += (qty * price)
        elif side == "SELL":
            grouped[sym]["sell_qty"] += qty
            grouped[sym]["sell_val"] += (qty * price)

    result = {}
    for sym, d in grouped.items():
        b_qty = d["buy_qty"]
        s_qty = d["sell_qty"]
        b_vwap = round(d["buy_val"] / b_qty, 2) if b_qty > 0 else 0.0
        s_vwap = round(d["sell_val"] / s_qty, 2) if s_qty > 0 else 0.0
        result[sym] = {
            "symbol": sym,
            "buy_qty": b_qty,
            "buy_vwap": b_vwap,
            "sell_qty": s_qty,
            "sell_vwap": s_vwap,
            "time": d["earliest_time"],
            "broker": ", ".join(sorted(d["brokers"]))
        }
    return result


def find_pending_sl(symbol: str, orders: List[Dict[str, Any]], entry_price: float) -> Optional[float]:
    """
    Finds intended Stop Loss by inspecting active/pending trigger orders from Kite or Dhan.
    Looks for SL, SL-M, or GTT trigger orders.
    """
    for o in orders:
        o_sym = (o.get("tradingsymbol") or o.get("tradingSymbol") or o.get("customSymbol") or "").strip().upper()
        if o_sym == symbol:
            status = str(o.get("status") or o.get("orderStatus") or "").upper()
            if status in ["TRIGGER PENDING", "PENDING", "OPEN"]:
                trigger_p = float(o.get("trigger_price", 0) or o.get("triggerPrice", 0) or 0)
                if trigger_p > 0 and trigger_p < entry_price:
                    return round(trigger_p, 2)
                p = float(o.get("price", 0) or 0)
                if p > 0 and p < entry_price:
                    return round(p, 2)
    return None


def calculate_charges(entry_price: float, exit_price: float, qty: float, brokerage_per_trade: float = 20.0, stt_rate: float = 0.025, gst_rate: float = 18.0) -> float:
    """
    Calculates statutory charges for a round-trip trade:
    Brokerage (capped at ₹20 per leg) + STT on sell + 18% GST.
    """
    turnover = (entry_price * qty) + (exit_price * qty)
    brokerage = min(brokerage_per_trade, turnover * 0.0003) * 2
    stt = (exit_price * qty) * (stt_rate / 100.0)
    gst = brokerage * (gst_rate / 100.0)
    return round(brokerage + stt + gst, 2)


# =============================================================================
# 3. LIVE LTP FETCHER (UPSTOX API + YAHOO FINANCE FALLBACK)
# =============================================================================

def fetch_live_ltp(symbol: str) -> Optional[float]:
    """Fetches real-time price via order_engine, Upstox API token or Yahoo Finance."""
    clean_sym = symbol.strip().upper().replace("NSE:", "").replace("BSE:", "")

    # 1. Try order_engine fetch_live_quote
    try:
        from order_engine import fetch_live_quote
        q, _ = fetch_live_quote(clean_sym)
        if q and q.get("ltp"):
            return round(float(q["ltp"]), 2)
    except Exception:
        pass

    # 2. Try Upstox API from config_credentials.json or upstoxtoken.txt
    token = ""
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                token = json.load(f).get("upstox", {}).get("access_token", "").strip()
        except Exception:
            pass
    if not token and UPSTOX_TOKEN_FILE.is_file():
        try:
            with open(UPSTOX_TOKEN_FILE, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            pass

    if token:
        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key=NSE_EQ|{clean_sym}"
            r = requests.get(url, headers=headers, timeout=4)
            if r.status_code == 200:
                d = r.json().get("data", {})
                for k, v in d.items():
                    if v.get("last_price"):
                        return round(float(v["last_price"]), 2)
        except Exception:
            pass

    # 2. Yahoo Finance fallback
    try:
        ticker = f"{clean_sym}.NS"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            res = r.json()["chart"]["result"][0]
            ltp = res["meta"].get("regularMarketPrice")
            if ltp:
                return round(float(ltp), 2)
    except Exception:
        pass

    return None


# =============================================================================
# 4. EXCEL WORKBOOK RECONCILER (Journal.xlsx)
# =============================================================================

def get_next_available_row(ws) -> int:
    """Finds the first row starting from row 2 where Symbol (column 3) is empty."""
    for r in range(2, 5000):
        val = ws.cell(row=r, column=3).value
        if val is None or str(val).strip() == "":
            return r
    return ws.max_row + 1


def reconcile_journal(fills_by_sym: Dict[str, Dict[str, Any]], all_orders: List[Dict[str, Any]], live_positions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Reconciles aggregated fills with Journal.xlsx:
    1. Matches SELL fills against currently OPEN trades -> stamps exit price, exit date, computes P&L.
    2. Matches BUY fills for new stocks -> appends as new OPEN rows.
    3. Auto-reconciles carried-forward live broker positions (Dhan, Zerodha, Upstox) missing from Trade Journal.
    4. Handles intraday round trips.
    5. Refreshes LTP and Action Signals for Open Positions.
    6. Recalculates Dashboard metrics and Calendar.
    """
    if live_positions is None:
        try:
            from order_engine import fetch_all_positions
            live_positions, _, _ = fetch_all_positions()
        except Exception:
            live_positions = []
    if not JOURNAL_FILE.is_file():
        print(f"❌ {JOURNAL_FILE.name} does not exist.")
        return {"status": "error", "message": "Journal file not found"}

    wb = openpyxl.load_workbook(JOURNAL_FILE)

    # 1. Clean Watchlist sheet if still present
    if "Watchlist" in wb.sheetnames:
        del wb["Watchlist"]
        print("🗑️ Removed unnecessary 'Watchlist' sheet from Journal.xlsx.")

    ws_tj = wb["Trade Journal"]
    today_dt = datetime.combine(date.today(), datetime.min.time())

    # Read existing rows in Trade Journal
    existing_open = {}  # {symbol: list of row indices}
    max_trade_num = 0
    all_trade_rows = []

    for r in range(2, ws_tj.max_row + 1):
        t_num = ws_tj.cell(row=r, column=1).value
        dt_val = ws_tj.cell(row=r, column=2).value
        sym = ws_tj.cell(row=r, column=3).value
        side = ws_tj.cell(row=r, column=4).value
        entry_p = ws_tj.cell(row=r, column=5).value
        sl_val = ws_tj.cell(row=r, column=6).value
        tgt_val = ws_tj.cell(row=r, column=7).value
        qty_val = ws_tj.cell(row=r, column=8).value
        status = ws_tj.cell(row=r, column=11).value

        if t_num and isinstance(t_num, (int, float)):
            max_trade_num = max(max_trade_num, int(t_num))

        if sym:
            sym_clean = str(sym).strip().upper()
            all_trade_rows.append(r)
            if status and "OPEN" in str(status).upper():
                if sym_clean not in existing_open:
                    existing_open[sym_clean] = []
                existing_open[sym_clean].append({
                    "row": r,
                    "date": dt_val,
                    "entry_price": float(entry_p or 0),
                    "sl": float(sl_val or 0) if sl_val else None,
                    "target": float(tgt_val or 0) if tgt_val else None,
                    "qty": float(qty_val or 0)
                })

    closed_today = []
    opened_today = []

    # Process fills
    for sym, fill_data in fills_by_sym.items():
        buy_qty = fill_data["buy_qty"]
        buy_vwap = fill_data["buy_vwap"]
        sell_qty = fill_data["sell_qty"]
        sell_vwap = fill_data["sell_vwap"]

        # Case A: We have SELL fills and an existing OPEN position
        if sell_qty > 0 and sym in existing_open and existing_open[sym]:
            open_pos = existing_open[sym].pop(0)  # FIFO match
            r_idx = open_pos["row"]
            entry_p = open_pos["entry_price"]
            orig_qty = open_pos["qty"]
            sl_val = open_pos["sl"]
            entry_dt = open_pos["date"]

            exit_qty = min(sell_qty, orig_qty)
            ws_tj.cell(row=r_idx, column=8, value=exit_qty)  # Qty
            ws_tj.cell(row=r_idx, column=9, value=sell_vwap)  # Exit Price
            ws_tj.cell(row=r_idx, column=10, value=today_dt)  # Exit Date
            ws_tj.cell(row=r_idx, column=11, value="CLOSED")  # Status

            realized_pnl = round((sell_vwap - entry_p) * exit_qty, 2)
            charges = calculate_charges(entry_p, sell_vwap, exit_qty)
            net_pnl = round(realized_pnl - charges, 2)
            pnl_pct = round((realized_pnl / (entry_p * exit_qty)) * 100.0, 2) if (entry_p * exit_qty) > 0 else 0.0

            risk_rs = round(abs(entry_p - sl_val) * exit_qty, 2) if sl_val else None
            r_mult = round(realized_pnl / risk_rs, 2) if risk_rs and risk_rs > 0 else None

            holding_days = 0
            if isinstance(entry_dt, datetime):
                holding_days = max(0, (today_dt - entry_dt).days)
            elif isinstance(entry_dt, date):
                holding_days = max(0, (date.today() - entry_dt).days)

            ws_tj.cell(row=r_idx, column=13, value=0.0)  # Unrealized P&L
            ws_tj.cell(row=r_idx, column=14, value=realized_pnl)
            ws_tj.cell(row=r_idx, column=15, value=pnl_pct)
            if risk_rs:
                ws_tj.cell(row=r_idx, column=16, value=risk_rs)
            if r_mult is not None:
                ws_tj.cell(row=r_idx, column=17, value=r_mult)
            ws_tj.cell(row=r_idx, column=19, value=holding_days)
            ws_tj.cell(row=r_idx, column=20, value=charges)
            ws_tj.cell(row=r_idx, column=21, value=net_pnl)

            closed_today.append({
                "symbol": sym,
                "qty": exit_qty,
                "entry_p": entry_p,
                "exit_p": sell_vwap,
                "net_pnl": net_pnl,
                "pnl_pct": pnl_pct,
                "r_mult": r_mult
            })
            print(f"🎯 CLOSED Position: {sym} | Sold {exit_qty} @ ₹{sell_vwap:,.2f} | Net P&L: ₹{net_pnl:+,.2f} ({pnl_pct:+.1f}%)")

            # Clean up any remaining duplicate ghost open entries for this symbol
            if sym in existing_open and existing_open[sym]:
                for extra_pos in existing_open[sym]:
                    extra_row = extra_pos["row"]
                    ws_tj.cell(row=extra_row, column=11, value="CLOSED")
                    ws_tj.cell(row=extra_row, column=9, value=sell_vwap)
                    ws_tj.cell(row=extra_row, column=10, value=today_dt)
                    ws_tj.cell(row=extra_row, column=13, value=0.0)
                existing_open[sym] = []

            # Partial exit remainder
            if orig_qty > sell_qty:
                rem_qty = orig_qty - sell_qty
                max_trade_num += 1
                next_row = get_next_available_row(ws_tj)
                ws_tj.cell(row=next_row, column=1, value=float(max_trade_num))
                ws_tj.cell(row=next_row, column=2, value=entry_dt)
                ws_tj.cell(row=next_row, column=3, value=sym)
                ws_tj.cell(row=next_row, column=4, value="BUY")
                ws_tj.cell(row=next_row, column=5, value=entry_p)
                ws_tj.cell(row=next_row, column=6, value=sl_val)
                ws_tj.cell(row=next_row, column=7, value=open_pos["target"])
                ws_tj.cell(row=next_row, column=8, value=rem_qty)
                ws_tj.cell(row=next_row, column=11, value="OPEN 🟢")
                print(f"   ↳ Retained {rem_qty} shares of {sym} as OPEN position (Row {next_row}).")

        # Case B: We have BUY fills for a new stock (not already open)
        elif buy_qty > 0 and (sell_qty == 0 or buy_qty > sell_qty):
            net_buy = buy_qty - sell_qty

            # Check if this trade was ALREADY logged today (idempotency guard)
            already_logged = False
            if sym in existing_open and existing_open[sym]:
                for pos in existing_open[sym]:
                    pos_dt = pos.get("date")
                    pos_d = pos_dt.date() if isinstance(pos_dt, (datetime, date)) else None
                    if pos_d == today_dt.date():
                        already_logged = True
                        break

            if already_logged:
                print(f"ℹ️ Position for {sym} already recorded today. Skipping duplicate row.")
                continue

            max_trade_num += 1
            next_row = get_next_available_row(ws_tj)

            # Detect SL from pending orders or default to 1.5%
            sl_detected = find_pending_sl(sym, all_orders, buy_vwap)
            if not sl_detected:
                sl_detected = round(buy_vwap * 0.985, 2)  # default 1.5% risk

            tgt_detected = round(buy_vwap * 1.05, 2)  # 1:3.3 R:R planned

            ws_tj.cell(row=next_row, column=1, value=float(max_trade_num))
            ws_tj.cell(row=next_row, column=2, value=today_dt)
            ws_tj.cell(row=next_row, column=3, value=sym)
            ws_tj.cell(row=next_row, column=4, value="BUY")
            ws_tj.cell(row=next_row, column=5, value=buy_vwap)
            ws_tj.cell(row=next_row, column=6, value=sl_detected)
            ws_tj.cell(row=next_row, column=7, value=tgt_detected)
            ws_tj.cell(row=next_row, column=8, value=net_buy)
            ws_tj.cell(row=next_row, column=11, value="OPEN 🟢")
            ws_tj.cell(row=next_row, column=12, value=buy_vwap)

            risk_rs = round(abs(buy_vwap - sl_detected) * net_buy, 2)
            ws_tj.cell(row=next_row, column=16, value=risk_rs)

            opened_today.append({
                "symbol": sym,
                "qty": net_buy,
                "entry_p": buy_vwap,
                "sl": sl_detected,
                "risk_rs": risk_rs
            })
            existing_open.setdefault(sym, []).append({
                "row": next_row,
                "date": today_dt,
                "entry_price": buy_vwap,
                "sl": sl_detected,
                "target": tgt_detected,
                "qty": net_buy
            })
            print(f"🌟 NEW Position: {sym} | Bought {net_buy} @ ₹{buy_vwap:,.2f} | SL: ₹{sl_detected:,.2f} (Risk: ₹{risk_rs:,.2f})")

        # Case C: Intraday Roundtrip (Buy & Sell today)
        elif buy_qty > 0 and sell_qty > 0 and buy_qty == sell_qty:
            max_trade_num += 1
            next_row = get_next_available_row(ws_tj)
            realized_pnl = round((sell_vwap - buy_vwap) * buy_qty, 2)
            charges = calculate_charges(buy_vwap, sell_vwap, buy_qty, stt_rate=0.025)
            net_pnl = round(realized_pnl - charges, 2)
            pnl_pct = round((realized_pnl / (buy_vwap * buy_qty)) * 100.0, 2)

            ws_tj.cell(row=next_row, column=1, value=float(max_trade_num))
            ws_tj.cell(row=next_row, column=2, value=today_dt)
            ws_tj.cell(row=next_row, column=3, value=sym)
            ws_tj.cell(row=next_row, column=4, value="BUY")
            ws_tj.cell(row=next_row, column=5, value=buy_vwap)
            ws_tj.cell(row=next_row, column=8, value=buy_qty)
            ws_tj.cell(row=next_row, column=9, value=sell_vwap)
            ws_tj.cell(row=next_row, column=10, value=today_dt)
            ws_tj.cell(row=next_row, column=11, value="CLOSED")
            ws_tj.cell(row=next_row, column=13, value=0.0)
            ws_tj.cell(row=next_row, column=14, value=realized_pnl)
            ws_tj.cell(row=next_row, column=15, value=pnl_pct)
            ws_tj.cell(row=next_row, column=19, value=0)
            ws_tj.cell(row=next_row, column=20, value=charges)
            ws_tj.cell(row=next_row, column=21, value=net_pnl)
            ws_tj.cell(row=next_row, column=24, value="Intraday 3m ORB")

            closed_today.append({
                "symbol": sym,
                "qty": buy_qty,
                "entry_p": buy_vwap,
                "exit_p": sell_vwap,
                "net_pnl": net_pnl,
                "pnl_pct": pnl_pct,
                "r_mult": None
            })
            print(f"⚡ INTRADAY Trade: {sym} | Bought & Sold {buy_qty} | Net P&L: ₹{net_pnl:+,.2f} ({pnl_pct:+.1f}%)")

    # =========================================================================
    # AUTO-RECONCILE CARRIED-FORWARD LIVE POSITIONS MISSING IN JOURNAL
    # =========================================================================
    if live_positions:
        print("\n--- Auto-Reconciling Live Open Positions from Brokers ---")
        for p in live_positions:
            p_sym = str(p.get("symbol", "")).strip().upper()
            net_qty = float(p.get("qty", 0) or 0)
            buy_avg = float(p.get("avg_price", 0) or 0)
            broker = str(p.get("broker", "UNKNOWN")).upper()
            prod = str(p.get("product", "MTF")).upper()

            if net_qty > 0 and buy_avg > 0 and p_sym:
                if any(c["symbol"].upper() == p_sym for c in closed_today):
                    continue  # Do not re-open a stock that was closed today!
                if p_sym not in existing_open or not existing_open[p_sym]:
                    initial_sl = None
                    try:
                        from order_engine import get_open_trades_from_logs
                        log_meta = get_open_trades_from_logs().get(p_sym, {})
                        if log_meta.get("stop_loss"):
                            initial_sl = float(log_meta["stop_loss"])
                    except Exception:
                        pass

                    if not initial_sl or initial_sl <= 0:
                        if "CE" in p_sym or "PE" in p_sym or "NIFTY" in p_sym:
                            initial_sl = round(buy_avg * 0.70, 2)
                        else:
                            initial_sl = round(buy_avg * 0.975, 2)

                    target_p = round(buy_avg + abs(buy_avg - initial_sl) * 2.0, 2)
                    max_trade_num += 1
                    next_row = get_next_available_row(ws_tj)

                    ws_tj.cell(row=next_row, column=1, value=float(max_trade_num))
                    ws_tj.cell(row=next_row, column=2, value=today_dt)
                    ws_tj.cell(row=next_row, column=3, value=p_sym)
                    ws_tj.cell(row=next_row, column=4, value="BUY")
                    ws_tj.cell(row=next_row, column=5, value=buy_avg)
                    ws_tj.cell(row=next_row, column=6, value=initial_sl)
                    ws_tj.cell(row=next_row, column=7, value=target_p)
                    ws_tj.cell(row=next_row, column=8, value=net_qty)
                    ws_tj.cell(row=next_row, column=11, value="OPEN 🟢")
                    ws_tj.cell(row=next_row, column=12, value=buy_avg)
                    ws_tj.cell(row=next_row, column=22, value=f"Live sync from {broker} ({prod})")

                    risk_rs = round(abs(buy_avg - initial_sl) * net_qty, 2)
                    ws_tj.cell(row=next_row, column=16, value=risk_rs)

                    existing_open.setdefault(p_sym, []).append({
                        "row": next_row,
                        "date": today_dt,
                        "entry_price": buy_avg,
                        "sl": initial_sl,
                        "target": target_p,
                        "qty": net_qty
                    })

                    opened_today.append({
                        "symbol": p_sym,
                        "qty": net_qty,
                        "entry_p": buy_avg,
                        "sl": initial_sl,
                        "risk_rs": risk_rs
                    })
                    print(f"📥 AUTO-JOURNALED Live Position: {p_sym} | {net_qty} shs @ ₹{buy_avg:,.2f} on {broker} ({prod})")

    # =========================================================================
    # REFRESH OPEN POSITIONS & LIVE LTP
    # =========================================================================
    print("\n--- Refreshing Open Positions Sheet & Real-Time LTP ---")
    active_open_trades = []
    seen_symbols = set()
    closed_symbols_today = set(c["symbol"].upper() for c in closed_today)
    live_open_symbols = set(str(p.get("symbol", "")).strip().upper() for p in live_positions if float(p.get("qty", 0) or 0) > 0) if live_positions is not None else None

    for r in range(2, ws_tj.max_row + 1):
        status = ws_tj.cell(row=r, column=11).value
        sym = ws_tj.cell(row=r, column=3).value
        if sym and status and "OPEN" in str(status).upper():
            sym_str = str(sym).strip().upper()

            # Guard 1: If symbol was closed today, mark row CLOSED and skip!
            if sym_str in closed_symbols_today:
                print(f"🧹 Reconciled ghost row {r} for closed symbol {sym_str} -> Marking CLOSED.")
                ws_tj.cell(row=r, column=11, value="CLOSED")
                continue

            # Guard 2: If live broker positions were queried and this symbol has 0 shares on all brokers, mark CLOSED!
            if live_open_symbols is not None and sym_str not in live_open_symbols:
                print(f"🧹 Reconciled ghost row {r} for {sym_str} (0 shares held on live brokers) -> Marking CLOSED.")
                ws_tj.cell(row=r, column=11, value="CLOSED")
                continue

            if sym_str in seen_symbols:
                print(f"🧹 Reconciled duplicate open row {r} for {sym_str} -> Marking CLOSED.")
                ws_tj.cell(row=r, column=11, value="CLOSED")
                continue
            seen_symbols.add(sym_str)
            side = ws_tj.cell(row=r, column=4).value or "BUY"
            entry_p = float(ws_tj.cell(row=r, column=5).value or 0)
            sl = float(ws_tj.cell(row=r, column=6).value or 0) if ws_tj.cell(row=r, column=6).value else None
            tgt = float(ws_tj.cell(row=r, column=7).value or 0) if ws_tj.cell(row=r, column=7).value else None
            qty = float(ws_tj.cell(row=r, column=8).value or 0)
            entry_dt = ws_tj.cell(row=r, column=2).value

            # Fetch live LTP
            ltp = fetch_live_ltp(sym_str)
            if not ltp:
                ltp = float(ws_tj.cell(row=r, column=12).value or entry_p)

            # Update Trade Journal LTP and Unrealized P&L
            unrealized_pnl = round((ltp - entry_p) * qty, 2)
            pnl_pct = round((unrealized_pnl / (entry_p * qty)) * 100.0, 2) if (entry_p * qty) > 0 else 0.0

            ws_tj.cell(row=r, column=12, value=ltp)
            ws_tj.cell(row=r, column=13, value=unrealized_pnl)
            ws_tj.cell(row=r, column=15, value=pnl_pct)

            # Holding Days
            h_days = 0
            if isinstance(entry_dt, datetime):
                h_days = max(0, (today_dt - entry_dt).days)
            elif isinstance(entry_dt, date):
                h_days = max(0, (date.today() - entry_dt).days)

            # Distance to SL & Target & Current R:R
            dist_sl = round(((ltp - sl) / ltp) * 100.0, 2) if sl and ltp > 0 else None
            dist_tgt = round(((tgt - ltp) / ltp) * 100.0, 2) if tgt and ltp > 0 else None
            risk_rs = round(abs(entry_p - sl) * qty, 2) if sl else None
            risk_per_share = abs(entry_p - sl) if (sl and sl > 0) else None
            current_rr = round((ltp - entry_p) / risk_per_share, 2) if (risk_per_share and risk_per_share > 0) else None

            # Update Trade Journal R-Multiple column with current live R:R
            if current_rr is not None:
                ws_tj.cell(row=r, column=17, value=f"{current_rr:+.2f}R")

            # Action Signal Logic
            action_sig = "✅ HOLD — On Track"
            if sl and ltp <= sl:
                action_sig = "🔴 EXIT NOW — SL HIT"
            elif tgt and ltp >= tgt:
                action_sig = "🟢 BOOK PROFIT — Target Hit"
            elif dist_sl is not None and dist_sl <= 1.0:
                action_sig = f"🟡 ALERT — Near SL ({dist_sl:.1f}% away)"
            elif dist_tgt is not None and dist_tgt <= 2.0:
                action_sig = "🔵 TRAIL SL — Near Target"
            elif current_rr is not None and current_rr >= 3.0:
                action_sig = "🟢 BOOK 50% — Let Rest Run"
            elif current_rr is not None and current_rr >= 2.0:
                action_sig = "🟢 TRAIL SL to Cost"
            elif risk_rs and unrealized_pnl >= (3 * risk_rs):
                action_sig = "🟢 BOOK 50% — Let Rest Run"
            elif risk_rs and unrealized_pnl >= (2 * risk_rs):
                action_sig = "🟢 TRAIL SL to Cost"

            active_open_trades.append({
                "symbol": sym_str,
                "type": side,
                "entry_price": entry_p,
                "sl": sl,
                "target": tgt,
                "qty": qty,
                "ltp": ltp,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
                "current_rr": current_rr,
                "dist_sl": dist_sl,
                "dist_tgt": dist_tgt,
                "risk_rs": risk_rs,
                "action_signal": action_sig,
                "entry_date": entry_dt,
                "holding_days": h_days
            })

    # Clear and rewrite Open Positions sheet with Current R:R column
    ws_op = wb["Open Positions"]
    headers_op = [
        "Symbol", "Type", "Entry Price", "Stop Loss", "Target", "Qty", "LTP",
        "Unrealized P&L", "P&L %", "Current R:R", "Dist. to SL %", "Dist. to Target %",
        "Risk (₹)", "Action Signal", "Entry Date", "Holding Days"
    ]
    for c_idx, h_text in enumerate(headers_op, 1):
        ws_op.cell(row=1, column=c_idx, value=h_text)

    # Clear all old data rows completely (rows 2 to 200)
    for r in range(2, max(ws_op.max_row + 1, 200)):
        for c in range(1, 20):
            ws_op.cell(row=r, column=c).value = None

    for idx, p in enumerate(active_open_trades, 2):
        rr_display = f"{p['current_rr']:+.2f}R" if p["current_rr"] is not None else "N/A"
        ws_op.cell(row=idx, column=1, value=p["symbol"])
        ws_op.cell(row=idx, column=2, value=p["type"])
        ws_op.cell(row=idx, column=3, value=p["entry_price"])
        ws_op.cell(row=idx, column=4, value=p["sl"])
        ws_op.cell(row=idx, column=5, value=p["target"])
        ws_op.cell(row=idx, column=6, value=p["qty"])
        ws_op.cell(row=idx, column=7, value=p["ltp"])
        ws_op.cell(row=idx, column=8, value=p["unrealized_pnl"])
        ws_op.cell(row=idx, column=9, value=p["pnl_pct"])
        ws_op.cell(row=idx, column=10, value=rr_display)
        ws_op.cell(row=idx, column=11, value=p["dist_sl"])
        ws_op.cell(row=idx, column=12, value=p["dist_tgt"])
        ws_op.cell(row=idx, column=13, value=p["risk_rs"])
        ws_op.cell(row=idx, column=14, value=p["action_signal"])
        ws_op.cell(row=idx, column=15, value=p["entry_date"])
        ws_op.cell(row=idx, column=16, value=p["holding_days"])
        print(f"  • {p['symbol']}: Qty {p['qty']:.0f} | Entry ₹{p['entry_price']:,.2f} | LTP ₹{p['ltp']:,.2f} | P&L: ₹{p['unrealized_pnl']:+,.2f} ({p['pnl_pct']:+.1f}% | {rr_display}) | {p['action_signal']}")

    # =========================================================================
    # RECALCULATE DASHBOARD METRICS
    # =========================================================================
    all_closed_net_pnls = []
    wins = []
    losses = []
    r_multiples = []

    for r in range(2, ws_tj.max_row + 1):
        status = ws_tj.cell(row=r, column=11).value
        sym = ws_tj.cell(row=r, column=3).value
        net_p = ws_tj.cell(row=r, column=21).value
        r_m = ws_tj.cell(row=r, column=17).value

        if sym and status and "CLOSED" in str(status).upper() and net_p is not None:
            val = float(net_p)
            all_closed_net_pnls.append(val)
            if val > 0:
                wins.append(val)
            elif val < 0:
                losses.append(val)
            if r_m is not None and isinstance(r_m, (int, float)):
                r_multiples.append(float(r_m))

    tot_trades = len(all_closed_net_pnls)
    tot_wins = len(wins)
    tot_losses = len(losses)
    win_rate = (tot_wins / tot_trades) if tot_trades > 0 else 0.0
    avg_win = (sum(wins) / tot_wins) if tot_wins > 0 else 0.0
    avg_loss = (sum(losses) / tot_losses) if tot_losses > 0 else 0.0
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    expectancy = (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss)
    profit_factor = (sum(wins) / abs(sum(losses))) if sum(losses) != 0 else (999.0 if sum(wins) > 0 else 0.0)
    largest_win = max(wins) if wins else 0.0
    largest_loss = min(losses) if losses else 0.0
    avg_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0
    tot_net_pnl = sum(all_closed_net_pnls)

    ws_dash = wb["Dashboard"]
    ws_dash.cell(row=4, column=2, value=float(tot_trades))
    ws_dash.cell(row=5, column=2, value=float(tot_wins))
    ws_dash.cell(row=6, column=2, value=float(tot_losses))
    ws_dash.cell(row=7, column=2, value=round(win_rate, 4))
    ws_dash.cell(row=8, column=2, value=f"₹{avg_win:,.2f}")
    ws_dash.cell(row=9, column=2, value=f"₹{abs(avg_loss):,.2f}")
    ws_dash.cell(row=10, column=2, value=round(wl_ratio, 2))
    ws_dash.cell(row=11, column=2, value=f"₹{expectancy:,.2f}")
    ws_dash.cell(row=12, column=2, value=round(profit_factor, 2))
    ws_dash.cell(row=15, column=2, value=f"₹{largest_win:,.2f}")
    ws_dash.cell(row=16, column=2, value=f"-₹{abs(largest_loss):,.2f}")
    ws_dash.cell(row=17, column=2, value=f"{avg_r:.2f}R")
    ws_dash.cell(row=18, column=2, value=f"₹{tot_net_pnl:,.2f}")

    # =========================================================================
    # RECALCULATE CALENDAR DAILY TOTALS
    # =========================================================================
    # Group closed net P&Ls by day for the current month
    pnl_by_day = {}
    curr_month_str = today_dt.strftime("%Y-%m")
    for r in range(2, ws_tj.max_row + 1):
        exit_dt = ws_tj.cell(row=r, column=10).value
        net_p = ws_tj.cell(row=r, column=21).value
        if exit_dt and net_p is not None:
            if isinstance(exit_dt, (datetime, date)):
                m_str = exit_dt.strftime("%Y-%m")
                d_num = exit_dt.day
                pnl_by_day[(m_str, d_num)] = pnl_by_day.get((m_str, d_num), 0.0) + float(net_p)

    ws_cal = wb["Calendar"]
    # Update current month calendar cells if matching
    for r in range(5, ws_cal.max_row, 2):
        for c in range(1, 8):
            day_cell_val = ws_cal.cell(row=r, column=c).value
            if day_cell_val and isinstance(day_cell_val, (int, float)):
                d_int = int(day_cell_val)
                pnl_val = pnl_by_day.get((curr_month_str, d_int), 0.0)
                if pnl_val != 0.0:
                    ws_cal.cell(row=r + 1, column=c, value=round(pnl_val, 2))

    # Update Config timestamp
    if "Config" in wb.sheetnames:
        wb["Config"].cell(row=12, column=2, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    wb.save(JOURNAL_FILE)
    print(f"\n💾 Successfully reconciled and saved {JOURNAL_FILE.name}!")

    return {
        "status": "success",
        "closed_today": closed_today,
        "opened_today": opened_today,
        "open_positions": active_open_trades,
        "total_trades": tot_trades,
        "win_rate": win_rate,
        "tot_net_pnl": tot_net_pnl,
        "expectancy": expectancy,
        "profit_factor": profit_factor
    }


# =============================================================================
# 5. TELEGRAM EOD REPORT CARD DISPATCH
# =============================================================================

def send_telegram_eod_card(summary: Dict[str, Any], config: Dict[str, Any]):
    """Sends rich EOD Summary Report to Telegram chat."""
    tg_cfg = config.get("telegram", {})
    if not tg_cfg.get("enabled", True):
        return

    bot_token = tg_cfg.get("bot_token", "").strip()
    chat_id = tg_cfg.get("chat_id", "").strip()
    if not bot_token or not chat_id:
        return

    now_str = datetime.now().strftime("%d %b %Y | %H:%M IST")
    closed = summary.get("closed_today", [])
    opened = summary.get("opened_today", [])
    open_pos = summary.get("open_positions", [])

    # Filter out any closed symbol from open positions to guarantee 0 contradictions
    closed_sym_set = set(c["symbol"].upper() for c in closed)
    open_pos = [p for p in open_pos if p["symbol"].upper() not in closed_sym_set]

    today_realized = sum(c["net_pnl"] for c in closed)
    tot_unrealized = sum(p["unrealized_pnl"] for p in open_pos)

    pnl_icon = "🟢" if today_realized >= 0 else "🔴"
    pnl_sign = "+" if today_realized >= 0 else ""

    lines = [
        f"📊 <b>JARVIS EOD TRADE JOURNAL — {now_str}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Today's Realized Net P&L:</b> {pnl_icon} <b>{pnl_sign}₹{today_realized:,.2f}</b>",
        ""
    ]

    # Closed trades section
    if closed:
        lines.append("🎯 <b>Trades Closed Today:</b>")
        for c in closed:
            c_icon = "🟢" if c["net_pnl"] >= 0 else "🔴"
            c_sign = "+" if c["net_pnl"] >= 0 else ""
            r_str = f" | {c['r_mult']:+.1f}R" if c.get("r_mult") is not None else ""
            lines.append(f"• <b>{c['symbol']}</b>: {c_icon} {c_sign}₹{c['net_pnl']:,.2f} ({c['pnl_pct']:+.1f}%{r_str})")
        lines.append("")

    # New opened trades section
    if opened:
        lines.append("🌟 <b>New Positions Entered:</b>")
        for o in opened:
            lines.append(f"• <b>{o['symbol']}</b>: Qty {o['qty']:.0f} @ ₹{o['entry_p']:,.2f} (SL: ₹{o['sl']:,.2f})")
        lines.append("")

    # Active Open Positions
    lines.append(f"📈 <b>Active Open Positions ({len(open_pos)}):</b>")
    for p in open_pos:
        u_icon = "🟢" if p["unrealized_pnl"] >= 0 else "🔴"
        u_sign = "+" if p["unrealized_pnl"] >= 0 else ""
        rr_str = f" | {p['current_rr']:+.1f}R" if p.get("current_rr") is not None else ""
        lines.append(f"• <b>{p['symbol']}</b>: {u_icon} {u_sign}₹{p['unrealized_pnl']:,.2f} ({p['pnl_pct']:+.1f}%{rr_str}) — {p['action_signal']}")

    lines.append(f"\n💼 <b>Total Unrealized P&L:</b> ₹{tot_unrealized:+,.2f}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🏆 <b>Overall Win Rate:</b> {summary.get('win_rate', 0)*100:.1f}% | <b>Profit Factor:</b> {summary.get('profit_factor', 0):.2f}")
    lines.append(f"📁 <i>Updated Journal saved to Journal.xlsx</i>")

    msg = "\n".join(lines)
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        r = requests.post(url, json=payload, timeout=6)
        if r.status_code == 200:
            print("📱 EOD Telegram Summary Report delivered successfully!")
    except Exception as e:
        print(f"⚠️ Telegram dispatch error: {e}")


# =============================================================================
# 6. MAIN CONTROLLER
# =============================================================================

def run_eod_sync():
    print("=" * 65)
    print("⚡ JARVIS EOD TRADE JOURNAL AUTOMATOR (ZERODHA + DHAN)")
    print("=" * 65)

    config = load_config()

    # 1. Create a safe backup before anything else
    backup_file = create_backup()
    if not backup_file:
        print("❌ Cannot proceed without a valid Journal.xlsx backup.")
        return

    # 2. Fetch Dhan trades & orders
    print("\n[1/3] Checking DhanHQ Broker Fills...")
    dhan_trades, dhan_orders, dhan_src = fetch_dhan_executions(config)
    print(f"      Source: {dhan_src} ({len(dhan_trades)} trades)")

    # 3. Fetch Zerodha Kite trades & orders
    print("\n[2/3] Checking Zerodha Kite Broker Fills...")
    kite_trades, kite_orders, kite_src = fetch_zerodha_executions(config)
    print(f"      Source: {kite_src} ({len(kite_trades)} trades)")

    all_fills = dhan_trades + kite_trades
    all_orders = dhan_orders + kite_orders

    if not all_fills:
        print("\nℹ️ No new executed trades detected today from Dhan or Zerodha.")
        print("   -> Tip: If you traded today, either update your tokens in config_credentials.json")
        print("      OR drop 'trades_kite.csv' / 'trades_dhan.csv' into this folder.")
        print("   -> Proceeding to refresh LTP and Action Signals for existing Open Positions...")

    # 3.5 Fetch live multi-broker open positions
    print("\n[3/4] Querying Live Broker Open Positions (Dhan + Zerodha + Upstox)...")
    try:
        from order_engine import fetch_all_positions
        live_pos, _, b_stat = fetch_all_positions()
        print(f"      Active live positions detected: {len(live_pos)}")
        for lp in live_pos:
            print(f"      • {lp['symbol']} [{lp['broker']} • {lp['product']}]: {lp['qty']} shs @ ₹{lp['avg_price']} (LTP: ₹{lp['ltp']})")
    except Exception as e:
        print(f"      ⚠️ Notice querying live positions: {e}")
        live_pos = []

    # 4. Aggregate & Reconcile
    print(f"\n[4/4] Reconciling fills and live positions with Journal.xlsx...")
    fills_by_sym = aggregate_fills_by_symbol(all_fills)
    summary = reconcile_journal(fills_by_sym, all_orders, live_positions=live_pos)

    # 5. Send Telegram Report
    if summary.get("status") == "success":
        send_telegram_eod_card(summary, config)

    print("\n" + "=" * 65)
    print("🎉 EOD JOURNAL SYNC COMPLETE!")
    print("=" * 65)


if __name__ == "__main__":
    run_eod_sync()
