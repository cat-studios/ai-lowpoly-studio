"""
The check after every render: the problems found by looking at test videos by hand, looked for automatically, so
they show up as a ⚠️ on the Videos page before the video is posted instead of after.

    output/<name>_check.json = {"time", "issues": [{"level": "warn"|"info", "what", "shots": [1-based], "fix"?}]}

Checks (all cheap; one vision call per 8 shots):
- her missing or hidden in a shot that should show her (the picture model looks at each shot's middle frame -
  she vanished in 2 fps storyboards, a kudu stood between her and the camera)
- cutaways too short to see (one landed on the two words "Number 5:")
- cutaways the script asked for that didn't make it into the video (all 7 animals of a Top 5 were dropped)
- made props shown although they failed their look check
- cast members squeezed into a spot away from her (Blender's "no free spot" warning)
- two sound effects at the same moment
- video and audio of different lengths (a broken encode)
Run again by hand: python pipeline/review.py episodes/<id>.json
"""
import base64
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

SHORT_CUTAWAY = 1.0          # seconds - shorter and it's a flash nobody can read
SOUND_GAP = 0.35             # two sounds closer than this play on top of each other
BATCH = 8                    # shots per picture-model look


def _issue(out, level, what, shots=(), fix=""):
    out.append({"level": level, "what": what, "shots": sorted({int(s) for s in shots}), **({"fix": fix} if fix else {})})


def cutaway_issues(ep, timing, requested, out):
    fps = float(timing["fps"])
    shown = [k for k, s in enumerate(ep["shots"]) if s.get("cutaway") or any(e.get("cutaway") for e in s.get("events") or [])]
    short = [k + 1 for k in shown if k < len(timing["shots"]) and timing["shots"][k]
             and timing["shots"][k]["n"] / fps < SHORT_CUTAWAY]
    if short:
        _issue(out, "warn", f"{len(short)} cutaway(s) last under {SHORT_CUTAWAY:.0f} s - too quick to see", short,
               "Give that line more words, or turn off 'Cut to a new shot every few words'.")
    lost = [k + 1 for k in requested if k not in shown]
    if lost:
        _issue(out, "warn", f"{len(lost)} of {len(requested)} cutaway(s) the script asked for weren't shown", lost,
               "The render log says why: it didn't look like the thing (swap it on Custom Video's 🎭 Who and what "
               "appears cards - one of your models, or Draw it), or its line doesn't name it.")


def cast_issues(ep, build, out):
    cast = ep.get("cast") or {}
    weak = []
    for who, info in cast.items():
        d = (info or {}).get("def") or {}
        if d and d.get("source") != "imported" and d.get("checked") is False and not d.get("sprite"):
            weak.append((who, d.get("look_score")))
    if weak:
        used = {e.get("who"): k + 1 for k, s in enumerate(ep["shots"]) for e in s.get("events") or []}
        _issue(out, "info", "Shown although it didn't quite look like itself: " + ", ".join(
            f"{w.replace('_', ' ')} ({sc}/10)" if sc else w.replace("_", " ") for w, sc in weak),
            [used[w] for w, _ in weak if w in used], "Swap it on the 🎭 Who and what appears cards.")
    logs = [build / "blender.log"] + sorted(build.glob("scene*/blender.log"))
    squeezed = []
    for lg in logs:
        if lg.exists():
            squeezed += re.findall(r"no free spot beside her .*? for a ([\d.]+) m cast member", lg.read_text(
                encoding="utf-8", errors="replace"))
    if squeezed:
        _issue(out, "info", f"{len(squeezed)} arrival(s) had no room beside her and were put further away",
               fix="A smaller set or fewer things in it gives them room.")


def sound_issues(ep, timing, cfg, out):
    import run_episode as R
    import settings as S
    ev = sorted(R.sfx_events(ep, timing, S.deep_merge(cfg["sfx"], ep.get("sfx", {}))), key=lambda x: x[1])
    fps = float(timing["fps"])
    clash = []
    for a, b in zip(ev, ev[1:]):
        if b[1] - a[1] < SOUND_GAP:
            k = next((i for i, t in enumerate(timing["shots"]) if t and (t["f0"] - 1) / fps <= a[1] < (t["f0"] - 1 + t["n"]) / fps), None)
            clash.append((a[0], b[0], k))
    if clash:
        _issue(out, "info", "Two sound effects at the same moment: " + ", ".join(f"{a} + {b}" for a, b, _ in clash),
               [k + 1 for *_, k in clash if k is not None])


