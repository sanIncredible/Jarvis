#!/usr/bin/env python3
"""
⚡ JARVIS TOKEN & CREDENTIALS HEALTH CHECKER
Quickly inspects the live validity of all broker and messaging tokens.
"""

import sys
import json
import requests
import urllib.request
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CONFIG_FILE = Path(__file__).resolve().parent / "config_credentials.json"
UPSTOX_TOKEN_FILE = Path(__file__).resolve().parent / "upstoxtoken.txt"

def send_telegram_direct(bot_token, chat_id, message, reply_markup=None, group_id=None, thread_id=None):
    """Sends alert message directly to Telegram via HTTPS, routing to designated forum topic if configured."""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        target_chat = group_id if (group_id and thread_id) else chat_id
        payload = {
            "chat_id": target_chat,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if group_id and thread_id:
            payload["message_thread_id"] = int(thread_id)
        if reply_markup:
            payload["reply_markup"] = reply_markup
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "Jarvis-Token-Checker"
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")
        return False


def check_all_tokens(notify=False):
    import urllib.request
    print("=" * 60)
    print("⚡ JARVIS BROKER & API CREDENTIALS HEALTH CHECK")
    print("=" * 60)
    results = {
        "telegram": False,
        "upstox": False,
        "dhan": False,
        "zerodha": False,
        "errors": []
    }

    if not CONFIG_FILE.is_file():
        print(f"❌ {CONFIG_FILE.name} not found!")
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 1. Telegram Check
    tg = cfg.get("telegram", {})
    bot_token = tg.get("bot_token", "").strip()
    chat_id = tg.get("chat_id", "").strip()
    if bot_token and chat_id:
        try:
            r = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)
            if r.status_code == 200:
                b_name = r.json().get("result", {}).get("username", "Bot")
                print(f"✅ Telegram Bot    : ACTIVE (@{b_name})")
                results["telegram"] = True
            else:
                print(f"❌ Telegram Bot    : FAILED (HTTP {r.status_code})")
        except Exception as e:
            print(f"⚠️ Telegram Bot    : ERROR ({e})")
    else:
        print("⚠️ Telegram Bot    : NOT CONFIGURED")

    # 2. Upstox Token Check
    upstox_token = cfg.get("upstox", {}).get("access_token", "").strip()
    if not upstox_token and UPSTOX_TOKEN_FILE.is_file():
        try:
            with open(UPSTOX_TOKEN_FILE, "r", encoding="utf-8") as f:
                upstox_token = f.read().strip()
        except Exception:
            pass

    if upstox_token:
        headers = {"Authorization": f"Bearer {upstox_token}", "Accept": "application/json"}
        try:
            r = requests.get("https://api.upstox.com/v2/market-quote/ltp?instrument_key=NSE_EQ|RELIANCE", headers=headers, timeout=5)
            if r.status_code == 200:
                print("✅ Upstox Token    : ACTIVE (Scanner live feed OK)")
                results["upstox"] = True
            else:
                print(f"❌ Upstox Token    : EXPIRED (HTTP {r.status_code})")
        except Exception as e:
            print(f"⚠️ Upstox Token    : ERROR ({e})")
    else:
        print("⚠️ Upstox Token    : NOT CONFIGURED")

    # 3. Dhan Token Check
    dhan = cfg.get("dhan", {})
    cid = dhan.get("client_id", "").strip()
    dtok = dhan.get("access_token", "").strip()
    if cid and dtok:
        headers = {"access-token": dtok, "client-id": cid, "Content-Type": "application/json"}
        try:
            r = requests.get("https://api.dhan.co/v2/trades", headers=headers, timeout=5)
            if r.status_code == 200:
                print("✅ DhanHQ Token    : ACTIVE (Orderbook sync OK)")
                results["dhan"] = True
            elif r.status_code == 401:
                print("⚠️ DhanHQ Token    : EXPIRED (Needs 30-day renewal from web.dhan.co)")
            else:
                print(f"❌ DhanHQ Token    : HTTP {r.status_code}")
        except Exception as e:
            print(f"⚠️ DhanHQ Token    : ERROR ({e})")
    else:
        print("⚠️ DhanHQ Token    : NOT CONFIGURED")

    # 4. Zerodha Kite Token Check
    kite = cfg.get("zerodha", {})
    ak = kite.get("api_key", "").strip()
    at = kite.get("access_token", "").strip()
    if ak and at:
        headers = {"X-Kite-Version": "3", "Authorization": f"token {ak}:{at}"}
        try:
            r = requests.get("https://api.kite.trade/trades", headers=headers, timeout=5)
            if r.status_code == 200:
                print("✅ Zerodha Token   : ACTIVE (Orderbook sync OK)")
                results["zerodha"] = True
            elif r.status_code == 403:
                print("⚠️ Zerodha Token   : EXPIRED (Daily 6:00 AM renewal or CSV fallback)")
            else:
                print(f"❌ Zerodha Token   : HTTP {r.status_code}")
        except Exception as e:
            print(f"⚠️ Zerodha Token   : ERROR ({e})")
    else:
        print("⚠️ Zerodha Token   : NOT CONFIGURED")

    print("=" * 60)

    # If --notify passed, dispatch Telegram alert card to Token Refresh topic
    if notify and bot_token and chat_id:
        group_id = tg.get("group_id")
        topics = tg.get("topics", {})
        thread_id = topics.get("token_refresh") or topics.get("tokens") or 2469
        now_str = datetime.now().strftime("%H:%M IST")
        has_failure = not results["upstox"] or not results["dhan"]
        
        if has_failure:
            lines = [
                f"🚨 <b>JARVIS PRE-MARKET TOKEN ALARM — {now_str}</b>",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]
            if not results["upstox"]:
                lines.append("❌ <b>Upstox Token : EXPIRED / INVALID</b>")
                lines.append("• <i>Live 3m scanner & 1-tap buy orders will fail at 09:15 AM!</i>")
                lines.append("• <b>Action:</b> Generate new token and reply:")
                lines.append("  <code>/upstox &lt;TOKEN&gt;</code> or paste directly into this chat.\n")
            if not results["dhan"]:
                lines.append("⚠️ <b>DhanHQ Token : INACTIVE / EXPIRED</b>")
                lines.append("• <i>MTF orderbook sync requires active Dhan token.</i>")
                lines.append("• <b>Action:</b> Reply <code>/dhan &lt;TOKEN&gt;</code>\n")
            if not results["zerodha"]:
                lines.append("⚪ <b>Zerodha Token : Inactive / Expired</b> (Optional CNC)")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("🕒 <i>Market opens at 09:15 AM. Please authenticate now!</i>")
            domain = "https://tidbit-component-national.ngrok-free.dev"
            markup = {
                "inline_keyboard": [
                    [{"text": "🚀 1-Click Upstox Login", "url": f"{domain}/login/upstox"}],
                    [{"text": "⚡ 1-Click Zerodha Login", "url": f"{domain}/login/zerodha"}]
                ]
            }
            msg = "\n".join(lines)
            send_telegram_direct(bot_token, chat_id, msg, reply_markup=markup, group_id=group_id, thread_id=thread_id)
            print("📢 Sent Token Expiry Alarm to Telegram Token Refresh topic!")
        else:
            lines = [
                f"✅ <b>JARVIS MORNING CREDENTIALS HEALTHY — {now_str}</b>",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "• Upstox (Feed & Orders) : 🟢 ACTIVE",
                "• DhanHQ (MTF Orders)    : 🟢 ACTIVE",
                f"• Zerodha (CNC Orders)   : {'🟢 ACTIVE' if results['zerodha'] else '⚪ Offline / Unconfigured'}",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "🌟 <i>All systems ready for 09:14 Situational Awareness & 09:15 Market Open!</i>"
            ]
            msg = "\n".join(lines)
            send_telegram_direct(bot_token, chat_id, msg, group_id=group_id, thread_id=thread_id)
            print("📢 Sent Morning Health Confirmation to Telegram Token Refresh topic!")

    return results

if __name__ == "__main__":
    notify_flag = "--notify" in sys.argv
    check_all_tokens(notify=notify_flag)
