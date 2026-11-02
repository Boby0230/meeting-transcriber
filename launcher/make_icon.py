"""Draws the app icon (microphone emoji on a mint rounded square) as an .iconset.

The mint matches --accent in static/style.css, so the icon matches the logo
in the app's own header.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

size = 1024
icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((100, 100, 924, 924), radius=185, fill=(110, 231, 160))

emoji_font = ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc", 160)
glyph = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
ImageDraw.Draw(glyph).text((20, 20), "🎙", font=emoji_font, embedded_color=True)
glyph = glyph.crop(glyph.getbbox()).resize((520, 520), Image.LANCZOS)
icon.alpha_composite(glyph, ((size - 520) // 2, (size - 520) // 2))

for px in (16, 32, 128, 256, 512):
    icon.resize((px, px), Image.LANCZOS).save(out / f"icon_{px}x{px}.png")
    icon.resize((px * 2, px * 2), Image.LANCZOS).save(out / f"icon_{px}x{px}@2x.png")
