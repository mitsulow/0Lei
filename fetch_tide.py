#!/usr/bin/env python3
"""
気象庁の潮位表テキストデータを取得し、港ごとのJSONファイルに変換する。

フォーマット仕様（気象庁公式）:
    1-72 カラム  : 毎時潮位（3桁×24時間）cm
    73-78 カラム : 年月日（YYMMDD）
    79-80 カラム : 地点記号（2桁）
    81-108 カラム: 満潮時刻・潮位（時刻4桁 + 潮位3桁）× 4回
    109-136 カラム: 干潮時刻・潮位（時刻4桁 + 潮位3桁）× 4回
    欠測: 時刻=9999, 潮位=999

出力: data/tide/{YYYY}/{CODE}.json
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# 対象港リスト（気象庁 潮位表掲載地点 2027 より緯度経度を10進度に変換）
# 日本全国をカバーする主要20港
PORTS = [
    {"code": "WN", "name": "稚内",   "lat": 45.400, "lon": 141.683},
    {"code": "HK", "name": "函館",   "lat": 41.783, "lon": 140.717},
    {"code": "AO", "name": "青森",   "lat": 40.833, "lon": 140.767},
    {"code": "MY", "name": "宮古",   "lat": 39.650, "lon": 141.983},
    {"code": "SD", "name": "仙台新港", "lat": 38.267, "lon": 141.000},
    {"code": "ON", "name": "小名浜", "lat": 36.933, "lon": 140.900},
    {"code": "TK", "name": "東京",   "lat": 35.650, "lon": 139.767},
    {"code": "QS", "name": "横浜",   "lat": 35.450, "lon": 139.650},
    {"code": "NG", "name": "名古屋", "lat": 35.083, "lon": 136.883},
    {"code": "OS", "name": "大阪",   "lat": 34.650, "lon": 135.433},
    {"code": "KB", "name": "神戸",   "lat": 34.683, "lon": 135.183},
    {"code": "TA", "name": "高松",   "lat": 34.350, "lon": 134.050},
    {"code": "Q8", "name": "広島",   "lat": 34.350, "lon": 132.467},
    {"code": "KC", "name": "高知",   "lat": 33.500, "lon": 133.567},
    {"code": "UW", "name": "宇和島", "lat": 33.233, "lon": 132.550},
    {"code": "TS", "name": "土佐清水", "lat": 32.783, "lon": 132.967},
    {"code": "QC", "name": "大分",   "lat": 33.267, "lon": 131.683},
    {"code": "AB", "name": "油津",   "lat": 31.583, "lon": 131.417},
    {"code": "KG", "name": "鹿児島", "lat": 31.600, "lon": 130.567},
    {"code": "NA", "name": "那覇",   "lat": 26.217, "lon": 127.667},
    {"code": "CC", "name": "父島",   "lat": 27.100, "lon": 142.200},
]

BASE_URL = "https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{year}/{code}.txt"


def parse_line(line):
    """
    1行（1日分）をパースして (YYYY-MM-DD, {"high": [...], "low": [...]}) を返す。
    満潮・干潮は [["HH:MM", level_cm], ...] の形式。
    """
    if len(line) < 136:
        return None

    try:
        yy = int(line[72:74])
        mm = int(line[74:76])
        dd = int(line[76:78])
    except ValueError:
        return None

    # 気象庁テキストは西暦下2桁。2000年代とみなす（2000-2099）
    year = 2000 + yy
    try:
        date_str = f"{year:04d}-{mm:02d}-{dd:02d}"
        datetime(year, mm, dd)  # バリデーション
    except ValueError:
        return None

    def extract_tides(start):
        """start カラム以降に (時刻4桁 + 潮位3桁) × 4 を取り出す"""
        tides = []
        for i in range(4):
            ofs = start + i * 7
            t_str = line[ofs:ofs + 4]
            l_str = line[ofs + 4:ofs + 7]
            if not t_str.strip() or t_str.strip() == "9999":
                continue
            try:
                hh = int(t_str[:2])
                mn = int(t_str[2:])
                level = int(l_str)
                if level == 999:  # 欠測
                    continue
                tides.append([f"{hh:02d}:{mn:02d}", level])
            except ValueError:
                continue
        return tides

    return date_str, {
        "high": extract_tides(80),   # 81-108カラム（0-indexed: 80-107）
        "low":  extract_tides(108),  # 109-136カラム（0-indexed: 108-135）
    }


def fetch_port(code, year, retries=3):
    """指定港・年のテキストデータを取得。失敗時は再試行。"""
    url = BASE_URL.format(year=year, code=code)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tsukiyoga-tide-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                # 翌年データがまだ公開されていない等
                return None
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {code} {year}: {last_err}")


def write_port_json(port, year, text, out_dir):
    """テキストをパースしてJSONに書き出す。書き出した日数を返す。"""
    days = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        result = parse_line(line)
        if result:
            date_str, data = result
            days[date_str] = data

    out = {
        "code": port["code"],
        "name": port["name"],
        "lat": port["lat"],
        "lon": port["lon"],
        "year": year,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "JMA (Japan Meteorological Agency)",
        "days": days,
    }

    out_path = out_dir / f"{port['code']}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return len(days)


def main():
    now = datetime.now(timezone.utc)
    years = [now.year]
    # 11月以降は翌年分も取得（気象庁は翌年分を11月頃に公開）
    if now.month >= 11:
        years.append(now.year + 1)

    root = Path(__file__).resolve().parent  # リポジトリルート
    base_out = root / "data" / "tide"
    base_out.mkdir(parents=True, exist_ok=True)

    # 港メタ情報
    ports_meta = {
        "updated_at": now.isoformat(),
        "source": "JMA",
        "ports": [{"code": p["code"], "name": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in PORTS],
    }
    with open(base_out / "ports.json", "w", encoding="utf-8") as f:
        json.dump(ports_meta, f, ensure_ascii=False, indent=2)
    print(f"Wrote ports.json ({len(PORTS)} ports)")

    # 各港×各年を処理
    success = 0
    skipped = 0
    failed = 0
    for year in years:
        out_dir = base_out / str(year)
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Year {year} ===")
        for port in PORTS:
            try:
                text = fetch_port(port["code"], year)
                if text is None:
                    print(f"  [skip] {port['code']} {port['name']}: no data (404)")
                    skipped += 1
                    continue
                n = write_port_json(port, year, text, out_dir)
                print(f"  [ok]   {port['code']} {port['name']}: {n} days")
                success += 1
                time.sleep(0.5)  # 気象庁への負荷軽減
            except Exception as e:
                print(f"  [FAIL] {port['code']} {port['name']}: {e}", file=sys.stderr)
                failed += 1

    print(f"\nSummary: success={success}, skipped={skipped}, failed={failed}")
    if failed > 0 and success == 0:
        sys.exit(1)  # 全滅ならエラー終了（GitHub Actionsが失敗通知を出す）


if __name__ == "__main__":
    main()
