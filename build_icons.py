"""ツキヨガ 半月アイコン生成

仕様:
  - 夜空背景（深紺ラジアル + 微星）
  - 中央に「右半分が光る半月（first quarter）」
  - 月は暖色クリーム + 柔らかいハロ
  - マスカブル安全圏（中央 80% 円）に余裕で収まる
  - 出力: icons/icon-{120,152,180,192,512}.png + favicon.png

実行: PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python build_icons.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "icons_v7"
OUT_DIR.mkdir(exist_ok=True)

SIZES = [120, 152, 180, 192, 512]
MASTER = 1024  # 高解像度で作って各サイズへリサンプル


def lerp_rgb(a, b, t):
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def make_background(size: int) -> Image.Image:
    """深い濃紺ベタ + わずかなビネット + 微星"""
    base_navy = (5, 10, 32)
    img = Image.new("RGB", (size, size), base_navy)
    px = img.load()
    cx, cy = size / 2, size / 2
    max_r = math.hypot(cx, cy)
    # ふちだけわずかに暗くしてアイコンの輪郭を引き締める
    edge_dark = (1, 3, 14)
    for y in range(size):
        for x in range(size):
            r = math.hypot(x - cx, y - cy) / max_r
            t = max(0.0, (r - 0.65) / 0.35)  # 65%より外側だけ徐々に暗く
            px[x, y] = lerp_rgb(base_navy, edge_dark, t)

    # 微星（seed 固定、少なめ・はっきり）
    rng = random.Random(20260517)
    d = ImageDraw.Draw(img)
    star_count = max(5, size // 130)
    for _ in range(star_count):
        sx = rng.randint(int(size * 0.05), int(size * 0.95))
        sy = rng.randint(int(size * 0.05), int(size * 0.95))
        # 月のエリアは広めに避ける
        dx = sx - cx
        dy = sy - cy
        if math.hypot(dx, dy) < size * 0.42:
            continue
        intensity = rng.randint(200, 245)
        col = (intensity, intensity, intensity)
        r = max(1, int(size * 0.0035))
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=col)
    return img


def draw_half_moon(base: Image.Image) -> Image.Image:
    """右半分が光る半月 + ハロ"""
    size = base.size[0]
    cx = cy = size / 2
    moon_r = size * 0.34   # 直径 68% （マスカブル安全圏 80% に余裕）

    base = base.convert("RGBA")

    # === ハロ：月の光側だけに、暗側にハミ出さないようマスク ===
    halo = Image.new("RGBA", base.size, (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hcx = cx + moon_r * 0.20
    for r, a in [
        (moon_r * 1.35, 14),
        (moon_r * 1.22, 28),
        (moon_r * 1.12, 48),
        (moon_r * 1.05, 80),
    ]:
        hd.ellipse([hcx - r, cy - r, hcx + r, cy + r], fill=(255, 232, 180, a))
    halo = halo.filter(ImageFilter.GaussianBlur(radius=size * 0.018))
    # 右半平面（光側）でのみ有効に：暗側にハミ出さない
    halo_alpha = halo.split()[3]
    ha_px = halo_alpha.load()
    for y in range(size):
        for x in range(size):
            if x < cx - moon_r * 0.05:  # 月の暗側＋少し内側はハロ無効
                ha_px[x, y] = 0
    halo.putalpha(halo_alpha)
    base = Image.alpha_composite(base, halo)

    # === 半月本体（右半分のクリーム円弧）===
    # アルファマスク = 円 ∩ 右半平面
    circle_mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(circle_mask).ellipse(
        [cx - moon_r, cy - moon_r, cx + moon_r, cy + moon_r], fill=255
    )
    right_mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(right_mask).rectangle(
        [int(cx), 0, size, size], fill=255
    )
    # ターミネータをほんの少しソフトに（中央の縦線がガタつかないように）
    right_mask = right_mask.filter(ImageFilter.GaussianBlur(radius=size * 0.0018))

    # 画素ごとに min を取って最終アルファに
    ca = circle_mask.load()
    rm = right_mask.load()
    moon_alpha = Image.new("L", base.size, 0)
    ma = moon_alpha.load()

    # クリーム色（中心ほど明るく、ふちはわずかに沈む）
    cream_center = (254, 248, 228)
    cream_edge = (232, 220, 192)
    moon_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ml = moon_layer.load()
    for y in range(size):
        for x in range(size):
            a = min(ca[x, y], rm[x, y])
            if a == 0:
                continue
            ma[x, y] = a
            dx = (x - cx) / moon_r
            dy = (y - cy) / moon_r
            d = min(1.0, math.hypot(dx, dy))
            shade = 1.0 - d * 0.22  # ふちで少し沈む
            r = int(cream_center[0] * shade + cream_edge[0] * (1 - shade) * 0.0)
            g = int(cream_center[1] * shade + cream_edge[1] * (1 - shade) * 0.0)
            b = int(cream_center[2] * shade + cream_edge[2] * (1 - shade) * 0.0)
            ml[x, y] = (min(255, r), min(255, g), min(255, b), a)

    base = Image.alpha_composite(base, moon_layer)

    # === ターミネータの内側に わずかな影縁（立体感） ===
    edge = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ed = ImageDraw.Draw(edge)
    edge_w = max(2, int(size * 0.005))
    # 月の縦中央線（円の中にだけ出るように、後でmoon_alphaでマスク）
    ed.line(
        [(cx, cy - moon_r * 0.99), (cx, cy + moon_r * 0.99)],
        fill=(40, 28, 60, 110),
        width=edge_w,
    )
    edge = edge.filter(ImageFilter.GaussianBlur(radius=size * 0.005))
    # moon_alphaで切り抜き（夜空側にハミ出さない）
    ea = edge.split()[3]
    ea_px = ea.load()
    for y in range(size):
        for x in range(size):
            if ma[x, y] == 0:
                ea_px[x, y] = 0
    edge.putalpha(ea)
    base = Image.alpha_composite(base, edge)

    return base


def build_master() -> Image.Image:
    base = make_background(MASTER)
    img = draw_half_moon(base)
    return img.convert("RGB")


def main() -> None:
    print("半月アイコン生成中（マスター 1024px）…")
    master = build_master()
    for size in SIZES:
        out = master.resize((size, size), Image.LANCZOS)
        path = OUT_DIR / f"icon-{size}.png"
        out.save(path, "PNG", optimize=True)
        print(f"  {path.name}  {path.stat().st_size/1024:.1f} KB")
    fav = master.resize((64, 64), Image.LANCZOS)
    fav.save(ROOT / "favicon.png", "PNG", optimize=True)
    print(f"  favicon.png  {(ROOT/'favicon.png').stat().st_size/1024:.1f} KB")
    print("完了")


if __name__ == "__main__":
    main()
