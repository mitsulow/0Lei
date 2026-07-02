#!/usr/bin/env python3
"""
Schumann Resonance Fetcher v6 - Deterministic Pixel Extraction
srf.jpg（折れ線グラフ）をピクセル解析で決定論的に読み取る。
v5 までの Claude Vision 読み取りを置換:
  - API コストゼロ
  - 誤読・幻覚なし (存在しない F5 を読まない)
  - グラフ構造が変わったら status:error で安全に停止 (前回値を保持)

グラフ構造 (sosrff.tsu.ru / sos70.ru の srf.jpg):
  - プロット領域: x=71..935, y=30..310 (グリッド 20px 間隔)
  - 3日分、1日 288px (2時間 = 24px)
  - F1=白, F2=黄, F3=赤, F4=緑 の4本 (F5 は存在しない)
  - 縦軸 (20px グリッドごとの目盛):
      F1: 8.15@y30  → 7.46@y130  (0.69Hz/100px)
      F2: 14.50@y90 → 12.90@y190 (1.60Hz/100px)
      F3: 20.80@y150→ 18.60@y250 (2.20Hz/100px)
      F4: 26.70@y210→ 24.20@y310 (2.50Hz/100px)
"""
import json
import datetime
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

# sosrff.tsu.ru が大学の直接配信 (最新)、sos70.ru はミラー (キャッシュが20分ほど古いことがある)
URLS_LINE = [
    "https://sosrff.tsu.ru/new/srf.jpg",
    "https://sos70.ru/provider.php?file=srf.jpg",
]
URLS_SPECTRO = [
    "https://sosrff.tsu.ru/new/shm.jpg",
    "https://sos70.ru/provider.php?file=shm.jpg",
]

OUTPUT_DATA = "schumann_data.json"
OUTPUT_HISTORY = "schumann_history.json"
IMAGE_LINE = "latest_linegraph.jpg"
IMAGE_SPECTRO = "latest_spectrogram.jpg"
MAX_HISTORY = 2880  # 15分×2880 = 30日分

# プロット領域 (検証つきで使うレイアウト定数)
PLOT_X0, PLOT_X1 = 71, 935
PLOT_Y0, PLOT_Y1 = 30, 310
DAY_PX = 288  # 24時間

# 縦軸キャリブレーション: (基準y, 基準Hz, 100pxあたりHz)
CALIB = {
    "F1": (30, 8.15, 0.69),
    "F2": (90, 14.50, 1.60),
    "F3": (150, 20.80, 2.20),
    "F4": (210, 26.70, 2.50),
}
# 物理的にありえる帯域 (外れたら誤読としてリジェクト)
SANE_BAND = {
    "F1": (6.8, 9.2),
    "F2": (12.0, 16.0),
    "F3": (17.5, 22.5),
    "F4": (23.0, 28.5),
}
THEORY = {"F1": 7.83, "F2": 14.1, "F3": 20.3, "F4": 26.4}


def fetch_image(urls):
    headers = {
        "User-Agent": "Mozilla/5.0 (schumann-monitor; research)",
        "Accept": "image/jpeg,image/*,*/*",
    }
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) > 1000:
                    print(f"+ Fetched {url} ({len(data)} bytes)")
                    return data, url
        except Exception as e:
            print(f"! Failed {url}: {e}")
            continue
    return None, None


def color_masks(arr):
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    return {
        "F1": (r > 190) & (g > 190) & (b > 190),          # 白
        "F2": (r > 190) & (g > 190) & (b < 120),           # 黄
        "F3": (r > 170) & (g < 110) & (b < 110),           # 赤
        "F4": (g > 170) & (r < 120) & (b < 120),           # 緑
    }


