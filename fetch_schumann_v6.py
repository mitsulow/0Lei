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
import hashlib
import io
import json
import os
import datetime
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

# ★sos70.ru に統一 (旧 sosrff.tsu.ru は2025年で凍結済み。サーバー時計が
#   過去に飛んで古いデータを再生するため、フォールバックからも除外した)。
#   sos70 はキャッシュが20分ほど古いことがあるが、正しさ優先。
URLS_LINE = [
    "https://sos70.ru/provider.php?file=srf.jpg",
]
URLS_SPECTRO = [
    "https://sos70.ru/provider.php?file=shm.jpg",
]
URLS_AMP = [
    "https://sos70.ru/provider.php?file=sra.jpg",
]
URLS_Q = [
    "https://sos70.ru/provider.php?file=srq.jpg",
]

OUTPUT_DATA = "schumann_data.json"
OUTPUT_HISTORY = "schumann_history.json"
IMAGE_LINE = "latest_linegraph.jpg"
IMAGE_SPECTRO = "latest_spectrogram.jpg"
MAX_HISTORY = 2880  # 15分×2880 = 30日分
# 無駄打ち対策: 前回取得した srf.jpg の SHA-256 (同一なら読み取りをスキップ)
SHA_FILE = "last_srf_sha256.txt"

# ===== 公式API v1 (docs/api-v1.md) =====
# ルール: フィールドは追加のみ可。変更・削除時は schema_version をメジャーアップし旧ファイル並行提供
SCHEMA_VERSION = "1.0"
# MMM 目標周波数。導出根拠: 恒星日 86,164 秒 ÷ (8回転 × 86,400 秒) 由来
TARGET_HZ = 8.0219032748
MAX_EVENTS = 100  # events 配列の保持上限
JST = datetime.timezone(datetime.timedelta(hours=9))


def jst_str(utc_now):
    """アプリ側で変換不要な、人間可読の JST 文字列"""
    return utc_now.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")


# ===== 項目6: スペクトログラム (shm.jpg) から「今日の共振コンディション」 =====
# 雷活動バースト (白飛び・高輝度の縦帯) を検出して3段階に分類する。
# 閾値は仮置き。調整はこの定数だけ変えればよい (一元管理)
SHM_LAYOUT = {"w": 1540, "h": 460, "x0": 61, "x1": 1497, "y0": 30, "y1": 435}
CONDITION_CFG = {
    "bright_col_luma": 150,  # 列平均輝度がこれ以上なら「白飛び列」
    "data_col_luma": 8,      # これ未満の列は無データ (右端のまだ来ていない時間帯)
    "active_frac": 0.05, "active_run_px": 15,  # 白飛び5% or 連続45分相当で active
    "storm_frac": 0.18, "storm_run_px": 50,    # 白飛び18% or 連続2.5時間相当で storm
}
# 参考: 2026-07-29 13〜16時 (トムスク時間) の大規模白飛びが storm の典型例
#       (実測: frac≈0.28, max_run≈95px。1時間 ≈ 20px)


def analyze_condition(spectro_bytes):
    """直近24時間 (データがある右端から1日分) の列ごとの平均輝度から
    白飛び列の割合と最大連続幅を算出し calm / active / storm を判定。
    取得失敗・レイアウト変化時は unknown で安全に劣化する"""
    if not spectro_bytes:
        return "unknown", None
    try:
        arr = np.array(Image.open(io.BytesIO(spectro_bytes)).convert("L"), dtype=float)
        h, w = arr.shape
        lay = SHM_LAYOUT
        if abs(w - lay["w"]) > 40 or abs(h - lay["h"]) > 40:
            print(f"! condition: unexpected shm.jpg size {w}x{h}")
            return "unknown", None
        arr[:110, 1430:] = 0.0  # 右上の SOS70 ロゴ (白) を除外
        colmean = arr[lay["y0"]:lay["y1"], lay["x0"]:lay["x1"]].mean(axis=0)
        day_px = (1503 - lay["x0"]) / 3.0  # 3日ウィンドウ → 24時間 ≈ 480px
        cfg = CONDITION_CFG
        datacols = np.where(colmean > cfg["data_col_luma"])[0]
        if len(datacols) == 0:
            return "unknown", None
        end = int(datacols[-1]) + 1
        win = colmean[max(0, end - int(day_px)):end]
        bright = win >= cfg["bright_col_luma"]
        frac = float(bright.mean())
        run = best = 0
        for b in bright:
            run = run + 1 if b else 0
            best = max(best, run)
        if frac >= cfg["storm_frac"] or best >= cfg["storm_run_px"]:
            cond = "storm"
        elif frac >= cfg["active_frac"] or best >= cfg["active_run_px"]:
            cond = "active"
        else:
            cond = "calm"
        metrics = {"bright_frac": round(frac, 4), "max_run_px": int(best),
                   "window_cols": int(len(win))}
        print(f"  condition: {cond} {metrics}")
        return cond, metrics
    except Exception as e:
        print(f"! condition analysis failed: {e}")
        return "unknown", None


