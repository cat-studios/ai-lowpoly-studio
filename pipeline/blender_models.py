"""
Loading real imported models (assets/imported) inside Blender. Used by blender_sets.p_model and by
imported_probe.py. Runs only inside Blender (needs bpy).

OBJ and FBX use Blender's own importers; a .blend contributes its mesh objects. MDL has no importer in
Blender, so those are recorded as "needs conversion" by pipeline/imported.py and never loaded here.
"""
import bpy
from pathlib import Path

from mathutils import Vector


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def load_model(path, fmt):
    """Import one model file into the current scene. Returns its TOP-LEVEL objects (children stay under them)."""
    path = str(path)
    before = {o.name for o in bpy.data.objects}
    if fmt == "obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif fmt == "fbx":
        bpy.ops.import_scene.fbx(filepath=path, use_image_search=True)
    elif fmt == "blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is None:
                continue
            if o.type in ("CAMERA", "LIGHT"):      # a model file's own camera/lights would light the set twice
                bpy.data.objects.remove(o, do_unlink=True)
            else:
                bpy.context.scene.collection.objects.link(o)
    else:
        raise RuntimeError(f"{fmt} files can't be loaded by Blender (convert to OBJ or FBX first)")
    new = [o for o in bpy.data.objects if o.name not in before and o.name in bpy.context.scene.objects]
    recolour_grey(new, path)
    fix_invisible(new, path)
    names = {o.name for o in new}
    return [o for o in new if o.parent is None or o.parent.name not in names]


def face_front(objs, log=print):
    """Turn a person model so it faces -Y (the camera side, the studio's front) - packs come facing any way (the
    "100 Avatars" ones face sideways: profile to the camera). The shoulder line is the wider horizontal axis at
    chest height; the toes (lowest points) stick out to the front."""
    import math
    from mathutils import Matrix
    pts = [o.matrix_world @ v.co for o in objs if o.type == "MESH" for v in o.data.vertices] + \
        [c.matrix_world @ v.co for o in objs for c in o.children_recursive if c.type == "MESH" for v in c.data.vertices]
    if len(pts) < 20:
        return 0.0
    zs = [p.z for p in pts]
    lo, hi = min(zs), max(zs)
    h = max(1e-4, hi - lo)
    chest = [p for p in pts if lo + 0.55 * h < p.z < lo + 0.8 * h] or pts
    ex = max(p.x for p in chest) - min(p.x for p in chest)
    ey = max(p.y for p in chest) - min(p.y for p in chest)
    side_on = ey > ex * 1.2                       # the shoulders run along Y: it faces +X or -X
    ax = "x" if side_on else "y"
    mid = (max(getattr(p, ax) for p in pts) + min(getattr(p, ax) for p in pts)) / 2
    feet = [getattr(p, ax) - mid for p in pts if p.z < lo + 0.05 * h]
    fwd = (sum(feet) / len(feet)) if feet else 0.0          # toes point to the front
    if side_on:
        angle = -math.pi / 2 if fwd > 0 else math.pi / 2    # +X front -> turn to -Y ; -X front -> turn to -Y
    else:
        angle = math.pi if fwd > 0.02 * h else 0.0          # it faces +Y (its back to the camera)
    if not angle:
        return 0.0
    rot = Matrix.Rotation(angle, 4, "Z")
    for o in objs:
        o.matrix_world = rot @ o.matrix_world
    bpy.context.view_layer.update()
    log(f"[models] person model turned {round(math.degrees(angle))} deg to face the camera")
    return angle


def relax_tpose(objs, angle=1.2, log=print):
    """A person model stored in a T-pose with no skeleton (the "100 Avatars" pack: one mesh, arms straight out):
    the arm vertices are turned down round each shoulder, so a person in a scene doesn't stand there like a
    scarecrow. Only called for people (actors / imported people). Nothing changes when the arms aren't out."""
    import math
    from mathutils import Matrix, Vector
    meshes = [o for o in objs if o.type == "MESH"] + [c for o in objs for c in o.children_recursive if c.type == "MESH"]
    if not meshes or any(o.type == "ARMATURE" for o in objs) or any(c.type == "ARMATURE" for o in objs
                                                                    for c in o.children_recursive):
        return False
    pts = [(o, v, o.matrix_world @ v.co) for o in meshes for v in o.data.vertices]
    zs = [p.z for _, _, p in pts]
    lo, hi = min(zs), max(zs)
    h = max(1e-4, hi - lo)
    cx = (max(p.x for _, _, p in pts) + min(p.x for _, _, p in pts)) / 2     # the middle of the box
    span = max(abs(p.x - cx) for _, _, p in pts)
    hips = [abs(p.x - cx) for _, _, p in pts if lo + 0.35 * h < p.z < lo + 0.55 * h]
    torso = max(hips) if hips else 0.2 * h
    if span < 0.3 * h or span < 2.2 * torso:             # arms aren't straight out: not a T-pose
        return False
    tips = [p for _, _, p in pts if abs(p.x - cx) > 0.85 * span]
    arm_z = sum(p.z for p in tips) / len(tips)
    if not (lo + 0.6 * h < arm_z < lo + 0.92 * h):        # the far-out points must be at shoulder height
        return False
    # the body's width just below the arms (at the hips a candy-cane body is only thin legs: the body got bent)
    below = [abs(p.x - cx) for _, _, p in pts if arm_z - 0.2 * h < p.z < arm_z - 0.06 * h]
    if below:
        torso = max(torso, max(below))
    sx = torso * 1.1                                      # the shoulder joint, just outside the body
    blend = min(0.08 * h, 0.35 * sx)                     # a narrow bend at the shoulder (0.08 h bent a whole thin body)

    def bend(p):
        """Where a (world) point goes: arm points swing down round their shoulder; the body stays."""
        dx = p.x - cx
        side = 1 if dx > 0 else -1
        out = abs(dx) - sx
        if out <= 0:
            return p                                      # the body never moves (bending it made a flared collar)
        w = min(1.0, out / blend)                         # the arm's root eases into the turn
        pivot = Vector((cx + side * sx, p.y, arm_z))
        # about +Y a positive angle takes +X towards -Z: the right arm (+X) turns by +a, the left by -a - both down
        return pivot + Matrix.Rotation(side * angle * w, 3, "Y") @ (p - pivot)

    for o in meshes:
        mw, inv = o.matrix_world, o.matrix_world.inverted()
        keys = o.data.shape_keys.key_blocks if o.data.shape_keys else []
        for kb in keys:                                   # shape keys (blinks...) hold the real positions
            for d in kb.data:
                d.co = inv @ bend(mw @ d.co)
        for v in o.data.vertices:
            v.co = inv @ bend(mw @ v.co)
        o.data.update()
    log(f"[models] arms lowered out of a T-pose ({len(pts)} points; h {h:.2f} span {span:.2f} body {torso:.2f} arms at {(arm_z - lo) / h:.2f})")
    return True


