"""
Hand-built set bases ("Legacy" quality), dressed by the AI - set style A.

Why: the hand-made Legacy Cafe / Park still look better than anything the free AI layout makes. What they have:
one primitive style, a small warm palette (+ matching fog and sun), a layout made for the 9:16 wide shot (the
signature piece at the back, furniture groups in a triangle, lamps hanging into the top of the frame, plants
framing the corners) and a dressed back wall (trim, a framed window, a menu board) - in a vertical shot the back
wall IS the background. Glowing accents (lamps, window, menu lines) give the warmth.

A base is all of that, written by hand once per kind of place (BASES): fixed pieces (wall dressing, lamps,
backdrops) built from simple parts in the base's palette, and named SLOTS (hero, side, furniture groups, corners)
with built-in defaults. For an idea, the AI only picks the base, a palette, the light and what fills each slot
(dress()); a slot thing is one of your imported models (from ONE pack per set, so styles don't clash), a built-in
prop, or a made 3D prop told the palette colours. The layout itself never changes, so the AI can't wreck it.

Coordinates: metres, the camera on the -y side looking at +y; the wide shot sees about |x| < 0.36 * (y + 6).
Wall pieces face -y and stand on the back wall (y = HD). Parts use propgen's format (centre pos, full size).
"""
import json
import math
import random
import re
import time

import catalog
import propgen
import setgen

ROOM = [12.0, 10.0]                 # indoor bases: 12 x 10 m (hw 6, hd 5), walls 5 m tall
HW, HD = ROOM[0] / 2, ROOM[1] / 2


def _shade(h, f):
    h = h.lstrip("#")
    r, g, b = (max(0, min(255, int(int(h[i:i + 2], 16) * f))) for i in (0, 2, 4))
    return f"#{r:02x}{g:02x}{b:02x}"


def box(pos, size, color, glow=False, rot=None):
    d = {"shape": "box", "pos": [round(v, 3) for v in pos], "size": [round(v, 3) for v in size], "color": color}
    if glow:
        d["glow"] = True
    if rot:
        d["rot"] = list(rot)
    return d


def cyl(pos, size, color, glow=False, rot=None):
    return dict(box(pos, size, color, glow, rot), shape="cylinder")


def cone(pos, size, color, glow=False, rot=None):
    return dict(box(pos, size, color, glow, rot), shape="cone")


def ball(pos, size, color, glow=False):
    return dict(box(pos, size, color, glow), shape="sphere")


# --------------------------------------------------------------------------- wall pieces (on the back wall)
# each returns (parts, height); z is from the floor, the piece faces -y, its root sits on the wall
def w_window(p, rng, night=False, w=2.0, h=1.4, z=2.7):
    glass = "#1b2550" if night else p.get("glass", "#bfe6ff")
    fr = p.get("frame", "#ffffff")
    parts = [box((0, 0, z), (w + 0.24, 0.06, h + 0.24), fr),
             box((0, -0.04, z), (w, 0.02, h), glass, glow=True),
             box((0, -0.06, z), (0.06, 0.03, h), fr), box((0, -0.06, z), (w, 0.03, 0.06), fr),
             box((0, -0.12, z - h / 2 - 0.12), (w + 0.4, 0.24, 0.07), fr)]
    if not night:                        # a hill and a cloud outside, like the Legacy Cafe's garden view
        parts += [box((-w * 0.2, -0.05, z - h * 0.3), (w * 0.55, 0.01, h * 0.25), "#8fd18a", glow=True),
                  box((w * 0.22, -0.05, z + h * 0.22), (w * 0.3, 0.01, h * 0.12), "#ffffff", glow=True)]
    return parts, z + h / 2


def w_board(p, rng, night=False, w=2.2, h=1.1, z=2.9, white=False):
    """A menu / chalk / white board with coloured lines (the Legacy Cafe's menu)."""
    face = "#f4f4f0" if white else p.get("board", "#2e3a2e")
    lines = ["#5a8fe0", "#e05a5a", "#3a3a40"] if white else ["#ffd36b", "#ff8fb0", "#9fe0ff"]
    parts = [box((0, 0, z), (w + 0.16, 0.05, h + 0.16), p.get("wood", "#8c5a3c")),
             box((0, -0.03, z), (w, 0.02, h), face)]
    for i, c in enumerate(lines):
        lw = w * (0.72 - i * 0.14)
        parts.append(box((-w * 0.08, -0.045, z + h * 0.3 - i * h * 0.28), (lw, 0.01, 0.09), c, glow=not white))
    return parts, z + h / 2


def w_shelf(p, rng, night=False, w=2.0, z=2.2):
    wood = p.get("wood", "#8c5a3c")
    parts = []
    for k, zz in enumerate((z, z + 0.65)):
        parts += [box((0, -0.16, zz), (w, 0.32, 0.05), wood),
                  box((-w * 0.4, -0.08, zz - 0.12), (0.05, 0.16, 0.2), _shade(wood, 0.8)),
                  box((w * 0.4, -0.08, zz - 0.12), (0.05, 0.16, 0.2), _shade(wood, 0.8))]
        x = -w / 2 + 0.12
        cols = [p["accent"], p.get("accent2", "#5a8fe0"), "#f2c14e", "#ffffff", _shade(p["accent"], 0.7)]
        while x < w / 2 - 0.15:
            if rng.random() < 0.3:          # a jar
                parts.append(cyl((x + 0.08, -0.16, zz + 0.13), (0.15, 0.15, 0.22), rng.choice(cols)))
                x += 0.24
            else:                           # a few books
                for _ in range(rng.randint(2, 4)):
                    bw, bh = rng.uniform(0.05, 0.09), rng.uniform(0.18, 0.3)
                    parts.append(box((x + bw / 2, -0.16, zz + 0.025 + bh / 2), (bw, 0.22, bh), rng.choice(cols)))
                    x += bw + 0.01
                x += 0.12
    return parts, z + 1.0


