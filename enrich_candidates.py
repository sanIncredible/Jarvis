#!/usr/bin/env python3
"""
enrich_candidates.py
====================
⚡ JARVIS UNIFIED CANDIDATE ENRICHMENT & A+ SNIPER SIEVE ENGINE
=============================================================================
Post-processing pipeline that merges, deduplicates, and scores candidates
across all four scanning engines:
  1. candidates.json          – EOD Stage-2 VCP Swing Candidates
  2. candidates_90d_nr.json   – Breadth Ledger 90D/30% NR Momo Setups
  3. candidates_nifty_ipo.json– Official Nifty IPO Index High-Tight Coils
  4. candidates_ems.json       – Chirag Kedia Easy Money Scan (EMS)

Core Enhancements Tailored for 3m ORB Swing Execution:
  1. Contraction Sieve (Coiled Rest vs Exhausted Runner): Identifies tight rests (Range <=2.2% or NR4/NR7/ID/VDU).
  2. Blue Sky Doorstep: Stocks sitting within <=3.5% of 52W High / ATH (zero overhead resistance).
  3. Institutional Liquidity Floor: Standard ₹10 Cr minimum turnover filter.
  4. Dynamic Regime Gating: Automatically couples with Jarvis Positional Market Regime (DEFENSIVE vs EXPANSION).
  5. The 3-Check Rule (A+ Sniper List): Sifts 179 candidates down to 3-10 pristine actionable setups.

Writes:
  • candidates_merged.json  – Full deduplicated universe with sniper list & regime context
  • candidates_merged.txt   – Human-readable executive briefing
"""

import sys
import json
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "config_credentials.json"
REGIME_FILE = BASE_DIR / "daily_positional_regime.json"
MARKET_REGIME_FILE = BASE_DIR / "market_regime.json"
OHLCV_CACHE_FILE = BASE_DIR / "ohlcv_cache.json"

SOURCE_FILES = {
    "eod":  BASE_DIR / "candidates.json",
    "nr90": BASE_DIR / "candidates_90d_nr.json",
    "ipo":  BASE_DIR / "candidates_nifty_ipo.json",
    "ems":  BASE_DIR / "candidates_ems.json",
}

OUT_JSON = BASE_DIR / "candidates_merged.json"
OUT_TXT  = BASE_DIR / "candidates_merged.txt"

IST = timezone(timedelta(hours=5, minutes=30))

TIER_SCORE_MAP = {1: 30.0, 2: 20.0, 3: 10.0}


def get_ist_now() -> str:
    return datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_market_regime() -> Dict[str, Any]:
    """Loads current market regime state to couple candidate risk gating."""
    for p in [REGIME_FILE, MARKET_REGIME_FILE]:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    code = d.get("regime_code") or d.get("state_code") or "SELECTIVE"
                    badge = d.get("regime_badge") or d.get("state_label") or "SELECTIVE"
                    alloc = d.get("swing_allocation_pct", 50)
                    is_defensive = ("DEFENSIVE" in code or "WASHOUT" in code or "CHOP" in code or alloc <= 25)
                    return {
                        "code": code,
                        "badge": badge,
                        "mandate": d.get("mandate") or d.get("guidance", ""),
                        "swing_allocation_pct": alloc,
                        "is_defensive": is_defensive
                    }
            except Exception:
                pass
    return {"code": "SELECTIVE", "badge": "SELECTIVE", "mandate": "Normal trading", "swing_allocation_pct": 50, "is_defensive": False}


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


def calc_ema(values: List[float], period: int) -> float:
    """Calculates Exponential Moving Average across a list of numeric values."""
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for val in values[period:]:
        ema = (val * k) + (ema * (1.0 - k))
    return ema


def load_ohlcv_cache() -> Dict[str, List[List[float]]]:
    """Loads cached daily OHLCV bars (valid for 30 minutes)."""
    if not OHLCV_CACHE_FILE.is_file():
        return {}
    try:
        with open(OHLCV_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if time.time() - data.get("_ts", 0) < 1800:
                return data.get("bars", {})
    except Exception:
        pass
    return {}


def save_ohlcv_cache(bars_dict: Dict[str, List[List[float]]]) -> None:
    try:
        with open(OHLCV_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "bars": bars_dict}, f)
    except Exception:
        pass


def fetch_single_ohlcv(sym: str) -> Tuple[str, Optional[List[List[float]]]]:
    y_sym = "TMPV" if sym == "TATAMOTORS" else sym
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y_sym}.NS?range=3mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = data["chart"]["result"][0]
            quotes = res["indicators"]["quote"][0]
            closes = quotes.get("close", [])
            highs = quotes.get("high", [])
            lows = quotes.get("low", [])
            vols = quotes.get("volume", [])
            valid = []
            for c, h, l, v in zip(closes, highs, lows, vols):
                if c is not None and h is not None and l is not None and v is not None and c > 0:
                    valid.append([round(c, 2), round(h, 2), round(l, 2), int(v)])
            if len(valid) >= 20:
                return sym, valid
    except Exception:
        pass
    return sym, None


