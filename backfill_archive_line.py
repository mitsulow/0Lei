#!/usr/bin/env python3
"""schumann-frequency.com の【線グラフ】アーカイブから飛び地を補完する（本命）。

- URL: cdn.schumann-frequency.com/assets/archiv/{Y}/{M}/schumann-frequencies-{D}-{M}-{Y}.jpg
- これはトムスク srf.jpg そのもの(1006x340)。既存の fetch_schumann_v6 が無改造で読める。
- 画像は (D-2,D-1,D) の3日分。既存の merge_series_history(5分バケット・JST日区切り)へ流し、
  日別平均は本家データと完全に同じ計算式で出る → オフセット補正すら不要。
- 既存 daily_summary は変えず、無い日だけ history/archive_line_fill.json に貯める。
  検証OK後に本統合。
"""
import datetime
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

import fetch_schumann_v6 as f6

HIST = Path("history")
BASE = "https://cdn.schumann-frequency.com/assets/archiv/{y}/{m:02d}/schumann-frequencies-{d:02d}-{m:02d}-{y}.jpg"
UA = {"User-Agent": "Mozilla/5.0 (0Lei backfill; research)"}
ARCHIVE_START = datetime.date(2023, 8, 1)
SANE = (7.2, 8.35)  # F1日平均の妥当域


def fetch(d):
    req = urllib.request.Request(BASE.format(y=d.year, m=d.month, d=d.day), headers=UA)
    raw = urllib.request.urlopen(req, timeout=30).read()
    return np.array(Image.open(io.BytesIO(raw)).convert("RGB"))


def image_daily_f1(img_date, templates):
    """画像(img_date)から、そこに写る各完全日のF1日平均(JST区切り)を返す {date: (mean,n)}"""
    arr = fetch(img_date)
    if f6.verify_layout(arr):
        return {}
    calib = f6.ocr_axis_calibration(arr, templates)
    series = f6.extract_series(arr, calib)  # {mode: [(x,hz),...]} 前後整合フィルタ済み
    f1 = series.get("F1", [])
    if not f1:
        return {}
    # x → 時刻。3日ウィンドウの右端が img_date。DAY_PX=288(24h)。JSTで日付に振り分け
    now = datetime.datetime(img_date.year, img_date.month, img_date.day, tzinfo=datetime.timezone.utc)
    xr = max(x for x, _ in f1)
    day = 0 if xr < f6.PLOT_X0 + f6.DAY_PX else (1 if xr < f6.PLOT_X0 + 2 * f6.DAY_PX else 2)
    hour = (xr - (f6.PLOT_X0 + day * f6.DAY_PX)) / f6.DAY_PX * 24
    stale, _ = f6.data_age_min(day, hour, now)
    t_right = now - datetime.timedelta(minutes=stale)
    buckets = {}
    for x, hz in f1:
        t = t_right - datetime.timedelta(minutes=(xr - x) * 5)
        dk = (t + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")  # JST区切り
        buckets.setdefault(dk, []).append(hz)
    out = {}
    for dk, vs in buckets.items():
        if len(vs) >= 60:  # 半日以上のサンプルがある完全な日だけ
            m = float(np.median(vs))
            if SANE[0] <= m <= SANE[1]:
                out[dk] = (round(m, 4), len(vs))
    return out


def main():
    summary = json.load(open(HIST / "daily_summary.json", encoding="utf-8"))["days"]
    have = set(e["d"] for e in summary)
    templates = f6.load_templates()

    today = datetime.date.today()
    gaps = []
    d = ARCHIVE_START
    while d < today:
        if d.isoformat() not in have:
            gaps.append(d.isoformat())
        d += datetime.timedelta(days=1)
    print(f"飛び地: {len(gaps)}日 ({gaps[0]}〜{gaps[-1]})")

    fill_path = HIST / "archive_line_fill.json"
    fill = {}
    if fill_path.exists():
        for e in json.load(open(fill_path, encoding="utf-8")).get("days", []):
            fill[e["d"]] = e

    need = set(gaps) - set(fill.keys())
    # 1枚(img_date)で img_date-2, img_date-1 の2完全日が採れる。画像は「対象日+1」で中日として拾う
    img_dates = sorted({(datetime.date.fromisoformat(g) + datetime.timedelta(days=1)) for g in need})
    done = 0
    for img_d in img_dates:
        if img_d > today:
            continue
        try:
            daily = image_daily_f1(img_d, templates)
        except Exception:
            continue
        for dk, (m, n) in daily.items():
            if dk in need and dk not in fill:
                fill[dk] = {"d": dk, "f1": m, "n": n, "src": "archive-line"}
                done += 1
        if done and done % 50 == 0:
            _save(fill_path, fill)
            print(f"  ...{done}日 補完 (画像 {img_d})")
        time.sleep(0.35)
    _save(fill_path, fill)
    print(f"=== 完了: {len(fill)}日 → archive_line_fill.json ===")


def _save(path, fill):
    json.dump({"schema_version": "1.0",
               "source": "schumann-frequency.com line-graph archive (Tomsk srf, same reader as live)",
               "days": [fill[k] for k in sorted(fill)]},
              open(path, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
