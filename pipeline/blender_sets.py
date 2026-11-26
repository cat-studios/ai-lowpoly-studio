"""
Builds a generated set (recipe from setgen.py) inside Blender, from a library of low-poly props.
Imported by blender_build.py, which passes in its helpers (prim, empty, mat, ...).
Props face -Y (towards the camera) at rot 0; every prop is parented to an empty at its position.
"""
import math
import random

import bpy
from mathutils import Vector

H = None          # helpers from blender_build (set by build())
R = None          # current recipe
RNG = None
ACC = "#ff8fb8"


def P(kind, name, loc, scale, color, parent, unlit=False, rot=(0, 0, 0), **kw):
    return H.prim(kind, name, loc, scale, rot, color=color, parent=parent, unlit=unlit, **kw)


def shade(hexs, f):
    """Darken (f<1) or lighten (f>1) a #rrggbb colour."""
    h = hexs.lstrip("#")
    c = [min(255, max(0, int(int(h[i:i + 2], 16) * f))) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(c)


def rand_col(*cols):
    return RNG.choice(cols)


def image_mat(path, lit=False, fog=True):
    """Material showing an image. lit=True: shaded like the rest of the set (floors, walls);
    lit=False: glowing (screens, posters). fog=False for the far sky backdrop."""
    img = bpy.data.images.load(path, check_existing=True)
    m = bpy.data.materials.new("tex_" + img.name)
    if m.node_tree is None:     # Blender < 5: nodes are off by default (5.x always has them; use_nodes goes in 6.0)
        m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    tex = N.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    em = N.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.35 if lit else 0.9
    L.new(tex.outputs["Color"], em.inputs["Color"])
    shader = em.outputs[0]
    if lit:
        diff = N.new("ShaderNodeBsdfDiffuse")
        add = N.new("ShaderNodeAddShader")
        L.new(tex.outputs["Color"], diff.inputs["Color"])
        L.new(diff.outputs[0], add.inputs[0])
        L.new(em.outputs[0], add.inputs[1])
        shader = add.outputs[0]
    L.new(H.add_fog(N, L, shader) if fog else shader, out.inputs["Surface"])
    return m


def texture_world_uv(o, slot, size=2.0, lit=True, fog=True):
    """Put a generated texture on an object, tiling it every `size` metres in world space."""
    path = (R.get("textures") or {}).get(slot)
    if not path:
        return False
    try:
        bpy.context.view_layer.update()
        mw = o.matrix_world
        o.data.materials.clear()
        o.data.materials.append(image_mat(path, lit=lit, fog=fog))
        for poly in o.data.polygons:
            poly.material_index = 0
        uv = o.data.uv_layers.active or o.data.uv_layers.new()
        for poly in o.data.polygons:
            n = (mw.to_3x3() @ poly.normal)
            ax = max(range(3), key=lambda i: abs(n[i]))
            for li in poly.loop_indices:
                v = mw @ o.data.vertices[o.data.loops[li].vertex_index].co
                a, b = [(v.y, v.z), (v.x, v.z), (v.x, v.y)][ax]
                uv.data[li].uv = (a / size, b / size)
        return True
    except Exception as exc:
        print(f"[sets] {slot} texture failed: {exc}")
        return False


def sky_backdrop():
    """A huge painted horizon far behind the set (outside), not fogged so it reads as sky."""
    path = (R.get("textures") or {}).get("sky")
    if not path:
        return
    d = R["fog"][1] * 0.92
    o = P("plane", "sky_backdrop", (0, d, 14), (d * 1.6, 16, 1), "#ffffff", None, rot=(math.pi / 2, 0, 0))
    o.data.materials.clear()
    o.data.materials.append(image_mat(path, lit=False, fog=False))
    uv = o.data.uv_layers.active or o.data.uv_layers.new()
    for poly in o.data.polygons:
        for li in poly.loop_indices:
            v = o.data.vertices[o.data.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x + 1) / 2 * 2.0, (v.y + 1) / 2)     # repeat twice across, full height


def textured_panel(name, parent, loc, scale, slot, fallback, unlit=True):
    """A flat panel that shows a ComfyUI texture if the recipe has one, else a flat colour."""
    o = P("cube", name, loc, scale, fallback, parent, unlit=unlit)
    path = (R.get("textures") or {}).get(slot)
    if path:
        try:
            o.data.materials.clear()
            o.data.materials.append(image_mat(path))
            # project the image onto the front face: simple planar UVs from x/z
            uv = o.data.uv_layers.active or o.data.uv_layers.new()
            for poly in o.data.polygons:
                for li in poly.loop_indices:
                    v = o.data.vertices[o.data.loops[li].vertex_index].co
                    uv.data[li].uv = ((v.x + 1) / 2, (v.z + 1) / 2)
        except Exception as exc:
            print(f"[sets] texture {path} failed: {exc}")
    return o


# --------------------------------------------------------------------------- prop library
def p_table(r, p):
    P("cyl", "top", (0, 0, 0.75), (0.6, 0.6, 0.04), "#f0e6da", r, vertices=10)
    P("cyl", "leg", (0, 0, 0.37), (0.05, 0.05, 0.37), "#3a2a22", r, vertices=6)


def p_chair(r, p):
    c = rand_col(ACC, "#c96a3c", "#6b8fd6")
    P("cube", "seat", (0, 0, 0.45), (0.22, 0.22, 0.03), c, r)
    P("cube", "back", (0, 0.2, 0.72), (0.22, 0.03, 0.25), c, r)
    for dx in (-0.18, 0.18):
        for dy in (-0.18, 0.18):
            P("cyl", "leg", (dx, dy, 0.22), (0.025, 0.025, 0.22), "#3a2a22", r, vertices=4)


def p_stool(r, p):
    P("cyl", "seat", (0, 0, 0.6), (0.25, 0.25, 0.05), rand_col(ACC, "#e05a5a"), r, vertices=8)
    P("cyl", "leg", (0, 0, 0.3), (0.04, 0.04, 0.3), "#333333", r, vertices=6)


def p_bed(r, p):
    P("cube", "frame", (0, 0, 0.22), (1.0, 1.3, 0.2), "#8c5a3c", r)
    P("cube", "mattress", (0, 0, 0.48), (0.95, 1.25, 0.08), "#ffffff", r)
    P("cube", "blanket", (0, -0.35, 0.57), (0.97, 0.9, 0.04), ACC, r)
    P("cube", "pillow", (0, 0.95, 0.6), (0.45, 0.18, 0.08), "#ffffff", r)
    P("cube", "head", (0, 1.28, 0.65), (1.0, 0.05, 0.45), "#8c5a3c", r)


