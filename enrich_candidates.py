#!/usr/bin/env python3
"""
enrich_candidates.py
====================
Post-processing script that merges, deduplicates, and scores candidates
from all four scanning engines:
  1. candidates.json          – EOD swing candidates
  2. candidates_90d_nr.json   – 90-day NR candidates
  3. candidates_nifty_ipo.json– IPO candidates
  4. candidates_ems.json       – Easy Money Scan (EMS)

Writes:
  • candidates_merged.json  – unified deduplicated JSON
  • candidates_merged.txt   – human-readable summary

No external dependencies. Uses only stdlib + pathlib.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

SOURCE_FILES = {
    "eod":  BASE_DIR / "candidates.json",
    "nr90": BASE_DIR / "candidates_90d_nr.json",
    "ipo":  BASE_DIR / "candidates_nifty_ipo.json",
    "ems":  BASE_DIR / "candidates_ems.json",
}

OUT_JSON = BASE_DIR / "candidates_merged.json"
OUT_TXT  = BASE_DIR / "candidates_merged.txt"

IST = timezone(timedelta(hours=5, minutes=30))

# ── Tier score defaults ──────────────────────────────────────────────────────
TIER_SCORE_MAP = {1: 30.0, 2: 20.0, 3: 10.0}


def get_ist_now() -> str:
    return datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")


# ── Loaders ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file; return empty dict on failure."""
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠ Failed to load {path.name}: {e}", file=sys.stderr)
        return {}


def load_eod(path: Path) -> List[Dict[str, Any]]:
    """EOD: has 'candidates' array."""
    data = _load_json(path)
    raw = data.get("candidates", [])
    out = []
    for r in raw:
        entry = dict(r)
        entry["_source"] = "eod"
        # Normalize tier_order: EOD uses tier (TIER 1A, TIER 1B, TIER 1C, TIER 2, TIER 3, SECTORAL PICKS)
        tier_str = str(entry.get("tier", "")).upper()
        if "TIER 1" in tier_str or "SECTORAL" in tier_str or "DOORSTEP" in tier_str:
            entry["tier_order"] = 1
        elif "TIER 2" in tier_str or "LAUNCHPAD" in tier_str:
            entry["tier_order"] = 2
        else:
            entry["tier_order"] = 3
        # Normalize total_score: EOD uses 'score'
        if "total_score" not in entry:
            entry["total_score"] = float(entry.get("score", 0) or 0)
        out.append(entry)
    return out


def load_tiered(path: Path, source: str) -> List[Dict[str, Any]]:
    """NR90, IPO, EMS: have tier1_candidates / tier2_candidates / tier3_candidates."""
    data = _load_json(path)
    out = []
    for tier_key, tier_order in [("tier1_candidates", 1), ("tier2_candidates", 2), ("tier3_candidates", 3)]:
        for r in data.get(tier_key, []):
            entry = dict(r)
            entry["_source"] = source
            # Ensure tier_order is set
            if "tier_order" not in entry:
                entry["tier_order"] = tier_order
            # Normalize total_score
            if "total_score" not in entry:
                # NR90/IPO use 'priority_score', fall back to tier-based default
                score = entry.get("priority_score") or entry.get("score")
                if score is not None:
                    entry["total_score"] = float(score)
                else:
                    entry["total_score"] = TIER_SCORE_MAP.get(tier_order, 0.0)
            out.append(entry)
    return out


# ── Merge & deduplicate ─────────────────────────────────────────────────────

