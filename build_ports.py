"""JMAから全港の lat/lon を取得して PORTS Python リテラルを出力。

使い方:
    python build_ports.py > /tmp/ports.txt

stdout に下記形式で出力。 fetch_tide.py の PORTS = [...] ブロックを置換する。

    PORTS = [
        {"code": "WN", "name": "稚内", "lat": 45.4, "lon": 141.683},
        ...
    ]
"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'
import re
import sys
import urllib.request
import concurrent.futures

INDEX_URL = "https://www.data.jma.go.jp/kaiyou/db/tide/suisan/index.php"
DETAIL_URL = "https://www.data.jma.go.jp/kaiyou/db/tide/suisan/suisan.php?stn={code}"
UA = {"User-Agent": "tsukiyoga-tide-builder/1.0"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read().decode('utf-8', errors='replace')


def parse_index(html):
    """option value の港コード(大文字始まり2文字)+地点名を抽出"""
    pattern = re.compile(r'<option value="([A-Z][A-Z0-9])"[^>]*>([^<]+)</option>')
    return [(code, name.strip()) for code, name in pattern.findall(html)]


def parse_lat_lon(html):
    """例: '35°39′N' → 35.65, '139°46′E' → 139.7667"""
    m_lat = re.search(r'緯度：</td><td[^>]*>(\d+)°(\d+)′([NS])', html)
    m_lon = re.search(r'経度：</td><td[^>]*>(\d+)°(\d+)′([EW])', html)
    if not m_lat or not m_lon:
        return None
    lat = int(m_lat.group(1)) + int(m_lat.group(2)) / 60
    if m_lat.group(3) == 'S':
        lat = -lat
    lon = int(m_lon.group(1)) + int(m_lon.group(2)) / 60
    if m_lon.group(3) == 'W':
        lon = -lon
    return round(lat, 4), round(lon, 4)


def get_port(code, name):
    try:
        html = fetch(DETAIL_URL.format(code=code))
        ll = parse_lat_lon(html)
        if ll:
            return {"code": code, "name": name, "lat": ll[0], "lon": ll[1]}
        print(f"  ! {code} ({name}): lat/lon not found", file=sys.stderr)
    except Exception as e:
        print(f"  ! {code} ({name}): {e}", file=sys.stderr)
    return None


def main():
    print("Fetching index...", file=sys.stderr)
    html = fetch(INDEX_URL)
    raw = parse_index(html)
    print(f"  {len(raw)} ports found", file=sys.stderr)

    print("Fetching details (parallel x10)...", file=sys.stderr)
    ports = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(get_port, c, n): (c, n) for c, n in raw}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            if r:
                ports.append(r)
            done += 1
            if done % 30 == 0:
                print(f"  {done}/{len(raw)}", file=sys.stderr)

    ports.sort(key=lambda p: p["code"])
    print(f"\nTotal: {len(ports)} ports with lat/lon", file=sys.stderr)

    # stdout: Python リテラル
    print("PORTS = [")
    for p in ports:
        print(f'    {{"code": "{p["code"]}", "name": "{p["name"]}", "lat": {p["lat"]}, "lon": {p["lon"]}}},')
    print("]")


if __name__ == "__main__":
    main()