def stream_issues(mp4, out):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0",
                            str(mp4)], capture_output=True, text=True, timeout=60)
        lens = {}
        for line in r.stdout.splitlines():
            kind, _, dur = line.partition(",")
            if dur and dur != "N/A":
                lens[kind] = float(dur)
        if "video" in lens and "audio" in lens and abs(lens["video"] - lens["audio"]) > 0.25:
            _issue(out, "warn", f"Video ({lens['video']:.1f} s) and sound ({lens['audio']:.1f} s) have different "
                                "lengths - the encode may be broken", fix="Render it again.")
        if lens.get("video", 0) > 90:
            _issue(out, "info", f"{lens['video']:.0f} s long - Reels over 90 s may not be shown as Reels")
    except Exception:
        pass


def picture_issues(ep, timing, build, ffmpeg, ollama, out, log=print):
    """The picture model looks at the middle frame of every shot that should show her, 8 at a time."""
    if not ollama:
        return
    import llm
    frames = build / "frames"
    fps = float(timing["fps"])
    todo = []
    for k, (s, t) in enumerate(zip(ep["shots"], timing["shots"])):
        if not t or s.get("cutaway") or any(e.get("cutaway") for e in s.get("events") or []):
            continue
        f = frames / f"f_{t['f0'] + max(0, t['n'] // 2):04d}.png"
        if f.exists() and t["n"] / fps >= 0.4:
            todo.append((k, f))
    if not todo:
        return
    who = (ep.get("character") or {}).get("name") or "the main character"
    looks = (ep.get("character") or {}).get("looks") or "a cartoon girl with cat ears"
    bad = {}
    tmp = build / "check_tiles"
    for b0 in range(0, len(todo), BATCH):
        part = todo[b0:b0 + BATCH]
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for n, (_, f) in enumerate(part):
            shutil.copyfile(f, tmp / f"c_{n:02d}.png")
        cols = min(4, len(part))
        rows = math.ceil(len(part) / cols)
        grid = build / "check_grid.png"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp / "c_%02d.png"), "-vf",
                        f"scale=216:384,tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", str(grid)],
                       check=True)
        try:
            # yes/no per frame: asked for a list of "problems", the 4B model listed shots where she was
            # merely far away ("visible but seen from a distance")
            r = llm.chat_json(ollama["url"], ollama.get("vision_model") or ollama["model"],
                              f"These are {len(part)} frames from a cartoon video, in a grid of {cols} columns and {rows} "
                              f"rows, numbered 1 to {len(part)} left to right, top row first. The main character is "
                              f"{looks}. For EVERY frame answer two questions: can you see her at all (even small or far "
                              "away counts as yes)? Does a big object stand between her and the camera, covering most "
                              'of her? Reply with JSON only: {"frames": [{"frame": number, "visible": true or false, '
                              '"blocked": true or false}]}', "Answer for every frame.", 0.1,
                              images=[base64.b64encode(grid.read_bytes()).decode("ascii")])
        except Exception as exc:
            log(f"  check: the picture model couldn't look at shots {part[0][0] + 1}-{part[-1][0] + 1} "
                f"({exc.__class__.__name__})")
            continue
        for p in (r.get("frames") or []) if isinstance(r, dict) else []:
            try:
                n = int(float(p.get("frame"))) - 1
            except Exception:
                continue
            if not 0 <= n < len(part):
                continue
            if p.get("visible") is False or str(p.get("visible")).lower() == "false":
                bad[part[n][0] + 1] = "she isn't in it"
            elif p.get("blocked") is True or str(p.get("blocked")).lower() == "true":
                bad[part[n][0] + 1] = "something is in front of her"
    shutil.rmtree(tmp, ignore_errors=True)
    # a second look at each flagged frame on its own, full size: only what it says twice is reported (in a grid it
    # missed her in a small top-down shot)
    frame_of = {k + 1: f for k, f in todo}
    for shot_no in list(bad):
        try:
            r = llm.chat_json(ollama["url"], ollama.get("vision_model") or ollama["model"],
                              f"Look closely at this frame from a cartoon video. Is {looks} anywhere in it (even "
                              "small or far away)? Is a big object in front of her, covering most of her? Reply with "
                              'JSON only: {"visible": true or false, "blocked": true or false}', "Check the frame.", 0.1,
                              images=[base64.b64encode(frame_of[shot_no].read_bytes()).decode("ascii")])
        except Exception:
            continue                                   # no second look: keep what the first one said
        vis = str(r.get("visible")).lower() if isinstance(r, dict) else ""
        blk = str(r.get("blocked")).lower() if isinstance(r, dict) else ""
        if (bad[shot_no] == "she isn't in it" and vis != "false") or \
                (bad[shot_no] != "she isn't in it" and blk != "true" and vis != "false"):
            bad.pop(shot_no)
    if bad:
        _issue(out, "warn", f"The picture model thinks {who} is missing or hidden in {len(bad)} shot(s): "
               + "; ".join(f"shot {k}: {w}" for k, w in sorted(bad.items()) if w)[:300], list(bad),
               "Look at those shots (🎞 Shots) - the picture model can be wrong.")


