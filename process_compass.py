"""コンパス画像を加工: リング部分カット → 円形コンパス本体のみ → 透過化 → 512px"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'
import numpy as np
from PIL import Image

SRC = r'C:\Users\waras\0Lei\images\compass_raw.jpg'
DST = r'C:\Users\waras\0Lei\images\compass.png'

img = Image.open(SRC).convert('RGBA')
W, H = img.size
print(f'入力: {W}x{H}')

# リング・台座を除いてコンパス本体だけ抽出（深めクロップ）
crop_top_ratio = 0.27       # 上のリング部分を削る
crop_bot_ratio = 0.06       # 下の台座を少し削る
crop_top = int(H * crop_top_ratio)
crop_bot = int(H * crop_bot_ratio)
new_h = H - crop_top - crop_bot
square = min(W, new_h)
crop_left = (W - square) // 2
crop_y0 = crop_top + (new_h - square) // 2
img = img.crop((crop_left, crop_y0, crop_left + square, crop_y0 + square))
print(f'クロップ後: {img.size}')

# 512px縮小
TARGET = 512
img = img.resize((TARGET, TARGET), Image.LANCZOS)

# 白背景透過化
arr = np.array(img).astype(np.int16)
r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
whiteness = np.minimum(np.minimum(r, g), b).astype(float)
alpha_factor = np.clip((255 - whiteness) / 50, 0, 1)
new_alpha = (255 * alpha_factor).clip(0, 255).astype(np.uint8)
arr[:, :, 3] = np.minimum(arr[:, :, 3], new_alpha).clip(0, 255)

# ★円形マスクで仕上げ（本体の円だけ残す）
cy, cx = TARGET // 2, TARGET // 2
radius_main = TARGET * 0.49  # 内側完全不透明
radius_fade = TARGET * 0.50  # 外側へ薄くフェード
y_ix, x_ix = np.ogrid[:TARGET, :TARGET]
dist = np.sqrt((x_ix - cx) ** 2 + (y_ix - cy) ** 2)
circle_mask = np.where(dist <= radius_main, 255,
                       np.where(dist <= radius_fade,
                                255 * (radius_fade - dist) / (radius_fade - radius_main),
                                0)).clip(0, 255).astype(np.uint8)
arr[:, :, 3] = np.minimum(arr[:, :, 3], circle_mask).clip(0, 255)

out = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')
out.save(DST, 'PNG', optimize=True)
print(f'出力: {DST} ({out.size[0]}x{out.size[1]})')
print(f'サイズ: {os.path.getsize(DST) / 1024:.1f} KB')
