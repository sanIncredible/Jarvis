import os
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
files = ['upstox_tablet_scanner.py', 'index.html', 'data.json', 'watchlist.txt', 'tablet_backup_runner.py', 'tablet_sync_to_cloud.py']

print("=" * 60)
print("🔄 UPDATING TABLET FILES FROM GITHUB")
print(f"📁 Download Directory: {BASE_DIR}")
print("=" * 60)

for f in files:
    url = f"https://raw.githubusercontent.com/sanIncredible/Jarvis/main/{f}"
    dest_path = os.path.join(BASE_DIR, f)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            with open(dest_path, "wb") as out:
                out.write(resp.read())
        print(f" ✅ {f} updated!")
    except Exception as e:
        print(f" ❌ {f} error: {e}")

print("=" * 60)
print(f"🎉 All files successfully saved to:\n   {BASE_DIR}")
print("=" * 60)
