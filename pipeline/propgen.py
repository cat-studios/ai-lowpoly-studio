"""
AI-made props. When a set needs something the built-in prop library can't build (a lava rock, a
cauldron, a vending machine...), Ollama designs it as a handful of low-poly primitives (boxes,
cylinders, cones, spheres, rocks) with colours. Each design is validated, saved to
assets/props/<kind>.json and reused by later sets, so the library grows every time you make a set.
Recipes embed the designs they use ("custom_props"), so a set keeps working on its own.
"""
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "assets" / "props"
SHAPES = {"box": "box", "cube": "box", "block": "box", "cuboid": "box",
          "cylinder": "cylinder", "cyl": "cylinder", "tube": "cylinder", "disc": "cylinder", "disk": "cylinder",
          "cone": "cone", "spike": "cone", "pyramid": "pyramid",
          "sphere": "sphere", "ball": "sphere", "dome": "sphere", "ellipsoid": "sphere",
          "rock": "rock", "ico": "rock", "blob": "rock", "lump": "rock"}
PLACES = ("near", "far", "scatter", "wall", "corner", "center")
HEX = re.compile(r"#[0-9a-fA-F]{6}")

GUIDE = (
    "You build ONE small low-poly 3D object (N64 style) out of simple primitive shapes. Reply with JSON only:\n"
    '{"parts": [{"shape": "box|cylinder|cone|pyramid|sphere|rock", "pos": [x, y, z], "size": [w, d, h], '
    '"rot": [rx, ry, rz], "color": "#rrggbb", "glow": false}], "place": "near|far|scatter|wall|corner"}\n'
    "Units are metres. z is up and the object stands on the ground at z=0, so a part's pos is its CENTRE "
    "(a 1 m tall box on the ground has z=0.5). The front faces -y (towards the camera). size is the full "
    "width (x), depth (y) and height (z). rot is in degrees (optional). glow=true for things that give off "
    "light (fire, lava, screens, lamps, magic) - they ignore shading. rock = a lumpy faceted blob.\n"
    'Also reply "complex": true ONLY when the object is too detailed to build from simple boxes, cylinders and '
    "spheres (a person or animal, a face, text, a detailed machine); otherwise false. Simple things (a table, a "
    "tree, a cup, a rock, a car) are false.\n"
    "Use 2 to 14 parts. Keep it chunky and readable from far away: few big parts, bold distinct colours, no "
    "tiny details. Real-world scale: a person is 1.6 m tall.\n"
    "Build it like a sculpture: start with the biggest part on the ground at x=0, y=0, then attach each other "
    "part so it touches or overlaps a part already placed (stack upward, stick to the sides). Nothing floats. "
    "Solid objects only - no smoke, mist or light beams.\n"
    "place: near = a few around the stage, far = many in the background (trees, spires), scatter = small "
    "things lying around, wall = furniture that stands against a wall (inside), corner = room corner.\n"
    'Example "street lamp": {"parts": [{"shape": "cylinder", "pos": [0,0,1.5], "size": [0.12,0.12,3], '
    '"color": "#2f3440"}, {"shape": "box", "pos": [0,0,3.1], "size": [0.4,0.4,0.25], "color": "#2f3440"}, '
    '{"shape": "sphere", "pos": [0,0,2.9], "size": [0.3,0.3,0.25], "color": "#ffe7a0", "glow": true}], '
    '"place": "near"}'
)


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    return s[:28].strip("_")


