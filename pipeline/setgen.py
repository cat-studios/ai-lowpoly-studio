"""
Random set generator. A set is a small JSON "recipe" (sets/<id>.json): floor, walls, colours, fog and
a list of props with positions. Blender builds any recipe from a library of low-poly props, so new
sets cost nothing to make. Marks (places the character can walk to) are generated with the layout,
which is what the "Starts at" / "walk_to" dropdowns use.
"""
import json
import math
import random
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS_DIR = ROOT / "sets"

# footprint radius of each prop (metres) - used to keep props apart and off the walkway
PROPS = {
    "table": 0.8, "chair": 0.35, "stool": 0.3, "bed": 1.3, "desk_pc": 0.9, "bookshelf": 0.6, "plant": 0.45,
    "floor_lamp": 0.3, "sofa": 1.1, "rug": 0.0, "counter": 1.6, "fridge": 0.5, "tv": 0.8, "arcade": 0.5,
    "crate": 0.5, "barrel": 0.45, "tree": 1.2, "pine": 1.1, "palm": 1.0, "rock": 0.8, "bush": 0.7,
    "mushroom": 0.5, "bench": 0.9, "lamppost": 0.3, "tombstone": 0.4, "dead_tree": 0.9, "cactus": 0.5,
    "snowman": 0.6, "umbrella": 1.0, "building": 3.5, "console": 0.8, "lollipop": 0.5, "gumdrop": 0.6,
    "school_desk": 0.6, "crystal": 0.6, "hill": 0.0, "water": 0.0, "poster": 0.0, "window": 0.0,
    "chalkboard": 0.0, "neon_sign": 0.0, "star_window": 0.0, "fence": 0.0, "balloons": 0.4,
}
WALL_PROPS = {"poster", "window", "chalkboard", "neon_sign", "star_window"}

THEMES = {
    "cafe": {
        "names": (["Cosy", "Little", "Sunny"], ["Cafe", "Coffee Shop", "Bakery"]),
        "indoor": True, "room": "large",
        "description": "A cosy cafe with a counter, small tables with chairs and a window",
        "palettes": [
            {"floor": ["#d9b38c", "#8c5a3c"], "wall": "#f2d7b5", "trim": "#a0623d", "accent": "#ff8fb8", "fog": "#e8c9a0"},
            {"floor": ["#b89a7a", "#7a5a40"], "wall": "#f5e6cc", "trim": "#6b4a32", "accent": "#7fb7d9", "fog": "#f0e0c8"},
        ],
        "floor": "checker", "props": [("counter", 1, 1, "wall_back"), ("table", 2, 3, "center"), ("chair", 4, 6, "scatter"),
                                      ("plant", 2, 2, "corner"), ("window", 1, 1, "hang_left"), ("poster", 1, 1, "hang_back"),
                                      ("floor_lamp", 1, 1, "corner")],
        "marks": ["table", "counter"], "light": "day",
        "textures": {"poster": "vintage cafe menu poster, flat illustration, pastel colours"},
    },
    "park": {
        "names": (["Sunny", "Quiet", "Green"], ["Park", "Garden", "Meadow"]),
        "indoor": False, "room": None,
        "description": "A sunny park with grass, trees, a bench and a lamppost",
        "palettes": [
            {"floor": ["#7fbf5a", "#6aa84a"], "wall": "#ffffff", "trim": "#ffffff", "accent": "#ffd23a", "fog": "#cfe9ff"},
        ],
        "floor": "grass", "props": [("tree", 2, 3, "far"), ("pine", 1, 2, "far"), ("bench", 1, 2, "near"),
                                    ("lamppost", 1, 2, "near"), ("bush", 2, 4, "near"), ("rock", 1, 2, "scatter"),
                                    ("plant", 1, 2, "near")],
        "marks": ["bench", "tree"], "light": "day", "textures": {},
    },
    "bedroom": {
        "names": (["Cozy", "Messy", "Pastel", "Tiny", "Gamer"], ["Bedroom", "Room", "Hideout"]),
        "indoor": True, "description": "A bedroom with a bed, a desk with a computer and shelves",
        "palettes": [
            {"floor": ["#c89f7a", "#b08463"], "wall": "#f3d9e6", "trim": "#ffffff", "accent": "#ff8fb8", "fog": "#f6e1ea"},
            {"floor": ["#9aa7c7", "#8693b3"], "wall": "#dfe6ff", "trim": "#b7c4ee", "accent": "#7aa2ff", "fog": "#e5ebff"},
            {"floor": ["#a7c4a0", "#93b08c"], "wall": "#fff3d6", "trim": "#e8cf9f", "accent": "#7fd18a", "fog": "#fff4dc"},
        ],
        "floor": "planks", "props": [("bed", 1, 1, "wall_back"), ("desk_pc", 1, 1, "wall_left"), ("bookshelf", 1, 2, "wall_back"),
                                     ("plant", 1, 2, "corner"), ("rug", 1, 1, "center"), ("floor_lamp", 0, 1, "corner"),
                                     ("poster", 1, 3, "hang_back"), ("window", 1, 1, "hang_left")],
        "marks": ["bed", "desk_pc"], "light": "day", "textures": {"poster": "cute retro anime poster, pastel colors, flat illustration"},
    },
    "classroom": {
        "names": (["Sunny", "Empty", "After-School", "Old"], ["Classroom", "Homeroom"]),
        "indoor": True, "description": "A school classroom with desks and a chalkboard",
        "palettes": [{"floor": ["#c9b08a", "#b89c76"], "wall": "#e9efe0", "trim": "#8fa585", "accent": "#e0c060", "fog": "#eef2e6"}],
        "floor": "planks", "props": [("school_desk", 6, 9, "grid"), ("chalkboard", 1, 1, "hang_back"), ("window", 2, 3, "hang_left"),
                                     ("bookshelf", 1, 1, "wall_back"), ("plant", 0, 1, "corner")],
        "marks": ["chalkboard"], "light": "day", "textures": {"chalkboard": "chalk drawing on a green chalkboard, doodles"},
    },
    "arcade": {
        "names": (["Neon", "Midnight", "Retro", "Pixel"], ["Arcade", "Game Center"]),
        "indoor": True, "description": "A dark arcade full of glowing game cabinets",
        "palettes": [{"floor": ["#2a2147", "#1b1533"], "wall": "#231a3a", "trim": "#ff3fa4", "accent": "#3ff0ff", "fog": "#180f2b"},
                     {"floor": ["#1f2b44", "#141c30"], "wall": "#18213a", "trim": "#ffe03f", "accent": "#ff4fd8", "fog": "#0f1426"}],
        "floor": "checker", "props": [("arcade", 6, 10, "wall_back"), ("arcade", 3, 5, "wall_left"), ("neon_sign", 1, 2, "hang_back"),
                                      ("stool", 2, 4, "scatter")],
        "marks": ["arcade"], "light": "night", "textures": {"neon_sign": "glowing neon sign, retro arcade logo, dark background"},
    },
    "kitchen": {
        "names": (["Sunny", "Grandma's", "Tiny", "Chaotic"], ["Kitchen"]),
        "indoor": True, "description": "A home kitchen with counters, a fridge and a table",
        "palettes": [{"floor": ["#f2f2f2", "#d24d4d"], "wall": "#fff7e0", "trim": "#7fbfdf", "accent": "#ffb347", "fog": "#fff6e4"},
                     {"floor": ["#e6e6e6", "#4d7fd2"], "wall": "#eaf6ff", "trim": "#f2c14e", "accent": "#7fd18a", "fog": "#eef7ff"}],
        "floor": "checker_small", "props": [("counter", 1, 1, "wall_back"), ("fridge", 1, 1, "wall_left"), ("table", 1, 1, "scatter"),
                                            ("chair", 2, 3, "scatter"), ("plant", 0, 1, "corner"), ("window", 1, 1, "hang_back")],
        "marks": ["counter", "fridge", "table"], "light": "day", "textures": {},
    },
    "living_room": {
        "names": (["Comfy", "Lazy Sunday", "Retro"], ["Living Room", "Lounge"]),
        "indoor": True, "description": "A living room with a sofa, a TV and a rug",
        "palettes": [{"floor": ["#a67c52", "#8f6843"], "wall": "#efe2cf", "trim": "#c9a27a", "accent": "#e07a5f", "fog": "#f1e6d6"}],
        "floor": "planks", "props": [("sofa", 1, 1, "wall_back"), ("tv", 1, 1, "wall_left"), ("rug", 1, 1, "center"),
                                     ("plant", 1, 2, "corner"), ("floor_lamp", 1, 1, "corner"), ("poster", 1, 2, "hang_back"),
                                     ("bookshelf", 0, 1, "wall_back")],
        "marks": ["sofa", "tv"], "light": "day", "textures": {"poster": "framed landscape painting, retro, soft colors"},
    },
    "forest": {
        "names": (["Misty", "Enchanted", "Quiet", "Mossy"], ["Forest", "Woods", "Clearing"]),
        "indoor": False, "description": "A forest clearing with pines, rocks and mushrooms",
        "palettes": [{"floor": ["#4f9a46"], "accent": "#e0574c", "fog": "#bcd9c3", "sky": "#bcd9c3"},
                     {"floor": ["#3f7f50"], "accent": "#f2c14e", "fog": "#a7c8d8", "sky": "#a7c8d8"}],
        "floor": "grass", "props": [("pine", 20, 30, "far"), ("tree", 4, 8, "ring"), ("rock", 3, 6, "ring"), ("bush", 4, 8, "ring"),
                                    ("mushroom", 3, 6, "scatter"), ("hill", 3, 4, "horizon")],
        "marks": ["tree", "rock", "mushroom"], "light": "day", "textures": {},
    },
    "beach": {
        "names": (["Sunny", "Tropical", "Sunset", "Secret"], ["Beach", "Shore", "Island"]),
        "indoor": False, "description": "A sandy beach with palm trees, an umbrella and the sea",
        "palettes": [{"floor": ["#f2d9a2"], "accent": "#ff6b6b", "fog": "#9fd8ff", "sky": "#9fd8ff", "water": "#3fa9e0"},
                     {"floor": ["#f0c98c"], "accent": "#ffb347", "fog": "#ffc49a", "sky": "#ffc49a", "water": "#e07a8f"}],
        "floor": "sand", "props": [("water", 1, 1, "sea"), ("palm", 4, 7, "ring"), ("umbrella", 1, 2, "scatter"), ("rock", 2, 4, "ring"),
                                   ("palm", 6, 10, "far")],
        "marks": ["umbrella", "palm", "water"], "light": "day", "textures": {},
    },
    "snow": {
        "names": (["Frosty", "Snowy", "Winter", "Silent"], ["Field", "Hills", "Village"]),
        "indoor": False, "description": "A snowy field with snowy pines and a snowman",
        "palettes": [{"floor": ["#f4f8ff"], "accent": "#e0574c", "fog": "#dfe9f5", "sky": "#dfe9f5"}],
        "floor": "snow", "props": [("pine", 18, 28, "far"), ("snowman", 1, 2, "scatter"), ("rock", 2, 4, "ring"), ("pine", 3, 5, "ring"),
                                   ("hill", 3, 4, "horizon")],
        "marks": ["snowman", "pine"], "light": "day", "textures": {},
    },
    "city": {
        "names": (["Downtown", "Night", "Rainy", "Neon"], ["Street", "City", "Rooftop"]),
        "indoor": False, "description": "A city street with tall buildings, lampposts and crates",
        "palettes": [{"floor": ["#55585f"], "accent": "#ffd36b", "fog": "#b6bfd0", "sky": "#b6bfd0"},
                     {"floor": ["#2d2f38"], "accent": "#ff4fd8", "fog": "#221c3a", "sky": "#221c3a", "night": True}],
        "floor": "road", "props": [("building", 8, 12, "city_block"), ("lamppost", 3, 5, "ring"), ("crate", 2, 5, "scatter"),
                                   ("barrel", 1, 3, "scatter"), ("bench", 0, 1, "ring")],
        "marks": ["lamppost", "crate", "bench"], "light": "day", "textures": {},
    },
    "desert": {
        "names": (["Dusty", "Endless", "Sunbaked"], ["Desert", "Canyon", "Dunes"]),
        "indoor": False, "description": "A hot desert with cacti, rocks and mesas",
        "palettes": [{"floor": ["#e8b77a"], "accent": "#5fa35f", "fog": "#f6d7a8", "sky": "#f6d7a8"}],
        "floor": "sand", "props": [("cactus", 6, 10, "ring"), ("rock", 4, 8, "ring"), ("hill", 4, 6, "horizon"), ("cactus", 8, 12, "far")],
        "marks": ["cactus", "rock"], "light": "day", "textures": {},
    },
    "space_station": {
        "names": (["Orbital", "Abandoned", "Deep Space"], ["Station", "Lab", "Bridge"]),
        "indoor": True, "description": "A space station with control consoles and windows to the stars",
        "palettes": [{"floor": ["#5d6475", "#4a5060"], "wall": "#7b8396", "trim": "#3ff0ff", "accent": "#ff4f6d", "fog": "#0b0e1a"}],
        "floor": "metal", "props": [("console", 2, 4, "wall_back"), ("console", 1, 2, "wall_left"), ("star_window", 2, 3, "hang_back"),
                                    ("crate", 1, 3, "corner"), ("crystal", 0, 2, "scatter")],
        "marks": ["console"], "light": "night", "textures": {"star_window": "view of a planet and stars from space, pixel art"},
    },
    "graveyard": {
        "names": (["Spooky", "Foggy", "Haunted", "Midnight"], ["Graveyard", "Cemetery"]),
        "indoor": False, "description": "A foggy graveyard with tombstones and dead trees",
        "palettes": [{"floor": ["#3b4a3a"], "accent": "#9f7fff", "fog": "#4a5370", "sky": "#4a5370", "night": True}],
        "floor": "grass", "props": [("tombstone", 8, 14, "ring"), ("dead_tree", 4, 7, "ring"), ("dead_tree", 10, 16, "far"),
                                    ("fence", 1, 1, "perimeter"), ("lamppost", 1, 2, "ring")],
        "marks": ["tombstone", "dead_tree"], "light": "night", "textures": {},
    },
    "candyland": {
        "names": (["Sugar", "Candy", "Sweet", "Bubblegum"], ["Land", "Kingdom", "Meadow"]),
        "indoor": False, "description": "A pastel candy world with giant lollipops and gumdrops",
        "palettes": [{"floor": ["#ffc6e0"], "accent": "#7fe0ff", "fog": "#ffe3f1", "sky": "#ffe3f1"},
                     {"floor": ["#c6f0d0"], "accent": "#ff8fb8", "fog": "#e8f7ff", "sky": "#e8f7ff"}],
        "floor": "grass", "props": [("lollipop", 6, 10, "ring"), ("gumdrop", 6, 10, "ring"), ("lollipop", 10, 16, "far"),
                                    ("hill", 3, 5, "horizon")],
        "marks": ["lollipop", "gumdrop"], "light": "day", "textures": {},
    },
}

