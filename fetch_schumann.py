#!/usr/bin/env python3
"""
fetch_schumann.py v3 — v1精密色判定 + v2新機能統合
====================================================
- メイン: v1のグリッドキャリブレーション + 色判定（実績ある高精度手法）
- フォールバック: v2の輝度ピーク検出（色判定が失敗した場合）
- Cumiana(イタリア)画像取得で冗長化
- 信頼度スコア・v2 JSONフォーマット対応
"""
import json, os, sys, datetime, urllib.request
from io import BytesIO
from urllib.error import URLError, HTTPError

try:
    from PIL import Image
    import numpy as np
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'Pillow', 'numpy', '-q'])
    from PIL import Image
    import numpy as np

# ============================================================
# 設定
# ============================================================
TOMSK_URL = "https://sos70.ru/provider.php?file=srf.jpg"
CUMIANA_URLS = [
    "http://www.vlf.it/cumiana/723601.601_VLF_SEQ_Cumiana.jpg",
    "http://www.vlf.it/cumiana/723.601_Cumiana_RT_EF_latest.jpg",
    "http://www.vlf.it/cumiana/723601.601_VLF_multistripD_Cumiana.jpg",
]
OUTPUT = "schumann.json"
HISTORY = "schumann_history.json"
MAX_HISTORY = 8640  # 30 days × 288/day
TIMEOUT = 20