def p_desk_pc(r, p):
    P("cube", "top", (0, 0, 0.75), (0.8, 0.4, 0.03), "#d9c2a0", r)
    for dx in (-0.72, 0.72):
        P("cube", "leg", (dx, 0, 0.37), (0.04, 0.36, 0.37), "#d9c2a0", r)
    P("cube", "monitor", (0, 0.15, 1.08), (0.32, 0.03, 0.21), "#222222", r)
    P("cube", "screen", (0, 0.115, 1.08), (0.29, 0.01, 0.18), shade(ACC, 1.2), r, unlit=True)
    P("cube", "stand", (0, 0.18, 0.85), (0.04, 0.03, 0.08), "#222222", r)
    P("cube", "keys", (0, -0.12, 0.79), (0.22, 0.07, 0.01), "#333333", r)
    P("cube", "chair_seat", (0, -0.65, 0.48), (0.24, 0.24, 0.04), "#444a5a", r)
    P("cube", "chair_back", (0, -0.86, 0.8), (0.24, 0.04, 0.3), "#444a5a", r)
    P("cyl", "chair_leg", (0, -0.65, 0.24), (0.04, 0.04, 0.24), "#222222", r, vertices=6)


def p_bookshelf(r, p):
    P("cube", "frame", (0, 0, 1.0), (0.5, 0.18, 1.0), "#7a4a2a", r)
    for i in range(4):
        z = 0.3 + i * 0.48
        x = -0.42
        while x < 0.38:
            w = RNG.uniform(0.03, 0.07)
            h = RNG.uniform(0.15, 0.2)
            P("cube", "book", (x + w, -0.05, z + h), (w * 0.9, 0.12, h),
              rand_col("#e05a5a", "#5a8fe0", "#f2c14e", "#7fd18a", "#c36bff", "#ffffff"), r)
            x += w * 2 + 0.01


def p_plant(r, p):
    P("cyl", "pot", (0, 0, 0.3), (0.28, 0.28, 0.3), "#c96a3c", r, vertices=6)
    P("ico", "leaves", (0, 0, 0.95), (0.5, 0.5, 0.65), rand_col("#4caf50", "#3f9a46"), r, subdivisions=1)


def p_floor_lamp(r, p):
    P("cyl", "base", (0, 0, 0.03), (0.2, 0.2, 0.03), "#333333", r, vertices=8)
    P("cyl", "pole", (0, 0, 0.8), (0.025, 0.025, 0.8), "#333333", r, vertices=4)
    P("cone", "shade", (0, 0, 1.65), (0.3, 0.3, 0.2), "#ffe9a8", r, unlit=True, vertices=8, radius1=1, radius2=0.6, depth=2)


def p_sofa(r, p):
    c = rand_col(ACC, "#6b8fd6", "#7fbf7f", "#c9a27a")
    P("cube", "base", (0, 0, 0.3), (1.0, 0.42, 0.18), c, r)
    P("cube", "back", (0, 0.32, 0.65), (1.0, 0.12, 0.3), c, r)
    for dx in (-0.95, 0.95):
        P("cube", "arm", (dx, 0, 0.5), (0.1, 0.42, 0.2), shade(c, 0.85), r)
    for dx in (-0.48, 0.48):
        P("cube", "cushion", (dx, -0.02, 0.52), (0.44, 0.36, 0.06), shade(c, 1.15), r)


def p_rug(r, p):
    P("cyl", "rug", (0, 0, 0.008), (1.9, 1.3, 0.004), shade(ACC, 1.25), r, vertices=16)
    P("cyl", "rug_in", (0, 0, 0.012), (1.5, 1.0, 0.004), shade(ACC, 0.95), r, vertices=16)


def p_counter(r, p):
    P("cube", "body", (0, 0, 0.55), (1.6, 0.45, 0.55), "#8c5a3c", r)
    P("cube", "top", (0, 0, 1.12), (1.7, 0.52, 0.05), "#f0e6da", r)
    P("cube", "item", (0.9, 0.1, 1.35), (0.25, 0.2, 0.2), "#c0c4cc", r)
    P("cyl", "pot", (-0.6, 0.1, 1.25), (0.12, 0.12, 0.1), ACC, r, vertices=8)


def p_fridge(r, p):
    P("cube", "body", (0, 0, 0.9), (0.4, 0.35, 0.9), "#f4f4f4", r)
    P("cube", "split", (0, -0.355, 1.2), (0.4, 0.01, 0.01), "#aaaaaa", r)
    P("cube", "handle", (0.3, -0.37, 1.45), (0.02, 0.02, 0.15), "#888888", r)


def p_tv(r, p):
    P("cube", "stand", (0, 0, 0.3), (0.7, 0.25, 0.3), "#5a3d2b", r)
    P("cube", "tv", (0, 0, 0.95), (0.7, 0.05, 0.4), "#1a1a1a", r)
    P("cube", "screen", (0, -0.055, 0.95), (0.64, 0.01, 0.35), "#4fa0e0", r, unlit=True)


def p_arcade(r, p):
    c = rand_col("#ff3fa4", "#3ff0ff", "#ffe03f", "#7f5fff", "#3fff8f")
    P("cube", "body", (0, 0, 0.85), (0.35, 0.35, 0.85), shade(c, 0.45), r)
    P("cube", "screen", (0, -0.33, 1.25), (0.26, 0.02, 0.2), shade(c, 1.1), r, unlit=True, rot=(-0.3, 0, 0))
    P("cube", "marquee", (0, -0.3, 1.68), (0.33, 0.04, 0.08), c, r, unlit=True)
    P("cube", "panel", (0, -0.42, 0.95), (0.33, 0.12, 0.03), "#222222", r)
    P("cyl", "stick", (-0.1, -0.45, 1.02), (0.015, 0.015, 0.05), "#eeeeee", r, vertices=4)
    for i in range(3):
        P("cyl", "btn", (0.03 + i * 0.08, -0.45, 0.985), (0.025, 0.025, 0.01), rand_col("#ff4040", "#40a0ff", "#ffe040"),
          r, unlit=True, vertices=6)


def p_crate(r, p):
    P("cube", "crate", (0, 0, 0.45), (0.45, 0.45, 0.45), "#a0723f", r)
    P("cube", "band", (0, 0, 0.45), (0.46, 0.46, 0.06), "#7a522a", r)


def p_barrel(r, p):
    P("cyl", "barrel", (0, 0, 0.5), (0.38, 0.38, 0.5), rand_col("#3f6fb0", "#b03f3f", "#6f6f6f"), r, vertices=10)


def _pine(r, snowy=False):
    P("cyl", "trunk", (0, 0, 0.6), (0.18, 0.18, 0.6), "#7a4a2a", r, vertices=5)
    green = rand_col("#2e8b3e", "#3fa34d", "#267a36")
    P("cone", "leaves", (0, 0, 2.1), (1.0, 1.0, 1.2), green, r, vertices=6)
    if snowy:
        P("cone", "snowcap", (0, 0, 2.75), (0.6, 0.6, 0.6), "#ffffff", r, vertices=6)


def p_pine(r, p):
    _pine(r, R.get("snowy") or R.get("theme") == "snow")


def p_tree(r, p):
    P("cyl", "trunk", (0, 0, 0.9), (0.25, 0.25, 0.9), "#7a4a2a", r, vertices=6)
    P("ico", "leaves", (0, 0, 2.5), (1.4, 1.4, 1.15), rand_col("#3fa34d", "#4caf50", "#2e8b3e"), r, subdivisions=1)


