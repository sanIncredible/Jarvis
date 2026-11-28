#!/usr/bin/env python3
"""
ipo_universe.py
===============
Builds the "fresh listings" universe: every MAINLINE (non-SME) IPO listed on NSE in the last N years
(default 3), merged with the official Nifty IPO Index constituents.

Sources
  1. NSE public-past-issues API (securityType == "Equity" -> mainboard; SME/DEBT/InvIT/REIT dropped).
     Gives issue price + listing date.
  2. NSE EQUITY_L.csv -> confirms the symbol is currently listed and its DATE OF LISTING matches the issue
     (an FPO of an old company, e.g. a follow-on, lists years earlier -> excluded).
  3. nifty_ipo_constituents.json (written by scan_nifty_ipo.fetch_ipo_constituents) -> always included.

Output: ipo_universe.json  {"built_at", "years", "count", "stocks": [{symbol, name, listing_date, issue_price,
         in_nifty_ipo, source}]}. Refreshed when older than REFRESH_DAYS; on any fetch failure the last cache is used.
"""

import csv
import io
import json
import sys
import http.cookiejar
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_FILE = BASE_DIR / "ipo_universe.json"
NIFTY_IPO_CACHE = BASE_DIR / "nifty_ipo_constituents.json"
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
PAST_ISSUES_URL = "https://www.nseindia.com/api/public-past-issues?from_date={f}&to_date={t}&security_type=all"
NSE_HOME = "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
REFRESH_DAYS = 7
LISTING_MATCH_DAYS = 10  # EQUITY_L listing date must be within this many days of the issue's listing date


def _parse_date(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.title() if "%b" in fmt or "%B" in fmt else s, fmt)
        except ValueError:
            continue
    return None


def _to_float(s: Any) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").replace("Rs.", "").strip())
    except (TypeError, ValueError):
        return None


def _opener():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.addheaders = [("User-Agent", UA), ("Accept", "*/*"), ("Referer", "https://www.nseindia.com/")]
    return op


def fetch_past_issues(years: int = 3) -> List[Dict[str, Any]]:
    to_d = datetime.now()
    from_d = to_d - timedelta(days=int(365.25 * years))
    op = _opener()
    op.open(NSE_HOME, timeout=20).read()  # cookie handshake
    url = PAST_ISSUES_URL.format(f=from_d.strftime("%d-%m-%Y"), t=to_d.strftime("%d-%m-%Y"))
    data = json.loads(op.open(url, timeout=30).read().decode("utf-8", errors="ignore"))
    return data if isinstance(data, list) else data.get("data", [])


def fetch_equity_listing_dates() -> Dict[str, Dict[str, Any]]:
    req = urllib.request.Request(EQUITY_L_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8", errors="ignore")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        sym = row.get("SYMBOL", "").upper()
        if sym:
            out[sym] = {"name": row.get("NAME OF COMPANY", sym), "series": row.get("SERIES", "EQ"),
                        "isin": row.get("ISIN NUMBER", ""), "listing_date": _parse_date(row.get("DATE OF LISTING", ""))}
    return out


def build_universe(years: int = 3) -> Dict[str, Any]:
    issues = fetch_past_issues(years)
    listed = fetch_equity_listing_dates()
    stocks: Dict[str, Dict[str, Any]] = {}
    dropped = {"not_mainboard": 0, "not_listed": 0, "fpo_or_mismatch": 0}
    for it in issues:
        if (it.get("securityType") or "").strip() != "Equity":
            dropped["not_mainboard"] += 1
            continue
        sym = (it.get("symbol") or "").strip().upper()
        lst = listed.get(sym)
        if not lst:
            dropped["not_listed"] += 1  # delisted / renamed / not yet listed
            continue
        issue_ld = _parse_date(it.get("listingDate", ""))
        eq_ld = lst["listing_date"]
        if not issue_ld or not eq_ld or abs((eq_ld - issue_ld).days) > LISTING_MATCH_DAYS:
            dropped["fpo_or_mismatch"] += 1
            continue
        stocks[sym] = {"symbol": sym, "name": it.get("company") or lst["name"], "series": lst["series"],
                       "isin": lst["isin"], "listing_date": eq_ld.strftime("%Y-%m-%d"),
                       "issue_price": _to_float(it.get("issuePrice")), "in_nifty_ipo": False, "source": "nse_ipo"}

    nifty = []
    if NIFTY_IPO_CACHE.is_file():
        try:
            nifty = json.loads(NIFTY_IPO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            nifty = []
    for c in nifty:
        sym = (c.get("symbol") or "").upper()
        if not sym:
            continue
        if sym in stocks:
            stocks[sym]["in_nifty_ipo"] = True
            stocks[sym]["industry"] = c.get("industry")
        else:
            ld = (listed.get(sym) or {}).get("listing_date")
            stocks[sym] = {"symbol": sym, "name": c.get("name", sym), "series": c.get("series", "EQ"),
                           "isin": c.get("isin", ""), "listing_date": ld.strftime("%Y-%m-%d") if ld else None,
                           "issue_price": None, "in_nifty_ipo": True, "industry": c.get("industry"),
                           "source": "nifty_ipo_index"}

    out = {"built_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "years": years, "count": len(stocks),
           "dropped": dropped, "stocks": sorted(stocks.values(), key=lambda s: s.get("listing_date") or "")}
    return out


def load_universe(years: int = 3, force: bool = False) -> List[Dict[str, Any]]:
    """Cached universe; rebuilt when stale (> REFRESH_DAYS) or forced. Falls back to the last cache on failure."""
    cached = None
    if UNIVERSE_FILE.is_file():
        try:
            cached = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cached = None
    fresh = False
    if cached and not force:
        try:
            age = datetime.now() - datetime.strptime(cached["built_at"], "%Y-%m-%d %H:%M")
            fresh = age.days < REFRESH_DAYS and cached.get("years") == years
        except Exception:
            fresh = False
    if fresh:
        return cached["stocks"]
    try:
        u = build_universe(years)
        if u["count"] >= 50:  # sanity: a near-empty build means the NSE API misbehaved
            UNIVERSE_FILE.write_text(json.dumps(u, indent=2), encoding="utf-8")
            return u["stocks"]
        print(f"Warning: IPO universe build returned only {u['count']} stocks; keeping cache.", file=sys.stderr)
    except Exception as e:
        print(f"Warning: IPO universe build failed: {e}", file=sys.stderr)
    return (cached or {}).get("stocks", [])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build the last-N-years mainline IPO universe")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    s = load_universe(a.years, force=a.force)
    print(f"{len(s)} stocks; Nifty IPO members: {sum(1 for x in s if x.get('in_nifty_ipo'))}")
