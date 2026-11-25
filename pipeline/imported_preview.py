"""
Runs INSIDE Blender (headless): a still picture of each imported model, for the Imported tab's cards.

    blender -b --factory-startup --python pipeline/imported_preview.py -- <in.json> <out_dir>

in.json = [{"id": "...", "path": "...", "format": "obj|fbx|blend"}, ...]
-> out_dir/<id>.png (square, transparent background, the model standing on the floor, slightly from above).
"""
import json
import math
import sys
from pathlib import Path

import bpy  # noqa: F401  (this script only runs inside Blender)
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_models as BM  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
items = json.loads(Path(argv[0]).read_text(encoding="utf-8-sig"))
out_dir = Path(argv[1])
out_dir.mkdir(parents=True, exist_ok=True)
SIZE = 320

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = scene.render.resolution_y = SIZE
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.film_transparent = True
world = scene.world or bpy.data.worlds.new("preview_world")
scene.world = world
if world.node_tree is None:     # Blender < 5 (use_nodes goes in 6.0)
    world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg is not None:
    bg.inputs[0].default_value = (0.85, 0.85, 0.88, 1.0)
    bg.inputs[1].default_value = 0.9

for it in items:
    BM.clear_scene()
    try:
        objs = BM.load_model(it["path"], it["format"])
        box = BM.bounds(objs)
        if box is None:
            print(f"[preview] {it['id']}: no mesh", flush=True)
            continue
        lo, hi = box
        centre = (lo + hi) / 2
        size = max(0.05, (hi - lo).length)
        # the model stands on the floor at the origin
        for o in objs:
            o.location = o.location - Vector((centre.x, centre.y, lo.z))
        centre = Vector((0.0, 0.0, (hi.z - lo.z) / 2))
        cam_data = bpy.data.cameras.new("preview_cam")
        cam = bpy.data.objects.new("preview_cam", cam_data)
        scene.collection.objects.link(cam)
        dist = size * 1.25
        cam.location = centre + Vector((dist * 0.7, -dist * 0.9, dist * 0.45))
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.camera = cam
        sun_data = bpy.data.lights.new("preview_sun", "SUN")
        sun_data.energy = 3.0
        sun = bpy.data.objects.new("preview_sun", sun_data)
        scene.collection.objects.link(sun)
        sun.rotation_euler = (math.radians(55), 0.0, math.radians(35))
        scene.render.filepath = str(out_dir / f"{it['id']}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[preview] {it['id']}", flush=True)
    except Exception as exc:                 # one broken model must not stop the others
        print(f"[preview] {it['id']} failed: {str(exc)[:160]}", flush=True)
