# Jarvis System State & Session Handoff Log — 2026-11-04

> **Date**: Wednesday, November 4, 2026  
> **Status**: Market Session Active (Post-Open)  
> **Primary Purpose**: Single-source-of-truth status document so future Antigravity sessions can immediately resume context without redundant searches.

---

## 1. Executive Summary & Where We Are

* **Core Project**: Jarvis Autonomous Trading System (Upstox Pro & DhanHQ integration, 3-minute ORB Engine, Nifty 500 Positional Swing Scanner, Telegram Command Bot).
* **Current Cloud Deployment**:
  * **Host**: Oracle Cloud Infrastructure (OCI) Always-Free VM (`80.225.210.222`).
  * **User & Dir**: `opc@80.225.210.222:/home/opc/Jarvis`
  * **SSH Key**: `C:\ProjectDir\ssh-key-2026-09-21_new.key`
  * **Active Systemd Service**: `scanner.service` (runs `upstox_tablet_scanner.py` with embedded Telegram Bot engine thread).
  * **Current Feed Mode**: Resilient Yahoo Finance Fallback active (since Upstox token is expired; DhanHQ orderbook active).

---

## 2. Recent Engineering Upgrades (Session of Nov 3, 2026)

### A. Diagnosed Missed Movers (`TRENT` & `ADANIGREEN`)
* `ADANIGREEN`: Failed Stage 1 due to poor close location (< 0.50, closed near day's low) and wide daily range.
* `TRENT`: Trapped by legacy 5-day VCP rule (> 2.5x ATR) because of an outlier bar 5 days ago, even though its **last 3 sessions coiled ultra-tightly (<= 0.97x ATR) into an Inside Day near 20-day high**.

### B. 5 Production Enhancements Integrated into `candidate_scanner.py`
1. **Dual-Timeframe VCP (3D Compression OR Inside Day Exception)**:
   * Tier 1 now accepts tight 3-day coils (<= 1.25x ATR) or Inside Day bars right near the 20-day high (<= 2.2%), preserving setups like `TRENT` and `KOTAKBANK`.
2. **VDU (Volume Dry-Up) Supply Exhaustion Detector**:
   * Identifies institutional supply drying up (RVOL <= 0.60x with low range), awarded the `🧊 VDU (Dry Supply)` badge and ranking boost.
3. **52-Week / All-Time High Proximity**:
   * Evaluates if a stock sits <= 2.5% from its 52-week or 3-month high. Badged with `👑 52W High` (zero overhead resistance).
4. **Tier 3 (🛡️ EMA Pullback Coil)**:
   * Identifies Stage 2 market leaders testing key 10 EMA or 20 EMA moving average support shelves with tight 3-day compression (e.g. `ACMESOLAR`, `HDFCLIFE`).
5. **Normalized Range & Close Location Adaptation**:
   * Stage 1 range cap widened to 2.85% for coiled momentum leaders. Close location threshold softened dynamically to 0.35 for ultra-tight bars (<= 1.5%) to preserve tight dojis.

### C. Watchlist Sync Policy Hardening
* Updated [`sync_to_cloud.py`](file:///C:/ProjectDir/sync_to_cloud.py): Local [`watchlist.txt`](file:///C:/ProjectDir/watchlist.txt) is now the strict master source of truth and replaces remote watchlist files without merging unwanted symbols.

---

## 3. Daily Pre-Breakout Candidate Universe (Nov 4, 2026)

* **Generated**: 2026-11-03 22:17 IST via `candidate_scanner.py`
* **Target Strategy**: 3-minute ORB + Previous Day High (PDH) breakout with Day Low stop loss.
* **Tiers**:
  * **[TIER 1]** 🔥 Pivot Doorstep (<= 2.2% from 20D high) / ⚡ Pivot Ignition
  * **[TIER 2]** 🚀 Base Launchpad (2.2% - 5.0% from 20D high)
  * **[TIER 3]** 🛡️ EMA Pullback Coil (holding 10/20 EMA support shelf)

| # | Symbol | LTP | Tier & Setup | 20D Dist | 5D / 3D VCP | RVOL | Sector | Badges |
| :---: | :--- | :---: | :--- | :---: | :---: | :---: | :--- | :--- |
| **1** | [ANANDRATHI](https://in.tradingview.com/chart/?symbol=NSE:ANANDRATHI) | ₹2,288.00 | **[TIER 1]** 🔥 PIVOT DOORSTEP | **+0.47%** | 1.4x / 1.4x | 0.31x | 🏢 Financial Services | 👑 52W High • 🧊 VDU |
| **2** | [DRREDDY](https://in.tradingview.com/chart/?symbol=NSE:DRREDDY) | ₹1,368.30 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.00%** | 2.1x / 1.0x | 0.87x | ⭐ Pharma Leader (+1.8%) | 👑 52W High |
| **3** | [PERSISTENT](https://in.tradingview.com/chart/?symbol=NSE:PERSISTENT) | ₹6,097.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.62%** | 2.4x / 1.2x | 0.49x | 📈 IT (+0.9%) | 👑 52W High • 🧊 VDU |
| **4** | [INDHOTEL](https://in.tradingview.com/chart/?symbol=NSE:INDHOTEL) | ₹836.05 | **[TIER 1]** 🔥 PIVOT DOORSTEP | **+0.00%** | 1.5x / 1.2x | 0.85x | 🏢 Consumer Services | 👑 52W High |
| **5** | [KOTAKBANK](https://in.tradingview.com/chart/?symbol=NSE:KOTAKBANK) | ₹464.65 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.28%** | 2.7x / 1.0x | 0.75x | 🏢 Financial Services | 👑 52W High |
| **6** | [ETERNAL](https://in.tradingview.com/chart/?symbol=NSE:ETERNAL) | ₹349.45 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.21%** | 2.5x / 1.4x | 0.75x | 🏢 Consumer Services | 👑 52W High |
| **7** | [WIPRO](https://in.tradingview.com/chart/?symbol=NSE:WIPRO) | ₹198.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+1.05%** | 3.0x / 1.6x | 0.38x | 📈 IT (+0.9%) | 👑 52W High • 🧊 VDU • 📦 Inside Day |
| **8** | [JSWSTEEL](https://in.tradingview.com/chart/?symbol=NSE:JSWSTEEL) | ₹1,320.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.17%** | 2.5x / 2.1x | 1.25x | ⭐ Metal Leader (+2.2%) | 👑 52W High |
| **9** | [NYKAA](https://in.tradingview.com/chart/?symbol=NSE:NYKAA) | ₹353.90 | **[TIER 1]** 🔥 PIVOT DOORSTEP | **+0.73%** | 2.1x / 0.8x | 1.05x | 🏢 Consumer Services | 👑 52W High • 📦 Inside Day |
| **10** | [ITCHOTELS](https://in.tradingview.com/chart/?symbol=NSE:ITCHOTELS) | ₹171.03 | **[TIER 1]** 🔥 PIVOT DOORSTEP | **+1.93%** | 1.5x / 0.9x | 0.42x | 🏢 Consumer Services | 👑 52W High • 🧊 VDU |
| **11** | [ATHERENERG](https://in.tradingview.com/chart/?symbol=NSE:ATHERENERG) | ₹1,795.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.80%** | 2.3x / 1.9x | 0.63x | 📈 Auto (+0.4%) | 👑 52W High |
| **12** | [TVSMOTOR](https://in.tradingview.com/chart/?symbol=NSE:TVSMOTOR) | ₹4,303.20 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.24%** | 2.0x / 1.2x | 0.72x | 📈 Auto (+0.4%) |  |
| **13** | [SONACOMS](https://in.tradingview.com/chart/?symbol=NSE:SONACOMS) | ₹900.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+1.23%** | 2.0x / 1.4x | 0.75x | 📈 Auto (+0.4%) | 👑 52W High • 📦 Inside Day |
| **14** | [TRENT](https://in.tradingview.com/chart/?symbol=NSE:TRENT) | ₹3,036.50 | **[TIER 1]** 🔥 PIVOT DOORSTEP | **+0.87%** | 3.2x / 1.0x | 0.64x | 🏢 Consumer Services |  |
| **15** | [GLENMARK](https://in.tradingview.com/chart/?symbol=NSE:GLENMARK) | ₹2,408.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.50%** | 2.4x / 2.0x | 1.55x | ⭐ Pharma Leader (+1.8%) |  |
| **16** | [HCLTECH](https://in.tradingview.com/chart/?symbol=NSE:HCLTECH) | ₹1,439.10 | **[TIER 1]** ⚡ PIVOT IGNITION | **+1.94%** | 2.4x / 1.2x | 0.49x | 📈 IT (+0.9%) | 👑 52W High • 🧊 VDU • 📦 Inside Day |
| **17** | [AUROPHARMA](https://in.tradingview.com/chart/?symbol=NSE:AUROPHARMA) | ₹1,694.50 | **[TIER 1]** ⚡ PIVOT IGNITION | **+1.20%** | 2.0x / 1.1x | 1.60x | ⭐ Pharma Leader (+1.8%) |  |
| **18** | [ONGC](https://in.tradingview.com/chart/?symbol=NSE:ONGC) | ₹232.17 | **[TIER 1]** ⚡ PIVOT IGNITION | **+1.13%** | 2.7x / 2.4x | 1.37x | ⭐ Energy Leader (+1.5%) | 📦 Inside Day |
| **19** | [TECHM](https://in.tradingview.com/chart/?symbol=NSE:TECHM) | ₹1,789.10 | **[TIER 1]** 🔥 PIVOT DOORSTEP | **+3.03%** | 1.4x / 0.7x | 0.39x | 📈 IT (+0.9%) | 🧊 VDU |
| **20** | [ICICIBANK](https://in.tradingview.com/chart/?symbol=NSE:ICICIBANK) | ₹1,424.50 | **[TIER 1]** ⚡ PIVOT IGNITION | **+0.47%** | 2.5x / 2.0x | 1.39x | 🏢 Financial Services | 👑 52W High |
| **21** | [TATACOMM](https://in.tradingview.com/chart/?symbol=NSE:TATACOMM) | ₹1,766.00 | **[TIER 2]** 🚀 BASE LAUNCHPAD | **+5.36%** | 1.8x / 1.5x | 0.42x | 🏢 Telecommunication | 🧊 VDU |
| **22** | [ACMESOLAR](https://in.tradingview.com/chart/?symbol=NSE:ACMESOLAR) | ₹416.70 | **[TIER 3]** 🛡️ EMA PULLBACK COIL | **+8.15%** | 1.5x / 1.1x | 0.59x | ⭐ Energy Leader (+1.5%) | 🧊 VDU • 📦 Inside Day |
| **23** | [ONESOURCE](https://in.tradingview.com/chart/?symbol=NSE:ONESOURCE) | ₹1,568.70 | **[TIER 2]** 🚀 BASE LAUNCHPAD | **+4.52%** | 1.6x / 1.0x | 0.39x | ⭐ Pharma Leader (+1.8%) | 🧊 VDU |
| **24** | [HDFCLIFE](https://in.tradingview.com/chart/?symbol=NSE:HDFCLIFE) | ₹525.50 | **[TIER 3]** 🛡️ EMA PULLBACK COIL | **+7.13%** | 1.5x / 1.4x | 1.13x | 🏢 Financial Services | 📦 Inside Day |
| **25** | [SANSERA](https://in.tradingview.com/chart/?symbol=NSE:SANSERA) | ₹4,228.00 | **[TIER 1]** ⚡ PIVOT IGNITION | **+3.19%** | 2.1x / 1.5x | 0.86x | 📈 Auto (+0.4%) |  |

---

## 4. Current Market Session & Automated Crons (Nov 4, 2026)

* **08:30 AM IST**: `check_tokens.py --notify` -> DhanHQ Active, Upstox Token Expired (HTTP 401).
* **09:10 AM IST**: `candidate_scanner.py --morning-card` -> Dispatched candidate briefing card to Telegram.
* **09:14 AM IST**: `pre_market_summary.py` -> Dispatched pre-open situational awareness card.
  * **Market Regime**: `SELECTIVE ROTATION (Half Size)` (50% position sizing, demand 2x volume confirmation).
  * **Nifty 50**: Gap-up +1.29% (₹23,742.25).
  * **Leading Sectors**: FMCG (+3.25%), Realty (+2.00%), Auto (+1.82%).
  * **Lagging Sectors**: Metal (-0.69%), Energy (-0.29%).
* **09:14 AM IST**: `sync_journal.py` -> Morning open positions refresh completed.
* **09:15 AM IST**: Market opened. `scanner.service` active and executing 3-minute scans seamlessly via fallback.

---

## 5. Active Watchlist (`watchlist.txt`)

```text
TATAELXSI
NIFTY
PCJEWELLER
OAL
WESTLIFE
NSE
INDGN
CEMPRO
NYKAA
TIPSMUSIC
ENTERO
AARTIDRUGS
INDEGENE
```

---

## 6. How to Resume Work / Operational Cheatsheet

1. **If Broker Feed Needs Token Refresh**:
   * Run [`Refresh_Tokens.bat`](file:///C:/ProjectDir/Refresh_Tokens.bat) or [`auto_token_generator.py`](file:///C:/ProjectDir/auto_token_generator.py) locally to renew Upstox access token, then sync credentials to OCI via [`sync_to_cloud.py`](file:///C:/ProjectDir/sync_to_cloud.py).
2. **Promoting Candidates to Live Scanner**:
   * Add any symbol from the table above into [`watchlist.txt`](file:///C:/ProjectDir/watchlist.txt) or send `/add <SYMBOL>` in Telegram bot `@Sannin_100M_bot`.
3. **Inspecting Cloud Scanner Services**:
   ```powershell
   python -c "import subprocess; subprocess.run(['ssh', '-i', r'C:\ProjectDir\ssh-key-2026-09-21_new.key', 'opc@80.225.210.222', 'journalctl -u scanner.service -n 25 --no-pager'])"
   ```
4. **Deploying Updates to Cloud**:
   ```powershell
   python C:\ProjectDir\sync_to_cloud.py
   ```


---

## 7. Dashboard EOD Candidates Tab Integration (10:15 IST)

* **Integrated Tab Navigation in Dashboard**:
  - Tab 1: **⚡ 3m ORB Triggers** (Live watchlist, 3m candle engine, signals, and hover chart popup).
  - Tab 2: **🎯 EOD Candidates** (Tier-wise pre-breakout swing candidates filtered yesterday EOD).
* **Tier-Wise Layout**:
  - **Tier 1 (🔥 Pivot Doorstep & Ignition)**: 21 setups sitting $\le 2.2\%$ from 20D pivot high.
  - **Tier 2 (🚀 Base Launchpad)**: 2 setups ($2.2\% - 5.0\%$ from 20D high).
  - **Tier 3 (🛡️ EMA Pullback Coil)**: 2 setups resting on rising 10/20 EMA support.
* **Corporate Proxy & Bandwidth Optimization**:
  - Ultra-lightweight payload (~900 bytes embedded in `data.json`, no heavy candle histories transferred).
  - Strictly read-only clickable TradingView pills (`https://in.tradingview.com/chart/?symbol=NSE:{sym}`) for direct single-tap analysis.
  - Zero hover popup / chart preview overhead on candidates tab to preserve minimum bandwidth across Git/OCI/laptop connections.
  - No delete endpoints or outbound mutation traffic to ensure full compatibility behind corporate proxies.
* **Live Deployment**: Pushed live to GitHub Pages (`https://sanincredible.github.io/Jarvis/`) and OCI Cloud VM (`80.225.210.222`).

---

## 8. Unlogged Swing Positions Reconciliation & VM Sync (12:30 - 13:00 IST)

* **Discovered Unlogged Positions in Holdings**:
  - Reconciled 4 active swing positions sitting in broker holdings without active journal tracking:
    - **Zerodha CNC**: `KROSS` (SL: ₹265.40 | Target: ₹326.00 | Notes: 5D Low SL)
    - **Zerodha CNC**: `NSE` (SL: ₹1746.00 | Target: ₹1880.00 | Notes: Structural SL)
    - **Dhan CNC/MTF**: `BHARTIHEXA` (SL: ₹1620.00 | Target: ₹1850.00 | Notes: 20 EMA trail)
    - **Dhan CNC/MTF**: `TATACONSUM` (SL: ₹1000.00 | Target: ₹1120.00 | Notes: Cost Breakeven)
  - Existing logged position: `ENTERO` (Dhan).
* **Implementation Details**:
  - Saved parameters in [`tracked_holdings.json`](file:///C:/ProjectDir/tracked_holdings.json).
  - Updated [`order_engine.py`](file:///C:/ProjectDir/order_engine.py) (`fetch_all_positions()`) to merge these tracked holdings into the active position feed.
  - Reconciled [`Journal.xlsx`](file:///C:/ProjectDir/Journal.xlsx), created local backup (`Journal_backup_20261104_125236.xlsx`), and marked `AARTIDRUGS` AMO order as `CANCELLED` in [`orders_log.json`](file:///C:/ProjectDir/orders_log.json).
* **OCI Cloud VM Verification**:
  - Pushed updated files to OCI VM (`80.225.210.222:/home/opc/Jarvis`).
  - Remote verification confirmed all 5 active positions:
    - `['TATACONSUM', 'BHARTIHEXA', 'ENTERO', 'KROSS', 'NSE']`
    - Aggregate: Count: 5 | Total PnL: +₹15,494.90 | Total Exposure: ~₹5,99,098.
  - `scanner.service` confirmed **Active & running** (running 3-minute scan cycles with embedded Telegram Bot).

---

## 9. Value at Risk (VaR) Integration Across Position Reports (14:30 IST)

* **Definition**:
  - Exact rupee loss incurred if the current Stop-Loss price is triggered.
  - If $SL \ge Entry$: Risk is strictly `₹0.00` (Breakeven / Risk-Free Free Roll).
  - If $SL < Entry$: $VaR = (Entry - SL) \times Qty$.
* **Integrated Touchpoints**:
  1. [`order_engine.py`](file:///C:/ProjectDir/order_engine.py):
     - `fetch_all_positions()`: Calculates `value_at_risk`, `var_pct`, `is_risk_free`, and portfolio-wide `total_var` & `total_var_pct`.
     - `get_all_open_positions_with_trailing_sl()`: Calculates both initial VaR and recommended trailing VaR (`rec_value_at_risk`).
  2. [`telegram_bot.py`](file:///C:/ProjectDir/telegram_bot.py):
     - `/positions` card: Shows per-stock SL + VaR and total portfolio VaR (`🛡️ ₹14,864.47 (2.48% of exposure)`).
     - `/trail` cockpit: Shows current VaR side-by-side with recommended trailing VaR (`➔ Rec: 🟢 ₹0.00`).
     - Danger SL surveillance alerts: Real-time VaR loss displayed.
  3. [`sync_journal.py`](file:///C:/ProjectDir/sync_journal.py):
     - EOD Telegram card: Appends VaR for each active open trade and portfolio summary.
* **Live Deployment**: Deployed to OCI VM (`80.225.210.222`) and restarted `scanner.service`.

---

## 10. Autonomous Trailing Order Fix & Exchange Tick Size Enforcement (14:43 IST)

* **Root Cause of Duplicate BHARTIHEXA Orders**:
  - The autonomous trailing worker detected `BHARTIHEXA` up **+3.98% / +2.1R** and triggered an automated Breakeven Stop-Loss ratchet (Trigger: ₹1,653.50).
  - Limit price calculation (`1653.50 * 0.998 = 1650.19`) generated a price not divisible by the NSE **₹0.05 tick size**, causing instant exchange OMS rejection (`EXCH:16283`).
  - Because the order failed, the cooldown timer was not set, causing the 60s background surveillance loop to retry repeatedly.
* **Fix Applied**:
  - Implemented [`round_to_tick()`](file:///C:/ProjectDir/order_engine.py#L53) across Upstox, Dhan, and Zerodha SL order engines to strictly round all trigger and limit prices to multiples of ₹0.05.
  - Implemented 30-minute cooldown backoff and error alerting on failures in [`telegram_bot.py`](file:///C:/ProjectDir/telegram_bot.py).
  - Automatically updates [`tracked_holdings.json`](file:///C:/ProjectDir/tracked_holdings.json) upon successful ratchet.
* **Verification**:
  - `BHARTIHEXA` order ID `221261104657003` (Trigger: ₹1,653.50 | Limit: ₹1,650.20) was submitted and **CONFIRMED (Status: PENDING)** by Dhan and the exchange.
  - Retries stopped completely. Zero duplicate orders.

---

## 11. TATACONSUM Trailing Stop-Loss Active & Confirmed (14:50 IST)

* **Holding Classification Fix**:
  - `TATACONSUM` is held under **MTF** (`mtf_qty: 101`), which previously caused an RMS rejection when submitted as CNC.
  - Updated [`order_engine.py`](file:///C:/ProjectDir/order_engine.py) to dynamically map Dhan holdings to `MTF` if `mtf_qty > 0`.
* **Dhan Exchange SL Placed**:
  - **Order ID**: `221261104666203`
  - **Symbol**: `TATACONSUM` (Qty: 101, Product: MTF)
  - **Trigger Price**: **₹1,004.00** | **Limit Price**: **₹1,002.00** (Round number pricing)
  - **Status**: 🟢 **PENDING (CONFIRMED by NSE/Dhan RMS)**
* **Portfolio Risk Metrics**:
  - Both `TATACONSUM` and `BHARTIHEXA` are now **100% Risk-Free / Breakeven runners (VaR = ₹0.00)**.
  - Overall Portfolio Value at Risk reduced to **₹11,454.71** (1.91% of portfolio exposure).

---

## 12. Telegram Supergroup Forum Topic Architecture & Alert Segregation (15:45 IST)

* **Objective**:
  - Prevent alert clutter and cross-talk by segregating different trading alerts into dedicated Telegram Forum Topics inside a single Supergroup (`group_id: -1004363626016`).
* **Topic Routing Matrix**:
  - **Topic 8 (`🎯 ORB Breakouts`)**: Real-time 3-minute dynamic ORB signals & Pine Script parity alerts (`orb_signals`).
  - **Topic 9 (`🛡️ Risk & Trailing`)**: Autonomous Value-at-Risk (VaR) telemetry, danger SL proximity warnings (LTP $\le 0.85\%$ from SL), and Breakeven ratchets (`risk_trailing`).
  - **Topic 10 (`🛒 Orders & Execution`)**: 1-tap Buy/Exit previews, fills, and broker order execution receipts (`orders`).
  - **Topic 11 (`📊 Reports & Journal`)**: 09:00 IST Morning Candidate Briefing, 09:14 Pre-Market summary, intraday market breadth, and 15:45 EOD Trade Journal (`reports`).
  - **Fallback**: Any unmapped alert or missing group configuration automatically routes safely to personal DM (`chat_id: 5066630232`).
* **Implemented Features**:
  1. [`telegram_bot.py`](file:///C:/ProjectDir/telegram_bot.py):
     - Added `get_telegram_extended_config()`, `get_topic_target()`, `send_topic_alert()`, and `send_topic_alert_async()`.
     - In-Thread Context: Bot listener reads `message_thread_id` and replies **directly into the same topic thread** where the command was issued.
     - Security: Restricted interactive inline buttons and group command execution strictly to admin user ID `5066630232`.
     - Added `/topics` (displays configured topic mappings and chat info) and `/settopic <name> <id>`.
  2. [`upstox_tablet_scanner.py`](file:///C:/ProjectDir/upstox_tablet_scanner.py):
     - Updated `send_telegram_alert` and `send_telegram_alert_async` with `topic_name="orb_signals"` routing to Topic 8.
  3. [`candidate_scanner.py`](file:///C:/ProjectDir/candidate_scanner.py), [`sync_journal.py`](file:///C:/ProjectDir/sync_journal.py), [`pre_market_summary.py`](file:///C:/ProjectDir/pre_market_summary.py), [`intraday_breadth_monitor.py`](file:///C:/ProjectDir/intraday_breadth_monitor.py):
     - Updated report dispatches to route to Topic 11 (`reports`).
* **Verification & Cloud Deployment**:
  - Dispatched verified test alerts across all 4 topics (Message IDs 20, 21, 22, 23 confirmed delivered by Telegram API).
  - Deployed to Oracle Cloud VM (`80.225.210.222`) via [`sync_to_cloud.py`](file:///C:/ProjectDir/sync_to_cloud.py).
  - `scanner.service` restarted and confirmed **active & running** with background surveillance and topic-aware command bot.


---

## 13. P0 & P1 Trading Engine Hardening (Overnight SL Protection & Atomic Trailing)

### Overview
Addressed two critical market microstructure vulnerabilities discovered during the end-to-end engine audit:
1. **P0 (Overnight SL Expiration & Direction-Aware Short VaR)**:
   - Indian stock exchanges (NSE/BSE) automatically cancel all pending DAY orders at 15:30 IST market close. Swing trades held overnight (`TATACONSUM`, `BHARTIHEXA`, `ENTERO`, `NSE`, `KROSS`) lost their hard stop losses at 15:30 IST and would be completely unprotected at the 09:15 AM market open next morning.
   - Fixed direction-unaware VaR calculation where short positions (`qty < 0`, e.g. `MOTHERSON`) produced negative VaR, subtracting risk from total portfolio VaR and falsely marking underwater short positions as "Risk-Free".
2. **P1 (Atomic Order Modification on Trailing Ratchets)**:
   - Replaced risky cancel-and-replace trailing logic (which previously cancelled the old SL, slept 0.6s, and placed a new SL—creating a window where the position had zero stop loss) with native atomic `PUT` order modification directly with broker RMS.

---

### Key Implementations

#### 1. Direction-Aware Short Position VaR Math ([`order_engine.py`](file:///C:/ProjectDir/order_engine.py#L1563-L1605), [`sync_journal.py`](file:///C:/ProjectDir/sync_journal.py#L1065-L1085), [`telegram_bot.py`](file:///C:/ProjectDir/telegram_bot.py#L1414-L1440))
* **Formula & Logic**:
  - `is_short = qty < 0`
  - **Short Positions**:
    - Fallback SL: `round(buy_avg * 1.025, 2)` (2.5% above entry to cap upside loss).
    - Breakeven condition: `sl <= buy_avg and sl > 0` (SL trailed downwards to entry or below).
    - Value at Risk: `var_inr = max(0.0, round((sl - buy_avg) * abs(qty), 2))` if `sl > buy_avg` else `0.0`.
  - **Long Positions**:
    - Fallback SL: `round(buy_avg * 0.975, 2)` (2.5% below entry).
    - Breakeven condition: `sl >= buy_avg and buy_avg > 0`.
    - Value at Risk: `var_inr = max(0.0, round((buy_avg - sl) * qty, 2))` if `sl < buy_avg` else `0.0`.
* **Empirical Verification**:
  - `MOTHERSON` (`Qty: -501`, `Avg: 158.06`): Previously `-₹1978.95` (falsely risk-free). Now correctly calculated as `₹1,978.95` positive risk (`RiskFree: False`, `Type: SHORT`).
  - Total Portfolio VaR corrected from `₹9,475.76` to `₹13,433.66` (exact directional risk aggregate).

#### 2. Atomic Order Modification Engine ([`order_engine.py`](file:///C:/ProjectDir/order_engine.py#L1080-L1220))
* Added native broker modification APIs:
  - `modify_upstox_stop_loss_order(order_id, quantity, trigger_price, limit_price)`: `PUT https://api.upstox.com/v2/order/modify`
  - `modify_dhan_stop_loss_order(order_id, quantity, trigger_price, limit_price)`: `PUT https://api.dhan.co/v2/orders/{order_id}`
  - `modify_zerodha_stop_loss_order(order_id, quantity, trigger_price, limit_price)`: `PUT https://api.kite.trade/orders/regular/{order_id}`
  - `modify_broker_stop_loss(broker, order_id, quantity, new_sl_price, transaction_type="SELL")`: Unified broker dispatcher.
* Added live orderbook inspector:
  - `get_pending_stop_loss_order(symbol, broker=None)`: Queries live broker orderbooks (`/v2/orders`, `/v2/order/retrieve-all`, `/orders`) and returns active pending trigger details.
* Updated `ratchet_stop_loss_to_breakeven()`:
  - Queries broker orderbook first via `get_pending_stop_loss_order()`.
  - If pending SL exists: atomically modifies it via `modify_broker_stop_loss()` (zero naked exposure window).
  - Only falls back to placement if no pending order exists or modify was rejected by broker RMS.

#### 3. Overnight Stop-Loss Auto-Rearm Engine ([`order_engine.py`](file:///C:/ProjectDir/order_engine.py#L2250-L2450))
* `rearm_overnight_stop_losses(notify=True, force=False)`:
  - Inspects all open positions across Dhan, Zerodha, and Upstox against live broker orderbooks.
  - Detects unprotected positions lacking active exchange SL orders.
  - Resolves target SL levels from `tracked_holdings.json`, `orders_log.json`, or default 2.5% structural buffers.
  - Validates pre-flight exchange rule (`LTP > SL` for Sell SL, `LTP < SL` for Buy SL) to alert if a position has gapped underwater overnight.
  - Submits fresh SL orders on the exchange when market opens.
  - Updates `orders_log.json` and `tracked_holdings.json` with new order IDs.
  - Dispatches full receipt card to Telegram Topic 10 (`orders`) and Topic 9 (`risk_trailing`).
* Telegram Bot Command:
  - Added `/rearm` and `/armsl` to `dispatch_command` in [`telegram_bot.py`](file:///C:/ProjectDir/telegram_bot.py).
  - Outside market hours: provides comprehensive audit of all 6 positions armed for market open.
  - During market hours or with `/rearm force`: executes live placement.
* OCI VM Morning Crontab:
  - Added cron job at **09:15:05 AM IST** (Mon–Fri) on OCI VM:
    `15 9 * * 1-5 cd /home/opc/Jarvis && /usr/bin/python3 -c "import time; time.sleep(5); from order_engine import rearm_overnight_stop_losses; rearm_overnight_stop_losses(notify=True)" >> /home/opc/Jarvis/rearm_sl.log 2>&1`

---

### Deployment & Status
* **Local Compilation**: `order_engine.py`, `sync_journal.py`, `telegram_bot.py` compiled cleanly (`python -m py_compile`).
* **Cloud Sync**: Synced to GitHub repo and OCI VM via [`sync_to_cloud.py`](file:///C:/ProjectDir/sync_to_cloud.py).
* **OCI VM Crontab**: Successfully verified with `crontab -l` on `80.225.210.222`.
* **OCI Service**: `scanner.service` active and running (PID `571371`).
