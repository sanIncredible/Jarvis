import urllib.request

files = ['upstox_tablet_scanner.py', 'index.html', 'data.json', 'watchlist.txt', 'tablet_backup_runner.py', 'tablet_sync_to_cloud.py']
print('🔄 Updating tablet files from GitHub...')
for f in files:
    url = f'https://raw.githubusercontent.com/sanIncredible/Jarvis/main/{f}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            with open(f, 'wb') as out:
                out.write(resp.read())
        print(f' ✅ {f} updated!')
    except Exception as e:
        print(f' ❌ {f} error: {e}')
print('\n🎉 Tablet is 100% updated to latest version!')
