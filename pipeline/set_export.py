"""
Export a set as a 3D file for the 3D view (sets/<id>.glb), and refresh its preview picture (sets/<id>.png).

    python pipeline/set_export.py <set_id>

The scene is built exactly like a video's (blender_build.py), so the 3D view shows the same props, textures and
imported models the videos use.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402
from progress import report  # noqa: E402
from run_episode import BLENDER_DEFAULT, embed_set, tool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def export(sid, blender):
    cfg = S.load_settings()
    report(0.1, "Building the set")
    ep = {"set": sid, "start": "center", "fps": 15,
          "render_res": [cfg["render"]["width"], cfg["render"]["height"]],
          "character": {"model": "placeholder"},
          "shots": [{"camera": "wide", "action": "idle", "duration": 1.0, "talk": 0}]}
    embed_set(ep)
    work = ROOT / "build" / "set_exports"
    work.mkdir(parents=True, exist_ok=True)
    out_glb = ROOT / "sets" / f"{sid}.glb"
    out_png = ROOT / "sets" / f"{sid}.png"
    ep["_export_glb"] = str(out_glb)
    ep["_still"] = str(out_png)
    jf = work / f"{sid}.json"
    jf.write_text(json.dumps(ep), encoding="utf-8")
    report(0.3, "Exporting the 3D view")
    r = subprocess.run([blender, "-b", "--factory-startup", "--python", str(ROOT / "pipeline" / "blender_build.py"),
                        "--", str(jf), str(work / "frames")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0 or not out_glb.exists():
        print(r.stdout[-2000:], r.stderr[-1500:])
        sys.exit(f"[export] {sid}: Blender failed")
    report(1.0, "Done")
    print(f"[export] {sid}: {out_glb.name} ({out_glb.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    export(sys.argv[1], tool("blender", "BLENDER", BLENDER_DEFAULT))
