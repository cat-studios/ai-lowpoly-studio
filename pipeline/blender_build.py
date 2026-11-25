"""
Builds and renders one episode inside Blender (run headless by run_episode.py).

    blender -b --factory-startup --python blender_build.py -- resolved.json frames_dir [scene.blend]

Everything is procedural: the set, the placeholder catgirl, every animation and
every camera are generated from the episode JSON. Later, the placeholder can be
swapped for a real rigged model by mapping the same pose channels onto bones.
"""
import bpy
import json
import math
import os
import random
import sys
from pathlib import Path
from mathutils import Euler, Matrix, Quaternion, Vector

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402  (shared with the web app)

argv = sys.argv[sys.argv.index("--") + 1:]
with open(argv[0], encoding="utf-8") as fh:
    EP = json.load(fh)
FRAMES_DIR = argv[1]
BLEND_OUT = argv[2] if len(argv) > 2 else None

FPS = int(EP.get("fps", 30))
RES_X, RES_Y = EP.get("render_res", [216, 384])
SHOTS = EP["shots"]
scene = bpy.context.scene

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)


# --------------------------------------------------------------------------- helpers
def hexcol(h):
    """'#rrggbb' (sRGB) -> linear RGB tuple."""
    if not isinstance(h, str):
        return tuple(h)
    h = h.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def lerp(a, b, u):
    return a + (b - a) * u


def lerp_angle(a, b, u):
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + d * u


FOG = {"color": hexcol("#9ec4f0"), "start": 10.0, "end": 30.0}
_MATS = {}


def mat(color, unlit=False):
    color = hexcol(color)
    key = (tuple(round(c, 4) for c in color), unlit)
    if key in _MATS:
        return _MATS[key]
    m = bpy.data.materials.new(f"mat{len(_MATS)}")
    if m.node_tree is None:     # Blender < 5: nodes are off by default (5.x always has them; use_nodes goes in 6.0)
        m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    rgba = (*color, 1.0)
    if unlit:
        surf = N.new("ShaderNodeEmission")
        surf.inputs["Color"].default_value = rgba
        surf.inputs["Strength"].default_value = 1.0
    else:
        surf = N.new("ShaderNodeBsdfDiffuse")
        surf.inputs["Color"].default_value = rgba
    L.new(add_fog(N, L, surf.outputs[0]), out.inputs["Surface"])
    m.diffuse_color = rgba
    _MATS[key] = m
    return m


def add_fog(N, L, shader_socket):
    """N64-style distance fog: blend a shader toward the fog colour by camera distance."""
    fog = N.new("ShaderNodeEmission")
    fog.inputs["Color"].default_value = (*FOG["color"], 1.0)
    mix = N.new("ShaderNodeMixShader")
    cam = N.new("ShaderNodeCameraData")
    mr = N.new("ShaderNodeMapRange")
    mr.clamp = True
    mr.inputs["From Min"].default_value = FOG["start"]
    mr.inputs["From Max"].default_value = FOG["end"]
    L.new(cam.outputs["View Distance"], mr.inputs["Value"])
    L.new(mr.outputs["Result"], mix.inputs["Fac"])
    L.new(shader_socket, mix.inputs[1])
    L.new(fog.outputs[0], mix.inputs[2])
    return mix.outputs[0]


OPS = {
    "cube": bpy.ops.mesh.primitive_cube_add,
    "cyl": bpy.ops.mesh.primitive_cylinder_add,
    "cone": bpy.ops.mesh.primitive_cone_add,
    "ico": bpy.ops.mesh.primitive_ico_sphere_add,
    "uv": bpy.ops.mesh.primitive_uv_sphere_add,
    "plane": bpy.ops.mesh.primitive_plane_add,
}


def prim(kind, name, loc=(0, 0, 0), scale=(1, 1, 1), rot=(0, 0, 0), color="#ffffff",
         parent=None, unlit=False, **kw):
    OPS[kind](**kw)
    o = bpy.context.active_object
    o.name = name
    o.location = loc
    o.scale = scale
    o.rotation_euler = rot
    if parent is not None:
        o.parent = parent
    o.data.materials.append(mat(color, unlit))
    return o