ROOM_W, ROOM_D = 14.0, 12.0          # indoor room: x -7..7, y -6..6 (back wall at +y, left wall at -x)
# room sizes an indoor scene can have (metres): a bathroom is small, a hall is big
ROOM_SIZES = {"small": (7.0, 6.0), "medium": (10.0, 9.0), "large": (14.0, 12.0)}


def set_room(size):
    """Use the room size for the set being made (small / medium / large; anything else = large)."""
    global ROOM_W, ROOM_D
    ROOM_W, ROOM_D = ROOM_SIZES.get(str(size or "").lower(), ROOM_SIZES["large"])
    return ROOM_W, ROOM_D
CLEAR = [(0, 0, 2.2), (0, -2.5, 1.2)]  # keep the stage free: (x, y, radius)


CUSTOM_R = {}     # footprint radius of AI-made props used by the set being generated (propgen)
CUSTOM_S = {}     # ...and the scale that makes them fit (big designs are shrunk, more so indoors)


def _radius(kind):
    return PROPS.get(kind, CUSTOM_R.get(kind, 0.5))


def _blocked_by_liquid(x, y, r, p):
    sh = p.get("shape")
    if sh == "pool":
        return math.hypot(x - p["pos"][0], y - p["pos"][1]) < p["r"] + r + 0.2
    if sh == "river":
        return abs(y - p["pos"][1]) < p["r"] + r + 0.2
    if sh == "sea":
        return y > 7.0 - r
    return False


def _free(x, y, r, placed, clear=True):
    if clear and any(math.hypot(x - cx, y - cy) < cr + r for cx, cy, cr in CLEAR):
        return False
    for p in placed:
        if p["kind"] == "liquid":
            if _blocked_by_liquid(x, y, r, p):
                return False
        elif _radius(p["kind"]) > 0 and math.hypot(x - p["pos"][0], y - p["pos"][1]) < r + _radius(p["kind"]) + 0.15:
            return False
    return True


def _place(rng, kind, zone, placed, indoor):
    """A spot for `kind` in `zone`. A zone like "far@left" (from a picture) only takes spots on that side."""
    if "@" in zone:
        base, side = zone.split("@", 1)
        for _ in range(40):
            p = _place_zone(rng, kind, base, placed, indoor)
            if p and (p["pos"][0] < 0) == (side == "left"):
                return p
        return _place_zone(rng, kind, base, placed, indoor)     # nothing fits on that side: anywhere in the zone
    return _place_zone(rng, kind, zone, placed, indoor)


