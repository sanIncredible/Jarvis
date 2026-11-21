#!/usr/bin/env python3
"""
⚡ JARVIS 1-CLICK MORNING TOKEN HUB
===================================
A lightweight local dashboard (http://127.0.0.1:8000) that completely eliminates
manual copying and pasting of tokens or callback URLs.

Features:
1. Zero copy-pasting for Zerodha: Click 'Login' -> Kite redirects to /callback -> token auto-exchanged & saved!
2. Zero copy-pasting for Upstox: Click 'Login' -> Upstox redirects to /callback -> token auto-exchanged & saved!
3. Fast 1-tap paste & test for Dhan: Click 'Paste from Clipboard' -> verified live against Dhan API & saved!
4. 1-Click Cloud Sync: Pushes updated credentials directly to OCI VM (/home/opc/Jarvis/) via encrypted SCP.
5. No passwords or PINs stored on disk or server.
"""

import os
import sys
import json
import hashlib
import threading
import webbrowser
import subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# Console UTF-8 encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_credentials.json"
PORT = 8000
SERVER_IP = "80.225.210.222"
SERVER_USER = "opc"
KEY_FILE = BASE_DIR / "ssh-key-2026-09-21_new.key"
if not KEY_FILE.is_file():
    KEY_FILE = BASE_DIR / "ssh-key-2026-09-20 (1).key"

def load_config():
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def check_token_status():
    """Checks validity of all three broker tokens."""
    cfg = load_config()
    res = {
        "zerodha": {"valid": False, "msg": "Not configured"},
        "upstox": {"valid": False, "msg": "Not configured"},
        "dhan": {"valid": False, "msg": "Not configured"},
        "cloud_sync": {"last_synced": False}
    }

    # 1. Zerodha
    z = cfg.get("zerodha", {})
    ak = z.get("api_key", "").strip()
    at = z.get("access_token", "").strip()
    if ak and at:
        try:
            r = requests.get("https://api.kite.trade/trades", headers={"X-Kite-Version": "3", "Authorization": f"token {ak}:{at}"}, timeout=4)
            if r.status_code == 200:
                res["zerodha"] = {"valid": True, "msg": "ACTIVE (Ready for trades)"}
            else:
                res["zerodha"] = {"valid": False, "msg": "EXPIRED (Daily 6 AM rule)"}
        except Exception as e:
            res["zerodha"] = {"valid": False, "msg": f"Error: {e}"}

    # 2. Upstox
    u = cfg.get("upstox", {})
    ut = u.get("access_token", "").strip()
    if ut:
        try:
            r = requests.get("https://api.upstox.com/v2/market-quote/ltp?instrument_key=NSE_EQ|RELIANCE", headers={"Authorization": f"Bearer {ut}", "Accept": "application/json"}, timeout=4)
            if r.status_code == 200:
                res["upstox"] = {"valid": True, "msg": "ACTIVE (Live scanner feed OK)"}
            else:
                res["upstox"] = {"valid": False, "msg": "EXPIRED (24-hr expiry)"}
        except Exception as e:
            res["upstox"] = {"valid": False, "msg": f"Error: {e}"}

    # 3. Dhan
    d = cfg.get("dhan", {})
    cid = d.get("client_id", "").strip()
    dt = d.get("access_token", "").strip()
    if cid and dt:
        try:
            r = requests.get("https://api.dhan.co/v2/trades", headers={"access-token": dt, "client-id": cid, "Content-Type": "application/json"}, timeout=4)
            if r.status_code == 200:
                res["dhan"] = {"valid": True, "msg": "ACTIVE (Orderbook sync OK)"}
            else:
                res["dhan"] = {"valid": False, "msg": "EXPIRED (Needs fresh token)"}
        except Exception as e:
            res["dhan"] = {"valid": False, "msg": f"Error: {e}"}

    return res

def push_to_cloud():
    """Pushes config_credentials.json to OCI VM and reloads scanner."""
    if not KEY_FILE.is_file():
        return False, "SSH key not found."
    
    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=6"
    ]
    scp_cmd = ["scp", "-i", str(KEY_FILE)] + ssh_opts + [str(CONFIG_FILE), f"{SERVER_USER}@{SERVER_IP}:/home/{SERVER_USER}/Jarvis/"]
    try:
        r1 = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=10)
        if r1.returncode != 0:
            return False, f"SCP failed: {r1.stderr}"
        
        # Reload scanner service
        ssh_cmd = ["ssh", "-i", str(KEY_FILE)] + ssh_opts + [f"{SERVER_USER}@{SERVER_IP}", "sudo systemctl restart scanner"]
        subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=8)
        return True, "Synced to OCI VM & Scanner reloaded!"
    except Exception as e:
        return False, str(e)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚡ Jarvis Morning Token Hub</title>
