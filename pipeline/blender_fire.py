"""Fire (2026-11-27, from an eerie explainer Reel): low-poly flames ON things, in the video's own flat look.

Shot "fire": the names burning in that shot (autodirect carries them from "[fire: window]" / "the car is on fire"
until "[fire: off]"). Each name is found like this:
- a cast thing ("cast_<name>"): the flames ride on it (parented), so they move and vanish with it;
- the set's props of that kind (all windows, the bed...): up to MAX_PROPS nearest to her;
- "here" or anything else: a ground fire beside her, in view.
Cast things named fire / flames / campfire / bonfire / inferno (run_episode gives them an ash disc + "fire") burn
whenever they're on screen.
A flame = a few tongues, each three cones (red outside, orange, a yellow core poking out towards the camera),
unlit like her toon materials, scaled and swayed every frame (a flicker), plus one orange point light that flickers.
Flat panels (a window on a wall) burn IN their face; solid things burn on top.
"""
import math
import random
import re

import bpy
from mathutils import Vector

B = None
MAX_PROPS = 4
LAYERS = (("#e8401a", 1.0, 1.0, 0.0), ("#ff8c1f", 0.68, 0.8, 0.45), ("#ffe04a", 0.36, 0.55, 0.8))
# (colour, width, height, how far towards the camera: a share of the outer radius - the core shows in front)
FLAME_THINGS = {"fire": 1.0, "flames": 1.0, "flame": 0.8, "blaze": 1.4, "inferno": 2.4, "campfire": 0.8,
                "bonfire": 1.6, "fireplace": 0.7, "torch": 0.35}
_MESH = None


def flame_size(name):
    """How tall a fire-named cast thing's flames are (m), or None when the name isn't a fire."""
    last = re.split(r"[_\s]+", str(name or "").lower())[-1]
    return FLAME_THINGS.get(last)


def _mesh():
    """One tongue: a five-sided cone that bulges a little and twists to a point (origin at its base)."""
    global _MESH
    if _MESH:
        return _MESH
    verts, faces, n = [], [], 5
    for k in range(n):
        a = math.tau * k / n
        verts.append((0.5 * math.cos(a), 0.5 * math.sin(a), 0.0))
    for k in range(n):
        a = math.tau * k / n + 0.5
        verts.append((0.42 * math.cos(a), 0.42 * math.sin(a), 0.35))
    verts.append((0.06, 0.0, 1.0))
    tip = len(verts) - 1
    for k in range(n):
        j = (k + 1) % n
        faces.append((k, j, n + j, n + k))
        faces.append((n + k, n + j, tip))
    faces.append(tuple(reversed(range(n))))
    me = bpy.data.meshes.new("flame")
    me.from_pydata(verts, [], faces)
    me.update()
    me.materials.append(None)
    _MESH = me
    return me


def _local_bounds(root):
    """The root's mesh descendants' bounds in the root's own space: (min, max) or None."""
    inv = root.matrix_world.inverted()
    lo, hi, found = Vector((1e9,) * 3), Vector((-1e9,) * 3), False
    for o in [root] + list(root.children_recursive):
        if o.type != "MESH" or o.name.startswith(("flame_", "shadow")):
            continue
        for c in o.bound_box:
            p = inv @ (o.matrix_world @ Vector(c))
            lo = Vector((min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)))
            hi = Vector((max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)))
            found = True
    return (lo, hi) if found else None


def _place(root, height=None):
    """Where the flames go on a thing, in its own space: [(x, y, z, width, height)] - one patch."""
    b = _local_bounds(root)
    sc = root.matrix_world.to_scale()
    s = max(1e-3, (abs(sc.x) + abs(sc.y) + abs(sc.z)) / 3)
    if height:                                        # a fire-named thing: flames of that size on its middle
        return [(0.0, 0.0, (b[1].z if b else 0.0) + 0.0, 0.8 * height / s, height / s)]
    if not b:
        return [(0.0, 0.0, 0.0, 0.8 / s, 1.0 / s)]
    lo, hi = b
    dx, dy, dz = hi.x - lo.x, hi.y - lo.y, hi.z - lo.z
    cx, cy = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
    if min(dx, dy) * s < 0.3 and dz * s > 0.4:        # a flat panel (a window on the wall): fire inside its face
        w = 0.8 * max(dx, dy)
        y = lo.y - 0.05 / s if dy <= dx else cy       # props face -y: just in front of the face
        x = cx if dy <= dx else lo.x - 0.05 / s
        return [(x, y, lo.z + 0.08 * dz, w, 0.75 * dz)]
    w = min(0.85 * max(dx, dy), 3.0 / s)
    h = max(0.4, min(1.8, 0.5 * min(max(dx, dy) * s, 2.0) + 0.3)) / s
    return [(cx, cy, hi.z - 0.04 * dz, w, h)]


