#!/usr/bin/env python3
"""
⚡ JARVIS UPSTOX V3 MARKET DATA WEBSOCKET STREAMER
=============================================================================
Provides institutional-grade, zero-latency streaming market data:
1. Connects to Upstox Market Data Feed V3 using protobuf streaming.
2. Streams real-time tick-by-tick quotes (LTP, OHLC, Volume) for active watchlist.
3. Automatically maps instrument keys (NSE_EQ|ISIN) back to stock tickers.
4. Thread-safe background execution with automatic reconnect & REST fallback bridge.
"""

import os
import sys
import json
import time
import threading
from typing import Dict, List, Callable, Optional, Any
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
UPSTOX_TOKEN_FILE = BASE_DIR / "upstoxtoken.txt"


def load_upstox_token() -> str:
    """Loads current Upstox token from config_credentials.json or upstoxtoken.txt."""
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                tok = d.get("upstox", {}).get("access_token", "").strip()
                if tok:
                    return tok
        except Exception:
            pass

    if UPSTOX_TOKEN_FILE.is_file():
        try:
            with open(UPSTOX_TOKEN_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


class UpstoxWebSocketFeed:
    """
    Manages continuous WebSocket streaming connection to Upstox Market Data Feed V3.
    """

    def __init__(self, symbols: List[str], on_tick: Optional[Callable[[str, float, Dict[str, Any]], None]] = None):
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.on_tick = on_tick
        self.is_running = False
        self.is_connected = False
        self.streamer = None
        self.thread = None
        self.key_to_symbol: Dict[str, str] = {}
        self.symbol_to_key: Dict[str, str] = {}
        self.latest_quotes: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self._last_tick_time = 0.0
        self._last_connected_time = 0.0

        # Build instrument key map
        self._build_key_mappings()

    def _build_key_mappings(self):
        """Resolves instrument keys for each watchlist symbol."""
        try:
            from upstox_tablet_scanner import get_instrument_key
            for sym in self.symbols:
                key = get_instrument_key(sym)
                self.symbol_to_key[sym] = key
                self.key_to_symbol[key] = sym
                # Also handle alternative delimiter formats
                self.key_to_symbol[key.replace("|", ":")] = sym
                self.key_to_symbol[key.replace(":", "|")] = sym
        except Exception as e:
            print(f"⚠️ Error resolving instrument keys for WebSocket: {e}")

    def _extract_tick_data(self, key: str, feed_val: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parses decoded Protobuf dict from Upstox V3 Market Data Feed."""
        try:
            ltp = 0.0
            close = 0.0
            high = 0.0
            low = 0.0
            open_p = 0.0
            volume = 0

            # Mode 1: LTPC feed
            ltpc = feed_val.get("ltpc") or {}
            if ltpc:
                ltp = float(ltpc.get("ltp") or 0.0)
                close = float(ltpc.get("cp") or 0.0)

            # Mode 2: Full market feed (fullFeed -> marketFF)
            full_feed = feed_val.get("fullFeed", {})
            market_ff = full_feed.get("marketFF", {})
            if market_ff:
                m_ltpc = market_ff.get("ltpc", {})
                if m_ltpc:
                    ltp = float(m_ltpc.get("ltp") or ltp)
                    close = float(m_ltpc.get("cp") or close)
                volume = int(market_ff.get("vtt") or 0)
                ohlc_list = market_ff.get("marketOHLC", {}).get("ohlc", [])
                for ohlc in ohlc_list:
                    # Daily interval candle
                    if ohlc.get("interval") in ("1d", "day", "I1D"):
                        open_p = float(ohlc.get("open") or 0.0)
                        high = float(ohlc.get("high") or 0.0)
                        low = float(ohlc.get("low") or 0.0)
                        close = float(ohlc.get("close") or close)

            # Mode 3: Index feed (fullFeed -> indexFF)
            index_ff = full_feed.get("indexFF", {})
            if index_ff:
                i_ltpc = index_ff.get("ltpc", {})
                if i_ltpc:
                    ltp = float(i_ltpc.get("ltp") or ltp)
                    close = float(i_ltpc.get("cp") or close)

            if ltp > 0:
                return {
                    "last_price": ltp,
                    "ltp": ltp,
                    "close": close,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "timestamp": time.time()
                }
        except Exception:
            pass
        return None

    def _on_ws_open(self, *args):
        self.is_connected = True
        self._last_connected_time = time.time()
        print(f"⚡ [WebSocket] Upstox V3 Market Data Feed Connected ({len(self.symbol_to_key)} instruments streaming)")

    def _on_ws_message(self, message: Dict[str, Any], *args):
        self._last_tick_time = time.time()
        feeds = message.get("feeds", {}) if isinstance(message, dict) else {}
        for key, val in feeds.items():
            sym = self.key_to_symbol.get(key)
            if not sym:
                # Try prefix split
                clean_k = key.replace(":", "|")
                sym = self.key_to_symbol.get(clean_k)

            if not sym:
                continue

            tick = self._extract_tick_data(key, val)
            if tick and tick["ltp"] > 0:
                with self.lock:
                    self.latest_quotes[sym] = tick

                if self.on_tick:
                    try:
                        self.on_tick(sym, tick["ltp"], tick)
                    except Exception as ex:
                        print(f"Error in on_tick callback for {sym}: {ex}")

    def _on_ws_error(self, *args):
        self.is_connected = False
        err = args[0] if args else "Unknown error"
        print(f"⚠️ [WebSocket] Feed Error: {err}")

    def _on_ws_close(self, *args):
        self.is_connected = False
        print(f"🔒 [WebSocket] Feed Closed: {args}")

    def start(self) -> bool:
        """Starts WebSocket streaming connection in background daemon thread."""
        tok = load_upstox_token()
        if not tok:
            print("⚠️ [WebSocket] Cannot start feed: Upstox access token missing.")
            return False

        try:
            import upstox_client
        except ImportError:
            print("⚠️ [WebSocket] upstox_client not installed. Falling back to REST polling.")
            return False

        keys = list(self.symbol_to_key.values())
        if not keys:
            print("⚠️ [WebSocket] No instrument keys resolved for streaming.")
            return False

        configuration = upstox_client.Configuration()
        configuration.access_token = tok

        try:
            self.streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(configuration),
                keys,
                "full"
            )
            self.streamer.on("open", self._on_ws_open)
            self.streamer.on("message", self._on_ws_message)
            self.streamer.on("error", self._on_ws_error)
            self.streamer.on("close", self._on_ws_close)
            self.streamer.auto_reconnect(True, interval=5, retry_count=5)

            self.is_running = True

            def _runner():
                try:
                    self.streamer.connect()
                except Exception as e:
                    self.is_connected = False
                    print(f"⚠️ [WebSocket] Connection exception: {e}")

            self.thread = threading.Thread(target=_runner, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            print(f"⚠️ [WebSocket] Initialization failed: {e}")
            return False

    def stop(self):
        """Stops the WebSocket streamer gracefully."""
        self.is_running = False
        self.is_connected = False
        if self.streamer:
            try:
                self.streamer.disconnect()
            except Exception:
                pass

    def update_symbols(self, new_symbols: List[str]):
        """Dynamically updates watchlist subscription while streamer is running."""
        clean = [s.strip().upper() for s in new_symbols if s.strip()]
        new_set = set(clean)
        old_set = set(self.symbols)

        added = list(new_set - old_set)
        removed = list(old_set - new_set)

        if not added and not removed:
            return

        self.symbols = clean
        self._build_key_mappings()

        if self.streamer and self.is_connected:
            try:
                if removed:
                    remove_keys = [self.symbol_to_key[s] for s in removed if s in self.symbol_to_key]
                    if remove_keys:
                        self.streamer.unsubscribe(remove_keys)
                if added:
                    add_keys = [self.symbol_to_key[s] for s in added if s in self.symbol_to_key]
                    if add_keys:
                        self.streamer.subscribe(add_keys, "full")
                print(f"⚡ [WebSocket] Updated subscriptions: +{len(added)} / -{len(removed)}")
            except Exception as e:
                print(f"⚠️ [WebSocket] Failed to update subscriptions: {e}")

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns latest streamed quote for a symbol."""
        with self.lock:
            return self.latest_quotes.get(symbol.upper())

    def get_all_latest_quotes(self) -> Dict[str, Dict[str, Any]]:
        """Returns snapshot of all latest streamed quotes."""
        with self.lock:
            return dict(self.latest_quotes)

    def is_healthy(self) -> bool:
        """Returns True if WebSocket is connected and has received ticks within 15s or just connected."""
        if not self.is_connected:
            return False
        now = time.time()
        return (now - self._last_tick_time < 15.0) or (now - self._last_connected_time < 15.0)


if __name__ == "__main__":
    from upstox_tablet_scanner import get_active_watchlist
    syms = get_active_watchlist()[:5]
    print(f"Testing UpstoxWebSocketFeed with {len(syms)} symbols: {syms}")

    def on_tick_print(sym, ltp, tick):
        print(f"⚡ TICK: {sym} -> ₹{ltp:,.2f} (vol: {tick.get('volume', 0)})")

    feed = UpstoxWebSocketFeed(syms, on_tick=on_tick_print)
    ok = feed.start()
    print(f"Feed start return: {ok}")
    time.sleep(4)
    feed.stop()
    print("Test finished.")
