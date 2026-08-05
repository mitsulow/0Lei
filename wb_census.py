# -*- coding: utf-8 -*-
import json, urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0"}
urls = [
    "sosrff.tsu.ru/new/srf.jpg",
    "sosrff.tsu.ru/srf.jpg",
    "sos70.ru/provider.php?file=srf.jpg",
]
for u in urls:
    q = ("https://web.archive.org/cdx/search/cdx?url=" +
         urllib.parse.quote(u, safe="") +
         "&output=json&from=2014&to=2024&limit=30000")
    try:
        raw = urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=60).read()
        d = json.loads(raw)
    except Exception as e:
        print(f"=== {u} === 失敗: {e}")
        continue
    rows = d[1:] if d else []
    ok = [r for r in rows if len(r) > 4 and r[4] == "200"]
    uniq = {r[5]: r for r in ok}
    print(f"=== {u} ===")
    print(f"  200応答 {len(ok)} / ユニーク画像 {len(uniq)}")
    print("  年別ユニーク:", dict(sorted(Counter(r[1][:4] for r in uniq.values()).items())))