def library():
    """All saved AI props: kind -> definition."""
    out = {}
    if LIB.exists():
        for p in sorted(LIB.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8-sig"))
                if d.get("parts"):
                    out[d.get("kind", p.stem)] = d
            except Exception:
                continue
    return out


def _num(v, lo, hi, default):
    try:
        v = float(v)
        return default if math.isnan(v) else max(lo, min(hi, v))
    except Exception:
        return default


def _vec(v, n, lo, hi, default):
    if isinstance(v, (int, float)):
        v = [v] * n
    if not isinstance(v, (list, tuple)):
        return list(default)
    v = list(v)[:n] + list(default)[len(v):]
    return [round(_num(x, lo, hi, d), 3) for x, d in zip(v, default)]


def _settle(parts):
    """Gravity: a part hanging in the air (nothing under it) drops onto the part below it, or the ground.
    Parts that overlap something (a canopy around a trunk, a lamp on a pole) are left alone."""
    def box(p):
        (x, y, z), (w, d, h) = p["pos"], p["size"]
        return x - w / 2, x + w / 2, y - d / 2, y + d / 2, z - h / 2, z + h / 2

    done = []
    for p in sorted(parts, key=lambda p: box(p)[4]):
        x0, x1, y0, y1, z0, z1 = box(p)
        under = [box(q) for q in done if box(q)[0] < x1 - 0.02 and box(q)[1] > x0 + 0.02
                 and box(q)[2] < y1 - 0.02 and box(q)[3] > y0 + 0.02 and box(q)[4] < z0]
        support = max([b[5] for b in under], default=0.0)
        if z0 - support > 0.05:
            p["pos"][2] = round(p["pos"][2] - (z0 - support), 3)
        done.append(p)


def clean(raw, kind, looks="", by="ollama"):
    """Validate an AI design. Returns a definition or None if nothing usable came back."""
    if not isinstance(raw, dict):
        return None
    parts_in = raw.get("parts") or raw.get("shapes") or raw.get("objects") or []
    parts = []
    for p in parts_in[:24]:
        if not isinstance(p, dict):
            continue
        shape = SHAPES.get(str(p.get("shape") or p.get("type") or "box").lower().strip())
        if not shape:
            continue
        size = _vec(p.get("size") or p.get("scale"), 3, 0.02, 14.0, (0.5, 0.5, 0.5))
        pos = _vec(p.get("pos") or p.get("position"), 3, -8.0, 16.0, (0.0, 0.0, size[2] / 2))
        rot = _vec(p.get("rot") or p.get("rotation"), 3, -360.0, 360.0, (0.0, 0.0, 0.0))
        col = str(p.get("color") or p.get("colour") or "").strip()
        parts.append({"shape": shape, "pos": pos, "size": size, "rot": rot,
                      "color": col.lower() if HEX.fullmatch(col) else "#9a9180", "glow": bool(p.get("glow"))})
    if not parts:
        return None
    # sit it on the ground: the lowest point touches z=0 (models often forget the centre rule)
    low = min(p["pos"][2] - p["size"][2] / 2 for p in parts)
    # ...and is centred on its footprint, so placement/spacing works
    cx = (min(p["pos"][0] - p["size"][0] / 2 for p in parts) + max(p["pos"][0] + p["size"][0] / 2 for p in parts)) / 2
    cy = (min(p["pos"][1] - p["size"][1] / 2 for p in parts) + max(p["pos"][1] + p["size"][1] / 2 for p in parts)) / 2
    for p in parts:
        p["pos"] = [round(p["pos"][0] - cx, 3), round(p["pos"][1] - cy, 3), round(p["pos"][2] - low, 3)]
    _settle(parts)
    # footprint + height measured from the parts, not trusted from the model
    radius = max(math.hypot(abs(p["pos"][0]) + p["size"][0] / 2, abs(p["pos"][1]) + p["size"][1] / 2) for p in parts)
    height = max(p["pos"][2] + p["size"][2] / 2 for p in parts)
    if radius > 6 or height > 16:            # far too big for a prop - shrink it to a sane size
        f = min(6 / radius, 16 / height)
        for p in parts:
            p["pos"] = [round(x * f, 3) for x in p["pos"]]
            p["size"] = [round(max(0.02, x * f), 3) for x in p["size"]]
        radius, height = radius * f, height * f
    place = str(raw.get("place") or "").lower()
    if place not in PLACES:
        place = "far" if height > 3 else ("scatter" if radius < 0.4 else "near")
    return {"kind": kind, "name": kind.replace("_", " "), "looks": str(looks)[:200], "place": place,
            "radius": round(min(radius, 4.0), 2), "height": round(height, 2), "parts": parts,
            "complex": bool(raw.get("complex")),
            "by": by, "created": time.time()}


# --------------------------------------------------------------------------- animals
# The AI's own animal designs come out as a few blocks (a pigeon was an upright cylinder with boxes), so animals
# are built from a body template instead: head, eyes, beak/snout, ears, legs, wings/fins, tail. The AI design (or
# the description) still gives the colours, and real_size() scales it to the real animal.
ANIMAL_FAMILIES = {
    "bird": set("""bird birds pigeon pigeons dove crow raven sparrow parrot seagull gull duck duckling chicken hen
rooster chick owl eagle hawk falcon penguin robin flamingo swan goose turkey canary budgie toucan pelican
magpie""".split()),
    "beast": set("""cat cats kitten kitty dog dogs puppy pup doggo fox wolf horse pony cow cows bull calf pig piglet sheep
lamb goat bear cub rabbit bunny mouse mice rat hamster deer reindeer lion tiger leopard cheetah raccoon squirrel
elephant donkey capybara panda koala otter hedgehog ferret llama alpaca camel moose zebra giraffe hippo rhino
kangaroo monkey dinosaur dino""".split()),
    "fish": set("fish goldfish shark whale dolphin salmon tuna koi trout piranha orca".split()),
    "bug": set("ant ants beetle ladybug ladybird bug bugs insect fly housefly cockroach cricket grasshopper "
               "firefly mosquito termite weevil".split()),
}
ANIMAL_COLORS = {   # body, wing/back, beak/snout - when the description names no colour
    "pigeon": ("#8d93a3", "#6c7282", "#3a3c44"), "dove": ("#eceef2", "#c9ccd4", "#e8a050"),
    "crow": ("#2b2b33", "#1d1d24", "#3a3a3a"), "raven": ("#2b2b33", "#1d1d24", "#3a3a3a"),
    "duck": ("#d8b46a", "#3f7a4a", "#f0a030"), "chicken": ("#f2efe6", "#e0d8c8", "#f0b030"),
    "hen": ("#b5651d", "#8a4a16", "#f0b030"), "penguin": ("#26262e", "#26262e", "#f0a030"),
    "flamingo": ("#ff8fb8", "#f2709e", "#2a2a2a"), "parrot": ("#3fb04a", "#d94a4a", "#f2d14e"),
    "owl": ("#9a7650", "#6e5236", "#d8b040"), "swan": ("#f4f4f4", "#e4e4e8", "#f08a30"),
    "cat": ("#e0a060", "#c78446", "#f2b8b0"), "kitten": ("#e0a060", "#c78446", "#f2b8b0"),
    "dog": ("#b5835a", "#8a5f3c", "#2a2a2a"), "puppy": ("#d6b07a", "#b58a58", "#2a2a2a"),
    "fox": ("#e07a30", "#f4efe6", "#2a2a2a"), "wolf": ("#8a8f99", "#6a6f78", "#2a2a2a"),
    "pig": ("#f2b0b8", "#e898a4", "#e07a8a"), "sheep": ("#f2f0ea", "#3a3a3a", "#3a3a3a"),
    "cow": ("#f4f2ee", "#2a2a2a", "#f2b8b8"), "horse": ("#8a5a36", "#5a3a22", "#3a2a1a"),
    "bear": ("#6e4a2e", "#553820", "#2a2a2a"), "panda": ("#f4f4f4", "#26232a", "#26232a"),
    "rabbit": ("#ece6dc", "#d8d0c4", "#f2b8c0"), "bunny": ("#ece6dc", "#d8d0c4", "#f2b8c0"),
    "mouse": ("#a8a4a0", "#8a8682", "#f2b8c0"), "rat": ("#8a8682", "#6e6a66", "#f2b8c0"),
    "frog": ("#5aa84a", "#3f8a3a", "#2a2a2a"), "elephant": ("#9a9aa2", "#85858d", "#9a9aa2"),
    "lion": ("#d8a050", "#a0682a", "#3a2a1a"), "tiger": ("#f08a30", "#2a2a2a", "#f4efe6"),
    "goldfish": ("#f08a30", "#f2b060", "#f4efe6"), "ladybug": ("#d93a3a", "#1a1a1a", "#1a1a1a"),
    "ladybird": ("#d93a3a", "#1a1a1a", "#1a1a1a"), "bee": ("#f2c230", "#2a2a2a", "#2a2a2a"),
    "firefly": ("#5a4a3a", "#f2e050", "#1a1a1a"), "grasshopper": ("#6aa84a", "#4a8a3a", "#2a2a2a"), "shark": ("#7a8a99", "#5a6a78", "#f4f4f4"),
    "whale": ("#4a6a8a", "#3a5470", "#d8dde4"), "dolphin": ("#8a9aaa", "#6f7f8f", "#d8dde4"),
}
FAMILY_COLORS = {"bug": ("#3a2a22", "#2a1e18", "#1a1a1a"), "bird": ("#9a8a7a", "#7a6a5a", "#e8a040"),
                 "beast": ("#a07850", "#80603c", "#2a2a2a"),
                 "fish": ("#5a8ab0", "#3f6a90", "#f4f4f4")}
FAMILY_HEIGHT = {"bird": 0.35, "beast": 0.6, "fish": 0.5, "bug": 0.05}       # without Ollama to ask (real_size)


def animal_family(kind, looks=""):
    """"bird" / "beast" / "fish" when the prop is an animal (by its name, else its description), else None.
    The name decides first: a "bird feeder" or "cat bed" isn't an animal."""
    parts = [w for w in re.split(r"[^a-z]+", str(kind).lower().replace("_", " ")) if w]
    name = set(parts)
    for fam, words in ANIMAL_FAMILIES.items():     # the LAST word is the thing: "brown dog" yes, "ant farm" no
        if parts and parts[-1] in words and not name & THING_WORDS:
            return fam
    if not str(looks).strip():
        return None
    desc = re.split(r"[^a-z]+", str(looks).lower())
    if len(name - {""}) <= 1 and not name & THING_WORDS:      # "+fluffy a fluffy grey cat" - the looks name it
        for fam, words in ANIMAL_FAMILIES.items():
            if set(desc[:4]) & words:
                return fam
    return None


THING_WORDS = set("""bed feeder food bowl cage house toy statue plush plushie poster picture painting sign tank
bath kennel hutch nest coop mask costume pillow figurine bone collar leash""".split())


def _shade(hexcol, f):
    c = hexcol.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * f))) for v in (r, g, b))


