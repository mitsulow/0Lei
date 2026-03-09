#!/usr/bin/env python3
"""
fetch_schumann.py v2 — 全案統合シューマン共振取得システム
==========================================================
案1: 輝度ピーク検出（Y座標ベース） — 色ではなく「位置」でHz読み取り
案2: Cumiana(イタリア)画像も取得して冗長化
案3: Mikhnevo(モスクワ)学術データチェック（将来拡張）

GitHub Actions で5分ごとに実行
出力: schumann.json, schumann_history.json
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from io import BytesIO
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

try:
    from PIL import Image
    import numpy as np
except ImportError:
    # GitHub Actions: pip install Pillow numpy
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'Pillow', 'numpy', '-q'])
    from PIL import Image
    import numpy as np


# ============================================================
# 設定
# ============================================================

# トムスク（sos70.ru）の周波数グラフ画像
TOMSK_SRF_URL = "https://sos70.ru/new/srf.jpg"
# Cumiana（イタリア）のスペクトログラム
CUMIANA_URL = "http://www.vlf.it/cumiana/723.601_Cumiana_RT_EF_latest.jpg"

# 各ソースのタイムアウト（秒）
TIMEOUT = 20

# srf.jpgの画像仕様（トムスク周波数グラフ）
# 縦軸: 0〜40Hz（上が40Hz、下が0Hz）
# 横軸: 72時間（3日間、右端が「今」）
# 4本の線: F1(白), F2(黄), F3(赤), F4(緑)
# グリッド: 緑がかった灰色の水平線

# Hz↔ピクセルのマッピング（srf.jpg解析から推定）
# 画像サイズはおよそ 900x260 だが、可変のためピクセル比率で計算
SRF_HZ_MIN = 0.0     # 画像下端
SRF_HZ_MAX = 40.0    # 画像上端
SRF_PLOT_TOP = 25     # プロットエリア上端（ピクセル、おおよそ）
SRF_PLOT_BOTTOM = 245 # プロットエリア下端（ピクセル、おおよそ）

# 各モードの探索範囲（Hz）
MODE_RANGES = {
    'F1': (6.0, 10.0),    # 第1モード: 7.83Hz付近
    'F2': (12.0, 16.0),   # 第2モード: 14.3Hz付近
    'F3': (18.0, 23.0),   # 第3モード: 20.8Hz付近
    'F4': (24.0, 29.0),   # 第4モード: 27.3Hz付近
}

# 履歴の最大保持期間
HISTORY_MAX_DAYS = 30

# JSON出力ファイル
OUTPUT_JSON = "schumann.json"
HISTORY_JSON = "schumann_history.json"

# ============================================================
# ユーティリティ
# ============================================================

def fetch_image(url, timeout=TIMEOUT):
    """画像をURLから取得してPIL Imageで返す"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; SchumannMonitor/2.0)'
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return Image.open(BytesIO(data))
    except (URLError, HTTPError, Exception) as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None


def y_to_hz(y, plot_top, plot_bottom, hz_min=SRF_HZ_MIN, hz_max=SRF_HZ_MAX):
    """ピクセルY座標をHz値に変換（上が高Hz、下が低Hz）"""
    if plot_bottom == plot_top:
        return hz_min
    ratio = (y - plot_top) / (plot_bottom - plot_top)
    # 上(top)がhz_max、下(bottom)がhz_min
    return hz_max - ratio * (hz_max - hz_min)


def hz_to_y(hz, plot_top, plot_bottom, hz_min=SRF_HZ_MIN, hz_max=SRF_HZ_MAX):
    """Hz値をピクセルY座標に変換"""
    ratio = (hz_max - hz) / (hz_max - hz_min)
    return int(plot_top + ratio * (plot_bottom - plot_top))


# ============================================================
# 案1: 輝度ピーク検出（Y座標ベース）— トムスク srf.jpg
# ============================================================

def detect_plot_area(img_array):
    """
    プロットエリアの上端・下端を自動検出する。
    グリッド線（水平の薄い線）の分布から判定。
    """
    h, w = img_array.shape[:2]
    
    # 右端10列の平均輝度プロファイル（縦方向）
    right_strip = img_array[:, -30:-5, :]  # 右端の25ピクセル幅
    brightness = np.mean(right_strip, axis=(1, 2))  # 各行の平均輝度
    
    # プロットエリア = 暗い背景（輝度が低い領域）
    # 閾値: 平均輝度の50%以下をプロットエリアとみなす
    threshold = np.mean(brightness) * 0.7
    dark_rows = brightness < threshold
    
    # 最初と最後のdark行を見つける
    dark_indices = np.where(dark_rows)[0]
    if len(dark_indices) < 10:
        # フォールバック: デフォルト値
        return SRF_PLOT_TOP, min(SRF_PLOT_BOTTOM, h - 15)
    
    return int(dark_indices[0]), int(dark_indices[-1])