def empty(name, parent=None, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    scene.collection.objects.link(e)
    e.empty_display_size = 0.1
    e.parent = parent
    e.location = loc
    return e


def checker(name, x0, x1, y0, y1, size, c1, c2, z=0.0):
    verts, faces, idx = [], [], []
    nx, ny = int((x1 - x0) / size), int((y1 - y0) / size)
    for i in range(nx):
        for j in range(ny):
            x, y, b = x0 + i * size, y0 + j * size, len(verts)
            verts += [(x, y, z), (x + size, y, z), (x + size, y + size, z), (x, y + size, z)]
            faces.append((b, b + 1, b + 2, b + 3))
            idx.append((i + j) % 2)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.materials.append(mat(c1))
    me.materials.append(mat(c2))
    for poly, mi in zip(me.polygons, idx):
        poly.material_index = mi
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    return o


def setup_world(ambient="#ffffff", ambient_strength=0.35):
    w = bpy.data.worlds.new("World")
    scene.world = w
    if w.node_tree is None:     # Blender < 5: nodes are off by default (5.x always has them; use_nodes goes in 6.0)
        w.use_nodes = True
    N, L = w.node_tree.nodes, w.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputWorld")
    seen = N.new("ShaderNodeBackground")      # what the camera sees: the fog colour
    seen.inputs["Color"].default_value = (*FOG["color"], 1)
    amb = N.new("ShaderNodeBackground")       # what lights the scene: flat ambient
    amb.inputs["Color"].default_value = (*hexcol(ambient), 1)
    amb.inputs["Strength"].default_value = ambient_strength
    global WORLD_NODES
    WORLD_NODES = (amb, seen)                 # kept so a shot's "light" can dim the ambient light and the sky
    lp = N.new("ShaderNodeLightPath")
    mix = N.new("ShaderNodeMixShader")
    L.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    L.new(amb.outputs[0], mix.inputs[1])
    L.new(seen.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs["Surface"])


def add_sun(rot=(0.9, 0.2, 0.6), strength=2.2, color="#ffffff"):
    ld = bpy.data.lights.new("sun", "SUN")
    ld.energy = strength
    ld.color = hexcol(color)
    try:
        ld.use_shadow = False   # N64 had no real-time shadows; we use a blob shadow
    except Exception:
        pass
    o = bpy.data.objects.new("sun", ld)
    scene.collection.objects.link(o)
    o.rotation_euler = rot


# --------------------------------------------------------------------------- sets
def set_cafe():
    FOG.update(color=hexcol("#e8c9a0"), start=9.0, end=24.0)
    setup_world("#fff0dd", 0.4)
    add_sun((0.8, 0.3, 0.5), 2.0, "#fff2e0")
    checker("floor", -7, 7, -7, 6, 1.0, "#d9b38c", "#8c5a3c")
    prim("cube", "wall_back", (0, 6.1, 2.5), (7, 0.1, 2.5), color="#f2d7b5")
    prim("cube", "wainscot_back", (0, 6.0, 0.6), (7, 0.05, 0.6), color="#a0623d")
    prim("cube", "wall_left", (-7.1, 0, 2.5), (0.1, 6.2, 2.5), color="#ecceaa")
    prim("cube", "wainscot_left", (-7.0, 0, 0.6), (0.05, 6.2, 0.6), color="#a0623d")
    prim("cube", "window", (-2.5, 5.98, 2.7), (1.4, 0.02, 0.8), color="#bfe6ff", unlit=True)
    prim("cube", "window_frame", (-2.5, 6.0, 2.7), (1.55, 0.02, 0.95), color="#ffffff")
    prim("cube", "door", (-6.95, -2.0, 1.2), (0.04, 0.7, 1.2), color="#6b3b22")
    prim("cube", "menu_board", (2.5, 5.98, 2.9), (1.6, 0.03, 0.7), color="#2e3a2e")
    for i, c in enumerate(["#ffd36b", "#ff8fb0", "#9fe0ff"]):
        prim("cube", f"menu_line{i}", (2.5, 5.93, 3.25 - i * 0.32), (1.1 - i * 0.2, 0.01, 0.05),
             color=c, unlit=True)
    # counter + espresso machine
    prim("cube", "counter", (2.5, 3.4, 0.55), (2.2, 0.45, 0.55), color="#8c5a3c")
    prim("cube", "counter_top", (2.5, 3.4, 1.13), (2.3, 0.55, 0.05), color="#f0e6da")
    prim("cube", "espresso", (3.4, 3.5, 1.5), (0.4, 0.3, 0.33), color="#c0c4cc")
    prim("cube", "espresso_top", (3.4, 3.5, 1.86), (0.42, 0.32, 0.04), color="#e04848")
    prim("cyl", "cup", (2.6, 3.2, 1.25), (0.07, 0.07, 0.08), color="#ffffff", vertices=8)
    # tables + stools
    for i, (x, y) in enumerate([(-3.0, 1.5), (-4.0, -3.5), (4.5, -2.5)]):
        prim("cyl", f"table_top{i}", (x, y, 0.95), (0.6, 0.6, 0.04), color="#f0e6da", vertices=10)
        prim("cyl", f"table_leg{i}", (x, y, 0.48), (0.06, 0.06, 0.46), color="#3a2a22", vertices=6)
        for k, a in enumerate((0.3, 2.6)):
            sx, sy = x + math.cos(a) * 0.95, y + math.sin(a) * 0.95
            prim("cyl", f"stool{i}_{k}", (sx, sy, 0.55), (0.25, 0.25, 0.05), color="#e05a5a", vertices=8)
            prim("cyl", f"stool_leg{i}_{k}", (sx, sy, 0.27), (0.04, 0.04, 0.27), color="#3a2a22", vertices=6)
    # hanging lamps
    for i, x in enumerate((-3.0, 0.5, 3.5)):
        prim("cone", f"lamp{i}", (x, 2.0, 4.1), (0.35, 0.35, 0.25), color="#ffe9a8", unlit=True, vertices=6)
        prim("cyl", f"cord{i}", (x, 2.0, 4.7), (0.015, 0.015, 0.4), color="#222222", vertices=4)
    # plants
    for i, (x, y) in enumerate([(-6.2, 5.2), (6.2, 5.2)]):
        prim("cyl", f"pot{i}", (x, y, 0.3), (0.3, 0.3, 0.3), color="#c96a3c", vertices=6)
        prim("ico", f"plant{i}", (x, y, 1.0), (0.55, 0.55, 0.7), color="#4caf50", subdivisions=1)
    return dict(catalog.SETS["cafe"]["marks"])


def set_park():
    FOG.update(color=hexcol("#a8d4ff"), start=8.0, end=34.0)
    setup_world("#e8f4ff", 0.4)
    add_sun((0.7, 0.2, 0.8), 2.2, "#fffbe8")
    prim("cyl", "ground", (0, 0, -0.05), (60, 60, 0.05), color="#5cbf4a", vertices=24)
    prim("cube", "path", (0, 4, 0.005), (1.0, 30, 0.01), color="#e0c38c")
    prim("cyl", "pond", (5.5, 6.0, 0.01), (2.2, 1.5, 0.01), color="#4aa0e8", vertices=10)
    rng = random.Random(7)
    placed = 0
    while placed < 45:
        x, y = rng.uniform(-30, 30), rng.uniform(-6, 40)
        if math.hypot(x, y) < 5 or abs(x) < 1.6 or math.hypot(x - 5.5, y - 6) < 3:
            continue
        s = rng.uniform(0.8, 1.6)
        prim("cyl", f"trunk{placed}", (x, y, 0.6 * s), (0.18 * s, 0.18 * s, 0.6 * s), color="#7a4a2a", vertices=5)
        prim("cone", f"leaves{placed}", (x, y, 2.1 * s), (1.0 * s, 1.0 * s, 1.2 * s),
             color=rng.choice(["#2e8b3e", "#3fa34d", "#267a36"]), vertices=6)
        placed += 1
    # one big hero tree near the "tree" mark
    prim("cyl", "hero_trunk", (-3.2, 4.8, 1.0), (0.3, 0.3, 1.0), color="#7a4a2a", vertices=6)
    prim("ico", "hero_leaves", (-3.2, 4.8, 2.8), (1.6, 1.6, 1.3), color="#3fa34d", subdivisions=1)
    for i, (x, y, s) in enumerate([(-18, 30, 8), (10, 34, 10), (28, 22, 7), (-30, 15, 6)]):
        prim("ico", f"hill{i}", (x, y, -s * 0.3), (s, s, s * 0.6), color="#4aa83c", subdivisions=1)
    prim("cube", "bench_seat", (2.8, 3.0, 0.5), (0.9, 0.3, 0.05), color="#b5651d")
    prim("cube", "bench_back", (2.8, 3.25, 0.85), (0.9, 0.04, 0.25), color="#b5651d")
    for i, dx in enumerate((-0.75, 0.75)):
        prim("cube", f"bench_leg{i}", (2.8 + dx, 3.0, 0.25), (0.05, 0.25, 0.25), color="#444444")
    for i in range(30):
        x, y = rng.uniform(-8, 8), rng.uniform(-3, 10)
        if abs(x) < 1.2:
            continue
        prim("ico", f"flower{i}", (x, y, 0.08), (0.08, 0.08, 0.08),
             color=rng.choice(["#ff6b9d", "#fff06b", "#ffffff", "#c36bff"]), unlit=True, subdivisions=1)
    prim("ico", "sky_sun", (-20, 60, 30), (4, 4, 4), color="#fff6b0", unlit=True, subdivisions=1)
    return dict(catalog.SETS["park"]["marks"])


SETS = {"cafe": set_cafe, "park": set_park}
if EP.get("set", "cafe") in SETS:
    MARKS = SETS[EP.get("set", "cafe")]()
elif EP.get("set_recipe"):            # generated set (sets/<id>.json), embedded by run_episode.py
    import types
    import blender_sets
    MARKS = blender_sets.build(EP["set_recipe"], types.SimpleNamespace(
        prim=prim, empty=empty, mat=mat, add_fog=add_fog, hexcol=hexcol, FOG=FOG,
        setup_world=setup_world, add_sun=add_sun, scene=scene))
else:
    raise SystemExit(f"Unknown set '{EP.get('set')}'. Built-in: {', '.join(SETS)}; generated sets live in sets/")


# --------------------------------------------------------------------------- character
DEFAULT_LOOK = {"hair": "#ff8fc8", "skin": "#ffdcc6", "dress": "#2b2f73", "apron": "#ffffff",
                "eyes": "#5a1f7a", "shoes": "#4a2a1f", "inner_ear": "#ffc0d8", "mouth": "#8a2a3a"}
HIP_Z = 0.57


class Rig:
    pass


GROUND_Z = 0.0


def make_shadow(radius, name="blob_shadow"):
    """A blob shadow that stays on the ground (not parented to the character, so it doesn't jump with her)."""
    o = prim("cyl", name, (0, 0, GROUND_Z + 0.012), (radius, radius, 0.005), color="#222222", unlit=True, vertices=12)
    o["r"] = radius
    return o


def write_shadow(shadow, loc, fr, base_z=None):
    """Follow x/y on the ground; shrink while the owner is in the air (higher = smaller)."""
    ground = GROUND_Z if base_z is None else base_z
    h = max(0.0, loc[2] - ground)
    f = 1.0 / (1.0 + 0.8 * h)
    shadow.location = (loc[0], loc[1], ground + 0.012)
    r = shadow["r"] * f
    shadow.scale = (r, r, 0.005)
    shadow.keyframe_insert("location", frame=fr)
    shadow.keyframe_insert("scale", frame=fr)


def build_catgirl(look, cat=True):
    """The placeholder body. cat=False = a plain person for the rest of the cast (no ears, tail, apron);
    look may then have "pants" (trousers instead of a skirt)."""
    c = {**DEFAULT_LOOK, **(look or {})}
    pants = c.get("pants") if not cat else None
    R = Rig()
    R.root = empty("char_root" if cat else "cast_root")
    R.shadow = make_shadow(0.34)
    R.hips = empty("hips", R.root, (0, 0, HIP_Z))
    R.legs = []
    for side, x in (("L", 0.1), ("R", -0.1)):
        p = empty(f"leg_{side}", R.hips, (x, 0, 0))
        prim("cyl", f"legmesh_{side}", (0, 0, -0.27), (0.065, 0.065, 0.27), color=pants or c["skin"], parent=p, vertices=6)
        if cat:
            prim("cube", f"sock_{side}", (0, 0, -0.42), (0.072, 0.072, 0.1), color=c["apron"], parent=p)
        prim("cube", f"shoe_{side}", (0, -0.04, -0.54), (0.08, 0.12, 0.04), color=c["shoes"], parent=p)
        R.legs.append(p)
    R.torso = empty("torso", R.hips)
    if pants:
        prim("cyl", "shorts", (0, 0, 0.02), (0.19, 0.15, 0.1), color=pants, parent=R.torso, vertices=8)
    else:
        prim("cone", "skirt", (0, 0, 0.0), (0.32, 0.3, 0.24), color=c["dress"], parent=R.torso, vertices=8,
             radius1=1, radius2=0.5, depth=2)
    if cat:
        prim("cone", "apron", (0, -0.03, 0.0), (0.27, 0.28, 0.22), color=c["apron"], parent=R.torso, vertices=8,
             radius1=1, radius2=0.5, depth=2)
    prim("cyl", "chest", (0, 0, 0.38 if not pants else 0.3), (0.15, 0.13, 0.15 if not pants else 0.24),
         color=c["dress"], parent=R.torso, vertices=8)
    if cat:
        prim("cube", "bow", (0, -0.14, 0.47), (0.07, 0.02, 0.035), color="#e04870", parent=R.torso)
    R.arms = []
    for side, x in (("L", 0.19), ("R", -0.19)):
        p = empty(f"arm_{side}", R.torso, (x, 0, 0.5))
        prim("cyl", f"sleeve_{side}", (0, 0, -0.08), (0.06, 0.06, 0.09), color=c["dress"], parent=p, vertices=6)
        prim("cyl", f"armmesh_{side}", (0, 0, -0.26), (0.042, 0.042, 0.13), color=c["skin"], parent=p, vertices=6)
        hobj = prim("ico", f"hand_{side}", (0, 0, -0.42), (0.055, 0.055, 0.055), color=c["skin"], parent=p, subdivisions=1)
        if side == "R":
            R.hand = (hobj, "")
        R.arms.append(p)
    R.neck = empty("neck", R.torso, (0, 0, 0.56))
    hd = R.neck
    prim("ico", "head", (0, 0, 0.27), (0.27, 0.26, 0.26), color=c["skin"], parent=hd, subdivisions=2)
    prim("ico", "hair", (0, 0.07, 0.33), (0.29, 0.27, 0.27), color=c["hair"], parent=hd, subdivisions=1)
    prim("cube", "bangs", (0, -0.2, 0.43), (0.23, 0.06, 0.07), color=c["hair"], parent=hd, rot=(0.35, 0, 0))
    prim("cube", "hair_back", (0, 0.2, 0.08), (0.24, 0.08, 0.3), color=c["hair"], parent=hd)
    for side, x in (("L", 1), ("R", -1)):
        prim("cube", f"side_lock_{side}", (0.24 * x, -0.06, 0.12), (0.05, 0.07, 0.2), color=c["hair"], parent=hd)
    # face
    R.eyes, R.brows, R.brow_z = [], [], 0.37
    for side, x in (("L", 0.1), ("R", -0.1)):
        e = empty(f"eye_{side}", hd, (x, -0.235, 0.24))
        prim("uv", f"eyeball_{side}", (0, 0, 0), (0.055, 0.03, 0.08), color=c["eyes"], parent=e,
             unlit=True, segments=8, ring_count=6)
        prim("ico", f"eye_hi_{side}", (0.018 if x > 0 else -0.018, -0.022, 0.03), (0.018, 0.01, 0.018),
             color="#ffffff", parent=e, unlit=True, subdivisions=1)
        R.eyes.append(e)
        b = empty(f"brow_{side}", hd, (x, -0.245, R.brow_z))
        prim("cube", f"browmesh_{side}", (0, 0, 0), (0.05, 0.01, 0.011), color="#5a2a40", parent=b, unlit=True)
        R.brows.append(b)
        prim("uv", f"blush_{side}", (x * 1.7, -0.225, 0.16), (0.04, 0.01, 0.022), color="#ff9db5", parent=hd,
             unlit=True, segments=6, ring_count=4)
    R.mouth = empty("mouth", hd, (0, -0.258, 0.13))
    prim("cube", "mouthmesh", (0, 0, 0), (0.06, 0.012, 0.016), color=c["mouth"], parent=R.mouth, unlit=True)
    # cat ears
    R.ears = []
    for side, x in ((("L", 1), ("R", -1)) if cat else ()):
        p = empty(f"ear_{side}", hd, (0.15 * x, 0.04, 0.5))
        prim("cone", f"earmesh_{side}", (0, 0, 0.1), (0.1, 0.07, 0.12), color=c["hair"], parent=p, vertices=4,
             rot=(0, 0, math.pi / 4))
        prim("cone", f"earinner_{side}", (0, -0.03, 0.08), (0.06, 0.03, 0.08), color=c["inner_ear"], parent=p,
             vertices=4, rot=(0, 0, math.pi / 4))
        R.ears.append(p)
    # tail (3 segment chain)
    R.tail = []
    parent, loc = R.hips, (0, 0.22, 0.02)
    for i in range(3 if cat else 0):
        p = empty(f"tail{i}", parent, loc)
        col = "#ffffff" if i == 2 else c["hair"]
        prim("cyl", f"tailmesh{i}", (0, 0, 0.13), (0.04, 0.04, 0.13), color=col, parent=p, vertices=6)
        R.tail.append(p)
        parent, loc = p, (0, 0, 0.26)
    # camera aim points
    R.aim_head = empty("aim_head", R.neck, (0, 0, 0.2))   # follows head when she leans
    R.aim_body = empty("aim_body", R.root, (0, 0, 0.95))
    return R


# --------------------------------------------------------------------------- real model (VRoid)
# Pose channels are rotations about world-aligned axes (character faces -Y), exactly like the
# placeholder's pivots. They are converted into each bone's local space, so every animation
# written for the placeholder drives the real skeleton unchanged.
BONES = {
    "hips": "J_Bip_C_Hips", "spine": "J_Bip_C_Spine", "chest": "J_Bip_C_Chest",
    "neck": "J_Bip_C_Neck", "head": "J_Bip_C_Head",
    "armL": "J_Bip_L_UpperArm", "armR": "J_Bip_R_UpperArm",
    "forearmL": "J_Bip_L_LowerArm", "forearmR": "J_Bip_R_LowerArm", "handL": "J_Bip_L_Hand", "handR": "J_Bip_R_Hand",
    "legL": "J_Bip_L_UpperLeg", "legR": "J_Bip_R_UpperLeg", "kneeL": "J_Bip_L_LowerLeg", "kneeR": "J_Bip_R_LowerLeg",
    "earL": "J_Opt_L_CatEar2_01", "earR": "J_Opt_R_CatEar2_01",
}
# expression -> VRoid face shape keys (Face mesh)
FACE = {
    "neutral":   {},
    "happy":     {"Fcl_EYE_Joy": 1.0, "Fcl_BRW_Joy": 1.0, "Fcl_MTH_Joy": 0.6},
    "surprised": {"Fcl_EYE_Surprised": 1.0, "Fcl_BRW_Surprised": 1.0, "Fcl_MTH_Surprised": 0.8},
    "angry":     {"Fcl_EYE_Angry": 1.0, "Fcl_BRW_Angry": 1.0, "Fcl_MTH_Angry": 0.7},
    "sad":       {"Fcl_EYE_Sorrow": 1.0, "Fcl_BRW_Sorrow": 1.0, "Fcl_MTH_Sorrow": 0.6},
    "smug":      {"Fcl_EYE_Fun": 0.8, "Fcl_BRW_Fun": 1.0, "Fcl_MTH_Fun": 0.8},
    "scared":    {"Fcl_EYE_Surprised": 0.7, "Fcl_BRW_Sorrow": 1.0, "Fcl_MTH_Small": 0.6},
}
EYES_CLOSED_EXPR = {"happy"}   # don't blink over closed "^^" eyes


def attach_to_bone(obj, arm, bone_name, world_loc):
    """Parent obj to a bone, keeping it at world_loc in the rest pose."""
    bpy.context.view_layer.update()
    pb = arm.pose.bones[bone_name]
    obj.parent, obj.parent_type, obj.parent_bone = arm, "BONE", bone_name
    obj.matrix_parent_inverse = (arm.matrix_world @ pb.matrix @ Matrix.Translation((0, pb.bone.length, 0))).inverted()
    obj.location = world_loc


class VRoidRig:
    def __init__(self, path, look):
        look = look or {}
        with bpy.data.libraries.load(str(path), link=False) as (src, dst):
            dst.collections = ["Character"]
        coll = dst.collections[0]
        scene.collection.children.link(coll)
        self.arm = next(o for o in coll.objects if o.type == "ARMATURE")
        self.face = next((o for o in coll.objects if o.type == "MESH" and o.data.shape_keys), None)
        for o in coll.objects:
            if o.type != "MESH":
                continue
            for slot in o.material_slots:
                m = slot.material
                if m and m.node_tree and "fog_in" in m.node_tree.nodes:
                    sock = m.node_tree.nodes["fog_in"].inputs[2]
                    if sock.links and not m.get("fogged"):
                        src_sock = sock.links[0].from_socket
                        m.node_tree.links.new(add_fog(m.node_tree.nodes, m.node_tree.links, src_sock), sock)
                        m["fogged"] = True
        self.root = empty("char_root")
        self.arm.parent = self.root
        self.shadow = make_shadow(0.3)
        bones = self.arm.data.bones
        B = dict(BONES)
        B.update(self._find_ears(bones, look.get("ear_bones")))
        missing = [b for b in B.values() if b not in bones]
        if missing:
            print(f"[build] warning: rig is missing bones {missing}; those channels are skipped")
        print(f"[build] ear bones: {B['earL']} / {B['earR']}")
        self.pb = {k: self.arm.pose.bones[b] for k, b in B.items() if b in bones}
        for p in self.pb.values():
            p.rotation_mode = "QUATERNION"
        # rest orientation of each bone in world space (armature sits at the origin)
        self.rest = {k: p.bone.matrix_local.to_quaternion() for k, p in self.pb.items()}
        # T-pose -> arms down: rotation taking the rest arm direction to straight down
        self.arm_down = {}
        for side in "LR":
            ua, hand = bones[B["arm" + side]], bones.get(B["hand" + side])
            d = ((hand.head_local if hand else ua.tail_local) - ua.head_local).normalized()
            self.arm_down[side] = d.rotation_difference(Vector((0, 0, -1)))
        hips = bones[B["hips"]].head_local
        head = bones[B["head"]].head_local
        self.hip_h = hips.z
        try:
            ul, ll = bones[B["legL"]].head_local, bones[B["kneeL"]].head_local
            foot = bones.get("J_Bip_L_Foot")
            self.thigh = (ll - ul).length
            self.shin = ((foot.head_local if foot else bones[B["kneeL"]].tail_local) - ll).length
        except Exception:
            self.thigh = self.shin = hips.z * 0.48
        self.face_now = {}
        self.hand = (self.arm, B["handR"] if B["handR"] in bones else B["armR"])   # what held things follow
        self.height = head.z + 0.25
        # aim points for the cameras
        self.aim_head = empty("aim_head")
        attach_to_bone(self.aim_head, self.arm, BONES["head"], Vector((0, 0, head.z + 0.08)))
        self.aim_body = empty("aim_body", self.root, (0, 0, hips.z + 0.05))
        # procedural tail (the VRoid model has no tail bones) - set "tail": false to disable
        self.tail = []
        if look.get("tail", True):
            col = look.get("tail_color", "#f2b8cf")
            parent = empty("tail_base")
            attach_to_bone(parent, self.arm, BONES["hips"], Vector((0, hips.y + 0.11, hips.z - 0.07)))
            for i in range(3):
                p = empty(f"tail{i}", parent, (0, 0, 0) if i == 0 else (0, 0, 0.2))
                prim("cyl", f"tailmesh{i}", (0, 0, 0.1), (0.032 - i * 0.004, 0.032 - i * 0.004, 0.1),
                     color="#ffffff" if i == 2 and look.get("tail_tip", True) else col, parent=p, vertices=6)
                self.tail.append(p)
                parent = p
        self.keys = self.face.data.shape_keys.key_blocks if self.face else {}
        self.used_keys = sorted({k for ex in FACE.values() for k in ex} |
                                {"Fcl_EYE_Close", "Fcl_MTH_A", "Fcl_MTH_O"})
        self.used_keys = [k for k in self.used_keys if k in self.keys]

    @staticmethod
    def _find_ears(bones, override=None):
        """Ear bones: profile override, else any non-zero-length bone with 'ear' in its name under the
        head (VRoid cat/dog/bunny ear accessories), closest to the head, one per side."""
        if override:
            return {"earL": override.get("L", ""), "earR": override.get("R", "")}
        out = {}
        for side, key in (("L", "earL"), ("R", "earR")):
            cands = []
            for b in bones:
                n = b.name.lower()
                if "ear" not in n or "head" in n or "hear" in n or (b.tail_local - b.head_local).length < 1e-4:
                    continue
                tag = f"_{side.lower()}_" in n or n.endswith(f"_{side.lower()}") or f".{side.lower()}" in n
                if not tag:   # no side in the name: decide by position (character's left is +X)
                    tag = (b.head_local.x > 0) == (side == "L")
                if tag:
                    depth, p = 0, b.parent
                    while p and "head" not in p.name.lower():
                        depth, p = depth + 1, p.parent
                    if p:
                        cands.append((depth, b.name))
            if cands:
                out[key] = min(cands)[1]
        return out

    def _set(self, name, q_world, fr):
        if name not in self.pb:
            return
        r = self.rest[name]
        self.pb[name].rotation_quaternion = r.inverted() @ q_world @ r
        self.pb[name].keyframe_insert("rotation_quaternion", frame=fr)

    def write(self, p, fr):
        E = lambda x, y, z: Euler((x, y, z), "XYZ").to_quaternion()
        self.root.location = p["loc"]
        self.root.rotation_euler = (0, 0, p["yaw"])
        self.root.keyframe_insert("location", frame=fr)
        self.root.keyframe_insert("rotation_euler", frame=fr)
        write_shadow(self.shadow, p["loc"], fr)
        leg_ik(p, self.thigh, self.shin)
        hp = self.pb["hips"]
        sh = p.get("shift", 0.0)
        hp.location = self.rest["hips"].inverted() @ Vector((sh, 0, p["bob"]))
        hp.keyframe_insert("location", frame=fr)
        half = E(p["lean"] / 2, p["sway"] / 2, p["twist"] / 2)
        self._set("spine", half, fr)
        self._set("chest", half, fr)
        self._set("neck", E(p["nod"] * 0.3, p["tilt"] * 0.3, p["turn"] * 0.3), fr)
        self._set("head", E(p["nod"] * 0.7, p["tilt"] * 0.7, p["turn"] * 0.7), fr)
        for side, sgn in (("L", -1), ("R", 1)):
            down = self.arm_down[side]
            # rot = upper-arm rotation about its own axis: turns the elbow so the forearm bends up/out, not forward
            spin = Quaternion((0, 0, 1), -sgn * p.get("rot" + side, 0.0))
            self._set("arm" + side, E(p["arm" + side], sgn * p["raise" + side], 0) @ spin @ down, fr)
            bend = -0.25 - p.get("elbow" + side, 0.0)          # relaxed elbow, forward
            self._set("forearm" + side, down.inverted() @ E(bend, 0, 0) @ down, fr)
            roll = math.asin(clamp(sh / max(0.2, self.thigh + self.shin), -0.5, 0.5))   # feet stay put
            self._set("leg" + side, E(p["leg" + side], roll, 0), fr)
            self._set("knee" + side, E(p.get("knee" + side, 0.0), 0, 0), fr)
            self._set("ear" + side, E(-p["ear" + side], (p["ear_spread"] - 0.25) * -sgn, 0), fr)
        tg = (fr - 1) / FPS
        base = [-1.2 + 0.6 * p["tail_lift"], 0.45, 0.35]
        for i, o in enumerate(self.tail):
            o.rotation_euler = (base[i], (0.3 + p["tail_sway"]) * math.sin(tg * 2.4 * p["tail_speed"] + i * 0.8), 0)
            o.keyframe_insert("rotation_euler", frame=fr)
        # face
        vals = dict.fromkeys(self.used_keys, 0.0)
        for k, v in FACE.get(p.get("expr", "neutral"), {}).items():
            if k in vals:
                vals[k] = v
        if p.get("blink") and p.get("expr") not in EYES_CLOSED_EXPR and "Fcl_EYE_Close" in vals:
            vals["Fcl_EYE_Close"] = 1.0
        if p.get("talk_amt") and "Fcl_MTH_A" in vals:
            vals["Fcl_MTH_A"] = max(vals["Fcl_MTH_A"], 0.9 * p["talk_amt"])
            if "Fcl_MTH_O" in vals:
                vals["Fcl_MTH_O"] = 0.3 * p["talk_amt"] * (1 + math.sin(tg * 5)) / 2
        for k, v in vals.items():       # ease between expressions instead of popping (blinks stay quick)
            prev = self.face_now.get(k, v)
            rate = 0.75 if k in ("Fcl_EYE_Close", "Fcl_MTH_A", "Fcl_MTH_O") else 0.3
            v = prev + (v - prev) * rate
            self.face_now[k] = v
            kb = self.keys[k]
            kb.value = v
            kb.keyframe_insert("value", frame=fr)


def pick_model():
    """run_episode.py resolves the character profile; "model" is an absolute .blend or "placeholder"."""
    look = EP.get("character") or {}
    m = look.get("model") if isinstance(look, dict) else None
    if not m or m == "placeholder":
        return None
    p = Path(m) if Path(m).is_absolute() else PROJECT / m
    if not p.exists():
        raise SystemExit(f"Character model not found: {p}")
    return p


_model = pick_model()
if _model:
    print(f"[build] character: {_model.name}")
    RIG = VRoidRig(_model, EP.get("character"))
else:
    print("[build] character: placeholder")
    RIG = build_catgirl(EP.get("character"))


# --------------------------------------------------------------------------- poses & animations
def default_pose():
    # relaxed stance: arms slightly away from the body and a touch forward, soft elbows
    return dict(loc=Vector(), yaw=0.0, bob=0.0, lean=0.0, twist=0.0, sway=0.0, shift=0.0,
                legL=0.0, legR=0.0, armL=-0.06, armR=-0.06, raiseL=0.16, raiseR=0.16, elbowL=0.12, elbowR=0.12,
                rotL=0.0, rotR=0.0,
                nod=0.0, tilt=0.0, turn=0.0, earL=0.0, earR=0.0, ear_spread=0.25,
                tail_lift=0.0, tail_sway=0.0, tail_speed=1.0,
                eye=[1.0, 1.0], brow=0.0, brow_up=0.0, mouth=[1.0, 1.0],
                kneeL=0.0, kneeR=0.0, expr="neutral", blink=False, talk_amt=0.0)


def env(t, T, seg, r=0.25):
    """0->1->0 weight for an action. Only ramps at the very start/end of the video: between actions the
    Smoother springs from one pose into the next (no dip back to a neutral pose in between)."""
    a = 1.0 if seg["prev_same"] else smooth(t / r)
    b = 1.0 if seg["next_same"] else smooth((T - t) / r)
    return min(a, b)


def wob(t, f, ph=0.0):
    """Smooth organic noise: two incommensurate sines (never repeats exactly)."""
    return 0.65 * math.sin(t * f + ph) + 0.35 * math.sin(t * f * 2.31 + ph * 1.7 + 1.3)


def hip_height():
    return float(getattr(RIG, "hip_h", HIP_Z))


# --------------------------------------------------------------------------- the smoother (follow-through)
SPRINGS = {   # channel: (frequency Hz, damping ratio). Lower damping = more overshoot / bounce
    "raiseL": (3.2, 0.72), "raiseR": (3.2, 0.72), "armL": (3.2, 0.72), "armR": (3.2, 0.72),
    "elbowL": (3.8, 0.7), "elbowR": (3.8, 0.7), "rotL": (3.2, 0.8), "rotR": (3.2, 0.8),
    "nod": (3.0, 0.85), "tilt": (2.6, 0.85), "turn": (2.8, 0.85),
    "lean": (2.4, 0.9), "sway": (2.2, 0.9), "twist": (2.6, 0.85), "shift": (2.0, 1.0), "bob": (6.0, 0.9),
    "legL": (7.0, 0.95), "legR": (7.0, 0.95), "kneeL": (7.0, 0.95), "kneeR": (7.0, 0.95),
    "earL": (5.0, 0.4), "earR": (5.0, 0.4), "ear_spread": (4.0, 0.5), "tail_lift": (2.5, 0.5),
}


class Smoother:
    """Critically-damped-ish springs on the pose channels: joints lag, overshoot a little and settle, and one
    action blends into the next. Locomotion legs bypass it (p['raw_legs']) so feet don't slide."""

    def __init__(self):
        self.x, self.v = {}, {}

    def apply(self, p):
        dt = 1.0 / FPS / 4
        for ch, (f, z) in SPRINGS.items():
            target = p[ch]
            if ch not in self.x:
                self.x[ch], self.v[ch] = target, 0.0
                continue
            if p.get("raw_legs") and ch in ("legL", "legR", "kneeL", "kneeR", "bob", "shift"):
                self.x[ch], self.v[ch] = target, 0.0
                continue
            w = 2 * math.pi * f
            x, v = self.x[ch], self.v[ch]
            for _ in range(4):
                v += (w * w * (target - x) - 2 * z * w * v) * dt
                x += v * dt
            self.x[ch], self.v[ch] = x, v
            p[ch] = x


def leg_ik(p, thigh, shin):
    """Lowering the hips (bob < 0) bends the knees so the feet stay on the floor instead of sinking."""
    if p.get("no_ik"):
        return
    drop = min(0.0, p["bob"])
    if drop > -1e-4:
        return
    L1, L2 = thigh, shin
    D = max(0.25 * (L1 + L2), L1 + L2 + drop)
    k = math.pi - math.acos(clamp((L1 * L1 + L2 * L2 - D * D) / (2 * L1 * L2), -1.0, 1.0))
    a = math.acos(clamp((L1 * L1 + D * D - L2 * L2) / (2 * L1 * D), -1.0, 1.0))
    for s in "LR":
        p["leg" + s] -= a
        p["knee" + s] += k
    p["lean"] += 0.35 * a          # lean in a little to stay balanced


# --------------------------------------------------------------------------- animations
def a_idle(p, t, T, seg):
    """Alive standing: slow weight shift onto one leg (the other knee relaxes), chest counter-sway,
    a drifting head and a little arm movement. Seeded per segment so two idles never match."""
    ph = (seg["f0"] % 97) * 0.37
    sh = 0.022 * wob(t, 0.55, ph)
    p["shift"] += sh
    p["kneeL"] += max(0.0, -sh) * 5.0
    p["kneeR"] += max(0.0, sh) * 5.0
    p["sway"] -= sh * 2.2
    p["tilt"] += 0.035 * wob(t, 0.7, ph + 2) + sh * 1.2
    p["turn"] += 0.05 * wob(t, 0.42, ph + 3)
    p["nod"] += 0.025 * wob(t, 0.6, ph + 4)
    p["raiseL"] += 0.025 * wob(t, 0.9, ph + 5)
    p["raiseR"] += 0.025 * wob(t, 0.8, ph + 6)
    p["armL"] += 0.03 * wob(t, 0.75, ph + 7)
    p["armR"] += 0.03 * wob(t, 0.7, ph + 8)
    p["calm"] = True


def _trap(u, r=0.22):
    """Distance covered (0..1) for a trapezoid speed profile with ramps r: ease in, cruise, ease out."""
    u = clamp(u)
    vmax = 1.0 / (1.0 - r)
    if u < r:
        return 0.5 * vmax * u * u / r
    if u > 1 - r:
        w = 1 - u
        return 1.0 - 0.5 * vmax * w * w / r
    return 0.5 * vmax * r + vmax * (u - r)


def _speed(u, r=0.22):
    u = clamp(u)
    return min(1.0, u / r, (1 - u) / r) if 0 < u < 1 else 0.0


def _locomote(p, t, T, seg, stride, amp, bob, lean, crouch=0.0, arms=0.7):
    """Walk/run/sneak. Steps are driven by the distance covered (no foot sliding), speed eases in and out,
    hips drop at each footfall, the chest counter-twists against the legs and the head stays steady."""
    p0, p1 = seg["p0"], seg["p1"]
    d = p1 - p0
    dist = d.length
    tin, tout = min(0.25, T * 0.2), min(0.3, T * 0.2)
    if dist < 1e-3:
        u, move_yaw = 0.0, seg["y0"]
    else:
        u = clamp((t - tin) / max(1e-3, T - tin - tout))
        move_yaw = math.atan2(d.x, -d.y)
    s_cov = _trap(u)
    mv = _speed(u) if dist > 1e-3 else 0.0
    p["loc"] = p0.lerp(p1, s_cov)
    if t < tin:
        p["yaw"] = lerp_angle(seg["y0"], move_yaw, smooth(t / tin))
    elif t > T - tout:
        p["yaw"] = lerp_angle(move_yaw, seg["y1"], smooth((t - (T - tout)) / tout))
    else:
        p["yaw"] = move_yaw
    ph = 2 * math.pi * (dist * s_cov) / stride       # one full cycle (two steps) per stride
    a = amp * (0.35 + 0.65 * mv) * min(1.0, mv * 3)
    s = math.sin(ph)
    p["legL"], p["legR"] = s * a, -s * a
    p["kneeL"] = a * 1.25 * max(0.0, math.sin(ph - 1.1)) + 0.08 * mv
    p["kneeR"] = a * 1.25 * max(0.0, -math.sin(ph - 1.1)) + 0.08 * mv
    p["raw_legs"] = True
    p["armL"], p["armR"] = -s * a * arms - 0.05, s * a * arms - 0.05
    p["elbowL"] = 0.3 + 0.35 * max(0.0, s) * a / max(amp, 1e-3) * mv
    p["elbowR"] = 0.3 + 0.35 * max(0.0, -s) * a / max(amp, 1e-3) * mv
    p["bob"] += bob * (abs(math.cos(ph)) - 0.55) * mv - crouch * min(1.0, mv * 3)
    p["shift"] += 0.018 * math.cos(ph) * mv
    p["twist"] += -0.14 * s * a / max(amp, 1e-3) * mv
    p["lean"] += lean * mv
    p["nod"] -= lean * 0.6 * mv                          # keep the eyes level
    p["tail_speed"] = 1.6


def a_walk(p, t, T, seg):
    _locomote(p, t, T, seg, 1.3, 0.45, 0.03, 0.05)


def a_run(p, t, T, seg):
    _locomote(p, t, T, seg, 2.1, 0.8, 0.06, 0.25, arms=0.9)
    p["elbowL"] += 0.9
    p["elbowR"] += 0.9
    p["raiseL"] = p["raiseR"] = 0.25
    p["earL"] = p["earR"] = 0.4


def a_sneak(p, t, T, seg):
    _locomote(p, t, T, seg, 0.95, 0.32, 0.015, 0.3, crouch=0.14, arms=0.3)
    p["raiseL"] = p["raiseR"] = 0.45
    p["armL"] -= 0.7
    p["armR"] -= 0.7
    p["elbowL"] = p["elbowR"] = 1.3          # tiptoe "paws up"
    p["earL"] = p["earR"] = 0.5
    p["tail_lift"] = -0.3
    p["turn"] += 0.25 * wob(t, 1.3)          # glancing around


def a_jump(p, t, T, seg):
    """Wind-up (crouch, arms swing back), launch (arms up), tuck in the air, land (absorb), recover."""
    times, h = seg["a"].get("times", 1), seg["a"].get("height", 0.9)
    per = T / times
    u = (t % per) / per
    if u < 0.25:                     # wind-up
        c = smooth(u / 0.25)
        p["bob"] -= 0.16 * c
        p["lean"] += 0.25 * c
        p["armL"] = p["armR"] = 0.55 * c
        p["raiseL"] = p["raiseR"] = 0.2
    elif u < 0.75:                   # in the air
        v = (u - 0.25) / 0.5
        p["loc"] = p["loc"] + Vector((0, 0, 4 * h * v * (1 - v)))
        p["raiseL"] = p["raiseR"] = 2.3
        p["armL"] = p["armR"] = -0.3
        p["elbowL"] = p["elbowR"] = 0.35
        tuck = math.sin(v * math.pi)
        p["legL"], p["legR"] = -0.7 * tuck, -0.25 * tuck
        p["kneeL"], p["kneeR"] = 1.3 * tuck, 0.7 * tuck
        p["lean"] -= 0.1 * tuck
        p["earL"] = p["earR"] = -0.3
        p["tail_lift"] = 0.8
    else:                            # landing: absorb, then stand up
        c = 1 - smooth((u - 0.75) / 0.25)
        p["bob"] -= 0.14 * c
        p["lean"] += 0.18 * c
        p["raiseL"] = p["raiseR"] = 0.16 + 0.5 * c


def a_wave(p, t, T, seg):
    """Arm out to the side, forearm up, hand waving from the elbow; the body leans into it."""
    e = env(t, T, seg)
    w = math.sin(t * 11)
    p["raiseR"] = lerp(0.16, 1.25, e)
    p["armR"] = -0.25 * e
    p["rotR"] = 1.45 * e
    p["elbowR"] = lerp(0.12, 1.35 + 0.35 * w, e)
    p["tilt"] += 0.12 * e
    p["sway"] -= 0.06 * e
    p["shift"] += 0.015 * e
    p["raiseL"] += 0.05 * e


def a_surprised(p, t, T, seg):
    e = env(t, T, seg, 0.12)
    hop = max(0.0, math.sin(min(1.0, t / 0.35) * math.pi)) * 0.12
    p["loc"] = p["loc"] + Vector((0, 0, hop))
    # startled: hands flung up beside her head (elbows bent, not a T-pose), easing a little after the flinch
    jolt = 1.0 + 0.15 * max(0.0, math.sin(min(1.0, t / 0.35) * math.pi))
    p["raiseL"] = p["raiseR"] = lerp(0.16, 1.05 * jolt, e)
    p["armL"] = p["armR"] = -0.4 * e
    p["elbowL"] = p["elbowR"] = 1.5 * e
    p["lean"] -= 0.18 * e
    p["nod"] -= 0.12 * e
    p["earL"] = p["earR"] = -0.45 * e
    p["tail_lift"] = 1.0 * e
    p["tail_sway"] = 0.3 * e
    p["tail_speed"] = 3.0


def a_sad(p, t, T, seg):
    e = env(t, T, seg, 0.4)
    p["nod"] += 0.38 * e
    p["earL"] = p["earR"] = 0.9 * e
    p["tail_lift"] = -1.0 * e
    p["lean"] += 0.12 * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.06, e)
    p["armL"] = p["armR"] = -0.15 * e
    p["elbowL"] = p["elbowR"] = 0.35 * e              # hands drift together in front
    p["bob"] -= 0.03 * e
    p["sway"] += 0.04 * wob(t, 0.5) * e               # a slow, heavy sway
    p["tail_speed"] = 0.4