def _animal_colours(kind, looks, fam, ai_parts=None):
    """(body, second, accent): a colour word in the description, else the animal's usual colours, else the AI
    design's main colour, else the family's."""
    import catalog
    words = re.split(r"[^a-z]+", f"{looks}".lower())
    named = [catalog.CAST_COLORS[w] for w in words if w in catalog.CAST_COLORS]
    base = next((ANIMAL_COLORS[w] for w in re.split(r"[^a-z]+", f"{kind} {looks}".lower().replace("_", " "))
                 if w in ANIMAL_COLORS), None)
    if named:
        body = named[0]
        second = named[1] if len(named) > 1 else _shade(body, 0.78)
        return body, second, (base or FAMILY_COLORS[fam])[2]
    if base:
        return base
    if ai_parts:
        cols = {}
        for p in ai_parts:
            v = p["size"][0] * p["size"][1] * p["size"][2]
            cols[p["color"]] = cols.get(p["color"], 0) + v
        body = max(cols, key=cols.get)
        return body, _shade(body, 0.78), FAMILY_COLORS[fam][2]
    return FAMILY_COLORS[fam]


def _part(shape, pos, size, color, rot=(0, 0, 0)):
    return {"shape": shape, "pos": [round(v, 3) for v in pos], "size": [round(v, 3) for v in size],
            "rot": [float(v) for v in rot], "color": color, "glow": False}