def analyze_column_luminosity(img_array, x, plot_top, plot_bottom, mode_range_hz):
    """
    指定X座標の縦1列を分析し、指定Hz範囲内の輝度ピーク位置を返す。
    
    方法: 
    1. 指定Hz範囲のY座標範囲を算出
    2. その範囲の各ピクセルの輝度を取得
    3. 周囲の背景と比べて明るいピークを検出
    4. ピークのY座標 → Hz変換
    """
    h, w = img_array.shape[:2]
    
    # Hz範囲をY座標範囲に変換
    hz_low, hz_high = mode_range_hz
    y_high = hz_to_y(hz_high, plot_top, plot_bottom)  # 高Hz = 上 = 小さいY
    y_low = hz_to_y(hz_low, plot_top, plot_bottom)     # 低Hz = 下 = 大きいY
    
    y_high = max(0, min(y_high, h - 1))
    y_low = max(0, min(y_low, h - 1))
    
    if y_low <= y_high:
        return None
    
    # 指定範囲の縦ストリップを取得（x±2ピクセルの平均で安定化）
    x_start = max(0, x - 2)
    x_end = min(w, x + 3)
    strip = img_array[y_high:y_low, x_start:x_end, :]
    
    # 各行の輝度（RGB平均）
    luminosity = np.mean(strip, axis=(1, 2))
    
    # 背景レベル（下位25%の中央値）をベースラインとする
    sorted_lum = np.sort(luminosity)
    baseline = np.median(sorted_lum[:max(1, len(sorted_lum) // 4)])
    
    # ピーク検出: ベースラインの1.5倍以上の輝度
    threshold = baseline + (np.max(luminosity) - baseline) * 0.3
    
    # ピークを見つける（単純な最大値ではなく、加重平均で精度アップ）
    above = luminosity > threshold
    if not np.any(above):
        # 閾値を下げて再試行
        threshold = baseline + (np.max(luminosity) - baseline) * 0.15
        above = luminosity > threshold
        if not np.any(above):
            return None
    
    # 加重平均Y座標（サブピクセル精度）
    indices = np.arange(len(luminosity))
    weights = np.where(above, luminosity - baseline, 0)
    weight_sum = np.sum(weights)
    if weight_sum == 0:
        return None
    
    weighted_y = np.sum(indices * weights) / weight_sum
    
    # 画像座標に戻す
    actual_y = y_high + weighted_y
    
    # Hz変換
    hz = y_to_hz(actual_y, plot_top, plot_bottom)
    
    # 信頼度スコア（ピーク鮮明度）
    peak_brightness = np.max(luminosity)
    confidence = min(1.0, (peak_brightness - baseline) / max(1, baseline))
    
    return {
        'hz': round(hz, 2),
        'confidence': round(confidence, 2),
        'peak_brightness': int(peak_brightness),
        'baseline': int(baseline)
    }


def analyze_srf_image(img):
    """
    srf.jpg全体を解析して、最新値（右端）のF1〜F4を返す。
    
    改善点（v2）:
    - 色判定ではなく「縦方向の輝度ピーク位置」で検出
    - 各モードの既知Hz範囲内だけをスキャン
    - JPG圧縮の色劣化に影響されにくい
    """
    arr = np.array(img)
    h, w = arr.shape[:2]
    
    print(f"[INFO] Image size: {w}x{h}")
    
    # プロットエリア自動検出
    plot_top, plot_bottom = detect_plot_area(arr)
    print(f"[INFO] Plot area: y={plot_top} to y={plot_bottom}")
    
    # 右端の解析（最新データ = 右端付近）
    # JPG境界のアーティファクトを避けるため、右端から5〜20ピクセルの範囲を複数列解析
    results = {}
    scan_columns = list(range(w - 20, w - 3, 2))  # 右端付近を複数列
    
    for mode_name, hz_range in MODE_RANGES.items():
        mode_results = []
        
        for x in scan_columns:
            result = analyze_column_luminosity(arr, x, plot_top, plot_bottom, hz_range)
            if result and result['confidence'] > 0.1:
                mode_results.append(result)
        
        if mode_results:
            # 信頼度で重み付け平均
            total_conf = sum(r['confidence'] for r in mode_results)
            weighted_hz = sum(r['hz'] * r['confidence'] for r in mode_results) / total_conf
            avg_conf = total_conf / len(mode_results)
            
            results[mode_name] = {
                'hz': round(weighted_hz, 2),
                'confidence': round(avg_conf, 2),
                'samples': len(mode_results)
            }
            print(f"[OK] {mode_name}: {weighted_hz:.2f} Hz (confidence: {avg_conf:.2f}, samples: {len(mode_results)})")
        else:
            results[mode_name] = None
            print(f"[MISS] {mode_name}: not detected")
    
    # === 旧方式（色判定）もフォールバックとして残す ===
    fallback = analyze_srf_color_fallback(arr, w, h, plot_top, plot_bottom)
    
    # 欠損モードをフォールバックで補完
    for mode_name in MODE_RANGES:
        if results.get(mode_name) is None and fallback.get(mode_name) is not None:
            results[mode_name] = fallback[mode_name]
            results[mode_name]['method'] = 'color_fallback'
            print(f"[FALLBACK] {mode_name}: {fallback[mode_name]['hz']:.2f} Hz (color method)")
    
    return results


def analyze_srf_color_fallback(arr, w, h, plot_top, plot_bottom):
    """
    旧方式: ピクセル色からF1〜F4を判定（v1互換フォールバック）
    JPG劣化で精度は限界があるが、輝度法が失敗した時のバックアップ
    """
    results = {}
    
    # 右端20ピクセルをスキャン
    for x in range(w - 15, w - 3):
        for y in range(plot_top, plot_bottom):
            r, g, b = int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])
            
            hz = y_to_hz(y, plot_top, plot_bottom)
            
            # F4(緑): 明確な緑
            if g > 120 and g > r * 1.3 and g > b * 1.3 and 24 < hz < 29:
                if 'F4' not in results or results['F4']['confidence'] < 0.5:
                    results['F4'] = {'hz': round(hz, 2), 'confidence': 0.5, 'samples': 1}
            
            # F3(赤): 明確な赤
            if r > 120 and r > g * 1.3 and r > b * 1.3 and 18 < hz < 23:
                if 'F3' not in results or results['F3']['confidence'] < 0.5:
                    results['F3'] = {'hz': round(hz, 2), 'confidence': 0.5, 'samples': 1}
            
            # F1(白): 高輝度
            if r > 200 and g > 200 and b > 200 and 6 < hz < 10:
                if 'F1' not in results or results['F1']['confidence'] < 0.4:
                    results['F1'] = {'hz': round(hz, 2), 'confidence': 0.4, 'samples': 1}
            
            # F2(黄): 黄色っぽい（改善版閾値）
            if r > 150 and g > 150 and b < 180 and (r + g) / 2 - b > 25 and 12 < hz < 16:
                if r > 220 and g > 220 and b > 190:
                    continue  # 白に近すぎる → スキップ
                if 'F2' not in results or results['F2']['confidence'] < 0.3:
                    results['F2'] = {'hz': round(hz, 2), 'confidence': 0.3, 'samples': 1}
    
    return results


# ============================================================
# 案2: Cumiana（イタリア）スペクトログラム解析
# ============================================================

def analyze_cumiana(img):
    """
    Cumianaのスペクトログラムからシューマン共振を検出する。
    
    Cumianaの画像は電界（E-field）スペクトログラムで、
    トムスクのように線グラフではなくヒートマップ形式。
    縦軸=周波数、横軸=時間、色=強度
    
    第1モード（7.83Hz付近）の輝度帯を検出して
    「活動レベル」（パワー推定）として返す。
    Hz値の精密な読み取りはスペクトログラムの解像度的に難しいため、
    主に「トムスクデータの補完・検証」用。
    """
    if img is None:
        return None
    
    try:
        arr = np.array(img)
        h, w = arr.shape[:2]
        
        # Cumianaの画像は複数チャンネル表示の場合がある
        # 右端25%列の輝度プロファイルで大まかなパワーレベルを取得
        right_quarter = arr[:, int(w * 0.75):, :]
        brightness = np.mean(right_quarter, axis=(1, 2))
        
        # 全体の輝度レベルから活動度を推定（0-100スケール）
        max_bright = np.max(brightness)
        mean_bright = np.mean(brightness)
        activity = min(100, int((max_bright / max(1, mean_bright) - 1) * 50))
        
        return {
            'source': 'Cumiana',
            'activity_level': activity,
            'status': 'ok',
            'image_size': f'{w}x{h}'
        }
    except Exception as e:
        print(f"[WARN] Cumiana analysis failed: {e}")
        return {
            'source': 'Cumiana',
            'status': 'error',
            'error': str(e)
        }


# ============================================================
# メイン処理
# ============================================================

def build_output(tomsk_results, cumiana_results):
    """JSON出力を構築"""
    now_utc = datetime.now(timezone.utc)
    now_jst = now_utc + timedelta(hours=9)
    
    # Hz値をフラットに取り出す
    modes = {}
    for mode_name in ['F1', 'F2', 'F3', 'F4']:
        r = tomsk_results.get(mode_name)
        if r:
            modes[mode_name] = r['hz']
        else:
            modes[mode_name] = None
    
    output = {
        'timestamp_utc': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'timestamp_jst': now_jst.strftime('%Y-%m-%d %H:%M'),
        'version': 2,
        'method': 'luminosity_peak',
        'modes': modes,
        'details': {
            'tomsk': tomsk_results,
            'cumiana': cumiana_results
        },
        'sources': {
            'primary': 'Tomsk/sos70.ru (luminosity peak detection)',
            'secondary': 'Cumiana/vlf.it (activity verification)',
        }
    }
    
    return output


def update_history(current_data):
    """schumann_history.jsonに追記"""
    history = []
    if os.path.exists(HISTORY_JSON):
        try:
            with open(HISTORY_JSON, 'r') as f:
                history = json.load(f)
        except:
            history = []
    
    # 新しいエントリ
    entry = {
        'timestamp': current_data['timestamp_utc'],
        'F1': current_data['modes'].get('F1'),
        'F2': current_data['modes'].get('F2'),
        'F3': current_data['modes'].get('F3'),
        'F4': current_data['modes'].get('F4'),
    }
    history.append(entry)
    
    # 30日以上前のデータを削除
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_MAX_DAYS)
    cutoff_str = cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')
    history = [h for h in history if h.get('timestamp', '') >= cutoff_str]
    
    with open(HISTORY_JSON, 'w') as f:
        json.dump(history, f)
    
    print(f"[INFO] History: {len(history)} entries")


