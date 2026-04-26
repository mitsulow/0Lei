"""
月画像を月本体の輪郭ピッタリにクロップする。
- 中心は画像中央と仮定
- 中心からの「明るいピクセル」の最大距離で半径を推定
- その半径で正方形クロップ＋円マスク再適用
"""
from PIL import Image, ImageDraw
import numpy as np
from pathlib import Path
import sys

ICONS = Path(r"C:\Users\waras\0Lei\moon_icons")
TARGET_PX = 192
BRIGHTNESS_THRESHOLD = 40
RADIUS_PADDING = 1.05  # 月本体の輪郭にちょっと余裕


def crop_one(path: Path) -> tuple[int, int]:
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    h, w, _ = arr.shape
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    brightness = (r.astype(int) + g.astype(int) + b.astype(int)) / 3
    bright = (brightness > BRIGHTNESS_THRESHOLD) & (a > 100)

    cx, cy = w // 2, h // 2

    if bright.sum() < 50:
        # 新月など光面がほぼ無いケース：共通半径で切り出し
        radius = int(min(w, h) * 0.4)
    else:
        ys, xs = np.where(bright)
        distances = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        radius = int(distances.max() * RADIUS_PADDING)
        radius = max(radius, 30)
        radius = min(radius, min(w, h) // 2)

    # 正方形クロップ
    left = max(0, cx - radius)
    top = max(0, cy - radius)
    right = min(w, cx + radius)
    bottom = min(h, cy + radius)
    cropped = img.crop((left, top, right, bottom))

    # 円形アルファマスクを再適用（月の輪郭ピッタリ）
    cw, ch = cropped.size
    big = Image.new("L", (cw * 4, ch * 4), 0)
    bd = ImageDraw.Draw(big)
    bd.ellipse([0, 0, cw * 4 - 1, ch * 4 - 1], fill=255)
    mask = big.resize((cw, ch), Image.LANCZOS)
    cropped.putalpha(mask)

    # 192px に縮小（アスペクト保持）
    cropped.thumbnail((TARGET_PX, TARGET_PX), Image.LANCZOS)
    cropped.save(path, "PNG", optimize=True, compress_level=9)

    return radius, path.stat().st_size


def main():
    files = sorted(ICONS.glob("moon_*.png"))
    print(f"processing {len(files)} files")
    total_before = 0
    total_after = 0
    for f in files:
        before = f.stat().st_size
        radius, after = crop_one(f)
        total_before += before
        total_after += after
        print(f"  {f.name}: r={radius} {before/1024:.0f}KB -> {after/1024:.0f}KB")
    print(f"total: {total_before/1024:.0f}KB -> {total_after/1024:.0f}KB")


if __name__ == "__main__":
    main()
