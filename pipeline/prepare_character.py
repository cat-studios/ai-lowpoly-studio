"""
One-time conversion: VRoid .vrm -> N64-ready .blend the episode builder can load.

    blender -b --factory-startup --python pipeline/prepare_character.py -- assets/characters/catgirl.vrm
        [--tex 128] [--decimate 0.5] [--keep-outline]

Writes next to the .vrm:
    catgirl.blend         armature + meshes, small packed textures, fog-ready materials
    catgirl.report.json   bones, shape keys, triangle counts, size (used to map animations)
"""
import argparse
import json
import math
import sys
from pathlib import Path

import addon_utils
import bpy

ap = argparse.ArgumentParser()
ap.add_argument("vrm", type=Path)
ap.add_argument("--tex", type=int, default=128, help="max texture size (N64 used tiny textures)")
ap.add_argument("--decimate", type=float, default=0.5, help="poly ratio for meshes without shape keys")
ap.add_argument("--keep-outline", action="store_true", help="keep MToon anime outlines")
ap.add_argument("--out", type=Path, help="output .blend (default: next to the .vrm, same name)")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])

src = args.vrm.resolve()
if not src.exists():
    sys.exit(f"Not found: {src}")
out_blend = (args.out.resolve() if args.out else src.with_suffix(".blend"))
out_report = out_blend.with_suffix(".report.json")

# default_set=True registers add-on preferences (the importer needs them); with
# --factory-startup in background mode nothing is written back to the user's prefs.
addon_utils.enable("bl_ext.blender_org.vrm", default_set=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

print(f"[prep] importing {src.name}")
bpy.ops.import_scene.vrm(filepath=str(src))

arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if arm is None or not meshes:
    sys.exit("Import produced no armature/meshes - is this a VRoid VRM?")


def tri_count(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    total = 0
    for o in objs:
        me = o.evaluated_get(dg).to_mesh()
        total += sum(len(p.vertices) - 2 for p in me.polygons)
        o.evaluated_get(dg).to_mesh_clear()
    return total


tris_before = tri_count(meshes)

# ---- strip anime outlines (MToon geometry-node outline modifiers) -------------------
if not args.keep_outline:
    for o in meshes:
        for m in list(o.modifiers):
            if "outline" in m.name.lower():
                o.modifiers.remove(m)

# ---- reduce polys on meshes that have no shape keys (hair, body, accessories) -------
if args.decimate < 1.0:
    for o in meshes:
        if o.data.shape_keys or len(o.data.polygons) < 300:
            continue
        m = o.modifiers.new("lowpoly", "DECIMATE")
        m.ratio = args.decimate
        with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
            bpy.ops.object.modifier_apply(modifier=m.name)

# ---- shrink textures -------------------------------------------------------------
for img in bpy.data.images:
    w, h = img.size[:]
    if w == 0 or h == 0:
        continue
    s = min(1.0, args.tex / max(w, h))
    if s < 1.0:
        img.scale(max(1, int(w * s)), max(1, int(h * s)))
    try:
        img.pack()
    except RuntimeError:
        pass

# ---- rebuild materials: base texture, soft anime lighting, alpha, fog hook ---------
SKIP = ("normal", "shade", "emiss", "matcap", "rim", "outline", "sphere")


def base_image(mat):
    if not mat.node_tree:
        return None
    imgs = [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    for n in imgs:   # prefer the texture wired into a "lit"/"base"/"color" input
        for link in n.outputs["Color"].links:
            name = link.to_socket.name.lower()
            if any(k in name for k in ("lit", "base", "color")) and not any(k in name for k in SKIP):
                return n.image
    for n in imgs:
        if not any(k in n.image.name.lower() for k in SKIP):
            return n.image
    return None


def rebuild(mat):
    img = base_image(mat)
    col = tuple(mat.diffuse_color)
    N, L = mat.node_tree.nodes, mat.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    diff = N.new("ShaderNodeBsdfDiffuse")
    emis = N.new("ShaderNodeEmission")
    emis.inputs["Strength"].default_value = 0.55        # keeps shadow sides bright and "anime"
    add = N.new("ShaderNodeAddShader")
    trans = N.new("ShaderNodeBsdfTransparent")
    amix = N.new("ShaderNodeMixShader")
    if img:
        tex = N.new("ShaderNodeTexImage")
        tex.image = img
        tex.interpolation = "Linear"                       # N64 bilinear blur on tiny textures
        L.new(tex.outputs["Color"], diff.inputs["Color"])
        L.new(tex.outputs["Color"], emis.inputs["Color"])
        # hard alpha cut-out: soft alpha on tiny textures + 1-sample dithering made lace/cloth
        # edges sparkle with noise; a clean 0/1 mask keeps edges crisp (and very N64)
        cut = N.new("ShaderNodeMath")
        cut.operation = "GREATER_THAN"
        cut.inputs[1].default_value = 0.5
        L.new(tex.outputs["Alpha"], cut.inputs[0])
        L.new(cut.outputs[0], amix.inputs["Fac"])
    else:
        diff.inputs["Color"].default_value = col
        emis.inputs["Color"].default_value = col
        amix.inputs["Fac"].default_value = 1.0
    L.new(diff.outputs[0], add.inputs[0])
    L.new(emis.outputs[0], add.inputs[1])
    L.new(trans.outputs[0], amix.inputs[1])
    L.new(add.outputs[0], amix.inputs[2])
    # "fog_in" / "fog_out": the episode builder splices its distance fog in between these
    amix.name, out.name = "fog_in", "fog_out"
    L.new(amix.outputs[0], out.inputs["Surface"])
    for attr, val in (("surface_render_method", "DITHERED"), ("use_backface_culling", False)):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass


for o in meshes:
    for slot in o.material_slots:
        if slot.material and slot.material.node_tree:
            rebuild(slot.material)

# ---- collect everything into one collection and save -----------------------------
coll = bpy.data.collections.new("Character")
bpy.context.scene.collection.children.link(coll)
for o in [arm] + meshes + [c for c in bpy.data.objects if c.parent in meshes or c.parent == arm]:
    for c in list(o.users_collection):
        c.objects.unlink(o)
    if o.name not in coll.objects:
        coll.objects.link(o)
for o in list(bpy.data.objects):
    if o.name not in coll.objects:
        bpy.data.objects.remove(o, do_unlink=True)
arm.name = "CharacterRig"
try:
    bpy.data.orphans_purge(do_recursive=True)
except Exception:
    pass

# ---- report: what the animation mapper needs to know --------------------------------
bones = {b.name: [round(v, 3) for v in (arm.matrix_world @ b.head_local)] for b in arm.data.bones}
zs = [v for o in meshes for v in ((o.matrix_world @ c).z for c in [__import__("mathutils").Vector(b) for b in o.bound_box])]
eye = next((n for n in bones if "FaceEye" in n), None)
head = next((n for n in bones if n.endswith("_Head")), None)
facing = None
if eye and head:
    facing = "-Y" if bones[eye][1] < bones[head][1] else "+Y"
report = {
    "source": src.name,
    "height_m": round(max(zs) - min(zs), 3),
    "faces": facing,
    "tris_before": tris_before,
    "tris_after": tri_count(meshes),
    "textures": {i.name: list(i.size) for i in bpy.data.images if i.size[0]},
    "meshes": {o.name: {"shape_keys": [k.name for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else []}
               for o in meshes},
    "bones": bones,
}
out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend), compress=True)
print(f"[prep] {report['tris_before']} -> {report['tris_after']} tris, height {report['height_m']} m, faces {facing}")
print(f"[prep] saved {out_blend}")
print(f"[prep] report {out_report}")
