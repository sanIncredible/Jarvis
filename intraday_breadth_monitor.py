#!/usr/bin/env python3
"""
=============================================================================
JARVIS INTRADAY MARKET BREADTH & MOMENTUM THRUST MONITOR
=============================================================================
Solves Point 2 (Intraday Blindspot), Point 3 (Discipline Leak / FOMO Shield),
and Point 4 (Risk Sizing Unbundling).

Features:
1. Samples all 500 Nifty 500 constituents via Upstox API v2 batch quotes in < 1.5s.
2. Unauthenticated Yahoo Finance batch quote fallback if Upstox token is unavailable.
3. Detects Day-1 Ignition sparks and Selling Climax washouts in real-time intraday.
4. Updates market_regime.json and intraday_breadth.json for scanner & dashboard consumption.
5. Dispatches high-priority Telegram alerts to @Sannin_100M_bot.
6. Decouples intraday scalping risk (₹1k/trade, ₹2k daily cap) from swing risk (0% - 100%).
=============================================================================
"""

import os
import sys
import json
import csv
import io
import time
import html
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
NIFTY500_CSV_CACHE = BASE_DIR / "nifty500_constituents.json"
INTRADAY_BREADTH_FILE = BASE_DIR / "intraday_breadth.json"
MARKET_REGIME_FILE = BASE_DIR / "market_regime.json"
NSE_CACHE_FILE = BASE_DIR / "upstox_nse_cache.json"

NSE_NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"


def load_config() -> Dict[str, Any]:
    """Loads configuration from config_credentials.json."""
    if not CONFIG_FILE.is_file():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error reading {CONFIG_FILE}: {e}")
        return {}