<style>
  :root {
    --bg: #0b0f19;
    --card: #151d30;
    --card-border: #233152;
    --accent: #3b82f6;
    --accent-hover: #2563eb;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --text: #f3f4f6;
    --text-muted: #9ca3af;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  body { background: var(--bg); color: var(--text); padding: 24px; min-height: 100vh; display: flex; flex-direction: column; align-items: center; }
  .container { max-width: 820px; width: 100%; }
  
  header { text-align: center; margin-bottom: 28px; }
  h1 { font-size: 26px; font-weight: 800; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  p.subtitle { color: var(--text-muted); font-size: 14px; margin-top: 6px; }

  .status-banner {
    background: #111827; border: 1px solid var(--card-border); border-radius: 12px;
    padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;
  }
  .status-indicators { display: flex; gap: 16px; font-size: 13px; font-weight: 600; }
  .badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 20px; font-size: 12px; }
  .badge.live { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
  .badge.expired { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }

  .card-grid { display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px; }
  .card {
    background: var(--card); border: 1px solid var(--card-border); border-radius: 14px;
    padding: 20px; display: flex; justify-content: space-between; align-items: center; gap: 16px;
    transition: transform 0.15s, border-color 0.15s;
  }
  .card:hover { border-color: #3b82f6; }
  .card-left { flex: 1; }
  .card-title { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
  .card-desc { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
  .card-status { font-size: 12px; margin-top: 8px; font-weight: 600; }

  .btn {
    padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer;
    border: none; transition: background 0.15s, transform 0.1s; text-decoration: none; display: inline-flex;
    align-items: center; justify-content: center; gap: 8px; color: white;
  }
  .btn:active { transform: scale(0.98); }
  .btn-primary { background: var(--accent); }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-success { background: var(--success); }
  .btn-success:hover { background: #059669; }
  .btn-outline { background: transparent; border: 1px solid #4b5563; color: var(--text); }
  .btn-outline:hover { background: #1f2937; }

  .dhan-box { display: flex; gap: 8px; margin-top: 10px; width: 100%; }
  .dhan-input {
    flex: 1; background: #0b0f19; border: 1px solid var(--card-border); border-radius: 6px;
    padding: 8px 12px; color: var(--text); font-size: 13px; outline: none;
  }
  .dhan-input:focus { border-color: var(--accent); }

  .cloud-bar {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(167, 139, 250, 0.1));
    border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 12px; padding: 18px 22px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .cloud-bar-text h3 { font-size: 16px; font-weight: 700; color: #a5b4fc; }
  .cloud-bar-text p { font-size: 13px; color: var(--text-muted); margin-top: 3px; }

  #alert-box {
    margin-top: 16px; padding: 12px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
    display: none; text-align: center;
  }
  #alert-box.success { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
  #alert-box.error { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>⚡ Jarvis 1-Click Morning Token Hub</h1>
    <p class="subtitle">Authenticate brokers with 1 click &bull; Auto-intercept callbacks &bull; Zero copy-paste</p>
  </header>

  <div class="status-banner">
    <div>
      <span style="font-size: 13px; color: var(--text-muted);">Active Target:</span>
      <strong style="color: #60a5fa; margin-left: 6px;">OCI Cloud VM (80.225.210.222)</strong>
    </div>
    <div class="status-indicators">
      <span id="badge-kite" class="badge expired">● Zerodha: Checking...</span>
      <span id="badge-upstox" class="badge expired">● Upstox: Checking...</span>
      <span id="badge-dhan" class="badge expired">● Dhan: Checking...</span>
    </div>
  </div>

  <div class="card-grid">
    <!-- Card 1: Zerodha -->
    <div class="card">
      <div class="card-left">
        <div class="card-title">🪁 Zerodha Kite Connect</div>
        <div class="card-desc">Daily 6:00 AM SEBI mandatory renewal. Used for trade reconciliation.</div>
        <div id="kite-status-text" class="card-status" style="color: #f87171;">Status: Expired</div>
      </div>
      <div>
        <button id="btn-kite" class="btn btn-primary" onclick="loginKite()">🔑 1-Click Login</button>
      </div>
    </div>

    <!-- Card 2: Upstox -->
    <div class="card">
      <div class="card-left">
        <div class="card-title">📈 Upstox Pro v2</div>
        <div class="card-desc">Real-time 3m intraday candles & tablet scanner live feed.</div>
        <div id="upstox-status-text" class="card-status" style="color: #f87171;">Status: Expired</div>
      </div>
      <div>
        <button id="btn-upstox" class="btn btn-primary" onclick="loginUpstox()">🔑 1-Click Login</button>
      </div>
    </div>

    <!-- Card 3: DhanHQ -->
    <div class="card" style="flex-direction: column; align-items: stretch;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div class="card-title">⚡ DhanHQ API</div>
          <div class="card-desc">Used for live broker fills & automated EOD Trade Journal sync.</div>
          <div id="dhan-status-text" class="card-status" style="color: #f87171;">Status: Expired</div>
        </div>
        <div>
          <button class="btn btn-outline" onclick="window.open('https://web.dhan.co', '_blank')">🌐 Open Dhan Portal</button>
        </div>
      </div>
      <div class="dhan-box">
        <input type="text" id="dhan-input" class="dhan-input" placeholder="Paste Dhan Access Token here (or click 'Auto-Paste')" />
        <button class="btn btn-outline" onclick="pasteClipboard()">📋 Paste</button>
        <button class="btn btn-primary" onclick="saveDhanToken()">Verify & Save</button>
      </div>
    </div>
  </div>

  <!-- Cloud Sync Bar -->
  <div class="cloud-bar">
    <div class="cloud-bar-text">
      <h3>🚀 Deploy to OCI Cloud VM</h3>
      <p>Securely syncs all active tokens to your cloud engine & automatically reloads the live scanner.</p>
    </div>
    <div>
      <button id="btn-sync" class="btn btn-success" onclick="syncCloud()">⚡ Push to Cloud Server</button>
    </div>
  </div>

  <div id="alert-box"></div>
</div>

<script>
  let kiteUrl = "";
  let upstoxUrl = "";

  function showAlert(msg, isSuccess) {
    const el = document.getElementById('alert-box');
    el.className = isSuccess ? 'success' : 'error';
    el.innerText = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 6000);
  }

  async function checkStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      
      // Zerodha
      const bK = document.getElementById('badge-kite');
      const tK = document.getElementById('kite-status-text');
      if (data.zerodha.valid) {
        bK.className = 'badge live'; bK.innerText = '● Zerodha: ACTIVE';
        tK.style.color = '#34d399'; tK.innerText = 'Status: ' + data.zerodha.msg;
      } else {
        bK.className = 'badge expired'; bK.innerText = '● Zerodha: Expired';
        tK.style.color = '#f87171'; tK.innerText = 'Status: ' + data.zerodha.msg;
      }

      // Upstox
      const bU = document.getElementById('badge-upstox');
      const tU = document.getElementById('upstox-status-text');
      if (data.upstox.valid) {
        bU.className = 'badge live'; bU.innerText = '● Upstox: ACTIVE';
        tU.style.color = '#34d399'; tU.innerText = 'Status: ' + data.upstox.msg;
      } else {
        bU.className = 'badge expired'; bU.innerText = '● Upstox: Expired';
        tU.style.color = '#f87171'; tU.innerText = 'Status: ' + data.upstox.msg;
      }

      // Dhan
      const bD = document.getElementById('badge-dhan');
      const tD = document.getElementById('dhan-status-text');
      if (data.dhan.valid) {
        bD.className = 'badge live'; bD.innerText = '● Dhan: ACTIVE';
        tD.style.color = '#34d399'; tD.innerText = 'Status: ' + data.dhan.msg;
      } else {
        bD.className = 'badge expired'; bD.innerText = '● Dhan: Expired';
        tD.style.color = '#f87171'; tD.innerText = 'Status: ' + data.dhan.msg;
      }

      kiteUrl = data.kite_login_url || "";
      upstoxUrl = data.upstox_login_url || "";
    } catch(e) {
      console.error(e);
    }
  }

  function loginKite() {
    if (!kiteUrl) { showAlert("Zerodha api_key not configured in config_credentials.json", false); return; }
    window.open(kiteUrl, '_blank');
  }

  function loginUpstox() {
    if (!upstoxUrl) { showAlert("Upstox client_id not configured in config_credentials.json", false); return; }
    window.open(upstoxUrl, '_blank');
  }

  async function pasteClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      document.getElementById('dhan-input').value = text.trim();
    } catch (e) {
      alert("Please press Ctrl+V to paste into the box.");
    }
  }

  async function saveDhanToken() {
    const tok = document.getElementById('dhan-input').value.trim();
    if (!tok) { showAlert("Please paste a Dhan token first.", false); return; }
    try {
      const res = await fetch('/api/dhan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({access_token: tok})
      });
      const data = await res.json();
      if (data.success) {
        showAlert("✅ DhanHQ Token verified and saved!", true);
        document.getElementById('dhan-input').value = '';
        checkStatus();
      } else {
        showAlert("❌ " + data.message, false);
      }
    } catch(e) {
      showAlert("Error saving Dhan token: " + e, false);
    }
  }

  async function syncCloud() {
    const btn = document.getElementById('btn-sync');
    btn.innerText = "⏳ Syncing...";
    btn.disabled = true;
    try {
      const res = await fetch('/api/sync', {method: 'POST'});
      const data = await res.json();
      if (data.success) {
        showAlert("🎉 " + data.message, true);
      } else {
        showAlert("⚠️ " + data.message, false);
      }
    } catch(e) {
      showAlert("Sync error: " + e, false);
    } finally {
      btn.innerText = "⚡ Push to Cloud Server";
      btn.disabled = false;
    }
  }

  // Poll status every 3 seconds to catch callbacks automatically
  setInterval(checkStatus, 3000);
  checkStatus();
</script>
</body>
</html>
"""

CALLBACK_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Authentication Successful</title>
<style>
  body { background: #0b0f19; color: #f3f4f6; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }
  .box { background: #151d30; padding: 36px 48px; border-radius: 16px; border: 1px solid #10b981; }
  h1 { color: #34d399; font-size: 24px; margin-bottom: 12px; }
  p { color: #9ca3af; font-size: 14px; }
</style>
</head>
<body>
<div class="box">
  <h1>🎉 {broker} Token Generated!</h1>
  <p>The token has been automatically saved to config_credentials.json.</p>
  <p style="margin-top: 14px; color: #60a5fa;">You can now close this tab and return to the Token Hub.</p>
</div>
<script>
  setTimeout(() => { window.close(); }, 3500);
</script>
</body>
</html>
"""

CALLBACK_ERROR_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Authentication Failed</title>
<style>
  body { background: #0b0f19; color: #f3f4f6; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }
  .box { background: #151d30; padding: 36px 48px; border-radius: 16px; border: 1px solid #ef4444; }
  h1 { color: #f87171; font-size: 24px; margin-bottom: 12px; }
  p { color: #9ca3af; font-size: 14px; }
</style>
</head>
<body>
<div class="box">
  <h1>❌ Authentication Failed</h1>
  <p>{error}</p>
</div>
</body>
</html>
"""

class TokenHubHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default console clutter

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Main Dashboard
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        # 2. Live Status API
        elif path == "/api/status":
            status = check_token_status()
            cfg = load_config()
            z_ak = cfg.get("zerodha", {}).get("api_key", "").strip()
            u_cid = cfg.get("upstox", {}).get("client_id", "").strip()
            u_red = cfg.get("upstox", {}).get("redirect_uri", f"http://127.0.0.1:{PORT}/callback").strip()

            status["kite_login_url"] = f"https://kite.zerodha.com/connect/login?v=3&api_key={z_ak}" if z_ak else ""
            status["upstox_login_url"] = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={u_cid}&redirect_uri={u_red}" if u_cid else ""

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode("utf-8"))

        # 3. OAuth Callback (/callback)
        elif path == "/callback":
            # Case A: Zerodha Kite redirect (?request_token=XXXXX)
            if "request_token" in query:
                req_token = query["request_token"][0].strip()
                print(f"📥 Intercepted Zerodha request_token: {req_token[:8]}...")
                cfg = load_config()
                z = cfg.get("zerodha", {})
                ak = z.get("api_key", "").strip()
                sec = z.get("api_secret", "").strip()

                if not ak or not sec:
                    self.send_error_html("Zerodha api_key or api_secret missing in config_credentials.json")
                    return

                checksum = hashlib.sha256(f"{ak}{req_token}{sec}".encode("utf-8")).hexdigest()
                url = "https://api.kite.trade/session/token"
                try:
                    r = requests.post(url, data={"api_key": ak, "request_token": req_token, "checksum": checksum}, headers={"X-Kite-Version": "3"}, timeout=10)
                    d = r.json()
                    if r.status_code == 200 and "data" in d and "access_token" in d["data"]:
                        at = d["data"]["access_token"]
                        cfg.setdefault("zerodha", {})["access_token"] = at
                        save_config(cfg)
                        print(f"🎉 SUCCESS! Zerodha access_token saved: {at[:6]}...{at[-4:]}")
                        self.send_success_html("Zerodha Kite")
                    else:
                        err = d.get("message", r.text)
                        print(f"❌ Failed to exchange Kite token: {err}")
                        self.send_error_html(f"Zerodha exchange failed: {err}")
                except Exception as e:
                    self.send_error_html(f"Error during Kite exchange: {e}")

            # Case B: Upstox redirect (?code=XXXXX)
            elif "code" in query:
                code = query["code"][0].strip()
                print(f"📥 Intercepted Upstox authorization code: {code[:8]}...")
                cfg = load_config()
                u = cfg.get("upstox", {})
                cid = u.get("client_id", "").strip()
                csec = u.get("client_secret", "").strip()
                red = u.get("redirect_uri", f"http://127.0.0.1:{PORT}/callback").strip()

                if not cid or not csec:
                    self.send_error_html("Upstox client_id or client_secret missing in config_credentials.json")
                    return

                url = "https://api.upstox.com/v2/login/authorization/token"
                payload = {
                    "code": code,
                    "client_id": cid,
                    "client_secret": csec,
                    "redirect_uri": red,
                    "grant_type": "authorization_code"
                }
                headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}

                try:
                    r = requests.post(url, data=payload, headers=headers, timeout=10)
                    d = r.json()
                    if r.status_code == 200 and "access_token" in d:
                        at = d["access_token"]
                        cfg.setdefault("upstox", {})["access_token"] = at
                        save_config(cfg)
                        print(f"🎉 SUCCESS! Upstox access_token saved: {at[:6]}...{at[-4:]}")
                        self.send_success_html("Upstox")
                    else:
                        err = d.get("message", r.text)
                        print(f"❌ Failed to exchange Upstox token: {err}")
                        self.send_error_html(f"Upstox exchange failed: {err}")
                except Exception as e:
                    self.send_error_html(f"Error during Upstox exchange: {e}")

            else:
                self.send_error_html("No recognized token or code in callback URL.")

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""

        # Dhan Token Save API
        if parsed.path == "/api/dhan":
            try:
                data = json.loads(body)
                token = data.get("access_token", "").strip()
                cfg = load_config()
                cid = cfg.get("dhan", {}).get("client_id", "").strip()
                
                # Verify token with Dhan API
                r = requests.get("https://api.dhan.co/v2/trades", headers={"access-token": token, "client-id": cid, "Content-Type": "application/json"}, timeout=5)
                if r.status_code == 200:
                    cfg.setdefault("dhan", {})["access_token"] = token
                    save_config(cfg)
                    print(f"🎉 SUCCESS! DhanHQ access_token verified and saved.")
                    self.send_json({"success": True, "message": "Dhan token verified and saved!"})
                else:
                    self.send_json({"success": False, "message": f"Dhan token validation failed (HTTP {r.status_code})"})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)})

        # Cloud Sync API
        elif parsed.path == "/api/sync":
            ok, msg = push_to_cloud()
            self.send_json({"success": ok, "message": msg})

        else:
            self.send_response(404)
            self.end_headers()

    def send_success_html(self, broker):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = CALLBACK_SUCCESS_HTML.replace("{broker}", broker)
        self.wfile.write(html.encode("utf-8"))

    def send_error_html(self, error):
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = CALLBACK_ERROR_HTML.replace("{error}", error)
        self.wfile.write(html.encode("utf-8"))

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def main():
    print("=" * 60)
    print("⚡ JARVIS 1-CLICK MORNING TOKEN HUB")
    print("============================================================")
    print(f"🚀 Server running on http://127.0.0.1:{PORT}")
    print("👉 Opening dashboard in your default browser...")
    print("👉 Press Ctrl+C in this terminal when finished.")
    print("=" * 60)

    # Launch browser after a short delay
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

    server = HTTPServer(("127.0.0.1", PORT), TokenHubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Token Hub stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