def fix_invisible(objs, path=""):
    """Some FBX files carry an opacity Blender reads as 0: every material of the Quaternius "Posed Background
    Characters" came in with Alpha 0, so cast people rendered as just a blob shadow. A material whose alpha isn't
    driven by a texture and is (nearly) 0 is made solid."""
    fixed = 0
    for o in objs:
        if o.type != "MESH":
            continue
        for m in o.data.materials:
            if not m or not m.node_tree:
                continue
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED" and "Alpha" in n.inputs:
                    a = n.inputs["Alpha"]
                    if not a.is_linked and a.default_value < 0.05:
                        a.default_value = 1.0
                        fixed += 1
                        try:
                            m.blend_method = "OPAQUE"
                        except Exception:
                            pass
    if fixed:
        print(f"[models] {fixed} see-through material(s) made solid in {Path(str(path)).name}")
    return fixed


# Some packs lost their colours on export: every material is Blender's default grey (0.64) - the Public Transport
# pack came out as all-grey vehicles. Their material NAMES still say what they are ("Red", "Windows", "Lights").
NAME_COLOURS = [   # (words in the material name, colour, glows)
    (("window", "windows", "glass", "windshield", "windscreen", "mirror"), "#9fd0e8", False),
    (("light", "lights", "lamp", "headlight", "bulb"), "#fff2b0", True),
    (("wheel", "wheels", "tyre", "tire", "tires", "rubber", "bumper", "black"), "#2a2a30", False),
    (("red",), "#d94a4a", False), (("white",), "#f2f0ea", False), (("blue",), "#3f6fd0", False),
    (("yellow",), "#f2c230", False), (("green",), "#4caf50", False), (("orange",), "#f0903a", False),
    (("pink",), "#ff8fb8", False), (("brown", "wood", "wooden"), "#8a5a36", False), (("rope",), "#c9a36a", False),
    (("dark",), "#3a3a40", False), (("grey", "gray", "metal", "steel", "silver", "handle", "frame"), "#9aa0aa", False),
    (("bike",), "#d94a4a", False), (("bottom",), "#3a3a40", False), (("hair",), "#3a2a20", False),
]
BODY_COLOURS = {"ambulance": "#f2f0ea", "taxi": "#f2c230", "school": "#f2b030", "bus": "#3f8fd0",
                "train": "#d94a4a", "cop": "#2b3a73", "police": "#2b3a73"}


def recolour_grey(objs, path):
    import re
    file_words = set(re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", Path(path).stem).lower()))
    body = next((c for w, c in BODY_COLOURS.items() if w in file_words), "#e8e4dc")
    seen = set()
    for o in mesh_objects(objs):
        for slot in o.material_slots:
            m = slot.material
            if m is None or m.name in seen:
                continue
            seen.add(m.name)
            node = m.node_tree.nodes.get("Principled BSDF") if getattr(m, "node_tree", None) else None
            col = node.inputs["Base Color"].default_value if node else m.diffuse_color
            if not all(abs(col[i] - 0.64) < 0.012 for i in range(3)):     # it has a real colour: leave it
                continue
            ws = set(re.findall(r"[a-z]+", m.name.lower()))
            hexc, glow = next(((c, g) for keys, c, g in NAME_COLOURS if ws & set(keys)), (body, False))
            rgb = tuple(int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
            lin = tuple(c ** 2.2 for c in rgb) + (1.0,)                  # node colours are linear
            if node:
                node.inputs["Base Color"].default_value = lin
                if glow and "Emission Color" in node.inputs:
                    node.inputs["Emission Color"].default_value = lin
                    node.inputs["Emission Strength"].default_value = 1.5
            m.diffuse_color = lin


def mesh_objects(objs):
    """Every mesh under these objects (including children)."""
    out, todo = [], list(objs)
    while todo:
        o = todo.pop()
        if o.type == "MESH":
            out.append(o)
        todo.extend(o.children)
    return out


def bounds(objs):
    """World-space (min, max) corners of all meshes under objs, or None if there are no meshes."""
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    found = False
    for o in mesh_objects(objs):
        found = True
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
    return (lo, hi) if found else None