def verify_layout(arr):
    """プロット枠 (上下の水平線・左右の縦線) がおよそ想定位置にあるか検証。
    レイアウトが変わったら誤読するより止まる方が安全。"""
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    greenish = (g - np.maximum(r, b)) > 30
    rows = greenish.sum(axis=1)
    cols = greenish.sum(axis=0)
    problems = []
    # 上枠 y=30 / 下枠 y=310 (±2px)
    for y, name in [(PLOT_Y0, "top"), (PLOT_Y1, "bottom")]:
        window = rows[max(0, y - 2): y + 3]
        if window.max() < 500:
            problems.append(f"{name} border not found near y={y}")
    # 左枠 x=71 / 右枠 x=935 (±2px)
    for x, name in [(PLOT_X0, "left"), (PLOT_X1, "right")]:
        window = cols[max(0, x - 2): x + 3]
        if window.max() < 180:
            problems.append(f"{name} border not found near x={x}")
    return problems


def extract_modes(arr):
    """右端 (最新) の各モード周波数をピクセルから読み取る"""
    masks = color_masks(arr)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    results = {}
    latest_x = None
    for key, mask in masks.items():
        m = mask.copy()
        # プロット領域内だけ見る
        m[:PLOT_Y0 + 1, :] = False
        m[PLOT_Y1:, :] = False
        m[:, :PLOT_X0 + 1] = False
        m[:, PLOT_X1:] = False
        if key == "F1":
            m[:105, 895:] = False  # 右上の SOS70 ロゴ (白) を除外
        colcount = m.sum(axis=0)
        # 1列に30px以上は縦線/ノイズ (日区切り線など) なので除外
        valid = np.where((colcount > 0) & (colcount < 30))[0]
        if len(valid) == 0:
            results[key] = {"hz": None, "confidence": 0, "reason": "no pixels"}
            continue
        xr = int(valid[-1])
        # 右端5列の中央値で安定化
        ys = []
        for x in valid[valid >= xr - 4]:
            yy = np.where(m[:, x])[0]
            if len(yy):
                ys.append(float(np.median(yy)))
        y = float(np.median(ys))
        y0, v0, span = CALIB[key]
        hz = v0 - (y - y0) * span / 100.0
        lo, hi = SANE_BAND[key]
        if not (lo <= hz <= hi):
            results[key] = {"hz": None, "confidence": 0,
                            "reason": f"out of band ({hz:.2f})"}
            continue
        # データの時刻 (右端x → 3日ウィンドウ内の時刻)
        # グラフの時刻軸はトムスク地方時 (UTC+7)、最終日 = トムスクの今日
        day = 0 if xr < PLOT_X0 + DAY_PX else (1 if xr < PLOT_X0 + 2 * DAY_PX else 2)
        hour = (xr - (PLOT_X0 + day * DAY_PX)) / DAY_PX * 24
        days_back = 2 - day
        tomsk_offset = datetime.timedelta(hours=7)
        now_tomsk = now_utc + tomsk_offset
        day_start_tomsk = now_tomsk.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=days_back)
        data_time = day_start_tomsk + datetime.timedelta(hours=hour) - tomsk_offset
        stale_min = max(0.0, (now_utc - data_time).total_seconds() / 60)
        # 信頼度: ピクセル読み取りは決定論的に高いが、古いデータは減点
        conf = 95
        if stale_min > 60:
            conf = max(30, 95 - int((stale_min - 60) / 30) * 10)
        results[key] = {
            "hz": round(hz, 2),
            "confidence": conf,
            "data_age_min": round(stale_min),
        }
        if latest_x is None or xr > latest_x:
            latest_x = xr
    return results


def build_notes(modes):
    parts = []
    f1 = modes.get("F1", {}).get("hz")
    if f1 is not None:
        dev = f1 - THEORY["F1"]
        if abs(dev) < 0.05:
            parts.append(f"F1は{f1:.2f}Hzで基準値7.83Hz付近と安定")
        elif dev > 0:
            parts.append(f"F1は{f1:.2f}Hzで基準よりやや高め (+{dev:.2f}Hz)")
        else:
            parts.append(f"F1は{f1:.2f}Hzで基準よりやや低め ({dev:.2f}Hz)")
    missing = [k for k in ("F1", "F2", "F3", "F4") if modes.get(k, {}).get("hz") is None]
    if missing:
        parts.append(f"{'・'.join(missing)}はデータ欠損中")
    stale = [k for k in ("F1", "F2", "F3", "F4")
             if (modes.get(k, {}).get("data_age_min") or 0) > 120]
    if stale:
        parts.append(f"{'・'.join(stale)}は2時間以上更新なし")
    parts.append("ピクセル解析による決定論的読み取り")
    return "。".join(parts) + "。"