def p_palm(r, p):
    lean = RNG.uniform(0.1, 0.3)
    for i in range(5):
        P("cyl", "seg", (math.sin(lean) * i * 0.6, 0, 0.3 + i * 0.58), (0.14 - i * 0.012, 0.14 - i * 0.012, 0.3),
          "#9c7a4a" if i % 2 else "#b08a58", r, vertices=6, rot=(0, lean, 0))
    top = (math.sin(lean) * 3.0, 0, 3.1)
    for k in range(6):
        a = k * math.tau / 6
        P("cube", "frond", (top[0] + math.cos(a) * 0.7, math.sin(a) * 0.7, top[2] - 0.15), (0.75, 0.16, 0.02),
          rand_col("#3fa34d", "#2e8b3e"), r, rot=(0, 0.35, a))


def p_rock(r, p):
    s = RNG.uniform(0.4, 0.9)
    P("ico", "rock", (0, 0, s * 0.35), (s, s * RNG.uniform(0.7, 1.1), s * 0.6),
      rand_col("#8a8a8a", "#7a7f88", "#9a9180"), r, subdivisions=1)


def p_bush(r, p):
    P("ico", "bush", (0, 0, 0.35), (0.7, 0.6, 0.45), rand_col("#3f9a46", "#4caf50", "#2e8b3e"), r, subdivisions=1)


def p_mushroom(r, p):
    s = RNG.uniform(0.6, 1.3)
    P("cyl", "stem", (0, 0, 0.25 * s), (0.08 * s, 0.08 * s, 0.25 * s), "#f4ecd8", r, vertices=6)
    P("uv", "cap", (0, 0, 0.5 * s), (0.32 * s, 0.32 * s, 0.18 * s), rand_col("#e0574c", "#f2c14e", "#c36bff"), r,
      segments=8, ring_count=5)
    for k in range(3):
        a = k * 2.1
        P("ico", "dot", (math.cos(a) * 0.18 * s, math.sin(a) * 0.18 * s, 0.6 * s), (0.04 * s,) * 3, "#ffffff", r,
          unlit=True, subdivisions=1)


def p_bench(r, p):
    P("cube", "seat", (0, 0, 0.5), (0.9, 0.3, 0.05), "#b5651d", r)
    P("cube", "back", (0, 0.25, 0.85), (0.9, 0.04, 0.25), "#b5651d", r)
    for dx in (-0.75, 0.75):
        P("cube", "leg", (dx, 0, 0.25), (0.05, 0.25, 0.25), "#444444", r)


def p_lamppost(r, p):
    P("cyl", "pole", (0, 0, 1.6), (0.06, 0.06, 1.6), "#2f3440", r, vertices=6)
    P("cube", "head", (0, 0, 3.25), (0.2, 0.2, 0.12), "#2f3440", r)
    P("ico", "light", (0, 0, 3.05), (0.16, 0.16, 0.12), "#ffe7a0", r, unlit=True, subdivisions=1)


def p_tombstone(r, p):
    c = rand_col("#8a8f99", "#7a7f88", "#9aa0a8")
    P("cube", "stone", (0, 0, 0.35), (0.3, 0.09, 0.35), c, r, rot=(RNG.uniform(-0.12, 0.12), 0, 0))
    P("cyl", "top", (0, 0, 0.7), (0.3, 0.3, 0.09), c, r, vertices=8, rot=(math.pi / 2, 0, 0))
    P("cube", "cross", (0, -0.1, 0.45), (0.12, 0.01, 0.02), shade(c, 0.6), r)


def p_dead_tree(r, p):
    P("cyl", "trunk", (0, 0, 1.0), (0.15, 0.15, 1.0), "#3b2f2a", r, vertices=5)
    for k in range(4):
        a = RNG.uniform(0, math.tau)
        z = RNG.uniform(1.2, 1.9)
        P("cyl", "branch", (math.cos(a) * 0.35, math.sin(a) * 0.35, z), (0.05, 0.05, 0.45), "#3b2f2a", r,
          vertices=4, rot=(math.sin(a) * 0.9, -math.cos(a) * 0.9, 0))


def p_cactus(r, p):
    h = RNG.uniform(0.9, 1.6)
    P("cyl", "body", (0, 0, h / 2 + 0.2), (0.18, 0.18, h / 2 + 0.2), "#4f9a4f", r, vertices=8)
    for side in (-1, 1):
        if RNG.random() < 0.8:
            z = RNG.uniform(0.6, h)
            P("cyl", "arm_out", (side * 0.3, 0, z), (0.1, 0.1, 0.15), "#4f9a4f", r, vertices=6, rot=(0, math.pi / 2, 0))
            P("cyl", "arm_up", (side * 0.42, 0, z + 0.25), (0.1, 0.1, 0.25), "#4f9a4f", r, vertices=6)


def p_snowman(r, p):
    for i, (z, s) in enumerate([(0.4, 0.45), (1.05, 0.33), (1.5, 0.24)]):
        P("ico", "ball", (0, 0, z), (s, s, s), "#ffffff", r, subdivisions=2)
    P("cone", "nose", (0, -0.3, 1.5), (0.04, 0.04, 0.12), "#ff8c1a", r, vertices=6, rot=(math.pi / 2, 0, 0))
    for dx in (-0.08, 0.08):
        P("ico", "eye", (dx, -0.21, 1.58), (0.03,) * 3, "#111111", r, unlit=True, subdivisions=1)
    P("cube", "scarf", (0, 0, 1.28), (0.3, 0.3, 0.04), ACC, r)


def p_umbrella(r, p):
    P("cyl", "pole", (0, 0, 1.1), (0.03, 0.03, 1.1), "#eeeeee", r, vertices=4)
    P("cone", "canopy", (0, 0, 2.1), (1.2, 1.2, 0.35), ACC, r, vertices=8)
    P("cube", "towel", (0.6, -0.9, 0.01), (0.45, 0.8, 0.005), rand_col("#3fa9e0", "#ffd36b", "#ff6b6b"), r)


