#!/usr/bin/env python3
"""
🛡️ JARVIS EMERGENCY BACKUP RUNNER (For Tablet / Pydroid 3 / Termux)
Runs the scanner directly on your device if OCI is ever offline or down.
"""

import os
import sys
import json
import base64
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def fetch_github_file(gh_cfg, filename):
    """Fetches latest file content from GitHub repository."""
    if not gh_cfg or not gh_cfg.get("token"):
        return None
    try:
        token = gh_cfg["token"].strip()
        owner = gh_cfg.get("username", "sanIncredible").strip()
        repo = gh_cfg.get("repo", "Jarvis").strip()
        branch = gh_cfg.get("branch", "main").strip()
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}?ref={branch}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Tablet-Emergency-Backup",
            "Accept": "application/vnd.github+json"
        })
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content_b64 = data.get("content", "")
            return base64.b64decode(content_b64).decode("utf-8")
    except Exception as e:
        print(f"   [GitHub Fetch Notice: {e}]")
        return None

def main():
    print("=" * 60)
    print("🛡️ JARVIS TABLET FAILOVER ENGINE (Rainy Day Mode)")
    print("=" * 60)

    # 1. Load config
    cfg_file = BASE_DIR / "config_credentials.json"
    gh_cfg = None
    if cfg_file.is_file():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                gh_cfg = cfg.get("github")
        except Exception:
            pass

    # 2. Pull latest token & watchlist from GitHub
    if gh_cfg:
        print("🌐 [GitHub Sync] Checking for latest synced token & watchlist...")
        tok = fetch_github_file(gh_cfg, "upstoxtoken.txt")
        if tok and tok.strip():
            with open(BASE_DIR / "upstoxtoken.txt", "w", encoding="utf-8") as f:
                f.write(tok.strip())
            print("   ✅ Fresh Upstox token pulled from GitHub!")

        wl = fetch_github_file(gh_cfg, "watchlist.txt")
        if wl and wl.strip():
            with open(BASE_DIR / "watchlist.txt", "w", encoding="utf-8") as f:
                f.write(wl.strip())
            print("   ✅ Latest watchlist pulled from GitHub!")

    # 3. Verify token
    tok_file = BASE_DIR / "upstoxtoken.txt"
    if not tok_file.is_file():
        print("❌ Error: upstoxtoken.txt not found. Please sync from laptop first.")
        return

    # 4. Launch scanner
    print("=" * 60)
    print("🚀 Starting Local Tablet Scanner Engine...")
    print("   -> Dashboard local url: http://127.0.0.1:5000")
    print("   -> Live feed pushing to: https://sanincredible.github.io/Jarvis/")
    print("=" * 60)

    import upstox_tablet_scanner
    upstox_tablet_scanner.run_upstox_scanner(once=False, auto_open_web=True)

if __name__ == "__main__":
    main()