def main():
    print("=" * 60)
    print("Schumann Resonance Fetcher v2 — 全案統合システム")
    print("=" * 60)
    
    # === ソース1: トムスク srf.jpg（メイン）===
    print("\n[1/2] Fetching Tomsk srf.jpg...")
    tomsk_img = fetch_image(TOMSK_SRF_URL)
    tomsk_results = {}
    
    if tomsk_img:
        print(f"[OK] Tomsk image: {tomsk_img.size}")
        tomsk_results = analyze_srf_image(tomsk_img)
    else:
        print("[FAIL] Tomsk image unavailable")
    
    # === ソース2: Cumiana（補完）===
    print("\n[2/2] Fetching Cumiana spectrogram...")
    cumiana_img = fetch_image(CUMIANA_URL)
    cumiana_results = analyze_cumiana(cumiana_img)
    
    if cumiana_results and cumiana_results.get('status') == 'ok':
        print(f"[OK] Cumiana activity level: {cumiana_results['activity_level']}")
    else:
        print("[WARN] Cumiana unavailable or error")
    
    # === 出力構築 ===
    output = build_output(tomsk_results, cumiana_results)
    
    # === ステータス判定 ===
    detected = sum(1 for v in output['modes'].values() if v is not None)
    print(f"\n[RESULT] Detected {detected}/4 modes")
    for mode, hz in output['modes'].items():
        if hz:
            print(f"  {mode}: {hz} Hz")
        else:
            print(f"  {mode}: --- (not detected)")
    
    # === JSON保存 ===
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n[SAVE] {OUTPUT_JSON}")
    
    update_history(output)
    print(f"[SAVE] {HISTORY_JSON}")
    
    # 1つもモード検出できなかった場合は非ゼロ終了（GitHub Actionsで警告）
    if detected == 0:
        print("\n[WARN] No modes detected!")
        # でもexit(0)にする（Actions失敗にはしない）
    
    print("\n[DONE]")


if __name__ == '__main__':
    main()