def p_building(r, p):
    w, d = RNG.uniform(1.8, 3.0), RNG.uniform(1.8, 3.0)
    h = RNG.uniform(4, 11) * p.get("scale", 1)
    c = rand_col("#8a8fa0", "#a08a7a", "#7a8aa0", "#9aa08a", "#6f7080")
    P("cube", "block", (0, 0, h), (w, d, h), c, r)
    lit = shade(R["palette"].get("accent", "#ffd36b"), 1.0) if R.get("night") else "#cfe3f5"
    for k in range(int(h // 1.3)):
        P("cube", "windows", (0, -d - 0.01, 1.0 + k * 2.3), (w * 0.8, 0.01, 0.35), lit, r, unlit=R.get("night", False))
    r.scale = (1, 1, 1)


def p_console(r, p):
    P("cube", "base", (0, 0, 0.5), (0.7, 0.4, 0.5), "#4a5060", r)
    P("cube", "panel", (0, -0.15, 1.05), (0.7, 0.3, 0.04), "#2a2f3a", r, rot=(0.5, 0, 0))
    for i in range(4):
        P("cube", "screen", (-0.45 + i * 0.3, -0.22, 1.08), (0.11, 0.08, 0.02), rand_col("#3ff0ff", "#7fff7f", "#ff4f6d"),
          r, unlit=True, rot=(0.5, 0, 0))


def p_lollipop(r, p):
    h = RNG.uniform(1.2, 2.4)
    P("cyl", "stick", (0, 0, h / 2), (0.05, 0.05, h / 2), "#ffffff", r, vertices=6)
    c = rand_col("#ff6b9d", "#7fe0ff", "#ffd36b", "#b38bff", "#7fff9f")
    P("cyl", "candy", (0, 0, h + 0.4), (0.45, 0.45, 0.08), c, r, vertices=12, rot=(math.pi / 2, 0, 0))
    P("cyl", "swirl", (0, -0.09, h + 0.4), (0.25, 0.25, 0.02), "#ffffff", r, unlit=True, vertices=12, rot=(math.pi / 2, 0, 0))


def p_gumdrop(r, p):
    s = RNG.uniform(0.4, 0.8)
    P("uv", "drop", (0, 0, 0), (s, s, s * 1.2), rand_col("#ff6b9d", "#7fe0ff", "#ffd36b", "#b38bff", "#7fff9f"), r,
      segments=8, ring_count=6)


def p_school_desk(r, p):
    P("cube", "top", (0, 0, 0.72), (0.45, 0.3, 0.025), "#c9a27a", r)
    P("cube", "leg", (0, 0, 0.36), (0.4, 0.02, 0.36), "#555555", r)
    P("cube", "seat", (0, -0.55, 0.42), (0.2, 0.2, 0.025), "#c9a27a", r)
    P("cube", "back", (0, -0.75, 0.65), (0.2, 0.02, 0.18), "#c9a27a", r)


def p_crystal(r, p):
    c = R["palette"].get("accent", "#7fe0ff")
    for k in range(3):
        a = k * 2.1
        P("cone", "crystal", (math.cos(a) * 0.2, math.sin(a) * 0.2, 0.4), (0.15, 0.15, 0.5), c, r, unlit=True,
          vertices=4, rot=(math.cos(a) * 0.3, math.sin(a) * 0.3, 0))


def p_hill(r, p):
    s = p.get("scale", 8)
    base = R["palette"]["floor"][0]
    P("ico", "hill", (0, 0, -s * 0.3), (s, s, s * 0.6), shade(base, 0.85), r, subdivisions=1)
    r.scale = (1, 1, 1)


def p_water(r, p):
    P("cube", "sea", (0, 0, 0.02), (40, 9, 0.02), R["palette"].get("water", "#3fa9e0"), r)
    for k in range(6):
        P("cube", "foam", (RNG.uniform(-12, 12), -8.8, 0.045), (RNG.uniform(1, 3), 0.1, 0.01), "#ffffff", r, unlit=True)


def p_poster(r, p):
    textured_panel("poster", r, (0, 0, 0), (0.45, 0.02, 0.6), "poster", shade(ACC, 1.1))
    if not (R.get("textures") or {}).get("poster"):
        P("cube", "art", (0, -0.025, 0.1), (0.3, 0.01, 0.25), rand_col("#ffffff", "#ffd36b", "#7fe0ff"), r, unlit=True)


def p_window(r, p):
    P("cube", "frame", (0, 0, 0), (1.3, 0.03, 0.8), "#ffffff", r)
    pane = "#1b2550" if R.get("night") else "#bfe6ff"
    textured_panel("pane", r, (0, -0.035, 0), (1.15, 0.01, 0.68), "window", pane)
    P("cube", "bar", (0, -0.05, 0), (0.03, 0.01, 0.68), "#ffffff", r)


def p_chalkboard(r, p):
    P("cube", "frame", (0, 0, 0), (2.0, 0.03, 0.9), "#8c5a3c", r)
    textured_panel("board", r, (0, -0.03, 0), (1.9, 0.01, 0.8), "chalkboard", "#2f4a3a", unlit=False)
    if not (R.get("textures") or {}).get("chalkboard"):
        for k in range(3):
            P("cube", "chalk", (RNG.uniform(-1.2, 0.4), -0.045, 0.4 - k * 0.3), (RNG.uniform(0.3, 0.7), 0.005, 0.02),
              "#e8f0e8", r, unlit=True)


def p_neon_sign(r, p):
    c = R["palette"].get("trim", ACC)
    textured_panel("sign", r, (0, 0, 0), (1.0, 0.03, 0.35), "neon_sign", "#120a20")
    if not (R.get("textures") or {}).get("neon_sign"):
        P("cube", "bar1", (0, -0.04, 0.12), (0.8, 0.01, 0.035), c, r, unlit=True)
        P("cube", "bar2", (0, -0.04, -0.1), (0.55, 0.01, 0.035), R["palette"].get("accent", "#3ff0ff"), r, unlit=True)


def p_star_window(r, p):
    P("cube", "frame", (0, 0, 0), (1.2, 0.04, 0.75), "#3a4050", r)
    textured_panel("space", r, (0, -0.045, 0), (1.1, 0.01, 0.65), "star_window", "#05070f")
    if not (R.get("textures") or {}).get("star_window"):
        for k in range(12):
            P("cube", "star", (RNG.uniform(-1, 1), -0.06, RNG.uniform(-0.55, 0.55)), (0.015, 0.005, 0.015), "#ffffff", r, unlit=True)
        P("uv", "planet", (0.5, -0.06, 0.2), (0.22, 0.01, 0.22), R["palette"].get("accent", "#ff4f6d"), r, unlit=True,
          segments=10, ring_count=6)


def p_fence(r, p):
    pts = [(x, 9.0) for x in range(-9, 10, 2)] + [(s * 9.0, y) for s in (-1, 1) for y in range(-3, 9, 2)]
    for x, y in pts:
        P("cube", "post", (x, y, 0.45), (0.06, 0.06, 0.45), "#2a2520", r)
    for z in (0.35, 0.7):
        P("cube", "rail", (0, 9.0, z), (9.0, 0.03, 0.03), "#2a2520", r)
        for s in (-1, 1):
            P("cube", "rail", (s * 9.0, 3.0, z), (0.03, 6.0, 0.03), "#2a2520", r)


def _glow_light(name, loc, color, energy, radius=1.0):
    """A coloured point light, so glowing things (lava, slime) light up what's around them."""
    ld = bpy.data.lights.new(name, "POINT")
    ld.energy = energy
    ld.color = H.hexcol(color)
    try:
        ld.shadow_soft_size = radius
        ld.use_shadow = False
    except Exception:
        pass
    o = bpy.data.objects.new(name, ld)
    H.scene.collection.objects.link(o)
    o.location = loc
    return o


def p_liquid(r, p):
    """A pool / river / sea of anything (water, lava, slime...). p: shape, r (radius / half width), color, glow."""
    col, glow, rad = p.get("color", "#3fa9e0"), bool(p.get("glow")), float(p.get("r", 4.0))
    hi = shade(col, 1.45) if glow else "#ffffff"
    rim = shade(R["palette"]["floor"][0], 0.55) if not R.get("indoor") else shade(R["palette"].get("trim", "#888888"), 0.8)
    if p.get("shape") == "pool":
        sx, sy = RNG.uniform(1.0, 1.2), RNG.uniform(0.75, 0.95)
        P("cyl", "rim", (0, 0, 0.03), ((rad + 0.35) * sx, (rad + 0.35) * sy, 0.03), rim, r, vertices=11)
        P("cyl", "liquid", (0, 0, 0.065), (rad * sx, rad * sy, 0.01), col, r, unlit=glow, vertices=11)
        for k in range(int(4 + rad * 2)):      # bubbles / sparkles / foam
            a, d = RNG.uniform(0, math.tau), RNG.uniform(0, rad * 0.8)
            s = RNG.uniform(0.08, 0.22) * (1 if glow else 0.7)
            P("uv" if glow else "cube", "bubble", (math.cos(a) * d * sx, math.sin(a) * d * sy, 0.08),
              (s, s, s * (0.6 if glow else 0.05)), hi, r, unlit=True, **({"segments": 6, "ring_count": 4} if glow else {}))
        for k in range(int(5 + rad * 2)):      # stones round the edge
            a = RNG.uniform(0, math.tau)
            s = RNG.uniform(0.2, 0.45)
            P("ico", "edge_rock", (math.cos(a) * (rad + 0.3) * sx, math.sin(a) * (rad + 0.3) * sy, s * 0.3),
              (s, s * 0.8, s * 0.6), shade(rim, RNG.uniform(0.8, 1.2)), r, subdivisions=1)
        if glow:
            _glow_light("liquid_glow", (p["pos"][0], p["pos"][1], 1.6), col, 70 * rad * rad, rad)
    elif p.get("shape") == "river":
        P("cube", "bank", (0, 0, 0.03), (45, rad + 0.3, 0.03), rim, r)
        P("cube", "liquid", (0, 0, 0.065), (45, rad, 0.01), col, r, unlit=glow)
        for k in range(14):
            s = RNG.uniform(0.3, 1.2)
            P("cube", "ripple", (RNG.uniform(-18, 18), RNG.uniform(-rad * 0.7, rad * 0.7), 0.08), (s, 0.06, 0.005), hi, r, unlit=True)
        if glow:
            for x in (-8, 0, 8):
                _glow_light("liquid_glow", (x, p["pos"][1], 1.4), col, 500, 2.0)
    else:   # sea: fills the horizon behind the stage
        P("cube", "sea", (0, 0, 0.02), (40, 9, 0.02), col, r, unlit=glow)
        for k in range(8):
            P("cube", "foam", (RNG.uniform(-12, 12), -8.8 + RNG.uniform(0, 0.3), 0.045), (RNG.uniform(1, 3), 0.1, 0.01), hi, r, unlit=True)
        if glow:
            for x in (-10, 0, 10):
                _glow_light("liquid_glow", (x, 9.0, 2.0), col, 900, 3.0)


SHAPE_PRIM = {"box": ("cube", {}), "cylinder": ("cyl", {"vertices": 8}), "cone": ("cone", {"vertices": 7}),
              "pyramid": ("cone", {"vertices": 4}), "sphere": ("uv", {"segments": 8, "ring_count": 5}),
              "rock": ("ico", {"subdivisions": 1})}


PROJECT = __import__("pathlib").Path(__file__).resolve().parent.parent


def sprite_mat(path):
    """Cut-out sprite: pixel-sharp texture, hard alpha edge, lit like the set and fogged."""
    img = bpy.data.images.load(str(path), check_existing=True)
    m = bpy.data.materials.new("spr_" + img.name)
    if m.node_tree is None:     # Blender < 5: nodes are off by default (5.x always has them; use_nodes goes in 6.0)
        m.use_nodes = True
    try:
        m.blend_method = "CLIP"
    except Exception:
        pass
    N, L = m.node_tree.nodes, m.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    tex = N.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Closest"
    diff = N.new("ShaderNodeBsdfDiffuse")
    em = N.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.45
    add = N.new("ShaderNodeAddShader")
    L.new(tex.outputs["Color"], diff.inputs["Color"])
    L.new(tex.outputs["Color"], em.inputs["Color"])
    L.new(diff.outputs[0], add.inputs[0])
    L.new(em.outputs[0], add.inputs[1])
    cut = N.new("ShaderNodeMath")
    cut.operation = "GREATER_THAN"
    cut.inputs[1].default_value = 0.5
    L.new(tex.outputs["Alpha"], cut.inputs[0])
    clear = N.new("ShaderNodeBsdfTransparent")
    mix = N.new("ShaderNodeMixShader")
    L.new(cut.outputs[0], mix.inputs[0])
    L.new(clear.outputs[0], mix.inputs[1])
    L.new(H.add_fog(N, L, add.outputs[0]), mix.inputs[2])
    L.new(mix.outputs[0], out.inputs["Surface"])
    return m


def p_sprite(r, p, d):
    """A drawn prop: a camera-facing cut-out (billboarded per shot in blender_build) with a soft ground shadow."""
    asp = float(d.get("sprite_aspect", 1.0))
    h = max(0.2, min(6.0, float(d.get("height", 1.2))))
    if d.get("width"):          # the drawing may show it lower/wider than expected: fit inside height AND width
        h = max(0.2, min(h, float(d["width"]) * 1.15 / asp))
    w = h * asp
    o = P("plane", f"{p['kind']}_sprite", (0, 0, h / 2), (w / 2, h / 2, 1), "#ffffff", r, rot=(math.pi / 2, 0, 0))
    o.data.materials.clear()
    o.data.materials.append(sprite_mat(PROJECT / d["sprite"]))
    o["billboard"] = True
    sw = max(0.12, min(w * 0.38, 0.9))
    P("cyl", "sprite_shadow", (0, 0, 0.011), (sw, max(0.1, min(sw * 0.45, 0.35)), 0.004), "#2a2a2a", r,
      unlit=True, vertices=10)
    return o


def p_model(r, p, d):
    """A real imported model (assets/imported, see pipeline/imported.py). It is loaded, stood on the ground at the
    origin and scaled so it is d["height"] tall; the origin of the root empty stays where the prop was placed."""
    import blender_models as BM
    from mathutils import Matrix
    import bpy as _bpy
    had = {a.name for a in _bpy.data.actions}
    objs = BM.load_model(PROJECT / d["model"]["file"], d["model"]["format"])
    clips = [a.name for a in _bpy.data.actions if a.name not in had]      # this model's own animation clips
    if d.get("person"):                          # a person: facing the camera, and arms down from a T-pose
        BM.face_front(objs)
        BM.relax_tpose(objs)
        BM.brighten_person(objs)                 # her flat cartoon light, not the set's sun alone
    box = BM.bounds(objs)
    if box is None:                              # nothing usable in the file: a plain stand-in
        P("cube", f"{p['kind']}_missing", (0, 0, 0.5), (0.4, 0.4, 0.5), "#ff00ff", r)
        print(f"[sets] imported model {d['model']['file']} has no mesh")
        return None
    lo, hi = box
    native_h = max(0.001, hi.z - lo.z)
    s = max(0.05, min(12.0, float(d.get("height", 1.2)))) / native_h
    holder = H.empty(f"{p['kind']}_model", r, (0, 0, 0))
    holder.location = (-(lo.x + hi.x) / 2 * s, -(lo.y + hi.y) / 2 * s, -lo.z * s)
    holder.scale = (s, s, s)
    if clips:
        holder["clips"] = clips                  # blender_cast.play_clips plays them (an animated pack's people)
    for o in objs:                               # re-parent under the holder, keeping each object's own transform
        o.parent = holder
        o.matrix_parent_inverse = Matrix.Identity(4)
    return holder


def p_custom(r, p, d):
    """An AI-designed prop (propgen): its drawn sprite if it has one, else a list of primitive parts.
    Each copy of a shape prop gets a slight colour/size wobble. Real imported models come first."""
    if d.get("crowd"):                           # a group (imported.crowd_def): each member at its offset
        for i, (md, off) in enumerate(zip(d["crowd"], d.get("offsets") or [])):
            sub = H.empty(f"{p['kind']}_m{i}", r, (off[0], off[1], 0.0))
            sub.rotation_euler = (0.0, 0.0, off[2] if len(off) > 2 else 0.0)
            p_custom(sub, {"kind": f"{p['kind']}_m{i}"}, md)
        return None
    if d.get("model"):
        return p_model(r, p, d)
    # priority: generated 3D parts, then the 2D picture - a picture is only used when there are no parts
    # (or the object was judged too complicated for them)
    if d.get("sprite") and (PROJECT / d["sprite"]).exists() and (not d.get("parts") or d.get("complex")):
        return p_sprite(r, p, d)
    if d.get("explainer"):
        return p_explainer(r, p, d)
    f = 1.0 if d.get("exact") else RNG.uniform(0.9, 1.1)    # a base's hand-made pieces keep their exact colours
    for i, part in enumerate(d.get("parts", [])):
        kind, kw = SHAPE_PRIM.get(part.get("shape"), SHAPE_PRIM["box"])
        sx, sy, sz = (max(0.01, v / 2) for v in part.get("size", (0.5, 0.5, 0.5)))
        rx, ry, rz = (math.radians(v) for v in part.get("rot", (0, 0, 0)))
        glow = bool(part.get("glow"))
        col = part.get("color", "#9a9180")
        P(kind, f"{p['kind']}_{i}", tuple(part.get("pos", (0, 0, sz))), (sx, sy, sz), col if glow else shade(col, f),
          r, unlit=glow, rot=(rx, ry, rz), **kw)


def _half(o, keep, cap_colour):
    """Cut a solid shape in half down its middle (the plane facing the camera) and keep the back or front half,
    the cut closed with a darker cap - a round section (a volcano's cone, a heart's ball, a tank's cylinder) cut
    open like a cross-section diagram: the back half stays, the front half is the cover that comes off."""
    import bmesh
    me = o.data
    bm = bmesh.new()
    bm.from_mesh(me)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, 0), plane_no=(0, 1, 0),
                                 clear_inner=(keep == "back"), clear_outer=(keep == "front"))
    cut = [g for g in res["geom_cut"] if isinstance(g, bmesh.types.BMEdge)]
    before = set(bm.faces)
    if cut:
        bmesh.ops.holes_fill(bm, edges=cut, sides=0)
    caps = [f for f in bm.faces if f not in before]
    if caps:
        me.materials.append(H.mat(cap_colour))
        for f in caps:
            f.material_index = len(me.materials) - 1
    bm.to_mesh(me)
    bm.free()
    me.update()