def merge_candidates() -> Dict[str, Any]:
    """Load all sources, deduplicate by symbol, apply cross-list bonus."""
    all_entries: List[Dict[str, Any]] = []

    # 1. Load all sources
    eod_list = load_eod(SOURCE_FILES["eod"])
    nr90_list = load_tiered(SOURCE_FILES["nr90"], "nr90")
    ipo_list = load_tiered(SOURCE_FILES["ipo"], "ipo")
    ems_list = load_tiered(SOURCE_FILES["ems"], "ems")

    all_entries.extend(eod_list)
    all_entries.extend(nr90_list)
    all_entries.extend(ipo_list)
    all_entries.extend(ems_list)

    source_counts = {
        "eod": len(eod_list),
        "nr90": len(nr90_list),
        "ipo": len(ipo_list),
        "ems": len(ems_list),
    }

    # 2. Group by symbol (uppercase)
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for entry in all_entries:
        sym = (entry.get("symbol") or entry.get("SYMBOL") or "").upper().strip()
        if not sym:
            continue
        entry["symbol"] = sym  # normalize
        by_symbol.setdefault(sym, []).append(entry)

    # 3. Deduplicate: keep best entry per symbol, merge sources
    merged: List[Dict[str, Any]] = []
    cross_list_count = 0

    for sym, entries in by_symbol.items():
        # Collect all source tags
        sources = sorted(set(e["_source"] for e in entries))
        # Pick the entry with highest total_score
        best = max(entries, key=lambda e: float(e.get("total_score", 0)))
        best = dict(best)  # copy to avoid mutation

        # Merge sources list
        best["source"] = best.pop("_source", sources[0])
        best["sources"] = sources

        # Cross-list bonus: +10 per additional list appearance
        num_lists = len(sources)
        cross_list_bonus = max(0, (num_lists - 1)) * 10.0
        if cross_list_bonus > 0:
            cross_list_count += 1
            best["cross_list_bonus"] = cross_list_bonus
            best["total_score"] = float(best.get("total_score", 0)) + cross_list_bonus
        else:
            best["cross_list_bonus"] = 0.0

        # Carry through all original fields; remove internal keys
        for key in list(best.keys()):
            if key.startswith("_"):
                del best[key]

        merged.append(best)

    # 4. Sort by total_score descending
    merged.sort(key=lambda x: -float(x.get("total_score", 0)))

    now_str = get_ist_now()
    payload = {
        "as_of": now_str,
        "total_unique": len(merged),
        "cross_list_count": cross_list_count,
        "source_counts": source_counts,
        "candidates": merged,
    }

    return payload


# ── Writers ──────────────────────────────────────────────────────────────────

def write_json(payload: Dict[str, Any]) -> None:
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    print(f"📄 Written: {OUT_JSON}")


def write_txt(payload: Dict[str, Any]) -> None:
    cands = payload.get("candidates", [])
    lines = [
        f"# JARVIS MERGED CANDIDATE UNIVERSE — {payload.get('as_of', '')}",
        f"# Total Unique Symbols: {payload.get('total_unique', 0)}",
        f"# Cross-List Appearances: {payload.get('cross_list_count', 0)}",
        f"# Sources: {payload.get('source_counts', {})}",
        "",
        f"{'#':<4} {'SYMBOL':<14} {'SCORE':>7} {'TIER':>4} {'SOURCES':<20} {'BONUS':>6} {'INDUSTRY':<30}",
        f"{'─'*4} {'─'*14} {'─'*7} {'─'*4} {'─'*20} {'─'*6} {'─'*30}",
    ]
    for idx, c in enumerate(cands, 1):
        sym = c.get("symbol", "?")
        score = float(c.get("total_score", 0))
        tier = c.get("tier_order", "?")
        sources = ",".join(c.get("sources", [c.get("source", "?")]))
        bonus = float(c.get("cross_list_bonus", 0))
        industry = c.get("industry", "") or ""
        bonus_str = f"+{bonus:.0f}" if bonus > 0 else ""
        lines.append(f"{idx:<4} {sym:<14} {score:>7.1f} {str(tier):>4} {sources:<20} {bonus_str:>6} {industry:<30}")

    # Summary footer
    lines.extend([
        "",
        f"# Top 10 by Score:",
    ])
    for idx, c in enumerate(cands[:10], 1):
        sym = c.get("symbol", "?")
        score = float(c.get("total_score", 0))
        sources = ",".join(c.get("sources", []))
        lines.append(f"  {idx:>2}. {sym:<14} {score:>7.1f}  ({sources})")

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"📝 Written: {OUT_TXT}")


