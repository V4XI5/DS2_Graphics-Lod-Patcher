import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BG, ACCENT = (5, 5, 5, 255), (255, 138, 31, 255)


def icon(size):
    s = 4 * size
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=BG, outline=ACCENT, width=max(4, s // 24))
    v = [(0.22, 0.25), (0.39, 0.25), (0.5, 0.58), (0.61, 0.25), (0.78, 0.25), (0.585, 0.77), (0.415, 0.77)]
    d.polygon([(x * s, y * s) for x, y in v], fill=ACCENT)
    return img.resize((size, size), Image.LANCZOS)


big = icon(256)
big.save(os.path.join(HERE, 'app', 'vaxis.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
big.save(os.path.join(HERE, 'build', 'vaxis_icon.png'))
print('icon written')
