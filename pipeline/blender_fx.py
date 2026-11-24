"""
Particle effects (rain, snow, droplets, bubbles, dust, sparkles, embers, petals, leaves, confetti, stars,
speed lines). Imported by blender_build.py after the characters are animated; B = blender_build's globals.

Each effect is a few dozen low-poly bits sharing one mesh, living in a box that follows the character (so the
effect is always in shot) and wrapping around inside it, so it never runs out. A shot picks its effects with
"particles" (a name or a list); the set's recipe can give a default ("particles" in sets/<id>.json).
Bits only exist (scale > 0) during the shots that use them.
"""
import math
import random

import json
from pathlib import Path

try:                                 # outside Blender (the web server reads FX + overrides) there's no mathutils
    from mathutils import Vector
except ImportError:
    Vector = None

OVERRIDES = Path(__file__).resolve().parent.parent / "assets" / "fx_overrides.json"

B = None

# name: shape, colours, count, box (w, d, h), velocity, wobble, size, unlit, spin, twinkle
FX = {
    "rain":        dict(shape="streak", colors=["#bcd6ff", "#9fc2f2"], n=150, box=(9, 8, 4.5), vel=(0.6, 0, -11), wob=0.0,
                        size=(0.015, 0.015, 0.32), unlit=True),
    "snow":        dict(shape="ico", colors=["#ffffff", "#eef4ff"], n=150, box=(9, 8, 4.0), vel=(0.2, 0, -0.9), wob=0.35,
                        size=(0.05,) * 3, unlit=True),
    "droplets":    dict(shape="uv", colors=["#d6ecff", "#bfe0ff", "#eaf6ff"], n=90, box=(7, 7, 3.5), vel=(0, 0, 0.15),
                        wob=0.25, size=(0.06,) * 3, unlit=True, rand_size=0.6),
    "bubbles":     dict(shape="uv", colors=["#cfefff", "#e6f8ff"], n=70, box=(7, 7, 4.0), vel=(0, 0, 0.9), wob=0.3,
                        size=(0.07,) * 3, unlit=True, rand_size=0.7),
    "dust":        dict(shape="cube", colors=["#d9c8a8", "#bfae90", "#f0e6d0"], n=120, box=(8, 7, 3.0), vel=(0.25, 0, -0.08),
                        wob=0.2, size=(0.03,) * 3, unlit=True),
    "specks":      dict(shape="cube", colors=["#2a2420", "#4a3a2a", "#ffffff"], n=110, box=(7, 6, 3.5), vel=(0, 0, -0.5),
                        wob=0.15, size=(0.03,) * 3, unlit=False, spin=3.0),
    "sparkles":    dict(shape="star", colors=["#fff6b0", "#ffffff", "#ffd6f0", "#c8f0ff"], n=90, box=(5, 5, 3.0),
                        vel=(0, 0, 0.2), wob=0.3, size=(0.08,) * 3, unlit=True, twinkle=True),
    "embers":      dict(shape="cube", colors=["#ff7a1a", "#ffb03a", "#ff4a1a"], n=90, box=(8, 7, 4.0), vel=(0.2, 0, 1.4),
                        wob=0.4, size=(0.03,) * 3, unlit=True, twinkle=True, spin=2.0),
    "petals":      dict(shape="quad", colors=["#ffb6d0", "#ffd0e0", "#ff9cc0", "#ffffff"], n=80, box=(9, 8, 4.0),
                        vel=(0.5, 0, -0.7), wob=0.6, size=(0.05, 0.035, 0.01), unlit=False, spin=4.0),
    "leaves":      dict(shape="quad", colors=["#e0902a", "#c8601a", "#d8b030", "#7fae3a"], n=70, box=(9, 8, 4.0),
                        vel=(0.6, 0, -0.9), wob=0.6, size=(0.07, 0.045, 0.01), unlit=False, spin=4.0),
    "confetti":    dict(shape="quad", colors=["#ff4a6a", "#ffd23a", "#3ad0ff", "#7aff6a", "#c86aff", "#ffffff"], n=160,
                        box=(7, 6, 4.0), vel=(0, 0, -1.3), wob=0.5, size=(0.04, 0.025, 0.01), unlit=True, spin=8.0),
    "beams":       dict(shape="streak", colors=["#f8ebc4", "#f3e4bb", "#fbf2d8"], n=22, box=(6, 6, 4.5),
                        vel=(0, 0, -0.35), wob=0.05, size=(0.018, 0.018, 1.4), unlit=True),
    "stars":       dict(shape="star", colors=["#ffffff", "#fff4c8", "#c8dcff"], n=120, box=(30, 6, 22), vel=(0, 0, 0),
                        wob=0.0, size=(0.16,) * 3, unlit=True, twinkle=True, depth=(16, 28)),
    "speed_lines": dict(floor=-4.0, shape="streak", colors=["#ffffff", "#eaf4ff"], n=45, box=(7, 7, 10), vel=(0, 0, 26), wob=0.0,
                        size=(0.012, 0.012, 1.1), unlit=True),
    "fireflies":   dict(shape="ico", colors=["#e8ff6a", "#fff3a0"], n=40, box=(7, 7, 2.6), vel=(0, 0, 0), wob=0.5,
                        size=(0.05,) * 3, unlit=True, twinkle=True),
    # --- added later: love hearts and friends
    "hearts":      dict(shape="heart", colors=["#ff4f8b", "#ff7fb0", "#ff2d6f", "#ffb3cf"], n=70, box=(8, 7, 4.0),
                        vel=(0.1, 0, 0.9), wob=0.35, size=(0.16, 0.02, 0.16), unlit=True, rand_size=0.5, spin=0.4),
    "music_notes": dict(shape="note", colors=["#5a3fd0", "#2f8fe0", "#e0408a", "#1f1f2e"], n=50, box=(8, 7, 4.0),
                        vel=(0.2, 0, 0.6), wob=0.5, size=(0.12, 0.02, 0.2), unlit=True, rand_size=0.4, spin=0.5),
    "coins":       dict(shape="disc", colors=["#ffd23a", "#f2b82a", "#ffe98a"], n=60, box=(7, 6, 4.0),
                        vel=(0, 0, -0.5), wob=0.25, size=(0.12, 0.02, 0.12), unlit=False, spin=5.0),
    "candy":       dict(shape="ico", colors=["#ffb3d9", "#b3f0ff", "#fff3a0", "#c9b3ff", "#b3ffc9"], n=60, box=(7, 6, 3.5),
                        vel=(0, 0, 0.1), wob=0.5, size=(0.06,) * 3, unlit=False, spin=2.0),
    "puffs":       dict(shape="ico", colors=["#ffffff", "#eef2ff", "#dfe6f5"], n=25, box=(9, 8, 3.5),
                        vel=(0.3, 0, 0.1), wob=0.3, size=(0.45,) * 3, unlit=True, rand_size=0.4),
    "sprinkles":   dict(shape="cube", colors=["#ff5fa2", "#5fd6ff", "#ffe04a", "#7dff8a", "#c77dff"], n=110, box=(7, 6, 3.5),
                        vel=(0, 0, -0.7), wob=0.2, size=(0.05, 0.012, 0.012), unlit=False, spin=5.0),
    "pixels":      dict(shape="cube", colors=["#ff4d6d", "#ffd23a", "#3ad0ff", "#7aff6a", "#c86aff"], n=120, box=(7, 7, 4.0),
                        vel=(0, 0, 0.5), wob=0.4, size=(0.04,) * 3, unlit=True, twinkle=True),
    "bolts":       dict(shape="streak", colors=["#fff27a", "#ffffff", "#ffe04a"], n=30, box=(8, 7, 4.0),
                        vel=(0, 0, -13), wob=0.0, size=(0.012, 0.012, 0.55), unlit=True, twinkle=True),
    "bats":        dict(shape="bat", colors=["#2a2233", "#3d2f4a"], n=22, box=(9, 8, 3.5), vel=(1.6, 0, 0.2),
                        wob=0.7, size=(0.32, 0.02, 0.22), unlit=True, rand_size=0.4),
    "paws":        dict(shape="paw", colors=["#ffb3cf", "#ffd0e0", "#ff9cc0", "#ffffff"], n=40, box=(8, 7, 3.5),
                        vel=(0, 0, 0.5), wob=0.4, size=(0.1, 0.02, 0.1), unlit=True, spin=1.5),
}
ALIASES = {"water": "droplets", "drops": "droplets", "raindrops": "rain", "bubble": "bubbles", "sparkle": "sparkles",
           "magic": "sparkles", "glitter": "sparkles", "fire": "embers", "sparks": "embers", "flowers": "petals",
           "blossom": "petals", "autumn": "leaves", "party": "confetti", "falling": "speed_lines", "speed": "speed_lines",
           "space": "stars", "seeds": "specks", "ash": "dust", "sand": "dust", "snowflakes": "snow",
           "love": "hearts", "heart": "hearts", "notes": "music_notes", "music": "music_notes", "note": "music_notes",
           "coin": "coins", "money": "coins", "candies": "candy", "sweets": "candy", "clouds": "puffs", "cloud": "puffs",
           "sprinkle": "sprinkles", "pixel": "pixels", "lightning": "bolts", "thunder": "bolts", "bat": "bats",
           "paw": "paws", "paw_prints": "paws"}