EXPLAIN = {}     # root object name ->{"groups": {part name: (empty, (lo, hi))}, "cover": (empty, (lo, hi)) or None}


def _part_box(parts):
    lo = [min(q["pos"][k] - q["size"][k] / 2 for q in parts) for k in range(3)]
    hi = [max(q["pos"][k] + q["size"][k] / 2 for q in parts) for k in range(3)]
    return lo, hi


def p_explainer(r, p, d):
    """An explainer object (propgen.design_explainer): parts with the same "name" hang under one empty, so they
    move together (blender_cast.explain_moves turns, slides, fills... it); "cover" parts hang under their own empty
    and are taken away to show it cut open. Each empty sits at the group's pivot: a turn's own pivot, the bottom
    middle for fill/drain (the level rises from the bottom), else the middle."""
    parts = d.get("parts", [])
    by_name, covers = {}, []
    for part in parts:
        (covers if part.get("cover") else by_name.setdefault(part.get("name") or "body", [])).append(part)
    moves = d.get("moves") or []
    info = {"groups": {}, "cover": None, "closed": None, "diagram": None}
    holder = r
    if d.get("sprite") and (PROJECT / d["sprite"]).exists() and (d.get("look_score") or 10) < 3:   # propgen.SPRITE_BELOW
        # only when the closed 3D model failed its look check is it shown closed as the drawn picture of the real
        # thing; the cut-away model takes its place when it opens
        info["closed"] = H.empty(f"{p['kind']}__closed", r, (0, 0, 0))
        p_sprite(info["closed"], p, d)
        holder = info["diagram"] = H.empty(f"{p['kind']}__diagram", r, (0, 0, 0))

    def pivot(name, box):
        lo, hi = box
        mid = [(a + b) / 2 for a, b in zip(lo, hi)]
        for mv in moves:
            if mv.get("part") != name:
                continue
            if mv.get("pivot"):
                return list(mv["pivot"])
            if mv.get("do") in ("fill", "drain"):
                return [mid[0], mid[1], lo[2]]
        return mid

    def build(group_parts, name, piv):
        e = H.empty(f"{p['kind']}__{name}", holder, tuple(piv))
        for i, part in enumerate(group_parts):
            kind, kw = SHAPE_PRIM.get(part.get("shape"), SHAPE_PRIM["box"])
            sx, sy, sz = (max(0.01, v / 2) for v in part.get("size", (0.5, 0.5, 0.5)))
            rx, ry, rz = (math.radians(v) for v in part.get("rot", (0, 0, 0)))
            loc = tuple(a - b for a, b in zip(part.get("pos", (0, 0, sz)), piv))
            o = P(kind, f"{p['kind']}__{name}_{i}", loc, (sx, sy, sz), part.get("color", "#9a9180"), e,
                  unlit=bool(part.get("glow")), rot=(rx, ry, rz), **kw)
            if part.get("half") in ("back", "front"):
                _half(o, part["half"], shade(part.get("color", "#9a9180"), 0.62))
        return e

    for name, gp in by_name.items():
        box = _part_box(gp)
        piv = pivot(name, box)
        info["groups"][name] = (build(gp, name, piv), box)
    if covers:
        box = _part_box(covers)
        info["cover"] = (build(covers, "cover", [(a + b) / 2 for a, b in zip(*box)]), box)
    EXPLAIN[r.name] = info
    return None


