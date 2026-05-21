"""太陽画像を透過化＋256px縮小して images/sun.png に保存"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'
import numpy as np
from PIL import Image

SRC = r'C:\Users\waras\0Lei\images\sun_raw.jpg'
DST = r'C:\Users\waras\0Lei\images\sun.png'
SIZE = 256  # canvas用ターゲット

img = Image.open(SRC).convert('RGBA')
W, H = img.size
print(f'入力: {W}x{H}')

# 縮小（高品質 LANCZOS）
img.thumbnail((SIZE, SIZE), Image.LANCZOS)

# 白背景を透過化（白に近いほど透過）
arr = np.array(img).astype(np.int16)
r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
# 白さ = min(r,g,b) が高い + 全体明るい
brightness = (r.astype(float) + g + b) / 3
whiteness = np.minimum(np.minimum(r, g), b).astype(float)
# 白い領域 = whiteness 200以上
mask = whiteness > 200
# 段階的に透過（255白→0アルファ、200→徐々に不透明）
alpha_factor = np.clip((255 - whiteness) / 55, 0, 1)
new_alpha = (255 * alpha_factor).clip(0, 255).astype(np.uint8)
# 元のアルファとの最小（黄色部分は維持）
arr[:, :, 3] = np.minimum(arr[:, :, 3], new_alpha).clip(0, 255)
out = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')

out.save(DST, 'PNG', optimize=True)
print(f'出力: {DST} ({out.size[0]}x{out.size[1]})')
print(f'サイズ: {os.path.getsize(DST) / 1024:.1f} KB')
