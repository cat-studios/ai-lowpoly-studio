"""
A cover picture for each Reel (output/<name>_cover.jpg, 1080x1920): the best frame of the video, picked by the vision
model, with the title on top in the caption style - same N64/VHS look as the video (the frame goes through the same
low-res colour chain, the title is drawn at render resolution so it's pixelated too, then the chunky upscale).

Made at the end of every render (run_episode). Again from the Videos page (🖼 Cover → 🔄 Pick again):
    python pipeline/cover.py episodes/<id>.json [--shot N]
It needs the render's frames (build/<name>/frames) - Settings → Free up disk space deletes them.
"""
import argparse
import base64
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# cameras that show her face well (a cover with her back, a speck or a cutaway doesn't sell the video)
GOOD_CAMS = {"closeup": 3, "medium": 3, "dramatic": 2, "low": 2, "high": 1, "side": 1, "wide": 1}
MAX_CANDIDATES = 8


def candidates(ep, timing, frames_dir, n=MAX_CANDIDATES):
    """[(shot index, frame png, heuristic score)]: the middle frame of the shots that show her, spread over the video."""
    out = []
    for i, (shot, tm) in enumerate(zip(ep["shots"], timing["shots"])):
        if not tm or shot.get("cutaway") or shot.get("camera") not in GOOD_CAMS:
            continue
        f = frames_dir / f"f_{tm['f0'] + max(0, tm['n'] // 2):04d}.png"
        if not f.exists():
            continue
        score = GOOD_CAMS[shot["camera"]] + (2 if shot.get("expression") not in (None, "", "neutral") else 0) \
            + (1 if i < len(ep["shots"]) / 3 else 0) - (1 if shot.get("speaker") else 0)
        out.append((i, f, score))
    if len(out) > n:                       # the best-looking ones, but from all through the video
        step = len(out) / n
        out = [max(out[int(k * step):int((k + 1) * step)], key=lambda c: c[2]) for k in range(n)]
    return out


def grid(cands, path, ffmpeg):
    """All candidates side by side in one picture (4 per row), for one vision call."""
    tmp = path.parent / "cover_cands"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for k, (_, f, _) in enumerate(cands):
        shutil.copyfile(f, tmp / f"c_{k:02d}.png")
    cols = min(4, len(cands))
    rows = math.ceil(len(cands) / cols)
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp / "c_%02d.png"),
                    "-vf", f"scale=216:384,tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", str(path)],
                   check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return cols, rows


def runner_up(cands, k):
    """Cover B: the best other candidate, preferably from another shot camera-wise far from A (a different look)."""
    others = [j for j in range(len(cands)) if j != k]
    if not others:
        return None
    return max(others, key=lambda j: (cands[j][2], abs(cands[j][0] - cands[k][0])))


def pick(cands, title, grid_png, cols, rows, ollama, log=print):
    """(index into cands, why, index of cover B or None): the vision model's two favourites, else the best
    heuristic scores."""
    best = max(range(len(cands)), key=lambda k: cands[k][2])
    if not ollama or len(cands) < 2:
        return best, "the clearest shot of her", runner_up(cands, best)
    import llm
    try:
        r = llm.chat_json(ollama["url"], ollama.get("vision_model") or ollama["model"],
                          f"These are {len(cands)} frames from a short cartoon video, in a grid of {cols} columns and "
                          f"{rows} rows, numbered 1 to {len(cands)} from left to right, top row first. Pick the best "
                          "one for the video's cover picture: the character's face clearly visible and expressive, "
                          "the picture clear, bright and uncluttered, fitting the title. Also name a DIFFERENT "
                          'second-best one. Reply with JSON only: {"best": number, "second": number, "why": "a few words"}',
                          f"Title: {title or 'a fun short video'}", 0.1,
                          images=[base64.b64encode(grid_png.read_bytes()).decode("ascii")])
        k = int(float(r.get("best"))) - 1
        if 0 <= k < len(cands):
            try:
                k2 = int(float(r.get("second"))) - 1
            except Exception:
                k2 = -1
            return k, str(r.get("why") or "")[:120], k2 if 0 <= k2 < len(cands) and k2 != k else runner_up(cands, k)
    except Exception as exc:
        log(f"  cover: the picture model couldn't choose ({exc.__class__.__name__}) - using the clearest shot")
    return best, "the clearest shot of her", runner_up(cands, best)


def title_ass(path, title, res, cap):
    """The title, big, in the top third: caption font, title colours (second half in the second colour), outline."""
    import run_episode as R
    up = title.upper() if cap.get("uppercase", True) else title
    words = R.ass_text(up).split()
    tcol, tcol2 = R.ass_color(cap.get("title_color"), "#f0f0f0"), R.ass_color(cap.get("title_color2"), "#f0e060")
    shadow = R.ass_color(cap.get("shadow_color"), "#302040")
    longest = max((len(w) for w in words), default=6)
    # as big as fits: about 3 words a line, the longest word inside the width
    size = max(6, min(round(res[1] * 0.062), round(res[0] * 0.9 / (0.68 * max(5, longest)))))
    half = (len(words) + 1) // 2
    text = " ".join(words[:half]) + f"\\N{{\\c{tcol2}&}}" + " ".join(words[half:])
    border = max(1, round(size / 9))
    path.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {res[0]}", f"PlayResY: {res[1]}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Cover,{cap['font'].replace(',', ' ')},{size},{tcol},{tcol},{shadow},{shadow},-1,0,0,0,100,100,1,0,1,"
        f"{border},{border},8,{round(res[0] * 0.05)},{round(res[0] * 0.05)},{round(res[1] * 0.08)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:00:05.00,Cover,,0,0,0,,{text}", ""]), encoding="utf-8")