def w_pictures(p, rng, night=False, z=2.8):
    parts = []
    for x, (pw, ph) in zip((-0.6, 0.55), ((0.8, 1.0), (0.7, 0.55))):
        parts += [box((x, 0, z), (pw + 0.12, 0.04, ph + 0.12), p.get("wood", "#8c5a3c")),
                  box((x, -0.03, z), (pw, 0.01, ph), rng.choice([p["accent"], p.get("accent2", "#9fe0ff"),
                                                                    "#f2d16b", "#bfe6ff"]))]
        parts.append(box((x - pw * 0.1, -0.04, z - ph * 0.15), (pw * 0.5, 0.01, ph * 0.3), "#ffffff"))
    return parts, z + 0.6


def w_clock(p, rng, night=False, z=3.3):
    return [cyl((0, -0.04, z), (0.7, 0.7, 0.08), p.get("wood", "#3a2a22"), rot=(90, 0, 0)),
            cyl((0, -0.09, z), (0.6, 0.6, 0.02), "#fffaf0", glow=True, rot=(90, 0, 0)),
            box((0, -0.11, z + 0.1), (0.04, 0.01, 0.22), "#222222"),
            box((0.08, -0.11, z), (0.18, 0.01, 0.04), "#222222")], z + 0.35


def w_neon(p, rng, night=False, z=3.0):
    c1, c2 = p["accent"], p.get("accent2", "#3ff0ff")
    return [box((0, 0, z), (1.9, 0.04, 0.7), "#120a20"),
            box((0, -0.04, z + 0.15), (1.5, 0.02, 0.08), c1, glow=True),
            box((-0.2, -0.04, z - 0.12), (1.0, 0.02, 0.08), c2, glow=True),
            ball((0.62, -0.05, z - 0.12), (0.18, 0.04, 0.18), c1, glow=True)], z + 0.35


def w_porthole(p, rng, night=False, z=2.7):
    """A big space window: stars and a planet (sci-fi)."""
    parts = [box((0, 0, z), (2.6, 0.06, 1.5), p.get("frame", "#3a4050")),
             box((0, -0.04, z), (2.4, 0.02, 1.3), "#05070f", glow=True),
             ball((0.6, -0.05, z + 0.15), (0.5, 0.02, 0.5), p["accent"], glow=True)]
    for _ in range(14):
        parts.append(box((rng.uniform(-1.1, 1.1), -0.055, z + rng.uniform(-0.55, 0.55)), (0.03, 0.01, 0.03),
                         "#ffffff", glow=True))
    return parts, z + 0.75


def w_banners(p, rng, night=False, z=3.0):
    parts = []
    for x in (-0.7, 0.7):
        parts += [box((x, -0.04, z + 0.85), (0.8, 0.06, 0.06), p.get("wood", "#5a4030")),
                  box((x, -0.06, z), (0.7, 0.02, 1.6), p["accent"]),
                  box((x, -0.07, z + 0.1), (0.3, 0.01, 0.3), p.get("accent2", "#f2c14e"))]
    return parts, z + 0.9


def w_torches(p, rng, night=False, z=2.4):
    parts = []
    for x in (-0.9, 0.9):
        parts += [box((x, -0.1, z), (0.1, 0.2, 0.5), "#3a3030"),
                  cone((x, -0.18, z + 0.4), (0.22, 0.22, 0.35), "#ffb347", glow=True)]
    return parts, z + 0.6


WALL = {"window": w_window, "board": w_board, "whiteboard": lambda p, r, n=False: w_board(p, r, n, white=True),
        "shelf": w_shelf, "pictures": w_pictures, "clock": w_clock, "neon": w_neon, "porthole": w_porthole,
        "banners": w_banners, "torches": w_torches}


# --------------------------------------------------------------------------- ceiling lamps
def lamps(p, style, xs=(-2.6, 0.3, 3.0), y=1.8):
    light = p.get("light", "#ffe9a8")
    parts = []
    for x in xs:
        if style == "pendant":                         # the Legacy Cafe's cone lamps
            parts += [cyl((x, y, 4.62), (0.03, 0.03, 0.8), "#222222"),
                      cone((x, y, 4.1), (0.7, 0.7, 0.45), light, glow=True)]
        elif style == "globe":
            parts += [cyl((x, y, 4.7), (0.03, 0.03, 0.6), "#222222"), ball((x, y, 4.25), (0.5, 0.5, 0.5), light, glow=True)]
        elif style == "bar":                           # office / classroom / lab tube lights
            parts += [box((x, y, 4.85), (1.4, 0.3, 0.08), "#d8dde5"), box((x, y, 4.78), (1.3, 0.22, 0.04), light, glow=True)]
        elif style == "chandelier":
            parts += [cyl((x, y, 4.7), (0.03, 0.03, 0.6), "#3a3030"), cyl((x, y, 4.3), (0.9, 0.9, 0.06), "#3a3030")]
            parts += [cone((x + math.cos(a) * 0.4, y + math.sin(a) * 0.4, 4.42), (0.1, 0.1, 0.2), "#ffb347", glow=True)
                      for a in (0, 2.1, 4.2)]
    return parts