def format_merged_telegram_card(payload: Dict[str, Any], max_display: int = 10) -> tuple:
    """Formats an executive Telegram card for /merged or /confluence with 1-tap add buttons."""
    cands = payload.get("candidates", [])
    total = payload.get("total_unique", len(cands))
    cross = payload.get("cross_list_count", 0)
    sc = payload.get("source_counts", {})

    lines = [
        "🏆 <b>JARVIS UNIFIED CANDIDATE CONFLUENCE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>As Of:</b> {payload.get('as_of', 'Latest')}",
        f"🎯 <b>Total Unique Candidates:</b> <b>{total}</b>",
        f"🔗 <b>Multi-List Confluence Setups:</b> <b>{cross}</b>",
        f"📋 <i>Sources: EOD ({sc.get('eod', 0)}) • MOMO ({sc.get('nr90', 0)}) • IPO ({sc.get('ipo', 0)}) • EMS ({sc.get('ems', 0)})</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🔥 <b>TOP RANKED CONFLUENCE SETUPS:</b>"
    ]

    for idx, c in enumerate(cands[:max_display], 1):
        sym = c.get("symbol", "")
        score = float(c.get("total_score", 0))
        sources_list = [s.upper() for s in c.get("sources", [c.get("source", "")])]
        src_str = " + ".join(sources_list)
        ind = c.get("industry", "") or ""
        bonus = float(c.get("cross_list_bonus", 0))
        bonus_badge = f" [⚡+{int(bonus)} Confluence]" if bonus > 0 else ""
        tier = c.get("tier") or c.get("tier_label") or f"Tier {c.get('tier_order', 1)}"
        dist = c.get("dist_52w_pct")
        dist_str = f" • 52W: <code>{dist:+.1f}%</code>" if dist is not None else ""
        lines.append(
            f"<b>{idx}. {sym}</b> — Score: <b>{score:.1f}</b>{bonus_badge}\n"
            f"   └ <i>{src_str}</i> | {tier}{dist_str} | {ind}"
        )

    lines.append("\n👉 <i>Tap any stock below to promote to your live Watchlist:</i>")

    # Generate inline buttons for Top 8 candidates
    btn_stocks = [c["symbol"] for c in cands[:9]]
    seen_b = set()
    uniq_btns = []
    for s in btn_stocks:
        if s and s not in seen_b:
            seen_b.add(s)
            uniq_btns.append(s)

    kb_rows = []
    for i in range(0, len(uniq_btns), 3):
        chunk = uniq_btns[i:i+3]
        kb_rows.append([{"text": f"+ {s}", "callback_data": f"cand_add:{s}"} for s in chunk])

    reply_markup = {"inline_keyboard": kb_rows} if kb_rows else None
    return "\n".join(lines), reply_markup


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("🔄 [JARVIS] Merging candidates from all scanners...")

    payload = merge_candidates()
    write_json(payload)
    write_txt(payload)

    # Print summary
    total = payload.get("total_unique", 0)
    cross = payload.get("cross_list_count", 0)
    sc = payload.get("source_counts", {})
    print(f"\n✅ Merged candidate universe:")
    print(f"   📊 Total unique symbols: {total}")
    print(f"   🔗 Cross-list appearances: {cross}")
    for src, cnt in sc.items():
        print(f"   📋 {src}: {cnt} entries")

    if total > 0:
        top = payload["candidates"][0]
        print(f"\n   🏆 Top candidate: {top['symbol']} (score: {top.get('total_score', 0):.1f}, sources: {top.get('sources', [])})")


if __name__ == "__main__":
    main()
