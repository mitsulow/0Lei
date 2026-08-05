#!/usr/bin/env python3
"""Wayback Machine からトムスク srf.jpg の過去スナップショットを取得し、
全幅読み取り (fetch_schumann_v6.extract_series) で日別履歴を遡って復元する。

- 1枚の画像に3日ぶん (5分刻み) が描かれているので、スナップショットが
  2〜3日おきにあれば連続した日別データが再構成できる
- 5分バケットの重複防止マージなので、何度実行しても増殖しない (再開可能)
- 処理済みスナップショットは history/wayback_done.json に記録

usage:
  python backfill_wayback.py 20260101 20261231   # 2026年ぶん
  python backfill_wayback.py 20230301 20261231   # 2023年3月〜全部
"""
import datetime
import io
import json
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

import fetch_schumann_v6 as f6

CDX = ("http://web.archive.org/cdx/search/cdx?url={u}"
       "&output=json&from={a}&to={b}&limit=8000")
SOURCES = [
    "sos70.ru/provider.php%3Ffile%3Dsrf.jpg",
    "sosrff.tsu.ru/new/srf.jpg",
    "www.sosrff.tsu.ru/new/srf.jpg",   # www系統: 2011-2013の古いキャプチャがここに(2012=44枚)
]
UA = {"User-Agent": "0Lei-schumann-backfill (personal research; contact mitsulow@gmail.com)"}


def get(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def snapshots(a, b):
    rows = []
    for u in SOURCES:
        try:
            d = json.loads(get(CDX.format(u=u, a=a, b=b), timeout=120))
        except Exception as e:
            print(f"! CDX failed for {u}: {e}")
            continue
        for r in d[1:]:
            ts, orig, status, digest = r[1], r[2], r[4], r[5]
            if status == "200":
                rows.append((ts, orig, digest))
    rows.sort()
    seen, out = set(), []
    for ts, orig, dg in rows:
        if dg in seen:
            continue  # 同一画像は1回だけ
        seen.add(dg)
        out.append((ts, orig))
    return out


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else "20260101"
    b = sys.argv[2] if len(sys.argv) > 2 else "20261231"
    snaps = snapshots(a, b)
    print(f"=== {len(snaps)} unique snapshots {a}..{b} ===")
    done_file = f6.HISTORY_DIR / "wayback_done.json"
    done = set(f6.load_json(done_file) or [])
    templates = f6.load_templates()
    total = 0
    for i, (ts, orig) in enumerate(snaps):
        if ts in done:
            continue
        url = f"https://web.archive.org/web/{ts}if_/{orig}"
        try:
            raw = get(url)
            arr = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            if f6.verify_layout(arr):
                print(f"  [{i + 1}/{len(snaps)}] {ts}: layout mismatch — skip")
                done.add(ts)
                f6.save_json(done_file, sorted(done))
                continue
            calib = f6.ocr_axis_calibration(arr, templates)
            series = f6.extract_series(arr, calib)
            snap_utc = datetime.datetime.strptime(ts, "%Y%m%d%H%M%S").replace(
                tzinfo=datetime.timezone.utc)
            n = f6.merge_series_history(series, snap_utc)
            total += n
            print(f"  [{i + 1}/{len(snaps)}] {ts}: +{n} samples")
        except Exception as e:
            # ネットワーク系エラーは done にせず次回再試行
            print(f"  [{i + 1}/{len(snaps)}] {ts}: ERROR {e}")
            time.sleep(4)
            continue
        done.add(ts)
        f6.save_json(done_file, sorted(done))
        time.sleep(1.2)  # アーカイブへの礼儀 (レート制限回避)

    # 日次集計と全期間サマリーを再生成
    for pth in sorted(f6.HISTORY_DIR.glob("????-??.json")):
        f6.rebuild_daily(pth.stem)
    f6.rebuild_daily_summary()
    print(f"=== done: +{total} new samples ===")


if __name__ == "__main__":
    main()