def p_balloons(r, p):
    """A bunch of party balloons on strings. The origin is where the strings meet (her hand when she holds it)."""
    cols = ["#ff3b4e", "#ffcf2e", "#3b8bff", "#ff6fc1", "#46d36a", "#a66bff", "#ff8a2e"]
    RNG.shuffle(cols)
    n = int(p.get("count", 6))
    for k in range(n):
        a = k / n * math.tau + RNG.uniform(-0.3, 0.3)
        rad = 0.18 + 0.22 * (k % 2)
        top = Vector((math.cos(a) * rad, math.sin(a) * rad * 0.6, 1.25 + RNG.uniform(0, 0.45)))
        P("uv", "balloon", tuple(top), (0.2, 0.2, 0.25), cols[k % len(cols)], r, segments=10, ring_count=7)
        P("cone", "knot", (top.x, top.y, top.z - 0.27), (0.04, 0.04, 0.04), shade(cols[k % len(cols)], 0.8), r,
          vertices=5, rot=(math.pi, 0, 0))
        mid = top / 2                                     # string from the hand up to the knot
        ln = top.length - 0.27
        d = top.normalized()
        rot = Vector((0, 0, 1)).rotation_difference(d).to_euler()
        P("cyl", "string", tuple(mid * ((ln) / top.length)), (0.006, 0.006, ln / 2), "#f4f4f4", r, vertices=4,
          rot=tuple(rot))


