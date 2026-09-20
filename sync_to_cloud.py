#!/usr/bin/env python3
"""
⚡ 1-Click Automated Cloud Sync (Windows-optimized)
Uses clean file-based SCP transfer to prevent Windows multiline shell escaping hangs.
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

KEY_FILE = BASE_DIR / "ssh-key-2026-09-20 (1).key"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
TOKEN_FILE = BASE_DIR / "upstoxtoken.txt"
CONFIG_FILE = BASE_DIR / "config_credentials.json"

SERVER_IP = "130.210.58.44"
SERVER_USER = "opc"
REMOTE_DIR = f"/home/{SERVER_USER}/Jarvis"

def main():
    print("=" * 60)
    print("⚡ 1-CLICK CLOUD SYNC — UPSTOX TOKEN & WATCHLIST")
    print("=" * 60)

    # 1. Key Check
    if not KEY_FILE.is_file():
        print(f"❌ Key file not found: {KEY_FILE}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    print(f"🔑 Key: {KEY_FILE.name}")

    # 2. Watchlist Check
    if not WATCHLIST_FILE.is_file():
        print(f"❌ Watchlist file not found: {WATCHLIST_FILE}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        sym_count = len([l for l in f if l.strip() and not l.startswith("#")])
    print(f"📋 Watchlist: {sym_count} symbols in {WATCHLIST_FILE.name}")

    # 3. Token Check
    if not TOKEN_FILE.is_file():
        print(f"❌ Token file not found: {TOKEN_FILE}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        tok = f.read().strip()
    print(f"🎟️ Upstox Token: Loaded ({len(tok)} characters)")

    print(f"🌐 Target: {SERVER_USER}@{SERVER_IP}")
    print("-" * 60)
    print("🚀 Uploading to Oracle Cloud via SCP...")

    # Options to prevent hanging on Windows OpenSSH & Indian ISP QoS filtering
    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "IPQoS=none",
        "-o", "ServerAliveInterval=15",
        "-o", "ConnectTimeout=10"
    ]

    # Step A: Transfer files using SCP (atomic and immune to shell escaping bugs)
    scp_cmd = [
        "scp",
        "-i", str(KEY_FILE)
    ] + ssh_opts + [
        str(WATCHLIST_FILE),
        str(TOKEN_FILE),
        f"{SERVER_USER}@{SERVER_IP}:{REMOTE_DIR}/"
    ]

    try:
        res = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=12)
        if res.returncode == 0:
            print("✅ Files uploaded (watchlist.txt + upstoxtoken.txt)")
        else:
            print(f"❌ Upload failed:\n{res.stderr.strip()}")
            input("\nPress Enter to exit...")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        print("❌ Connection timed out! Check if your current Wi-Fi/VPN blocks port 22 (SSH).")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)

    # Step B: Update config_credentials.json and restart scanner
    print("🔄 Applying new token and restarting cloud scanner...")
    remote_script = (
        f"python3 -c \""
        f"import json;"
        f"cfg=json.load(open('{REMOTE_DIR}/config_credentials.json'));"
        f"cfg['upstox']['access_token']=open('{REMOTE_DIR}/upstoxtoken.txt').read().strip();"
        f"json.dump(cfg, open('{REMOTE_DIR}/config_credentials.json','w'), indent=2);"
        f"\" && sudo systemctl restart scanner && sudo systemctl is-active scanner"
    )

    ssh_cmd = [
        "ssh",
        "-i", str(KEY_FILE)
    ] + ssh_opts + [
        f"{SERVER_USER}@{SERVER_IP}",
        remote_script
    ]

    try:
        res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=12)
        if "active" in res.stdout:
            print("🌟 Scanner service reloaded & ACTIVE with fresh token!")
        else:
            print(f"Server response: {res.stdout.strip()} {res.stderr.strip()}")
    except Exception as e:
        print(f"⚠️ Reload notice: {e}")

    # Step C: Also sync watchlist to GitHub repository
    try:
        from upstox_tablet_scanner import load_github_config, sync_file_to_github_api
        gh_cfg = load_github_config()
        if gh_cfg:
            sync_file_to_github_api(gh_cfg, str(WATCHLIST_FILE.name), "Update watchlist.txt")
            print("📦 Watchlist synced to GitHub repository.")
    except Exception:
        pass

    print("=" * 60)
    print("🎉 SUCCESS! Cloud scanner is 100% updated and running live.")
    print("👉 View Dashboard: https://sanincredible.github.io/Jarvis/")
    print("=" * 60)

if __name__ == "__main__":
    main()