def render(frame, title, out, build, res, look, cap, ffmpeg):
    """The chosen frame through the video's look + the title -> a 1080x1920 jpg."""
    import run_episode as R
    title_ass(build / "cover.ass", title, res, cap)
    pre = R.low_res_chain(look)
    b, w = look["black"], look["white"]
    v = (f"scale={res[0]}:{res[1]}," + (pre + "," if pre else "") + "subtitles=cover.ass,"
         f"scale={R.OUT_W}:{R.OUT_H}:flags=neighbor"
         + (f",gblur=sigma={look['blur']}" if look.get("blur") and not look.get("sharp_pixels") else "")
         + (f",rgbashift=rh={-look['fringe']}:bh={look['fringe']}:edge=smear" if look.get("fringe") else "")
         + f",eq=saturation={look['saturation']}:contrast={look['contrast']},"
         f"colorlevels=romin={b[0]}:gomin={b[1]}:bomin={b[2]}:romax={w[0]}:gomax={w[1]}:bomax={w[2]}"
         + (",vignette=angle=PI/6" if look.get("vignette") else ""))
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(Path(frame).resolve()), "-vf", v,
                    "-frames:v", "1", "-q:v", "2", str(Path(out).resolve())], cwd=build, check=True)
    return out


def make(ep, timing, build, name, look, cap, ffmpeg, ollama=None, shot=None, log=print):
    """Pick the frame and draw the cover -> (output/<name>_cover.jpg, {shot, why}). None if no frame fits."""
    frames = build / "frames"
    cands = candidates(ep, timing, frames)
    if shot is not None:                                   # chosen by hand (the Videos page)
        tm = timing["shots"][shot]
        f = frames / f"f_{tm['f0'] + max(0, tm['n'] // 2):04d}.png"
        cands, k, why, k2 = [(shot, f, 0)], 0, "picked by you", None
    elif not cands:
        all_f = sorted(frames.glob("f_*.png"))
        if not all_f:
            return None, {}
        cands, k, why, k2 = [(0, all_f[len(all_f) // 3], 0)], 0, "no clear shot of her - a frame a third of the way in", None
    else:
        gp = build / "cover_grid.png"
        cols, rows = grid(cands, gp, ffmpeg)
        k, why, k2 = pick(cands, ep.get("title", ""), gp, cols, rows, ollama, log)
    out = ROOT / "output" / f"{name}_cover.jpg"
    res = ep.get("render_res") or [216, 384]
    render(cands[k][1], ep.get("title") or "", out, build, res, look, cap, ffmpeg)
    info = {"shot": cands[k][0], "why": why}
    out_b = ROOT / "output" / f"{name}_cover_b.jpg"
    if k2 is not None:                                     # cover B: another frame, to try against A
        render(cands[k2][1], ep.get("title") or "", out_b, build, res, look, cap, ffmpeg)
        info["b_shot"] = cands[k2][0]
    elif out_b.exists() and shot is None:
        out_b.unlink()                                     # an old B of a different render would mislead
    (build / "cover.json").write_text(json.dumps(info), encoding="utf-8")
    return out, info


def main():
    import run_episode as R
    import settings as S
    ap = argparse.ArgumentParser(description="Make (or remake) a video's cover picture from its render frames")
    ap.add_argument("episode", type=Path)
    ap.add_argument("--shot", type=int, help="use this shot (1 = the first) instead of letting the AI choose")
    args = ap.parse_args()
    name = R.slug(args.episode.stem)
    build = ROOT / "build" / name
    if not (build / "resolved.json").exists() or not (build / "timing.json").exists() \
            or not any((build / "frames").glob("f_*.png")):
        sys.exit("This video's render frames are gone (Settings → Free up disk space deletes them) - render it "
                 "again to get a new cover.")
    cfg = S.load_settings()
    ep = json.loads((build / "resolved.json").read_text(encoding="utf-8-sig"))
    timing = json.loads((build / "timing.json").read_text(encoding="utf-8-sig"))
    look = S.deep_merge(S.deep_merge(cfg["look"], S.LOOK_PRESETS.get(ep.get("look_preset") or "", {})), ep.get("look", {}))
    cap = S.deep_merge(cfg["captions"], ep.get("captions", {}))
    shot = None
    if args.shot:
        shot = max(0, min(len(timing["shots"]) - 1, args.shot - 1))
    out, info = make(ep, timing, build, name, look, cap, R.tool("ffmpeg", "FFMPEG"), cfg["ollama"], shot)
    if not out:
        sys.exit("No frames to make a cover from.")
    print(f"Cover -> {out} (shot {info['shot'] + 1}: {info['why']})")


if __name__ == "__main__":
    main()
