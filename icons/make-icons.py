#!/usr/bin/env python3
"""Regenerate the installable PNG icon set from sonar-icon.jpeg.

Only needed when the source artwork changes; the PNGs it writes are checked
in, so install.sh never has to convert anything (and never needs Pillow).

    uv run --with pillow icons/make-icons.py

The source is a 1024x1024 render of a rounded-square icon sitting on a dark
backdrop with a drop shadow. CROP is the outer edge of that rounded square and
RADIUS its corner radius, both measured off the render; the backdrop outside
them is masked to transparent so the icon does not show as a dark tile on a
light panel.
"""
from pathlib import Path

from PIL import Image, ImageDraw

CROP = (136, 136, 887, 887)  # left, top, right, bottom (right/bottom exclusive)
RADIUS = 162  # corner radius in source pixels
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
SS = 4  # mask supersampling, for a clean antialiased corner

root = Path(__file__).resolve().parent
art = Image.open(root.parent / "sonar-icon.jpeg").convert("RGB").crop(CROP)
side = art.width

mask = Image.new("L", (side * SS, side * SS), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    (0, 0, side * SS - 1, side * SS - 1), radius=RADIUS * SS, fill=255
)
art = art.convert("RGBA")
art.putalpha(mask.resize((side, side), Image.LANCZOS))

for size in SIZES:
    out = root / "hicolor" / f"{size}x{size}" / "apps" / "sonarex.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    art.resize((size, size), Image.LANCZOS).save(out, optimize=True)
    print(out.relative_to(root.parent))
