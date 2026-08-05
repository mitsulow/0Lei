# -*- coding: utf-8 -*-
import json, urllib.request, urllib.parse, time
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0"}
# トムスクの周波数線グラフのあらゆる別名・ミラーを総当たり
urls = [
    "sos70.ru/provider.php?file=srf.jpg",
    "sosrff.tsu.ru/srf.jpg",
    "sosrff.tsu.ru/new/frequency.jpg",
    "sosrff.tsu.ru/frequency.jpg",
    "www.sosrff.tsu.ru/new/srf.jpg",
    "sosrff.tsu.ru/*",          # 全リソース(srf系を拾う)
]
for u in urls:
    q = ("https://web.archive.org/cdx/search/cdx?url=" +
         urllib.parse.quote(u, safe="") +
         "&output=json&from=2010&to=2024&limit=40000")
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=60).read()
            d = json.loads(raw)
            break
        except Exception as e:
            if attempt == 2:
                print(f"=== {u} === 失敗: {e}")
                d = None
            time.sleep(5)
    if not d:
        continue
    rows = d[1:] if d else []
    ok = [r for r in rows if len(r) > 4 and r[4] == "200"]
    if u.endswith("*"):
        # srf/frequencyを含む画像だけ
        srf = [r for r in ok if ("srf" in r[2].lower() or "frequen" in r[2].lower()) and r[2].lower().endswith(".jpg")]
        by = Counter(r[2].split("/")[-1] for r in srf)
        print(f"=== {u} === srf/freq画像 {len(srf)}件 ファイル名別: {dict(by.most_common(8))}")
    else:
        uniq = {r[5]: r for r in ok}
        print(f"=== {u} === 200:{len(ok)} ユニーク:{len(uniq)} 年別:{dict(sorted(Counter(r[1][:4] for r in uniq.values()).items()))}")