# ============================================================
# 画像取得
# ============================================================
def fetch_image(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 SchumannMonitor/3.0",
        "Cache-Control": "no-cache"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        print(f"  Downloaded {len(data)} bytes from {url[:50]}...")
        return Image.open(BytesIO(data)).convert("RGB")
    except (URLError, HTTPError, Exception) as e:
        print(f"  [WARN] {url[:50]}...: {e}")
        return None

# ============================================================
# メイン解析: v1方式（色判定 + グリッドキャリブレーション）
# ============================================================
def analyze_v1(img):
    """v1の実績ある解析ロジック（v7 analyze関数ベース）"""
    w, h = img.size
    px = img.load()

    # --- プロット境界検出 ---
    pL, pR = int(w*0.08), int(w*0.95)
    for x in range(int(w*0.03), int(w*0.15)):
        dk = sum(1 for y in range(int(h*0.1), int(h*0.4), 3) if all(c < 40 for c in px[x,y]))
        if dk > 15: pL = x; break
    for x in range(w - int(w*0.02), int(w*0.8), -1):
        dk = sum(1 for y in range(int(h*0.1), int(h*0.4), 3) if all(c < 40 for c in px[x,y]))
        if dk > 15: pR = x; break

    # --- F1グリッドキャリブレーション ---
    f1T, f1B = int(h*0.06), int(h*0.44)
    gRows = []
    for y in range(int(h*0.03), int(h*0.50)):
        lp = sum(1 for x in range(pL+10, pL+int((pR-pL)*0.3), 4)
                 if all(30 < c < 140 for c in px[x,y]))
        if lp > 20: gRows.append(y)

    if gRows:
        gLines, cl = [], [gRows[0]]
        for i in range(1, len(gRows)):
            if gRows[i] - gRows[i-1] <= 4: cl.append(gRows[i])
            else: gLines.append(round(sum(cl)/len(cl))); cl = [gRows[i]]
        gLines.append(round(sum(cl)/len(cl)))
        if len(gLines) >= 5:
            sp = gLines[1] - gLines[0]
            f1L = [gLines[0]]
            for i in range(1, len(gLines)):
                if gLines[i] - gLines[i-1] < sp*2.5: f1L.append(gLines[i])
                else: break
            if len(f1L) >= 4: f1T, f1B = f1L[0], f1L[-1]

    print(f"  Plot: x[{pL}..{pR}] F1: y[{f1T}..{f1B}]")

    # --- 色判定関数 ---
    def is_white(r,g,b): return r>190 and g>190 and b>190 and max(abs(r-g),abs(r-b),abs(g-b))<55
    def is_yellow(r,g,b): return r>150 and g>130 and b<110 and r>b*1.6 and g>b*1.3
    def is_red(r,g,b): return r>100 and g<90 and b<90 and r>g*1.4 and r>b*1.4
    def is_green(r,g,b): return g>80 and r<100 and b<100 and g>r*1.15 and g>b*1.15

    # --- モード定義 ---
    modes = [
        {"name":"F1", "yTop":f1T, "yBot":f1B, "hzTop":8.30, "hzBot":7.20, "match":is_white},
        {"name":"F2", "yTop":f1T, "yBot":f1B, "hzTop":14.40, "hzBot":13.00, "match":is_yellow},
        {"name":"F3", "yTop":int(h*0.42), "yBot":int(h*0.72), "hzTop":21.10, "hzBot":18.30, "match":is_red},
        {"name":"F4", "yTop":int(h*0.60), "yBot":int(h*0.95), "hzTop":26.90, "hzBot":24.00, "match":is_green},
    ]

    pw = pR - pL

    # --- 段階スキャン（最新→過去にフォールバック）---
    scan_zones = [
        ("latest(85-92%)", 0.85, 0.92),
        ("recent(75-85%)", 0.75, 0.85),
        ("6h(65-75%)", 0.65, 0.75),
        ("12h(50-65%)", 0.50, 0.65),
    ]

    best = None
    for label, s, e in scan_zones:
        xs, xe = int(pL + pw*s), int(pL + pw*e)
        hits = 0
        for x in range(xs, xe+1, 3):
            for y in range(f1T, f1B, 2):
                if is_white(*px[x,y]): hits += 1
            if hits >= 3: break
        print(f"  Zone {label}: {hits} hits")
        if hits >= 3: best = (label, s, e); break

    if not best:
        print("  All zones empty, fallback to 65-75%")
        best = ("fallback(65-75%)", 0.65, 0.75)

    label, s, e = best
    xs, xe = int(pL + pw*s), int(pL + pw*e)
    print(f"  >> Using zone {label} x[{xs}..{xe}]")

    # --- 各モード検出 ---
    results = {}
    for mode in modes:
        mH = mode["yBot"] - mode["yTop"]
        if mH <= 0: results[mode["name"]] = None; continue
        def y_to_hz(y, m=mode): return m["hzTop"] - ((y - m["yTop"]) / (m["yBot"] - m["yTop"])) * (m["hzTop"] - m["hzBot"])

        vals = []
        for x in range(xs, xe+1):
            col_y = [y for y in range(mode["yTop"], mode["yBot"]) if mode["match"](*px[x,y])]
            if col_y:
                col_y.sort()
                hz = y_to_hz(col_y[len(col_y)//2])
                if mode["hzBot"]-1 <= hz <= mode["hzTop"]+1:
                    vals.append(hz)

        if len(vals) >= 2:
            vals.sort()
            med = vals[len(vals)//2]
            confidence = min(1.0, len(vals) / 15)  # 15点以上で信頼度100%
            results[mode["name"]] = {
                "hz": round(med, 2),
                "confidence": round(confidence, 2),
                "samples": len(vals),
                "method": "color"
            }
            print(f"  [OK] {mode['name']}: {med:.2f} Hz ({len(vals)} pts, conf={confidence:.0%})")
        else:
            results[mode["name"]] = None
            print(f"  [MISS] {mode['name']}: insufficient ({len(vals)} pts)")

    # --- 24h平均 (F1) ---
    d3S = int(pL + pw*0.10)
    m1 = modes[0]
    m1H = m1["yBot"] - m1["yTop"]
    day_vals = []
    for x in range(d3S, xe+1, 4):
        col_y = [y for y in range(m1["yTop"], m1["yBot"]) if is_white(*px[x,y])]
        if col_y:
            col_y.sort()
            hz = m1["hzTop"] - ((col_y[len(col_y)//2] - m1["yTop"]) / m1H) * (m1["hzTop"] - m1["hzBot"])
            if 6.5 <= hz <= 9.5: day_vals.append(hz)

    avg24 = None
    if len(day_vals) >= 10:
        mn = sum(day_vals) / len(day_vals)
        sd = (sum((v-mn)**2 for v in day_vals) / len(day_vals)) ** 0.5
        flt = [v for v in day_vals if abs(v-mn) < sd*2]
        avg24 = round(sum(flt) / len(flt), 2)
        print(f"  [OK] 24h avg: {avg24} Hz ({len(flt)} pts)")

    return results, avg24, label

# ============================================================
# フォールバック: v2方式（輝度ピーク検出）
# ============================================================
def analyze_v2_fallback(img, missing_modes):
    """v2の輝度ピーク検出。v1で検出できなかったモードのみ補完"""
    if not missing_modes:
        return {}

    arr = np.array(img)
    h, w = arr.shape[:2]

    MODE_RANGES = {
        'F1': (6.0, 10.0),
        'F2': (12.0, 16.0),
        'F3': (18.0, 23.0),
        'F4': (24.0, 29.0),
    }

    # 簡易プロットエリア検出
    right_strip = arr[:, -30:-5, :]
    brightness = np.mean(right_strip, axis=(1, 2))
    threshold = np.mean(brightness) * 0.7
    dark_rows = np.where(brightness < threshold)[0]
    if len(dark_rows) >= 10:
        plot_top, plot_bottom = int(dark_rows[0]), int(dark_rows[-1])
    else:
        plot_top, plot_bottom = 25, h - 15

    HZ_MIN, HZ_MAX = 0.0, 40.0

    def hz_to_y(hz):
        ratio = (HZ_MAX - hz) / (HZ_MAX - HZ_MIN)
        return int(plot_top + ratio * (plot_bottom - plot_top))

    def y_to_hz(y):
        if plot_bottom == plot_top: return HZ_MIN
        ratio = (y - plot_top) / (plot_bottom - plot_top)
        return HZ_MAX - ratio * (HZ_MAX - HZ_MIN)

    results = {}
    for mode_name in missing_modes:
        hz_range = MODE_RANGES.get(mode_name)
        if not hz_range:
            continue

        hz_low, hz_high = hz_range
        y_high = max(0, min(hz_to_y(hz_high), h - 1))
        y_low = max(0, min(hz_to_y(hz_low), h - 1))
        if y_low <= y_high:
            continue

        # 右端付近を複数列スキャン
        scan_cols = list(range(w - 20, w - 3, 2))
        mode_results = []

        for x in scan_cols:
            x_start, x_end = max(0, x-2), min(w, x+3)
            strip = arr[y_high:y_low, x_start:x_end, :]
            lum = np.mean(strip, axis=(1, 2))
            sorted_lum = np.sort(lum)
            baseline = np.median(sorted_lum[:max(1, len(sorted_lum)//4)])
            thresh = baseline + (np.max(lum) - baseline) * 0.3

            above = lum > thresh
            if not np.any(above):
                continue

            indices = np.arange(len(lum))
            weights = np.where(above, lum - baseline, 0)
            ws = np.sum(weights)
            if ws == 0:
                continue

            wy = np.sum(indices * weights) / ws
            actual_y = y_high + wy
            hz = y_to_hz(actual_y)
            conf = min(1.0, (np.max(lum) - baseline) / max(1, baseline))

            if conf > 0.1:
                mode_results.append({"hz": hz, "conf": conf})

        if mode_results:
            total_conf = sum(r['conf'] for r in mode_results)
            weighted_hz = sum(r['hz'] * r['conf'] for r in mode_results) / total_conf
            avg_conf = total_conf / len(mode_results)
            results[mode_name] = {
                "hz": round(weighted_hz, 2),
                "confidence": round(min(avg_conf, 0.6), 2),  # フォールバックなのでmax 60%
                "samples": len(mode_results),
                "method": "luminosity_fallback"
            }
            print(f"  [FALLBACK] {mode_name}: {weighted_hz:.2f} Hz (conf={avg_conf:.0%})")

    return results

# ============================================================
# Cumiana解析
# ============================================================
def fetch_cumiana():
    for url in CUMIANA_URLS:
        img = fetch_image(url)
        if img:
            try:
                arr = np.array(img)
                h, w = arr.shape[:2]
                right_q = arr[:, int(w*0.75):, :]
                brightness = np.mean(right_q, axis=(1, 2))
                max_b = np.max(brightness)
                mean_b = np.mean(brightness)
                activity = min(100, int((max_b / max(1, mean_b) - 1) * 50))
                return {"source": "Cumiana", "status": "ok", "activity_level": activity, "url": url}
            except Exception as e:
                print(f"  [WARN] Cumiana analysis error: {e}")
    return {"source": "Cumiana", "status": "unavailable"}

# ============================================================
# メイン
# ============================================================
def main():
    print("=" * 60)
    print("Schumann Fetcher v3 — v1精密色判定 + v2統合")
    print("=" * 60)

    # --- トムスク画像取得 ---
    print("\n[1/2] Fetching Tomsk srf.jpg...")
    img = fetch_image(TOMSK_URL)
    if not img:
        print("[FATAL] Tomsk unavailable!")
        # 空のJSON出力
        now = datetime.datetime.utcnow()
        with open(OUTPUT, "w") as f:
            json.dump({"timestamp_utc": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        "version": 3, "modes": {}, "error": "Tomsk unavailable"}, f, indent=2)
        return

    w, h = img.size
    print(f"  Image: {w}x{h}")

    # --- v1方式で解析（メイン）---
    print("\n--- Primary: v1 color detection ---")
    v1_results, avg24, zone = analyze_v1(img)

    # --- 欠損モードをv2フォールバックで補完 ---
    missing = [m for m in ['F1','F2','F3','F4'] if v1_results.get(m) is None]
    v2_results = {}
    if missing:
        print(f"\n--- Fallback: v2 luminosity for {missing} ---")
        v2_results = analyze_v2_fallback(img, missing)

    # --- 結果統合 ---
    final_details = {}
    final_modes = {}
    for m in ['F1','F2','F3','F4']:
        if v1_results.get(m):
            final_details[m] = v1_results[m]
            final_modes[m] = v1_results[m]["hz"]
        elif v2_results.get(m):
            final_details[m] = v2_results[m]
            final_modes[m] = v2_results[m]["hz"]
        else:
            final_details[m] = None
            final_modes[m] = None

    # --- Cumiana ---
    print("\n[2/2] Fetching Cumiana...")
    cumiana = fetch_cumiana()
    if cumiana["status"] == "ok":
        print(f"  [OK] Cumiana activity: {cumiana['activity_level']}")
    else:
        print("  [WARN] Cumiana unavailable")

    # --- 結果表示 ---
    detected = sum(1 for v in final_modes.values() if v is not None)
    print(f"\n{'='*40}")
    print(f"RESULT: {detected}/4 modes detected")
    for m, hz in final_modes.items():
        d = final_details.get(m)
        if hz and d:
            print(f"  {m}: {hz} Hz [{d.get('method','?')}, conf={d.get('confidence',0):.0%}]")
        else:
            print(f"  {m}: ---")
    print(f"{'='*40}")

    # --- JSON出力（v2フォーマット互換）---
    now = datetime.datetime.utcnow()
    jst = now + datetime.timedelta(hours=9)

    output = {
        "timestamp_utc": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "timestamp_jst": jst.strftime('%Y-%m-%d %H:%M'),
        "version": 3,
        "method": "color_primary",
        "zone": zone,
        "modes": final_modes,
        "avg24": avg24,
        "details": {
            "tomsk": final_details,
            "cumiana": cumiana,
        },
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n[SAVE] {OUTPUT}")

    # --- 履歴追記 ---
    history = []
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY) as f:
                history = json.load(f)
        except: pass

    entry = {
        "timestamp": output["timestamp_utc"],
        "F1": final_modes.get("F1"),
        "F2": final_modes.get("F2"),
        "F3": final_modes.get("F3"),
        "F4": final_modes.get("F4"),
    }

    # v1形式の履歴との互換（小文字キーも入れる）
    entry["t"] = output["timestamp_utc"]
    entry["f1"] = final_modes.get("F1")
    entry["f2"] = final_modes.get("F2")
    entry["f3"] = final_modes.get("F3")
    entry["f4"] = final_modes.get("F4")

    history.append(entry)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(HISTORY, "w") as f:
        json.dump(history, f)
    print(f"[SAVE] {HISTORY} ({len(history)} records)")
    print("\n[DONE]")

if __name__ == "__main__":
    main()
