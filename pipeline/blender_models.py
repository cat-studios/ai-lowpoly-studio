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
    names = {o.name for o in new}
    return [o for o in new if o.parent is None or o.parent.name not in names]


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
