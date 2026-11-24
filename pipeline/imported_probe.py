"""
Runs INSIDE Blender (headless) to measure imported model files for pipeline/imported.py:

    blender -b --factory-startup --python pipeline/imported_probe.py -- <in.json> <out.json>

in.json  = [{"path": "...", "format": "obj|fbx|blend"}, ...]
out.json = {"<path>": {"ok": true, "height": m, "width": m, "depth": m, "meshes": n}
                    or {"ok": false, "error": "..."}}
"""
import json
import sys
from pathlib import Path

import bpy  # noqa: F401  (this script only runs inside Blender)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_models as BM  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
files = json.loads(Path(argv[0]).read_text(encoding="utf-8-sig"))
result = {}
for f in files:
    BM.clear_scene()
    try:
        objs = BM.load_model(f["path"], f["format"])
        box = BM.bounds(objs)
        if box is None:
            result[f["path"]] = {"ok": False, "error": "no mesh in this file"}
            continue
        lo, hi = box
        result[f["path"]] = {"ok": True, "height": round(hi.z - lo.z, 3),
                             "width": round(max(hi.x - lo.x, hi.y - lo.y), 3), "depth": round(hi.y - lo.y, 3),
                             "meshes": len(BM.mesh_objects(objs))}
    except Exception as exc:          # one broken file must not stop the rest
        result[f["path"]] = {"ok": False, "error": str(exc)[:200] or exc.__class__.__name__}
    print(f"[probe] {Path(f['path']).name}: {'ok' if result[f['path']]['ok'] else result[f['path']]['error']}", flush=True)

Path(argv[1]).write_text(json.dumps(result), encoding="utf-8")