def animal_parts(fam, body, second, accent):
    """A chunky low-poly animal facing -y (the camera), standing on z=0, about 1 unit tall."""
    eye, white = "#141418", "#f4f4f4"
    if fam == "bird":
        return [
            _part("sphere", (0, 0.02, 0.42), (0.46, 0.72, 0.46), body),                     # body
            _part("sphere", (0, -0.3, 0.74), (0.32, 0.32, 0.32), body),                     # head
            _part("cone", (0, -0.5, 0.72), (0.1, 0.1, 0.2), accent, (90, 0, 0)),             # beak
            _part("sphere", (0.12, -0.42, 0.8), (0.07, 0.07, 0.07), eye),                   # eyes
            _part("sphere", (-0.12, -0.42, 0.8), (0.07, 0.07, 0.07), eye),
            _part("sphere", (0.25, 0.06, 0.46), (0.1, 0.52, 0.3), second, (-12, 0, 0)),      # wings
            _part("sphere", (-0.25, 0.06, 0.46), (0.1, 0.52, 0.3), second, (-12, 0, 0)),
            _part("box", (0, 0.42, 0.42), (0.26, 0.3, 0.06), second, (-25, 0, 0)),          # tail
            _part("cylinder", (0.09, 0, 0.1), (0.04, 0.04, 0.2), accent),                   # legs
            _part("cylinder", (-0.09, 0, 0.1), (0.04, 0.04, 0.2), accent),
        ]
    if fam == "bug":                                                                       # six legs
        legs = []
        for k, y in enumerate((-0.18, 0.0, 0.18)):
            for sx in (1, -1):
                legs.append(_part("cylinder", (sx * 0.3, y, 0.16), (0.05, 0.05, 0.36), second, (0, sx * 55, 0)))
        return [
            _part("sphere", (0, -0.42, 0.42), (0.3, 0.3, 0.28), body),                          # head
            _part("sphere", (0, -0.1, 0.4), (0.3, 0.38, 0.28), body),                           # middle
            _part("sphere", (0, 0.36, 0.44), (0.46, 0.6, 0.42), body),                          # back end
            _part("sphere", (0.09, -0.55, 0.47), (0.07, 0.07, 0.07), "#141418"),                # eyes
            _part("sphere", (-0.09, -0.55, 0.47), (0.07, 0.07, 0.07), "#141418"),
            _part("cylinder", (0.08, -0.56, 0.68), (0.03, 0.03, 0.34), second, (25, 0, 15)),    # antennae
            _part("cylinder", (-0.08, -0.56, 0.68), (0.03, 0.03, 0.34), second, (25, 0, -15)),
        ] + legs
    if fam == "fish":
        return [
            _part("sphere", (0, 0, 0.32), (0.3, 0.9, 0.55), body),                          # body
            _part("cone", (0, 0.58, 0.32), (0.08, 0.36, 0.42), second, (-90, 0, 0)),        # tail
            _part("cone", (0, 0.02, 0.66), (0.06, 0.3, 0.22), second),                      # top fin
            _part("box", (0.17, -0.08, 0.26), (0.04, 0.2, 0.12), second, (0, 25, 0)),       # side fins
            _part("box", (-0.17, -0.08, 0.26), (0.04, 0.2, 0.12), second, (0, -25, 0)),
            _part("sphere", (0.12, -0.3, 0.4), (0.09, 0.09, 0.09), white),                  # eyes
            _part("sphere", (-0.12, -0.3, 0.4), (0.09, 0.09, 0.09), white),
            _part("sphere", (0.15, -0.33, 0.4), (0.05, 0.05, 0.05), eye),
            _part("sphere", (-0.15, -0.33, 0.4), (0.05, 0.05, 0.05), eye),
        ]
    return [                                                                                 # four legs
        _part("sphere", (0, 0.05, 0.52), (0.46, 0.9, 0.44), body),                          # body
        _part("sphere", (0, -0.5, 0.78), (0.4, 0.38, 0.38), body),                          # head
        _part("box", (0, -0.7, 0.72), (0.2, 0.16, 0.15), second),                           # snout
        _part("sphere", (0, -0.79, 0.76), (0.07, 0.05, 0.06), accent),                      # nose
        _part("sphere", (0.1, -0.67, 0.86), (0.07, 0.05, 0.07), eye),                       # eyes
        _part("sphere", (-0.1, -0.67, 0.86), (0.07, 0.05, 0.07), eye),
        _part("cone", (0.13, -0.47, 1.0), (0.13, 0.08, 0.18), second),                      # ears
        _part("cone", (-0.13, -0.47, 1.0), (0.13, 0.08, 0.18), second),
        _part("cylinder", (0.15, -0.25, 0.18), (0.12, 0.12, 0.36), body),                   # legs
        _part("cylinder", (-0.15, -0.25, 0.18), (0.12, 0.12, 0.36), body),
        _part("cylinder", (0.15, 0.32, 0.18), (0.12, 0.12, 0.36), body),
        _part("cylinder", (-0.15, 0.32, 0.18), (0.12, 0.12, 0.36), body),
        _part("cylinder", (0, 0.56, 0.68), (0.07, 0.07, 0.36), second, (-40, 0, 0)),        # tail
    ]


def make_animal(d, kind, looks, fam):
    """Replace an animal definition's parts with the body template, keeping its colours, size and the rest."""
    body, second, accent = _animal_colours(kind, looks, fam, d.get("parts"))
    parts = animal_parts(fam, body, second, accent)
    h0 = max(p["pos"][2] + p["size"][2] / 2 for p in parts)
    want = float(d.get("height") or 0) if d.get("size_checked") else FAMILY_HEIGHT[fam]
    f = (want or FAMILY_HEIGHT[fam]) / h0
    for p in parts:
        p["pos"] = [round(v * f, 3) for v in p["pos"]]
        p["size"] = [round(max(0.01, v * f), 3) for v in p["size"]]
    radius = max(math.hypot(abs(p["pos"][0]) + p["size"][0] / 2, abs(p["pos"][1]) + p["size"][1] / 2) for p in parts)
    d.update(parts=parts, height=round(h0 * f, 2), radius=round(radius, 2), animal=fam,
             complex=False)        # the look check decides if it needs a drawn picture (fails twice -> sprite)
    return d


# --------------------------------------------------------------------------- vehicles
# Only when no imported model fits (imported.match comes first, with stand-ins: a mail van -> the ambulance).
# The AI's own vehicles came out as tilted overlapping slabs; these are chunky toy-like bodies, long side to the
# camera (x), standing on their wheels.
VEHICLE_FAMILIES = {
    "car": set("car cars auto automobile sedan taxi cab jeep suv limo limousine racecar coupe hatchback cop "
               "cruiser buggy".split()),
    "van": set("van minivan camper campervan ambulance".split()),
    "truck": set("truck lorry pickup firetruck tanker dumptruck semi".split()),
    "bus": set("bus coach schoolbus tram trolley".split()),
}
VEHICLE_COLORS = {"mail": "#2b5fb3", "postal": "#2b5fb3", "taxi": "#f2c230", "cab": "#f2c230",
                  "police": "#2b3a73", "cop": "#2b3a73", "ambulance": "#f4f2ee", "fire": "#d94a4a",
                  "firetruck": "#d94a4a", "school": "#f2b030", "schoolbus": "#f2b030", "ice": "#ff8fb8",
                  "delivery": "#c9a36a", "garbage": "#3f7a4a"}
VEHICLE_SIZE = {"car": (4.2, 1.45), "van": (4.8, 2.1), "truck": (6.0, 2.7), "bus": (9.0, 3.0)}   # length, height


def vehicle_family(kind, looks=""):
    """"car" / "van" / "truck" / "bus" when the thing is a road vehicle (its name's last word decides), else None."""
    ws = [w for w in re.split(r"[^a-z]+", str(kind).lower().replace("_", " ")) if w]
    if not ws:
        return None
    for fam, names in VEHICLE_FAMILIES.items():
        if ws[-1] in names or ws[-1].rstrip("s") in names:
            return fam
    if ws[-1] in ("vehicle", "wagon"):
        return "car"
    return None