def _burn(parent, patch, active, seed):
    """Tongues + a light for one patch, keyed on the frames it burns (scaled to nothing elsewhere)."""
    x, y, z, w, h = patch
    rng = random.Random(seed)
    n = max(1, min(6, round(w / max(0.25, h * 0.45))))
    keyed = [fr for fr in range(1, B.TOTAL + 1)
             if active[fr] or active[min(B.TOTAL + 1, fr + 1)] or active[max(0, fr - 1)] or fr == 1]
    me = _mesh()
    for k in range(n):
        off = (k + 0.5) / n - 0.5
        tw = w / n * 1.35 * rng.uniform(0.85, 1.15)
        th = h * (1.0 - 0.35 * abs(off) * 2) * rng.uniform(0.8, 1.1)
        ph = rng.uniform(0, math.tau)
        for li, (col, ws, hs, front) in enumerate(LAYERS):
            o = bpy.data.objects.new(f"flame_{seed}_{k}_{li}", me)
            B.scene.collection.objects.link(o)
            o.parent = parent
            slot = o.material_slots[0]
            slot.link = "OBJECT"
            slot.material = B.mat(col, True)
            base = Vector((x + off * w, y - front * tw * 0.45, z))
            for fr in keyed:
                t = (fr - 1) / B.FPS
                fl = 1 + 0.22 * math.sin(t * 9.0 + ph + li) + 0.12 * math.sin(t * 15.3 + ph * 2)
                sw = 0.14 * math.sin(t * 4.7 + ph) + 0.05 * math.sin(t * 11 + li)
                on = active[fr]
                o.location = base
                o.scale = ((tw * ws * (1.08 - 0.08 * fl), tw * ws * 0.8, th * hs * fl) if on else (1e-4,) * 3)
                o.rotation_euler = (sw * 0.6, sw, t * 1.7 + ph)
                o.keyframe_insert("location", frame=fr)
                o.keyframe_insert("scale", frame=fr)
                o.keyframe_insert("rotation_euler", frame=fr)
    li = bpy.data.lights.new(f"firelight_{seed}", "POINT")
    li.color = (1.0, 0.55, 0.2)
    try:
        li.use_shadow = False
        li.shadow_soft_size = 0.4
    except Exception:
        pass
    lo = bpy.data.objects.new(f"firelight_{seed}", li)
    B.scene.collection.objects.link(lo)
    lo.parent = parent
    lo.location = Vector((x, y - 0.3, z + h * 0.5))
    power = 140.0 * max(0.5, min(3.0, w * h))
    for fr in keyed:
        t = (fr - 1) / B.FPS
        li.energy = power * (1 + 0.25 * math.sin(t * 13 + seed) + 0.15 * math.sin(t * 7.1)) if active[fr] else 0.0
        li.keyframe_insert("energy", frame=fr)


def _props_named(name):
    """The set's prop roots of a kind ("window" finds base_window_l0 too), nearest to her first."""
    rx = re.compile(rf"^(imp_|base_|souv_)?[a-z0-9_]*{re.escape(name)}[a-z0-9_]*?\d+$")
    roots = [o for o in bpy.data.objects
             if o.type == "EMPTY" and o.parent is None and not o.name.startswith("cast_") and rx.match(o.name)]
    her = B.char_loc.get(1, Vector())
    roots.sort(key=lambda o: (o.matrix_world.translation - her).length)
    return roots[:MAX_PROPS]


def _ground_spot(first):
    """A ground fire for "here" / a name with nothing to burn: beside her and a little back, in view."""
    her = B.char_loc.get(first, Vector()).copy()
    e = bpy.data.objects.new("fire_spot", None)
    B.scene.collection.objects.link(e)
    e.location = Vector((her.x + 1.3, her.y + 1.4, 0.0))
    return e


def build(ns):
    global B
    B = ns
    shots = B.SHOTS
    if len(B.shot_info) < len(shots):
        return
    active = {}                                      # name -> [bool per frame]
    for si, shot in enumerate(shots):
        for name in shot.get("fire") or []:
            arr = active.setdefault(str(name).lower(), [False] * (B.TOTAL + 2))
            info = B.shot_info[si]
            for fr in range(info["f0"], min(B.TOTAL, info["f0"] + info["n"] - 1) + 1):
                arr[fr] = True
    cast = B.EP.get("cast") or {}
    for who, info in cast.items():                  # fire things burn whenever they're there (they scale with it)
        if isinstance(info, dict) and (info.get("def") or {}).get("fire"):
            active.setdefault(f"cast:{who}", [True] * (B.TOTAL + 2))
    if not active:
        return
    bpy.context.view_layer.update()
    seed = 0
    for name, arr in active.items():
        first = next((fr for fr in range(1, B.TOTAL + 1) if arr[fr]), 1)
        if name.startswith("cast:"):
            who = name[5:]
            root = bpy.data.objects.get(f"cast_{who}")
            if root:
                seed += 1
                h = (cast[who]["def"].get("flame_h") or flame_size(who) or 1.0)
                for patch in _place(root, height=h):
                    _burn(root, patch, arr, seed)
                print(f"[fire] {who}: a fire thing")
            continue
        slug = re.sub(r"[^a-z0-9_]+", "_", name).strip("_")
        roots = [bpy.data.objects[f"cast_{slug}"]] if f"cast_{slug}" in bpy.data.objects else []
        roots = roots or (_props_named(slug) if slug and slug != "here" else [])
        where = "cast thing" if roots and roots[0].name.startswith("cast_") else f"{len(roots)} set prop(s)"
        if not roots:
            roots, where = [_ground_spot(first)], "a ground fire beside her"
        for root in roots:
            seed += 1
            patches = [(0.0, 0.0, 0.0, 0.8, 1.0)] if root.name.startswith("fire_spot") else _place(root)
            for patch in patches:
                _burn(root, patch, arr, seed)
        print(f"[fire] {name}: {where}")
