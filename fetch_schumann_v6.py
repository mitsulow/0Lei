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
import io
import json
import datetime
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

# ★sos70.ru を主とする (2026-07-02: sosrff.tsu.ru 直配信はサーバー時計が
#   2025年8月に飛んで過去データを再生する障害中。ミラーの sos70 は正常)。
#   sos70 はキャッシュが20分ほど古いことがあるが、正しさ優先。
URLS_LINE = [
    "https://sos70.ru/provider.php?file=srf.jpg",
    "https://sosrff.tsu.ru/new/srf.jpg",
]
URLS_SPECTRO = [
    "https://sos70.ru/provider.php?file=shm.jpg",
    "https://sosrff.tsu.ru/new/shm.jpg",
]
URLS_AMP = [
    "https://sos70.ru/provider.php?file=sra.jpg",
    "https://sosrff.tsu.ru/new/sra.jpg",
]
URLS_Q = [
    "https://sos70.ru/provider.php?file=srq.jpg",
    "https://sosrff.tsu.ru/new/srq.jpg",
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

# 縦軸キャリブレーション (静的フォールバック用): (基準y, 基準Hz, 100pxあたりHz)
# ★注意: 軸レンジは観測データに応じて自動スケーリングされる (2026-07-02 に実測確認)。
#   通常は下の OCR (ocr_axis_calibration) が毎回動的に導出し、これは OCR 失敗時の保険。
CALIB = {
    "F1": (30, 8.15, 0.69),
    "F2": (90, 14.50, 1.60),
    "F3": (150, 20.80, 2.20),
    "F4": (210, 26.70, 2.50),
}

# 軸ラベル OCR: 目盛り数字 (固定ビットマップフォント) をテンプレート照合で読む
# digit_templates.json = 実画像から抽出した 0-9 の字形 (9x6 二値ビットマップ、複数バリアント)
TEMPLATE_FILE = Path(__file__).with_name("digit_templates.json")
LABEL_X = {"F1": (25, 69), "F3": (25, 69), "F2": (941, 992), "F4": (941, 992)}


def load_templates():
    try:
        data = json.loads(TEMPLATE_FILE.read_text())
        return {ch: [np.array([[int(c) for c in row] for row in t], np.uint8)
                     for t in ts] for ch, ts in data.items()}
    except Exception as e:
        print(f"! digit templates unavailable: {e}")
        return None


def label_masks(arr):
    """軸ラベル読み取り用の緩い色マスク (JPEG 劣化に耐性)"""
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    return {
        "F1": (np.minimum(np.minimum(r, g), b) > 110),
        "F2": (r > 140) & (g > 140) & ((g - b) > 50),
        "F3": (r > 110) & ((r - g) > 60) & ((r - b) > 60),
        "F4": (g > 110) & ((g - r) > 60) & ((g - b) > 60),
    }


def _label_rows(mask, x0, x1):
    sub = mask[:, x0:x1]
    rows = np.where(sub.sum(axis=1) >= 2)[0]
    out = []
    if len(rows):
        s = rows[0]; p = rows[0]
        for y in rows[1:]:
            if y - p > 2:
                out.append((s, p)); s = y
            p = y
        out.append((s, p))
    return [(s, e) for s, e in out if 5 <= e - s <= 11 and 24 <= s <= 316]


def _cell_canon(mask, y0, y1, cx):
    cell = mask[y0:y1 + 1, cx:cx + 5]
    ys, xs = np.where(cell)
    if len(ys) == 0:
        return None
    gl = cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    c = np.zeros((9, 6), np.uint8)
    c[:min(9, gl.shape[0]), :min(6, gl.shape[1])] = gl[:9, :6]
    return c


def _read_label(mask, y0, y1, x0, x1, templates):
    """1行のラベルを読む。数字は右端揃え 6px ピッチなので
    右端から固定オフセットでセルを切る (小数点の検出は不要)。"""
    sub = mask[y0:y1 + 1, x0:x1]
    cols = np.where(sub.sum(axis=0) > 0)[0]
    if len(cols) == 0:
        return None
    xe = x0 + int(cols.max())
    digs = []
    for cx in [xe - 25, xe - 19, xe - 10, xe - 4]:
        c = _cell_canon(mask, y0, y1, cx)
        if c is None:
            digs.append(None)
            continue
        best, bd = None, 99
        for ch, ts in templates.items():
            for t in ts:
                d = int((c != t).sum())
                if d < bd:
                    bd, best = d, ch
        digs.append(best if bd <= 6 else "?")
    ds = [d for d in digs if d]
    if "?" in ds:
        return None
    if len(ds) == 4:
        return float(ds[0] + ds[1] + "." + ds[2] + ds[3])
    if len(ds) == 3:
        return float(ds[0] + "." + ds[1] + ds[2])
    return None


def ocr_axis_calibration(arr, templates):
    """目盛りラベルを OCR し、軸ごとに線形フィット (外れ値除去つき) で
    キャリブレーションを導出する。返り値: {mode: (y0, v0, span100) or None}"""
    if templates is None:
        return {}
    lm = label_masks(arr)
    result = {}
    for key, (x0, x1) in LABEL_X.items():
        pts = []
        for ys, ye in _label_rows(lm[key], x0, x1):
            val = _read_label(lm[key], ys, ye, x0, x1, templates)
            if val is None:
                continue
            center = (ys + ye) / 2 - 3          # ラベル中心はグリッド線の約3px下
            grid_y = round((center - PLOT_Y0) / 20) * 20 + PLOT_Y0
            if abs(center - grid_y) > 4:
                continue
            pts.append((float(grid_y), val))
        # 線形フィット + 外れ値除去 (ロゴ被り等の誤読はステップが合わず residual が大きい)
        calib = None
        pts_work = list(pts)
        while len(pts_work) >= 4:
            ys_a = np.array([p[0] for p in pts_work])
            vs_a = np.array([p[1] for p in pts_work])
            A = np.vstack([ys_a, np.ones(len(ys_a))]).T
            (slope, intercept), res = np.linalg.lstsq(A, vs_a, rcond=None)[0], None
            resid = np.abs(vs_a - (slope * ys_a + intercept))
            if resid.max() <= 0.03:
                if slope < 0:  # 上が大きい値のはず
                    calib = (PLOT_Y0, slope * PLOT_Y0 + intercept, -slope * 100)
                break
            pts_work.pop(int(resid.argmax()))
        result[key] = calib
        pretty = f"y{PLOT_Y0}={calib[1]:.3f}Hz, {calib[2]:.3f}Hz/100px" if calib else "FAILED"
        print(f"  OCR calib {key}: {len(pts)} labels -> {pretty}")
    return result
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
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return {
        # 白 = 明るい かつ 彩度が低い。彩度条件がないと JPEG で白化した
        # 黄線の芯が混入し、F1 が F2 側に引っ張られる (2026-07-02 実測)
        "F1": (mn > 190) & ((mx - mn) < 50),
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


def data_age_min(day, hour, now_utc):
    """右端データの鮮度 (分) を返す。
    グラフの時刻軸はトムスク標準時 (UTC+7)。ただしサーバー時計の故障で
    ずれることがある (2026-07-02 に sosrff 側で +1h と日付10ヶ月ズレを実測)。
    +7 で未来になってしまう場合は +8, +9 を順に試して妥当な方を採用する。"""
    for off in (7, 8, 9):
        tz = datetime.timedelta(hours=off)
        local_now = now_utc + tz
        day_start = local_now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=2 - day)
        data_time = day_start + datetime.timedelta(hours=hour) - tz
        age = (now_utc - data_time).total_seconds() / 60
        if age >= -10:  # 抽出の滲みで数分の負は許容
            return max(0.0, age), off
    return 0.0, 8


def extract_modes(arr, ocr_calib=None, sane_check=True):
    """右端 (最新) の各モードの値をピクセルから読み取る
    sane_check=False で周波数帯域チェックを外す (振幅・Q値グラフ用)"""
    masks = color_masks(arr)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    results = {}
    latest_x = None
    for key, mask in masks.items():
        cal = (ocr_calib or {}).get(key)
        used_ocr = cal is not None
        if cal is None:
            cal = CALIB[key]
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
        y0, v0, span = cal
        hz = v0 - (y - y0) * span / 100.0
        if sane_check:
            lo, hi = SANE_BAND[key]
            if not (lo <= hz <= hi):
                results[key] = {"hz": None, "confidence": 0,
                                "reason": f"out of band ({hz:.2f})"}
                continue
        elif hz < 0 or hz > 500:
            results[key] = {"hz": None, "confidence": 0,
                            "reason": f"implausible ({hz:.2f})"}
            continue
        # データの時刻 (右端x → 3日ウィンドウ内の時刻)
        day = 0 if xr < PLOT_X0 + DAY_PX else (1 if xr < PLOT_X0 + 2 * DAY_PX else 2)
        hour = (xr - (PLOT_X0 + day * DAY_PX)) / DAY_PX * 24
        stale_min, axis_off = data_age_min(day, hour, now_utc)
        # 信頼度: OCR で軸を検証できた場合は高い。静的フォールバック時は
        # 軸が変わっている可能性があるので上限 60。古いデータはさらに減点。
        conf = 95 if used_ocr else 60
        if stale_min > 60:
            conf = max(30, conf - int((stale_min - 60) / 30) * 10)
        results[key] = {
            "hz": round(hz, 2),
            "confidence": conf,
            "data_age_min": round(stale_min),
            "calibration": "ocr" if used_ocr else "static-fallback",
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
    fallback = [k for k in ("F1", "F2", "F3", "F4")
                if modes.get(k, {}).get("calibration") == "static-fallback"]
    if fallback:
        parts.append(f"{'・'.join(fallback)}は軸OCR失敗のため参考値")
    parts.append("軸目盛りOCR検証つきピクセル解析")
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

    templates = load_templates()
    ocr_calib = ocr_axis_calibration(arr, templates)
    modes = extract_modes(arr, ocr_calib)
    for k, v in modes.items():
        print(f"  {k}: {v}")

    # 有効モードが1つも無ければ前回データを保持して終了
    if all(m.get("hz") is None for m in modes.values()):
        print("! No modes extracted — keeping previous data")
        return

    # 振幅 (sra) と Q値 (srq) も同じエンジンで読む (ラベル形式・色・レイアウトが同一)
    def read_aux(urls, label):
        try:
            raw, _ = fetch_image(urls)
            if raw is None:
                return {}
            aux = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            if verify_layout(aux):
                print(f"! {label}: layout check failed")
                return {}
            aux_calib = ocr_axis_calibration(aux, templates)
            vals = extract_modes(aux, aux_calib, sane_check=False)
            print(f"  {label}: " + ", ".join(
                f"{k}={v.get('hz')}" for k, v in vals.items()))
            return {k: v.get("hz") for k, v in vals.items()}
        except Exception as e:
            print(f"! {label} failed: {e}")
            return {}

    amp_vals = read_aux(URLS_AMP, "amplitude(pT)")
    q_vals = read_aux(URLS_Q, "quality(Q)")

    polarization = calculate_polarization(utc_now)

    # F5 は元グラフに存在しないので常に null (v5 では幻覚読みしていた)
    modes_out = {k: {"hz": v.get("hz"), "confidence": v.get("confidence", 0),
                     "calibration": v.get("calibration"),
                     "amp": amp_vals.get(k), "q": q_vals.get(k)}
                 for k, v in modes.items()}
    modes_out["F5"] = {"hz": None, "confidence": 0}

    valid = {k: v for k, v in modes.items() if v.get("hz") is not None}
    strongest = min(valid, key=lambda k: abs(valid[k]["hz"] - THEORY[k])) if valid else ""

    data = {
        "timestamp": timestamp,
        "status": "ok",
        "source_line": line_url,
        "source_spectro": spectro_url,
        "model": "pixel-extraction-v6.1-ocr",
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