def a_angry(p, t, T, seg):
    e = env(t, T, seg, 0.15)
    st = math.sin(t * 8)
    p["legL"] = -0.4 * max(0.0, st) * e
    p["legR"] = -0.4 * max(0.0, -st) * e
    p["kneeL"] = 0.6 * max(0.0, st) * e
    p["kneeR"] = 0.6 * max(0.0, -st) * e
    p["bob"] -= 0.04 * abs(st) * e                    # stomp down into each step
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.5, e)
    p["armL"] = p["armR"] = -0.55 * e
    p["elbowL"] = p["elbowR"] = 1.4 * e + 0.15 * abs(st) * e     # fists up, shaking
    p["lean"] += 0.12 * e
    p["nod"] += 0.08 * e
    p["turn"] += 0.08 * math.sin(t * 20) * e
    p["earL"] = p["earR"] = 0.75 * e
    p["ear_spread"] = 0.25 + 0.5 * e
    p["tail_lift"] = 0.8 * e
    p["tail_sway"] = 0.4 * e
    p["tail_speed"] = 4.0


def a_think(p, t, T, seg):
    e = env(t, T, seg, 0.3)
    p["armR"] = -1.15 * e
    p["elbowR"] = 2.1 * e          # hand to chin
    p["raiseR"] = lerp(0.16, 0.22, e)
    p["armL"] = -0.55 * e          # other arm across the body, holding the elbow
    p["elbowL"] = 1.2 * e
    p["raiseL"] = lerp(0.16, 0.05, e)
    p["tilt"] += 0.2 * e + 0.04 * wob(t, 0.8) * e
    p["nod"] -= 0.12 * e
    p["turn"] += 0.2 * e
    p["shift"] += 0.02 * e
    p["earR"] = -0.2 * e
    p["eye"] = [1.0, 0.85]
    p["calm"] = True


