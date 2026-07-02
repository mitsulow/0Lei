#!/usr/bin/env python3
"""
自作シューマン共振グラフ生成 (モード別4枚 + 時系列アーカイブ)

fetch_schumann_v6.py が保存した latest_linegraph.jpg から全時系列を
ピクセル抽出し、schumann_series.json に蓄積 (7日保持)。
そこから「一昨日00:00〜今日24:00 (JST)」のローリング3日窓で
graph_f1.png 〜 graph_f4.png を描画する。

- トムスク原本の画像は一切使わない (数値データのみ読み取り → 完全自作描画)
- 白線は彩度フィルタ (JPEG白化した黄線の芯を排除)
- 孤立スパイク除去 (前後から飛んだ孤立点は棄却)
- 現在値 = 右端5点の中央値 (端の滲みに頑健)
- Y軸は本家方式: 実測レンジ6等分の端数ラベル (精密感 + 縦幅フル活用)
- 平均の数値はヘッダーの凡例へ (グラフと重ならない)
"""
import io
import json
import math
import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "f6", Path(__file__).with_name("fetch_schumann_v6.py"))
f6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f6)

SERIES_FILE = Path(__file__).with_name("schumann_series.json")
IMAGE_LINE = Path(__file__).with_name("latest_linegraph.jpg")
RETAIN_DAYS = 7
JST = datetime.timezone(datetime.timedelta(hours=9))

MODES = [
    ("F1", "第一次モード", 7.83, (0, 255, 200)),
    ("F2", "第二次モード", 14.1, (255, 214, 10)),
    ("F3", "第三次モード", 20.3, (200, 120, 255)),
    ("F4", "第四次モード", 26.4, (255, 60, 140)),
]


# ============ 時系列抽出 ============

def loose_masks(a):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return {
        # 白: 明るい+彩度<32 (JPEGで白化した黄線の芯を排除)
        "F1": (mn > 150) & ((mx - mn) < 32),
        "F2": (r > 150) & (g > 150) & ((g - b) > 50) & ((r - b) > 50),
        "F3": (r > 120) & ((r - g) > 55) & ((r - b) > 55),
        "F4": (g > 120) & ((g - r) > 55) & ((g - b) > 55),
    }


def _clusters(ys):
    out = []
    s = ys[0]; p = ys[0]
    for y in ys[1:]:
        if y - p > 4:
            out.append((s + p) / 2); s = y
        p = y
    out.append((s + p) / 2)
    return out


def extract_series(arr, calib):
    """各モードの全カラム時系列 (Hz or None) を返す"""
    a = arr.astype(int)
    masks = loose_masks(a)
    X0, X1, Y0, Y1 = f6.PLOT_X0, f6.PLOT_X1, f6.PLOT_Y0, f6.PLOT_Y1
    out = {}
    for key, m in masks.items():
        if calib.get(key) is None:
            out[key] = [None] * (X1 - X0 - 1)
            continue
        mm = m.copy()
        mm[:Y0 + 1, :] = False; mm[Y1:, :] = False
        mm[:, :X0 + 1] = False; mm[:, X1:] = False
        if key == "F1":
            mm[:105, 895:] = False  # SOS70ロゴ
        pts = []
        prev = None
        for x in range(X0 + 1, X1):
            ys = np.where(mm[:, x])[0]
            if 0 < len(ys) < 30:
                cs = _clusters(list(ys))
                y = min(cs, key=lambda c: abs(c - prev)) if prev is not None else cs[0]
                prev = y
                pts.append(y)
            else:
                pts.append(None)
                prev = None
        # 孤立スパイク除去
        J = 20
        n = len(pts)
        for i in range(n):
            if pts[i] is None:
                continue
            pv = pts[i - 1] if i > 0 else None
            nx = pts[i + 1] if i < n - 1 else None
            far_pv = pv is not None and abs(pts[i] - pv) > J
            far_nx = nx is not None and abs(pts[i] - nx) > J
            if far_pv and (nx is None or far_nx):
                pts[i] = None
            elif pv is None and nx is None:
                pts[i] = None
        y0c, v0c, span = calib[key]
        out[key] = [None if y is None else round(v0c - (y - y0c) * span / 100.0, 2)
                    for y in pts]
    return out


# ============ アーカイブ (自前の連続データ) ============