def _place_zone(rng, kind, zone, placed, indoor):
    r = _radius(kind)
    hw, hd = ROOM_W / 2, ROOM_D / 2
    for _ in range(80):
        rot, z = 0.0, 0.0
        if zone == "wall_back":
            x, y = rng.uniform(-hw + r + 0.3, hw - r - 0.3), hd - max(r, 0.4) - 0.1
        elif zone == "wall_left":
            x, y, rot = -hw + max(r, 0.4) + 0.1, rng.uniform(-hd + r + 1.5, hd - r - 0.5), math.pi / 2
        elif zone == "corner":
            x, y = rng.choice([(-hw + 0.8, hd - 0.8), (hw - 0.8, hd - 0.8), (-hw + 0.8, -hd + 1.5)])
            x, y = x + rng.uniform(-0.2, 0.2), y + rng.uniform(-0.2, 0.2)
        elif zone == "grid":     # rows of desks either side of the stage, facing the camera side
            slots = [(-5.2, 4.0), (-3.2, 4.0), (3.2, 4.0), (5.2, 4.0), (-5.2, 2.0), (-3.4, 2.0), (3.4, 2.0),
                     (5.2, 2.0), (-5.2, 0.0), (5.2, 0.0)]
            i = sum(1 for p in placed if p["kind"] == kind)
            if i >= len(slots):
                return None
            x, y = slots[i]
            return {"kind": kind, "pos": [x, y], "rot": 0.0, "scale": 1.0}
        elif zone in ("hang_back", "hang_left"):
            if zone == "hang_back":
                x, y, rot = rng.uniform(-hw + 1.2, hw - 1.2), hd - 0.03, 0.0
            else:
                x, y, rot = -hw + 0.03, rng.uniform(-hd + 2, hd - 1.5), math.pi / 2
            z = rng.uniform(2.2, 2.8)
            near = [p for p in placed if p["kind"] in WALL_PROPS and abs(p["rot"] - rot) < 0.1]
            if any(math.hypot(x - p["pos"][0], y - p["pos"][1]) < 2.4 for p in near):
                continue
            return {"kind": kind, "pos": [round(x, 2), round(y, 2)], "rot": rot, "z": round(z, 2), "scale": 1.0}
        elif zone == "center":         # the middle of the room first, then around it - never on top of another
            for x, y in ((0.0, 0.3), (-2.2, 0.6), (2.2, 0.6), (-2.2, 2.6), (2.2, 2.6), (0.0, 2.8)):
                if _radius(kind) <= 0 or _free(x, y, r, placed, clear=False):
                    return {"kind": kind, "pos": [x, y], "rot": 0.0, "scale": 1.0}
            return None
        elif zone == "showcase":   # in shot: beside / behind the stage, facing the camera
            side = rng.choice([-1, 1])      # the wide camera sees about |x| < 0.36 * (y + 6) (9:16, 28 mm)
            y = rng.uniform(1.5, 4.8) if indoor else rng.uniform(2.5, 7.5)
            if indoor:                      # a small room's back wall is at y = 3: stay inside it
                y = min(y, hd - r - 0.3)
            x = side * rng.uniform(0.4, 0.9) * 0.36 * (y + 6)
            if indoor:
                x = max(-hw + r + 0.2, min(hw - r - 0.2, x))
            rot = rng.uniform(-0.5, 0.5)
        elif zone == "view":       # anywhere the wide shot sees, behind the stage too (fill_view)
            y = rng.uniform(0.5, hd - r - 0.3) if indoor else rng.uniform(1.0, 12.0)
            x = rng.uniform(-0.95, 0.95) * 0.36 * (y + 6)
            if indoor:
                x = max(-hw + r + 0.2, min(hw - r - 0.2, x))
            if abs(x) < 1.1 + r and y < 3.8:   # keep the space just behind her open (the "back" mark)
                continue
            rot = rng.uniform(-0.6, 0.6)
        elif zone == "scatter":
            lim = (hw - 1, hd - 1) if indoor else (7, 7)
            x, y = rng.uniform(-lim[0], lim[0]), rng.uniform(-lim[1] + 1, lim[1])
            rot = rng.uniform(0, math.tau)
        elif zone == "ring":
            a, d = rng.uniform(0, math.tau), rng.uniform(4.0, 10.0)
            x, y, rot = math.cos(a) * d, math.sin(a) * d + 2, rng.uniform(0, math.tau)
            if y < -3:      # keep the space between the camera and the stage open
                continue
        elif zone == "far":
            a, d = rng.uniform(0, math.tau), rng.uniform(11, 32)
            x, y, rot = math.cos(a) * d, math.sin(a) * d + 6, rng.uniform(0, math.tau)
            if y < -4 and abs(x) < 12:
                continue
        elif zone == "horizon":
            a = rng.uniform(math.radians(20), math.radians(160))
            d = rng.uniform(30, 45)
            return {"kind": kind, "pos": [round(math.cos(a) * d, 1), round(math.sin(a) * d, 1)], "rot": 0.0,
                    "scale": round(rng.uniform(6, 11), 1)}
        elif zone == "sea":
            return {"kind": kind, "pos": [0.0, 16.0], "rot": 0.0, "scale": 1.0}
        elif zone == "perimeter":
            return {"kind": kind, "pos": [0.0, 0.0], "rot": 0.0, "scale": 1.0}
        elif zone == "city_block":
            side = rng.choice([-1, 1, 0])
            if side == 0:
                x, y = rng.uniform(-14, 14), rng.uniform(13, 20)
            else:
                x, y = side * rng.uniform(9, 14), rng.uniform(-6, 18)
            rot = 0.0
            if not _free(x, y, 2.6, placed, clear=False):
                continue
            return {"kind": kind, "pos": [round(x, 2), round(y, 2)], "rot": 0.0, "scale": round(rng.uniform(0.8, 1.4), 2)}
        else:
            raise ValueError(zone)
        if _free(x, y, r, placed, clear=zone not in ("far",)):
            s = rng.uniform(0.85, 1.2) if zone in ("ring", "far", "scatter", "showcase") else 1.0
            return {"kind": kind, "pos": [round(x, 2), round(y, 2)], "rot": round(rot, 3), "z": z,
                    "scale": round(s * CUSTOM_S.get(kind, 1.0), 2)}
    return None


NOT_DRESSING = {"liquid", "hill", "rug", "fence", "water", "building"} | WALL_PROPS


def in_view(x, y, margin=0.0):
    """Is a floor spot inside the 9:16 wide shot (camera 6 m in front of the stage, 28 mm)?"""
    return y > -1.5 and abs(x) < 0.36 * (y + 6) + margin


def view_count(placed):
    """How many real things (not rugs, fences, hills, wall pictures) the wide shot sees."""
    return sum(1 for p in placed if p["kind"] not in NOT_DRESSING and in_view(*p["pos"][:2]))


FILL_IN, FILL_OUT = 9, 11        # things the wide shot should see; sets had 4-7 (a big empty room round her)
# things a place has several of - copied to fill the view. One-off things (a barn door, a flagpole, the AI's
# signature prop) are only copied when the set already has two or more of them.
DRESSING = re.compile(r"(chair|stool|seat|bench|plant|flower|pot|vase|crate|box|barrel|sack|bag|basket|bale|book|"
                      r"stack|pile|lamp|lantern|candle|rock|stone|bush|shrub|tree|pine|palm|mushroom|cactus|table|"
                      r"desk|shelf|cart|cone|bin|bucket|jar|bottle|cushion|pillow|toy|ball|sign|post|log|stump|"
                      r"fern|grass|reed|coral|shell|crystal|gumdrop|lollipop|tombstone|grave|statue|pillar|column)s?$")


TALL_SINGLES = re.compile(r"(lamp|lantern|pillar|column|statue|shelf|cabinet|clock|ladder)")   # at most 2 of each
ONE_OFF = re.compile(r"(door|gate|portal|entrance|arch|flag|banner|altar|throne|counter|stage|sign_?board)")


def fill_view(rng, placed, indoor, log=print, target=None):
    """Fuller sets: add more of the set's own things (never new kinds - they'd break the theme) where the wide
    shot sees them, until it shows `target` things. Big furniture is left alone (one sofa is enough); small things
    (chairs, plants, crates, the AI's props) are copied, the least-copied first. Returns how many were added."""
    target = target or (FILL_IN if indoor else FILL_OUT)
    have = view_count(placed)
    if have >= target:
        return 0
    counts = {}
    for p in placed:
        if p["kind"] not in NOT_DRESSING and p["kind"].removeprefix("imp_") not in INDOOR_BIG and not p.get("z") \
                and 0 < _radius(p["kind"]) <= (1.2 if indoor else 2.0):
            counts[p["kind"]] = counts.get(p["kind"], 0) + 1
    counts = {k: n for k, n in counts.items() if (n >= 2 or DRESSING.search(k.removeprefix("imp_")))
              and not ONE_OFF.search(k)}
    if not counts:
        return 0
    added, fails = 0, 0
    # how many of one thing a set may have: a row of 5 identical floor lamps read as odd poles in a bedroom
    limit = lambda k: 2 if TALL_SINGLES.search(k) else (4 if indoor else 6)
    while have + added < target and fails < 24:
        open_kinds = [k for k in counts if counts[k] < limit(k)]
        if not open_kinds:
            break
        kind = min(open_kinds, key=lambda k: (counts[k] + rng.random() * 0.9))
        q = _place(rng, kind, rng.choice(["showcase", "view"]), placed, indoor)
        if q and in_view(*q["pos"]):
            placed.append(q)
            counts[kind] += 1
            added += 1
        else:
            fails += 1
            counts[kind] += 0.5                 # no room for this one: try the others first
    if added:
        log(f"[set] filled the view: +{added} ({have} -> {have + added} things in the wide shot)")
    return added


def _mark_near(prop):
    """A walkable point in front of a prop (towards the stage centre)."""
    x, y = prop["pos"]
    if prop["kind"] == "water" or prop.get("shape") == "sea":           # the shoreline, not the sea
        return [0.0, 6.2]
    if prop.get("shape") == "river":
        return [0.0, round(y - prop["r"] - 0.6, 2)]
    d = math.hypot(x, y) or 1.0
    step = (prop["r"] + 0.6) if prop["kind"] == "liquid" else _radius(prop["kind"]) + 0.7
    if prop["kind"] in WALL_PROPS:
        step = 1.3
    nx, ny = x - x / d * step, y - y / d * step
    if prop["kind"] in WALL_PROPS and prop["rot"] == 0.0:
        nx, ny = x, y - step
    return [round(nx, 2), round(ny, 2)]


