"""
Render a still preview of a set (sets/<id>.png) - a wide shot with the placeholder character.

    python pipeline/set_preview.py <set_id> [<set_id> ...]
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402
from run_episode import BLENDER_DEFAULT, embed_set, tool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def preview(sid, blender):
    cfg = S.load_settings()
    ep = {"set": sid, "start": "center", "fps": 15, "render_res": [cfg["render"]["width"], cfg["render"]["height"]],
          "character": {"model": "placeholder"},
          "shots": [{"camera": "wide", "action": "wave", "duration": 1.0, "talk": 0}]}
    embed_set(ep)
    work = ROOT / "build" / "set_previews"
    work.mkdir(parents=True, exist_ok=True)
    out = (ROOT / "sets" / f"{sid}.png") if sid not in ("cafe", "park") else (ROOT / "sets" / f"_{sid}.png")
    ep["_still"] = str(out)
    jf = work / f"{sid}.json"
    jf.write_text(json.dumps(ep), encoding="utf-8")
    r = subprocess.run([blender, "-b", "--factory-startup", "--python", str(ROOT / "pipeline" / "blender_build.py"),
                        "--", str(jf), str(work / "frames")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    for line in r.stdout.splitlines():
        if line.startswith(("[sets]", "[build]")) or "Error" in line:
            print(line)
    if r.returncode != 0 or not out.exists():
        print(r.stdout[-3000:], r.stderr[-2000:])
        sys.exit(f"preview failed for {sid}")
    print(f"Preview: {out}")


if __name__ == "__main__":
    b = tool("blender", "BLENDER", BLENDER_DEFAULT)
    for sid in sys.argv[1:]:
        preview(sid, b)
