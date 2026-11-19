#!/usr/bin/env python3
import sys
import json
import base64
import urllib.request
from pathlib import Path

# Safe UTF-8 printing on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"

def push_file(gh_cfg, path_str, commit_msg):
    token = gh_cfg["token"].strip()
    owner = gh_cfg.get("username", "sanIncredible").strip()
    repo = gh_cfg.get("repo", "Jarvis").strip()
    branch = gh_cfg.get("branch", "main").strip()

    file_path = BASE_DIR / path_str
    if not file_path.is_file():
        print(f"File not found: {path_str}")
        return False
    content_bytes = file_path.read_bytes()

    # Get SHA
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path_str}?ref={branch}"
    sha = None
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "Jarvis-Deployer",
        "Accept": "application/vnd.github+json"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            sha = json.loads(resp.read().decode("utf-8")).get("sha")
    except Exception:
        pass

    put_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path_str}"
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
        "User-Agent": "Jarvis-Deployer",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(put_req, timeout=15) as resp:
            status = resp.status in (200, 201)
            print(f"{'✅' if status else '❌'} Pushed {path_str} (HTTP {resp.status})")
            return status
    except Exception as e:
        print(f"❌ Failed to push {path_str}: {e}")
        return False

def purge_cdn(files):
    for f in files:
        url = f"https://purge.jsdelivr.net/gh/sanIncredible/Jarvis@main/{f}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                print(f"CDN Purged: {f} -> {resp.status}")
        except Exception as e:
            print(f"CDN Purge failed for {f}: {e}")

def main():
    if not CONFIG_FILE.is_file():
        print("Config file missing!")
        return
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    gh_cfg = cfg.get("github")
    if not gh_cfg or not gh_cfg.get("token"):
        print("GitHub token missing!")
        return

    files_to_push = [
        ".nojekyll",
        "candidate_schema.py",
        "enrich_candidates.py",
        "scan_nr_momo.py",
        "scan_nifty_ipo.py",
        "scan_ems.py",
        "order_engine.py",
        "telegram_bot.py",
        "upstox_tablet_scanner.py",
        "index.html",
        "data.json",
        "candidates_merged.json",
        "candidates_merged.txt",
        "candidates_90d_nr.json",
        "candidates_90d_nr.txt",
        "candidates_nifty_ipo.json",
        "candidates_nifty_ipo.txt",
        "candidates_ems.json",
        "candidates_ems.txt",
        "candidates_exited.json",
        "eod_hindsight_report.py"
    ]

    commit_msg = "Deploy 3-Check Sniper Sieve, Blue Sky radar, and unified confluence candidates"
    for f in files_to_push:
        push_file(gh_cfg, f, commit_msg)

    purge_cdn([
        "index.html",
        "data.json",
        "candidates_merged.json",
        "candidates_merged.txt",
        "candidates_90d_nr.json",
        "candidates_90d_nr.txt",
        "candidates_nifty_ipo.json",
        "candidates_nifty_ipo.txt",
        "candidates_ems.json",
        "candidates_ems.txt",
        "candidates_exited.json"
    ])
    print("Done pushing to GitHub!")

if __name__ == "__main__":
    main()
