"""
⚡ MASTER MULTI-BROKER SYMBOL & ISIN REGISTRY CACHE
Pre-caches and unifies symbol definitions across:
- Upstox API v2 (NSE_EQ|ISIN)
- DhanHQ (security_id int)
- Zerodha Kite (tradingsymbol)
Loads once at pre-market / startup, guaranteeing zero runtime latency.
"""

import os
import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "master_symbol_registry.json"
DHAN_CACHE_FILE = BASE_DIR / "dhan_nse_cache.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"

# Core fallback mapping for top symbols
KNOWN_ISINS = {
    "RELIANCE": "INE002A01018",
    "TCS": "INE467B01029",
    "HDFCBANK": "INE040A01034",
    "INFY": "INE009A01021",
    "ICICIBANK": "INE090A01021",
    "TATAMOTORS": "INE155A01022",
    "CEMPRO": "INE686A01026",
    "ENTERO": "INE01CR01017",
    "ITC": "INE154A01025",
    "TATACONSUM": "INE192A01025",
    "TIPSMUSIC": "INE716B01029",
    "GRAPHITE": "INE541A01023",
    "WEWORK": "INE07CR01015",
    "HEGAM": "INE545H01011",
    "INDGN": "INE06CR01012"
}

_MEMORY_REGISTRY = {}


def build_master_registry():
    """Compiles and saves master_symbol_registry.json."""
    registry = {}

    # Load Dhan cache if exists
    dhan_map = {}
    if DHAN_CACHE_FILE.is_file():
        try:
            with open(DHAN_CACHE_FILE, "r", encoding="utf-8") as f:
                dhan_map = json.load(f)
        except Exception:
            pass

    # Read active watchlist
    symbols = []
    if WATCHLIST_FILE.is_file():
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            for l in f:
                s = l.strip().upper()
                if s and not s.startswith("#"):
                    symbols.append(s)

    # Read candidates if exists
    cand_file = BASE_DIR / "candidates.json"
    if cand_file.is_file():
        try:
            with open(cand_file, "r", encoding="utf-8") as cf:
                cdata = json.load(cf)
                for c in cdata.get("candidates", []):
                    csym = c.get("symbol", "").upper()
                    if csym and csym not in symbols:
                        symbols.append(csym)
        except Exception:
            pass

    for s in symbols:
        isin = KNOWN_ISINS.get(s, "")
        upstox_key = f"NSE_EQ|{isin}" if isin else f"NSE_EQ|{s}"
        dhan_id = dhan_map.get(s)

        registry[s] = {
            "symbol": s,
            "isin": isin,
            "upstox_key": upstox_key,
            "dhan_id": dhan_id,
            "zerodha_symbol": s,
            "exchange": "NSE"
        }

    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as rf:
            json.dump(registry, rf, indent=2)
        print(f"✅ Master symbol registry compiled ({len(registry)} symbols) -> {REGISTRY_FILE.name}")
    except Exception as e:
        print(f"⚠️ Failed to save registry: {e}")

    global _MEMORY_REGISTRY
    _MEMORY_REGISTRY = registry
    return registry


def get_master_symbol(symbol):
    """Instant O(1) in-memory resolution of multi-broker symbol data."""
    global _MEMORY_REGISTRY
    sym_u = (symbol or "").strip().upper()
    if not _MEMORY_REGISTRY and REGISTRY_FILE.is_file():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as rf:
                _MEMORY_REGISTRY = json.load(rf)
        except Exception:
            pass

    if sym_u in _MEMORY_REGISTRY:
        return _MEMORY_REGISTRY[sym_u]

    # Dynamic fallback
    isin = KNOWN_ISINS.get(sym_u, "")
    return {
        "symbol": sym_u,
        "isin": isin,
        "upstox_key": f"NSE_EQ|{isin}" if isin else f"NSE_EQ|{sym_u}",
        "dhan_id": None,
        "zerodha_symbol": sym_u,
        "exchange": "NSE"
    }


if __name__ == "__main__":
    reg = build_master_registry()
    print("Sample CEMPRO:", get_master_symbol("CEMPRO"))
    print("Sample ENTERO:", get_master_symbol("ENTERO"))
