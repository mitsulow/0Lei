#!/usr/bin/env python3
"""過去データの取り込み(1回もの) + 太陽活動指数のバックフィル。

1) legacy: デスクトップのai-talk-roomで2023年に抽出済みの
   schumann_daily.csv (schumann-resonance.earth のアーカイブ由来、
   2021-04-09〜2023-06-22、1日約400点のピクセル解析) を
   history/legacy_daily.json に変換する。
   ※アーカイブサイトは現在ダミー画像を返すため再取得は不可能。このCSVが唯一の遺産。

2) solar: GFZポツダムの日別Ap指数 (CC BY 4.0) を2021-04-01から全部取り、
   history/solar_daily.json に保存する。以後の毎日更新は fetch_schumann_v6 が行う。
"""
import csv
import datetime
import json
import urllib.request
from pathlib import Path

HISTORY = Path("history")
CSV_PATH = Path(r"C:\Users\waras\OneDrive\デスクトップ\AI関連\ai-talk-room\schumann_data\schumann_daily.csv")


def build_legacy():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                v = float(r["daily_avg_hz"])
                n = int(r.get("data_points") or 0)
            except (ValueError, TypeError):
                continue
            if 7.0 <= v <= 8.6:
                rows.append({"d": r["date"], "f1": round(v, 4), "n": n, "src": "sre"})
    rows.sort(key=lambda e: e["d"])
    out = {"schema_version": "1.0",
           "source": "schumann-resonance.earth archive (pixel-extracted 2023, Tomsk data)",
           "days": rows}
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / "legacy_daily.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"+ legacy_daily.json ({len(rows)} days: {rows[0]['d']} -> {rows[-1]['d']})")


def build_solar():
    start = "2021-04-01T00:00:00Z"
    end = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT23:59:59Z")
    url = f"https://kp.gfz.de/app/json/?start={start}&end={end}&index=Ap"
    req = urllib.request.Request(url, headers={"User-Agent": "0Lei-solar"})
    d = json.load(urllib.request.urlopen(req, timeout=120))
    days = []
    for t, ap in zip(d.get("datetime", []), d.get("Ap", [])):
        if ap is not None:
            days.append({"d": t[:10], "ap": ap})
    out = {"schema_version": "1.0",
           "source": "GFZ Potsdam Kp/Ap index (CC BY 4.0)",
           "days": days}
    (HISTORY / "solar_daily.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"+ solar_daily.json ({len(days)} days: {days[0]['d']} -> {days[-1]['d']})")


if __name__ == "__main__":
    build_legacy()
    build_solar()