def load_nifty500_universe() -> List[Dict[str, str]]:
    """
    Loads Nifty 500 constituent symbols and ISINs.
    Caches constituents locally for 7 days, updating automatically from NSE India.
    """
    now_ts = time.time()
    if NIFTY500_CSV_CACHE.is_file():
        try:
            mtime = NIFTY500_CSV_CACHE.stat().st_mtime
            if now_ts - mtime < 7 * 86400:
                with open(NIFTY500_CSV_CACHE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if len(data) >= 450:
                        return data
        except Exception:
            pass

    print("🌐 Downloading fresh Nifty 500 constituents from NSE...")
    try:
        req = urllib.request.Request(
            NSE_NIFTY500_CSV_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            constituents = []
            for row in reader:
                sym = (row.get("Symbol") or "").strip()
                isin = (row.get("ISIN Code") or "").strip()
                name = (row.get("Company Name") or "").strip()
                industry = (row.get("Industry") or "").strip()
                if sym and isin:
                    constituents.append({
                        "symbol": sym,
                        "isin": isin,
                        "name": name,
                        "industry": industry
                    })

            if len(constituents) >= 450:
                with open(NIFTY500_CSV_CACHE, "w", encoding="utf-8") as f:
                    json.dump(constituents, f, indent=2)
                print(f"✅ Cached {len(constituents)} Nifty 500 constituents.")
                return constituents
    except Exception as e:
        print(f"⚠️ Could not download Nifty 500 CSV ({e}). Falling back to local cache.")

    # Fallback to existing cache if present
    if NIFTY500_CSV_CACHE.is_file():
        try:
            with open(NIFTY500_CSV_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Secondary fallback to upstox_nse_cache.json
    if NSE_CACHE_FILE.is_file():
        try:
            with open(NSE_CACHE_FILE, "r", encoding="utf-8") as f:
                raw_cache = json.load(f)
                return [{"symbol": k, "isin": v, "name": k, "industry": ""} 
                        for k, v in raw_cache.items() if v.startswith("INE")][:500]
        except Exception:
            pass

    return []


def fetch_upstox_quotes_batch(isins: List[str], token: str) -> Dict[str, Dict[str, Any]]:
    """
    Fetches real-time quotes in batches of 150 instruments from Upstox API v2.
    Returns mapping of ISIN -> quote dict.
    """
    if not token or not isins:
        return {}

    quotes = {}
    batch_size = 150
    chunks = [isins[i:i + batch_size] for i in range(0, len(isins), batch_size)]

    for ch in chunks:
        keys = ",".join([f"NSE_EQ|{isin}" for isin in ch])
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={keys}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Jarvis-Intraday-Breadth"
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=7) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for full_key, item in data.get("data", {}).items():
                    # full_key format: 'NSE_EQ:SYMBOL' or instrument_token 'NSE_EQ|ISIN'
                    itoken = item.get("instrument_token", "")
                    isin = itoken.split("|")[-1] if "|" in itoken else ""
                    if isin:
                        quotes[isin] = item
        except Exception as e:
            print(f"⚠️ Upstox quote batch request failed: {e}")

    return quotes


def fetch_yahoo_quotes_fallback(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Unauthenticated concurrent fallback using Yahoo Finance v8 chart API.
    Does not require crumb or authentication, bypassing HTTP 401.
    """
    if not symbols:
        return {}

    quotes = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def fetch_single(sym: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        clean_sym = sym.replace(".NS", "").strip()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_sym}.NS?interval=1d&range=1d"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result_list = data.get("chart", {}).get("result", [])
                if not result_list:
                    return clean_sym, None
                meta = result_list[0].get("meta", {})
                lp = float(meta.get("regularMarketPrice") or 0.0)
                pc = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0.0)
                if lp > 0 and pc > 0:
                    nc = round(lp - pc, 2)
                    pct = round(((lp - pc) / pc) * 100, 2)
                    return clean_sym, {
                        "last_price": lp,
                        "prev_close": pc,
                        "net_change": nc,
                        "pct_change": pct,
                        "volume": meta.get("regularMarketVolume", 0),
                        "symbol": clean_sym,
                        "source": "Yahoo Finance (v8)"
                    }
        except Exception:
            pass
        return clean_sym, None

    # Sample top 250 liquid symbols for high-speed fallback
    target_symbols = symbols[:250]
    with ThreadPoolExecutor(max_workers=35) as executor:
        for sym, q in executor.map(fetch_single, target_symbols):
            if q:
                quotes[sym] = q

    return quotes


def calculate_intraday_breadth(constituents: List[Dict[str, str]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculates breadth and thrust metrics for the liquid 500 universe.
    """
    token = cfg.get("upstox", {}).get("access_token", "").strip()
    isins = [c["isin"] for c in constituents if c.get("isin")]
    sym_by_isin = {c["isin"]: c["symbol"] for c in constituents}

    data_source = "Upstox API v2"
    upstox_quotes = fetch_upstox_quotes_batch(isins, token) if token else {}

    results = []
    if len(upstox_quotes) >= 300:
        for isin, q in upstox_quotes.items():
            sym = sym_by_isin.get(isin) or q.get("symbol", isin)
            lp = float(q.get("last_price") or 0.0)
            nc = float(q.get("net_change") or 0.0)
            ohlc_close = float(q.get("ohlc", {}).get("close") or 0.0)

            # In Upstox, prev_close is either lp - nc or ohlc_close
            prev_close = lp - nc if (lp - nc) > 0 else ohlc_close
            if prev_close <= 0 or lp <= 0:
                continue

            pct_chg = round((nc / prev_close) * 100, 2)
            results.append({
                "symbol": sym,
                "isin": isin,
                "ltp": lp,
                "prev_close": round(prev_close, 2),
                "net_change": round(nc, 2),
                "pct_change": pct_chg,
                "volume": q.get("volume", 0),
                "day_high": q.get("ohlc", {}).get("high", lp),
                "day_low": q.get("ohlc", {}).get("low", lp)
            })
    else:
        # Fallback to Yahoo Finance v8 chart
        print("⚠️ Upstox token unavailable/expired. Activating concurrent Yahoo Finance v8 fallback...")
        data_source = "Yahoo Finance (v8 Fallback)"
        symbols = [c["symbol"] for c in constituents if c.get("symbol")]
        y_quotes = fetch_yahoo_quotes_fallback(symbols)
        for sym, q in y_quotes.items():
            lp = float(q.get("last_price") or 0.0)
            pc = float(q.get("prev_close") or 0.0)
            if pc <= 0 or lp <= 0:
                continue
            pct_chg = round(((lp - pc) / pc) * 100, 2)
            results.append({
                "symbol": sym,
                "isin": "",
                "ltp": lp,
                "prev_close": pc,
                "net_change": round(lp - pc, 2),
                "pct_change": pct_chg,
                "volume": q.get("volume", 0),
                "day_high": lp,
                "day_low": lp
            })

    total_sampled = len(results)
    if total_sampled == 0:
        # Check if existing cached breadth data exists
        if INTRADAY_BREADTH_FILE.is_file():
            try:
                with open(INTRADAY_BREADTH_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    cached["source"] = "Cached EOD Snapshot (Offline/Weekend)"
                    cached["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
                    return cached
            except Exception:
                pass
        return {"error": "Unable to fetch intraday breadth quotes."}

    advancers = [r for r in results if r["pct_change"] > 0]
    decliners = [r for r in results if r["pct_change"] < 0]
    unchanged = [r for r in results if r["pct_change"] == 0]

    up_4_list = [r for r in results if r["pct_change"] >= 4.0]
    dn_4_list = [r for r in results if r["pct_change"] <= -4.0]
    up_2_list = [r for r in results if r["pct_change"] >= 2.0]
    dn_2_list = [r for r in results if r["pct_change"] <= -2.0]

    all_changes = [r["pct_change"] for r in results]
    avg_change = round(sum(all_changes) / len(all_changes), 2)
    sorted_changes = sorted(all_changes)
    median_change = round(sorted_changes[len(sorted_changes) // 2], 2)

    top_gainers = sorted(results, key=lambda x: x["pct_change"], reverse=True)[:5]
    top_losers = sorted(results, key=lambda x: x["pct_change"])[:5]

    ad_ratio = round(len(advancers) / max(len(decliners), 1), 2)
    thrust_ratio = round(len(up_4_list) / max(len(dn_4_list), 1), 2)
    net_thrust = len(up_4_list) - len(dn_4_list)

    # State Machine Evaluation
    # 1. Day-1 Ignition Spark: Strong institutional thrust
    if len(up_4_list) >= 35 and len(dn_4_list) <= 12 and ad_ratio >= 2.2:
        signal_state = "IGNITION"
        signal_badge = "🟢 DAY-1 IGNITION REVERSAL"
        guidance = "Institutional thrust spark detected! 25% pilot swing risk unlocked."
        swing_multiplier = 0.25
        risk_alert_type = "IGNITION_UNLOCKED"
    # 2. Climax / Washout Panic: Broad liquidation cascade
    elif len(dn_4_list) >= 60 or (ad_ratio <= 0.15 and len(decliners) >= 400):
        signal_state = "WASHOUT"
        signal_badge = "🔴 SELLING CLIMAX / WASHOUT"
        guidance = "Heavy institutional liquidation active. 0% swing risk. SIT ON HANDS."
        swing_multiplier = 0.0
        risk_alert_type = "WASHOUT_LOCKED"
    # 3. Expansion Sweet Spot: Healthy broad participation
    elif len(up_4_list) >= 20 and len(dn_4_list) <= 8 and ad_ratio >= 2.0:
        signal_state = "EXPANSION"
        signal_badge = "🟢 HEALTHY EXPANSION"
        guidance = "Strong breadth tailwind. Breakouts have high follow-through."
        swing_multiplier = 1.0
        risk_alert_type = "EXPANSION_ACTIVE"
    # 4. Selective / Mixed: Stock-picking environment
    elif ad_ratio >= 0.9 and ad_ratio <= 2.0 and len(dn_4_list) < 25:
        signal_state = "SELECTIVE"
        signal_badge = "🟡 SELECTIVE ROTATION"
        guidance = "Mixed breadth. Stick strictly to top relative strength leaders."
        swing_multiplier = 0.50
        risk_alert_type = "SELECTIVE_ROTATION"
    # 5. Choppy / Defensive Drift
    else:
        signal_state = "DEFENSIVE"
        signal_badge = "⚠️ DEFENSIVE / HIGH FAKEOUT RISK"
        guidance = "Weak breadth. 80%+ of breakouts fail. Preserve capital."
        swing_multiplier = 0.0
        risk_alert_type = "DEFENSIVE_CHOP"

    # Risk Parameters Integration
    risk_cfg = cfg.get("risk_parameters", {})
    account_cap = risk_cfg.get("account_capital", 500000)
    intra_cfg = risk_cfg.get("intraday", {})
    swing_cfg = risk_cfg.get("swing", {})

    base_swing_risk = swing_cfg.get("base_risk_per_trade", 10000)
    swing_risk_allowed = int(base_swing_risk * swing_multiplier)

    intra_risk_per_trade = intra_cfg.get("max_risk_per_trade", 1000)
    intra_daily_loss = intra_cfg.get("max_daily_loss", 2000)
    intra_max_open = intra_cfg.get("max_open_trades", 2)

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "time_str": datetime.now().strftime("%H:%M:%S IST"),
        "source": data_source,
        "total_sampled": total_sampled,
        "advancers": len(advancers),
        "decliners": len(decliners),
        "unchanged": len(unchanged),
        "ad_ratio": ad_ratio,
        "up_4_count": len(up_4_list),
        "dn_4_count": len(dn_4_list),
        "up_2_count": len(up_2_list),
        "dn_2_count": len(dn_2_list),
        "thrust_ratio": thrust_ratio,
        "net_thrust": net_thrust,
        "avg_change_pct": avg_change,
        "median_change_pct": median_change,
        "signal_state": signal_state,
        "signal_badge": signal_badge,
        "guidance": guidance,
        "risk_alert_type": risk_alert_type,
        "top_gainers": [{"symbol": r["symbol"], "chg": r["pct_change"], "ltp": r["ltp"]} for r in top_gainers],
        "top_losers": [{"symbol": r["symbol"], "chg": r["pct_change"], "ltp": r["ltp"]} for r in top_losers],
        "risk_matrix": {
            "account_capital": account_cap,
            "swing_allowed": (swing_multiplier > 0),
            "swing_multiplier": swing_multiplier,
            "swing_risk_per_trade": swing_risk_allowed,
            "base_swing_risk": base_swing_risk,
            "intraday_allowed": True,
            "intraday_risk_per_trade": intra_risk_per_trade,
            "intraday_max_daily_loss": intra_daily_loss,
            "intraday_max_open_trades": intra_max_open,
            "intraday_mandatory_flat": "15:15 IST"
        }
    }


def update_market_regime_state(breadth_data: Dict[str, Any]):
    """
    Persists real-time breadth metrics to intraday_breadth.json
    and synchronizes market_regime.json for scanner & dashboard consumption.
    """
    # 1. Write intraday_breadth.json
    try:
        with open(INTRADAY_BREADTH_FILE, "w", encoding="utf-8") as f:
            json.dump(breadth_data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving {INTRADAY_BREADTH_FILE}: {e}")

    # 2. Update market_regime.json
    try:
        existing_regime = {}
        if MARKET_REGIME_FILE.is_file():
            try:
                with open(MARKET_REGIME_FILE, "r", encoding="utf-8") as f:
                    existing_regime = json.load(f)
            except Exception:
                pass

        regime_payload = {
            "updated_at": breadth_data["timestamp"],
            "state_code": breadth_data["signal_state"],
            "state_label": breadth_data["signal_badge"],
            "guidance": breadth_data["guidance"],
            "swing_allocation_pct": int(breadth_data["risk_matrix"]["swing_multiplier"] * 100),
            "swing_risk_per_trade": breadth_data["risk_matrix"]["swing_risk_per_trade"],
            "intraday_risk_per_trade": breadth_data["risk_matrix"]["intraday_risk_per_trade"],
            "intraday_max_daily_loss": breadth_data["risk_matrix"]["intraday_max_daily_loss"],
            "intraday_max_open_trades": breadth_data["risk_matrix"]["intraday_max_open_trades"],
            "fakeout_warning": "HIGH FAKEOUT RISK: 80%+ of long breakouts fail in this regime." if breadth_data["risk_matrix"]["swing_multiplier"] == 0 else "NORMAL EXECUTION",
            "breadth_snapshot": {
                "advancers": breadth_data["advancers"],
                "decliners": breadth_data["decliners"],
                "ad_ratio": breadth_data["ad_ratio"],
                "up_4_count": breadth_data["up_4_count"],
                "dn_4_count": breadth_data["dn_4_count"],
                "net_thrust": breadth_data["net_thrust"]
            }
        }
        with open(MARKET_REGIME_FILE, "w", encoding="utf-8") as f:
            json.dump(regime_payload, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error updating {MARKET_REGIME_FILE}: {e}")


def build_telegram_html(data: Dict[str, Any]) -> str:
    """Formats a clean, robust Telegram alert with proper HTML escaping."""
    badge = html.escape(data.get("signal_badge", ""))
    time_str = html.escape(data.get("time_str", ""))
    source = html.escape(data.get("source", ""))
    guidance = html.escape(data.get("guidance", ""))

    adv = data.get("advancers", 0)
    dec = data.get("decliners", 0)
    ad_ratio = data.get("ad_ratio", 0.0)
    up4 = data.get("up_4_count", 0)
    dn4 = data.get("dn_4_count", 0)
    net_th = data.get("net_thrust", 0)
    th_ratio = data.get("thrust_ratio", 0.0)
    med_chg = data.get("median_change_pct", 0.0)

    rm = data.get("risk_matrix", {})
    swing_risk = rm.get("swing_risk_per_trade", 0)
    swing_mult = int(rm.get("swing_multiplier", 0.0) * 100)
    intra_risk = rm.get("intraday_risk_per_trade", 1000)
    intra_loss = rm.get("intraday_max_daily_loss", 2000)
    intra_max = rm.get("intraday_max_open_trades", 2)

    lines = [
        f"⚡ <b>JARVIS INTRADAY BREADTH PULSE</b> | <code>{time_str}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🚦 <b>REGIME STATUS</b>: <code>{badge}</code>",
        f"📢 <i>{guidance}</i>",
        "",
        "📊 <b>NIFTY 500 LIQUID BREADTH:</b>",
        f"• Advances/Declines: <b>{adv} Adv</b> | <b>{dec} Dec</b> (Ratio: <code>{ad_ratio:.2f}</code>)",
        f"• Momentum Thrust  : <b>🟢 +4% Up: {up4}</b> | <b>🔴 -4% Down: {dn4}</b>",
        f"• Net 4% Thrust    : <b>{net_th:+d}</b> (Thrust Ratio: <code>{th_ratio:.2f}</code>)",
        f"• Universe Median  : <b>{med_chg:+.2f}%</b> [{source}]",
        "",
        "🛡️ <b>MANDATORY RISK MATRIX:</b>",
        f"• 📈 <b>Swing Risk</b>   : <b>₹{swing_risk:,}</b> / trade (<b>{swing_mult}%</b> Risk Alloc)",
        f"• ⚡ <b>Intra Scalp</b>  : <b>₹{intra_risk:,}</b> / trade (Max Cap: <b>₹{intra_loss:,}</b>)",
        f"• 🎯 <b>Max Open Intra</b>: <b>{intra_max} trades max</b> (Flat by 15:15 IST)",
        ""
    ]

    gainers = data.get("top_gainers", [])
    if gainers:
        lines.append("🚀 <b>Top Thrust Leaders:</b>")
        for g in gainers[:4]:
            lines.append(f"  • <code>{html.escape(g['symbol'])}</code>: +{g['chg']:.2f}% (₹{g['ltp']:,.2f})")
        lines.append("")

    losers = data.get("top_losers", [])
    if losers:
        lines.append("🔻 <b>Top Drag / Selloff:</b>")
        for l in losers[:4]:
            lines.append(f"  • <code>{html.escape(l['symbol'])}</code>: {l['chg']:.2f}% (₹{l['ltp']:,.2f})")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📱 <a href='https://sanincredible.github.io/Jarvis/'>Open Live Tablet Dashboard</a>")

    return "\n".join(lines)


def send_telegram_alert(msg_html: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """Sends high-priority Telegram alert."""
    tg = cfg.get("telegram", {})
    if not tg.get("enabled"):
        return False, "Telegram disabled in config"

    token = tg.get("bot_token")
    chat_id = tg.get("chat_id")
    if not token or not chat_id:
        return False, "Missing bot_token or chat_id"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return True, "Delivered"
            return False, str(data)
    except Exception as e:
        return False, str(e)


def main():
    force_run = "--force" in sys.argv or "--test" in sys.argv
    quiet = "--quiet" in sys.argv

    cfg = load_config()
    print("=" * 65)
    print("⚡ JARVIS INTRADAY BREADTH & MOMENTUM THRUST MONITOR")
    print(f"⏰ Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 65)

    constituents = load_nifty500_universe()
    if not constituents:
        print("❌ Could not load Nifty 500 constituents universe.")
        sys.exit(1)

    print(f"📡 Sampling {len(constituents)} stocks from Nifty 500 universe...")
    t0 = time.time()
    breadth = calculate_intraday_breadth(constituents, cfg)
    t1 = time.time()

    if "error" in breadth:
        print(f"❌ Breadth calculation error: {breadth['error']}")
        sys.exit(1)

    print(f"✅ Calculation completed in {t1 - t0:.2f} seconds [{breadth['source']}]")
    print(f"📊 Adv/Dec : {breadth['advancers']} Adv | {breadth['decliners']} Dec (Ratio: {breadth['ad_ratio']:.2f})")
    print(f"🚀 Thrust  : +4% Up: {breadth['up_4_count']} | -4% Down: {breadth['dn_4_count']} (Net: {breadth['net_thrust']:+d})")
    print(f"🚦 Signal  : {breadth['signal_badge']}")
    print(f"📢 Guidance: {breadth['guidance']}")
    print(f"🛡️ Risk    : Swing ₹{breadth['risk_matrix']['swing_risk_per_trade']:,} | Intra ₹{breadth['risk_matrix']['intraday_risk_per_trade']:,}")

    # Persist state
    update_market_regime_state(breadth)
    print(f"💾 Updated {INTRADAY_BREADTH_FILE.name} and {MARKET_REGIME_FILE.name}")

    # Dispatch Telegram alert
    msg_html = build_telegram_html(breadth)
    if not quiet or force_run:
        print("📱 Dispatching Intraday Breadth Pulse to Telegram...")
        ok, res = send_telegram_alert(msg_html, cfg)
        if ok:
            print("✅ Telegram notification delivered successfully!")
        else:
            print(f"⚠️ Telegram dispatch note: {res}")

    print("=" * 65)


if __name__ == "__main__":
    main()