def a_laugh(p, t, T, seg):
    e = env(t, T, seg, 0.2)
    k = abs(math.sin(t * 13))
    p["lean"] -= 0.12 * e
    p["bob"] += 0.015 * k * e
    p["nod"] += (-0.12 + 0.09 * math.sin(t * 13)) * e
    p["sway"] += 0.05 * math.sin(t * 3) * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.35, e)
    p["armL"] = p["armR"] = -0.6 * e
    p["elbowL"] = p["elbowR"] = 1.25 * e     # hands to belly


def a_dance(p, t, T, seg):
    """A little groove: bounce on the beat (knees), hips side to side, alternating arm pumps with bent elbows."""
    e = env(t, T, seg, 0.2)
    w = t * 2 * math.pi * 2.0                 # 120 bpm
    beat = abs(math.sin(w / 2))
    side = math.sin(w / 2)
    p["bob"] -= 0.06 * beat * e
    p["shift"] += 0.035 * side * e
    p["sway"] -= 0.12 * side * e
    p["twist"] += 0.2 * math.sin(w / 4) * e
    up_l, up_r = max(0.0, side), max(0.0, -side)
    p["raiseL"] = lerp(0.16, 0.6 + 0.9 * up_l, e)
    p["raiseR"] = lerp(0.16, 0.6 + 0.9 * up_r, e)
    p["armL"] = -0.45 * e
    p["armR"] = -0.45 * e
    p["rotL"] = (0.4 + 0.9 * up_l) * e
    p["rotR"] = (0.4 + 0.9 * up_r) * e
    p["elbowL"] = lerp(0.12, 1.3 - 0.5 * up_l, e)
    p["elbowR"] = lerp(0.12, 1.3 - 0.5 * up_r, e)
    p["tilt"] += 0.12 * side * e
    p["nod"] += 0.06 * beat * e
    p["yaw"] += 0.25 * math.sin(t * 2.2) * e
    p["tail_speed"] = 2.5


def a_spin(p, t, T, seg):
    e = env(t, T, seg)
    p["yaw"] += 2 * math.pi * seg["a"].get("turns", 1) * smooth(t / T)
    sp = math.sin(math.pi * clamp(t / T))
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.75, sp * e)      # arms float out as she spins, elbows soft
    p["elbowL"] = p["elbowR"] = lerp(0.12, 0.5, sp * e)
    p["armL"] = p["armR"] = -0.25 * sp * e
    p["tilt"] += 0.1 * sp * e
    p["bob"] += 0.02 * sp * e


def a_celebrate(p, t, T, seg):
    e = env(t, T, seg, 0.15)
    hop = abs(math.sin(t * math.pi * 2))
    p["loc"] = p["loc"] + Vector((0, 0, 0.25 * hop * e))
    p["raiseL"] = p["raiseR"] = lerp(0.16, 1.75 + 0.2 * math.sin(t * 4 * math.pi), e)   # fist pumps
    p["armL"] = p["armR"] = -0.2 * e
    p["rotL"] = p["rotR"] = 1.3 * e
    p["elbowL"] = p["elbowR"] = lerp(0.12, 0.7 + 0.5 * hop, e)
    p["legL"], p["legR"] = -0.2 * hop * e, 0.05 * e
    p["kneeL"] = 0.4 * hop * e
    p["lean"] -= 0.08 * e
    p["tail_lift"] = 1.0 * e
    p["tail_speed"] = 3.0
    p["earL"] = p["earR"] = -0.3 * e


def a_nod(p, t, T, seg):
    e = env(t, T, seg, 0.1)
    p["nod"] += 0.22 * math.sin(t * 8) * e
    p["lean"] += 0.03 * math.sin(t * 8 - 0.6) * e      # the body follows a little
    p["calm"] = True


def a_shake_head(p, t, T, seg):
    e = env(t, T, seg, 0.1)
    p["turn"] += 0.38 * math.sin(t * 9) * e
    p["twist"] -= 0.05 * math.sin(t * 9 - 0.5) * e
    p["nod"] += 0.06 * e