def vehicle_parts(fam, body, glass="#9fd0e8", tyre="#26232a"):
    """A toy-like vehicle, long side along x, standing on z=0, about 1 unit long."""
    light, dark = "#fff2b0", _shade(body, 0.7)
    wheel = lambda x, y, r: _part("cylinder", (x, y, r), (2 * r, 0.06, 2 * r), tyre, (90, 0, 0))   # noqa: E731
    if fam == "bus":
        parts = [_part("box", (0, 0, 0.2), (1.0, 0.28, 0.27), body),
                 _part("box", (0.03, 0, 0.27), (0.86, 0.285, 0.07), glass),                   # window strip
                 _part("box", (0.49, 0, 0.24), (0.025, 0.24, 0.12), glass)]                   # windscreen
        wheels = [wheel(0.33, s * 0.12, 0.055) for s in (-1, 1)] + [wheel(-0.3, s * 0.12, 0.055) for s in (-1, 1)]
    elif fam == "truck":
        parts = [_part("box", (-0.14, 0, 0.27), (0.7, 0.3, 0.36), body),                       # cargo box
                 _part("box", (0.36, 0, 0.21), (0.27, 0.28, 0.25), dark),                     # cab
                 _part("box", (0.43, 0, 0.27), (0.13, 0.285, 0.1), glass),
                 _part("box", (0.08, 0, 0.07), (0.92, 0.2, 0.05), "#3a3a40")]                 # chassis
        wheels = [wheel(0.35, s * 0.13, 0.07) for s in (-1, 1)] + [wheel(-0.32, s * 0.13, 0.07) for s in (-1, 1)]
    elif fam == "van":
        parts = [_part("box", (0, 0, 0.21), (1.0, 0.36, 0.3), body),
                 _part("box", (0.38, 0, 0.32), (0.2, 0.365, 0.11), glass),                    # front windows
                 _part("box", (0.495, 0, 0.13), (0.02, 0.3, 0.08), dark)]                     # grille
        wheels = [wheel(0.3, s * 0.17, 0.08) for s in (-1, 1)] + [wheel(-0.3, s * 0.17, 0.08) for s in (-1, 1)]
    else:
        parts = [_part("box", (0, 0, 0.14), (1.0, 0.42, 0.15), body),                          # lower body
                 _part("box", (-0.05, 0, 0.26), (0.5, 0.38, 0.12), body),                      # cabin
                 _part("box", (-0.05, 0, 0.265), (0.52, 0.385, 0.08), glass)]                  # windows
        wheels = [wheel(0.3, s * 0.2, 0.08) for s in (-1, 1)] + [wheel(-0.3, s * 0.2, 0.08) for s in (-1, 1)]
    lamps = [_part("sphere", (0.5, s * 0.1, 0.16), (0.03, 0.06, 0.05), light) for s in (-1, 1)]
    for p in lamps:
        p["glow"] = True
    return parts + wheels + lamps


def make_vehicle(d, kind, looks, fam):
    """Replace a vehicle definition's parts with the body template (colour from the name/looks/AI design)."""
    import catalog
    ws = re.split(r"[^a-z]+", f"{kind} {looks}".lower().replace("_", " "))
    named = [catalog.CAST_COLORS[w] for w in ws if w in catalog.CAST_COLORS]
    body = named[0] if named else next((VEHICLE_COLORS[w] for w in ws if w in VEHICLE_COLORS), None)
    if not body and d.get("parts"):
        cols = {}
        for p in d["parts"]:
            cols[p["color"]] = cols.get(p["color"], 0) + p["size"][0] * p["size"][1] * p["size"][2]
        body = max(cols, key=cols.get)
    parts = vehicle_parts(fam, body or "#d94a4a")
    length, height = VEHICLE_SIZE[fam]
    if set(ws) & {"toy", "tiny", "mini", "miniature", "model", "little"}:
        length *= 0.08                         # a toy car fits in her hand
    h0 = max(p["pos"][2] + p["size"][2] / 2 for p in parts)
    f = length / 1.0
    for p in parts:
        # built nose along +x; props face -y (moving things turn their -y to where they're going), so turn it
        x, y, z = p["pos"]
        sx, sy, sz = p["size"]
        p["pos"] = [round(y * f, 3), round(-x * f, 3), round(z * f, 3)]
        p["size"] = [round(max(0.01, sy * f), 3), round(max(0.01, sx * f), 3), round(max(0.01, sz * f), 3)]
        if p["shape"] == "cylinder":
            p["rot"] = [0.0, 90.0, 0.0]          # wheels: axle across the vehicle
    radius = max(math.hypot(abs(p["pos"][0]) + p["size"][0] / 2, abs(p["pos"][1]) + p["size"][1] / 2) for p in parts)
    d.update(parts=parts, height=round(h0 * f, 2), radius=round(radius, 2), vehicle=fam, complex=False,
             size_checked=True, on="floor", width=round(length, 2))
    return d


def template_for(kind, looks=""):
    """("animal", family) / ("vehicle", family) when the thing gets a body template, else None."""
    v = vehicle_family(kind, looks)
    if v:
        return "vehicle", v
    a = animal_family(kind, looks)
    return ("animal", a) if a else None


def apply_template(d, kind, looks, tpl):
    return (make_vehicle if tpl[0] == "vehicle" else make_animal)(d, kind, looks, tpl[1])


def needs_picture(d):
    """Only objects too detailed for simple 3D shapes (or with no shape at all) get a 2D picture.
    Priority: imported model > generated 3D model > 2D picture."""
    return bool(d.get("complex") or not d.get("parts"))


def fallback(kind, looks="", colors=None):
    """No AI available (or it returned junk): a simple stand-in built from the words in the name."""
    words = f"{kind} {looks}".lower()
    c = (colors or ["#8a7f99", "#c4b6a0"])
    glow = any(w in words for w in ("lava", "fire", "glow", "magma", "neon", "lamp", "torch", "crystal", "magic"))
    if any(w in words for w in ("rock", "stone", "boulder", "lava", "magma")):
        parts = [{"shape": "rock", "pos": [0, 0, 0.45], "size": [1.4, 1.1, 0.9], "color": "#3a3438"},
                 {"shape": "rock", "pos": [0.35, -0.2, 0.75], "size": [0.5, 0.4, 0.35], "color": c[0], "glow": glow}]
    elif any(w in words for w in ("tree", "spire", "tower", "pillar", "column", "totem")):
        parts = [{"shape": "cylinder", "pos": [0, 0, 1.2], "size": [0.5, 0.5, 2.4], "color": c[1]},
                 {"shape": "cone", "pos": [0, 0, 3.0], "size": [1.6, 1.6, 1.6], "color": c[0], "glow": glow}]
    else:
        parts = [{"shape": "box", "pos": [0, 0, 0.4], "size": [0.9, 0.7, 0.8], "color": c[1]},
                 {"shape": "sphere", "pos": [0, 0, 1.0], "size": [0.6, 0.6, 0.45], "color": c[0], "glow": glow}]
    for p in parts:
        p.setdefault("rot", [0, 0, 0])
        p.setdefault("glow", False)
    return clean({"parts": parts}, kind, looks, by="fallback")