def evaluate_qm_coil(sym: str, bars: Optional[List[List[float]]], live_ltp: Optional[float] = None, live_vol: Optional[float] = None) -> Tuple[bool, Dict[str, Any]]:
    """
    Evaluates Kristjan Qullamaggie High Tight Flag / 10 & 20 EMA Coil:
    1. Prior 1M Momentum: >= 25.0% gain over past 20-25 days.
    2. Pullback Depth (Qullamaggie method): Retracement from swing peak to base low <= 20.0%.
    3. 10/20 EMA Support Shelf: Price surfing near 10 EMA or 20 EMA, holding above 20 EMA.
    4. Volume Dry-Up (VDU): RVOL <= 0.90 (lower volume during pullback/consolidation).
    5. Narrowness Contraction: Daily range <= 2.8% OR NR7 / NR4 / Inside Day.
    """
    if not bars or len(bars) < 20:
        return False, {}

    c_list = [b[0] for b in bars]
    h_list = [b[1] for b in bars]
    l_list = [b[2] for b in bars]
    v_list = [b[3] for b in bars]

    if live_ltp and live_ltp > 0:
        c_list[-1] = live_ltp
        h_list[-1] = max(h_list[-1], live_ltp)
        l_list[-1] = min(l_list[-1], live_ltp)
    if live_vol and live_vol > 0:
        v_list[-1] = live_vol

    ltp = c_list[-1]

    # Lookback 25 bars for momentum impulse
    lb = min(25, len(c_list))
    h_peak = max(h_list[-lb:])
    l_trough = min(l_list[-lb:])
    gain_1m = ((h_peak - l_trough) / l_trough) * 100.0 if l_trough > 0 else 0.0

    # Qullamaggie Pullback depth: from swing peak to base low of last 8 bars
    base_lb = min(8, len(l_list))
    base_low = min(l_list[-base_lb:])
    pullback_depth = ((h_peak - base_low) / h_peak) * 100.0 if h_peak > 0 else 0.0
    curr_from_peak = ((h_peak - ltp) / h_peak) * 100.0 if h_peak > 0 else 0.0

    ema10 = calc_ema(c_list, 10)
    ema20 = calc_ema(c_list, 20)
    dist_ema10 = ((ltp - ema10) / ltp) * 100.0 if ltp > 0 else 0.0
    dist_ema20 = ((ltp - ema20) / ltp) * 100.0 if ltp > 0 else 0.0

    avg_vol_20 = sum(v_list[-20:]) / 20.0 if len(v_list) >= 20 else 1.0
    rvol = v_list[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

    prev_c = c_list[-2] if len(c_list) >= 2 else ltp
    rng_pct = ((h_list[-1] - l_list[-1]) / prev_c) * 100.0 if prev_c > 0 else 2.0

    is_nr7 = len(bars) >= 8 and (h_list[-1] - l_list[-1]) <= min(h_list[i] - l_list[i] for i in range(-7, -1))
    is_nr4 = len(bars) >= 5 and (h_list[-1] - l_list[-1]) <= min(h_list[i] - l_list[i] for i in range(-4, -1))
    is_inside = len(bars) >= 2 and h_list[-1] <= h_list[-2] and l_list[-1] >= l_list[-2]

    # Criteria Checks:
    c_momo = gain_1m >= 25.0
    c_shallow = pullback_depth <= 20.0  # Qullamaggie shallow pullback depth
    c_ema = (ltp >= ema20 * 0.985) and (abs(dist_ema10) <= 3.0 or abs(dist_ema20) <= 2.5)
    c_vdu = rvol <= 0.90
    c_narrow = (rng_pct <= 2.8) or is_nr7 or is_nr4 or is_inside

    is_qm = bool(c_momo and c_shallow and c_ema and c_vdu and c_narrow)

    details = {
        "is_qm_coil": is_qm,
        "gain_1m_pct": round(gain_1m, 1),
        "pullback_depth_pct": round(pullback_depth, 1),
        "curr_from_peak_pct": round(curr_from_peak, 1),
        "ema10": round(ema10, 2),
        "ema20": round(ema20, 2),
        "dist_ema10_pct": round(dist_ema10, 1),
        "dist_ema20_pct": round(dist_ema20, 1),
        "rvol": round(rvol, 2),
        "daily_range_pct": round(rng_pct, 2),
        "is_nr7": is_nr7,
        "is_nr4": is_nr4,
        "is_inside": is_inside,
        "is_vdu": bool(rvol <= 0.70),
        "coil_tag": f"🌀 QM 10/20 EMA COIL (-{round(pullback_depth, 1)}% Retr)",
        "checks_passed": {
            "momo_impulse": c_momo,
            "shallow_retrace": c_shallow,
            "ema_shelf": c_ema,
            "vdu_supply": c_vdu,
            "narrow_coil": c_narrow
        }
    }
    return is_qm, details


def sync_qm_coils_to_ems(cache: Dict[str, Any]) -> None:
    """Enriches candidates_ems.json with is_qm_coil and qm_details so EMS tab has 1-click filter."""
    ems_path = SOURCE_FILES.get("ems")
    if not ems_path or not ems_path.is_file():
        return
    try:
        with open(ems_path, "r", encoding="utf-8") as f:
            ems_data = json.load(f)
        all_cands = ems_data.get("all_candidates", [])
        qm_count = 0
        for c in all_cands:
            sym = c.get("symbol", "")
            bars = cache.get(sym)
            if c.get("ltp") is None and bars and len(bars) > 0:
                c["ltp"] = round(float(bars[-1][0]), 2)
            is_qm, details = evaluate_qm_coil(sym, bars)
            c["is_qm_coil"] = is_qm
            c["qm_details"] = details
            if is_qm:
                qm_count += 1
                c["coil_tag"] = details.get("coil_tag", "🌀 QM COIL")

        for k in ["tier1_candidates", "tier2_candidates", "tier3_candidates"]:
            for c in ems_data.get(k, []):
                sym = c.get("symbol", "")
                bars = cache.get(sym)
                if c.get("ltp") is None and bars and len(bars) > 0:
                    c["ltp"] = round(float(bars[-1][0]), 2)
                is_qm, details = evaluate_qm_coil(sym, bars)
                c["is_qm_coil"] = is_qm
                c["qm_details"] = details
                if is_qm:
                    c["coil_tag"] = details.get("coil_tag", "🌀 QM COIL")

        ems_data["qm_coil_count"] = qm_count
        with open(ems_path, "w", encoding="utf-8") as f:
            json.dump(ems_data, f, indent=2, ensure_ascii=False)
        print(f"   🌀 Enriched candidates_ems.json: {qm_count} Qullamaggie Coils tagged")
    except Exception as e:
        print(f"   ℹ️ Notice: Failed to sync QM coils to EMS: {e}")


def load_eod(path: Path) -> List[Dict[str, Any]]:
    """EOD Stage 2 VCP candidates."""
    data = _load_json(path)
    raw = data.get("candidates", [])
    out = []
    for r in raw:
        entry = dict(r)
        entry["_source"] = "eod"
        tier_str = str(entry.get("tier", "")).upper()
        if "TIER 1" in tier_str or "SECTORAL" in tier_str or "DOORSTEP" in tier_str:
            entry["tier_order"] = 1
        elif "TIER 2" in tier_str or "LAUNCHPAD" in tier_str:
            entry["tier_order"] = 2
        else:
            entry["tier_order"] = 3
        if "total_score" not in entry:
            entry["total_score"] = float(entry.get("score", 0) or 0)
        out.append(entry)
    return out


def load_tiered(path: Path, source: str) -> List[Dict[str, Any]]:
    """NR90, IPO, EMS."""
    data = _load_json(path)
    out = []
    for tier_key, tier_order in [("tier1_candidates", 1), ("tier2_candidates", 2), ("tier3_candidates", 3)]:
        for r in data.get(tier_key, []):
            entry = dict(r)
            entry["_source"] = source
            if "tier_order" not in entry:
                entry["tier_order"] = tier_order
            if "total_score" not in entry:
                score = entry.get("priority_score") or entry.get("score")
                if score is not None:
                    entry["total_score"] = float(score)
                else:
                    entry["total_score"] = TIER_SCORE_MAP.get(tier_order, 0.0)
            out.append(entry)
    return out


# ── Merge, Deduplicate & Sieve ───────────────────────────────────────────────

def merge_candidates() -> Dict[str, Any]:
    """
    Executes full multi-list merge, deduplication, 3-Check Sniper Sieve,
    Blue Sky tagging, and Regime Gating.
    """
    cfg = load_config()
    c_filters = cfg.get("candidate_filters", {})
    min_turnover = float(c_filters.get("liquidity_min_cr", 10.0))
    blue_sky_max = float(c_filters.get("blue_sky_dist_max", 3.5))
    tight_range_max = float(c_filters.get("tight_range_max", 2.2))
    min_rs = int(c_filters.get("min_rs_rating", 80))
    defensive_strict = bool(c_filters.get("regime_defensive_strict", True))

    regime_state = load_market_regime()

    all_entries: List[Dict[str, Any]] = []
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

    # Load auxiliary live quote cache to resolve missing ltp, turnover, pdh, pdl
    cache_quotes: Dict[str, Dict[str, Any]] = {}
    for aux_path in [BASE_DIR / "data.json", BASE_DIR / "dhan_nse_cache.json"]:
        if aux_path.is_file():
            try:
                with open(aux_path, "r", encoding="utf-8") as f:
                    aux_data = json.load(f)
                    stocks_list = aux_data.get("stocks", []) if isinstance(aux_data, dict) else (aux_data if isinstance(aux_data, list) else [])
                    for st in stocks_list:
                        if isinstance(st, dict):
                            s_key = (st.get("symbol") or st.get("trading_symbol") or "").upper().strip()
                            if s_key and s_key not in cache_quotes:
                                cache_quotes[s_key] = st
            except Exception:
                pass

    # Group by symbol
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for entry in all_entries:
        sym = (entry.get("symbol") or entry.get("SYMBOL") or "").upper().strip()
        if not sym:
            continue
        entry["symbol"] = sym
        by_symbol.setdefault(sym, []).append(entry)

    merged: List[Dict[str, Any]] = []
    cross_list_count = 0

    for sym, entries in by_symbol.items():
        sources = sorted(set(e["_source"] for e in entries))
        # Choose best base entry (preferring entry with highest existing score)
        best = max(entries, key=lambda e: float(e.get("total_score", 0)))
        best = dict(best)

        # Merge key fields across sources if missing on best entry
        for other in entries:
            for k in ["daily_range_pct", "dist_52w_pct", "dist_ath_pct", "rs_rating", "turnover_cr", "ltp", "change_pct", "industry", "name", "gain_tier", "is_fresh_3m", "is_nr7", "is_nr4", "is_inside", "is_vdu", "coil_tag", "vol_tag", "sector_tag", "day_high", "day_low", "prev_close", "curr_close", "curr_high", "curr_low"]:
                if best.get(k) is None and other.get(k) is not None:
                    best[k] = other[k]

        # Resolve from auxiliary live cache if missing
        aux_q = cache_quotes.get(sym)
        if aux_q:
            if best.get("ltp") is None and aux_q.get("ltp"):
                best["ltp"] = aux_q["ltp"]
            if best.get("turnover_cr") is None and aux_q.get("turnover_cr"):
                best["turnover_cr"] = aux_q["turnover_cr"]
            if best.get("daily_range_pct") is None and aux_q.get("daily_range_pct"):
                best["daily_range_pct"] = aux_q["daily_range_pct"]
            if best.get("day_high") is None and (aux_q.get("day_high") or aux_q.get("high")):
                best["day_high"] = aux_q.get("day_high") or aux_q.get("high")
            if best.get("day_low") is None and (aux_q.get("day_low") or aux_q.get("low")):
                best["day_low"] = aux_q.get("day_low") or aux_q.get("low")
            if best.get("prev_close") is None and (aux_q.get("prev_close") or aux_q.get("close")):
                best["prev_close"] = aux_q.get("prev_close") or aux_q.get("close")

        # Fallback to curr_close from nr90 or ipo if ltp missing
        if best.get("ltp") is None and best.get("curr_close"):
            best["ltp"] = best["curr_close"]

        # If turnover is missing but vol and ltp are present:
        if best.get("turnover_cr") is None and best.get("vol") and best.get("ltp"):
            try:
                v = float(best["vol"])
                p = float(best["ltp"])
                best["turnover_cr"] = round((v * p) / 10000000.0, 2)
            except Exception:
                pass

        best["source"] = best.pop("_source", sources[0])
        best["sources"] = sources

        # Cross-list confluence bonus: +10 per additional source
        num_lists = len(sources)
        cross_list_bonus = max(0, (num_lists - 1)) * 10.0
        best["cross_list_bonus"] = cross_list_bonus
        if cross_list_bonus > 0:
            cross_list_count += 1

        # ── 1. CHECK 1: MOMENTUM VELOCITY ──
        rs_val = int(best.get("rs_rating") or 0)
        gain_tier = str(best.get("gain_tier") or "")
        triggers = best.get("triggers", [])
        momo_ok = (
            num_lists >= 2 or
            (best.get("source") == "ems" and best.get("tier_order") == 1) or
            rs_val >= min_rs or
            any(t in gain_tier for t in ["30%", "50%", "75%", "100%"]) or
            len(triggers) >= 2 or
            "90D" in str(best.get("flags", []))
        )
        best["check_momentum"] = momo_ok

        # ── 2. CHECK 2: STRUCTURE / BLUE SKY DOORSTEP ──
        raw_dist_52w = best.get("dist_52w_pct")
        if raw_dist_52w is None:
            raw_dist_52w = best.get("dist_ath_pct")

        abs_dist_52w = None
        is_blue_sky = False
        if raw_dist_52w is not None:
            try:
                abs_dist_52w = abs(float(raw_dist_52w))
                # Normal threshold: within blue_sky_max% (default 3.5%) of 52W High / ATH
                is_blue_sky = bool(abs_dist_52w <= blue_sky_max)
            except (ValueError, TypeError):
                is_blue_sky = False

        dist_pivot = best.get("dist_pivot_20d_pct")
        tier_str = str(best.get("tier") or "").upper()

        is_doorstep = (
            is_blue_sky or
            (dist_pivot is not None and abs(float(dist_pivot)) <= 2.2) or
            ("DOORSTEP" in tier_str) or
            best.get("is_fresh_3m", False)
        )
        best["is_blue_sky"] = is_blue_sky
        best["is_doorstep"] = is_doorstep
        best["check_structure"] = is_doorstep

        # ── 3. CHECK 3: VOLATILITY CONTRACTION (COIL VS EXHAUSTION) ──
        rng = best.get("daily_range_pct")
        is_tight = False
        if rng is not None:
            try:
                is_tight = bool(float(rng) <= tight_range_max)
            except (ValueError, TypeError):
                is_tight = False
        is_nr = bool(best.get("is_nr7") or best.get("is_nr4") or best.get("is_inside") or best.get("is_vdu"))
        is_coiled = is_tight or is_nr
        best["is_coiled"] = is_coiled
        best["check_contraction"] = is_coiled

        # ── 4. INSTITUTIONAL LIQUIDITY FLOOR ──
        # Strict: must have verified turnover >= min_turnover (default ₹10 Cr). No phantom passes!
        turnover = best.get("turnover_cr")
        is_liquid = False
        if turnover is not None:
            try:
                is_liquid = bool(float(turnover) >= min_turnover)
            except (ValueError, TypeError):
                is_liquid = False
        best["is_liquid"] = is_liquid

        # ── 5. REGIME-AWARE A+ SNIPER GATING ──
        is_defensive = regime_state.get("is_defensive", False)
        if is_defensive and defensive_strict:
            # Defensive / Washout / Fakeout Risk Mode:
            # Stricter Blue Sky Doorstep (<= 2.2% from high), strict contraction, verified liquidity
            is_tight_doorstep = (abs_dist_52w is not None and abs_dist_52w <= 2.2) or ("DOORSTEP" in tier_str)
            is_defensive_coiled = (is_nr or (rng is not None and float(rng) <= 1.8))
            is_sniper = bool(momo_ok and is_tight_doorstep and is_defensive_coiled and is_liquid)
        else:
            is_sniper = bool(momo_ok and is_doorstep and is_coiled and is_liquid)
        best["is_sniper"] = is_sniper

        if is_sniper:
            best["grade"] = "A+"
        elif is_doorstep and (momo_ok or is_coiled):
            best["grade"] = "A"
        else:
            best["grade"] = "B"

        # Apply Scoring Bonuses
        bonus_score = cross_list_bonus
        if is_blue_sky:
            bonus_score += 15.0
        if is_coiled:
            bonus_score += 10.0
        if is_sniper:
            bonus_score += 20.0

        current_score = float(best.get("total_score", 0))
        best["total_score"] = round(current_score + bonus_score, 1)

        # ── 6. 3m ORB EXECUTION PRIMITIVES INJECTION ──
        ltp_val = float(best.get("ltp") or best.get("curr_close") or 0.0)
        pdh_val = float(best.get("day_high") or best.get("curr_high") or best.get("pdh") or 0.0)
        pdl_val = float(best.get("day_low") or best.get("curr_low") or best.get("pdl") or 0.0)

        if ltp_val > 0:
            best["ltp"] = round(ltp_val, 2)
        if pdh_val > 0:
            best["pdh"] = round(pdh_val, 2)
        if pdl_val > 0:
            best["pdl"] = round(pdl_val, 2)

        if ltp_val > 0:
            clean_ltp = int(round(ltp_val))
            if pdl_val > 0 and pdl_val < ltp_val and ((ltp_val - pdl_val) / ltp_val) <= 0.035:
                est_sl = int(round(pdl_val))
                est_sl_pct = round(((clean_ltp - est_sl) / clean_ltp) * 100.0, 1)
            else:
                est_sl = int(round(clean_ltp * 0.975))
                est_sl_pct = 2.5
            risk_per_sh = max(1, clean_ltp - est_sl)
            best["est_sl"] = est_sl
            best["est_sl_pct"] = est_sl_pct
            best["qty_risk_1k"] = max(1, int(1000 // risk_per_sh))
            best["qty_risk_2k"] = max(1, int(2000 // risk_per_sh))
            best["target_2r"] = clean_ltp + (2 * risk_per_sh)

        # Flags & Badges
        flags = list(best.get("flags", []))
        if is_sniper and "🎯 A+ Sniper" not in flags:
            flags.insert(0, "🎯 A+ Sniper")
        if is_blue_sky and "👑 Blue Sky" not in flags:
            flags.append("👑 Blue Sky")
        if is_coiled and not any("Tight" in f or "NR" in f or "Inside" in f for f in flags):
            flags.append("📦 Coiled Rest")
        best["flags"] = flags

        # Clean internal keys
        for key in list(best.keys()):
            if key.startswith("_"):
                del best[key]

        merged.append(best)

    # ── 7. KRISTJAN QULLAMAGGIE 10/20 EMA PULLBACK COIL SIEVE ──
    symbols = [c["symbol"] for c in merged if c.get("symbol")]
    ohlcv_cache = load_ohlcv_cache()
    missing_syms = [s for s in symbols if s not in ohlcv_cache]
    if missing_syms:
        with ThreadPoolExecutor(max_workers=20) as ex:
            fetched = list(ex.map(fetch_single_ohlcv, missing_syms))
        for s, b in fetched:
            if b:
                ohlcv_cache[s] = b
        save_ohlcv_cache(ohlcv_cache)

    qm_cands = []
    for c in merged:
        sym = c.get("symbol", "")
        bars = ohlcv_cache.get(sym)
        if c.get("ltp") is None and bars and len(bars) > 0:
            c["ltp"] = round(float(bars[-1][0]), 2)
            if c.get("curr_close") is None:
                c["curr_close"] = c["ltp"]
        is_qm, qm_details = evaluate_qm_coil(sym, bars, c.get("ltp"), c.get("vol"))
        c["is_qm_coil"] = is_qm
        c["qm_details"] = qm_details
        if is_qm:
            c["total_score"] = round(float(c.get("total_score", 0)) + 12.0, 1)
            flags = list(c.get("flags", []))
            if "🌀 QM Coil" not in flags:
                flags.append("🌀 QM Coil")
            c["flags"] = flags
            qm_cands.append(c)

    # Sync QM coils back to candidates_ems.json
    sync_qm_coils_to_ems(ohlcv_cache)

    # Sort by total_score descending
    merged.sort(key=lambda x: -float(x.get("total_score", 0)))

    # Sub-lists
    sniper_cands = [c for c in merged if c.get("is_sniper")]
    qm_cands.sort(key=lambda x: -float(x.get("total_score", 0)))

    # In defensive regimes, cap actionable A+ Snipers to Top 5 pristine setups to eliminate noise
    is_defensive = regime_state.get("is_defensive", False)
    if is_defensive and defensive_strict and len(sniper_cands) > 5:
        for demoted in sniper_cands[5:]:
            demoted["is_sniper"] = False
            demoted["grade"] = "A"
            if "🎯 A+ Sniper" in demoted.get("flags", []):
                demoted["flags"].remove("🎯 A+ Sniper")
        sniper_cands = sniper_cands[:5]
    elif len(sniper_cands) > 10:
        for demoted in sniper_cands[10:]:
            demoted["is_sniper"] = False
            demoted["grade"] = "A"
            if "🎯 A+ Sniper" in demoted.get("flags", []):
                demoted["flags"].remove("🎯 A+ Sniper")
        sniper_cands = sniper_cands[:10]

    blue_sky_cands = [c for c in merged if c.get("is_blue_sky")]

    now_str = get_ist_now()
    payload = {
        "as_of": now_str,
        "market_regime": regime_state,
        "total_unique": len(merged),
        "cross_list_count": cross_list_count,
        "sniper_count": len(sniper_cands),
        "blue_sky_count": len(blue_sky_cands),
        "qm_coil_count": len(qm_cands),
        "source_counts": source_counts,
        "filters_applied": {
            "min_turnover_cr": min_turnover,
            "blue_sky_dist_max": blue_sky_max,
            "tight_range_max": tight_range_max,
            "min_rs_rating": min_rs,
            "regime_defensive_strict": defensive_strict
        },
        "sniper_candidates": sniper_cands,
        "blue_sky_candidates": blue_sky_cands,
        "qm_candidates": qm_cands,
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
    snipers = payload.get("sniper_candidates", [])
    regime = payload.get("market_regime", {})
    
    lines = [
        f"# JARVIS UNIFIED CANDIDATE CONFLUENCE & A+ SNIPER BRIEFING — {payload.get('as_of', '')}",
        f"# Market Regime: {regime.get('badge', 'N/A')} (Swing Alloc: {regime.get('swing_allocation_pct', 0)}%)",
        f"# Total Unique: {payload.get('total_unique', 0)} | 🎯 A+ Snipers: {len(snipers)} | 👑 Blue Sky: {payload.get('blue_sky_count', 0)} | 🔗 Multi-Source: {payload.get('cross_list_count', 0)}",
        f"# 3-Check Rule: [1] Momentum Velocity + [2] Blue Sky/Doorstep (≤3.5% 52W) + [3] Volatility Contraction (≤2.2% rng / NR)",
        "",
        "==========================================================================================",
        f"🎯 A+ SNIPER WATCHLIST (PRIME 3-CHECK SETUPS FOR TOMORROW'S 3m ORB)",
        "==========================================================================================",
        f"{'#':<4} {'SYMBOL':<14} {'SCORE':>7} {'GRADE':>6} {'SOURCES':<18} {'52W DIST':>10} {'RANGE':>8} {'INDUSTRY':<26}",
        f"{'─'*4} {'─'*14} {'─'*7} {'─'*6} {'─'*18} {'─'*10} {'─'*8} {'─'*26}",
    ]

    for idx, c in enumerate(snipers, 1):
        sym = c.get("symbol", "?")
        score = float(c.get("total_score", 0))
        sources = ",".join(c.get("sources", []))
        dist = f"{c['dist_52w_pct']:+.1f}%" if c.get("dist_52w_pct") is not None else "Doorstep"
        rng = f"{c['daily_range_pct']:.2f}%" if c.get("daily_range_pct") is not None else "-"
        ind = c.get("industry", "") or ""
        lines.append(f"{idx:<4} {sym:<14} {score:>7.1f} {'A+':>6} {sources:<18} {dist:>10} {rng:>8} {ind:<26}")

    qm_cands = payload.get("qm_candidates", [])
    if qm_cands:
        lines.extend([
            "",
            "==========================================================================================",
            f"🌀 KRISTJAN QULLAMAGGIE 10/20 EMA HIGH-TIGHT COILS ({len(qm_cands)} Setups)",
            "==========================================================================================",
            f"{'#':<4} {'SYMBOL':<14} {'1M GAIN':>9} {'PULLBACK':>10} {'10EMA DIST':>12} {'RVOL':>7} {'RANGE':>8} {'INDUSTRY':<24}",
            f"{'─'*4} {'─'*14} {'─'*9} {'─'*10} {'─'*12} {'─'*7} {'─'*8} {'─'*24}",
        ])
        for idx, c in enumerate(qm_cands[:25], 1):
            sym = c.get("symbol", "?")
            qm = c.get("qm_details", {})
            g_str = f"+{qm.get('gain_1m_pct', 0):.1f}%"
            pb_str = f"-{qm.get('pullback_depth_pct', 0):.1f}%"
            ema_str = f"{qm.get('dist_ema10_pct', 0):+.1f}%"
            rv_str = f"{qm.get('rvol', 0):.2f}x"
            rng_str = f"{qm.get('daily_range_pct', 0):.2f}%"
            ind = c.get("industry", "") or ""
            lines.append(f"{idx:<4} {sym:<14} {g_str:>9} {pb_str:>10} {ema_str:>12} {rv_str:>7} {rng_str:>8} {ind:<24}")

    lines.extend([
        "",
        "==========================================================================================",
        f"🏆 ALL RANKED CANDIDATES (TOP 40)",
        "==========================================================================================",
        f"{'#':<4} {'SYMBOL':<14} {'SCORE':>7} {'GRADE':>6} {'SOURCES':<18} {'52W DIST':>10} {'BONUS':>6} {'INDUSTRY':<26}",
        f"{'─'*4} {'─'*14} {'─'*7} {'─'*6} {'─'*18} {'─'*10} {'─'*6} {'─'*26}",
    ])

    for idx, c in enumerate(cands[:40], 1):
        sym = c.get("symbol", "?")
        score = float(c.get("total_score", 0))
        grade = c.get("grade", "B")
        sources = ",".join(c.get("sources", []))
        bonus = float(c.get("cross_list_bonus", 0))
        bonus_str = f"+{bonus:.0f}" if bonus > 0 else ""
        dist = f"{c['dist_52w_pct']:+.1f}%" if c.get("dist_52w_pct") is not None else "-"
        ind = c.get("industry", "") or ""
        lines.append(f"{idx:<4} {sym:<14} {score:>7.1f} {grade:>6} {sources:<18} {dist:>10} {bonus_str:>6} {ind:<26}")

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"📝 Written: {OUT_TXT}")


# ── Telegram Cards ───────────────────────────────────────────────────────────

def format_sniper_telegram_card(payload: Dict[str, Any], max_display: int = 8) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Formats specialized Telegram briefing card for /sniper command:
    Strictly displays A+ Grade Setups meeting the 3-Check Rule with 1-tap add buttons.
    """
    snipers = payload.get("sniper_candidates", [])
    regime = payload.get("market_regime", {})
    regime_badge = regime.get("badge", "SELECTIVE")
    is_defensive = regime.get("is_defensive", False)

    lines = [
        "🎯 <b>JARVIS A+ SNIPER PRE-MARKET SHORTLIST</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>As Of:</b> {payload.get('as_of', 'Latest')}",
        f"🛡️ <b>Market Regime:</b> <code>{regime_badge}</code>",
        f"🎯 <b>A+ Qualified Setups:</b> <b>{len(snipers)}</b> <i>(Sifted from {payload.get('total_unique', 0)} stocks)</i>",
        "💡 <i>Criteria: Momentum Velocity + Blue Sky (≤3.5% 52W) + Coiled Rest (≤2.2% rng / NR)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if is_defensive:
        lines.append("⚠️ <b>DEFENSIVE GATING ACTIVE:</b> <i>Zero or minimal swing risk. Trade high-conviction 3m scalps only.</i>\n")

    if not snipers:
        lines.append("ℹ️ <i>No stocks met all 3 strict Sniper checks today. Sit on hands or review /merged.</i>")
        return "\n".join(lines), None

    lines.append("🔥 <b>PRIME A+ BREAKOUT CANDIDATES:</b>")
    for idx, c in enumerate(snipers[:max_display], 1):
        sym = c.get("symbol", "")
        score = float(c.get("total_score", 0))
        sources_list = [s.upper() for s in c.get("sources", [c.get("source", "")])]
        src_str = " + ".join(sources_list)
        ind = c.get("industry", "") or ""
        dist = c.get("dist_52w_pct")
        dist_str = f"52W: <code>{dist:+.1f}%</code>" if dist is not None else "Doorstep"
        rng = c.get("daily_range_pct")
        rng_str = f"Rng: <code>{rng:.1f}%</code>" if rng is not None else ""
        tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
        
        # Risk-Normalized Sizing Calculation
        ltp_val = float(c.get("ltp") or 0.0)
        day_low_val = float(c.get("day_low") or 0.0)
        sizing_str = ""
        if ltp_val > 0:
            clean_ltp = int(round(ltp_val))
            if day_low_val > 0 and day_low_val < ltp_val and ((ltp_val - day_low_val) / ltp_val) <= 0.04:
                sl_est = int(round(day_low_val))
            else:
                sl_est = int(round(ltp_val * 0.985))
            if sl_est >= clean_ltp:
                sl_est = max(1, clean_ltp - 1)
            risk_per_sh = max(1, clean_ltp - sl_est)
            q_1k = max(1, int(1000 // risk_per_sh))
            q_2k = max(1, int(2000 // risk_per_sh))
            c_1k = q_1k * clean_ltp
            c_2k = q_2k * clean_ltp
            c1_str = f"₹{c_1k/1000:.0f}k" if c_1k < 100000 else f"₹{c_1k/100000:.1f}L"
            c2_str = f"₹{c_2k/1000:.0f}k" if c_2k < 100000 else f"₹{c_2k/100000:.1f}L"
            sizing_str = f"\n   └ 🎯 <b>Sizing:</b> 1k Risk = <b>{q_1k} shs</b> ({c1_str}) | 2k Risk = <b>{q_2k} shs</b> ({c2_str}) [SL: ₹{sl_est:,}]"

        lines.append(
            f"<b>{idx}. {tv_link}</b> — Score: <b>{score:.1f}</b>\n"
            f"   └ <i>{src_str}</i> | {dist_str} • {rng_str} | {ind}"
            f"{sizing_str}"
        )

    lines.append("\n👉 <i>Tap to add to Watchlist or 1-tap execute with normalized risk:</i>")

    btn_stocks = [c["symbol"] for c in snipers[:6]]
    seen_b = set()
    uniq_btns = []
    for s in btn_stocks:
        if s and s not in seen_b:
            seen_b.add(s)
            uniq_btns.append(s)

    kb_rows = []
    # 1-Tap Promote Top 5 Snipers directly to live Watchlist
    if len(snipers) >= 1:
        top_n = min(5, len(snipers))
        kb_rows.append([
            {"text": f"🚀 Promote Top {top_n} Snipers to Watchlist", "callback_data": "cand_add_top5"}
        ])

    # 1-Tap Risk Order Buttons for Top 2 setups
    for s in uniq_btns[:2]:
        kb_rows.append([
            {"text": f"⚡ Buy 1k: {s}", "callback_data": f"buy_risk:{s}:1k"},
            {"text": f"⚡ Buy 2k: {s}", "callback_data": f"buy_risk:{s}:2k"}
        ])

    # Watchlist promotion buttons
    for i in range(0, len(uniq_btns), 3):
        chunk = uniq_btns[i:i+3]
        kb_rows.append([{"text": f"➕ {s}", "callback_data": f"cand_add:{s}"} for s in chunk])

    reply_markup = {"inline_keyboard": kb_rows} if kb_rows else None
    return "\n".join(lines), reply_markup


def format_qm_telegram_card(payload: Dict[str, Any], max_display: int = 8) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Formats Telegram briefing card for /qm or /coils:
    Displays Kristjan Qullamaggie High Tight Flag & 10/20 EMA Coils with 1-tap add/buy buttons.
    """
    qm_cands = payload.get("qm_candidates", [])
    regime = payload.get("market_regime", {})
    regime_badge = regime.get("badge", "SELECTIVE")

    lines = [
        "🌀 <b>KRISTJAN QULLAMAGGIE 10/20 EMA COILS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>As Of:</b> {payload.get('as_of', 'Latest')}",
        f"🛡️ <b>Market Regime:</b> <code>{regime_badge}</code>",
        f"🌀 <b>Qualified Coils:</b> <b>{len(qm_cands)}</b> setups",
        "💡 <i>Criteria: 1M Gain ≥25-30% • Shallow Pullback ≤20% • 10/20 EMA Shelf • VDU • Range Contraction</i>",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if not qm_cands:
        lines.append("ℹ️ <i>No stocks met all Qullamaggie High-Tight Coil checks today.</i>")
        return "\n".join(lines), None

    lines.append("🔥 <b>PRIME 10/20 EMA COILS:</b>")
    for idx, c in enumerate(qm_cands[:max_display], 1):
        sym = c.get("symbol", "")
        qm = c.get("qm_details", {})
        g_val = qm.get("gain_1m_pct", 0)
        pb_val = qm.get("pullback_depth_pct", 0)
        e10_val = qm.get("dist_ema10_pct", 0)
        rv_val = qm.get("rvol", 0)
        rng_val = qm.get("daily_range_pct", 0)
        ind = c.get("industry", "") or ""
        tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
        
        # Risk-Normalized Sizing
        ltp_val = float(c.get("ltp") or 0.0)
        day_low_val = float(c.get("day_low") or 0.0)
        sizing_str = ""
        if ltp_val > 0:
            clean_ltp = int(round(ltp_val))
            if day_low_val > 0 and day_low_val < ltp_val and ((ltp_val - day_low_val) / ltp_val) <= 0.04:
                sl_est = int(round(day_low_val))
            else:
                sl_est = int(round(ltp_val * 0.985))
            if sl_est >= clean_ltp:
                sl_est = max(1, clean_ltp - 1)
            risk_per_sh = max(1, clean_ltp - sl_est)
            q_1k = max(1, int(1000 // risk_per_sh))
            sizing_str = f"\n   └ 🎯 <b>1k Risk Qty:</b> <b>{q_1k} shs</b> [SL: ₹{sl_est:,}]"

        lines.append(
            f"<b>{idx}. {tv_link}</b> — 1M: <b>+{g_val:.1f}%</b> | Retrace: <b>-{pb_val:.1f}%</b>\n"
            f"   └ 10EMA: <code>{e10_val:+.1f}%</code> • RVOL: <code>{rv_val:.2f}x</code> • Rng: <code>{rng_val:.1f}%</code> | {ind}"
            f"{sizing_str}"
        )

    lines.append("\n👉 <i>Tap to add to Watchlist or execute with normalized risk:</i>")
    btn_stocks = [c["symbol"] for c in qm_cands[:6]]
    uniq_btns = []
    seen_b = set()
    for s in btn_stocks:
        if s and s not in seen_b:
            seen_b.add(s)
            uniq_btns.append(s)

    kb_rows = []
    if len(qm_cands) >= 1:
        top_n = min(5, len(qm_cands))
        kb_rows.append([
            {"text": f"🚀 Promote Top {top_n} QM Coils to Watchlist", "callback_data": "cand_add_top5_qm"}
        ])

    for s in uniq_btns[:2]:
        kb_rows.append([
            {"text": f"⚡ Buy 1k: {s}", "callback_data": f"buy_risk:{s}:1k"},
            {"text": f"⚡ Buy 2k: {s}", "callback_data": f"buy_risk:{s}:2k"}
        ])

    for i in range(0, len(uniq_btns), 3):
        chunk = uniq_btns[i:i+3]
        kb_rows.append([{"text": f"➕ {s}", "callback_data": f"cand_add:{s}"} for s in chunk])

    reply_markup = {"inline_keyboard": kb_rows} if kb_rows else None
    return "\n".join(lines), reply_markup


def format_merged_telegram_card(payload: Dict[str, Any], max_display: int = 10) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Formats executive Telegram card for /merged or /confluence."""
    cands = payload.get("candidates", [])
    total = payload.get("total_unique", len(cands))
    cross = payload.get("cross_list_count", 0)
    snipers = payload.get("sniper_candidates", [])
    sc = payload.get("source_counts", {})
    regime = payload.get("market_regime", {})

    lines = [
        "🏆 <b>JARVIS UNIFIED CANDIDATE CONFLUENCE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>As Of:</b> {payload.get('as_of', 'Latest')}",
        f"🛡️ <b>Regime:</b> <code>{regime.get('badge', 'SELECTIVE')}</code>",
        f"🎯 <b>Total Unique:</b> <b>{total}</b> • 🎯 <b>A+ Snipers:</b> <b>{len(snipers)}</b>",
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
        grade = c.get("grade", "B")
        grade_badge = f" [🎯 {grade}]" if grade in ("A+", "A") else ""
        bonus = float(c.get("cross_list_bonus", 0))
        bonus_badge = f" [⚡+{int(bonus)}]" if bonus > 0 else ""
        dist = c.get("dist_52w_pct")
        dist_str = f" • 52W: <code>{dist:+.1f}%</code>" if dist is not None else ""
        tv_link = f"<a href='https://in.tradingview.com/chart/?symbol=NSE:{sym}'><b>{sym}</b></a>"
        lines.append(
            f"<b>{idx}. {tv_link}</b> — Score: <b>{score:.1f}</b>{grade_badge}{bonus_badge}\n"
            f"   └ <i>{src_str}</i>{dist_str} | {ind}"
        )

    lines.append("\n👉 <i>Tap any stock below to promote to your live Watchlist:</i>")

    btn_stocks = [c["symbol"] for c in cands[:9]]
    seen_b = set()
    uniq_btns = []
    for s in btn_stocks:
        if s and s not in seen_b:
            seen_b.add(s)
            uniq_btns.append(s)

    kb_rows = []
    if len(snipers) >= 1:
        top_n = min(5, len(snipers))
        kb_rows.append([
            {"text": f"🚀 Promote Top {top_n} Snipers to Watchlist", "callback_data": "cand_add_top5"}
        ])

    for i in range(0, len(uniq_btns), 3):
        chunk = uniq_btns[i:i+3]
        kb_rows.append([{"text": f"➕ {s}", "callback_data": f"cand_add:{s}"} for s in chunk])

    reply_markup = {"inline_keyboard": kb_rows} if kb_rows else None
    return "\n".join(lines), reply_markup


def main():
    print("🔄 [JARVIS] Merging candidates from all scanners with 3-Check Sniper Sieve...")
    payload = merge_candidates()
    write_json(payload)
    write_txt(payload)

    total = payload.get("total_unique", 0)
    cross = payload.get("cross_list_count", 0)
    snipers = payload.get("sniper_candidates", [])
    blue_skies = payload.get("blue_sky_candidates", [])
    sc = payload.get("source_counts", {})
    regime = payload.get("market_regime", {})

    print(f"\n✅ Merged candidate universe:")
    print(f"   🛡️ Market Regime: {regime.get('badge', 'N/A')}")
    print(f"   📊 Total unique symbols: {total}")
    print(f"   🎯 A+ Sniper setups: {len(snipers)}")
    print(f"   👑 Blue Sky setups (<=3.5% 52W): {len(blue_skies)}")
    print(f"   🔗 Cross-list confluences: {cross}")
    for src, cnt in sc.items():
        print(f"   📋 {src}: {cnt} entries")

    if snipers:
        print(f"\n   🎯 Top A+ Snipers:")
        for s in snipers[:5]:
            print(f"      • {s['symbol']:<12} Score: {s['total_score']} | Sources: {s['sources']} | 52W: {s.get('dist_52w_pct')}%")


if __name__ == "__main__":
    main()
