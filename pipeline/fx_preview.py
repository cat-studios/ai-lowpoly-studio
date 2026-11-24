"""
Render short looping preview clips of the particle effects for the Assets page.

    python pipeline/fx_preview.py [effect ...]      # default: every effect
-> assets/fx_previews/<effect>.mp4 (looping clip) + <effect>.jpg (poster). Uses the user's edits
(assets/fx_overrides.json) and the active character, in the park.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_fx  # noqa: E402
import settings as S  # noqa: E402
from run_episode import BLENDER_DEFAULT, embed_set, resolve_character, tool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "fx_previews"
SECS = 2.0


NIGHT_FX = {"stars", "fireflies"}     # invisible in daylight: previewed on a night set


def night_set():
    for js in sorted((ROOT / "sets").glob("*.json")):
        try:
            rec = json.loads(js.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if rec.get("night") and not rec.get("indoor") and not rec.get("air"):
            return rec["id"]
    return "park"


def render(names, set_id, tag, cfg):
    ep = {"set": set_id, "start": "center", "fps": 24, "render_res": [216, 384],
          "shots": [{"camera": "wide" if n in ("stars", "speed_lines") else "medium", "action": "idle",
                     "duration": SECS, "talk": 0, "particles": [n]} for n in names]}
    ep["character"] = resolve_character(ep, cfg)
    embed_set(ep)
    work = ROOT / "build" / f"fx_previews_{tag}"
    if work.exists():
        shutil.rmtree(work)
    (work / "frames").mkdir(parents=True)
    jf = work / "episode.json"
    jf.write_text(json.dumps(ep), encoding="utf-8")
    print(f"[fx] rendering {len(names)} preview(s) in {set_id}: {', '.join(names)}")
    from progress import FrameWatcher
    total = round(SECS * 24) * len(names)
    with FrameWatcher(work / "frames", total, BAR[0], BAR[0] + (BAR[1] - BAR[0]) * 0.85, f"Rendering {tag} previews"):
        r = subprocess.run([tool("blender", "BLENDER", BLENDER_DEFAULT), "-b", "--factory-startup", "--python",
                        str(ROOT / "pipeline" / "blender_build.py"), "--", str(jf), str(work / "frames")],
                           capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or "Traceback" in r.stdout or "Traceback" in r.stderr:
        print(r.stdout[-3000:], r.stderr[-1500:])
        sys.exit("[fx] Blender failed")
    timing = json.loads((work / "timing.json").read_text(encoding="utf-8-sig"))
    OUT.mkdir(parents=True, exist_ok=True)
    ffmpeg = tool("ffmpeg", "FFMPEG")
    for n, sh in zip(names, timing["shots"]):
        f0, cnt = sh["f0"], sh["n"]
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(timing["fps"]),
                        "-start_number", str(f0), "-i", str(work / "frames" / "f_%04d.png"), "-frames:v", str(cnt),
                        "-vf", "scale=324:576:flags=neighbor,format=yuv420p", "-c:v", "libx264", "-crf", "24",
                        "-movflags", "+faststart", "-an", str(OUT / f"{n}.mp4")], check=True)
        mid = f0 + cnt // 2
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i",
                        str(work / "frames" / f"f_{mid:04d}.png"), "-vf", "scale=324:576:flags=neighbor", "-q:v", "4",
                        str(OUT / f"{n}.jpg")], check=True)
        print(f"[fx] preview ready: {n}")


BAR = [0.0, 1.0]


def main():
    from progress import report
    names = [n for n in sys.argv[1:] if n in blender_fx.FX] or list(blender_fx.FX)
    cfg = S.load_settings()
    day = [n for n in names if n not in NIGHT_FX]
    night = [n for n in names if n in NIGHT_FX]
    split = len(day) / max(1, len(names))
    if day:
        BAR[:] = [0.02, 0.02 + 0.96 * split]
        render(day, "park", "day", cfg)
    if night:
        BAR[:] = [0.02 + 0.96 * split, 0.98]
        render(night, night_set(), "night", cfg)
    report(1.0, "Done")


if __name__ == "__main__":
    main()
