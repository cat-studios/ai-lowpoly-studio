"""
Measure a reference picture's colours (run with tools/voice-venv, which has Pillow):

    tools/voice-venv/Scripts/python.exe pipeline/picture_colors.py <picture> <out.json>

out.json = {"top": "#rrggbb", "middle": "#rrggbb", "bottom": "#rrggbb", "palette": ["#rrggbb", ...]}
top / middle / bottom are the average colours of the upper, middle and lower thirds of the picture: the sky (or
far background), the walls or trees, and the ground. palette is five dominant colours.
"""
import json
import sys

from PIL import Image


def hex_of(rgb):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, round(v)))) for v in rgb[:3])


def band_average(img, y0, y1):
    band = img.crop((0, y0, img.width, max(y0 + 1, y1))).resize((1, 1), Image.BOX)
    return band.getpixel((0, 0))


def main():
    src, out = sys.argv[1], sys.argv[2]
    img = Image.open(src).convert("RGB")
    h = img.height
    small = img.copy()
    small.thumbnail((160, 160))
    quant = small.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
    pal = quant.getpalette()[:15]
    counts = sorted(quant.getcolors(), reverse=True)
    palette = [hex_of(pal[i * 3:i * 3 + 3]) for _, i in counts[:5]]
    data = {"top": hex_of(band_average(img, 0, h // 3)),
            "middle": hex_of(band_average(img, h // 3, 2 * h // 3)),
            "bottom": hex_of(band_average(img, 2 * h // 3, h)),
            "palette": palette}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    print(json.dumps(data))


if __name__ == "__main__":
    main()