def a_point(p, t, T, seg):
    """Points out and forward, the way a person does: the shoulder leads, the elbow keeps a little bend,
    the head turns to look where the finger goes, her weight settles onto one leg, and the arm breathes
    slightly while it holds. The other arm rests loosely at her side."""
    e = env(t, T, seg, 0.25)
    rise = smooth(min(1.0, e * 1.3))                      # the arm lifts with ease, not at a constant speed
    hold = 0.5 + 0.5 * math.sin(t * 1.6)                  # slow, tiny breathing while she holds the pose
    tgt = seg.get("_at_xy")
    if tgt is not None and (tgt - p["loc"]).length > 0.3:
        # aimed at something ("turn on the machine"): she turns part of the way to it (never fully away from
        # the camera) and the arm on that side takes the rest, the head looking where the finger goes.
        d = tgt - p["loc"]
        rel = (math.atan2(d.x, -d.y) - p["yaw"] + math.pi) % (2 * math.pi) - math.pi   # > 0: on her left
        # her body turns a third of the way (a side target: ~30 degrees; behind her: ~55), so she stays open to the
        # camera; with a bigger turn plus the head turn she ended up side-on
        body = max(-0.95, min(0.95, rel * 0.32)) * rise
        p["yaw"] += body
        phi = abs(rel) - abs(body)                        # what the arm still has to cover, 0 = straight ahead
        k = clamp(phi / (math.pi / 2))
        back = clamp((phi - math.pi / 2) / (math.pi / 2))
        sd, sg = ("L", 1.0) if rel > 0 else ("R", -1.0)
        # behind her, the arm also rises over the shoulder so it isn't hidden behind her body from the front
        p["raise" + sd] = lerp(0.16, lerp(0.3, 1.3, k) + 0.35 * back, rise)
        p["arm" + sd] = lerp(0.0, lerp(-1.35, -0.05, k) + 0.6 * back + 0.03 * hold, rise)
        p["elbow" + sd] = lerp(0.12, 0.22 + 0.04 * hold, rise)
        p["rot" + sd] = lerp(0.0, 0.25, rise)
        p["turn"] += sg * min(0.35, phi * 0.3) * rise
        p["twist"] += sg * 0.12 * rise
        p["lean"] += 0.05 * rise
        p["shift"] -= sg * 0.025 * rise
        other = "R" if sd == "L" else "L"
        p["raise" + other] = lerp(0.16, 0.12, e)
        p["elbow" + other] = lerp(0.12, 0.45, e)
        return
    p["raiseR"] = lerp(0.16, 1.0, rise)                   # diagonally out and forward, readable from the front
    p["armR"] = lerp(0.0, -0.7 + 0.03 * hold, rise)
    p["elbowR"] = lerp(0.12, 0.22 + 0.04 * hold, rise)    # a slight bend, never a stiff straight arm
    p["rotR"] = lerp(0.0, 0.25, rise)
    p["twist"] -= 0.12 * rise                             # shoulder leads the point
    p["turn"] -= 0.22 * rise                              # head follows the finger
    p["tilt"] -= 0.06 * rise
    p["lean"] += 0.05 * rise
    p["shift"] += 0.025 * rise                            # weight onto the other leg
    p["sway"] += 0.01 * math.sin(t * 1.1) * e
    p["raiseL"] = lerp(0.16, 0.12, e)
    p["elbowL"] = lerp(0.12, 0.45, e)                     # the free hand is relaxed and bent


def a_stretch(p, t, T, seg):
    """Cat stretch: arms sweep up in front to reach overhead, up on her toes, then a big forward bow."""
    e = env(t, T, seg, 0.5)
    u = clamp(t / max(T, 1e-3))
    up = smooth(clamp(u / 0.35)) * e
    bow = smooth(clamp((u - 0.5) / 0.3)) * e
    p["armL"] = p["armR"] = -2.85 * up
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.22, up)
    p["elbowL"] = p["elbowR"] = lerp(0.12, 0.05, up)
    p["lean"] += -0.18 * up * (1 - bow) + 0.65 * bow
    p["bob"] += 0.025 * up * (1 - bow)
    p["nod"] -= 0.15 * up * (1 - bow) + 0.3 * bow
    p["tail_lift"] = 1.0 * e
    p["earL"] = p["earR"] = 0.3 * e


def a_sit(p, t, T, seg):
    """Sit down on the floor: hips all the way down, knees up, hands resting behind her."""
    e = env(t, T, seg, 0.45)
    p["no_ik"] = True
    p["bob"] -= (hip_height() - 0.12) * e
    p["legL"] = p["legR"] = -1.45 * e
    p["kneeL"] = p["kneeR"] = 1.7 * e
    p["lean"] -= 0.15 * e
    p["armL"] = p["armR"] = 0.45 * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.28, e)
    p["elbowL"] = p["elbowR"] = 0.2 * e
    p["tail_lift"] = -0.8 * e
    p["calm"] = True


def a_look_around(p, t, T, seg):
    """Look left, pause, look right, pause - the head leads, the body follows."""
    e = env(t, T, seg, 0.3)
    u = t * 1.6
    look = math.copysign(abs(math.sin(u)) ** 0.5, math.sin(u))     # dwell at each side
    p["turn"] += 0.6 * look * e
    p["twist"] += 0.12 * look * e
    p["nod"] -= 0.08 * e
    p["earL"] = -0.3 * max(0.0, look) * e
    p["earR"] = -0.3 * max(0.0, -look) * e


def a_fall(p, t, T, seg):
    """Skydiving: tipped forward, arms and legs spread and fluttering in the wind, hair/ears blown up."""
    e = env(t, T, seg, 0.3)
    flut = math.sin(t * 9)
    p["lean"] += 0.55 * e
    p["nod"] -= 0.45 * e                 # head up, looking at the camera
    p["raiseL"] = p["raiseR"] = lerp(0.16, 1.5 + 0.08 * flut, e)
    p["rotL"] = p["rotR"] = 1.2 * e
    p["elbowL"] = p["elbowR"] = lerp(0.12, 0.9 + 0.1 * flut, e)
    p["armL"] = p["armR"] = -0.15 * e
    p["legL"], p["legR"] = 0.35 * e + 0.05 * flut, 0.45 * e - 0.05 * flut
    p["kneeL"] = p["kneeR"] = 0.7 * e
    p["no_ik"] = True
    p["earL"] = p["earR"] = -0.6 * e
    p["tail_lift"] = 1.0 * e
    p["loc"] = p["loc"] + Vector((0.04 * math.sin(t * 2.3), 0, 0.06 * math.sin(t * 3.1)))


def a_float(p, t, T, seg):
    """Weightless: slow tumble, limbs drifting, gentle bob."""
    e = env(t, T, seg, 0.4)
    p["loc"] = p["loc"] + Vector((0, 0, 0.12 * math.sin(t * 1.4)))
    p["lean"] += 0.12 * math.sin(t * 0.9) * e
    p["sway"] += 0.1 * math.sin(t * 0.7 + 1) * e
    p["raiseL"] = lerp(0.16, 0.9 + 0.25 * math.sin(t * 1.1), e)
    p["raiseR"] = lerp(0.16, 0.8 + 0.25 * math.sin(t * 1.3 + 2), e)
    p["rotL"] = p["rotR"] = 0.8 * e
    p["elbowL"] = p["elbowR"] = 0.6 * e
    p["legL"] = (0.25 * math.sin(t * 0.8)) * e
    p["legR"] = (-0.25 * math.sin(t * 0.8 + 0.5)) * e
    p["kneeL"] = p["kneeR"] = 0.4 * e
    p["no_ik"] = True
    p["calm"] = True


def a_float_up(p, t, T, seg):
    """Lifted off the ground (balloons!): the height rises (see airborne()), she looks up, then down, delighted."""
    e = env(t, T, seg, 0.3)
    u = clamp(t / max(T, 1e-3))
    p["nod"] += (-0.3 * math.sin(math.pi * min(1.0, u * 1.6)) + 0.15 * smooth(u)) * e
    p["raiseL"] = lerp(0.16, 0.7, e)
    p["rotL"] = 0.6 * e
    p["elbowL"] = 0.5 * e
    p["calm"] = True


def a_land(p, t, T, seg):
    """Coming back down; a little knee bend when the feet touch."""
    e = env(t, T, seg, 0.2)
    u = clamp(t / max(T, 1e-3))
    if u > 0.75:
        p["bob"] -= 0.12 * math.sin(math.pi * (u - 0.75) / 0.25) * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.6 * (1 - u), e)


def airborne(p, t, T, seg):
    """Height above the ground (float_up / land) + what the body does up there: legs dangle and swing,
    one hand holds on (the balloons' strings follow her right hand)."""
    a0, a1 = seg.get("alt0", 0.0), seg.get("alt1", 0.0)
    u = clamp(t / max(T, 1e-3))
    h = lerp(a0, a1, smooth(u)) if seg["anim"] in ("float_up", "land") else a0
    if h < 0.05:
        return
    h += 0.08 * math.sin(t * 1.3 + seg["f0"] * 0.1)          # bob on the breeze
    p["loc"] = p["loc"] + Vector((0.05 * math.sin(t * 0.7), 0, h))
    w = min(1.0, h / 0.4)
    p["no_ik"] = True
    p["legL"] += (0.15 + 0.12 * math.sin(t * 1.7)) * w
    p["legR"] += (0.05 - 0.12 * math.sin(t * 1.7 + 0.6)) * w
    p["kneeL"] += 0.45 * w
    p["kneeR"] += 0.25 * w
    p["bob"] = max(p["bob"], 0.0)
    p["sway"] += 0.05 * math.sin(t * 0.9) * w
    if seg["anim"] not in ("wave", "point", "think", "celebrate"):   # holding on with the right hand
        p["raiseR"] = lerp(p["raiseR"], 2.55, w)
        p["armR"] = lerp(p["armR"], -0.15, w)
        p["rotR"] = lerp(p.get("rotR", 0.0), 0.2, w)
        p["elbowR"] = lerp(p["elbowR"], 0.15, w)


def a_scared(p, t, T, seg):
    e = env(t, T, seg, 0.15)
    p["shift"] += 0.012 * math.sin(t * 55) * e                       # trembling
    p["earL"] = p["earR"] = 1.0 * e
    p["tail_lift"] = -0.6 * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.3, e)
    p["armL"] = p["armR"] = -1.2 * e
    p["elbowL"] = p["elbowR"] = 1.4 * e     # hands up to face
    p["bob"] -= 0.1 * e
    p["lean"] += 0.1 * e
    p["nod"] += 0.1 * e


def a_blow_kiss(p, t, T, seg):
    """Hand up to the lips, then flung out towards the camera. One kiss about every 0.8 s."""
    e = env(t, T, seg, 0.2)
    k = (t * 1.25) % 1.0
    out = smooth(min(1.0, max(0.0, (k - 0.35) * 3.0)))     # the flick: hand leaves the lips
    # lips: arm forward and twisted in so the hand is at her mouth (raising it out to the side read as a wave);
    # the flick throws it forward and a little out, towards the camera (it used to read as pointing sideways)
    p["armR"] = lerp(0.0, lerp(-2.4, -1.15, out), e)
    p["elbowR"] = lerp(0.12, lerp(2.3, 0.35, out), e)
    p["raiseR"] = lerp(0.16, lerp(0.0, 0.5, out), e)
    p["rotR"] = lerp(0.0, lerp(-1.7, 0.2, out), e)
    p["tilt"] += 0.15 * e
    p["sway"] += 0.04 * math.sin(t * 2.5) * e


def a_clap(p, t, T, seg):
    """Both hands in front of her, clapping three times a second."""
    e = env(t, T, seg, 0.15)
    c = 0.5 + 0.5 * math.cos(t * math.tau * 3.0)            # 1 when the hands meet
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.9, e)
    p["elbowL"] = p["elbowR"] = lerp(0.12, 1.9 - 0.25 * c, e)
    p["armL"] = 0.35 * c * e
    p["armR"] = -0.35 * c * e
    p["lean"] += 0.05 * c * e
    p["earL"] = p["earR"] = 0.15 * c * e


def a_bow(p, t, T, seg):
    """A slow, polite bow: lean forward from the waist and back up, arms relaxed at her sides."""
    e = env(t, T, seg, 0.25)
    b = 0.5 - 0.5 * math.cos(t * math.tau / 2.6)            # 0 upright, 1 bowed
    p["lean"] += 0.55 * b * e
    p["nod"] += 0.2 * b * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.05, e)
    p["elbowL"] = p["elbowR"] = lerp(0.12, 0.2, e)


def a_sneeze(p, t, T, seg):
    """Sneezes: head goes back, the breath builds, then the head snaps forward. Repeats every 1.6 s."""
    e = env(t, T, seg, 0.1)
    ph = (t % 1.6) / 1.6
    wind = smooth(min(1.0, ph / 0.6))
    burst = max(0.0, 1.0 - abs(ph - 0.66) / 0.07)
    p["nod"] += (-0.35 * wind + 0.8 * burst) * e
    p["sway"] += 0.12 * burst * e
    p["shift"] += 0.05 * burst * e
    # into the elbow: the forearm comes up across her mouth (arm forward, twisted in - see facepalm) and the head
    # snaps down into it. Raising the arm out to the side (the old pose) read as a wave.
    arm = smooth(min(1.0, ph / 0.35)) * e
    p["armR"] = -2.3 * arm
    p["elbowR"] = lerp(0.12, 2.4, arm)
    p["raiseR"] = lerp(0.16, 0.0, arm)
    p["rotR"] = -1.6 * arm


def a_facepalm(p, t, T, seg):
    """Hand to the forehead, head drops a little, a small sigh of a sway."""
    e = env(t, T, seg, 0.2)
    # upper arm swung well forward and twisted in (rot < 0) so the folded forearm lies across her face, and the
    # head drops into the hand. Raising the arm out to the side (the old pose) put the hand at the temple - it read
    # as a salute; without the twist the hand stays beside her face, at the shoulder's width. Picked from rendered
    # variants (nod > 0 = head down).
    p["armR"] = -2.3 * e
    p["elbowR"] = lerp(0.12, 2.4, e)
    p["raiseR"] = lerp(0.16, 0.0, e)
    p["rotR"] = -1.6 * e
    p["armL"] = -0.2 * e                # the other arm hangs, a little slumped
    p["elbowL"] = 0.45 * e
    p["raiseL"] = lerp(0.16, 0.08, e)
    p["nod"] += (0.45 + 0.04 * math.sin(t * 2.0)) * e
    p["tilt"] += 0.08 * e
    p["sway"] -= 0.03 * e


def a_shiver(p, t, T, seg):
    """Cold: a fast tremble through the body, arms hugged in close."""
    e = env(t, T, seg, 0.2)
    j = math.sin(t * 36)
    p["shift"] += 0.02 * j * e
    p["sway"] += 0.015 * j * e
    p["nod"] += 0.02 * j * e
    p["raiseL"] = p["raiseR"] = lerp(0.16, 0.3, e)
    p["elbowL"] = p["elbowR"] = lerp(0.12, 1.5, e)
    p["armL"] = 0.4 * e
    p["armR"] = -0.4 * e