def overrides():
    try:
        return json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def effective(name, ov=None):
    """An effect's settings with the user's edits from the Assets page applied (colours, amount, speed, size)."""
    spec = dict(FX[name])
    o = (ov if ov is not None else overrides()).get(name) or {}
    cols = [c for c in (o.get("colors") or []) if isinstance(c, str) and len(c) == 7 and c.startswith("#")]
    if cols:
        spec["colors"] = cols
    amount = float(o.get("amount", 1.0) or 1.0)
    speed = float(o.get("speed", 1.0) or 1.0)
    size = float(o.get("size", 1.0) or 1.0)
    spec["n"] = max(4, min(600, int(round(spec["n"] * amount))))
    spec["vel"] = tuple(v * speed for v in spec["vel"])
    spec["wob"] = spec["wob"] * (0.5 + 0.5 * speed)
    spec["size"] = tuple(v * size for v in spec["size"])
    return spec


def norm(names):
    if not names:
        return []
    if isinstance(names, str):
        names = [n for n in names.replace(",", " ").split() if n]
    out = []
    for n in names:
        n = ALIASES.get(str(n).lower(), str(n).lower())
        if n in FX and n not in out:
            out.append(n)
    return out


def _ellipse(cx, cz, rx, rz, n=12):
    return [(cx + rx * math.cos(math.tau * i / n), cz + rz * math.sin(math.tau * i / n)) for i in range(n)]


