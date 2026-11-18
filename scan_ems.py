#!/usr/bin/env python3
"""
scan_ems.py
===========
⚡ JARVIS CHIRAG KEDIA "EASY MONEY SCAN" (EMS) ENGINE
=====================================================
Fetches live momentum and market breadth data from Manas Arora's Breadth Ledger
(markets.manasarora.com / breadth-ledger.manas-arora.workers.dev)
and filters for Chirag Kedia's high-conviction "Easy Money" setups:

Filtering Rules:
1. 1-Week Price Change   >= 20%  (5 trading days)
   OR
2. 1-Month Price Change  >= 25%  (20-30 trading days)
   OR
3. 1-Quarter Price Change >= 35% (60-90 trading days)
   OR
4. 6-Month Price Change  >= 50%  (125 trading days)

Multi-Tier Momentum Architecture:
- TIER 1 [🔥 MULTI-TIMEFRAME THRUST] : Triggers 2 or more timeframe hurdles simultaneously (e.g. 1M + 6M).
- TIER 2 [🚀 SHORT-TERM IGNITION]   : Fresh 1-Week (>=20%) or 1-Month (>=25%) burst.
- TIER 3 [📦 STRUCTURAL RUNNERS]    : Sustained 1-Quarter (>=35%) or 6-Month (>=50%) trend leader.
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import ssl
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
LEDGER_DATA_URL = "https://breadth-ledger.manas-arora.workers.dev/data.json"
LEDGER_SNAP_URL = "https://breadth-ledger.manas-arora.workers.dev/data-snapshot.json"
OUT_EMS_JSON = BASE_DIR / "candidates_ems.json"
OUT_EMS_TXT = BASE_DIR / "candidates_ems.txt"

IST = timezone(timedelta(hours=5, minutes=30))

# ── Sector mapping (matches candidate_scanner.py) ──────────────────────────
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
    "Media": "Nifty Media",
}

# Short display name from Nifty index name
_SECTOR_DISPLAY = {
    "Nifty Auto": "Auto",
    "Nifty Pharma": "Pharma",
    "Nifty IT": "IT",
    "Nifty Metal": "Metal",
    "Nifty Realty": "Realty",
    "Nifty Bank": "Bank",
    "Nifty Energy": "Energy",
    "Nifty FMCG": "FMCG",
    "Nifty Infra": "Infra",
    "Nifty Media": "Media",
}


def get_ist_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_ledger_data() -> Dict[str, Any]:
    """Fetches real-time JSON payload from Manas Arora's Cloudflare Worker."""
    ctx = ssl.create_default_context()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    for url in [LEDGER_DATA_URL, LEDGER_SNAP_URL]:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    data = json.loads(raw)
                    if data and "momo" in data:
                        return data
        except Exception as e:
            print(f"Warning: Failed to fetch from {url}: {e}", file=sys.stderr)

    # Local fallback cache if available
    local_cache = BASE_DIR / "ledger_cache.json"
    if local_cache.is_file():
        try:
            with open(local_cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {}


def scan_ems_candidates() -> Dict[str, Any]:
    """
    Executes Chirag Kedia's Easy Money Scan across the entire Ledger universe.
    Returns structured candidate payload grouped into Tier 1, 2, and 3.
    """
    data = fetch_ledger_data()
    if not data or "momo" not in data:
        print("Error: Could not retrieve Ledger momo data.", file=sys.stderr)
        return {}

    # Save local cache
    try:
        with open(BASE_DIR / "ledger_cache.json", "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

    momo = data.get("momo", {})
    lb = momo.get("lb", [5, 10, 20, 30, 60, 90, 125, 180, 250])
    th = momo.get("th", [10, 15, 20, 25, 30, 40, 50, 75, 100])

    # Map lookback index
    # lb[0]=5, lb[1]=10, lb[2]=20, lb[3]=30, lb[4]=60, lb[5]=90, lb[6]=125, lb[7]=180, lb[8]=250
    # th: 10(k=1), 15(k=2), 20(k=3), 25(k=4), 30(k=5), 40(k=6), 50(k=7), 75(k=8), 100(k=9)

    near_map = {row[0]: row[1] for row in data.get("near", []) if len(row) >= 2}
    rs_map = {row[0]: row[1] for row in data.get("rs", {}).get("rows", []) if len(row) >= 2}

    candidates = []
    seen = set()

    for g in momo.get("groups", []):
        ind = g.get("industry", "Equity")
        for sym, mask in g.get("stocks", []):
            if sym in seen or not mask or len(mask) < 7:
                continue

            m5 = int(mask[0]) if mask[0] != '-' else 0
            m20 = int(mask[2]) if mask[2] != '-' else 0
            m30 = int(mask[3]) if mask[3] != '-' else 0
            m60 = int(mask[4]) if mask[4] != '-' else 0
            m90 = int(mask[5]) if mask[5] != '-' else 0
            m125 = int(mask[6]) if mask[6] != '-' else 0

            triggers = []
            trigger_badges = []

            # 1. 1-Week >= 20% (lb 5, th >= 20% -> k >= 3)
            if m5 >= 3:
                val = th[m5 - 1] if m5 <= len(th) else 20
                triggers.append(f"1W ≥ {val}%")
                trigger_badges.append(f"⚡ 1W +{val}%")

            # 2. 1-Month >= 25% (lb 20 or 30, th >= 25% -> k >= 4)
            best_1m = max(m20, m30)
            if best_1m >= 4:
                val = th[best_1m - 1] if best_1m <= len(th) else 25
                triggers.append(f"1M ≥ {val}%")
                trigger_badges.append(f"🚀 1M +{val}%")

            # 3. 1-Quarter >= 35% (lb 60 or 90, th >= 30% -> k >= 5, or >=40% k >= 6)
            best_1q = max(m60, m90)
            if best_1q >= 5:  # 30% or 40%+
                val = th[best_1q - 1] if best_1q <= len(th) else 35
                triggers.append(f"1Q ≥ {val}%")
                trigger_badges.append(f"🎯 1Q +{val}%")

            # 4. 6-Month >= 50% (lb 125, th >= 50% -> k >= 7)
            if m125 >= 7:
                val = th[m125 - 1] if m125 <= len(th) else 50
                triggers.append(f"6M ≥ {val}%")
                trigger_badges.append(f"💎 6M +{val}%")

            if not triggers:
                continue

            seen.add(sym)

            dist_val = near_map.get(sym)
            rs_val = rs_map.get(sym, 0)

            # ── Risk filter: reject stocks extended >25% below 52W high ──
            if dist_val is not None and dist_val < -25:
                continue

            # Classify into 3 Tiers
            num_trig = len(triggers)
            has_short = any("1W" in t or "1M" in t for t in triggers)
            has_long = any("1Q" in t or "6M" in t for t in triggers)

            if num_trig >= 2:
                tier_code = "TIER_1_MULTI"
                tier_label = "TIER 1: 🔥 MULTI-TIMEFRAME THRUST (2+ Triggers)"
                tier_order = 1
            elif has_short:
                tier_code = "TIER_2_SHORT"
                tier_label = "TIER 2: 🚀 SHORT-TERM MOMENTUM BURST (1W / 1M)"
                tier_order = 2
            else:
                tier_code = "TIER_3_STRUCT"
                tier_label = "TIER 3: 📦 STRUCTURAL TREND LEADERS (1Q / 6M)"
                tier_order = 3

            # ── Sector tag ───────────────────────────────────────────
            mapped_sector = INDUSTRY_TO_SECTOR.get(ind)
            if mapped_sector:
                sector_display = _SECTOR_DISPLAY.get(mapped_sector, mapped_sector)
                sector_tag = f"🏢 {sector_display}"
                sector_score = 5.0
            else:
                sector_tag = f"🏢 {ind}"
                sector_score = 3.0

            # ── Volume proxy from RS rating ──────────────────────────
            rs_int = int(rs_val) if rs_val else 0
            if rs_int >= 90:
                volume_score = 15.0
            elif rs_int >= 80:
                volume_score = 10.0
            elif rs_int >= 70:
                volume_score = 5.0
            else:
                volume_score = 0.0

            # ── Unified scoring ──────────────────────────────────────
            tier_score = {1: 30, 2: 20, 3: 10}.get(tier_order, 0)
            momentum_score = num_trig * 10
            total_score = tier_score + volume_score + momentum_score + sector_score

            candidates.append({
                "symbol": sym,
                "industry": ind,
                "sector_tag": sector_tag,
                "tier": tier_code,
                "tier_label": tier_label,
                "tier_order": tier_order,
                "triggers": triggers,
                "trigger_badges": trigger_badges,
                "triggers_count": num_trig,
                "dist_52w_pct": round(dist_val, 1) if dist_val is not None else None,
                "rs_rating": rs_int,
                "volume_score": volume_score,
                "momentum_score": momentum_score,
                "sector_score": sector_score,
                "tier_score": tier_score,
                "total_score": total_score,
                "m5": m5,
                "m20": m20,
                "m30": m30,
                "m60": m60,
                "m125": m125
            })

    # Sort candidates by:
    # 1. Tier order (1, 2, 3)
    # 2. Number of triggers descending (e.g. 4, 3, 2, 1)
    # 3. RS rating descending (99 -> 1)
    # 4. Proximity to 52W high (dist_52w_pct closest to 0)
    candidates.sort(key=lambda x: (
        x["tier_order"],
        -x["total_score"],
        -x["triggers_count"],
        -(x["rs_rating"] or 0),
        -(x["dist_52w_pct"] if x["dist_52w_pct"] is not None else -999)
    ))

    t1 = [c for c in candidates if c["tier_order"] == 1]
    t2 = [c for c in candidates if c["tier_order"] == 2]
    t3 = [c for c in candidates if c["tier_order"] == 3]

    now_ist = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    summary = {
        "as_of": now_ist,
        "source": "Manas Arora Breadth Ledger (markets.manasarora.com)",
        "scan_name": "Chirag Kedia Easy Money Scan (EMS)",
        "rules": [
            "1-Week Price Change >= 20%",
            "1-Month Price Change >= 25%",
            "1-Quarter Price Change >= 35%",
            "6-Month Price Change >= 50%"
        ],
        "universe_count": data.get("universe", 994),
        "total_ems_candidates": len(candidates),
        "tier1_count": len(t1),
        "tier2_count": len(t2),
        "tier3_count": len(t3),
        "tier1_candidates": t1,
        "tier2_candidates": t2,
        "tier3_candidates": t3,
        "all_candidates": candidates
    }

    # Save to JSON
    with open(OUT_EMS_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Save to TXT
    lines = [
        f"# JARVIS CHIRAG KEDIA EASY MONEY SCAN (EMS) CANDIDATES — {now_ist}",
        f"# Rules: 1W >= 20% | 1M >= 25% | 1Q >= 35% | 6M >= 50%",
        f"# Total Unique EMS Candidates: {len(candidates)} (Tier 1: {len(t1)}, Tier 2: {len(t2)}, Tier 3: {len(t3)})",
        "",
        "## TIER 1: MULTI-TIMEFRAME THRUST (2+ Triggers)"
    ]
    for c in t1:
        d_str = f"{c['dist_52w_pct']:+.1f}% 52W" if c['dist_52w_pct'] is not None else "N/A"
        lines.append(f"{c['symbol']:<14} | RS:{c['rs_rating']:<3} | {d_str:<10} | {c['industry']:<25} | {', '.join(c['triggers'])}")

    lines.extend(["", "## TIER 2: SHORT-TERM MOMENTUM (1W / 1M)"])
    for c in t2:
        d_str = f"{c['dist_52w_pct']:+.1f}% 52W" if c['dist_52w_pct'] is not None else "N/A"
        lines.append(f"{c['symbol']:<14} | RS:{c['rs_rating']:<3} | {d_str:<10} | {c['industry']:<25} | {', '.join(c['triggers'])}")

    lines.extend(["", "## TIER 3: STRUCTURAL RUNNERS (1Q / 6M)"])
    for c in t3:
        d_str = f"{c['dist_52w_pct']:+.1f}% 52W" if c['dist_52w_pct'] is not None else "N/A"
        lines.append(f"{c['symbol']:<14} | RS:{c['rs_rating']:<3} | {d_str:<10} | {c['industry']:<25} | {', '.join(c['triggers'])}")

    with open(OUT_EMS_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return summary


def format_ems_telegram_card(summary: Dict[str, Any]) -> tuple:
    """Formats an executive Telegram briefing for /ems command with 1-tap add buttons."""
    total = summary.get("total_ems_candidates", 0)
    t1 = summary.get("tier1_candidates", [])
    t2 = summary.get("tier2_candidates", [])
    t3 = summary.get("tier3_candidates", [])

    lines = [
        "⚡ <b>CHIRAG KEDIA EASY MONEY SCAN (EMS)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>As Of:</b> {summary.get('as_of', 'Latest')}",
        f"🎯 <b>Total Unique EMS Setups:</b> <b>{total}</b>",
        f"🔥 <b>Tier 1 (Multi-TF):</b> {len(t1)} • 🚀 <b>Tier 2 (Short):</b> {len(t2)} • 📦 <b>Tier 3:</b> {len(t3)}",
        "💡 <i>Criteria: 1W ≥20% OR 1M ≥25% OR 1Q ≥35% OR 6M ≥50%</i>",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if t1:
        lines.append("🔥 <b>TIER 1: MULTI-TIMEFRAME THRUST (Top 8):</b>")
        for idx, c in enumerate(t1[:8], 1):
            d_str = f"<code>{c['dist_52w_pct']:+.1f}%</code> 52W" if c['dist_52w_pct'] is not None else ""
            rs_str = f"RS:<b>{c['rs_rating']}</b>" if c['rs_rating'] else ""
            trigs = " + ".join(c['trigger_badges'])
            lines.append(f"  {idx}. <b>{c['symbol']}</b> ({rs_str} {d_str})\n     └ {trigs} • <i>{c['industry']}</i>")

    if t2:
        lines.append("\n🚀 <b>TIER 2: SHORT-TERM MOMO BURST:</b>")
        for idx, c in enumerate(t2[:5], 1):
            d_str = f"<code>{c['dist_52w_pct']:+.1f}%</code>" if c['dist_52w_pct'] is not None else ""
            trigs = " + ".join(c['trigger_badges'])
            lines.append(f"  • <b>{c['symbol']}</b> ({d_str}) — {trigs} • <i>{c['industry']}</i>")

    lines.append("\n👉 <i>Tap any stock below to add to your live Watchlist:</i>")

    # Generate inline buttons for Top Tier 1 & Tier 2 stocks
    btn_stocks = [c["symbol"] for c in t1[:9]] + [c["symbol"] for c in t2[:3]]
    # Dedup while preserving order
    seen_b = set()
    uniq_btns = []
    for s in btn_stocks:
        if s not in seen_b:
            seen_b.add(s)
            uniq_btns.append(s)

    kb_rows = []
    for i in range(0, len(uniq_btns), 3):
        chunk = uniq_btns[i:i+3]
        kb_rows.append([{"text": f"+ {s}", "callback_data": f"cand_add:{s}"} for s in chunk])

    reply_markup = {"inline_keyboard": kb_rows} if kb_rows else None
    return "\n".join(lines), reply_markup


def send_telegram_ems_notification(summary: Dict[str, Any]):
    """Sends EOD EMS alert to Telegram."""
    cfg = load_config()
    tg_cfg = cfg.get("telegram", {})
    bot_token = tg_cfg.get("bot_token", "").strip()
    chat_id = tg_cfg.get("chat_id", "").strip()
    if not bot_token or not chat_id:
        return

    text, markup = format_ems_telegram_card(summary)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if markup:
        payload["reply_markup"] = markup

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
        print(f"Failed to send EMS telegram alert: {e}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan Chirag Kedia Easy Money Scan (EMS) candidates")
    parser.add_argument("--notify", action="store_true", help="Send Telegram card alert")
    args = parser.parse_args()

    print("⚡ [JARVIS EMS] Fetching Breadth Ledger data and scanning Chirag Kedia EMS...")
    summary = scan_ems_candidates()
    total = summary.get("total_ems_candidates", 0)
    print(f"✅ Discovered {total} Unique EMS stocks ({summary.get('tier1_count', 0)} Tier 1 Multi-TF, {summary.get('tier2_count', 0)} Tier 2 Short, {summary.get('tier3_count', 0)} Tier 3 Structural).")

    if args.notify:
        send_telegram_ems_notification(summary)
        print("📲 Dispatched Telegram EMS briefing.")

    try:
        from enrich_candidates import main as enrich_main
        enrich_main()
    except Exception as e:
        print(f"ℹ️ Auto-enrichment notice: {e}")
