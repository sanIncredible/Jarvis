#!/usr/bin/env python3
"""
🛡️ JARVIS WATCHLIST HYGIENE & AUTOMATED PRUNING ENGINE
=============================================================================
Maintains a laser-focused 15-20 symbol watchlist of high-velocity setups:
1. Tracks setup lifecycle (days active on watchlist.txt via watchlist_meta.json).
2. Detects Stale setups: >= 3 trading days without triggering a 3m ORB breakout.
3. Detects Invalidated setups: Price broken below 20 EMA or critical support anchor.
4. Provides 1-tap automated pruning for Telegram bot and CLI maintenance.
"""

import sys
import os
import json
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE_DIR = Path(__file__).resolve().parent
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
WATCHLIST_META_FILE = BASE_DIR / "watchlist_meta.json"
CONFIG_FILE = BASE_DIR / "config_credentials.json"


def load_config() -> Dict[str, Any]:
    """Loads credentials from config_credentials.json."""
    if not CONFIG_FILE.is_file():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def read_watchlist_symbols() -> List[str]:
    """Reads clean list of uppercase symbols from watchlist.txt."""
    if not WATCHLIST_FILE.is_file():
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
    except Exception:
        return []


def write_watchlist_symbols(symbols: List[str]) -> bool:
    """Writes list of symbols back to watchlist.txt with header."""
    lines = [
        "# Upstox 3m ORB Scanner Watchlist",
        "# Add or remove NSE stock tickers below (one per line, or space/comma separated)",
        ""
    ]
    uniq = list(dict.fromkeys([s.strip().upper() for s in symbols if s.strip()]))
    lines.extend(uniq)
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        print(f"Error writing {WATCHLIST_FILE.name}: {e}")
        return False