SIZE_GUIDE = ("You know the real-world size of everyday objects. Reply with JSON only: "
              '{"height_m": number, "width_m": number, "on": "floor" or "table" or "wall"}. '
              "height_m/width_m = a typical real one in metres. on = where it normally stands: floor (furniture, "
              "appliances, plants, vehicles, people-sized things), table (small things you put on a table or "
              "counter: bowls, pots, lamps, samovars, books, food), wall (things that hang).")


def real_size(d, ollama, log=print):
    """Ask once how big the real object is (one number is far more reliable than the shape design's guess) and
    scale the definition to it. Also records where it sits: floor / table / wall."""
    if not ollama or d.get("size_checked"):
        return d
    import llm
    try:
        r = llm.chat_json(ollama["url"], ollama["model"], SIZE_GUIDE,
                          f"Object: {d['kind'].replace('_', ' ')} ({d.get('looks') or ''})", temperature=0.2)
        h = _num(r.get("height_m"), 0.05, 12.0, 0.0)
        wdt = _num(r.get("width_m"), 0.03, 15.0, 0.0)
        on = r.get("on") if r.get("on") in ("floor", "table", "wall") else "floor"
    except Exception as exc:
        log(f"[props] size check for '{d['kind']}' failed ({exc.__class__.__name__})")
        return d
    if h > 0:
        f = h / max(0.05, float(d.get("height", h)))
        for p in d.get("parts", []):
            p["pos"] = [round(x * f, 3) for x in p["pos"]]
            p["size"] = [round(max(0.01, x * f), 3) for x in p["size"]]
        d["height"] = round(h, 2)
        d["radius"] = round(min(4.0, float(d.get("radius", 0.5)) * f), 2)
        if wdt > 0:
            d["width"] = round(wdt, 2)
            squeeze_to_width(d, log)
        d["on"] = on
        if on == "table":
            d["place"] = "scatter"
        d["size_checked"] = True
        log(f"[props] '{d['kind']}' is about {h:.2f} m tall, sits on the {on}")
    return d


def squeeze_to_width(d, log=print):
    """A made prop far wider than the real thing (a "flagpole" 6 m tall and 8 m wide filled a set's whole view) is
    squeezed sideways to its real width (d["width"], from real_size); the height stays. True if it changed."""
    wdt = float(d.get("width") or 0)
    # the real width is often just the main body (a flagpole's pole): allow a quarter of the height for bits that
    # stick out (the flag, a lamp's shade) - only shapes far past that are squeezed
    wdt = max(wdt, 0.25 * float(d.get("height") or 0), 0.3) if wdt > 0 else 0
    if not (wdt > 0 and d.get("parts") and 2 * float(d.get("radius", 0)) > wdt * 1.5) or d.get("model"):
        return False
    g = wdt / (2 * float(d["radius"]))
    for p in d["parts"]:
        p["pos"] = [round(p["pos"][0] * g, 3), round(p["pos"][1] * g, 3), p["pos"][2]]
        p["size"] = [round(max(0.01, p["size"][0] * g), 3), round(max(0.01, p["size"][1] * g), 3), p["size"][2]]
    d["radius"] = round(wdt / 2, 2)
    log(f"[props] '{d.get('kind')}' was far too wide - squeezed to {wdt:.2f} m")
    return True


def add_sprite(d, comfy_cfg, log=print, force=False):
    """Give a prop a picture: ComfyUI draws it and it's cut out (assets/props/<kind>.png). Blender shows the sprite
    as a camera-facing cut-out (N64 style) - much more recognisable than shapes. The shapes stay as the fallback."""
    if not comfy_cfg or (d.get("sprite") and (ROOT / d["sprite"]).exists() and not force):
        return d
    import comfy
    kind = d["kind"]
    out = LIB / f"{kind}.png"
    try:
        info = comfy.object_sprite(kind, d.get("looks") or kind.replace("_", " "), out, comfy_cfg,
                                   seed=sum(map(ord, kind)) * 31, log=log)
    except Exception as exc:
        log(f"[props] couldn't draw '{kind}' ({exc.__class__.__name__}: {str(exc)[:80]}) - using shapes")
        info = None
    if info:
        d["sprite"] = f"assets/props/{kind}.png"
        d["sprite_aspect"] = info["aspect"]
        log(f"[props] drew '{kind}' ({info['w']}x{info['h']} px sprite)")
    return d


def _save(d):
    LIB.mkdir(parents=True, exist_ok=True)
    (LIB / f"{d['kind']}.json").write_text(json.dumps(d, indent=1), encoding="utf-8")