def calculate_polarization(utc_now):
    # トムスクの時計時刻は UTC+7 (v5 は +5.6 の太陽時を使っていて表示が約1.4h ズレていた)
    tomsk_local_hour = (utc_now.hour + utc_now.minute / 60 + 7) % 24
    is_day_tomsk = 6 <= tomsk_local_hour <= 18
    japan_hour = (utc_now.hour + utc_now.minute / 60 + 9) % 24
    is_day_japan = 6 <= japan_hour <= 18
    polarization = "right" if is_day_japan else "left"
    polarization_jp = "右回転（昼）" if is_day_japan else "左回転（夜）"
    return {
        "state": polarization,
        "state_jp": polarization_jp,
        "japan_hour": round(japan_hour, 2),
        "tomsk_hour": round(tomsk_local_hour, 2),
        "is_day_japan": is_day_japan,
        "is_day_tomsk": is_day_tomsk,
    }


def load_history():
    if Path(OUTPUT_HISTORY).exists():
        try:
            with open(OUTPUT_HISTORY, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = utc_now.isoformat()
    print(f"=== Schumann Fetch v6 (pixel) @ {timestamp} ===")

    line_bytes, line_url = fetch_image(URLS_LINE)
    if line_bytes is None:
        print("! Line graph fetch failed — keeping previous data")
        return

    with open(IMAGE_LINE, "wb") as f:
        f.write(line_bytes)

    spectro_bytes, spectro_url = fetch_image(URLS_SPECTRO)
    if spectro_bytes:
        with open(IMAGE_SPECTRO, "wb") as f:
            f.write(spectro_bytes)

    arr = np.array(Image.open(IMAGE_LINE).convert("RGB"))

    problems = verify_layout(arr)
    if problems:
        print(f"! Layout check failed: {problems} — keeping previous data")
        save_json(OUTPUT_DATA + ".error", {
            "timestamp": timestamp,
            "status": "error",
            "error": f"layout changed: {problems}",
        })
        return

    modes = extract_modes(arr)
    for k, v in modes.items():
        print(f"  {k}: {v}")

    # 有効モードが1つも無ければ前回データを保持して終了
    if all(m.get("hz") is None for m in modes.values()):
        print("! No modes extracted — keeping previous data")
        return

    polarization = calculate_polarization(utc_now)

    # F5 は元グラフに存在しないので常に null (v5 では幻覚読みしていた)
    modes_out = {k: {"hz": v.get("hz"), "confidence": v.get("confidence", 0)}
                 for k, v in modes.items()}
    modes_out["F5"] = {"hz": None, "confidence": 0}

    valid = {k: v for k, v in modes.items() if v.get("hz") is not None}
    strongest = min(valid, key=lambda k: abs(valid[k]["hz"] - THEORY[k])) if valid else ""

    data = {
        "timestamp": timestamp,
        "status": "ok",
        "source_line": line_url,
        "source_spectro": spectro_url,
        "model": "pixel-extraction-v6",
        "modes": modes_out,
        "amplitude_level": "unknown",
        "strongest_mode": strongest,
        "notes": build_notes(modes),
        "polarization": polarization,
        "data_age_min": {k: v.get("data_age_min") for k, v in modes.items()},
    }
    save_json(OUTPUT_DATA, data)
    print(f"+ Saved {OUTPUT_DATA}")

    history = load_history()
    history.append({
        "t": timestamp,
        "F1": modes.get("F1", {}).get("hz"),
        "F2": modes.get("F2", {}).get("hz"),
        "F3": modes.get("F3", {}).get("hz"),
        "F4": modes.get("F4", {}).get("hz"),
        "F5": None,
        "c1": modes.get("F1", {}).get("confidence"),
    })
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    save_json(OUTPUT_HISTORY, history)
    print(f"+ History updated ({len(history)} entries)")


if __name__ == "__main__":
    main()