ANIMS = {
    "blow_kiss": a_blow_kiss, "clap": a_clap, "bow": a_bow, "sneeze": a_sneeze, "facepalm": a_facepalm,
    "shiver": a_shiver,
    "idle": a_idle, "turn": a_idle, "walk_to": a_walk, "run_to": a_run, "sneak_to": a_sneak,
    "jump": a_jump, "wave": a_wave, "surprised": a_surprised, "sad": a_sad, "angry": a_angry,
    "think": a_think, "laugh": a_laugh, "dance": a_dance, "spin": a_spin, "celebrate": a_celebrate,
    "nod": a_nod, "shake_head": a_shake_head, "point": a_point, "stretch": a_stretch, "sit": a_sit,
    "look_around": a_look_around, "scared": a_scared, "fall": a_fall, "float": a_float,
    "float_up": a_float_up, "land": a_land,
}

# animations as data (pipeline/animlib.py: the pose vocabulary + assets/anims/*.json): played like the ones above
import animlib  # noqa: E402


def _anim_player(a):
    keys = animlib.resolved_keys(a)

    def play(p, t, T, seg):
        e = env(t, T, seg, 0.2)
        for k, v in animlib.sample(a, t, keys).items():
            if k[-1] in "RL" and k[:-1] in animlib.ARM_KEYS:
                p[k] = lerp(p[k], v, e)            # arms: go to the pose
            else:
                p[k] = p.get(k, 0.0) + v * e       # head/body: added to what's there (breathing, talking...)
    return play


for _an, _aa in animlib.library().items():
    ANIMS.setdefault(_an, _anim_player(_aa))
MOVE_ANIMS = {"walk_to", "run_to", "sneak_to"}
ANIM_EXPR = {"surprised": "surprised", "sad": "sad", "angry": "angry", "laugh": "happy",
             "celebrate": "happy", "dance": "happy", "stretch": "happy", "scared": "surprised",
             "wave": "happy", "blow_kiss": "happy", "clap": "happy", "bow": "happy", "sneeze": "surprised",
             "facepalm": "sad", "shiver": "sad"}
EXPRESSIONS = {
    "neutral":   dict(eye=[1.0, 1.0], brow=0.0, brow_up=0.0, mouth=[1.0, 1.0]),
    "happy":     dict(eye=[1.05, 0.3], brow=-0.1, brow_up=0.012, mouth=[1.6, 1.6]),
    "surprised": dict(eye=[1.25, 1.3], brow=-0.15, brow_up=0.04, mouth=[0.8, 3.5]),
    "angry":     dict(eye=[1.0, 0.65], brow=0.55, brow_up=-0.01, mouth=[1.4, 0.8]),
    "sad":       dict(eye=[1.0, 0.8], brow=-0.45, brow_up=-0.005, mouth=[0.8, 1.0]),
    "smug":      dict(eye=[1.0, 0.5], brow=-0.15, brow_up=0.015, mouth=[1.5, 1.0]),
    "scared":    dict(eye=[0.8, 1.2], brow=-0.4, brow_up=0.03, mouth=[1.0, 2.0]),
}


def apply_expression(p, name):
    ex = EXPRESSIONS.get(name, EXPRESSIONS["neutral"])
    p["expr"] = name
    if p["eye"] == [1.0, 1.0]:
        p["eye"] = list(ex["eye"])
    p["brow"], p["brow_up"], p["mouth"] = ex["brow"], ex["brow_up"], list(ex["mouth"])


def secondary(p, tg, talk_t):
    """Always-on life: breathing, ear flicks, blinking, lip flap - and small hand/head gestures on the
    rhythm of speech when she's standing calmly."""
    br = math.sin(tg * 2.3)
    p["bob"] += 0.004 * br
    p["lean"] -= 0.012 * br                     # chest rises as she breathes in
    p["earL"] -= 0.35 * max(0.0, math.sin(tg * 1.9)) ** 40
    p["earR"] -= 0.35 * max(0.0, math.sin(tg * 1.3 + 1.0)) ** 40
    p["blink"] = (tg % 3.3) < 0.14 or (tg % 7.9) < 0.12
    if p["eye"][1] > 0.5 and p["blink"]:
        p["eye"][1] *= 0.1
    if talk_t is not None:
        p["talk_amt"] = abs(math.sin(talk_t * 13))
        p["mouth"][1] *= 1.0 + 2.2 * p["talk_amt"]
        beat = max(0.0, wob(talk_t, 3.1, 0.4)) ** 1.5           # emphasis beats while talking
        p["nod"] += 0.03 * math.sin(talk_t * 7) + 0.06 * beat
        p["tilt"] += 0.04 * wob(talk_t, 1.7, 2.0)
        if p.get("calm"):
            s = p.get("gesture_side", "R")
            o = "L" if s == "R" else "R"
            g = 0.5 + 0.5 * wob(talk_t, 1.3, 1.0)
            p["elbow" + s] += 0.9 * g + 0.3 * beat
            p["arm" + s] -= 0.45 * g + 0.1 * beat
            p["raise" + s] += 0.12 * g
            p["elbow" + o] += 0.25 * max(0.0, wob(talk_t, 0.9, 3.0))
            p["arm" + o] -= 0.12 * max(0.0, wob(talk_t, 0.9, 3.0))


def write_pose(R, p, fr):
    def k(o, path):
        o.keyframe_insert(data_path=path, frame=fr)
    R.root.location = p["loc"]
    R.root.rotation_euler = (0, 0, p["yaw"])
    k(R.root, "location"); k(R.root, "rotation_euler")
    write_shadow(R.shadow, p["loc"], fr)
    R.hips.location = (p.get("shift", 0.0), 0, HIP_Z + p["bob"]); k(R.hips, "location")
    R.torso.rotation_euler = (p["lean"], p["sway"], p["twist"]); k(R.torso, "rotation_euler")
    R.legs[0].rotation_euler = (p["legL"], 0, 0); R.legs[1].rotation_euler = (p["legR"], 0, 0)
    R.arms[0].rotation_euler = (p["armL"], -p["raiseL"], 0); R.arms[1].rotation_euler = (p["armR"], p["raiseR"], 0)
    for o in R.legs + R.arms:
        k(o, "rotation_euler")
    R.neck.rotation_euler = (p["nod"], p["tilt"], p["turn"]); k(R.neck, "rotation_euler")
    if R.ears:
        R.ears[0].rotation_euler = (-p["earL"], p["ear_spread"], 0)
        R.ears[1].rotation_euler = (-p["earR"], -p["ear_spread"], 0)
    for o in R.ears:
        k(o, "rotation_euler")
    tg = (fr - 1) / FPS
    base = [-1.1 + 0.6 * p["tail_lift"], 0.5, 0.4]
    for i, o in enumerate(R.tail):
        o.rotation_euler = (base[i], (0.3 + p["tail_sway"]) * math.sin(tg * 2.4 * p["tail_speed"] + i * 0.8), 0)
        k(o, "rotation_euler")
    for o in R.eyes:
        o.scale = (p["eye"][0], 1, p["eye"][1]); k(o, "scale")
    R.mouth.scale = (p["mouth"][0], 1, p["mouth"][1]); k(R.mouth, "scale")
    for i, o in enumerate(R.brows):
        o.rotation_euler = (0, -p["brow"] if i == 0 else p["brow"], 0)
        o.location.z = R.brow_z + p["brow_up"]
        k(o, "rotation_euler"); k(o, "location")


# --------------------------------------------------------------------------- walking round furniture
WALK_MARGIN = 0.55      # half her body width plus a little room (metres)


BUILTIN_OBST = {   # hand-built sets (set_cafe / set_park): their furniture as circles (x, y, radius)
    "cafe": [(1.6, 3.4, 0.55), (2.5, 3.4, 0.55), (3.4, 3.4, 0.55),               # the counter
             (-3.0, 1.5, 0.85), (-4.0, -3.5, 0.85), (4.5, -2.5, 0.85)],          # tables with their stools
    "park": [(2.8, 3.1, 0.5), (-3.2, 4.8, 0.45), (5.5, 6.0, 2.0)],               # bench, hero tree, pond
}


def _obstacles():
    """Footprints (x, y, radius) of the set's floor props. Things up high (lamps, posters) don't count."""
    if EP.get("set") in BUILTIN_OBST and not EP.get("set_recipe"):
        return list(BUILTIN_OBST[EP["set"]])
    recipe = EP.get("set_recipe") or {}
    custom = recipe.get("custom_props") or {}
    try:
        import setgen
        table = setgen.PROPS
    except Exception:
        table = {}
    out = []
    for p in recipe.get("props") or []:
        kind = p.get("kind", "")
        if float(p.get("z") or 0) > 1.0 or not p.get("pos"):
            continue
        d = custom.get(kind) or {}
        r = float(d.get("radius") or 0) or float(table.get(d.get("kind") or kind, 0.0) or 0.0)
        if r > 0:
            out.append((float(p["pos"][0]), float(p["pos"][1]), r))
    return out


OBST = _obstacles()


def _clear_of(q, pad=WALK_MARGIN):
    """Push a point out of any prop it sits in (a mark inside a table would walk her through it)."""
    x, y = q
    for _ in range(3):
        moved = False
        for ox, oy, r in OBST:
            need = r + pad
            d = math.hypot(x - ox, y - oy)
            if d < need:
                if d < 1e-6:
                    x, y = ox, oy - need
                else:
                    x, y = ox + (x - ox) / d * need, oy + (y - oy) / d * need
                moved = True
        if not moved:
            break
    return (x, y)