def imported_def(kind, looks="", setting="", log=print):
    """A real imported model (assets/imported) for `kind`, checked BEFORE anything is generated. None if no match."""
    try:
        import imported
        if imported.is_group(kind):            # "marching_soldier_group", "crowd": several models, not one
            d = imported.crowd_def(kind, looks, setting)
            if d:
                log(f"[props] '{kind}' is a crowd of {len(d['crowd'])} imported models ({d['name']})")
            return d
        d = imported.match(kind, looks, setting)
    except Exception as exc:
        log(f"[props] imported models unavailable ({exc.__class__.__name__}: {str(exc)[:80]})")
        return None
    if d and d.get("needs_height"):            # not in the size table: ask once how big the real thing is
        try:
            import settings as S
            m = next(x for p in imported.packs() for x in p.get("models", []) if x["id"] == d["model"]["id"])
            if imported.ask_height(m, S.load_settings().get("ollama"), log):
                d = dict(imported.model_def(m["id"], kind, looks), stand_in=d.get("stand_in", False))
        except Exception as exc:
            log(f"[props] size of '{d['name']}' unknown ({exc.__class__.__name__}) - using its file's size")
    if d:
        ws = set(re.findall(r"[a-z]+", f"{kind} {looks}".lower().replace("_", " ")))
        f = 0.25 if ws & {"tiny", "mini", "miniature", "toy", "baby", "pocket"} else \
            0.55 if ws & {"small", "little", "smol"} else 1.8 if ws & {"giant", "huge", "enormous", "massive"} else 1.0
        if f != 1.0:
            d = dict(d, height=round(max(0.08, d["height"] * f), 3), width=round(d["width"] * f, 3),
                     radius=round(d["radius"] * f, 2))
        log(f"[props] using imported model '{d['name']}' for '{kind}' (from {d['pack']}"
            + (", the closest model there is)" if d.get("stand_in") else ")"))
    return d


def design(kind, looks, setting="", ollama=None, log=print, save=True, comfy_cfg=None, use_imported=True):
    """Get the definition for `kind`: a real imported model if one matches, else the library, else designed now.
    Ollama works out its size and a shape version; with comfy_cfg (ComfyUI on) it also gets a drawn sprite."""
    kind = slug(kind)
    real = imported_def(kind, looks, setting, log) if use_imported else None
    if real:
        return real
    have = library().get(kind)
    if have:
        log(f"[props] reusing '{kind}' from the prop library")
        changed = False
        tpl = template_for(kind, have.get("looks", ""))
        if tpl and not have.get(tpl[0]) and have.get("source") != "imported":
            # an animal/vehicle designed before the body templates (a few blocks): rebuilt once, the old file kept
            (LIB / ".trash").mkdir(parents=True, exist_ok=True)
            (LIB / ".trash" / f"{kind}-blocks-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
                json.dumps(have, indent=1), encoding="utf-8")
            apply_template(have, kind, have.get("looks", ""), tpl)
            log(f"[props] '{kind}' rebuilt as a {tpl[1]} (the old shape is in assets/props/.trash)")
            changed = True
        if ollama and not have.get("size_checked"):        # older library props get a real size...
            real_size(have, ollama, log)
            changed = have.get("size_checked", False)
        if not have.get("animal") and not have.get("vehicle") and squeeze_to_width(have, log):
            changed = True                                   # ...the real width (older ones could be 8 m wide)...
        if ollama and _prop_check_on() and "checked" not in have and have.get("parts") and not have.get("complex")                 and have.get("source") != "imported":       # ...a look check (once)...
            have = look_checked(have, kind, have.get("looks", ""), setting, ollama, log)
            changed = True
        if comfy_cfg and not have.get("sprite") and needs_picture(have):   # ...and a picture if it needs one
            add_sprite(have, comfy_cfg, log)
            changed = changed or bool(have.get("sprite"))
        if changed and save:
            _save(have)
        return have
    d = None
    if ollama:
        import llm
        user = (f"Object: {kind.replace('_', ' ')}\nWhat it looks like: {looks or kind.replace('_', ' ')}\n"
                + (f"It is part of this place: {setting}\n" if setting else ""))
        for attempt in range(2):
            try:
                d = clean(llm.chat_json(ollama["url"], ollama["model"], GUIDE, user, temperature=0.7), kind, looks)
            except Exception as exc:
                log(f"[props] Ollama failed on '{kind}' ({exc.__class__.__name__}: {str(exc)[:80]})")
                d = None
            if d and len(d["parts"]) >= 2:
                break
    if not d:
        d = fallback(kind, looks)
        log(f"[props] '{kind}': simple stand-in shape (no usable AI design)")
    else:
        log(f"[props] designed new prop '{kind}' ({len(d['parts'])} parts, {d['radius']} m wide, {d['height']} m tall)")
    tpl = template_for(kind, looks)
    if tpl:                                    # animals and vehicles: a body template, coloured like the design
        apply_template(d, kind, looks, tpl)
        log(f"[props] '{kind}' built as a {tpl[1]}")
    real_size(d, ollama, log)
    if ollama and d.get("parts") and d.get("source") != "imported" and not d.get("complex") and _prop_check_on():
        # every made prop - AI shapes or a body template (duck, van, ant) - is looked at; fails twice -> sprite
        d = look_checked(d, kind, looks, setting, ollama, log)
    if needs_picture(d):                       # 3D first: a picture only for complicated or shapeless objects
        add_sprite(d, comfy_cfg, log)
    if save and (d.get("by") == "ollama" or d.get("sprite") or d.get("animal") or d.get("vehicle")):
        _save(d)
    return d


# ----------------------------------------------------------------------------- does it look like what it is?
PROP_PASS = 6                                  # vision score (1-10) that counts as "looks like it"