# --------------------------------------------------------------------------- fully random sets
# No themes, no templates: every choice (inside/outside, light, colours, floor, which props, how many,
# where, the name) is rolled fresh, so each set is a new combination.
import colorsys  # noqa: E402

INDOOR_BIG = ["bed", "desk_pc", "bookshelf", "sofa", "counter", "fridge", "tv", "arcade", "console"]
INDOOR_SMALL = ["table", "chair", "stool", "plant", "floor_lamp", "crate", "barrel", "school_desk", "crystal",
                "gumdrop", "mushroom", "snowman", "rock", "bush", "cactus", "umbrella", "lollipop"]
WALL_HANGS = ["poster", "window", "chalkboard", "neon_sign", "star_window"]
OUT_FAR = ["pine", "tree", "palm", "dead_tree", "lollipop", "cactus", "crystal"]
OUT_NEAR = ["rock", "bush", "mushroom", "bench", "lamppost", "tombstone", "umbrella", "crate", "barrel",
            "snowman", "gumdrop", "cactus", "crystal", "table", "arcade", "tree", "palm", "pine", "lollipop",
            "dead_tree", "stool", "plant"]
MARKABLE = ["bed", "desk_pc", "sofa", "counter", "fridge", "tv", "arcade", "console", "table", "tree", "palm",
            "bench", "snowman", "umbrella", "rock", "lamppost", "tombstone", "chalkboard", "lollipop", "cactus",
            "mushroom", "crate", "bookshelf", "plant", "water"]
ADJ = ["Sleepy", "Wobbly", "Neon", "Dusty", "Secret", "Tiny", "Giant", "Lonely", "Fuzzy", "Glitchy", "Golden",
       "Mossy", "Velvet", "Crooked", "Sunny", "Hollow", "Bubbly", "Rusty", "Frosted", "Pastel", "Midnight", "Lost",
       "Cozy", "Haunted", "Shiny", "Forgotten", "Silly", "Quiet", "Electric", "Candy", "Ancient", "Floating",
       "Upside", "Polka", "Starlit", "Muddy", "Crystal", "Paper", "Lucky", "Odd"]
NOUN_IN = ["Room", "Hideout", "Lounge", "Studio", "Den", "Hall", "Loft", "Chamber", "Workshop", "Parlor",
           "Basement", "Attic", "Lab", "Corner", "Club", "Office", "Shop", "Gallery", "Vault", "Nook"]
NOUN_OUT = ["Plains", "Grove", "Shore", "Valley", "Plaza", "Meadow", "Field", "Dunes", "Hollow", "Park",
            "Gardens", "Ridge", "Island", "Crossing", "Clearing", "Outskirts", "Lagoon", "Orchard", "Wastes", "Hills"]
POSTER_IDEAS = ["a cute cat face", "a retro rocket", "a smiling sun", "a pixel heart", "a cartoon fish",
                "a mountain landscape", "a strawberry", "a robot", "a cat silhouette at night", "a slice of pizza",
                "a planet with rings", "a cartoon ghost", "a lighthouse", "a cupcake", "a dinosaur"]
NEON_IDEAS = ["a heart", "a cat head", "a lightning bolt", "a star", "a coffee cup", "a game controller",
              "a moon", "a palm tree", "a pizza slice", "an arrow"]


def _hex(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s)))
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _palette(rng, indoor, light):
    base = rng.random()
    scheme = rng.choice(["analogous", "complement", "triad", "mono"])
    second = {"analogous": base + rng.uniform(0.06, 0.14), "complement": base + 0.5,
              "triad": base + 1 / 3, "mono": base}[scheme]
    accent = base + rng.choice([0.33, 0.5, 0.66, 0.15])
    dark = light == "night"
    pal = {"accent": _hex(accent, rng.uniform(0.6, 0.9), rng.uniform(0.55, 0.65))}
    if indoor:
        fl = rng.uniform(0.32, 0.62) * (0.55 if dark else 1)
        fs = rng.uniform(0.15, 0.55)
        pal["floor"] = [_hex(base, fs, fl), _hex(base if rng.random() < 0.6 else second, fs, fl - rng.uniform(0.08, 0.2))]
        pal["wall"] = _hex(second, rng.uniform(0.15, 0.5), rng.uniform(0.25, 0.38) if dark else rng.uniform(0.68, 0.88))
        pal["trim"] = _hex(accent if rng.random() < 0.5 else second, rng.uniform(0.3, 0.7), rng.uniform(0.4, 0.6))
    else:
        if rng.random() < 0.65:     # mostly believable ground (grass, sand, dirt, snow), sometimes anything
            gh, gs, gl = rng.choice([(0.3, 0.45, 0.45), (0.11, 0.55, 0.72), (0.07, 0.35, 0.4), (0.6, 0.15, 0.94),
                                     (0.25, 0.4, 0.5), (0.4, 0.35, 0.42)])
            gh += rng.uniform(-0.04, 0.04)
        else:
            gh, gs, gl = base, rng.uniform(0.3, 0.6), rng.uniform(0.45, 0.7)
        pal["floor"] = [_hex(gh, gs, gl * (0.6 if dark else 1))]
        pal["water"] = _hex(rng.choice([0.55, 0.58, 0.5, base]), rng.uniform(0.5, 0.8), rng.uniform(0.4, 0.55))
    sky_h = rng.random() if rng.random() < 0.4 else rng.choice([0.58, 0.55, 0.6])
    if dark:
        pal["fog"] = _hex(sky_h, rng.uniform(0.3, 0.6), rng.uniform(0.08, 0.2))
    elif light == "sunset":
        pal["fog"] = _hex(rng.choice([0.04, 0.08, 0.92, 0.85, 0.75]), rng.uniform(0.5, 0.8), rng.uniform(0.65, 0.78))
    else:
        pal["fog"] = _hex(sky_h, rng.uniform(0.3, 0.7), rng.uniform(0.72, 0.88))
    if indoor:   # indoor "fog" is just the colour beyond the open sides - match the room mood
        pal["fog"] = _hex(second, 0.3, 0.15 if dark else 0.85)
    return pal


def generate_random(seed=None, where=None, light=None, name=None, library=True):
    """A brand-new set. where: 'inside'/'outside'/None, light: 'day'/'sunset'/'night'/None (= random).
    library=True: may also use props the AI designed for earlier sets (assets/props), for more variety."""
    set_room("large")
    rng = random.Random(seed if seed is not None else time.time_ns())
    seed = rng.randrange(1, 10**9)
    rng = random.Random(seed)
    indoor = {"inside": True, "outside": False}.get(where, rng.random() < 0.5)
    light = light if light in ("day", "sunset", "night") else rng.choices(["day", "sunset", "night"], [5, 2, 3])[0]
    pal = _palette(rng, indoor, light)
    placed, liquid, defs = [], None, {}
    if library:
        try:
            import propgen
            lib = propgen.library()
        except Exception:
            lib = {}
        if lib and rng.random() < 0.6:
            pick = rng.sample(sorted(lib), min(len(lib), rng.randint(1, 2)))
            defs = {k: lib[k] for k in pick}
            use_custom(defs, indoor)
    if not indoor and rng.random() < 0.3:
        kind = rng.choices(list(LIQUIDS), [12] + [1] * (len(LIQUIDS) - 1))[0]
        liquid = make_liquid(rng, kind, rng.choice(["sea", "sea", "pool", "river"]))
        placed.append(liquid)

    def add(kind, zone, n):
        for _ in range(n):
            p = _place(rng, kind, zone, placed, indoor)
            if p:
                placed.append(p)

    if indoor:
        floor = rng.choice(["planks", "checker", "checker_small", "metal", "checker"])
        for kind in rng.sample(INDOOR_BIG, rng.randint(2, 4)):
            add(kind, rng.choice(["wall_back", "wall_back", "wall_left"]), rng.randint(1, 3 if kind in ("arcade", "console", "bookshelf") else 1))
        for kind in rng.sample(INDOOR_SMALL, rng.randint(2, 5)):
            add(kind, rng.choice(["scatter", "corner", "scatter"]), rng.randint(1, 3))
        if rng.random() < 0.5:
            add("rug", "center", 1)
        for kind in rng.sample(WALL_HANGS, rng.randint(1, 3)):
            add(kind, rng.choice(["hang_back", "hang_left"]), rng.randint(1, 2))
    else:
        snowy = pal["floor"][0].lower() > "#e0"  # very light ground = snow
        floor = "snow" if snowy else rng.choice(["grass", "sand", "grass", "dirt", "stone"])
        if rng.random() < 0.2:
            floor = "road"
            add("building", "city_block", rng.randint(5, 10))
        for kind in rng.sample(OUT_FAR, rng.randint(1, 2)):
            add(kind, "far", rng.randint(6, 18))
        for kind in rng.sample(OUT_NEAR, rng.randint(2, 5)):
            add(kind, rng.choice(["ring", "ring", "scatter"]), rng.randint(1, 5))
        if rng.random() < 0.7:
            add("hill", "horizon", rng.randint(2, 5))
        if rng.random() < 0.15:
            add("fence", "perimeter", 1)
    for k, d in defs.items():
        add(k, "showcase", 1)
        add(k, zone_for(k, d.get("place", "near"), indoor, rng), rng.randint(1, 3) if d.get("place") != "far" else rng.randint(4, 10))
    marks = _marks_for(placed, liquid)
    kinds = {p["kind"] for p in placed}
    # ambience follows what's actually in the scene
    if "arcade" in kinds:
        amb = "amb_arcade"
    elif "console" in kinds or "star_window" in kinds:
        amb = "amb_space"
    elif indoor:
        amb = "amb_room"
    elif liquid and liquid["type"] == "water":
        amb = "amb_waves"
    elif "building" in kinds:
        amb = "amb_city"
    elif light == "night" and ({"tombstone", "dead_tree"} & kinds):
        amb = "amb_spooky"
    elif floor in ("snow", "sand") or light == "night":
        amb = "amb_wind"
    else:
        amb = "amb_birds"
    nm = name or f"{rng.choice(ADJ)} {rng.choice(NOUN_IN if indoor else NOUN_OUT)}"
    sid = re.sub(r"[^a-z0-9]+", "_", nm.lower()).strip("_") + f"_{seed % 10000:04d}"
    shown = [k.replace("_", " ").replace("desk pc", "desk") for k in kinds if k not in ("hill", "rug", "fence", "liquid")][:4]
    if liquid:
        shown = [liquid["type"] if liquid["shape"] == "sea" else f"a {liquid['type']} {liquid['shape']}"] + shown[:3]
    desc = (f"A {'sunset' if light == 'sunset' else light}time {'room' if indoor else 'place outside'}"
            + (f" with {', '.join(shown[:-1])} and {shown[-1]}" if len(shown) > 1 else (f" with {shown[0]}" if shown else "")))
    fog = [12.0, 32.0] if indoor else ([5.0, rng.uniform(20, 28)] if light == "night" else [rng.uniform(7, 13), rng.uniform(28, 42)])
    return {
        "id": sid, "name": nm, "theme": "random", "seed": seed, "indoor": indoor, "light": light,
        "description": desc, "palette": pal, "floor": floor, "night": light == "night",
        "snowy": floor == "snow", "fog": [round(f, 1) for f in fog], "props": placed, "marks": marks,
        "ambience": amb, "textures": {}, "created": time.time(), "custom_props": defs,
        "room": [ROOM_W, ROOM_D],
        "texture_prompts": {
            "poster": f"poster of {rng.choice(POSTER_IDEAS)}, flat illustration, bold simple colors",
            "chalkboard": "chalk doodles on a green chalkboard",
            "neon_sign": f"glowing neon sign of {rng.choice(NEON_IDEAS)}, dark background",
            "star_window": "view of a planet and stars from space, pixel art",
        },
    }


