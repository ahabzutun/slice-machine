"""Draws the app icon (1024 px PNG): a sliced waveform in the blueprint style Kontrolleur's icon uses.
   python3 scripts/make_icon.py   →  scripts/AppIcon-1024.png, scripts/AppIcon.icns, slicemachine/icon.png"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

S = 1024
HERE = os.path.dirname(os.path.abspath(__file__))


def layer():
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


base = Image.new("RGBA", (S, S), (14, 18, 25, 255))
grid = layer()
g = ImageDraw.Draw(grid)
for v in range(84, 964, 48):
    g.line((v, 0, v, S), fill=(110, 150, 180, 26), width=2)
    g.line((0, v, S, v), fill=(110, 150, 180, 26), width=2)
base.alpha_composite(grid)

# a drum-like waveform: hits with decaying tails
random.seed(7)
x0, x1, cy, amp = 150, 874, 512, 250
hits = [0.0, 0.17, 0.31, 0.46, 0.58, 0.74, 0.87]
pts_top, pts_bot = [], []
for x in range(x0, x1 + 1, 3):
    t = (x - x0) / (x1 - x0)
    a = 0.04
    for h in hits:
        if t >= h:
            a = max(a, math.exp(-(t - h) * 26) * (0.95 if h in (0.0, 0.46) else 0.7))
    w = a * (0.75 + 0.25 * math.sin(x * 0.9)) * amp
    pts_top.append((x, cy - w))
    pts_bot.append((x, cy + w * 0.92))
poly = pts_top + pts_bot[::-1]
cyan, orange = (80, 225, 248, 255), (255, 165, 75, 255)
fill = layer()
ImageDraw.Draw(fill).polygon(poly, fill=(70, 220, 245, 70))
base.alpha_composite(fill)
glow = layer()
ImageDraw.Draw(glow).line(pts_top + pts_bot[::-1] + [pts_top[0]], fill=(70, 220, 245, 150), width=22)
base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)))
lines = layer()
d = ImageDraw.Draw(lines)
d.line(pts_top, fill=cyan, width=9, joint="curve")
d.line(pts_bot, fill=cyan, width=9, joint="curve")
# slice markers at the hits
for h in hits[1:]:
    x = x0 + h * (x1 - x0) - 6
    d.line((x, 210, x, 814), fill=orange, width=10)
    d.ellipse((x - 16, 186, x + 16, 218), fill=orange)
base.alpha_composite(lines)

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((60, 60, 964, 964), radius=200, fill=255)
out = layer()
out.paste(base, (0, 0), mask)
out.save(os.path.join(HERE, "AppIcon-1024.png"))
out.save(os.path.join(HERE, "AppIcon.icns"), sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
out.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "..", "slicemachine", "icon.png"))
print("icon written")
