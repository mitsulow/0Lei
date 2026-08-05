#!/usr/bin/env python3
"""三重クロスチェック版・宝の山ビルダー（夜間バッチ）。

1枚の画像に3日分が写る性質を使い、同じ日・同じ5分スロットを複数の画像から読んで
「合議(中央値)」で確定する。1枚のOCRミスや局所ノイズを、他の2枚が打ち消す。

- schumann-frequency.com 線グラフを【毎日】取得(=各日が最大3枚に登場)。
- スロット(UTC5分)ごとにモード別の読み値を集め、中央値±0.12Hz外の外れ値を捨て、
  残りの中央値を確定値とする。読んだ枚数(agree)も記録し信頼度が分かる。
- 修正版 fetch_schumann_v6(透かし除外済み)の extract_series を使用。
- 月別 history/{YYYY-MM}.json に {t,F1,F2,F3,F4,src,agree} 形式で保存。
- resumable: 進捗を cross_progress.json に記録、途中再開で既処理画像はスキップ。
"""
import datetime
import io
import json
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

import fetch_schumann_v6 as f6

HIST = Path("history")
BASE = "https://cdn.schumann-frequency.com/assets/archiv/{y}/{m:02d}/schumann-frequencies-{d:02d}-{m:02d}-{y}.jpg"
UA = {"User-Agent": "Mozilla/5.0 (0Lei cross-treasure; research)"}
START = datetime.date(2023, 8, 1)
DEV = 0.12   # 合議: 中央値からこれ以上離れた読みは外れ値
MODES = ("F1", "F2", "F3", "F4")
PROG = HIST / "cross_progress.json"


def fetch(d):
    req = urllib.request.Request(BASE.format(y=d.year, m=d.month, d=d.day), headers=UA)
    return np.array(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB"))


def image_points(img_date, templates):
    """画像から5分スロット(UTC epoch)ごとの {mode: hz} を返す。加工なしの生読み。"""
    arr = fetch(img_date)
    if f6.verify_layout(arr):
        return {}
    calib = f6.ocr_axis_calibration(arr, templates)
    series = f6.extract_series(arr, calib)
    allx = [x for pts in series.values() for x, _ in pts]
    if not allx:
        return {}
    xr = max(allx)
    now = datetime.datetime(img_date.year, img_date.month, img_date.day, tzinfo=datetime.timezone.utc)
    day = 0 if xr < f6.PLOT_X0 + f6.DAY_PX else (1 if xr < f6.PLOT_X0 + 2 * f6.DAY_PX else 2)
    hour = (xr - (f6.PLOT_X0 + day * f6.DAY_PX)) / f6.DAY_PX * 24
    stale, _ = f6.data_age_min(day, hour, now)
    t_right = now - datetime.timedelta(minutes=stale)
    out = {}
    for mode, pts in series.items():
        for x, hz in pts:
            t = t_right - datetime.timedelta(minutes=(xr - x) * 5)
            epoch = int(t.timestamp() // 300) * 300
            out.setdefault(epoch, {})[mode] = float(hz)
    return out


def main():
    templates = f6.load_templates()
    today = datetime.date.today()
    start = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else START

    # 各日が最大3枚に登場するよう、画像は毎日取得
    img_dates = []
    d = start + datetime.timedelta(days=2)
    while d <= today:
        img_dates.append(d.isoformat())
        d += datetime.timedelta(days=1)

    done = set(json.load(open(PROG, encoding="utf-8"))) if PROG.exists() else set()
    # スロット別に読み値を貯める: acc[epoch][mode] = [hz,...]
    acc = defaultdict(lambda: defaultdict(list))

    processed = 0
    for iso in img_dates:
        if iso in done:
            continue
        try:
            pts = image_points(datetime.date.fromisoformat(iso), templates)
        except Exception:
            done.add(iso)
            continue
        for epoch, modes in pts.items():
            for mode, hz in modes.items():
                acc[epoch][mode].append(hz)
        done.add(iso)
        processed += 1
        if processed % 60 == 0:
            _flush(acc)
            json.dump(sorted(done), open(PROG, "w", encoding="utf-8"))
            print(f"  {processed}枚処理 / スロット {len(acc)} (画像 {iso})", flush=True)
        time.sleep(0.25)

    _flush(acc)
    json.dump(sorted(done), open(PROG, "w", encoding="utf-8"))
    # 日別サマリー再生成
    for p in sorted(HIST.glob("????-??.json")):
        f6.rebuild_daily(p.stem)
    f6.rebuild_daily_summary()
    total = sum(len(m) for e, m in acc.items())
    print(f"=== 完了: {processed}枚処理・{len(acc)}スロット確定 ===", flush=True)


def _consensus(vals):
    """合議: 中央値±DEV内の読みの中央値を返す。読み枚数も。"""
    if not vals:
        return None, 0
    med = float(np.median(vals))
    kept = [v for v in vals if abs(v - med) <= DEV]
    if not kept:
        return round(med, 2), len(vals)
    return round(float(np.median(kept)), 2), len(kept)


def _flush(acc):
    """acc の内容を月別 history/{月}.json へ確定書き込み(既存とマージ)。"""
    by_month = defaultdict(dict)
    for epoch, modes in acc.items():
        t = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
        mk = t.strftime("%Y-%m")
        rec = {"t": t.isoformat()}
        agree = 0
        for mode in MODES:
            v, n = _consensus(modes.get(mode, []))
            rec[mode] = v
            agree = max(agree, n)
        rec["src"] = "cross"
        rec["agree"] = agree
        by_month[mk][t.isoformat()] = rec
    for mk, recs in by_month.items():
        p = HIST / f"{mk}.json"
        existing = {}
        if p.exists():
            for e in json.load(open(p, encoding="utf-8")):
                existing[e["t"]] = e
        existing.update(recs)  # クロス確定値で上書き
        arr = [existing[t] for t in sorted(existing)]
        json.dump(arr, open(p, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
