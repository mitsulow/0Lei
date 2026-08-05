#!/usr/bin/env python3
"""シューマン共振・生データの宝庫を「密」にする。

schumann-frequency.com の線グラフ・アーカイブ(トムスク srf.jpg・毎日)から
F1〜F4を5分刻みの生値で読み、既存の history/{YYYY-MM}.json に統合する。

- 宝庫の器は既存 history/{月}.json（5分・F1〜F4・{t,F1,F2,F3,F4,src}）。
  Wayback由来で2023-03から疎に存在。ここへ2023-08以降の毎日を流し込んで密にする。
- 読み取り・時刻付け・5分バケット統合は全て既存 fetch_schumann_v6 の関数を再利用。
  → 生成される値は本家ライブ観測と完全に同じ計算式(加工・平均なし)。
- 1枚(D)で D-2,D-1 の2完全日ぶんの全5分点が採れる → 画像は2日おきで全日カバー。
- merge_series_history が5分バケットで重複排除するので何度実行しても増えない。resumable。
"""
import datetime
import io
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

import fetch_schumann_v6 as f6

BASE = "https://cdn.schumann-frequency.com/assets/archiv/{y}/{m:02d}/schumann-frequencies-{d:02d}-{m:02d}-{y}.jpg"
UA = {"User-Agent": "Mozilla/5.0 (0Lei treasure; research)"}
LINE_START = datetime.date(2023, 8, 1)  # 線グラフ・アーカイブの最古(それ以前はスペクトログラムのみ)


def fetch(d):
    req = urllib.request.Request(BASE.format(y=d.year, m=d.month, d=d.day), headers=UA)
    return np.array(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB"))


def main():
    start = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else LINE_START
    end = datetime.date.today()
    templates = f6.load_templates()

    # 2日おきに画像を取り、各画像から D-2,D-1 の2完全日ぶんの5分点を統合
    img_dates = []
    d = start + datetime.timedelta(days=2)
    while d <= end:
        img_dates.append(d)
        d += datetime.timedelta(days=2)
    print(f"対象 {len(img_dates)}枚 ({img_dates[0]}〜{img_dates[-1]})、各3日分の5分生値を統合")

    total = 0
    for i, img_d in enumerate(img_dates, 1):
        try:
            arr = fetch(img_d)
            if f6.verify_layout(arr):
                continue
            calib = f6.ocr_axis_calibration(arr, templates)
            series = f6.extract_series(arr, calib)  # {mode:[(x,hz)]} 前後整合フィルタ済み
            now = datetime.datetime(img_d.year, img_d.month, img_d.day, tzinfo=datetime.timezone.utc)
            n = f6.merge_series_history(series, now)  # 5分バケットで history/{月}.json へ統合
            total += n
        except Exception:
            continue
        if i % 40 == 0:
            print(f"  {i}/{len(img_dates)}枚  新規5分点 {total}  (画像 {img_d})")
        time.sleep(0.3)

    print(f"=== 完了: +{total} 個の5分生値を history/ に統合 ===")
    # 日別サマリーも作り直す(グラフの穴が埋まる)
    for p in sorted(f6.HISTORY_DIR.glob("????-??.json")):
        f6.rebuild_daily(p.stem)
    f6.rebuild_daily_summary()
    print("日別サマリー再生成 完了")


if __name__ == "__main__":
    main()