def p_cloud(r, p):
    """A big puffy low-poly cloud: a cluster of flattened balls, white on top, a little blue-grey underneath."""
    n = RNG.randint(5, 8)
    top = "#ffffff" if not R.get("night") else "#8a90b0"
    under = "#dfe8f5" if not R.get("night") else "#5a6080"
    for k in range(n):
        x, y = RNG.uniform(-2.2, 2.2), RNG.uniform(-1.2, 1.2)
        s = RNG.uniform(0.9, 1.8)
        P("ico", "puff", (x, y, RNG.uniform(-0.2, 0.5)), (s, s * 0.9, s * 0.62), top, r, subdivisions=2,
          unlit=not R.get("night"))
    P("ico", "belly", (0, 0, -0.45), (2.6, 1.5, 0.5), under, r, subdivisions=2, unlit=not R.get("night"))
    r["drift"] = True


def p_planet(r, p):
    c = rand_col("#d98a4a", "#6aa0d9", "#c86aa0", "#8ad06a", "#e0c070")
    P("uv", "planet", (0, 0, 0), (1.6, 1.6, 1.6), c, r, segments=12, ring_count=8)
    P("uv", "band", (0, 0, 0.3), (1.63, 1.63, 0.25), shade(c, 0.75), r, segments=12, ring_count=8)
    if RNG.random() < 0.6:
        P("cyl", "ring", (0, 0, 0), (2.8, 2.8, 0.02), shade(c, 1.3), r, vertices=16, rot=(0.35, 0.2, 0))
    r["drift"] = True


def p_space_rock(r, p):
    s = RNG.uniform(0.3, 1.1)
    c = {"core": rand_col("#3a2a26", "#2a201e", "#4a3028"), "underwater": rand_col("#4a6a6a", "#5a7a6a")}.get(
        R.get("air"), rand_col("#7a7f88", "#6a6460", "#8a8a8a"))
    P("ico", "rock", (0, 0, 0), (s, s * RNG.uniform(0.6, 1.0), s * RNG.uniform(0.6, 0.9)), c, r, subdivisions=1,
      rot=(RNG.uniform(0, 3), RNG.uniform(0, 3), 0))
    r["drift"] = True


def p_lava_chunk(r, p):
    s = RNG.uniform(0.5, 1.4)
    P("ico", "chunk", (0, 0, 0), (s, s * 0.8, s * 0.7), "#2a1a16", r, subdivisions=1, rot=(RNG.uniform(0, 3), 0, 0))
    for k in range(3):
        P("cube", "vein", (RNG.uniform(-0.5, 0.5) * s, -0.6 * s, RNG.uniform(-0.3, 0.3) * s),
          (0.35 * s, 0.05, 0.05), "#ff6a1a", r, unlit=True, rot=(0, 0, RNG.uniform(-0.6, 0.6)))
    r["drift"] = True


def p_kelp(r, p):
    h = RNG.uniform(2.5, 5.0)
    c = rand_col("#2f7a4a", "#3a8a3a", "#4a9a5a")
    for k in range(5):
        P("cone", "leaf", (math.sin(k) * 0.15, 0, -h / 2 + k * h / 5), (0.25, 0.08, h / 8), c, r, vertices=4,
          rot=(0, 0.3 * math.sin(k * 1.7), 0))
    r["drift"] = True


PROP_BUILDERS = {k[2:]: v for k, v in globals().items() if k.startswith("p_") and callable(v) and k != "p_custom"}


# --------------------------------------------------------------------------- floors & walls
def _room():
    """Half the room's width and depth (metres) for this set - small rooms are smaller, big halls bigger."""
    w, d = (R or {}).get("room") or [14.0, 12.0]
    return w / 2, d / 2


def floor_indoor(kind, pal):
    c1, c2 = (pal["floor"] + pal["floor"])[:2]
    hw, hd = _room()
    x0, x1, y0, y1 = -hw, hw, -hd - 1.0, hd
    if kind == "planks":
        tiles(x0, x1, y0, y1, 2 * hw, 0.5, c1, c2, lambda i, j: j % 2)
    elif kind == "checker_small":
        tiles(x0, x1, y0, y1, 0.5, 0.5, c1, c2, lambda i, j: (i + j) % 2)
    elif kind == "metal":
        tiles(x0, x1, y0, y1, 1.0, 1.0, c1, c2, lambda i, j: (i + j) % 2)
    else:
        tiles(x0, x1, y0, y1, 1.0, 1.0, c1, c2, lambda i, j: (i + j) % 2)


def tiles(x0, x1, y0, y1, sx, sy, c1, c2, pattern):
    verts, faces, idx = [], [], []
    nx, ny = max(1, round((x1 - x0) / sx)), max(1, round((y1 - y0) / sy))
    for i in range(nx):
        for j in range(ny):
            x, y, b = x0 + i * sx, y0 + j * sy, len(verts)
            verts += [(x, y, 0), (x + sx, y, 0), (x + sx, y + sy, 0), (x, y + sy, 0)]
            faces.append((b, b + 1, b + 2, b + 3))
            idx.append(pattern(i, j))
    me = bpy.data.meshes.new("floor")
    me.from_pydata(verts, [], faces)
    me.update()
    me.materials.append(H.mat(c1))
    me.materials.append(H.mat(c2))
    for poly, mi in zip(me.polygons, idx):
        poly.material_index = mi
    o = bpy.data.objects.new("floor", me)
    H.scene.collection.objects.link(o)
    texture_world_uv(o, "floor", size=2.0)


