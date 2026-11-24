"""
Loading real imported models (assets/imported) inside Blender. Used by blender_sets.p_model and by
imported_probe.py. Runs only inside Blender (needs bpy).

OBJ and FBX use Blender's own importers; a .blend contributes its mesh objects. MDL has no importer in
Blender, so those are recorded as "needs conversion" by pipeline/imported.py and never loaded here.
"""
import bpy
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
    names = {o.name for o in new}
    return [o for o in new if o.parent is None or o.parent.name not in names]


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