# ===== 項目3: 履歴の永久蓄積 (history/YYYY-MM.json) =====
HISTORY_DIR = Path("history")


def update_permanent_history(timestamp, modes, condition=None):
    """毎回の読み取り値を月別ファイルに追記し、月替わりで前月を日次圧縮、
    月平均サマリー (ダッシュボードのトレンドグラフ用) を更新する"""
    HISTORY_DIR.mkdir(exist_ok=True)
    mk = timestamp[:7]  # "YYYY-MM"
    path = HISTORY_DIR / f"{mk}.json"
    records = load_json(path) or []
    records.append({
        "t": timestamp,
        "F1": modes.get("F1", {}).get("hz"),
        "F2": modes.get("F2", {}).get("hz"),
        "F3": modes.get("F3", {}).get("hz"),
        "F4": modes.get("F4", {}).get("hz"),
        "condition": condition,
    })
    save_json(path, records)
    print(f"+ Permanent history {path} ({len(records)} records)")
    compress_previous_month(mk)
    update_monthly_summary()


SERIES_DEV_MAX = {"F1": 0.25, "F2": 0.45, "F3": 0.6, "F4": 0.7}


def extract_series(arr, ocr_calib=None):
    """全幅読み取り: 折れ線グラフの左端〜右端をすべて読む (1px = 5分, 3日ぶん≈860点)。
    右端1点読みと違い、前後の点との整合チェックができるので読み取りミスも弾ける。"""
    masks = color_masks(arr)
    out = {}
    for key, mask in masks.items():
        cal = (ocr_calib or {}).get(key) or CALIB[key]
        m = mask.copy()
        m[:PLOT_Y0 + 1, :] = False
        m[PLOT_Y1:, :] = False
        m[:, :PLOT_X0 + 1] = False
        m[:, PLOT_X1:] = False
        if key == "F1":
            m[:105, 895:] = False  # 右上の SOS70 ロゴ (白) を除外
            # 中央の白い透かし "Copyright@ http://sosrff.tsu.ru"(行~164-190,列~310-700)を除外。
            # これがF1(白)マスクに混入し、中日のF1が median で低く歪んでいた(2026-08-05根治)
            m[162:192, 305:705] = False
        y0, v0, span = cal
        lo, hi = SANE_BAND[key]
        # 各モードを「妥当Hz範囲に対応する行帯」だけに限定する。
        # これで中央の白い透かし "Copyright@..." や他モードの線が混入せず、
        # 列内 median が本物の線だけで決まる (2026-08-05: F1が透かしで低く出るバグの根治)
        r_a = y0 + (v0 - hi) * 100.0 / span
        r_b = y0 + (v0 - lo) * 100.0 / span
        r_top = max(PLOT_Y0 + 1, int(min(r_a, r_b)) - 3)
        r_bot = min(PLOT_Y1 - 1, int(max(r_a, r_b)) + 3)
        m[:r_top, :] = False
        m[r_bot + 1:, :] = False
        colcount = m.sum(axis=0)
        valid = np.where((colcount > 0) & (colcount < 30))[0]
        pts = []
        for x in valid:
            yy = np.where(m[:, x])[0]
            if not len(yy):
                continue
            hz = v0 - (float(np.median(yy)) - y0) * span / 100.0
            if lo <= hz <= hi:
                pts.append((int(x), hz))
        # 前後との整合チェック: 近傍5点の中央値から大きく飛んだ点は
        # 線の重なり・ラベル・ノイズの読み取りミスとして捨てる
        dev = SERIES_DEV_MAX.get(key, 0.5)
        clean = []
        for i, (x, hz) in enumerate(pts):
            nb = sorted(q[1] for q in pts[max(0, i - 2): i + 3])
            med = nb[len(nb) // 2]
            if abs(hz - med) <= dev:
                clean.append((x, hz))
        out[key] = clean
    return out


def merge_series_history(series, now_utc):
    """全幅読み取りの系列を月別永久履歴へマージする。
    時刻は5分バケットに丸め、記録済みバケットはスキップ = 何度実行しても増殖しない。
    Actions が半日止まっても、次の1回で3日ぶんまで自動回収できる。"""
    xs = [x for pts in series.values() for (x, _) in pts]
    if not xs:
        return 0
    xr = max(xs)
    # 右端の時刻 (extract_modes と同じ軸ロジックで鮮度を求め、そこから逆算)
    day = 0 if xr < PLOT_X0 + DAY_PX else (1 if xr < PLOT_X0 + 2 * DAY_PX else 2)
    hour = (xr - (PLOT_X0 + day * DAY_PX)) / DAY_PX * 24
    stale_min, _off = data_age_min(day, hour, now_utc)
    t_right = now_utc - datetime.timedelta(minutes=stale_min)

    def bucket(t):
        return int(t.timestamp() // 300) * 300

    by_t = {}
    for key, pts in series.items():
        for x, hz in pts:
            t = t_right - datetime.timedelta(minutes=(xr - x) * 5)
            by_t.setdefault(bucket(t), {})[key] = round(hz, 2)

    HISTORY_DIR.mkdir(exist_ok=True)
    months = {}
    for e in by_t:
        t = datetime.datetime.fromtimestamp(e, datetime.timezone.utc)
        months.setdefault(t.strftime("%Y-%m"), []).append(e)
    added = 0
    for mk, epochs in months.items():
        path = HISTORY_DIR / f"{mk}.json"
        records = load_json(path) or []
        seen = set()
        for r in records:
            try:
                tt = datetime.datetime.fromisoformat(str(r["t"]))
                seen.add(bucket(tt))
            except Exception:
                pass
        for e in sorted(epochs):
            if e in seen:
                continue
            t = datetime.datetime.fromtimestamp(e, datetime.timezone.utc)
            v = by_t[e]
            records.append({
                "t": t.isoformat(),
                "F1": v.get("F1"), "F2": v.get("F2"),
                "F3": v.get("F3"), "F4": v.get("F4"),
                "src": "line",  # 全幅読み取り由来 (右端1点読みと区別)
            })
            added += 1
        records.sort(key=lambda r: str(r.get("t", "")))
        save_json(path, records)
    return added


def rebuild_daily(mk):
    """{月}.daily.json を生データから再生成する (当月も毎回作り直す)。
    日付は日本時間 (UTC+9) で区切る — ダッシュボードの棒グラフと同じ流儀"""
    src = HISTORY_DIR / f"{mk}.json"
    if not src.exists():
        return
    records = load_json(src) or []
    days = {}
    for r in records:
        try:
            tt = datetime.datetime.fromisoformat(str(r["t"]))
            d = (tt + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
        except Exception:
            continue
        for k in ("F1", "F2", "F3", "F4"):
            v = r.get(k)
            if v is not None:
                days.setdefault(d, {}).setdefault(k, []).append(v)
    out = []
    for d in sorted(days):
        entry = {"date": d}
        for k, vs in sorted(days[d].items()):
            entry[k] = {"min": min(vs), "max": max(vs),
                        "mean": round(sum(vs) / len(vs), 4), "count": len(vs)}
        out.append(entry)
    save_json(HISTORY_DIR / f"{mk}.daily.json", out)


def recover_from_archive(utc_now, ocr_calib_templates):
    """保険: schumann-frequency.com の線グラフアーカイブから直近数日を回収し、
    ライブ観測(sos70)が落ちていた時間帯の5分点を穴埋めする。
    宝の山(history/{月}.json)と同じ器・同じ merge_series_history に流すので、
    取りこぼしても翌日には自動で埋まる。過去方向にも未来方向にも効く保険。"""
    import urllib.request
    base = "https://cdn.schumann-frequency.com/assets/archiv/{y}/{m:02d}/schumann-frequencies-{d:02d}-{m:02d}-{y}.jpg"
    ua = {"User-Agent": "Mozilla/5.0 (0Lei recover)"}
    total = 0
    # 「今日」と「昨日」の画像を取れば、直近3〜4日ぶんの完全日をカバーできる
    for back in (0, 1):
        d = (utc_now + datetime.timedelta(hours=9)).date() - datetime.timedelta(days=back)
        try:
            req = urllib.request.Request(base.format(y=d.year, m=d.month, d=d.day), headers=ua)
            raw = urllib.request.urlopen(req, timeout=25).read()
            a = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            if verify_layout(a):
                continue
            cal = ocr_axis_calibration(a, ocr_calib_templates)
            ser = extract_series(a, cal)
            img_utc = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
            total += merge_series_history(ser, img_utc)
        except Exception:
            continue
    return total


def update_solar_daily():
    """GFZポツダムの日別Ap指数 (CC BY 4.0) の直近14日を取得してマージ。
    初回バックフィルは build_legacy_and_solar.py で実施済み"""
    import urllib.request
    path = HISTORY_DIR / "solar_daily.json"
    data = load_json(path) or {"schema_version": "1.0",
                               "source": "GFZ Potsdam Kp/Ap index (CC BY 4.0)", "days": []}
    now = datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
    end = now.strftime("%Y-%m-%dT23:59:59Z")
    url = f"https://kp.gfz.de/app/json/?start={start}&end={end}&index=Ap"
    req = urllib.request.Request(url, headers={"User-Agent": "0Lei-solar"})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    by = {e["d"]: e for e in data["days"]}
    for t, ap in zip(d.get("datetime", []), d.get("Ap", [])):
        if ap is not None:
            by[t[:10]] = {"d": t[:10], "ap": ap}
    data["days"] = [by[k] for k in sorted(by)]
    save_json(path, data)
    print(f"+ solar_daily.json ({len(data['days'])} days)")


def rebuild_daily_summary():
    """全期間のF1日平均を1ファイルに集約 (ダッシュボードはこれだけ読めばよい)。
    APIは追加のみ = 既存ファイルは不変 (api-v1 ルール準拠)"""
    # 月ファイルはUTC区切り・日付はJST区切りなので、月境の日は2ファイルに
    # 跨って現れる。同じ日付は件数で重み付けして1本に合算する
    acc = {}
    for p in sorted(HISTORY_DIR.glob("????-??.daily.json")):
        for e in load_json(p) or []:
            f1 = e.get("F1") or {}
            if isinstance(f1, dict) and f1.get("mean") is not None:
                d = e["date"]
                n = f1.get("count", 0) or 1
                sm, cn = acc.get(d, (0.0, 0))
                acc[d] = (sm + f1["mean"] * n, cn + n)
    # 日平均が妥当域(7.2〜8.12Hz)を外れる日は軸誤読の疑い → グラフから除外
    days = {d: {"d": d, "f1": round(sm / cn, 4), "n": cn}
            for d, (sm, cn) in acc.items()
            if 7.2 <= sm / cn <= 8.12}
    # 【真A案・2026-08-06】レガシー日平均(schumann-resonance.earth由来CSV)はマージしない。
    # あれは1日1点の平均値で、中央に寄って本物の日々変動が潰れる(σ0.08 vs 5分読取りσ0.13)。
    # 出典は history/legacy_daily.json に温存するが、宝の山と日別グラフには線グラフ5分読取り
    # (line/cross)だけを使い、全期間で質を揃える。
    out = [days[d] for d in sorted(days)]
    save_json(HISTORY_DIR / "daily_summary.json",
              {"schema_version": "1.0", "days": out})
    print(f"+ daily_summary.json ({len(out)} days)")


def compress_previous_month(current_mk):
    """月が変わったら前月ファイルを日次集計 (min/max/mean/count) に圧縮した
    .daily.json も生成する。生データは残す (リポジトリ肥大が問題になるまで削除しない)"""
    y, m = int(current_mk[:4]), int(current_mk[5:7])
    prev_mk = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    src = HISTORY_DIR / f"{prev_mk}.json"
    dst = HISTORY_DIR / f"{prev_mk}.daily.json"
    if not src.exists() or dst.exists():
        return
    records = load_json(src) or []
    days = {}
    for r in records:
        d = str(r.get("t", ""))[:10]
        if len(d) != 10:
            continue
        for k in ("F1", "F2", "F3", "F4"):
            v = r.get(k)
            if v is not None:
                days.setdefault(d, {}).setdefault(k, []).append(v)
    out = []
    for d in sorted(days):
        entry = {"date": d}
        for k, vs in sorted(days[d].items()):
            entry[k] = {"min": min(vs), "max": max(vs),
                        "mean": round(sum(vs) / len(vs), 4), "count": len(vs)}
        out.append(entry)
    save_json(dst, out)
    print(f"+ Compressed {src} -> {dst} ({len(out)} days)")


def update_monthly_summary():
    """F1 月平均の一覧。ダッシュボードはこれ1ファイルで月平均トレンドを描ける"""
    months = []
    for p in sorted(HISTORY_DIR.glob("????-??.json")):
        records = load_json(p) or []
        vals = [r["F1"] for r in records if r.get("F1") is not None]
        months.append({
            "month": p.stem,
            "F1_mean": round(sum(vals) / len(vals), 4) if vals else None,
            "count": len(records),
        })
    save_json(HISTORY_DIR / "monthly_summary.json", {
        "schema_version": "1.0",
        "target_hz": TARGET_HZ,
        "baseline_hz": 7.83,
        "months": months,
    })


def update_events(prev_data, f1_hz, timestamp):
    """将来のプッシュ通知用イベント。F1 が 8.0Hz を上抜けた回を記録する
    (超えている間は毎回入れず、下→上のクロス時のみ追加)"""
    events = list((prev_data or {}).get("events") or [])
    prev_f1 = None
    try:
        prev_f1 = prev_data["modes"]["F1"]["hz"]
    except (TypeError, KeyError):
        pass
    if f1_hz is not None and f1_hz > 8.0 and (prev_f1 is None or prev_f1 <= 8.0):
        events.append({"type": "f1_above_8.0", "at": timestamp})
        print(f"+ event: f1_above_8.0 ({f1_hz} Hz)")
    return events[-MAX_EVENTS:]

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
            # 中央の白い透かし "Copyright@ http://sosrff.tsu.ru"(行~164-190,列~310-700)を除外。
            # これがF1(白)マスクに混入し、中日のF1が median で低く歪んでいた(2026-08-05根治)
            m[162:192, 305:705] = False
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


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def set_github_output(name, value):
    """GitHub Actions のステップ出力 (後続ステップの if 条件用)。ローカル実行では何もしない"""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = utc_now.isoformat()
    print(f"=== Schumann Fetch v6 (pixel) @ {timestamp} ===")

    line_bytes, line_url = fetch_image(URLS_LINE)
    if line_bytes is None:
        print("! Line graph fetch failed — keeping previous data")
        set_github_output("changed", "false")
        return

    # 無駄打ち対策: srf.jpg が前回と同一 (トムスク側未更新) なら
    # 重い読み取り処理を飛ばし、timestamp だけ更新して正常終了
    sha = hashlib.sha256(line_bytes).hexdigest()
    prev_sha = None
    if Path(SHA_FILE).exists():
        prev_sha = Path(SHA_FILE).read_text(encoding="utf-8").strip()
    if sha == prev_sha:
        prev_data = load_json(OUTPUT_DATA)
        if prev_data is not None:
            prev_data["timestamp"] = timestamp
            prev_data["updated_jst"] = jst_str(utc_now)
            prev_data["polarization"] = calculate_polarization(utc_now)
            prev_data["source_unchanged"] = True
            save_json(OUTPUT_DATA, prev_data)
            print("+ srf.jpg unchanged (SHA-256 match) — timestamp-only update")
            set_github_output("changed", "false")
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
        set_github_output("changed", "false")
        return

    templates = load_templates()
    ocr_calib = ocr_axis_calibration(arr, templates)
    modes = extract_modes(arr, ocr_calib)
    for k, v in modes.items():
        print(f"  {k}: {v}")

    # 有効モードが1つも無ければ前回データを保持して終了
    if all(m.get("hz") is None for m in modes.values()):
        print("! No modes extracted — keeping previous data")
        set_github_output("changed", "false")
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

    # 項目6: 今日の共振コンディション (shm.jpg の雷活動バースト検出)
    condition, condition_metrics = analyze_condition(spectro_bytes)

    polarization = calculate_polarization(utc_now)

    # F5 は元グラフに存在しないので常に null (v5 では幻覚読みしていた)
    modes_out = {k: {"hz": v.get("hz"), "confidence": v.get("confidence", 0),
                     "calibration": v.get("calibration"),
                     "amp": amp_vals.get(k), "q": q_vals.get(k)}
                 for k, v in modes.items()}
    modes_out["F5"] = {"hz": None, "confidence": 0}

    valid = {k: v for k, v in modes.items() if v.get("hz") is not None}
    strongest = min(valid, key=lambda k: abs(valid[k]["hz"] - THEORY[k])) if valid else ""

    # 公式API v1: 前回データを読み (events 引き継ぎ用)、追加フィールドを計算
    prev_data = load_json(OUTPUT_DATA)
    f1_hz = modes.get("F1", {}).get("hz")

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
        "source_unchanged": False,
        # ===== 公式API v1 追加フィールド (既存フィールドは不変) =====
        "schema_version": SCHEMA_VERSION,
        "target_hz": TARGET_HZ,
        "distance_to_target_hz": round(f1_hz - TARGET_HZ, 4) if f1_hz is not None else None,
        "updated_jst": jst_str(utc_now),
        "events": update_events(prev_data, f1_hz, timestamp),
        "condition": condition,
        "condition_metrics": condition_metrics,
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

    # 項目3: 月別ファイルへの永久蓄積 (トレンドグラフの元データ)。condition も一緒に記録
    update_permanent_history(timestamp, modes, condition)

    # 項目3.5: 全幅読み取り — 画像に描かれている3日ぶん (5分刻み) を丸ごと回収。
    # 前後の点と整合しない読み取りミスは除外し、記録済みの時刻はスキップ
    try:
        series = extract_series(arr, ocr_calib)
        n_new = merge_series_history(series, utc_now)
        print(f"+ Full-width backfill: {n_new} new samples "
              f"({', '.join(k + '=' + str(len(v)) for k, v in series.items())})")
    except Exception as e:
        print(f"! Full-width backfill failed: {e}")

    # 項目3.6: 保険 — schumann-frequency.com アーカイブから直近数日を回収し、
    # ライブが落ちていた穴を自動で埋める(宝の山と同じ器へ)
    try:
        rec = recover_from_archive(utc_now, templates)
        if rec:
            print(f"+ Archive recovery: {rec} new samples (self-healing)")
    except Exception as e:
        print(f"! archive recovery failed: {e}")

    # 日次集計はJST区切りで毎回作り直す (当月ぶんもダッシュボードから読める)
    try:
        for pth in sorted(HISTORY_DIR.glob("????-??.json")):
            rebuild_daily(pth.stem)
        rebuild_daily_summary()
    except Exception as e:
        print(f"! rebuild_daily failed: {e}")
    try:
        update_solar_daily()
    except Exception as e:
        print(f"! solar update failed: {e}")

    # 今回の srf.jpg の SHA-256 を記録 (次回の無駄打ち判定用)
    Path(SHA_FILE).write_text(sha + "\n", encoding="utf-8")
    set_github_output("changed", "true")


if __name__ == "__main__":
    main()