def walls(pal):
    wall, trim = pal.get("wall", "#f2d7b5"), pal.get("trim", "#a0623d")
    hw, hd = _room()
    wb = P("cube", "wall_back", (0, hd + 0.1, 2.5), (hw, 0.1, 2.5), wall, None)
    P("cube", "trim_back", (0, hd, 0.6), (hw, 0.05, 0.6), trim, None)
    wl = P("cube", "wall_left", (-hw - 0.1, 0, 2.5), (0.1, hd + 0.2, 2.5), shade(wall, 0.95), None)
    P("cube", "trim_left", (-hw, 0, 0.6), (0.05, hd + 0.2, 0.6), trim, None)
    for w in (wb, wl):
        texture_world_uv(w, "walls", size=2.5)
    dollhouse_walls(hw, hd, shade(wall, 0.9))


def dollhouse_walls(hw, hd, colour):
    """The front (camera side) and right walls of a room, seen only from inside: a camera that looks back
    toward the usual camera side (the lead camera on a walk) sees a wall, a camera outside the room looks
    straight through it (back faces culled, no shadows)."""
    y0 = -hd - 1.0                                          # where the floor ends
    for name, verts in (("wall_front", [(-hw, y0, 0), (hw, y0, 0), (hw, y0, 9), (-hw, y0, 9)]),
                        ("wall_right", [(hw, y0, 0), (hw, hd, 0), (hw, hd, 9), (hw, y0, 9)])):
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], [(0, 3, 2, 1)])             # facing into the room
        me.update()
        me.materials.append(H.mat(colour))
        o = bpy.data.objects.new(name, me)
        H.scene.collection.objects.link(o)
        texture_world_uv(o, "walls", size=2.5)
        m = o.data.materials[0].copy()                        # its own copy: the culling is for this wall only
        m.use_backface_culling = True
        try:
            m.use_backface_culling_shadow = True
        except Exception:
            pass
        o.data.materials[0] = m
        try:
            o.visible_shadow = False
        except Exception:
            pass


def ground_outdoor(kind, pal):
    base = pal["floor"][0]
    g = P("cyl", "ground", (0, 0, -0.05), (60, 60, 0.05), base, None, vertices=24)
    if texture_world_uv(g, "floor", size=3.0):
        kind = "textured"       # skip the colour patches; the texture carries the detail
    sky_backdrop()
    if kind == "road":
        P("cube", "road", (0, 4, 0.004), (3.2, 40, 0.004), shade(base, 0.7), None)
        for k in range(12):
            P("cube", "dash", (0, -14 + k * 3.5, 0.01), (0.08, 0.7, 0.004), "#f2d16b", None, unlit=True)
        for s in (-1, 1):
            P("cube", "curb", (s * 3.4, 4, 0.06), (0.2, 40, 0.06), shade(base, 1.3), None)
    elif kind != "textured":
        for k in range(14):        # soft colour patches break up the flat ground
            a, d = RNG.uniform(0, math.tau), RNG.uniform(2, 22)
            s = RNG.uniform(1.0, 3.0)
            P("cyl", "patch", (math.cos(a) * d, math.sin(a) * d + 4, 0.003), (s, s * 0.7, 0.002),
              shade(base, RNG.choice([0.9, 1.08])), None, vertices=8)
    if R.get("light") == "sunset":
        P("ico", "sky_sun", (-14, 60, 6), (6, 6, 6), "#ffb070", None, unlit=True, subdivisions=1)
    elif not R.get("night"):
        P("ico", "sky_sun", (-20, 60, 30), (4, 4, 4), "#fff6b0", None, unlit=True, subdivisions=1)
    else:
        P("ico", "moon", (18, 60, 28), (3, 3, 3), "#e8ecff", None, unlit=True, subdivisions=1)


def make_thing(name, kind, d, helpers):
    """A prop for the cast (a car, a meteor...): an AI-designed definition `d`, or a built-in kind.
    Works on any set, including the hand-made cafe/park (where build() never ran). Returns its root empty."""
    global H, R, RNG
    if H is None:
        H = helpers
    if R is None:
        R = {"palette": {"accent": ACC, "floor": ["#888888"], "trim": "#888888"}, "textures": {}, "fog": [10, 40]}
    if RNG is None:
        RNG = random.Random(7)
    root = H.empty(f"cast_{name}", None, (0, 0, 0))
    if d and (d.get("parts") or d.get("model") or d.get("crowd")):
        p_custom(root, {"kind": name}, d)
    elif kind in PROP_BUILDERS:
        PROP_BUILDERS[kind](root, {"kind": kind, "pos": [0, 0], "scale": 1.0})
    else:
        P("cube", "box", (0, 0, 0.5), (0.5, 0.5, 0.5), ACC, root)
    return root


# --------------------------------------------------------------------------- entry point
def build(recipe, helpers):
    global H, R, RNG, ACC
    H, R = helpers, recipe
    RNG = random.Random(recipe.get("seed", 1))
    pal = recipe["palette"]
    ACC = pal.get("accent", "#ff8fb8")
    H.FOG.update(color=H.hexcol(pal.get("fog", "#9ec4f0")), start=recipe["fog"][0], end=recipe["fog"][1])
    night = recipe.get("night")
    sunset = recipe.get("light") == "sunset"
    if night:
        H.setup_world("#8f95c8", 0.55)
        H.add_sun((0.8, 0.25, 0.6), 0.8, "#9fb0ff")
    elif sunset:     # low, warm sun and a tinted ambient
        H.setup_world(pal.get("fog", "#ffc49a"), 0.45)
        H.add_sun((1.25, 0.15, 0.9), 1.8, "#ffb27a")
    else:
        H.setup_world("#ffffff", 0.4)
        H.add_sun((0.8, 0.25, 0.6), 2.1, "#fff6e8")
    if recipe.get("air"):
        sky_backdrop()               # no ground at all - just the sky / water / rock colour
    elif recipe.get("indoor"):
        floor_indoor(recipe.get("floor", "checker"), pal)
        walls(pal)
    else:
        ground_outdoor(recipe.get("floor", "grass"), pal)
    custom = recipe.get("custom_props") or {}
    for i, p in enumerate(recipe.get("props", [])):
        fn = PROP_BUILDERS.get(p["kind"])
        if not fn and p["kind"] in custom:
            fn = (lambda d: lambda root, p: p_custom(root, p, d))(custom[p["kind"]])
        if not fn:
            print(f"[sets] unknown prop {p['kind']}")
            continue
        root = H.empty(f"{p['kind']}{i}", None, (p["pos"][0], p["pos"][1], p.get("z", 0.0)))
        root.rotation_euler = (0, 0, p.get("rot", 0.0))
        s = p.get("scale", 1.0)
        root.scale = (s, s, s)
        fn(root, p)
        if recipe.get("air"):
            root["drift"] = True       # everything floats; falling sets stream it upward (blender_build)
    print(f"[sets] built '{recipe.get('name')}' ({recipe.get('theme')}) with {len(recipe.get('props', []))} props")
    return {k: tuple(v) for k, v in recipe["marks"].items()}