def _blocked(a, b):
    """The prop (x, y, needed clearance) a straight walk a -> b runs into first, or None."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    best = None
    for ox, oy, r in OBST:
        need = r + WALK_MARGIN
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((ox - ax) * dx + (oy - ay) * dy) / L2))
        if math.hypot(ax + t * dx - ox, ay + t * dy - oy) < need - 1e-3 and (best is None or t < best[0]):
            best = (t, (ox, oy, need))
    return best[1] if best else None


def _route(a, b, depth=0):
    """Points to walk through from a to b, going round furniture on whichever side is shorter. Returns [a, ..., b]."""
    hit = _blocked(a, b) if depth < 4 else None
    if hit is None:
        return [a, b]
    ox, oy, need = hit
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    best = None
    for s in (1, -1):
        w = (ox + s * nx * (need + 0.1), oy + s * ny * (need + 0.1))
        r1 = _route(a, w, depth + 1)
        r = r1 + _route(w, b, depth + 1)[1:]
        plen = sum(math.hypot(r[i + 1][0] - r[i][0], r[i + 1][1] - r[i][1]) for i in range(len(r) - 1))
        if best is None or plen < best[0]:
            best = (plen, r)
    return best[1]


def _pieces(anim, n, p0, p1, yaw, y1):
    """A move split into legs round furniture: [(frames, from, to, yaw_in, yaw_out)]. Anything else: one piece."""
    whole = [(n, p0, p1, yaw, y1)]
    if anim not in MOVE_ANIMS or OBST == []:
        return whole
    legs = _route((p0.x, p0.y), (p1.x, p1.y))
    if len(legs) < 3:
        return whole
    pts = [Vector((x, y, 0.0)) for x, y in legs]
    pts[0], pts[-1] = p0.copy(), p1.copy()
    lens = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]
    tot = sum(lens) or 1.0
    cuts = [0] + [round(n * sum(lens[:i + 1]) / tot) for i in range(len(lens))]
    cuts[-1] = n
    cnts = [cuts[i + 1] - cuts[i] for i in range(len(lens))]
    if min(cnts) < 1:
        return whole
    out, cur = [], yaw
    for i, cnt in enumerate(cnts):
        w1 = y1 if i == len(cnts) - 1 else math.atan2(pts[i + 1].x - pts[i].x, -(pts[i + 1].y - pts[i].y))
        out.append((cnt, pts[i], pts[i + 1], cur, w1))
        cur = w1
    return out


def resolve_pos(v, cur):
    if v is None:
        return cur.copy()
    if isinstance(v, str):
        if v not in MARKS:
            raise SystemExit(f"Unknown mark '{v}'. Marks in this set: {', '.join(MARKS)}")
        return Vector((*_clear_of(MARKS[v]), 0))
    return Vector((v[0], v[1], 0))


BUILTIN_THINGS = {   # hand-built sets: where the named things really are (marks are spots in front of them)
    "cafe": {"machine": (3.4, 3.5), "espresso": (3.4, 3.5), "counter": (2.5, 3.4), "table": (-3.0, 1.5),
             "door": (-6.95, -2.0), "window": (-2.5, 5.98)},
    "park": {"bench": (2.8, 3.1), "tree": (-3.2, 4.8), "pond": (5.5, 6.0)},
}


def point_target(name, pos):
    """Where "point at <name>" aims (x, y), or None: the named thing itself (a hand-built set's furniture, else the
    generated set's nearest prop of that kind), else the mark of that name. `name` can also be [x, y]."""
    if name is None:
        return None
    if isinstance(name, (list, tuple)):
        return Vector((float(name[0]), float(name[1]), 0.0))
    name = str(name)
    if EP.get("set") in BUILTIN_THINGS and not EP.get("set_recipe") and name in BUILTIN_THINGS[EP["set"]]:
        return Vector((*BUILTIN_THINGS[EP["set"]][name], 0.0))
    found = []
    for pr in (EP.get("set_recipe") or {}).get("props") or []:
        kind = str(pr.get("kind", ""))
        if pr.get("pos") and name in (kind, kind.replace("_pc", ""), kind[4:] if kind.startswith("imp_") else None):
            found.append(Vector((float(pr["pos"][0]), float(pr["pos"][1]), 0.0)))
    if found:
        return min(found, key=lambda v: (v - pos).length)
    if name in MARKS:
        return Vector((*MARKS[name], 0.0))
    return None


def yaw_for(face, pos, cur):
    if face is None:
        return cur
    named = {"camera": 0.0, "front": 0.0, "left": -math.pi / 2, "right": math.pi / 2,
             "away": math.pi, "back": math.pi}
    if face in named:
        return named[face]
    d = resolve_pos(face, pos) - pos
    return math.atan2(d.x, -d.y) if d.length > 1e-3 else cur


# Every main character gets a track: the same shots, each one played by its speaker (shot "speaker", default: the
# episode's character) while the others listen. All tracks share the shot lengths, so frames line up.
PRIMARY = "main"
CO_STARS = EP.get("co_stars") or []      # other main characters, resolved by run_episode (id, name, model, camera_scale...)
SPEAKER_POS = {}                          # shot index -> {character id: where the speaker stands when the shot starts}
shot_info = []


def speaker_of(shot):
    return shot.get("speaker") or PRIMARY


def build_track(who, start_pos):
    """One character's segments for every shot. The speaker plays the shot's actions (and talks); the others
    idle - or play the shot's "listen" anim - and are turned towards the speaker by fix_faces()."""
    segs, frame, pos, yaw = [], 1, start_pos, 0.0
    alt = float(EP.get("start_alt", 0.0)) if who == PRIMARY else 0.0   # height above the ground (float_up)
    for si, shot in enumerate(SHOTS):
        speaks = speaker_of(shot) == who
        if speaks:
            SPEAKER_POS.setdefault(si, {})[who] = pos.copy()
            acts = shot.get("actions")
            if not acts:
                acts = [{"anim": shot.get("action", "idle"),
                         **{k: shot[k] for k in ("to", "face", "times", "height", "turns", "at") if k in shot}}]
        else:
            acts = [{"anim": shot.get("listen", "idle")}]
        want = float(shot.get("duration", 2.0))
        fixed = sum(a.get("duration", 0) for a in acts)
        free = [a for a in acts if "duration" not in a]
        each = max(0.4, (want - fixed) / len(free)) if free else 0.0
        durs = [a.get("duration", each) for a in acts]
        if not free and fixed < want:          # stretch last action so the line fits
            durs[-1] += want - fixed
        ns = [max(1, round(d * FPS)) for d in durs]
        ns[-1] = max(1, ns[-1] + (round(want * FPS) - sum(ns)))    # every track gets the same frame count
        f0 = frame
        for a, n in zip(acts, ns):
            anim = a.get("anim", "idle")
            if anim not in ANIMS:
                raise SystemExit(f"Unknown anim '{anim}'. Available: {', '.join(sorted(ANIMS))}")
            p0 = pos.copy()
            p1 = resolve_pos(a.get("to"), pos) if anim in MOVE_ANIMS else pos.copy()
            y1 = yaw_for(a.get("face", "camera" if anim in MOVE_ANIMS else None), p1, yaw) if speaks else yaw
            a0 = alt
            if speaks and anim == "float_up":
                alt = min(6.0, float(a.get("height", alt + 2.2)))
            elif speaks and anim == "land":
                alt = 0.0
            expr = (a.get("expression") or (shot.get("expression") if speaks else None)
                    or ANIM_EXPR.get(anim, "neutral"))
            at_xy = point_target(a.get("at"), p1) if anim == "point" and speaks else None
            for pn, q0, q1, w0, w1 in _pieces(anim, n, p0, p1, yaw, y1):
                segs.append(dict(f0=frame, n=pn, anim=anim, a=a, p0=q0, p1=q1, y0=w0, y1=w1, shot=si, alt0=a0,
                                 alt1=alt, expr=expr, listener=not speaks, _at_xy=at_xy))
                frame += pn
            pos, yaw = p1, y1
        if who == PRIMARY:
            shot_info.append({"f0": f0, "n": frame - f0})
    for i, s in enumerate(segs):     # env() only ramps at the very start/end; the Smoother blends the rest
        s["prev_same"] = i > 0
        s["next_same"] = i + 1 < len(segs)
    return segs


def fix_faces(segs):
    """Listeners turn to whoever is speaking in their shot (that speaker's spot at the start of the shot)."""
    prev = None
    for s in segs:
        if prev is not None:
            s["y0"] = prev
        if s["listener"]:
            tgt = SPEAKER_POS.get(s["shot"], {}).get(speaker_of(SHOTS[s["shot"]]))
            if tgt is not None and (tgt - s["p0"]).length > 1e-3:
                s["y1"] = yaw_for((tgt.x, tgt.y), s["p0"], s["y0"])
            else:
                s["y1"] = s["y0"]
        prev = s["y1"]


TRACKS = {PRIMARY: {"segs": build_track(PRIMARY, resolve_pos(EP.get("start", "center"), Vector())),
                    "rig": RIG, "cam_scale": float((EP.get("character") or {}).get("camera_scale", 1.0))
                    if isinstance(RIG, VRoidRig) else 1.0}}
def _primary_pos_at(si):
    """Where she stands when shot si starts."""
    return next((s["p0"].copy() for s in TRACKS[PRIMARY]["segs"] if s["shot"] == si), Vector())


for k, co in enumerate(CO_STARS):
    start = co.get("start")
    if start in MARKS:
        spot = resolve_pos(start, Vector())
    else:
        # beside her where she'll be when they first speak (a fixed spot in the room left them out of every shot
        # once she walked off), on the side towards the middle of the set, clear of furniture
        first = next((si for si, sh in enumerate(SHOTS) if speaker_of(sh) == co["id"]), 0)
        her_at = _primary_pos_at(first)
        side = (-1 if her_at.x > 0.5 else 1) * (1 if k % 2 == 0 else -1)
        spot = Vector((*_clear_of((her_at.x + 1.3 * side, her_at.y + 0.4)), 0.0))
    segs = build_track(co["id"], spot)
    m = co.get("model")
    if m and m != "placeholder" and Path(m).exists():
        rig = VRoidRig(Path(m), co)
    else:
        rig = build_catgirl(co)
    TRACKS[co["id"]] = {"segs": segs, "rig": rig, "cam_scale": float(co.get("camera_scale", 1.0))
                        if isinstance(rig, VRoidRig) else 1.0}
    print(f"[build] co-star: {co.get('name', co['id'])} ({'model' if isinstance(rig, VRoidRig) else 'placeholder'})")
for who in TRACKS:
    fix_faces(TRACKS[who]["segs"])
segments = TRACKS[PRIMARY]["segs"]

TOTAL = shot_info[-1]["f0"] + shot_info[-1]["n"] - 1 if shot_info else 0
AUDIO_LEAD = float(EP.get("audio_lead", 0.15))
HAS_CUTAWAY = any(s.get("cutaway") for s in SHOTS)
print(f"[build] {len(SHOTS)} shots, {len(TRACKS)} character(s), {TOTAL} frames @ {FPS}fps")

for who, tr in TRACKS.items():
    tr["loc"] = {}                   # frame -> where this character stands
    tr["yaw"] = {}                   # frame -> which way they face (the camera finds a speaker's face with it)
    R = tr["rig"]
    SM = Smoother()
    for s in tr["segs"]:
        shot = SHOTS[s["shot"]]
        speaks = speaker_of(shot) == who
        T = s["n"] / FPS
        talk_len = float(shot.get("talk", 0.0)) if speaks else 0.0
        sf0 = shot_info[s["shot"]]["f0"]
        for k in range(s["n"]):
            fr = s["f0"] + k
            t = k / FPS
            p = default_pose()
            p["loc"] = s["p0"].copy()
            p["yaw"] = lerp_angle(s["y0"], s["y1"], smooth(t / 0.3)) if s["anim"] not in MOVE_ANIMS else s["y0"]
            ANIMS[s["anim"]](p, t, T, s)
            airborne(p, t, T, s)
            apply_expression(p, s["expr"])
            ts = (fr - sf0) / FPS - float(shot.get("lead", AUDIO_LEAD))   # first shot has a longer intro
            p["gesture_side"] = "R" if s["shot"] % 2 == 0 else "L"
            secondary(p, (fr - 1) / FPS, ts if speaks and 0 <= ts <= talk_len else None)   # only the speaker talks
            SM.apply(p)
            if isinstance(R, VRoidRig):
                R.write(p, fr)
            else:
                write_pose(R, p, fr)
            if HAS_CUTAWAY:
                gone = bool(shot.get("cutaway"))
                R.root.scale = (1e-4,) * 3 if gone else (1.0, 1.0, 1.0)
                R.root.keyframe_insert("scale", frame=fr)
                if gone:
                    R.shadow.scale = (1e-4,) * 3
                    R.shadow.keyframe_insert("scale", frame=fr)
            tr["loc"][fr] = p["loc"].copy()
            tr["yaw"][fr] = p["yaw"]
char_loc = TRACKS[PRIMARY]["loc"]


# --------------------------------------------------------------------------- sets with no ground
AIR = (EP.get("set_recipe") or {}).get("air")
if AIR:
    _motion = EP["set_recipe"].get("motion", "float")
    _speed = 9.0 if _motion == "fall" else 0.0
    for _o in [o for o in scene.objects if o.get("drift")]:
        _z0, _ph = _o.location.z, (hash(_o.name) % 100) * 0.13
        for fr in range(1, TOTAL + 1):
            t = (fr - 1) / FPS
            z = _z0 + _speed * t + 0.25 * math.sin(t * 0.6 + _ph)
            _o.location.z = (z + 26.0) % 44.0 - 26.0          # wrap: clouds rushing up come back from below
            _o.keyframe_insert("location", frame=fr)
    for _o in scene.objects:                                   # no ground = no blob shadows
        if _o.name.startswith(("blob_shadow", "shadow_", "sprite_shadow")):
            _o.hide_render = True


# --------------------------------------------------------------------------- the rest of the cast
CAST_TRACKS = {}                           # cast people who speak: where they stand, frame by frame (for the camera)
if EP.get("cast"):
    import types
    import blender_cast
    import blender_sets
    blender_cast.build(types.SimpleNamespace(**globals()))


# --------------------------------------------------------------------------- cameras
CAMS = {
    #            offset from character       aim     lens
    "wide":     ((0.0, -6.0, 2.3),           "body", 28),
    "medium":   ((0.0, -4.0, 1.8),           "body", 30),
    "closeup":  ((0.0, -2.0, 1.55),          "head", 40),
    "side":     ((5.0, -1.5, 1.6),           "body", 30),
    "low":      ((0.8, -2.8, 0.35),          "head", 22),
    "high":     ((0.0, -3.0, 6.0),           "body", 26),
    "dramatic": ((1.2, -1.6, 1.45),          "head", 50),
    "back":     ((-1.2, 3.5, 2.0),           "head", 30),
    "macro":    ((0.05, -0.8, 1.6),          "head", 85),     # eye close-up (the reference's eye shots)
    "tiny":     ((0.0, -11.0, 1.6),          "body", 35),     # a small figure in a big scene
    "silhouette": ((0.6, 3.0, 1.1),          "head", 35),     # low, from behind: she reads as a dark shape
    "lead":     ((0.5, 3.0, 1.55),           "head", 30),     # ahead of her walk, looking back (turned below)
}
def _blockers(fr):
    """(x, y, radius, is_cast) of what can stand in a camera's way at frame fr: floor props and the cast."""
    out = [(x, y, r, False) for x, y, r in OBST]
    if EP.get("cast"):
        for tr in CAST_TRACKS.values():                  # people, where they are at that frame
            p = tr["loc"].get(fr)
            if p is not None and p.z > -10:              # AWAY (off stage) is far below the floor
                out.append((p.x, p.y, 0.4, True))
        out += [(p.x, p.y, max(0.35, r), True) for p, r in getattr(blender_cast, "TAKEN", [])]
    return out


def _view_blocked(cam, tgt, fr=None):
    """A floor prop or cast member (bigger than a crate) stands between the camera and her, or the camera is in one."""
    c, t = Vector((cam.x, cam.y, 0.0)), Vector((tgt.x, tgt.y, 0.0))
    seg = t - c
    for ox, oy, r, cast in (_blockers(fr) if fr else [(x, y, rr, False) for x, y, rr in OBST]):
        p = Vector((ox, oy, 0.0))
        if (p - t).length < 0.3:                         # that's the speaker herself (a cast person speaking)
            continue
        if not cast and (r < 0.35 or (p - t).length < r + 0.35):   # small props, or the furniture she stands at
            continue
        u = max(0.0, min(0.85, (p - c).dot(seg) / max(seg.length_squared, 1e-6)))
        if (c + seg * u - p).length < r * 0.85:
            return True
    return False


def _clear_view(views, off):
    """views: [(camera centre, her position, frame)] over the shot (a tracking camera moves with her): the first
    camera offset - as given, then swung round her - from which nothing blocks any of them."""
    def clear(o):
        return not any(_view_blocked(c + o, t, fr) for c, t, fr in views)
    if clear(off):
        return off
    turned = []
    for da in (0.45, -0.45, 0.9, -0.9, 1.3, -1.3):
        o = Vector((off.x * math.cos(da) - off.y * math.sin(da), off.x * math.sin(da) + off.y * math.cos(da), off.z))
        if clear(o):
            turned.append(((o.y > 0.3) != (off.y > 0.3), abs(da), o))   # stay on the camera's side of her (a lead camera: ahead of her)
    return min(turned, key=lambda x: x[:2])[2] if turned else off


rng = random.Random(3)
first_cam = None
SHOT_CAMS = []
CAM_POS = {}         # frame -> camera position (particles fill the space the camera sees)
for si, shot in enumerate(SHOTS):
    name = shot.get("camera", "medium")
    if name not in CAMS:
        raise SystemExit(f"Unknown camera '{name}'. Available: {', '.join(CAMS)}")
    off, aim, lens = CAMS[name]
    SP = TRACKS.get(speaker_of(shot)) or CAST_TRACKS.get(speaker_of(shot)) or TRACKS[PRIMARY]   # whoever speaks
    loc_of, srig = SP["loc"], SP["rig"]
    off = Vector(off) * float(shot.get("zoom", 1.0)) * SP["cam_scale"]
    if aim == "head" and SP.get("head_dist", 1.0) != 1.0:      # a bigger head: same framing from further back
        off = Vector((off.x * SP["head_dist"], off.y * SP["head_dist"], off.z))
    f0, n = shot_info[si]["f0"], shot_info[si]["n"]
    f1 = f0 + n - 1
    if SP is not TRACKS[PRIMARY] and SP.get("yaw"):
        # she talks to the camera, so her cameras sit on the camera side (-y). Someone else who speaks faces the
        # person they talk to: turn the camera offset with them, or it films the back of their head - and swing it
        # further round when she would stand between the camera and them (it filmed her back instead).
        fm = (f0 + f1) // 2
        a0 = SP["yaw"].get(fm, 0.0)
        sp_at, her_at = SP["loc"][fm].copy(), char_loc[fm].copy()
        sp_at.z = her_at.z = 0.0
        best_off = None
        for da in (0.0, 0.6, -0.6, 1.0, -1.0, 1.4, -1.4):
            a = a0 + da
            o = Vector((off.x * math.cos(a) - off.y * math.sin(a), off.x * math.sin(a) + off.y * math.cos(a), off.z))
            cam_at = sp_at + Vector((o.x, o.y, 0.0))
            seg = sp_at - cam_at
            u = max(0.0, min(1.0, (her_at - cam_at).dot(seg) / max(seg.length_squared, 1e-6)))
            if (cam_at + seg * u - her_at).length > 0.55 or u > 0.97:     # she isn't in the way
                best_off = o
                break
        off = best_off or Vector((off.x * math.cos(a0) - off.y * math.sin(a0),
                                  off.x * math.sin(a0) + off.y * math.cos(a0), off.z))
    if name == "lead":
        # the camera goes ahead of her along the walk and looks back, so a walk away from the usual camera shows
        # her face (the side/back cameras showed her three-quarters from behind)
        d = loc_of[f1] - loc_of[f0]
        d.z = 0.0
        if d.length > 0.5:
            d.normalize()
            side = Vector((d.y, -d.x, 0.0))
            off = Vector((d.x * off.y + side.x * off.x, d.y * off.y + side.y * off.x, off.z))
    if name == "side" and shot.get("action") == "point" and shot.get("at") is not None:
        # pointing at something behind her is filmed from the side (autodirect) - from the side the thing is on,
        # or her body hides the arm that points
        tgt = point_target(shot["at"], loc_of[f0])
        if tgt is not None and (1.0 if tgt.x - loc_of[f0].x > 0 else -1.0) * off.x < 0:   # dead behind = her right (a_point)
            off = Vector((-off.x, off.y, off.z))
    center = (loc_of[f0] + loc_of[f1]) / 2
    if shot.get("move", "static") == "static" and (loc_of[f1] - loc_of[f0]).length > 0.8:
        # she walks during a still shot: set the camera up from the end of the walk nearest to it, so walking
        # toward the camera ends at the shot's normal distance (from the middle she walked almost into the lens)
        o = Vector((off.x, off.y, 0.0))
        near = min((loc_of[f0], loc_of[f1]), key=lambda q: ((center + o) - q).length)
        if ((center + o) - near).length < o.length - 0.3:
            center = near.copy()
    center.z = max(0.0, min(loc_of[f0].z, loc_of[f1].z) * 0.85)    # up in the air: the camera comes along
    aim_obj = srig.aim_head if aim == "head" else srig.aim_body
    both = bool(shot.get("both")) and len(TRACKS) > 1
    if both:                                  # "both": the speaker and everyone else in one frame
        mid_f = (f0 + f1) // 2
        mids = [t_["loc"][mid_f].copy() for t_ in TRACKS.values()]
        for m_ in mids:
            m_.z = 0.0
        center = sum(mids, Vector()) / len(mids)
        # a two-shot: look across the line between them from the camera side, far enough back for all of them
        # (a 9:16 frame at ~30 mm is about 0.6 x the distance wide)
        a_, b_ = max(((p, q) for p in mids for q in mids), key=lambda pq: (pq[0] - pq[1]).length)
        span = (a_ - b_).length
        perp = Vector((-(a_ - b_).y, (a_ - b_).x, 0.0)).normalized() if span > 0.3 else Vector((0.0, -1.0, 0.0))
        if perp.y > 0:
            perp = -perp                      # stay on the camera side of them
        dist = max(4.0, (span + 1.6) / 0.6)
        off = Vector((perp.x * dist, perp.y * dist, 1.7))
        lens = 28                             # the distance above assumes a wide lens, whatever the shot's camera
        aim_obj = empty(f"both{si}", None, (center.x, center.y, 1.0))
    focus = blender_cast.FOCUS.get(si) if EP.get("cast") else None
    if focus is not None and not both and name in ("wide", "medium", "high", "low") and shot.get("move") != "follow":
        her_p, new_p = Vector((center.x, center.y, 0.0)), Vector((focus.x, focus.y, 0.0))
        mid = her_p.lerp(new_p, 0.5)                                # frame her and whoever just arrived
        # pull back until both sit inside the 9:16 frame with a body's width to spare (whoever is nearer the
        # camera takes up more of it - a fixed push-back left the arrival at the frame's edge)
        half = math.atan(10.125 / lens) * 0.82              # horizontal half-angle of a 36 mm-tall 9:16 frame
        grow = 1.0
        while grow < 2.6:
            o = Vector((off.x * grow, off.y * grow, 0.0))
            cam_at, look = mid + o, (-o).normalized()
            fits = True
            for q in (her_p, new_p):
                v = q - cam_at
                side_off = abs(v.x * look.y - v.y * look.x) + 0.45         # + half a body
                fits = fits and math.atan2(side_off, max(0.3, v.dot(look))) <= half
            if fits:
                break
            grow += 0.1
        off = Vector((off.x * grow, off.y * grow, off.z * (1.0 + (grow - 1.0) * 0.3)))
        center = mid
        aim_obj = empty(f"focus{si}", None, (mid.x, mid.y, 0.95))
    cut = blender_cast.CUT.get(si) if EP.get("cast") else None
    if cut:                    # cutaway: frame the subject, three-quarter and a little low; follow it if it moves
        # a 9:16 frame at ~32 mm sees about 0.63 x distance across and 1.12 x distance up
        w, h = cut.get("w", cut["r"] * 2), cut["h"]
        dist = max(0.8 if cut.get("part") else 1.4, w * 0.8 / 0.63, h * 1.5 / 1.12)   # wide things run off the sides
        if cut.get("verb") == "fly_by":
            dist = max(dist * 1.3, 3.0)      # the camera follows it across (TRACK_TO), so it can stay close
        elif cut["moving"]:
            dist *= 1.2
        center = cut["center"].copy()
        center.z = float(cut.get("z", 0.0))         # a part of an explainer object can be up off the ground
        off = Vector((0.3 * dist, -dist, max(0.22, 0.55 * h)))      # small things: a low, macro-ish angle
        aim_obj = cut["target"]
        lens = 32 if name in ("wide", "medium", "side", "high", "low", "back", "lead") else lens
    if not cut and not both and OBST:
        # furniture between the camera and the speaker (the post office counter filled half a side shot): swing the
        # camera round her to the nearest clear angle
        fm = (f0 + f1) // 2
        if shot.get("move") == "follow":                 # the camera travels with her: check along the way
            views = [(loc_of[fr], loc_of[fr], fr) for fr in (f0, fm, f1)]
        else:
            views = [(center, loc_of[fr], fr) for fr in (f0, fm, f1)]
        off = _clear_view(views, off)
    cd = bpy.data.cameras.new(f"cam{si}")
    cd.lens = lens
    cd.clip_start, cd.clip_end = 0.05, 300
    cam = bpy.data.objects.new(f"cam{si}_{name}", cd)
    scene.collection.objects.link(cam)
    con = cam.constraints.new("TRACK_TO")
    con.target = aim_obj
    con.track_axis, con.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
    move = shot.get("move", "static")
    if move == "static":
        cam.location = center + off
        for fr in range(f0, f1 + 1):
            CAM_POS[fr] = (center + off).copy()
    else:
        for fr in range(f0, f1 + 1):
            u = (fr - f0) / max(1, f1 - f0)
            o = off.copy()
            base = center
            if move == "push_in":
                o *= lerp(1.3, 0.9, smooth(u))
            elif move == "pull_out":
                o *= lerp(0.8, 1.3, smooth(u))
            elif move == "orbit":
                a = lerp(-0.6, 0.6, u)
                o = Vector((o.x * math.cos(a) - o.y * math.sin(a), o.x * math.sin(a) + o.y * math.cos(a), o.z))
            elif move == "follow":
                base = loc_of[fr].copy()
                base.z = 0
            elif move == "shake":
                o += Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * 0.06
            cam.location = base + o
            cam.keyframe_insert("location", frame=fr)
            CAM_POS[fr] = (base + o).copy()
    m = scene.timeline_markers.new(f"shot{si}", frame=f0)
    m.camera = cam
    SHOT_CAMS.append((cam, f0, f1))
    first_cam = first_cam or cam
scene.camera = first_cam

# drawn props (sprites) turn to face whichever camera is live: one locked-track per shot camera, switched on
# only during its shot (constant keys so there's no in-between)
try:
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "CONSTANT"
except Exception:
    pass
for ob in [o for o in scene.objects if o.get("billboard")]:
    for cam, f0, f1 in SHOT_CAMS:
        c = ob.constraints.new("LOCKED_TRACK")
        c.target = cam
        c.track_axis = "TRACK_Z"        # the upright plane's front is its local +Z, its "up" is local +Y
        c.lock_axis = "LOCK_Y"
        keys = {1: 0.0, f0 - 1: 0.0, f0: 1.0, f1: 1.0, f1 + 1: 0.0}     # flat on during its shot, flat off otherwise
        for fr, v in sorted(keys.items()):
            if fr >= 1:
                c.influence = v
                c.keyframe_insert("influence", frame=fr)


# --------------------------------------------------------------------------- particle effects (need the cameras)
import types as _types
import blender_fx
blender_fx.build(_types.SimpleNamespace(**globals()))


# --------------------------------------------------------------------------- time of day
# A shot with "light": "day" | "sunset" | "night" | "dawn" sets the sun from that shot on (it eases between shots),
# so a video can move through a day. Shots without it leave the set's own light alone.
# each: sun energy, sun colour, ambient light strength (lights the whole scene), sky colour the camera sees
LIGHT_KEYS = {"day": (2.2, "#ffffff", 0.4, "#9ec4f0"), "sunset": (1.5, "#ffb070", 0.28, "#f0a88a"),
              "night": (0.25, "#7f97ff", 0.05, "#1c2445"), "dawn": (1.2, "#ffd6b0", 0.22, "#c8c4f0")}
_sun = bpy.data.objects.get("sun")
_lk = [(shot_info[si]["f0"], LIGHT_KEYS[s["light"]]) for si, s in enumerate(SHOTS) if s.get("light") in LIGHT_KEYS]
if _sun is not None and _lk and "WORLD_NODES" in globals():
    _ld = _sun.data
    _amb, _seen = WORLD_NODES

    def _set_light(v):
        en, col, strength, sky = v
        _ld.energy, _ld.color = en, hexcol(col)
        _amb.inputs["Strength"].default_value = strength
        _seen.inputs["Color"].default_value = (*hexcol(sky), 1.0)

    def _key_light(f):
        _ld.keyframe_insert("energy", frame=f)
        _ld.keyframe_insert("color", frame=f)
        _amb.inputs["Strength"].keyframe_insert("default_value", frame=f)
        _seen.inputs["Color"].keyframe_insert("default_value", frame=f)

    # the set's own lighting until the first change (it used to take the FIRST change's light from frame 1),
    # then each change cuts in at the start of its shot and holds until the next one
    _prev = (_ld.energy, tuple(_ld.color), _amb.inputs["Strength"].default_value,      # linear colours:
             tuple(_seen.inputs["Color"].default_value[:3]))                           # hexcol() passes tuples through
    _set_light(_prev)
    _key_light(1)
    for _f0, _v in _lk:
        if _f0 > 2:
            _set_light(_prev)
            _key_light(_f0 - 1)
        _set_light(_v)
        _key_light(_f0)
        _prev = _v
    print(f"[build] light changes: {[s['light'] for s in SHOTS if s.get('light') in LIGHT_KEYS]}")

# --------------------------------------------------------------------------- render settings
r = scene.render
r.engine = "BLENDER_EEVEE"
r.resolution_x, r.resolution_y, r.resolution_percentage = RES_X, RES_Y, 100
r.fps = FPS
scene.frame_start, scene.frame_end = 1, TOTAL
try:
    scene.eevee.taa_render_samples = 1     # no anti-aliasing: crunchy edges
except Exception:
    pass
scene.view_settings.view_transform = "Standard"
try:
    r.image_settings.media_type = "IMAGE"
except Exception:
    pass
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGB"
os.makedirs(FRAMES_DIR, exist_ok=True)
r.filepath = os.path.join(FRAMES_DIR, "f_")

with open(os.path.join(os.path.dirname(argv[0]), "timing.json"), "w", encoding="utf-8") as fh:
    json.dump({"fps": FPS, "total_frames": TOTAL, "shots": shot_info}, fh, indent=2)

if BLEND_OUT:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(BLEND_OUT))

if EP.get("_export_glb"):             # the set as a 3D file for the 3D view (web: Sets page -> 3D view)
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(EP["_export_glb"]), export_format="GLB",
                              export_yup=True, use_selection=False)
    print(f"[export] {EP['_export_glb']}", flush=True)

if EP.get("_still"):                  # set preview: one frame from the middle of the first shot
    scene.frame_set(max(1, TOTAL // 2))
    r.filepath = os.path.abspath(EP["_still"])
    bpy.ops.render.render(write_still=True)
elif not EP.get("_no_render"):
    bpy.ops.render.render(animation=True)
print("[build] done")
