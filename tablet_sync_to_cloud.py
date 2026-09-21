#!/usr/bin/env python3
"""
📱 JARVIS TABLET 1-CLICK SYNC (For Android / Pydroid 3)
Allows you to push fresh Upstox token and watchlist to GitHub directly from your tablet,
with ZERO laptop needed!
"""

import os
import sys
import json
import base64
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

TOKEN_FILE = BASE_DIR / "upstoxtoken.txt"
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
CONFIG_FILE = BASE_DIR / "config_credentials.json"

def push_file_to_github(gh_cfg, path_str, content_str, commit_msg):
    """Pushes file content to GitHub repo via HTTPS REST API (Port 443)."""
    if not gh_cfg or not gh_cfg.get("token"):
        print("❌ Error: GitHub token not found in config_credentials.json")
        return False
    try:
        token = gh_cfg["token"].strip()
        owner = gh_cfg.get("username", "sanIncredible").strip()
        repo = gh_cfg.get("repo", "Jarvis").strip()
        branch = gh_cfg.get("branch", "main").strip()

        # 1. Fetch current SHA if file exists
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path_str}?ref={branch}"
        sha = None
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Tablet-Sync",
            "Accept": "application/vnd.github+json"
        })
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                sha = json.loads(resp.read().decode("utf-8")).get("sha")
        except Exception:
            pass

        # 2. PUT update
        put_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path_str}"
        content_bytes = content_str.encode("utf-8")
        payload = {
            "message": commit_msg,
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "branch": branch
        }
        if sha:
            payload["sha"] = sha

        data = json.dumps(payload).encode("utf-8")
        put_req = urllib.request.Request(put_url, data=data, method="PUT", headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Tablet-Sync",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(put_req, timeout=12) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"❌ Error uploading {path_str}: {e}")
        return False

def validate_upstox_token(token):
    """Tests token with Upstox API v2 profile endpoint."""
    try:
        url = "https://api.upstox.com/v2/user/profile"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                user_name = data.get("data", {}).get("user_name", "Trader")
                user_id = data.get("data", {}).get("user_id", "")
                return True, f"{user_name} ({user_id})"
    except Exception as e:
        return False, str(e)
    return False, "Invalid response"

def main():
    print("=" * 60)
    print("📱 JARVIS TABLET CLOUD SYNC (No Laptop Needed)")
    print("=" * 60)

    # 1. Load GitHub Config
    gh_cfg = None
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                gh_cfg = cfg.get("github")
        except Exception:
            pass

    if not gh_cfg:
        print("❌ config_credentials.json missing or no GitHub config found!")
        return

    # 2. Existing Token Check
    current_token = ""
    if TOKEN_FILE.is_file():
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            current_token = f.read().strip()

    print(f"Current Token: {'Loaded (' + str(len(current_token)) + ' chars)' if current_token else 'Not found'}")
    print("\n👉 Paste new Upstox Token (or press ENTER to keep current token):")
    try:
        user_input = input().strip()
    except (EOFError, KeyboardInterrupt):
        user_input = ""

    token_to_use = user_input if user_input else current_token

    if not token_to_use:
        print("❌ No token provided. Exiting.")
        return

    # 3. Validate Token
    print("\n🔍 Validating token with Upstox API...")
    ok, info = validate_upstox_token(token_to_use)
    if ok:
        print(f"   ✅ Token Active & Authenticated for: {info}")
    else:
        print(f"   ⚠️ Token verification warning: {info}")
        print("   Proceeding with upload anyway...")

    # Save locally on tablet
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token_to_use)

    # 4. Upload Token to GitHub
    print("\n🚀 Pushing upstoxtoken.txt to GitHub...")
    tok_ok = push_file_to_github(gh_cfg, "upstoxtoken.txt", token_to_use, "Sync Upstox token from tablet")
    if tok_ok:
        print("   ✅ Token successfully updated on GitHub!")
    else:
        print("   ❌ Failed to push token to GitHub.")

    # 5. Upload Watchlist to GitHub (if present)
    if WATCHLIST_FILE.is_file():
        print("\n📋 Pushing watchlist.txt to GitHub...")
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            wl_content = f.read()
        wl_ok = push_file_to_github(gh_cfg, "watchlist.txt", wl_content, "Sync watchlist from tablet")
        if wl_ok:
            print("   ✅ Watchlist successfully updated on GitHub!")

    print("\n" + "=" * 60)
    print("🎉 CLOUD SYNC COMPLETE!")
    print("👉 OCI Cloud Scanner pulls updates automatically on every scan cycle & at 09:14 AM.")
    print("👉 Live Dashboard: https://sanincredible.github.io/Jarvis/")
    print("=" * 60)

if __name__ == "__main__":
    main()