# --------------------------------------------------------------------------- outdoor backdrops
def o_buildings(p, rng):
    """A row of shop fronts across the back of a street (each its own prop)."""
    out, x = [], -10.0
    cols = p.get("buildings", ["#c98a6b", "#e0c08a", "#8fb0c9", "#d9a0a0", "#a8c48f"])
    while x < 10.5:
        w, h = rng.uniform(2.6, 3.6), rng.uniform(4.0, 8.0)
        c = rng.choice(cols)
        parts = [box((0, 0, h / 2), (w, 2.4, h), c), box((0, 0, h + 0.15), (w + 0.2, 2.6, 0.3), _shade(c, 0.75))]
        for k in range(int((h - 2.6) // 1.4)):
            for wx in (-w * 0.25, w * 0.25):
                parts.append(box((wx, -1.22, 2.9 + k * 1.4), (w * 0.28, 0.04, 0.7), "#cfe3f5", glow=True))
        parts += [box((0, -1.22, 1.1), (w * 0.5, 0.05, 2.2), _shade(c, 0.55)),          # door / shop window
                  box((0, -1.4, 2.4), (w * 0.9, 0.4, 0.08), rng.choice([p["accent"], p.get("accent2", "#5a8fe0")]))]
        out.append((parts, (x + w / 2, 11.0 + rng.uniform(-0.4, 0.4)), h, w / 2))
        x += w + rng.uniform(0.05, 0.3)
    return out


def o_sea(p, rng):
    sea = p.get("water", "#3fa9e0")
    parts = [box((0, 0, 0.02), (80, 30, 0.04), sea), box((0, -14.8, 0.05), (80, 0.6, 0.02), "#ffffff", glow=True)]
    for _ in range(8):
        parts.append(box((rng.uniform(-14, 14), rng.uniform(-12, 8), 0.06), (rng.uniform(1, 3), 0.12, 0.01),
                         _shade(sea, 1.25), glow=True))
    return parts


def o_path(p, length=24.0, w=1.6):
    return [box((0, 0, 0.006), (w, length, 0.01), p.get("path", "#c8b08a"))]


# --------------------------------------------------------------------------- the bases
# slot: pos (x, y), rot, default kind (a built-in prop, "" = empty), what it's for (told to the AI), max width
IN_SLOTS = {
    "hero": {"pos": (2.0, 3.7), "w": 2.8, "about": "the big piece that says what the place is (at the back)"},
    "side": {"pos": (-3.4, 4.2), "w": 1.4, "about": "a tall piece against the back wall, left"},
    "group_a": {"pos": (-1.9, 1.0), "w": 1.6, "about": "a furniture group in the middle-left (a table and seats)"},
    "group_b": {"pos": (1.75, -1.5), "w": 1.2, "about": "a smaller thing at the front right, half in the frame"},
    "corner": {"pos": (-2.9, 2.8), "w": 1.0, "about": "a small thing framing the left edge (a plant...)"},
}
OUT_SLOTS = {
    "hero": {"pos": (2.2, 4.2), "w": 3.5, "about": "the big piece that says what the place is"},
    "side": {"pos": (-2.6, 5.0), "w": 2.5, "about": "a second big piece, back left"},
    "group_a": {"pos": (-2.0, 1.2), "w": 2.0, "about": "something to sit at or use, middle left"},
    "group_b": {"pos": (2.4, -0.6), "w": 1.6, "about": "a smaller thing near the front right"},
    "corner": {"pos": (-3.6, 3.2), "w": 1.6, "about": "a tree / post / plant framing the left edge"},
}

BASES = {
    "shop": {
        "name": "Shop", "indoor": True, "floor": "checker", "lamps": "pendant", "ambience": "amb_jazz_clink",
        "words": "cafe coffee shop store bakery diner restaurant bar pub tea bookshop boutique market post office "
                 "bank pharmacy ice cream candy shop toy shop pet shop barber salon florist arcade",
        "walls": ["window", "board"], "seats": "stool",
        "defaults": {"hero": "counter", "side": "bookshelf", "group_a": "table", "group_b": "plant", "corner": "plant"},
        "palettes": {
            "warm cafe": {"floor": ["#d9b38c", "#8c5a3c"], "wall": "#f2d7b5", "trim": "#a0623d", "accent": "#e05a5a",
                          "accent2": "#5a8fe0", "fog": "#e8c9a0", "wood": "#8c5a3c"},
            "mint diner": {"floor": ["#f4f4f0", "#3a3a40"], "wall": "#cdeee2", "trim": "#e05a5a", "accent": "#e05a5a",
                           "accent2": "#3fb8a8", "fog": "#d8efe6", "wood": "#6b4a3a"},
            "pastel sweets": {"floor": ["#ffd6e5", "#f7a8c4"], "wall": "#fff0f5", "trim": "#c96a9a", "accent": "#ff8fb8",
                              "accent2": "#8fe6ff", "fog": "#ffe4ef", "wood": "#b07a5a"},
        }},
    "kitchen": {
        "name": "Kitchen", "indoor": True, "floor": "checker_small", "lamps": "globe", "ambience": "amb_room",
        "words": "kitchen cooking cook chef bakery oven pantry dining breakfast lunch dinner food fridge",
        "walls": ["window", "shelf"], "seats": "chair",
        "defaults": {"hero": "counter", "side": "fridge", "group_a": "table", "group_b": "plant", "corner": "plant"},
        "palettes": {
            "sunny yellow": {"floor": ["#f4f4f0", "#e0b84a"], "wall": "#fff3c4", "trim": "#5a8fe0", "accent": "#e05a5a",
                             "accent2": "#5a8fe0", "fog": "#fff0c8", "wood": "#a0703d"},
            "mint retro": {"floor": ["#ffffff", "#3fb8a8"], "wall": "#d6f2ea", "trim": "#e0603a", "accent": "#e0603a",
                           "accent2": "#3fb8a8", "fog": "#dcf0ea", "wood": "#8c5a3c"},
            "farmhouse": {"floor": ["#c9a27a", "#8c6a4a"], "wall": "#f2ead8", "trim": "#5a7a4a", "accent": "#c94a3a",
                          "accent2": "#e0b84a", "fog": "#efe4cc", "wood": "#7a5a3a"},
        }},
    "bedroom": {
        "name": "Bedroom", "indoor": True, "floor": "planks", "lamps": "globe", "ambience": "amb_room",
        "words": "bedroom bed sleep nap dream bedtime night room kids room nursery dorm hotel room",
        "walls": ["window", "pictures"], "seats": "chair",
        "defaults": {"hero": "bed", "side": "bookshelf", "group_a": "desk_pc", "group_b": "floor_lamp", "corner": "plant"},
        "palettes": {
            "cozy lilac": {"floor": ["#c9a27a", "#b08a62"], "wall": "#e6dcf2", "trim": "#8a6aa8", "accent": "#b48ee0",
                           "accent2": "#ff8fb8", "fog": "#e8e0f0", "wood": "#8c5a3c"},
            "sky blue": {"floor": ["#d9b38c", "#c49a70"], "wall": "#d6ebfa", "trim": "#5a8fe0", "accent": "#5a8fe0",
                         "accent2": "#ffd36b", "fog": "#dcecf8", "wood": "#a0703d"},
            "peach": {"floor": ["#c9a27a", "#a8805a"], "wall": "#ffe1cc", "trim": "#d9805a", "accent": "#ff8f6b",
                      "accent2": "#7fbf7f", "fog": "#ffe6d4", "wood": "#8c5a3c"},
        }},
    "living_room": {
        "name": "Living room", "indoor": True, "floor": "planks", "lamps": "globe", "ambience": "amb_room",
        "words": "living room lounge home house apartment family sofa couch tv movie night party",
        "walls": ["window", "pictures"], "seats": "chair",
        "defaults": {"hero": "sofa", "side": "bookshelf", "group_a": "rug", "group_b": "floor_lamp", "corner": "plant"},
        "palettes": {
            "warm home": {"floor": ["#b08a62", "#9a744e"], "wall": "#f2e2c8", "trim": "#8c5a3c", "accent": "#d9805a",
                          "accent2": "#5a8fe0", "fog": "#efdcc0", "wood": "#7a4a2a"},
            "teal modern": {"floor": ["#d9c2a0", "#c4ab88"], "wall": "#d6ece8", "trim": "#2f7a74", "accent": "#2f9a8a",
                            "accent2": "#f2c14e", "fog": "#d8ecea", "wood": "#8c6a4a"},
            "rose": {"floor": ["#c9a27a", "#b08a62"], "wall": "#f7dcdc", "trim": "#a05a6a", "accent": "#d96a8a",
                     "accent2": "#7fbf9f", "fog": "#f4dede", "wood": "#7a4a3a"},
        }},
    "classroom": {
        "name": "Classroom", "indoor": True, "floor": "checker", "lamps": "bar", "ambience": "amb_room",
        "words": "classroom school class lesson teacher student homework exam library study university lecture "
                 "museum gallery",
        "walls": ["board", "clock"], "seats": "chair",
        "defaults": {"hero": "desk_pc", "side": "bookshelf", "group_a": "school_desk", "group_b": "school_desk",
                     "corner": "plant"},
        "palettes": {
            "school green": {"floor": ["#d9d2c0", "#b8b0a0"], "wall": "#f2efd8", "trim": "#5a7a4a", "accent": "#e0603a",
                             "accent2": "#5a8fe0", "fog": "#eeeadc", "wood": "#8c6a4a", "board": "#2e4a3a"},
            "library brown": {"floor": ["#9a744e", "#7a5a3a"], "wall": "#e8d8bc", "trim": "#6a4a2a", "accent": "#a03a3a",
                              "accent2": "#3a6a8a", "fog": "#e4d4b8", "wood": "#6a4a2a", "board": "#2e3a2e"},
        }},
    "office": {
        "name": "Office / lab", "indoor": True, "floor": "metal", "lamps": "bar", "ambience": "amb_room",
        "words": "office work job desk computer lab laboratory science experiment hospital doctor clinic studio "
                 "company meeting boss bank",
        "walls": ["window", "whiteboard"], "seats": "chair",
        "defaults": {"hero": "desk_pc", "side": "bookshelf", "group_a": "table", "group_b": "plant", "corner": "plant"},
        "palettes": {
            "clean office": {"floor": ["#c8ccd4", "#b0b5be"], "wall": "#eef1f5", "trim": "#5a6a80", "accent": "#3a8fe0",
                             "accent2": "#f2c14e", "fog": "#e8ecf2", "wood": "#8a7a6a"},
            "lab mint": {"floor": ["#e8f0ee", "#c8d8d4"], "wall": "#f4fbfa", "trim": "#3a9a8a", "accent": "#3fd0a8",
                         "accent2": "#b48ee0", "fog": "#e8f4f2", "wood": "#7a8a8a"},
        }},
    "scifi": {
        "name": "Sci-fi room", "indoor": True, "floor": "metal", "lamps": "bar", "ambience": "amb_space",
        "words": "space station spaceship rocket ship alien future robot control room lab cyber moon base mars "
                 "planet galaxy astronaut",
        "walls": ["porthole", "neon"], "seats": "stool",
        "defaults": {"hero": "console", "side": "console", "group_a": "table", "group_b": "crystal", "corner": "crate"},
        "palettes": {
            "deep space": {"floor": ["#3a4050", "#2a2f3a"], "wall": "#4a5266", "trim": "#2a2f3a", "accent": "#3ff0ff",
                           "accent2": "#ff4fd8", "fog": "#2a3048", "wood": "#5a6070", "frame": "#3a4050",
                           "light": "#bff6ff"},
            "white ship": {"floor": ["#d8dde5", "#b8c0cc"], "wall": "#eef2f7", "trim": "#5a6a80", "accent": "#ff8f3a",
                           "accent2": "#3a8fe0", "fog": "#dfe6f0", "wood": "#8a94a4", "frame": "#8a94a4",
                           "light": "#ffffff"},
        }},
    "hall": {
        "name": "Castle / dungeon hall", "indoor": True, "floor": "checker", "lamps": "chandelier",
        "ambience": "amb_spooky",
        "words": "castle dungeon throne king queen knight dragon wizard magic witch haunted ghost spooky cave tomb "
                 "temple palace medieval museum crypt vampire",
        "walls": ["banners", "torches"], "seats": "stool",
        "defaults": {"hero": "@throne", "side": "bookshelf", "group_a": "table", "group_b": "barrel", "corner": "crate"},
        "palettes": {
            "royal stone": {"floor": ["#8a8f99", "#6f7480"], "wall": "#a8a49a", "trim": "#5a5048", "accent": "#a8323a",
                            "accent2": "#f2c14e", "fog": "#8f8a84", "wood": "#5a4030"},
            "haunted purple": {"floor": ["#5a5266", "#463f52"], "wall": "#6e6480", "trim": "#3a3048", "accent": "#7fd17f",
                               "accent2": "#b48ee0", "fog": "#4a4458", "wood": "#3a3030"},
        }},
    "street": {
        "name": "Town street", "indoor": False, "floor": "road", "ambience": "amb_city", "backdrop": "buildings",
        "words": "street city town road downtown sidewalk market square shop fronts traffic bus stop neighborhood "
                 "village alley",
        "defaults": {"hero": "lamppost", "side": "", "group_a": "bench", "group_b": "crate", "corner": "tree"},
        "palettes": {
            "sunny town": {"floor": ["#9a9a92"], "wall": "#e0c08a", "trim": "#7a6a5a", "accent": "#e05a5a",
                           "accent2": "#5a8fe0", "fog": "#bcd8f0",
                           "buildings": ["#d98a6b", "#e8c88a", "#8fb0c9", "#d9a0a0", "#a8c48f", "#f2e2c8"]},
            "dusk city": {"floor": ["#7a7a80"], "wall": "#a89cb0", "trim": "#4a4458", "accent": "#ff8f3a",
                          "accent2": "#b48ee0", "fog": "#c8b0c8",
                          "buildings": ["#8a7a9a", "#a08a8a", "#6a7a9a", "#9a8a7a", "#7a6a8a"]},
        }},
    "park": {
        "name": "Park / garden", "indoor": False, "floor": "grass", "ambience": "amb_birds", "backdrop": "trees",
        "words": "park garden playground picnic farm field meadow lawn backyard yard zoo flowers outside spring "
                 "summer camp",
        "defaults": {"hero": "tree", "side": "tree", "group_a": "bench", "group_b": "bush", "corner": "lamppost"},
        "palettes": {
            "spring green": {"floor": ["#7fbf5a"], "wall": "#7fbf5a", "trim": "#6b4a2a", "accent": "#ff8fb8",
                             "accent2": "#ffd36b", "fog": "#bfe0f5", "path": "#d8c08a"},
            "autumn": {"floor": ["#a8a85a"], "wall": "#a8a85a", "trim": "#6b4a2a", "accent": "#e0703a",
                       "accent2": "#f2c14e", "fog": "#f0d8b8", "path": "#c8a07a"},
        }},
    "beach": {
        "name": "Beach", "indoor": False, "floor": "sand", "ambience": "amb_waves", "backdrop": "sea",
        "words": "beach sea ocean shore island tropical summer holiday vacation surf sand coast pier lagoon",
        "defaults": {"hero": "umbrella", "side": "palm", "group_a": "umbrella", "group_b": "rock", "corner": "palm"},
        "palettes": {
            "tropical": {"floor": ["#f2dca0"], "wall": "#f2dca0", "trim": "#a0703d", "accent": "#ff6b6b",
                         "accent2": "#3fa9e0", "fog": "#bfe6ff", "water": "#3fa9e0"},
            "sunset coast": {"floor": ["#e8c890"], "wall": "#e8c890", "trim": "#8a5a3a", "accent": "#ff8f3a",
                             "accent2": "#b48ee0", "fog": "#ffcfa8", "water": "#4a8fc0"},
        }},
    "forest": {
        "name": "Forest", "indoor": False, "floor": "grass", "ambience": "amb_birds", "backdrop": "pines",
        "words": "forest woods jungle camping campfire trail mountain nature wild cabin lake river snow winter "
                 "christmas fairy mushroom",
        "defaults": {"hero": "rock", "side": "pine", "group_a": "mushroom", "group_b": "bush", "corner": "pine"},
        "palettes": {
            "deep green": {"floor": ["#5a8f4a"], "wall": "#5a8f4a", "trim": "#4a3a2a", "accent": "#e05a5a",
                           "accent2": "#ffd36b", "fog": "#b8d8c0", "path": "#8a6a4a"},
            "snowy": {"floor": ["#f2f6fa"], "wall": "#f2f6fa", "trim": "#5a6a7a", "accent": "#e05a5a",
                      "accent2": "#5a8fe0", "fog": "#e0ecf5", "path": "#c8d4e0", "snowy": True},
        }},
}

def h_throne(p):
    """The castle hall's own centrepiece (no built-in prop says "castle")."""
    gold, red = p.get("accent2", "#f2c14e"), p["accent"]
    return [box((0, 0, 0.12), (2.4, 1.6, 0.24), _shade(p["floor"][0], 0.8)),            # the step
            box((0, 0.1, 0.6), (1.0, 0.8, 0.7), red), box((0, 0.48, 1.5), (1.0, 0.16, 1.9), red),
            box((0, 0.5, 2.55), (1.15, 0.2, 0.2), gold),
            cone((0, 0.5, 2.85), (0.3, 0.3, 0.4), gold),
            box((-0.58, 0.1, 1.0), (0.16, 0.8, 0.12), gold), box((0.58, 0.1, 1.0), (0.16, 0.8, 0.12), gold)], 3.1, 1.2


HANDMADE = {"throne": h_throne}       # "@throne" as a slot default: a base's own piece, built from parts

GROUPS = {   # a slot filled with one of these gets seats around it (the Legacy Cafe's tables + stools)
    "table": [(-0.95, 0.25, 1.3), (0.95, 0.25, -1.3)],
    "school_desk": [],
}


def pick_base(idea, where=None):
    """The base whose words fit the idea best (indoor/outdoor when asked), or None."""
    ws = set(re.findall(r"[a-z]+", str(idea).lower()))
    best, score = None, 0
    for bid, b in BASES.items():
        if where == "inside" and not b["indoor"] or where == "outside" and b["indoor"]:
            continue
        bw = set(b["words"].split())
        sc = len(ws & bw) + 0.5 * sum(1 for w in ws for x in bw if len(w) > 3 and (w in x or x in w) and w != x)
        if sc > score:
            best, score = bid, sc
    return best


# --------------------------------------------------------------------------- the AI dresses a base
DRESS_GUIDE = (
    "You dress a hand-built 3D set for a short cartoon video. The layout is fixed; you choose what fills it. "
    "Reply with JSON only:\n"
    '{"base": "<one base id>", "name": "short set name", "description": "one sentence", "palette": "<one palette '
    'name of that base>", "light": "day|sunset|night", "slots": {"hero": {"kind": "thing_name", "looks": "short '
    'look"}, "side": {...}, "group_a": {...}, "group_b": {...}, "corner": {...}}, "walls": ["<wall piece>", '
    '"<wall piece>"]}\n'
    "Rules: kind is one or two words joined with _ (espresso_machine, cauldron, telescope). Use null for a slot "
    "to keep the base's default thing. Change the hero to the ONE thing that makes this place recognisable; keep "
    "most others as they are or pick things that belong there. No people or animals in slots. walls: two of the "
    "wall pieces listed for that base or from: window, board, whiteboard, shelf, pictures, clock, neon, porthole, "
    "banners, torches (indoor bases only).")


def dress(idea, base_id, ollama, log=print, light=None):
    """The AI's choices for this idea (or {} when it isn't reachable: the base's defaults are used)."""
    import llm
    bases = {bid: {"name": b["name"], "inside": b["indoor"], "palettes": list(b["palettes"]),
                   "defaults": b["defaults"], "walls": b.get("walls", [])} for bid, b in BASES.items()}
    user = (f"Idea: {idea or 'a surprising place'}\nSuggested base: {base_id or 'pick one'}\n"
            + (f"Light: {light}\n" if light else "")
            + "Bases: " + json.dumps(bases) + "\nSlots: "
            + json.dumps({k: v["about"] for k, v in IN_SLOTS.items()}))
    try:
        r = llm.chat_json(ollama["url"], ollama["model"], DRESS_GUIDE, user, 0.7)
        return r if isinstance(r, dict) else {}
    except Exception as exc:
        log(f"[set] the AI couldn't dress the base ({exc.__class__.__name__}) - using its own things")
        return {}


# --------------------------------------------------------------------------- slot things
class _Picker:
    """Resolves slot things: an imported model (only from the first pack used - one style per set), a built-in
    prop, or a made 3D prop told the palette colours."""

    def __init__(self, pal, setting, ollama, log, comfy_cfg):
        self.pal, self.setting, self.ollama, self.log, self.comfy = pal, setting, ollama, log, comfy_cfg
        self.pack = None

    def get(self, kind, looks="", design=True):
        """(prop kind for the recipe, its custom def or None, width) - or (None, None, 0). design=False: only a
        built-in prop or an imported model (the AI's made props are kept for the hero spot)."""
        kind = propgen.slug(kind or "")
        if not kind:
            return None, None, 0.0
        if kind in setgen.PROPS:
            return kind, None, 2 * float(setgen.PROPS[kind] or 0.6)       # PROPS = kind -> radius
        real = propgen.imported_def(kind, looks, self.setting, log=self.log)
        if real and (self.pack is None or real.get("pack") == self.pack or real.get("crowd")):
            self.pack = self.pack or real.get("pack")
            return "imp_" + kind, real, float(real.get("width") or 1.0)
        if real:
            self.log(f"[set] '{kind}': the imported one is from another pack ({real.get('pack')})")
        if not design:
            return None, None, 0.0
        import comfy                     # colour NAMES: the look check marked a prop down for "missing #ffd36b"
        cols = ", ".join(dict.fromkeys(comfy.colour_word(self.pal[k]) for k in ("accent", "accent2", "trim", "wood")
                                       if self.pal.get(k)))
        d = propgen.design(kind, f"{looks or kind.replace('_', ' ')}; colours: {cols}", self.setting, self.ollama,
                           self.log, comfy_cfg=self.comfy, use_imported=False)
        return (kind, d, float(d.get("width") or 2 * float(d.get("radius") or 0.5))) if d else (None, None, 0.0)


def _mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#" + "".join(f"{round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t):02x}" for i in (0, 2, 4))


def _dist(a, b):
    a, b = a.lstrip("#"), b.lstrip("#")
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (0, 2, 4))


def palette_pass(recipe, rng, log=print):
    """Set style B on a free AI layout: one palette (made props' colours pulled 35% toward it), flat colours (no AI
    textures), and inside a dressed back wall (two Legacy-style wall pieces) and hanging lamps. Once per recipe."""
    if recipe.get("dressed") or recipe.get("air"):
        return recipe
    pal = dict(recipe.get("palette") or {})
    pal.setdefault("accent", "#e05a5a")
    pal.setdefault("trim", "#8c5a3c")
    pal.setdefault("floor", ["#d9b38c"])
    pal.update(accent2=pal.get("trim"), wood=pal.get("trim"))
    targets = [c for c in (pal["accent"], pal["trim"], pal.get("wall"), pal["floor"][0]) if isinstance(c, str)
               and re.fullmatch(r"#[0-9a-fA-F]{6}", c)]
    n = 0
    for d in (recipe.get("custom_props") or {}).values():
        if d.get("source") in ("imported", "base") or not d.get("parts"):
            continue
        for part in d["parts"]:
            c = part.get("color")
            if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) and not part.get("glow") and targets:
                part["color"] = _mix(c, min(targets, key=lambda t: _dist(c, t)), 0.35)
                n += 1
    recipe["textures"], recipe["texture_prompts"] = {}, {}
    if recipe.get("indoor"):
        hd = float((recipe.get("room") or ROOM)[1]) / 2
        recipe["props"] = [p for p in recipe["props"] if p["kind"] not in setgen.WALL_PROPS]   # the pieces replace them
        recipe.setdefault("custom_props", {})
        for x, wname in zip((-1.9, 1.9), ("window", rng.choice(["shelf", "pictures", "board", "clock"]))):
            parts, h = WALL[wname](pal, rng, recipe.get("night"))
            _piece(recipe, f"base_{wname}_{'l' if x < 0 else 'r'}", parts, (x, hd - 0.06), h)
        _piece(recipe, "base_lamps", lamps(pal, rng.choice(["pendant", "globe"])), (0.0, 0.0), 5.0)
    recipe["dressed"] = True
    log(f"[set] palette style: {n} colour(s) pulled to the palette, flat colours"
        + (", dressed back wall + lamps" if recipe.get("indoor") else ""))
    return recipe


