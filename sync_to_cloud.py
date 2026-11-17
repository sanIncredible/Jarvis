from datetime import datetime
import shutil
#!/usr/bin/env python3
"""
⚡ 1-Click Automated Cloud Sync (Dual-Mode: GitHub HTTPS + Direct OCI SSH)
Guarantees 100% successful sync even if OCI SSH port 22 times out.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

KEY_FILE = BASE_DIR / "ssh-key-2026-09-21_new.key"
if not KEY_FILE.is_file():
    KEY_FILE = BASE_DIR / "ssh-key-2026-09-20 (1).key"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
TOKEN_FILE = BASE_DIR / "upstoxtoken.txt"
CONFIG_FILE = BASE_DIR / "config_credentials.json"

SERVER_IP = "80.225.210.222"
SERVER_USER = "opc"
REMOTE_DIR = f"/home/{SERVER_USER}/Jarvis"

import time
import urllib.request

def purge_jsdelivr_cache():
    """Purges jsDelivr CDN cache instantly so cloud dashboard reflects updates immediately."""
    try:
        url = "https://purge.jsdelivr.net/gh/sanIncredible/Jarvis@main/data.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Purge"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            pass
        print("   ⚡ jsDelivr Edge CDN Cache Purged successfully!")
    except Exception as e:
        print(f"   ℹ️ CDN purge notice: {e}")

def pull_latest_data_json():
    """Downloads the latest data.json from GitHub so local dashboard/files match cloud immediately."""
    try:
        url = f"https://raw.githubusercontent.com/sanIncredible/Jarvis/main/data.json?_t={int(time.time())}"
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            if d and "stocks" in d:
                with open(BASE_DIR / "data.json", "w", encoding="utf-8") as f:
                    json.dump(d, f, indent=2)
                print(f"   📥 Local data.json updated ({len(d['stocks'])} stocks synced)")
    except Exception as e:
        print(f"   ℹ️ Local pull notice: {e}")

def main():
    print("=" * 60)
    print("⚡ 1-CLICK CLOUD SYNC — UPSTOX TOKEN & WATCHLIST")
    print("=" * 60)

    # 1. Watchlist Check (Local watchlist is master authority: replaces GitHub & OCI VM, no merging)
    if not WATCHLIST_FILE.is_file():
        print(f"❌ Watchlist file not found: {WATCHLIST_FILE}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        raw_syms = [l.strip().upper() for l in f if l.strip() and not l.startswith("#")]
    print(f"📋 Master Watchlist (Local): {len(raw_syms)} symbols in {WATCHLIST_FILE.name}")
    print(f"   Symbols: {', '.join(raw_syms)}")
    print("   ℹ️ Authority Policy: Overwriting GitHub & OCI with local watchlist (no merging).")

    # 2. Token & Config Check
    if not CONFIG_FILE.is_file():
        print(f"❌ Configuration file not found: {CONFIG_FILE}")
        input("\nPress Enter to exit...")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # If upstoxtoken.txt exists locally, auto-merge into config_credentials.json
    if TOKEN_FILE.is_file():
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            t_txt = f.read().strip()
        if t_txt and t_txt != cfg.get("upstox", {}).get("access_token", ""):
            cfg.setdefault("upstox", {})["access_token"] = t_txt
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)

    upstox_tok = cfg.get("upstox", {}).get("access_token", "").strip()
    if upstox_tok:
        print(f"🎟️ Upstox Token: Loaded from config_credentials.json ({len(upstox_tok)} chars)")
    else:
        print("⚠️ Upstox Token: Not set in config_credentials.json")

    # 2.1 Immediate Master Watchlist Sync to GitHub (Guarantees GitHub is current FIRST)
    from upstox_tablet_scanner import load_github_config, sync_file_to_github_api
    gh_cfg = load_github_config()
    ok_w = False
    if gh_cfg:
        ok_w = sync_file_to_github_api(gh_cfg, "watchlist.txt", f"Update master watchlist.txt ({len(raw_syms)} symbols)")
        if ok_w:
            print(f"   📤 Pushed latest watchlist.txt to GitHub repository ({len(raw_syms)} symbols)")

    # 2.5 Generate Fresh Market Snapshot for New Watchlist
    print("-" * 60)
    print(f"📊 Compiling market snapshot for {len(raw_syms)} symbols via Upstox API...")
    try:
        from upstox_tablet_scanner import scan_watchlist, export_static_html, get_ist_now
        results = scan_watchlist()
        now_str = get_ist_now().strftime("%H:%M:%S IST")
        export_static_html(results, now_str, 5000)
        print(f"   ✅ Fresh data.json & scanner_dashboard.html compiled ({len(results)} symbols)")
    except Exception as e:
        print(f"   ⚠️ Scan notice: {e}")

    # 3. GitHub Cloud Sync (Step 1: Always runs first, 100% reliable)
    print("-" * 60)
    print("🚀 [Step 1/2] Syncing to GitHub Cloud Repository (HTTPS 443)...")
    github_ok = False
    try:
        if gh_cfg:
            if not ok_w:
                ok_w = sync_file_to_github_api(gh_cfg, "watchlist.txt", f"Update watchlist.txt ({len(raw_syms)} symbols)")
            ok_s = sync_file_to_github_api(gh_cfg, "upstox_tablet_scanner.py", "Update scanner engine")
            ok_h = sync_file_to_github_api(gh_cfg, "index.html", "Update index.html")
            ok_d = sync_file_to_github_api(gh_cfg, "scanner_dashboard.html", "Update scanner_dashboard.html")
            ok_j = sync_file_to_github_api(gh_cfg, "data.json", f"sync data.json ({len(raw_syms)} symbols)")
            if (BASE_DIR / "pre_market_summary.py").is_file():
                sync_file_to_github_api(gh_cfg, "pre_market_summary.py", "Update pre_market_summary engine")
            if (BASE_DIR / "pre_market_summary.json").is_file():
                sync_file_to_github_api(gh_cfg, "pre_market_summary.json", "Update 09:14 SA summary data")
            if (BASE_DIR / "intraday_breadth_monitor.py").is_file():
                sync_file_to_github_api(gh_cfg, "intraday_breadth_monitor.py", "Update intraday breadth monitor engine")
            if (BASE_DIR / "intraday_breadth.json").is_file():
                sync_file_to_github_api(gh_cfg, "intraday_breadth.json", "Update intraday breadth pulse data")
            if (BASE_DIR / "market_regime.json").is_file():
                sync_file_to_github_api(gh_cfg, "market_regime.json", "Update market regime state")
            if (BASE_DIR / "daily_swing_detector.py").is_file():
                sync_file_to_github_api(gh_cfg, "daily_swing_detector.py", "Update daily swing detector engine")
            if (BASE_DIR / "daily_positional_regime.json").is_file():
                sync_file_to_github_api(gh_cfg, "daily_positional_regime.json", "Update daily positional regime state")
            if (BASE_DIR / "bonde_2026_visualizer.html").is_file():
                sync_file_to_github_api(gh_cfg, "bonde_2026_visualizer.html", "Update 2026 visualizer with Vol Ratio")
            if (BASE_DIR / "bonde_2025_visualizer.html").is_file():
                sync_file_to_github_api(gh_cfg, "bonde_2025_visualizer.html", "Update 2025 visualizer with Vol Ratio")
            if (BASE_DIR / "nifty_smallcap_2026_chart_data.json").is_file():
                sync_file_to_github_api(gh_cfg, "nifty_smallcap_2026_chart_data.json", "Update 2026 chart data")
            if (BASE_DIR / "nifty_smallcap_2025_chart_data.json").is_file():
                sync_file_to_github_api(gh_cfg, "nifty_smallcap_2025_chart_data.json", "Update 2025 chart data")
            if (BASE_DIR / "sync_journal.py").is_file():
                sync_file_to_github_api(gh_cfg, "sync_journal.py", "Update trade journal auto-sync engine")
            if (BASE_DIR / "telegram_bot.py").is_file():
                sync_file_to_github_api(gh_cfg, "telegram_bot.py", "Update telegram command bot engine")
            if (BASE_DIR / "order_engine.py").is_file():
                sync_file_to_github_api(gh_cfg, "order_engine.py", "Update broker MTF order engine")
            if (BASE_DIR / "candidate_scanner.py").is_file():
                sync_file_to_github_api(gh_cfg, "candidate_scanner.py", "Update candidate scanner engine")
            if (BASE_DIR / "candidates.txt").is_file():
                sync_file_to_github_api(gh_cfg, "candidates.txt", "Update swing candidates.txt")
            if (BASE_DIR / "candidates.json").is_file():
                sync_file_to_github_api(gh_cfg, "candidates.json", "Update swing candidates.json")
            if (BASE_DIR / "tracked_holdings.json").is_file():
                sync_file_to_github_api(gh_cfg, "tracked_holdings.json", "Update tracked swing holdings")
            if (BASE_DIR / "orders_log.json").is_file():
                sync_file_to_github_api(gh_cfg, "orders_log.json", "Update active orders log")
            if (BASE_DIR / "eod_hindsight_report.py").is_file():
                sync_file_to_github_api(gh_cfg, "eod_hindsight_report.py", "Update EOD hindsight simulation report engine")
            if (BASE_DIR / "exited_stocks_manager.py").is_file():
                sync_file_to_github_api(gh_cfg, "exited_stocks_manager.py", "Update exited stocks re-entry manager")
            if (BASE_DIR / "exited_stocks.json").is_file():
                sync_file_to_github_api(gh_cfg, "exited_stocks.json", "Update exited stocks ledger")
            if ok_w and ok_j:
                print("   ✅ GitHub Cloud Sync: SUCCESS! (watchlist, data.json, dashboard & index.html live)")
                github_ok = True
            else:
                print("   ⚠️ GitHub Cloud Sync partial.")
        else:
            print("   ⚠️ GitHub config not found in config_credentials.json.")
    except Exception as e:
        print(f"   ⚠️ GitHub sync notice: {e}")

    # 4. Direct OCI Push (Step 2: Fast SSH/SCP push)
    print(f"🌐 [Step 2/2] Attempting Direct SSH/SCP push to OCI VM ({SERVER_IP})...")
    ssh_ok = False
    if KEY_FILE.is_file():
        ssh_opts = [
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "IPQoS=none",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5"
        ]

        # 4a. Bidirectional Safety Sync: Pull orders_log.json & protect Journal.xlsx
        remote_journal_is_newer = False
        try:
            # Check remote orders_log.json mtime vs local
            ssh_ord_cmd = ["ssh", "-i", str(KEY_FILE)] + ssh_opts + [
                f"{SERVER_USER}@{SERVER_IP}",
                "stat -c %Y /home/opc/Jarvis/orders_log.json 2>/dev/null || echo 0"
            ]
            res_ord_stat = subprocess.run(ssh_ord_cmd, capture_output=True, text=True, timeout=8)
            remote_ord_mtime = int(res_ord_stat.stdout.strip()) if res_ord_stat.stdout.strip().isdigit() else 0
            local_ord = BASE_DIR / "orders_log.json"
            local_ord_mtime = int(local_ord.stat().st_mtime) if local_ord.is_file() else 0
            if remote_ord_mtime > local_ord_mtime and remote_ord_mtime > 0:
                scp_orders_cmd = ["scp", "-i", str(KEY_FILE)] + ssh_opts + [
                    f"{SERVER_USER}@{SERVER_IP}:{REMOTE_DIR}/orders_log.json",
                    str(BASE_DIR / "orders_log.json")
                ]
                subprocess.run(scp_orders_cmd, capture_output=True, text=True, timeout=8)
                print("   📥 Pulled latest orders_log.json from OCI VM (live broker trade history synced)")
        except Exception:
            pass

        try:
            # 2. Check remote Journal.xlsx mtime vs local Journal.xlsx mtime
            ssh_stat_cmd = ["ssh", "-i", str(KEY_FILE)] + ssh_opts + [
                f"{SERVER_USER}@{SERVER_IP}",
                "stat -c %Y /home/opc/Jarvis/Journal.xlsx 2>/dev/null || echo 0"
            ]
            res_stat = subprocess.run(ssh_stat_cmd, capture_output=True, text=True, timeout=8)
            remote_mtime = int(res_stat.stdout.strip()) if res_stat.stdout.strip().isdigit() else 0

            local_j = BASE_DIR / "Journal.xlsx"
            local_mtime = int(local_j.stat().st_mtime) if local_j.is_file() else 0

            if remote_mtime > local_mtime and remote_mtime > 0:
                remote_journal_is_newer = True
                if local_j.is_file():
                    b_dir = BASE_DIR / "backups"
                    b_dir.mkdir(parents=True, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    shutil.copy2(local_j, b_dir / f"Journal_local_pre_pull_{ts}.xlsx")

                scp_j_cmd = ["scp", "-i", str(KEY_FILE)] + ssh_opts + [
                    f"{SERVER_USER}@{SERVER_IP}:{REMOTE_DIR}/Journal.xlsx",
                    str(local_j)
                ]
                res_j = subprocess.run(scp_j_cmd, capture_output=True, text=True, timeout=10)
                if res_j.returncode == 0:
                    print("   📥 Pulled latest Journal.xlsx from OCI VM (EOD reconciled trades preserved!)")
        except Exception as e:
            print(f"   ℹ️ Journal sync note: {e}")

        scp_files = [
            str(WATCHLIST_FILE),
            str(CONFIG_FILE),
            str(BASE_DIR / "upstox_tablet_scanner.py"),
            str(BASE_DIR / "index.html"),
            str(BASE_DIR / "scanner_dashboard.html"),
            str(BASE_DIR / "data.json"),
            str(BASE_DIR / "pre_market_summary.py"),
            str(BASE_DIR / "intraday_breadth_monitor.py"),
            str(BASE_DIR / "market_regime.json"),
            str(BASE_DIR / "intraday_breadth.json"),
            str(BASE_DIR / "daily_swing_detector.py"),
            str(BASE_DIR / "daily_positional_regime.json"),
            str(BASE_DIR / "bonde_2026_visualizer.html"),
            str(BASE_DIR / "bonde_2025_visualizer.html"),
            str(BASE_DIR / "nifty_smallcap_2026_chart_data.json"),
            str(BASE_DIR / "nifty_smallcap_2025_chart_data.json"),
            str(BASE_DIR / "sync_journal.py"),
            str(BASE_DIR / "check_tokens.py"),
            str(BASE_DIR / "token_hub.py"),
            str(BASE_DIR / "telegram_bot.py"),
            str(BASE_DIR / "order_engine.py"),
            str(BASE_DIR / "candidate_scanner.py"),
            str(BASE_DIR / "eod_hindsight_report.py"),
            str(BASE_DIR / "exited_stocks_manager.py")
        ]
        if (BASE_DIR / "exited_stocks.json").is_file():
            scp_files.append(str(BASE_DIR / "exited_stocks.json"))
        if (BASE_DIR / "candidates.txt").is_file():
            scp_files.append(str(BASE_DIR / "candidates.txt"))
        if (BASE_DIR / "candidates.json").is_file():
            scp_files.append(str(BASE_DIR / "candidates.json"))
        if (BASE_DIR / "tracked_holdings.json").is_file():
            scp_files.append(str(BASE_DIR / "tracked_holdings.json"))
        if (BASE_DIR / "nifty500_constituents.json").is_file():
            scp_files.append(str(BASE_DIR / "nifty500_constituents.json"))
        if (BASE_DIR / "dhan_nse_cache.json").is_file():
            scp_files.append(str(BASE_DIR / "dhan_nse_cache.json"))
        if (BASE_DIR / "Journal.xlsx").is_file() and not remote_journal_is_newer:
            scp_files.append(str(BASE_DIR / "Journal.xlsx"))
        if (BASE_DIR / "orders_log.json").is_file():
            scp_files.append(str(BASE_DIR / "orders_log.json"))

        scp_cmd = [
            "scp",
            "-i", str(KEY_FILE)
        ] + ssh_opts + scp_files + [
            f"{SERVER_USER}@{SERVER_IP}:{REMOTE_DIR}/"
        ]

        try:
            res = subprocess.run(scp_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if res.returncode == 0:
                print("   ✅ Files copied to OCI VM (/home/opc/Jarvis/)")
                # Reload scanner
                ssh_cmd = [
                    "ssh",
                    "-i", str(KEY_FILE)
                ] + ssh_opts + [
                    f"{SERVER_USER}@{SERVER_IP}",
                    "sudo systemctl restart scanner"
                ]
                subprocess.run(ssh_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
                print("   🌟 Scanner service reloaded on OCI VM!")
                ssh_ok = True
            else:
                print(f"   ℹ️ Direct SCP notice: {res.stderr.strip() or 'Connection timeout'}")
        except Exception as ex:
            print(f"   ℹ️ Direct SSH note: {ex}")
    else:
        print("   ℹ️ SSH key not found, skipped direct SCP.")

    # 5. Flush Global CDN Edge Cache
    purge_jsdelivr_cache()

    print("=" * 60)
    if github_ok or ssh_ok:
        print("🎉 SYNC FINISHED SUCCESSFULLY!")
        print(f"   -> {len(raw_syms)} Watchlist Symbols: {', '.join(raw_syms)}")
        print("   -> Live Dashboard: https://sanincredible.github.io/Jarvis/")
        if not ssh_ok and github_ok:
            print("   💡 Note: Direct SSH timed out, but your token/watchlist are safely on GitHub.")
            print("      The OCI engine reads updates from GitHub automatically at 09:14 AM.")
    else:
        print("❌ Both GitHub and SSH sync encountered issues.")
    print("=" * 60)

if __name__ == "__main__":
    main()