def load_store():
    store = None
    if SERIES_FILE.exists():
        try:
            store = json.loads(SERIES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            store = None
    if store is not None:
        for sec in ("modes", "amp", "q"):
            store.setdefault(sec, {})
        return store
    return {"step_min": 5, "modes": {}, "amp": {}, "q": {}}


def merge_series(store, series, now_utc, section="modes"):
    """画像のカラム位置→時刻に変換してアーカイブへマージ (5分グリッド)"""
    # 画像の時刻軸オフセットを鮮度から自動判定 (data_age_min と同じロジック)
    X0, X1 = f6.PLOT_X0, f6.PLOT_X1
    N = X1 - X0 - 1
    # 右端の最新データで軸オフセットを決める
    last_idx = None
    for i in range(N - 1, -1, -1):
        if any(series[k][i] is not None for k in series):
            last_idx = i
            break
    if last_idx is None:
        return store
    hours_at = 72 * (last_idx + 1) / N
    day = min(2, int(hours_at // 24))
    hour = hours_at - day * 24
    _, axis_off = f6.data_age_min(day, hour, now_utc)
    tz = datetime.timezone(datetime.timedelta(hours=axis_off))
    local_now = now_utc.astimezone(tz)
    day1 = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=2)
    for key in series:
        dst = store[section].setdefault(key, {})
        for i, v in enumerate(series[key]):
            if v is None:
                continue
            t = day1 + datetime.timedelta(hours=72 * (i + 0.5) / N)
            t_jst = t.astimezone(JST)
            # 5分グリッドに丸め
            minute = (t_jst.minute // 5) * 5
            stamp = t_jst.replace(minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
            dst[stamp] = v
    # 保持期間で剪定
    cutoff = (now_utc.astimezone(JST) - datetime.timedelta(days=RETAIN_DAYS)).strftime("%Y-%m-%dT%H:%M")
    for key in store[section]:
        store[section][key] = {t: v for t, v in sorted(store[section][key].items()) if t >= cutoff}
    return store


# ============ 描画 ============

def _rounded(img, rad):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], rad, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img, (0, 0), mask)
    return out


def _fonts(S):
    try:
        return (ImageFont.truetype("meiryo.ttc", 12 * S),
                ImageFont.truetype("meiryo.ttc", 10 * S),
                ImageFont.truetype("meiryo.ttc", 9 * S),
                ImageFont.truetype("meiryob.ttc", 17 * S),
                ImageFont.truetype("meiryob.ttc", 12 * S))
    except OSError:
        try:
            p = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            pb = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
            return (ImageFont.truetype(p, 12 * S), ImageFont.truetype(p, 10 * S),
                    ImageFont.truetype(p, 9 * S), ImageFont.truetype(pb, 17 * S),
                    ImageFont.truetype(pb, 12 * S))
        except OSError:
            f = ImageFont.load_default()
            return (f, f, f, f, f)


def render_graphs(store, now_jst, outdir, section="modes", prefix="graph_f", unit="Hz", with_theory=True):
    # ローリング3日窓: 一昨日 00:00 〜 今日 24:00 (JST)
    start = now_jst.replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=2)
    end = start + datetime.timedelta(days=3)
    total_h = 72.0

    S = 2
    GW, GH = 1000 * S, 206 * S
    PADL, PADR, PADT, PADB = 6 * S, 62 * S, 12 * S, 32 * S  # 右目盛り (最新値=右端の真横で読める)
    BG = (34, 36, 44)             # 黒寄り (ネオンが締まる)
    TXT = (255, 255, 255)
    TICK = (255, 255, 255)        # 目盛り文字は完全な白
    DIM = (168, 172, 184)
    fM, fS_, fT, fB, fP = _fonts(S)
    DIV = 6
    stats = {}

    for key, name, theory, col in MODES:
        data = []
        for stamp, v in sorted(store[section].get(key, {}).items()):
            t = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=JST)
            if start <= t < end:
                data.append((t, v))
        base = Image.new("RGB", (GW, GH), BG)
        d = ImageDraw.Draw(base)
        px0, px1, py0, py1 = PADL, GW - PADR, PADT, GH - PADB

        vals = [v for _, v in data]
        if vals:
            avg = sum(vals) / len(vals)
            rng = max(max(vals) - min(vals), 0.05)
            lo = min(vals) - rng * 0.03
            hi = max(vals) + rng * 0.03
        else:
            avg = theory
            lo, hi = theory - 0.5, theory + 0.5

        def X(t):
            return px0 + (px1 - px0) * ((t - start).total_seconds() / 3600) / total_h

        def Y(v):
            return py1 - (py1 - py0) * (v - lo) / (hi - lo)

        # 時間軸 (完全JST): 3hラベル / 6hグリッド / 1h小目盛 / 0時に日付
        for hh in range(0, 73):
            t = start + datetime.timedelta(hours=hh)
            xx = X(t)
            if t.hour % 6 == 0:
                d.line([(xx, py0), (xx, py1)],
                       fill=(78, 82, 94) if t.hour == 0 else (62, 66, 78),
                       width=S if t.hour == 0 else 1)
            else:
                d.line([(xx, py1 - 3 * S), (xx, py1)], fill=(120, 124, 136), width=1)
            if t.hour % 3 == 0 and hh < 72:
                anc = "la" if xx < px0 + 8 * S else "ma"
                d.text((xx, py1 + 7 * S), f"{t.hour}", fill=TICK, font=fT, anchor=anc)
            if t.hour == 12 and hh < 72:
                d.text((xx, py1 + 18 * S),
                       f"{t.month}/{t.day}({'月火水木金土日'[t.weekday()]})",
                       fill=TXT, font=fS_, anchor="ma")
        d.line([(px0, py1), (px1, py1)], fill=(150, 154, 166), width=1)

        # Y軸: 本家方式 = 実測レンジ6等分の端数ラベル + 半刻み補助線 (全幅)
        for k in range(DIV * 2 + 1):
            vv = lo + (hi - lo) * k / (DIV * 2)
            yy = Y(vv)
            if k % 2 == 0:
                d.line([(px0, yy), (px1, yy)], fill=(66, 70, 82))
                d.text((px1 + 6 * S, yy), f"{vv:.2f}", fill=TICK, font=fT, anchor="lm")
            else:
                d.line([(px0, yy), (px1, yy)], fill=(50, 53, 64))
        d.line([(px1, py0), (px1, py1)], fill=(150, 154, 166), width=1)

        # 3日間平均の破線 (文字なし — 数値はヘッダーの凡例へ)
        yy = Y(avg)
        for xx in range(int(px0), int(px1), 12 * S):
            d.line([(xx, yy), (xx + 6 * S, yy)], fill=(255, 225, 130), width=S)

        # ネオングロー + 本線 (5分を超える欠測は線を切る)
        ov = Image.new("RGBA", (GW, GH), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        prev = None
        for t, v in data:
            p = (X(t), Y(v))
            if prev is not None and (t - prev[0]).total_seconds() <= 600:
                od.line([prev[1], p], fill=col + (70,), width=5 * S)
            prev = (t, p)
        base = Image.alpha_composite(base.convert("RGBA"), ov)
        d = ImageDraw.Draw(base)
        prev = None
        for t, v in data:
            p = (X(t), Y(v))
            if prev is not None and (t - prev[0]).total_seconds() <= 600:
                d.line([prev[1], p], fill=col, width=S + 1)
            prev = (t, p)

        # 最新点 + 現在値 (右端5点の中央値)
        cur = None
        if data:
            t_last, v_last = data[-1]
            cx, cy = X(t_last), Y(v_last)
            d.ellipse([cx - 7 * S, cy - 7 * S, cx + 7 * S, cy + 7 * S], outline=col, width=S)
            d.ellipse([cx - 3 * S, cy - 3 * S, cx + 3 * S, cy + 3 * S], fill=(255, 255, 255))
            tail = vals[-5:]
            cur = sorted(tail)[len(tail) // 2]

        # 見出し・数値は HTML 側で表示するため、画像はプロットのみ。
        # 2倍解像度のまま保存 (スマホで拡大しても補助目盛りまで読める)
        img = _rounded(base.convert("RGB"), 28)
        img.save(outdir / (prefix + key[-1] + ".png"))
        stats[key] = {"cur": cur, "avg": round(avg, 2), "theory": theory}
        print(f"+ {prefix}{key[-1]}.png  現在:{cur}  3日平均:{round(avg,2)} {unit}")

    return stats


def main():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if not IMAGE_LINE.exists():
        print("! latest_linegraph.jpg がありません (先に fetch_schumann_v6.py を実行)")
        return
    arr = np.array(Image.open(IMAGE_LINE).convert("RGB"))
    if f6.verify_layout(arr):
        print("! レイアウト検証に失敗 — グラフ生成をスキップ (前回画像を維持)")
        return
    templates = f6.load_templates()
    store = load_store()

    # 周波数 (srf)
    calib = f6.ocr_axis_calibration(arr, templates)
    series = extract_series(arr, calib)
    store = merge_series(store, series, now_utc, section="modes")

    # 振幅 (sra) と Q値 (srq): 同じエンジンで全時系列を抽出して蓄積
    for urls, section, fname in [(f6.URLS_AMP, "amp", "latest_amp.jpg"),
                                 (f6.URLS_Q, "q", "latest_q.jpg")]:
        try:
            raw, _ = f6.fetch_image(urls)
            if raw is None:
                print(f"! {section}: fetch failed")
                continue
            Path(__file__).with_name(fname).write_bytes(raw)
            aux = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            if f6.verify_layout(aux):
                print(f"! {section}: layout check failed")
                continue
            aux_calib = f6.ocr_axis_calibration(aux, templates)
            aux_series = extract_series(aux, aux_calib)
            store = merge_series(store, aux_series, now_utc, section=section)
        except Exception as e:
            print(f"! {section} failed: {e}")

    SERIES_FILE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    n = {k: len(v) for k, v in store["modes"].items()}
    print(f"+ series 蓄積: {n}")

    now_jst = now_utc.astimezone(JST)
    outdir = Path(__file__).parent
    stats = render_graphs(store, now_jst, outdir)  # 周波数 graph_f1..4
    render_graphs(store, now_jst, outdir, section="amp", prefix="graph_a", unit="pT", with_theory=False)
    render_graphs(store, now_jst, outdir, section="q", prefix="graph_q", unit="Q", with_theory=False)
    Path(__file__).with_name("graph_stats.json").write_text(
        json.dumps({"updated": now_utc.isoformat(), "modes": stats}, ensure_ascii=False),
        encoding="utf-8")


if __name__ == "__main__":
    main()