def save(recipe):
    SETS_DIR.mkdir(exist_ok=True)
    (SETS_DIR / f"{recipe['id']}.json").write_text(json.dumps(recipe, indent=1), encoding="utf-8")
    return recipe


_LOAD_CACHE = {}      # path -> (mtime_ns, size, recipe): every set file is parsed once, then only when it changes


def load_all():
    """Every saved recipe (sets/*.json) by id. Files that didn't change since the last call aren't parsed again
    (catalog.all_sets() runs this many times per request)."""
    out, seen = {}, set()
    for p in sorted(SETS_DIR.glob("*.json")):
        try:
            st = p.stat()
            key = str(p)
            seen.add(key)
            hit = _LOAD_CACHE.get(key)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                r = hit[2]
            else:
                r = json.loads(p.read_text(encoding="utf-8-sig"))
                _LOAD_CACHE[key] = (st.st_mtime_ns, st.st_size, r)
            out[r["id"]] = r
        except Exception:
            continue
    for key in [k for k in _LOAD_CACHE if k not in seen]:
        _LOAD_CACHE.pop(key, None)
    return out


HEX = re.compile(r"#[0-9a-fA-F]{6}")
SYNONYMS = {  # what models often ask for -> the closest prop we can build
    "cabinet": "bookshelf", "shelf": "bookshelf", "shelves": "bookshelf", "bookcase": "bookshelf", "cupboard": "bookshelf",
    "bucket": "barrel", "keg": "barrel", "box": "crate", "boxes": "crate", "chest": "crate",
    "couch": "sofa", "armchair": "sofa", "bench_seat": "bench", "desk": "desk_pc", "computer": "desk_pc", "pc": "desk_pc",
    "oven": "fridge", "stove": "counter", "kitchen_counter": "counter", "bar": "counter", "register": "counter",
    "lamp": "floor_lamp", "light": "lamppost", "streetlight": "lamppost", "flower": "plant", "flowers": "plant",
    "potted_plant": "plant", "fern": "plant", "statue": "rock", "boulder": "rock", "stone": "rock", "candy": "lollipop",
    "candy_cane": "lollipop", "cake": "gumdrop", "cupcake": "gumdrop", "television": "tv", "screen": "tv",
    "machine": "console", "control_panel": "console", "game": "arcade", "arcade_machine": "arcade", "chairs": "chair",
    "seat": "chair", "tables": "table", "grave": "tombstone", "gravestone": "tombstone", "shrub": "bush", "hedge": "bush",
    "palm_tree": "palm", "oak": "tree", "pine_tree": "pine", "dead tree": "dead_tree", "parasol": "umbrella",
    "balloon": "balloons", "party_balloons": "balloons", "helium_balloons": "balloons",
    "toadstool": "mushroom", "gem": "crystal", "crystals": "crystal", "house": "building", "tower": "building",
}


def _place_hint(e, default=""):
    """The place of a plan entry, with its side from a picture ("left"/"right") when it has one: "far_left"."""
    place = str(e.get("place") or default or "")
    raw = str(e.get("side") or "").lower().strip()
    side = raw.replace(" ", "_").split("_")[-1]          # "far_right" -> "right"
    if side not in ("left", "right"):
        return place
    if not place and "_" in raw:                         # the side field can carry the place too: "far_right"
        place = raw.rsplit("_", 1)[0]
    return f"{place or 'ring'}@{side}"


def _kind(k):
    k = str(k or "").strip().lower().replace(" ", "_")
    return SYNONYMS.get(k, SYNONYMS.get(k.rstrip("s"), k))


LIQUIDS = {   # type -> (colour, glows, ambience it suggests)
    "water": ("#3fa9e0", False, "amb_waves"), "lava": ("#ff5a1f", True, None), "magma": ("#ff5a1f", True, None),
    "slime": ("#7fff3f", True, None), "acid": ("#b6ff3f", True, None), "goo": ("#b38bff", True, None),
    "potion": ("#c36bff", True, None), "chocolate": ("#5a3420", False, None), "honey": ("#f2b43f", False, None),
    "milk": ("#f4f0e8", False, None), "soda": ("#c0502a", False, None), "tar": ("#1a1820", False, None),
    "oil": ("#2a2430", False, None), "ice": ("#cfefff", False, None), "mud": ("#6b4a2f", False, None),
    "juice": ("#ff9a3f", False, None), "ink": ("#202a55", False, None), "blood": ("#8a1020", False, None),
}
LIQUID_SHAPES = ("pool", "river", "sea")
MAX_NEW_PROPS = 4
FLOORS_IN = ["planks", "checker", "checker_small", "metal", "stone"]
FLOORS_OUT = ["grass", "sand", "snow", "road", "stone", "dirt"]


def make_liquid(rng, kind="water", shape=None, color=None, glow=None, indoor=False):
    """A pool / river / sea prop. Placed before anything else so other props keep out of it."""
    kind = re.sub(r"[^a-z]+", "_", str(kind or "water").lower()).strip("_")[:16] or "water"
    base_col, base_glow, _ = LIQUIDS.get(kind, ("#3fa9e0", False, None))
    col = color.strip() if isinstance(color, str) and HEX.fullmatch(color.strip()) else base_col
    glow = base_glow if glow is None else bool(glow)
    shape = shape if shape in LIQUID_SHAPES else rng.choice(["pool", "pool", "river", "sea"])
    if indoor:            # a sunken pool in the floor, off to one side of the stage
        shape = "pool"
        pos, r = [rng.choice([-4.2, 4.2]), round(rng.uniform(2.0, 3.0), 2)], round(rng.uniform(1.5, 2.0), 2)
    elif shape == "pool":
        r = round(rng.uniform(3.0, 4.2), 2)
        pos = [round(rng.uniform(-2.5, 2.5), 2), round(r + rng.uniform(3.4, 4.4), 2)]   # just behind the stage
    elif shape == "river":
        pos, r = [0.0, round(rng.uniform(6.8, 8.5), 2)], round(rng.uniform(1.0, 1.6), 2)   # r = half width
    else:
        pos, r = [0.0, 16.0], 9.0
    return {"kind": "liquid", "type": kind, "shape": shape, "pos": pos, "r": r, "rot": 0.0,
            "color": col, "glow": glow, "scale": 1.0}


def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _close(a, b, limit=150):
    return math.dist(_rgb(a), _rgb(b)) < limit


def _mix(a, b, t):
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(_rgb(a), _rgb(b)))


