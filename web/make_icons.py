"""
Draws the app icon (a low-poly cat face with lavender hair) and writes every size the browser / iOS /
Android want into web/icons/. Needs Pillow:  tools/voice-venv/Scripts/python.exe web/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "icons"
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def draw(size=S, rounded=True):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bg = Image.new("RGB", (S, S))
    top, bot = hexc("#3a2a5e"), hexc("#17141f")
    for y in range(S):                                           # vertical gradient
        ImageDraw.Draw(bg).line([(0, y), (S, y)], fill=lerp(top, bot, y / S))
    d = ImageDraw.Draw(bg)
    # faint retro grid floor
    for k in range(9):
        y = int(S * (0.72 + 0.035 * k * k ** 0.3))
        d.line([(0, y), (S, y)], fill=lerp(hexc("#5a3f86"), bot, k / 9), width=3)
    for k in range(-6, 7):
        d.line([(S / 2 + k * 40, S * 0.72), (S / 2 + k * 260, S)], fill=hexc("#4a3570"), width=3)
    # low-poly face: facets in slightly different lavender shades
    hair, hair_d, hair_l = hexc("#c9aed8"), hexc("#a98cc0"), hexc("#ddc8ea")
    skin, skin_d = hexc("#ffe2d3"), hexc("#f2c9b8")
    inner = hexc("#ffb3cf")
    cx, cy = S / 2, S * 0.56
    # ears
    for sgn in (-1, 1):
        base_o, base_i, tip = (cx + sgn * 330, cy - 90), (cx + sgn * 110, cy - 230), (cx + sgn * 300, cy - 420)
        d.polygon([base_o, base_i, tip], fill=hair_d if sgn < 0 else hair)
        d.polygon([(cx + sgn * 290, cy - 150), (cx + sgn * 160, cy - 225), (cx + sgn * 285, cy - 345)], fill=inner)
    # head silhouette (octagon-ish) as hair, split into facets
    pts = [(cx - 330, cy - 90), (cx - 250, cy - 250), (cx, cy - 300), (cx + 250, cy - 250), (cx + 330, cy - 90),
           (cx + 300, cy + 120), (cx + 160, cy + 260), (cx, cy + 300), (cx - 160, cy + 260), (cx - 300, cy + 120)]
    shades = [hair_d, hair, hair_l, hair, hair_d, hair, hair_d, hair, hair_l, hair_d]
    for i in range(len(pts)):
        d.polygon([(cx, cy), pts[i], pts[(i + 1) % len(pts)]], fill=shades[i])
    # face (skin) facets
    face = [(cx - 230, cy - 20), (cx - 120, cy - 120), (cx + 120, cy - 120), (cx + 230, cy - 20),
            (cx + 200, cy + 150), (cx + 90, cy + 245), (cx - 90, cy + 245), (cx - 200, cy + 150)]
    for i in range(len(face)):
        d.polygon([(cx, cy + 60), face[i], face[(i + 1) % len(face)]], fill=skin if i % 2 else skin_d)
    # bangs
    for k, x in enumerate(range(-260, 260, 104)):
        d.polygon([(cx + x, cy - 140), (cx + x + 104, cy - 140), (cx + x + 52 + (18 if k % 2 else -18), cy - 20)],
                  fill=hair if k % 2 else hair_l)
    # eyes
    eye = hexc("#5a1f7a")
    for sgn in (-1, 1):
        ex, ey = cx + sgn * 110, cy + 70
        d.ellipse([ex - 48, ey - 62, ex + 48, ey + 62], fill=eye)
        d.ellipse([ex - 20 + sgn * 6, ey - 44, ex + 6 + sgn * 6, ey - 16], fill=(255, 255, 255))
        d.ellipse([ex + 52 * sgn - 30, ey + 80, ex + 52 * sgn + 30, ey + 104], fill=hexc("#ffa8c0"))
    # little "w" mouth
    d.line([(cx - 34, cy + 175), (cx - 17, cy + 192), (cx, cy + 175), (cx + 17, cy + 192), (cx + 34, cy + 175)],
           fill=hexc("#8a2a3a"), width=9, joint="curve")
    img.paste(bg, (0, 0))
    if rounded:   # rounded-square mask (iOS adds its own mask; browsers/Android use this)
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
        img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    full = draw(1024, rounded=False)                  # iOS wants a square, opaque icon (it rounds it)
    full.convert("RGB").resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    for n in (192, 512):
        full.convert("RGB").resize((n, n), Image.LANCZOS).save(OUT / f"icon-{n}.png")      # "any" / maskable
    rounded = draw(1024, rounded=True)
    rounded.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512-rounded.png")
    rounded.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    rounded.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