def check_render(d, log=print):
    """A picture of the prop as the cutaway camera frames it (blender_build straight, no video). Path or None."""
    import os
    import shutil
    import subprocess
    import tempfile
    sys.path.insert(0, str(ROOT / "pipeline"))
    import run_episode as R
    import settings as S
    cfg = S.load_settings()
    tmp = Path(tempfile.mkdtemp(prefix="propcheck_"))
    try:
        who = d["kind"]
        ep = {"title": "", "set": "cafe", "start": "center", "music": "", "ambience": "", "co_stars": [],
              "_language": "en", "audio_lead": 0.0, "fps": 6, "render_res": [270, 480],
              "cast": {who: {"type": "thing", "def": d, "looks": d.get("looks", "")}},
              "shots": [{"action": "idle", "camera": "medium", "move": "static", "expression": "neutral",
                         "duration": 0.7, "line": "", "talk": 0.0, "lead": 0.0,
                         "events": [{"who": who, "do": "appear", "cutaway": True}]}]}
        ep["character"] = R.resolve_character(ep, cfg)
        (tmp / "ep.json").write_text(json.dumps(ep, default=str), encoding="utf-8")
        (tmp / "frames").mkdir()
        blender = os.environ.get("BLENDER", R.BLENDER_DEFAULT)
        r = subprocess.run([blender, "-b", "--factory-startup", "--python", str(ROOT / "pipeline" / "blender_build.py"),
                            "--", str(tmp / "ep.json"), str(tmp / "frames"), str(tmp / "scene.blend")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        pngs = sorted((tmp / "frames").glob("f_*.png"))
        if r.returncode != 0 or not pngs:
            log(f"[props] look check: render failed for '{who}'")
            return None
        out = Path(tempfile.gettempdir()) / f"propcheck_{who}_{int(time.time())}.png"
        shutil.copyfile(pngs[-1], out)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def look_score(d, ollama, log=print):
    """(score 1-10 or None, what's wrong): the vision model looks at the check render."""
    import base64
    import llm
    pic = check_render(d, log)
    if not pic:
        return None, ""
    try:
        r = llm.chat_json(ollama["url"], ollama.get("vision_model") or ollama["model"],
                          "You check simple low-poly 3D props (built from a few boxes, cylinders and spheres) in a "
                          "cartoon game. Be fair: chunky is fine, but someone must be able to tell what it is. Reply "
                          'with JSON only: {"score": 1 to 10 (6 = clearly recognisable), "problem": "what is wrong '
                          'or missing (empty if none)"}',
                          f"It should be: {d['kind'].replace('_', ' ')} ({d.get('looks') or ''})", 0.1,
                          images=[base64.b64encode(pic.read_bytes()).decode("ascii")])
        return max(1, min(10, int(float(r.get("score", 0))))), str(r.get("problem") or "")[:240]
    except Exception as exc:
        log(f"[props] look check unavailable ({exc.__class__.__name__})")
        return None, ""


def _prop_check_on():
    try:
        import settings as S
        return bool(S.load_settings()["sets"].get("prop_check", True))
    except Exception:
        return True


def look_checked(d, kind, looks, setting, ollama, log=print):
    """Check an AI design's look; if it fails, the AI redesigns it once from the critique; if that fails too, it
    becomes a drawn sprite (complex = True -> add_sprite). The best-scoring shape design is kept as the fallback."""
    import llm
    best = d
    for attempt in (1, 2):
        score, problem = look_score(d, ollama, log)
        if score is None:                      # no vision model / render: keep it as it is
            return best
        d["look_score"] = score
        log(f"[props] '{kind}' looks like it? {score}/10" + (f" - {problem}" if problem else ""))
        if score >= best.get("look_score", 0):
            best = d
        if score >= PROP_PASS:
            d["checked"] = True
            return d
        if attempt == 2:
            break
        user = (f"Object: {kind.replace('_', ' ')}\nWhat it looks like: {looks or kind.replace('_', ' ')}\n"
                + (f"It is part of this place: {setting}\n" if setting else "")
                + f"Your last design was checked and did NOT look like it: {problem or 'not recognisable'}. "
                  "Build it again so it clearly reads as this object.")
        try:
            nd = clean(llm.chat_json(ollama["url"], ollama["model"], GUIDE, user, temperature=0.6), kind, looks)
        except Exception:
            nd = None
        if not nd or len(nd["parts"]) < 2:
            break
        f = float(best.get("height", 1.0)) / max(0.05, float(nd["height"]))   # keep the real size already found
        for part in nd["parts"]:
            part["pos"] = [round(x * f, 3) for x in part["pos"]]
            part["size"] = [round(max(0.01, x * f), 3) for x in part["size"]]
        nd.update({k: best[k] for k in ("height", "width", "on", "size_checked", "place") if k in best})
        nd["radius"] = round(min(4.0, float(nd["radius"]) * f), 2)
        d = nd
    best = dict(best, checked=False, complex=True)   # failed twice: a drawn picture reads better than shapes
    log(f"[props] '{kind}' still doesn't look right - it gets a drawn picture (sprite) instead")
    return best


def redraw(kind, looks=None, log=print):
    """Draw a library prop again (optionally from a new description) - the Assets page's Redraw button."""
    import settings as S
    d = library().get(kind)
    if not d:
        raise SystemExit(f"no prop '{kind}' in the library")
    if looks:
        d["looks"] = str(looks)[:200]
    cfg = S.load_settings()
    if cfg["comfy"].get("mode", "auto") == "off":
        cfg["comfy"]["mode"] = "auto"            # an explicit redraw always asks ComfyUI
    old = LIB / f"{kind}.png"
    if old.exists():
        (LIB / ".trash").mkdir(exist_ok=True)
        old.replace(LIB / ".trash" / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.png")
    d.pop("sprite", None)
    from progress import report
    report(0.15, "Drawing with ComfyUI")
    add_sprite(d, cfg["comfy"], log, force=True)
    report(0.95, "Saving")
    if not d.get("sprite"):
        raise SystemExit("ComfyUI couldn't draw it (is ComfyUI running?) - the old picture is in assets/props/.trash")
    _save(d)
    log(f"[props] redrew '{kind}'")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import settings as S
    if len(sys.argv) > 2 and sys.argv[1] == "redraw":
        redraw(sys.argv[2], " ".join(sys.argv[3:]) or None)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "missing":     # draw a picture for every prop that has none yet
        from progress import report
        cfg = S.load_settings()["comfy"]
        lib = library()                                   # read once, not once per prop
        todo = [k for k, d in sorted(lib.items())
                if needs_picture(d) and not (d.get("sprite") and (ROOT / d["sprite"]).exists())]
        print(f"[props] {len(todo)} prop(s) without a picture", flush=True)
        for i, k in enumerate(todo):
            report(i / max(1, len(todo)), f"Drawing {k} ({i + 1}/{len(todo)})")
            d = lib[k]
            add_sprite(d, cfg, log=print, force=True)
            if d.get("sprite"):
                _save(d)
            else:
                print(f"[props] '{k}' still has no picture", flush=True)
        report(1.0, "Done")
        sys.exit(0)
    o = S.load_settings()["ollama"]
    print(json.dumps(design(sys.argv[1], " ".join(sys.argv[2:]), ollama=o, save=False), indent=1))