def zone_for(kind, place, indoor, rng, n=1):
    """Where a prop goes. place = the AI prop's own hint (near/far/scatter/wall/corner), optionally with a side
    from a picture: "far_left", "near_right"."""
    if "@" in place:
        base, side = place.split("@", 1)
        return f"{zone_for(kind, base, indoor, rng, n)}@{side}"
    if place in ("wall_back", "wall_left", "corner", "hang_back", "hang_left", "center", "scatter", "grid"):
        return place                                   # a theme's exact zone: keep it (a poster stays on the wall)
    if kind in INDOOR_BIG and indoor:
        return rng.choice(["wall_back", "wall_back", "wall_left"])
    if indoor:     # the left wall and most of the floor are outside the wide shot: favour where it looks
        return {"wall": rng.choice(["wall_back", "wall_back", "wall_left"]), "corner": "corner",
                "far": "wall_back"}.get(place, rng.choice(["showcase", "scatter", "showcase", "corner"]))
    if place == "far" or (kind in OUT_FAR and n >= 6):
        return "far"
    if place == "scatter":
        return "scatter"
    return rng.choice(["ring", "ring", "scatter"])


SURFACES = {"table": 0.79, "counter": 1.17, "desk_pc": 0.78, "school_desk": 0.745}   # kind -> top height


def place_on_surfaces(rng, kind, n, placed):
    """Put small things (bowls, samovars, lamps...) on the tables/counters/desks in the set. Returns how many fit."""
    tops = [p for p in placed if p["kind"] in SURFACES]
    if not tops:
        return 0
    done = 0
    for i in range(n):
        t = tops[i % len(tops)]
        ang = t.get("rot", 0.0)
        dx, dy = rng.uniform(-0.45, 0.45), rng.uniform(-0.15, 0.15)
        if t["kind"] == "table":
            dx, dy = rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)
        x = t["pos"][0] + dx * math.cos(ang) - dy * math.sin(ang)
        y = t["pos"][1] + dx * math.sin(ang) + dy * math.cos(ang)
        placed.append({"kind": kind, "pos": [round(x, 2), round(y, 2)], "rot": round(rng.uniform(-0.4, 0.4), 3),
                       "z": SURFACES[t["kind"]] * t.get("scale", 1.0), "scale": round(CUSTOM_S.get(kind, 1.0), 2)})
        done += 1
    return done


def use_custom(defs, indoor=False):
    """Register AI-made prop definitions for placement: footprint radius, shrunk to fit (rooms are small)."""
    for k, d in defs.items():
        r, h = float(d.get("radius") or 0.6), float(d.get("height") or 1.0)
        cap_r, cap_h = (1.0, 2.6) if indoor else (2.8, 9.0)
        f = min(1.0, cap_r / max(r, 0.01), cap_h / max(h, 0.01))
        CUSTOM_S[k], CUSTOM_R[k] = f, round(r * f, 2)


def _marks_for(placed, liquid=None):
    marks = {"center": [0.0, 0.0], "front": [0.0, -2.5], "left": [-3.0, -0.5], "right": [3.0, -0.5], "back": [0.0, 3.0]}
    if liquid:
        marks[liquid["type"]] = _mark_near(liquid)
        if _blocked_by_liquid(0.0, 3.0, 0.3, liquid):
            marks.pop("back")
    kinds = []
    for p in placed:
        if p["kind"] not in kinds and p["kind"] not in ("liquid", "hill", "rug", "fence", "water", "building") \
                and p["kind"] not in WALL_PROPS:
            kinds.append(p["kind"])
    # AI-made props first (they're usually what the place is about), then the built-in favourites
    order = [k for k in kinds if k not in PROPS][:3] + [k for k in MARKABLE if k in kinds]
    for kind in order:
        if len(marks) >= 9:
            break
        p = min((p for p in placed if p["kind"] == kind), key=lambda p: math.hypot(*p["pos"]))
        if math.hypot(*p["pos"]) < 14:
            name = kind.replace("_pc", "")
            if name.startswith("imp_"):            # an imported model: the place is "table", not "imp_table"
                name = name[4:] if name[4:] and name[4:] not in marks else name
            marks[name] = _mark_near(p)
    return marks


def _plan_fx(plan):
    import catalog
    out = []
    for fx in plan.get("particles") or []:
        fx = catalog.PARTICLE_ALIASES.get(str(fx).lower(), str(fx).lower())
        if fx in catalog.PARTICLES and fx not in out:
            out.append(fx)
    return out[:2]


# words in an idea that pick a theme (longer phrases first, so "living room" beats "room")
THEME_WORDS = [
    ("living_room", ("living room", "lounge", "sofa")), ("bedroom", ("bedroom", "bed room", "sleeping room")),
    ("classroom", ("classroom", "school", "lesson")), ("kitchen", ("kitchen",)),
    ("cafe", ("cafe", "café", "coffee", "espresso", "bakery", "tea shop")),
    ("arcade", ("arcade", "game centre", "game center")), ("space_station", ("space station", "spaceship", "space lab")),
    ("graveyard", ("graveyard", "cemetery", "tombstone")), ("candyland", ("candy", "sweet world", "lollipop")),
    ("snow", ("snowy", "snow", "winter", "ski ", "arctic", "frozen")), ("desert", ("desert", "dunes", "cactus")),
    ("beach", ("beach", "seaside", "shore")), ("city", ("city street", "downtown", "high street")),
    ("forest", ("forest", "woods", "woodland", "clearing")), ("park", ("park", "garden", "meadow")),
]


THEME_DIR = ROOT / "sets" / "themes"          # themes made with "Generated theme" are saved here and loaded at start