def _piece(recipe, kind, parts, pos, h, r=0.0, rot=0.0, z=0.0):
    recipe["custom_props"][kind] = {"kind": kind, "name": kind.replace("_", " "), "parts": parts, "exact": True,
                                    "height": round(h, 2), "radius": round(r, 2), "by": "base", "source": "base",
                                    "place": "wall" if r == 0 else "near"}
    recipe["props"].append({"kind": kind, "pos": [round(pos[0], 2), round(pos[1], 2)], "rot": rot, "z": z,
                            "scale": 1.0})


def create(idea="", where=None, light=None, seed=None, name=None, ollama=None, log=print, comfy_cfg=None,
           base_id=None):
    """A new set recipe from a hand-built base (not saved). where: inside / outside / None."""
    seed = seed if seed is not None else random.randrange(10 ** 9)
    rng = random.Random(seed)
    base_id = base_id if base_id in BASES else pick_base(idea, where)
    choice = dress(idea, base_id, ollama, log, light) if ollama else {}
    if choice.get("base") in BASES and (not where or (where == "inside") == BASES[choice["base"]]["indoor"]):
        base_id = base_id or choice["base"]
        if not pick_base(idea, where):         # the words didn't decide: the AI's pick
            base_id = choice["base"]
    base_id = base_id or ("street" if where == "outside" else "shop")
    b = BASES[base_id]
    pname = choice.get("palette") if choice.get("palette") in b["palettes"] else rng.choice(list(b["palettes"]))
    pal = dict(b["palettes"][pname])
    light = light or (choice.get("light") if choice.get("light") in ("day", "sunset", "night") else "day")
    night = light == "night"
    log(f"[set] base: {b['name']} ({base_id}), palette {pname}, {light}")
    title = str(choice.get("name") or name or idea or b["name"]).strip()[:40] or b["name"]
    set_name = name or title.title()
    recipe = {"id": (re.sub(r"[^a-z0-9]+", "_", set_name.lower()).strip("_")[:40] or base_id) + f"_{seed % 10000}",
              "name": set_name, "theme": f"base:{base_id}", "style": "base", "base": base_id,
              "seed": seed, "indoor": b["indoor"], "light": light, "night": night, "snowy": bool(pal.get("snowy")),
              "description": str(choice.get("description") or f"{b['name']} - {idea}")[:200],
              "palette": {k: pal[k] for k in ("floor", "wall", "trim", "accent", "fog") if k in pal}
              | ({"water": pal["water"]} if pal.get("water") else {}),
              "floor": ("snow" if pal.get("snowy") else b["floor"]), "fog": [12.0, 30.0] if b["indoor"] else [16.0, 48.0],
              "props": [], "custom_props": {}, "ambience": b["ambience"], "textures": {}, "particles": [],
              "created": time.time(), "designed_by": "base"}
    if b["indoor"]:
        recipe["room"] = list(ROOM)
    if pal.get("snowy"):
        recipe["particles"] = ["snow"]
    setting = f"{recipe['name']}: {recipe['description']}"
    picker = _Picker(pal, setting, ollama, log, comfy_cfg)
    slots_def = IN_SLOTS if b["indoor"] else OUT_SLOTS
    marks = {"center": [0.0, 0.0], "front": [0.0, -2.5], "left": [-3.0, -0.5], "right": [3.0, -0.5],
             "back": [0.0, 3.0]}

    # fixed pieces: the back wall's two features, lamps / the outdoor backdrop
    if b["indoor"]:
        walls = [w for w in (choice.get("walls") or []) if w in WALL][:2] or list(b["walls"])
        walls = (walls + list(b["walls"]))[:2]
        for x, wname in zip((-1.6, 1.9), walls):
            parts, h = WALL[wname](pal, rng, night)
            _piece(recipe, f"base_{wname}_{'l' if x < 0 else 'r'}", parts, (x, HD - 0.06), h)
        _piece(recipe, "base_lamps", lamps(pal, b["lamps"]), (0.0, 0.0), 5.0)
    else:
        bd = b.get("backdrop")
        if bd == "buildings":
            for i, (parts, pos, h, r) in enumerate(o_buildings(pal, rng)):
                _piece(recipe, f"base_building{i}", parts, pos, h, r)
        elif bd == "sea":
            _piece(recipe, "base_sea", o_sea(pal, rng), (0.0, 22.0), 0.1)
        elif bd in ("trees", "pines"):
            tree = "pine" if bd == "pines" else "tree"
            for i in range(9):
                x = -11 + i * 2.75 + rng.uniform(-0.5, 0.5)
                recipe["props"].append({"kind": tree if rng.random() < 0.75 else "bush", "pos": [round(x, 2),
                                        round(10.5 + rng.uniform(-1, 1.5), 2)], "rot": 0.0, "z": 0.0,
                                        "scale": round(rng.uniform(1.1, 1.6), 2)})
            recipe["props"].append({"kind": "hill", "pos": [-6.0, 18.0], "rot": 0.0, "z": 0.0, "scale": 9.0})
            recipe["props"].append({"kind": "hill", "pos": [7.0, 20.0], "rot": 0.0, "z": 0.0, "scale": 11.0})
        if base_id in ("park", "forest"):
            _piece(recipe, "base_path", o_path(pal), (0.0, 2.0), 0.02)

    # the slots: the AI's thing or the base's default, scaled to fit its place
    slots = choice.get("slots") if isinstance(choice.get("slots"), dict) else {}
    for sid, sd in slots_def.items():
        want = slots.get(sid) if isinstance(slots.get(sid), dict) else None
        kind = (want or {}).get("kind") or b["defaults"].get(sid) or ""
        looks = (want or {}).get("looks") or ""
        if kind.startswith("@") and kind[1:] in HANDMADE:          # the base's own hand-made piece
            parts, h, r = HANDMADE[kind[1:]](pal)
            _piece(recipe, f"base_{kind[1:]}", parts, sd["pos"], h, r)
            marks[kind[1:]] = [sd["pos"][0], round(sd["pos"][1] - r - 0.7, 2)]
            continue
        default = b["defaults"].get(sid) or ""
        if want and default and not default.startswith("@") and \
                propgen.slug(kind).split("_")[-1] == default.split("_")[-1]:
            kind, looks = default, ""            # a "cloud_bed" is still a bed: the hand-built one (it scored 4/10)
        k, d, width = picker.get(kind, looks, design=(sid == "hero"))
        if not k and want:                       # the AI's thing couldn't be made: the default
            k, d, width = picker.get(b["defaults"].get(sid) or "", "")
        if not k:
            continue
        if d:
            recipe["custom_props"][k] = d
        x, y = sd["pos"]
        scale = round(min(1.0, sd["w"] / max(0.2, width)), 2) if width else 1.0
        recipe["props"].append({"kind": k, "pos": [x, y], "rot": 0.0, "z": 0.0, "scale": scale})
        base_kind = k[4:] if k.startswith("imp_") else k
        if base_kind in GROUPS and b.get("seats"):                  # a table gets its seats
            for dx, dy, rot in GROUPS[base_kind]:
                recipe["props"].append({"kind": b["seats"], "pos": [round(x + dx, 2), round(y + dy, 2)],
                                        "rot": rot, "z": 0.0, "scale": 1.0})
        if base_kind == "school_desk":                              # a second desk behind it: a class
            recipe["props"].append({"kind": k, "pos": [x + 0.2, y + 1.6], "rot": 0.0, "z": 0.0, "scale": scale})
        if sid in ("hero", "side", "group_a") and base_kind not in ("rug", "hill") and len(marks) < 9:
            mark = base_kind.replace("_pc", "")
            if mark not in marks:
                marks[mark] = [round(x, 2), round(y - min(1.6, width * scale / 2 + 0.7), 2)]
        log(f"[set] {sid}: {k}" + (f" ({d.get('name')})" if d and d.get("source") == "imported" else ""))
    if b["indoor"] and not any(p["kind"] == "rug" for p in recipe["props"]):
        # the lower part of the frame was bare floor: a rug in the middle (flat, she walks over it)
        recipe["props"].append({"kind": "rug", "pos": [0.0, 0.6], "rot": 0.0, "z": 0.0, "scale": 1.1})
    if b["indoor"]:                              # the right corner mirrors the left one, like the Legacy Cafe's plants
        rk = b["defaults"].get("corner") or "plant"
        if rk in setgen.PROPS:
            recipe["props"].append({"kind": rk, "pos": [3.9, 4.4], "rot": 0.0, "z": 0.0, "scale": 1.0})
    recipe["marks"] = marks
    return recipe
