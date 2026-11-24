"""
Cut an object out of a ComfyUI picture that was drawn on a flat magenta background -> transparent sprite.
Runs inside tools/voice-venv (needs Pillow):

    python sprite_cut.py <in.png> <out.png> [max_px]   -> prints {"w":..,"h":..,"aspect":..,"coverage":..}

The background is flood-filled from the edges (so pink/purple parts *inside* the object survive), magenta that
shows through holes (handles, wheels) is removed too, the fringe is eroded, then the sprite is cropped and shrunk
to N64 size with a hard alpha edge.
"""
import json
import sys
from collections import deque

from PIL import Image


def is_keyish(c, bg, tol):
    r, g, b = c
    d = abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])
    magenta = r > g + 70 and b > g + 50          # any shade of the magenta/purple backdrop
    return d < tol or (magenta and d < tol * 2.4)


def main(src, dst, max_px=128):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    px = im.load()
    border = [px[x, 0] for x in range(W)] + [px[x, H - 1] for x in range(W)] + \
             [px[0, y] for y in range(H)] + [px[W - 1, y] for y in range(H)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
    tol = 90
    alpha = bytearray([255]) * (W * H)
    q = deque()
    for x in range(W):
        q.append((x, 0)); q.append((x, H - 1))
    for y in range(H):
        q.append((0, y)); q.append((W - 1, y))
    while q:                                     # flood fill the backdrop from the edges
        x, y = q.popleft()
        i = y * W + x
        if not alpha[i] or not is_keyish(px[x, y], bg, tol):
            continue
        alpha[i] = 0
        if x > 0: q.append((x - 1, y))
        if x < W - 1: q.append((x + 1, y))
        if y > 0: q.append((x, y - 1))
        if y < H - 1: q.append((x, y + 1))
    for y in range(H):                           # backdrop seen through holes (between legs, handles)
        for x in range(W):
            i = y * W + x
            if alpha[i]:
                r, g, b = px[x, y]
                if r > g + 110 and b > g + 90 and abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) < tol * 1.3:
                    alpha[i] = 0
    for _ in range(2):                           # eat the pink fringe
        kill = []
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                i = y * W + x
                if alpha[i] and (not alpha[i - 1] or not alpha[i + 1] or not alpha[i - W] or not alpha[i + W]):
                    r, g, b = px[x, y]
                    if r > g + 30 and b > g + 20:
                        kill.append(i)
        for i in kill:
            alpha[i] = 0
    a = Image.frombytes("L", (W, H), bytes(alpha))
    box = a.getbbox()
    if not box:
        print(json.dumps({"error": "nothing left after cutting"}))
        return 1
    rgba = im.convert("RGBA")
    rgba.putalpha(a)
    pad = 2
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(H, box[3] + pad))
    rgba = rgba.crop(box)
    w, h = rgba.size
    f = min(1.0, max_px / max(w, h))
    out = rgba.resize((max(1, round(w * f)), max(1, round(h * f))), Image.LANCZOS)
    al = out.getchannel("A").point(lambda v: 255 if v > 140 else 0)
    out.putalpha(al)
    out.save(dst)
    coverage = sum(1 for v in alpha if v) / float(W * H)
    print(json.dumps({"w": out.size[0], "h": out.size[1], "aspect": round(out.size[0] / out.size[1], 3),
                      "coverage": round(coverage, 3), "touches_edge": box[0] == 0 or box[1] == 0 or box[2] == W or box[3] == H}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 128))