def load_saved_themes():
    """Add the themes saved in sets/themes/*.json to THEMES (so they appear in the theme picker)."""
    if not THEME_DIR.is_dir():
        return
    for f in sorted(THEME_DIR.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8-sig"))
            if t.get("props") and t.get("id"):
                THEMES[t["id"]] = t
        except Exception:
            pass


def theme_list():
    """Every theme, for the picker: [{id, name}] (built-in first)."""
    return [{"id": k, "name": (v.get("description") or k.replace("_", " ")).split(" with ")[0][:60],
             "indoor": bool(v.get("indoor"))} for k, v in THEMES.items()]


def theme_for(plan, choice=None):
    """Which theme a scene uses. choice: "random" = none (the free AI layout, which can be odd); a theme id = that
    theme; "auto" / None = the theme whose words appear in the idea / name / description."""
    if choice == "random":
        return None
    if choice and choice not in ("auto",) and choice in THEMES:
        return choice
    text = f"{plan.get('_idea', '')} {plan.get('name', '')} {plan.get('description', '')}".lower()
    for theme, words in THEME_WORDS:
        if any(w in text for w in words):
            return theme
    return None


load_saved_themes()


def generate_from_plan(plan, seed=None, where=None, light=None, ollama=None, log=print, comfy_cfg=None, theme=None):
    """Build a recipe from an AI plan (llm.design_set). Props we can't build yet are designed on the spot by
    propgen (and saved to the prop library), liquids become pools/rivers/seas. Anything missing or invalid is
    filled in randomly, so a bad plan still gives a good set."""
    import propgen
    set_room(plan.get("room"))                                     # bathroom small, hall big, the AI says which
    if str(where or plan.get("where") or "").lower() == "air":     # no ground: sky / space / underwater / core
        rec = generate_air(plan.get("air_kind"), seed, light or plan.get("light"), plan.get("name"),
                           f"{plan.get('_idea', '')} {plan.get('name', '')} {plan.get('description', '')}")
        rec["description"] = str(plan.get("description") or rec["description"])[:200]
        c = plan.get("colors") or {}
        if rec["air"] in ("sky", "underwater") and isinstance(c.get("sky"), str) and HEX.fullmatch(c["sky"].strip()):
            rec["palette"]["fog"] = rec["palette"]["floor"][0] = c["sky"].strip()
        rec["particles"] = sorted(set(rec["particles"]) | set(_plan_fx(plan)))
        extra = [e for e in (plan.get("new_props") or []) if isinstance(e, dict) and e.get("name")][:2]
        rng = random.Random(rec["seed"] + 3)
        for e in extra:                 # a plane in the sky, a satellite, fish... drawn like any AI prop
            k = propgen.slug(e["name"])
            d = propgen.design(k, str(e.get("looks") or k), rec["description"], ollama, log, comfy_cfg=comfy_cfg)
            rec["custom_props"][k] = d
            for i in range(rng.randint(1, 3)):
                ang = rng.uniform(0, math.tau)
                rec["props"].append({"kind": k, "pos": [round(math.cos(ang) * rng.uniform(3, 9), 2),
                                                        round(4 + math.sin(ang) * rng.uniform(2, 8), 2)],
                                     "z": round(rng.uniform(-10, 6), 2), "rot": 0.0, "scale": 1.0})
        amb = plan.get("ambience")
        import sfx as sfxlib
        if amb in sfxlib.all_slots():
            rec["ambience"] = amb
        rec["designed_by"] = "ollama"
        return rec
    th = theme_for(plan, theme)                            # a known place decides inside / outside itself
    th_where = ("inside" if THEMES[th]["indoor"] else "outside") if th else None
    if th:                                                 # the theme's ground, before the ground is picked below
        plan["floor"] = THEMES[th]["floor"]
    base = generate_random(seed, where or th_where or plan.get("where"), light or plan.get("light"), None, library=False)
    if th and THEMES[th].get("room") and THEMES[th]["indoor"]:
        set_room(THEMES[th]["room"])                       # generate_random() resets the room; put the theme's back
    elif plan.get("room") and not th:
        set_room(plan.get("room"))                         # ...and the AI's room size, if it gave one
    rng = random.Random(base["seed"] + 1)
    indoor = base["indoor"]
    # colours
    pal = dict(base["palette"])
    c = plan.get("colors") or {}
    ok = lambda v: isinstance(v, str) and HEX.fullmatch(v.strip())
    if indoor:
        if ok(c.get("floor")):
            pal["floor"] = [c["floor"], c["floor2"] if ok(c.get("floor2")) else pal["floor"][1]]
        for src, dst in (("walls", "wall"), ("trim", "trim")):
            if ok(c.get(src)):
                pal[dst] = c[src]
    else:
        if ok(c.get("floor")):
            pal["floor"] = [c["floor"]]
        if ok(c.get("water")):
            pal["water"] = c["water"]
    if ok(c.get("sky")) and not indoor:
        pal["fog"] = c["sky"]
    if ok(c.get("accent")):
        pal["accent"] = c["accent"]
    floors = FLOORS_IN if indoor else FLOORS_OUT
    floor = plan.get("floor") if plan.get("floor") in floors else base["floor"]
    # props: built-in, from the prop library, or brand new (designed now)
    lib = propgen.library()
    looks = {}
    for np_ in (plan.get("new_props") or []):
        if isinstance(np_, dict) and np_.get("name") and str(np_["name"]).strip().lower() not in ("none", "null", ""):
            looks[propgen.slug(np_["name"])] = (str(np_.get("looks") or np_.get("description") or ""),
                                                 int(np_.get("count", 0) or 0), str(np_.get("place") or ""))
    banned = {"hill", "water", "fence", "rug", "liquid"} | WALL_PROPS
    entries = [p for p in (plan.get("props") or []) if isinstance(p, dict)]
    if th:                                             # a known place: its own props, so it makes sense
        theme, T = th, THEMES[th]
        plan["where"] = "inside" if T["indoor"] else "outside"
        plan["floor"] = T["floor"] if T["indoor"] or T["floor"] in ("grass", "sand", "snow", "road", "stone", "dirt") else plan.get("floor")
        if T.get("room") and T["indoor"]:
            plan["room"] = T["room"]
        if not plan.get("colors") and T.get("palettes"):
            p0 = T["palettes"][0]
            plan["colors"] = {"floor": p0["floor"][0], "floor2": p0["floor"][-1], "walls": p0.get("wall", "#f2f2f2"),
                              "trim": p0.get("trim", "#b0b0b0"), "accent": p0.get("accent", "#ff8fb8"),
                              "sky": p0.get("fog", "#cfe9ff")}
        entries = [{"kind": k, "count": rng.randint(lo, hi), "place": zone} for k, lo, hi, zone in T["props"]]
        looks = {}                                      # no extra AI props on top of a theme
        log(f"[set] a {theme.replace('_', ' ')} - using its own props")
    for k, (lk, n, pl) in looks.items():            # new props the plan described but forgot to list
        if not any(propgen.slug(_kind(e.get("kind"))) == k for e in entries):
            entries.append({"kind": k, "count": n or rng.randint(2, 5), "place": pl})
    entries.sort(key=lambda e: propgen.slug(_kind(e.get("kind"))) not in looks)
    wanted, new_kinds, gen_kinds = [], [], set()
    real_defs = {}                                   # imported models matched for this set (see imported.py)
    plan_setting = f"{plan.get('name', '')}: {plan.get('description', '')}".strip(": ")
    for e in entries:
        kind = _kind(e.get("kind"))
        try:
            n = max(1, min(20, int(e.get("count", 1) or 1)))
        except Exception:
            n = 1
        # real imported models come first: if one matches this prop, use it and generate nothing
        k_slug = propgen.slug(kind)
        if e.get("generate") and k_slug.split("_")[-1] in __import__("imported").PERSON_NOUNS:
            e = dict(e, generate=False)          # people always come from your imported people, never blocks
        if e.get("generate"):                  # make_set's look check asked for it: designed, not an imported
            gen_kinds.add(k_slug)                # stand-in (the user's imported bookshelf is an empty frame)
        if k_slug and k_slug not in banned and k_slug not in LIQUIDS and k_slug not in propgen.SHAPES                 and not e.get("generate"):
            real = propgen.imported_def(k_slug, looks.get(k_slug, ("", 0, ""))[0], plan_setting, log)
            if real:
                key = "imp_" + k_slug                   # its own name, so the built-in prop of the same name isn't used
                if key not in real_defs and not any(k == key for k, _, _ in wanted):
                    real_defs[key] = real
                    wanted.append((key, n, _place_hint(e)))
                continue
        if kind in PROPS and kind not in banned:
            if not (kind == "building" and indoor):
                wanted.append((kind, n, _place_hint(e)))
            continue
        kind = propgen.slug(kind)
        if not kind or kind in banned or kind in LIQUIDS or kind in propgen.SHAPES or any(k == kind for k, _, _ in wanted):
            continue
        if (kind not in lib or kind in gen_kinds) and kind not in new_kinds:
            if len(new_kinds) >= MAX_NEW_PROPS:
                continue
            new_kinds.append(kind)
        wanted.append((kind, n, _place_hint(e, looks.get(kind, ("", 0, ""))[2])))
    defs = {k: lib[k] for k, _, _ in wanted if k in lib}
    defs.update(real_defs)
    setting = f"{plan.get('name', '')}: {plan.get('description', '')}".strip(": ")
    for k in new_kinds:
        defs[k] = propgen.design(k, looks.get(k, ("", 0, ""))[0] or k.replace("_", " "), setting, ollama, log,
                                 comfy_cfg=comfy_cfg, use_imported=k not in gen_kinds)
    for k, d in list(defs.items()):            # older library props get a real size and a drawing now
        if d.get("source") == "imported":      # real models are used as they are
            continue
        if (comfy_cfg and not d.get("sprite") and propgen.needs_picture(d)) or (ollama and not d.get("size_checked")):
            defs[k] = propgen.design(k, d.get("looks", ""), setting, ollama, log, comfy_cfg=comfy_cfg)
    use_custom(defs, indoor)
    wanted = [(k, n, pl or (defs[k].get("place") or "" if k in defs else "")) for k, n, pl in wanted
              if k in PROPS or k in defs]
    # liquid (lava pit, slime river, chocolate sea...)
    placed, liquid = [], None
    lq = plan.get("liquid")
    if isinstance(lq, str):
        lq = {"type": lq}
    if not isinstance(lq, dict) and "water" in [str(e) for e in (plan.get("extras") or []) if isinstance(e, str)]:
        lq = {"type": "water", "shape": "sea"}
    idea = str(plan.get("_idea") or "").lower()
    liquid_words = ("water", "lake", "sea", "ocean", "beach", "river", "pool", "pond", "swamp", "lava", "volcan",
                    "slime", "spa", "bath", "fountain", "aquarium", "canal", "harbor", "harbour", "island", "magma")
    if isinstance(lq, dict) and indoor and not any(w in idea for w in liquid_words):
        log(f"[set] skipping the AI's indoor {lq.get('type', 'liquid')} pool - the idea has no water in it")
        lq = None
    if isinstance(lq, dict) and str(lq.get("type") or lq.get("kind") or "").lower() not in ("", "none", "no", "null"):
        liquid = make_liquid(rng, lq.get("type") or lq.get("kind"), lq.get("shape"), lq.get("color"),
                             lq.get("glow"), indoor)
        placed.append(liquid)
        if not indoor and _close(pal["floor"][0], liquid["color"]):   # keep the pool readable against the ground
            pal["floor"] = [_mix(pal["floor"][0], "#2a2428", 0.7)]

    def add(kind, zone, n):
        tries = {"wall_back": ["wall_left", "corner", "scatter"], "wall_left": ["wall_back", "corner", "scatter"],
                 "corner": ["scatter", "wall_left"], "showcase": ["scatter", "ring"], "ring": ["scatter", "far"]}
        for _ in range(n):
            p = None
            for z in [zone] + tries.get(zone, []):      # the wall is full? try the other wall, a corner...
                if z == "ring" and indoor:
                    continue
                p = _place(rng, kind, z, placed, indoor)
                if p:
                    break
            if p:
                d = defs.get(kind) or {}
                if d.get("on") == "wall" and float(d.get("height") or 2) < 1.2 and indoor:
                    p["z"] = round(1.45 - float(d.get("height") or 0.5) / 2, 2)    # hangs on the wall
                placed.append(p)

    ex = plan.get("extras") or []
    ex = ex if isinstance(ex, list) else [ex]
    extras = {str(e.get("kind") or e.get("name") or e.get("type") or "") if isinstance(e, dict) else str(e) for e in ex}
    if not wanted:          # unusable plan: random props, but keep the plan's look and name
        log("[set] the AI plan had no usable props - picking some at random")
        for p in base["props"]:
            if p["kind"] in PROPS and not (liquid and p["kind"] == "water") and \
                    _free(p["pos"][0], p["pos"][1], _radius(p["kind"]), placed, clear=False):
                placed.append(p)
    # small things that belong on a table: make sure there is a table/counter, and put them there afterwards
    on_table = [(k, n) for k, n, _ in wanted if (defs.get(k) or {}).get("on") == "table"]
    wanted = [w for w in wanted if (defs.get(w[0]) or {}).get("on") != "table"]
    if on_table and not any(k in SURFACES for k, _, _ in wanted):
        wanted.append(("table", 1, ""))
    # the set's signature (AI-made) props go where the camera sees them first
    stars = [k for k, _, pl in wanted if k in defs and pl != "far"][:3] or [k for k, _, _ in wanted if k in defs][:2]
    for k in stars:
        before = len(placed)
        add(k, "showcase", 1)
        wanted = [(kk, n - (len(placed) - before) if kk == k else n, pl) for kk, n, pl in wanted]
    if not wanted:
        pass
    elif indoor:
        for kind, n, pl in wanted:
            add(kind, zone_for(kind, pl, True, rng, n), min(n, 4 if kind in INDOOR_BIG else 6))
        if rng.random() < 0.5 and not liquid:
            add("rug", "center", 1)
    else:
        counts = {k: n for k, n, _ in wanted}
        if floor == "road" or "building" in counts:
            add("building", "city_block", counts.get("building", rng.randint(5, 9)))
        for kind, n, pl in wanted:
            if kind != "building":
                add(kind, zone_for(kind, pl, False, rng, n), n)
        if "hills" in extras or "hill" in extras:
            add("hill", "horizon", rng.randint(2, 5))
        if "fence" in extras:
            add("fence", "perimeter", 1)
    for k, n in on_table:
        fit = place_on_surfaces(rng, k, min(n, 4), placed)
        if fit < min(n, 4):
            add(k, "scatter", min(n, 4) - fit)
    fill_view(rng, placed, indoor, log)
    if indoor:
        for wp in (plan.get("wall_pictures") or []):
            if isinstance(wp, dict) and wp.get("kind") in WALL_HANGS:
                add(wp["kind"], rng.choice(["hang_back", "hang_left"]), max(1, min(3, int(wp.get("count", 1) or 1))))
                if wp.get("prompt"):
                    base["texture_prompts"][wp["kind"]] = str(wp["prompt"])[:200]
    import sfx as sfxlib
    slots = sfxlib.all_slots()
    amb = plan.get("ambience") if plan.get("ambience") in slots else None
    if not amb and liquid:
        amb = LIQUIDS.get(liquid["type"], (None, None, None))[2]
    name = str(plan.get("name") or base["name"])[:40]
    sid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + f"_{base['seed'] % 10000:04d}"
    tex = plan.get("textures") or {}
    for slot in ("floor", "walls", "sky"):
        if isinstance(tex.get(slot), str) and tex[slot].strip():
            base["texture_prompts"][slot] = tex[slot].strip()[:200]
    used = {p["kind"] for p in placed} | {p["kind"][4:] for p in placed if p["kind"].startswith("imp_")}
    asked = [propgen.slug(_kind(e.get("kind"))) for e in entries]
    missing = [k for k in asked if k and k not in used and k not in banned]
    if missing:
        log(f"[set] not placed: {', '.join(missing)} (unknown, no room, or over the {MAX_NEW_PROPS} new-prop limit)")
    base["particles"] = _plan_fx(plan) or [fx for fx, words in (("stars", ("moon", "space", "planet", "mars", "star")),
                                                                  ("snow", ("snow", "ice", "frost", "winter")),
                                                                  ("embers", ("lava", "volcano", "magma", "fire")))
                                         if any(w in f"{plan.get('_idea', '')} {name}".lower() for w in words)]
    out = {**base, "id": sid, "name": name, "description": str(plan.get("description") or base["description"])[:200],
           "palette": pal, "floor": floor, "snowy": floor == "snow", "props": placed, "marks": _marks_for(placed, liquid),
           "ambience": amb or base["ambience"], "designed_by": "ollama", "theme": "ai",
           "custom_props": {k: d for k, d in defs.items() if k in used},
           "room": [ROOM_W, ROOM_D],
           "plan": {k: v for k, v in plan.items() if k != "_idea"}}
    idea = plan.get("new_ambience")
    if isinstance(idea, str) and idea.strip() and idea.strip().lower() not in ("none", "no", "null"):
        out["ambience_idea"] = idea.strip()[:120]
    elif not amb and plan.get("ambience") and plan.get("ambience") not in slots:
        out["ambience_idea"] = str(plan["ambience"]).replace("_", " ")[:120]   # it named a sound we don't have
    return out


# --------------------------------------------------------------------------- sets with no ground ("air")
# Skydiving, flying, floating in space, under water, falling to the centre of the earth: no floor, things float
# around her in 3D, and when she falls ("motion": "fall") everything streams upward past her.
AIR_KINDS = {
    "sky":        dict(names=("Open Sky", "Above the Clouds", "Sky High", "Cloud Sea"), fog=("#9fd0ff", "#ffc49a", "#1b2550"),
                       props=[("cloud", 26)], particles=["speed_lines"], motion="fall", light="day",
                       description="High in the sky among big puffy clouds"),
    "space":      dict(names=("Outer Space", "Deep Space", "Starfield", "Orbit"), fog=("#05070f", "#05070f", "#05070f"),
                       props=[("planet", 3), ("space_rock", 10)], particles=["stars"], motion="float", light="night",
                       description="Floating in space among planets and rocks"),
    "underwater": dict(names=("Deep Blue", "Under the Sea", "Ocean Depths", "Coral Deep"), fog=("#1f6f9f", "#2a5f8f", "#0f2a4a"),
                       props=[("kelp", 14), ("space_rock", 6)], particles=["bubbles"], motion="float", light="day",
                       description="Under the sea, floating in blue water"),
    "core":       dict(names=("Earth's Core", "The Deep Drop", "Molten Depths", "Magma Shaft"), fog=("#5a1408", "#5a1408", "#2a0804"),
                       props=[("lava_chunk", 18), ("space_rock", 14)], particles=["embers", "speed_lines"], motion="fall",
                       light="night", description="Falling through glowing rock towards the centre of the earth"),
}
AIR_WORDS = {"sky": ("sky", "skydiv", "parachut", "cloud", "flying", "fly ", "plane", "falling from", "air"),
             "space": ("space", "orbit", "planet", "galaxy", "astronaut", "star"),
             "underwater": ("underwater", "under water", "under the sea", "ocean", "sea floor", "diving", "submarine"),
             "core": ("core", "centre of the earth", "center of the earth", "underground", "magma", "hole")}


def air_kind_for(text):
    t = f" {str(text or '').lower()} "
    for kind, words in AIR_WORDS.items():
        if any(w in t for w in words):
            return kind
    return "sky"


def generate_air(kind=None, seed=None, light=None, name=None, idea=""):
    """A set without ground. kind: sky / space / underwater / core (None = guessed from the idea)."""
    rng = random.Random(seed if seed is not None else time.time_ns())
    seed = rng.randrange(1, 10**9)
    rng = random.Random(seed)
    kind = kind if kind in AIR_KINDS else air_kind_for(idea)
    A = AIR_KINDS[kind]
    light = light if light in ("day", "sunset", "night") else A["light"]
    fog = A["fog"][{"day": 0, "sunset": 1, "night": 2}[light]]
    props = []
    for k, n in A["props"]:
        for i in range(n):
            # a tall column of things around (and mostly below) her; the camera looks along +y
            a = rng.uniform(0, math.tau)
            d = rng.uniform(3.0, 14.0)
            x, y = math.cos(a) * d, math.sin(a) * d + 4.0
            if abs(x) < 1.6 and -4.5 < y < 1.2:      # keep the line between camera and her clear
                x += 2.5 if x >= 0 else -2.5
            props.append({"kind": k, "pos": [round(x, 2), round(y, 2)], "z": round(rng.uniform(-24, 14), 2),
                          "rot": round(rng.uniform(0, math.tau), 3),
                          "scale": round(rng.uniform(0.7, 1.6) * (3.0 if k == "planet" else 1.0), 2)})
    nm = name or rng.choice(A["names"])
    sid = re.sub(r"[^a-z0-9]+", "_", nm.lower()).strip("_") + f"_{seed % 10000:04d}"
    pal = {"accent": {"sky": "#ffffff", "space": "#c8a0ff", "underwater": "#7fe0ff", "core": "#ff6a1a"}[kind],
           "floor": [fog], "fog": fog, "water": fog}
    amb = {"sky": "amb_wind", "space": "amb_space", "underwater": "amb_waves", "core": "amb_spooky"}[kind]
    return {"id": sid, "name": nm, "theme": "air", "air": kind, "motion": A["motion"], "seed": seed, "indoor": False,
            "light": light, "night": light == "night", "description": A["description"], "palette": pal,
            "floor": "none", "snowy": False, "fog": [14.0, 60.0] if kind != "underwater" else [4.0, 26.0],
            "props": props, "particles": list(A["particles"]),
            "marks": {"center": [0.0, 0.0], "front": [0.0, -2.5], "left": [-3.0, -0.5], "right": [3.0, -0.5],
                      "back": [0.0, 3.0]},
            "ambience": amb, "textures": {}, "texture_prompts": {}, "created": time.time(), "custom_props": {}}


HIDDEN = SETS_DIR / ".hidden.json"     # sets you removed that live in code (cafe, park)


def hidden():
    try:
        return set(json.loads(HIDDEN.read_text(encoding="utf-8-sig")))
    except Exception:
        return set()


def hide(sid):
    SETS_DIR.mkdir(exist_ok=True)
    HIDDEN.write_text(json.dumps(sorted(hidden() | {sid})), encoding="utf-8")


if __name__ == "__main__":
    for _ in range(6):
        r = generate_random()
        print(f"{r['name']:<24} {'inside ' if r['indoor'] else 'outside'} {r['light']:<7} floor={r['floor']:<13} "
              f"{len(r['props']):>2} props  kinds={sorted({p['kind'] for p in r['props']})}  amb={r['ambience']}")