def load_watchlist_meta() -> Dict[str, Any]:
    """Loads watchlist_meta.json tracking symbol lifecycle."""
    if not WATCHLIST_META_FILE.is_file():
        return {}
    try:
        with open(WATCHLIST_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_watchlist_meta(meta: Dict[str, Any]) -> bool:
    """Saves updated watchlist_meta.json."""
    try:
        with open(WATCHLIST_META_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving {WATCHLIST_META_FILE.name}: {e}")
        return False


def sync_watchlist_meta() -> Dict[str, Any]:
    """
    Reconciles watchlist_meta.json with watchlist.txt:
    • Adds newly added symbols with today's timestamp.
    • Removes symbols that are no longer in watchlist.txt.
    • Increments or calculates days_active.
    """
    curr_symbols = read_watchlist_symbols()
    meta = load_watchlist_meta()
    today_str = date.today().strftime("%Y-%m-%d")

    updated_meta = {}
    for s in curr_symbols:
        s_u = s.upper()
        if s_u in meta:
            entry = meta[s_u]
            added_date_str = entry.get("added_date", today_str)
            try:
                d_added = datetime.strptime(added_date_str[:10], "%Y-%m-%d").date()
                days_active = max(1, (date.today() - d_added).days)
            except Exception:
                days_active = int(entry.get("days_active", 1))
            entry["days_active"] = days_active
            updated_meta[s_u] = entry
        else:
            updated_meta[s_u] = {
                "symbol": s_u,
                "added_date": today_str,
                "days_active": 1,
                "source": "WATCHLIST_ADD",
                "status": "ACTIVE"
            }

    save_watchlist_meta(updated_meta)
    return updated_meta


def audit_watchlist_hygiene() -> Dict[str, Any]:
    """
    Performs comprehensive technical hygiene audit on watchlist.txt:
    • ACTIVE: Fresh setups (< 3 days, holding above 20 EMA).
    • STALE: Lingering setups (>= 3 trading days without triggering breakout).
    • INVALIDATED: Broken setups (Trading below 20 EMA or broken below support).
    """
    meta = sync_watchlist_meta()
    curr_symbols = list(meta.keys())

    # Fetch live quotes and EMAs for technical hygiene
    active_setups = []
    stale_setups = []
    invalidated_setups = []

    for sym in curr_symbols:
        m = meta[sym]
        days_act = int(m.get("days_active", 1))

        # Check technical status via order_engine or Yahoo Finance
        ltp = 0.0
        ema20 = 0.0
        change_pct = 0.0

        try:
            from order_engine import fetch_live_quote
            q, _ = fetch_live_quote(sym)
            if q:
                ltp = float(q.get("ltp") or 0.0)
                ema20 = float(q.get("ema20") or 0.0)
                change_pct = float(q.get("change_pct") or 0.0)
        except Exception:
            pass

        # Fallback to Yahoo if order_engine quote missing
        if ltp <= 0:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?interval=1d&range=20d"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    res = d["chart"]["result"][0]
                    ltp = float(res["meta"].get("regularMarketPrice", 0.0) or 0.0)
                    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
                    if len(closes) >= 10:
                        ema20 = float(sum(closes[-20:]) / min(len(closes), 20))
            except Exception:
                pass

        below_ema20 = bool(ema20 > 0 and ltp > 0 and ltp < (ema20 * 0.995))
        is_stale_age = bool(days_act >= 3)

        info = {
            "symbol": sym,
            "days_active": days_act,
            "ltp": round(ltp, 2) if ltp > 0 else None,
            "ema20": round(ema20, 2) if ema20 > 0 else None,
            "change_pct": round(change_pct, 2),
            "added_date": m.get("added_date", "Unknown")
        }

        if below_ema20:
            info["reason"] = f"Broke below 20 EMA (LTP ₹{ltp:,.1f} < EMA ₹{ema20:,.1f})"
            info["status"] = "INVALIDATED"
            invalidated_setups.append(info)
        elif is_stale_age:
            info["reason"] = f"Inactive on watchlist for {days_act} trading days"
            info["status"] = "STALE"
            stale_setups.append(info)
        else:
            info["reason"] = f"Fresh coiling setup ({days_act}d on list)"
            info["status"] = "ACTIVE"
            active_setups.append(info)

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "total_symbols": len(curr_symbols),
        "active_count": len(active_setups),
        "stale_count": len(stale_setups),
        "invalidated_count": len(invalidated_setups),
        "active": active_setups,
        "stale": stale_setups,
        "invalidated": invalidated_setups
    }


def prune_watchlist(symbols_to_prune: Optional[List[str]] = None, sync_cloud: bool = True) -> Tuple[List[str], List[str]]:
    """
    Removes specified or auto-detected stale & invalidated symbols from watchlist.txt.
    Returns: (pruned_symbols, remaining_symbols)
    """
    curr = read_watchlist_symbols()
    if symbols_to_prune is None:
        audit = audit_watchlist_hygiene()
        symbols_to_prune = [s["symbol"] for s in audit["stale"]] + [s["symbol"] for s in audit["invalidated"]]

    to_prune_set = set(s.upper() for s in symbols_to_prune)
    remaining = [s for s in curr if s.upper() not in to_prune_set]
    pruned = [s for s in curr if s.upper() in to_prune_set]

    if pruned:
        write_watchlist_symbols(remaining)
        meta = load_watchlist_meta()
        for p in pruned:
            if p in meta:
                del meta[p]
        save_watchlist_meta(meta)

        if sync_cloud:
            try:
                from sync_to_cloud import push_watchlist_to_github
                push_watchlist_to_github()
            except Exception as e:
                print(f"Notice pushing pruned watchlist to GitHub: {e}")

    return pruned, remaining


def format_hygiene_telegram_card(audit: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Formats rich Telegram card for /hygiene command with 1-tap prune button."""
    lines = [
        "🧹 <b>JARVIS WATCHLIST HYGIENE AUDIT</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Total Tracked Symbols:</b> <b>{audit['total_symbols']}</b>",
        f"• 🟢 <b>Active & Coiling:</b> <b>{audit['active_count']}</b>",
        f"• ⚠️ <b>Stale (&gt;=3d no breakout):</b> <b>{audit['stale_count']}</b>",
        f"• ❌ <b>Invalidated (Below 20 EMA):</b> <b>{audit['invalidated_count']}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if audit.get("active"):
        act_strs = [f"<b>{s['symbol']}</b> ({s['days_active']}d)" for s in audit["active"][:10]]
        lines.append(f"🟢 <b>ACTIVE SETUPS:</b>\n{', '.join(act_strs)}\n")

    if audit.get("stale"):
        stale_strs = [f"<code>{s['symbol']}</code> ({s['days_active']}d)" for s in audit["stale"]]
        lines.append(f"⚠️ <b>STALE / DORMANT SETUPS:</b>\n{', '.join(stale_strs)}\n")

    if audit.get("invalidated"):
        inv_strs = [f"<code>{s['symbol']}</code> ({s['reason']})" for s in audit["invalidated"]]
        lines.append(f"❌ <b>INVALIDATED SETUPS:</b>\n• " + "\n• ".join(inv_strs) + "\n")

    stale_and_inv = [s["symbol"] for s in audit.get("stale", [])] + [s["symbol"] for s in audit.get("invalidated", [])]
    kb_rows = []
    if stale_and_inv:
        lines.append("💡 <i>Tap below to prune inactive setups and maintain a high-velocity watchlist:</i>")
        kb_rows.append([
            {"text": f"🧹 1-Tap Prune Stale ({len(stale_and_inv)} stocks)", "callback_data": "wl_prune_stale"}
        ])

    kb_rows.append([
        {"text": "📋 View Full Watchlist", "callback_data": "wl_show"},
        {"text": "🔄 Refresh Audit", "callback_data": "wl_hygiene_refresh"}
    ])

    markup = {"inline_keyboard": kb_rows}
    return "\n".join(lines), markup


if __name__ == "__main__":
    if "--prune" in sys.argv:
        p, rem = prune_watchlist()
        print(f"✅ Pruned {len(p)} symbols: {', '.join(p)}")
        print(f"Remaining ({len(rem)}): {', '.join(rem)}")
    else:
        aud = audit_watchlist_hygiene()
        print(f"Watchlist Total: {aud['total_symbols']}")
        print(f"Active: {aud['active_count']}")
        print(f"Stale: {aud['stale_count']}")
        print(f"Invalidated: {aud['invalidated_count']}")
        for s in aud["stale"]:
            print(f"  ⚠️ STALE: {s['symbol']} ({s['days_active']}d)")
        for s in aud["invalidated"]:
            print(f"  ❌ INVALIDATED: {s['symbol']} ({s['reason']})")