def _heart():
    pts = []
    for i in range(20):
        t = math.tau * i / 20
        pts.append((16 * math.sin(t) ** 3, 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
    return [pts]


# flat cut-out shapes (lists of polygons in the x/z plane, facing the camera); scaled to fit when built
FLAT_SHAPES = {
    "heart": _heart,
    "note": lambda: [_ellipse(-0.18, -0.32, 0.2, 0.16), [(0.02, -0.3), (0.08, -0.3), (0.08, 0.45), (0.02, 0.45)],
                     [(0.08, 0.45), (0.3, 0.25), (0.08, 0.1)]],
    "disc": lambda: [_ellipse(0, 0, 0.5, 0.5, 10)],
    "bat": lambda: [_ellipse(0, 0, 0.12, 0.2, 8),
                    [(-0.1, 0.05), (-0.5, 0.3), (-0.42, -0.05), (-0.25, -0.12), (-0.12, -0.05)],
                    [(0.1, 0.05), (0.5, 0.3), (0.42, -0.05), (0.25, -0.12), (0.12, -0.05)],
                    [(-0.08, 0.15), (-0.12, 0.32), (-0.02, 0.2)], [(0.08, 0.15), (0.12, 0.32), (0.02, 0.2)]],
    "paw": lambda: [_ellipse(0, -0.15, 0.25, 0.2, 12)] + [_ellipse(x, z, 0.09, 0.09, 8)
                                                          for x, z in ((-0.26, 0.12), (-0.1, 0.3), (0.1, 0.3), (0.26, 0.12))],
}


def _flat_mesh(shape):
    import bmesh
    import bpy
    polys = FLAT_SHAPES[shape]()
    pts = [p for poly in polys for p in poly]
    ext = max(max(abs(x) for x, _ in pts), max(abs(z) for _, z in pts)) or 1.0
    bm = bmesh.new()
    for poly in polys:
        verts = [bm.verts.new((x / (2 * ext), 0.0, z / (2 * ext))) for x, z in poly]
        try:
            bm.faces.new(verts)
        except ValueError:                       # a duplicate corner: skip that piece
            pass
    me = bpy.data.meshes.new(f"fx_flat_{shape}")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(None)                # one material slot, like the primitive shapes (each object sets its own)
    return me


def _mesh(shape):
    """One shared low-poly mesh per shape, with one material slot that each object overrides."""
    import bpy
    if shape in FLAT_SHAPES:
        return _flat_mesh(shape)
    kw ={"cube": ("cube", {}), "ico": ("ico", {"subdivisions": 1}), "uv": ("uv", {"segments": 6, "ring_count": 4}),
          "streak": ("cube", {}), "quad": ("cube", {}), "star": ("ico", {"subdivisions": 1})}[shape]
    o = B.prim(kw[0], f"fx_proto_{shape}", (0, -400, -100), (1, 1, 1), **kw[1])
    me = o.data
    bpy.data.objects.remove(o)
    return me


def cam_at(fr):
    return B.CAM_POS.get(fr, B.char_loc.get(fr, Vector()) + Vector((0, -6, 2)))


WEATHER = {"snow", "rain", "droplets", "leaves", "petals"}    # never a set's default inside (a shot may ask)


def build(ns):
    global B
    B = ns
    import bpy
    recipe = B.EP.get("set_recipe") or {}
    default = norm(recipe.get("particles"))
    if recipe.get("indoor"):     # an indoor set's own weather (sets made before the check): no snow in a post office
        default = [n for n in default if n not in WEATHER]
    want = [norm(shot["particles"]) if "particles" in shot else default for shot in B.SHOTS]
    used = sorted({n for w in want for n in w})
    if not used:
        return
    meshes = {}
    ov = overrides()
    for name in used:
        spec = effective(name, ov)
        rng = random.Random(sum(map(ord, name)) * 7)
        if spec["shape"] not in meshes:
            meshes[spec["shape"]] = _mesh(spec["shape"])
        me = meshes[spec["shape"]]
        active = [False] * (B.TOTAL + 2)
        for si, info in enumerate(B.shot_info):
            if name in want[si]:
                for fr in range(info["f0"], min(B.TOTAL, info["f0"] + info["n"] - 1) + 1):
                    active[fr] = True
        # key the active frames plus one frame either side (where the bits switch on/off)
        keyed = [fr for fr in range(1, B.TOTAL + 1)
                 if active[fr] or active[min(B.TOTAL + 1, fr + 1)] or active[max(0, fr - 1)] or fr == 1]
        bw, bd, bh = spec["box"]
        depth = spec.get("depth")
        for i in range(spec["n"]):
            o = bpy.data.objects.new(f"fx_{name}{i}", me)
            B.scene.collection.objects.link(o)
            slot = o.material_slots[0]
            slot.link = "OBJECT"
            slot.material = B.mat(rng.choice(spec["colors"]), spec.get("unlit", True))
            s = Vector(spec["size"]) * max(0.3, 1 + spec.get("rand_size", 0.3) * rng.uniform(-0.5, 1.0))
            seed = Vector((rng.random(), rng.random(), rng.random()))
            spin = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * spec.get("spin", 0.0)
            vel = Vector(spec["vel"]) * rng.uniform(0.8, 1.2)
            ph = rng.uniform(0, math.tau)
            for fr in keyed:
                on = active[fr]
                t = (fr - 1) / B.FPS
                c = B.char_loc.get(fr, Vector()).copy()
                c.z = 0.0
                cam = cam_at(fr)
                look = (c - Vector((cam.x, cam.y, 0.0)))
                dist = max(1.5, look.length)
                fwd = look.normalized() if look.length > 1e-3 else Vector((0, 1, 0))
                if depth:                     # far background layer (stars), behind her as seen from the camera
                    mid = c + fwd * (depth[0] + depth[1]) / 2
                    size = Vector((bw, bw, bh))
                    corner = Vector((mid.x - bw / 2, mid.y - bw / 2, -4.0))
                else:                         # the space between the camera and a bit behind her
                    span = dist + 2.4
                    mid = Vector((cam.x, cam.y, 0.0)) + fwd * (1.8 + span / 2)
                    size = Vector((max(bw * 0.6, span * 0.9), max(bw * 0.6, span * 0.9), bh))
                    corner = Vector((mid.x - size.x / 2, mid.y - size.y / 2, spec.get("floor", -0.3)))
                # world-space position (so the bits don't slide along when she walks) ...
                w = Vector((seed.x * size.x + vel.x * t + spec["wob"] * math.sin(t * 1.7 + ph),
                            seed.y * size.y + vel.y * t + spec["wob"] * 0.5 * math.cos(t * 1.3 + ph),
                            seed.z * size.z + vel.z * t + spec["wob"] * 0.3 * math.sin(t * 2.1 + ph)))
                # ... wrapped into the box that follows her, so the effect never runs out
                o.location = Vector(((w.x - corner.x) % size.x, (w.y - corner.y) % size.y,
                                     (w.z - corner.z) % size.z)) + corner
                k = 0.45 + 0.55 * abs(math.sin(t * 3.1 + ph)) if spec.get("twinkle") else 1.0
                o.scale = tuple(s * k) if on else (1e-4, 1e-4, 1e-4)
                o.keyframe_insert("location", frame=fr)
                o.keyframe_insert("scale", frame=fr)
                if spec.get("spin"):
                    o.rotation_euler = tuple(spin * t)
                    o.keyframe_insert("rotation_euler", frame=fr)
        print(f"[fx] {name}: {spec['n']} bits, {sum(active)} frames")
