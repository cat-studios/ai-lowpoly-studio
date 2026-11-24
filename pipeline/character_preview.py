"""
Render a still preview of each character (assets/characters/<id>.preview.png), shown on the Characters page.

    python pipeline/character_preview.py <character id> [<character id> ...]

Uses the same character loading as a video (run_episode.resolve_character) in a plain park, one medium shot
standing still. Characters without a model file are skipped: there is nothing to draw yet.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402
from progress import report  # noqa: E402
from run_episode import BLENDER_DEFAULT, embed_set, resolve_character, tool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHAR_DIR = ROOT / "assets" / "characters"


def preview(cid, blender):
    cfg = S.load_settings()
    ep = {"set": "park", "start": "center", "fps": 15,
          "render_res": [cfg["render"]["width"], cfg["render"]["height"]],
          "character": cid,
          "shots": [{"camera": "medium", "action": "idle", "move": "static", "expression": "happy",
                     "duration": 1.0, "talk": 0}]}
    prof = resolve_character(dict(ep), cfg)
    if prof.get("model") in (None, "placeholder"):
        print(f"[preview] {cid}: no model file - nothing to draw, skipped")
        return False
    ep["character"] = prof
    embed_set(ep)
    work = ROOT / "build" / "character_previews"
    work.mkdir(parents=True, exist_ok=True)
    out = CHAR_DIR / f"{cid}.preview.png"
    ep["_still"] = str(out)
    jf = work / f"{cid}.json"
    jf.write_text(json.dumps(ep), encoding="utf-8")
    report(0.2, f"Drawing {prof.get('name', cid)}")
    r = subprocess.run([blender, "-b", "--factory-startup", "--python", str(ROOT / "pipeline" / "blender_build.py"),
                        "--", str(jf), str(work / "frames")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    for line in r.stdout.splitlines():
        if line.startswith(("[build]", "[sets]")) or "Error" in line:
            print(line)
    if r.returncode != 0 or not out.exists():
        print(r.stdout[-2000:], r.stderr[-1500:])
        sys.exit(f"[preview] {cid}: Blender failed")
    print(f"[preview] {cid}: {out}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    b = tool("blender", "BLENDER", BLENDER_DEFAULT)
    ids = sys.argv[1:]
    for i, cid in enumerate(ids):
        report(i / len(ids), f"Character {i + 1}/{len(ids)}")
        preview(cid, b)
    report(1.0, "Done")