def fact_issues(build, out):
    """The fact check before the render (factcheck.py): contradicted facts are a warning, unchecked ones an note."""
    p = Path(build) / "facts.json"
    if not p.exists():
        return
    res = json.loads(p.read_text(encoding="utf-8"))
    for c in res.get("claims") or []:
        if c.get("verdict") == "contradicted":
            _issue(out, "warn", f"A fact may be wrong: \"{c['claim']}\" - {c.get('note') or 'the article says otherwise'}",
                   [c.get("shot") or 0], fix="Check it (source: " + (c.get("source") or "none") + ") and reword the line")
        elif c.get("verdict") == "unknown":
            _issue(out, "info", f"Not checked: \"{c['claim']}\" ({c.get('note') or 'no source found'})", [c.get("shot") or 0])


def check(ep, timing, build, mp4, cfg, requested=(), ffmpeg="ffmpeg", log=print):
    """All the checks -> the issues list (also saved next to the video as <name>_check.json)."""
    out = []
    for fn, args in ((cutaway_issues, (ep, timing, list(requested), out)), (cast_issues, (ep, build, out)),
                     (sound_issues, (ep, timing, cfg, out)), (stream_issues, (mp4, out)),
                     (fact_issues, (build, out)),
                     (picture_issues, (ep, timing, build, ffmpeg, cfg.get("ollama"), out, log))):
        try:
            fn(*args)
        except Exception as exc:                       # a check that breaks never fails the video
            log(f"  check '{fn.__name__}' couldn't run: {exc.__class__.__name__}: {str(exc)[:120]}")
    res = {"time": time.time(), "issues": out}
    Path(mp4).with_name(Path(mp4).stem + "_check.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return out


def requested_cutaways(ep_path):
    """Shots whose script asked for a cutaway (0-based), read from the episode file before the render drops any."""
    try:
        disk = json.loads(Path(ep_path).read_text(encoding="utf-8-sig"))
        return [k for k, s in enumerate(disk.get("shots") or []) if s.get("cutaway")]
    except Exception:
        return []


def main():
    import run_episode as R
    import settings as S
    ap_path = Path(sys.argv[1])
    name = R.slug(ap_path.stem)
    build = ROOT / "build" / name
    mp4 = ROOT / "output" / f"{name}.mp4"
    if not (build / "resolved.json").exists() or not mp4.exists():
        sys.exit("Render the video first.")
    ep = json.loads((build / "resolved.json").read_text(encoding="utf-8-sig"))
    timing = json.loads((build / "timing.json").read_text(encoding="utf-8-sig"))
    issues = check(ep, timing, build, mp4, S.load_settings(), requested_cutaways(ap_path), R.tool("ffmpeg", "FFMPEG"))
    for i in issues:
        print(f"[{i['level']}] {i['what']}" + (f" (shots {', '.join(map(str, i['shots']))})" if i["shots"] else ""))
    print(f"{len(issues)} thing(s) to look at" if issues else "Nothing found.")


if __name__ == "__main__":
    main()
