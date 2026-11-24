"""
Convert a video (mp4, mov, m4v, webm...) into a high-quality animated GIF, kept under a size cap.

    python pipeline/gif.py input.mp4 [--out output/gifs/name.gif] [--width 0] [--fps 0]
                                     [--colors 256] [--dither sierra2_4a|floyd_steinberg|bayer|none]
                                     [--max-mb 10]

A GIF holds 256 colours per palette, so the quality comes from how that palette is made and applied:
  * full-resolution frames unless --width is given (Lanczos scaling, never upscaled)
  * the source frame rate, capped at 50 fps (the GIF maximum browsers honour), or --fps
  * ONE palette worked out from every frame of the clip (palettegen stats_mode=full), not a guess
  * Sierra 2-4A error-diffusion dithering by default - the smoothest gradients (--dither bayer for a crisper look)
  * no frame differencing (diff_mode is off), so every frame is a complete, clean image
  * loops forever

Size cap: the first try uses the settings above. If the GIF is bigger than --max-mb (default 10 MB), it steps
down only as far as needed: frame rate first (least visible), then width, then colours. The first version that
fits is kept; if nothing fits, the smallest attempt is kept and a warning is printed.

Prints PROGRESS lines for the web app's progress bar and GIF=<path> when done.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import progress  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GIFS = ROOT / "output" / "gifs"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
DITHER = {
    "sierra2_4a": "sierra2_4a",
    "floyd_steinberg": "floyd_steinberg",
    "bayer": "bayer:bayer_scale=3",
    "none": "none",
}
MAX_FPS = 50
MB = 1024 * 1024


def probe(src):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(src)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"ffprobe could not read {src.name}: {r.stderr[-300:]}")
    data = json.loads(r.stdout or "{}")
    st = (data.get("streams") or [{}])[0]
    if not st.get("width"):
        raise SystemExit(f"{src.name} has no video stream")
    try:
        fps = float(Fraction(st.get("r_frame_rate") or "0/1"))
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    if not 0 < fps <= 240:
        fps = 24.0
    dur = float((data.get("format") or {}).get("duration") or 0)
    return {"w": int(st["width"]), "h": int(st["height"]), "fps": fps, "dur": dur}


def chain(info, fps, width):
    """Frame-rate and scale steps shared by both passes, so the palette sees exactly the frames that get encoded."""
    steps = [f"fps={fps:g}"]
    if width and width < info["w"]:
        steps.append(f"scale={width}:-2:flags=lanczos")
    return ",".join(steps)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("ffmpeg failed:\n" + (r.stderr or "")[-800:])


def encode(src, info, out, fps, width, colors, dither, span):
    """One full two-pass encode (palette from all frames, then paletteuse). span = (lo, hi) of the progress bar."""
    lo, hi = span
    vf = chain(info, fps, width)
    with tempfile.TemporaryDirectory() as tmp:
        palette = Path(tmp) / "palette.png"
        progress.report(lo, "Analysing every frame's colours")
        run([FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
             "-vf", f"{vf},palettegen=max_colors={colors}:stats_mode=full:reserve_transparent=0",
             "-frames:v", "1", str(palette)])

        mid = lo + (hi - lo) * 0.15
        progress.report(mid, "Encoding GIF")
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
               "-progress", "pipe:1", "-nostats",
               "-i", str(src), "-i", str(palette),
               "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither={DITHER[dither]}:new=0",
               "-loop", "0", "-an", "-f", "gif", str(out)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") and info["dur"] > 0:
                try:
                    done = int(line.split("=", 1)[1]) / 1e6 / info["dur"]
                except ValueError:
                    continue
                progress.report(mid + (hi - mid) * min(1.0, done), "Encoding GIF")
            elif line and not line.startswith(("progress=", "out_time", "bitrate=", "total_size=", "speed=",
                                               "frame=", "fps=", "stream_", "dup_", "drop_", "packet", "N/A")):
                tail.append(line)
        if proc.wait() != 0:
            raise SystemExit("ffmpeg failed:\n" + "\n".join(tail[-12:]))
    return out.stat().st_size


def ladder(info, fps, width, colors):
    """Settings to try, best first. Only one thing changes per step, so the quality loss stays as small as possible."""
    w0 = min(width, info["w"]) if width else info["w"]
    tries = [(fps, w0, colors)]
    for f in (30, 24, 20, 15):                       # 1. lower the frame rate (least visible)
        if f < fps:
            tries.append((f, w0, colors))
    f_low = min(fps, 24)
    for x in (0.85, 0.75, 0.65, 0.55, 0.45, 0.35):   # 2. then the frame size
        w = int(w0 * x) // 2 * 2
        if 120 <= w < w0:
            tries.append((f_low, w, colors))
    w_low = max(120, int(w0 * 0.55) // 2 * 2)
    for c in (128, 64):                              # 3. then fewer colours, as a last resort
        if c < colors:
            tries.append((f_low, w_low, c))
    seen, out = set(), []
    for t in tries:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", help="GIF path (default output/gifs/<name>.gif)")
    ap.add_argument("--width", type=int, default=0, help="output width in px (0 = original size)")
    ap.add_argument("--fps", type=float, default=0, help="frame rate (0 = the video's own, max 50)")
    ap.add_argument("--colors", type=int, default=256, choices=range(2, 257), metavar="2-256",
                    help="palette size (256 = best)")
    ap.add_argument("--dither", choices=list(DITHER), default="sierra2_4a")
    ap.add_argument("--max-mb", type=float, default=10.0, help="keep the GIF under this size (default 10 MB)")
    a = ap.parse_args()

    src = Path(a.input).resolve()
    if not src.is_file():
        raise SystemExit(f"no such file: {src}")
    out = (Path(a.out) if a.out else GIFS / f"{src.stem}.gif").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    limit = int(a.max_mb * MB)

    info = probe(src)
    fps0 = min(a.fps, MAX_FPS) if a.fps else min(info["fps"], MAX_FPS)
    print(f"Source {info['w']}x{info['h']} @ {info['fps']:.2f} fps, {info['dur']:.1f} s", flush=True)
    print(f"Target under {a.max_mb:g} MB. Starting at best quality.", flush=True)

    tries = ladder(info, fps0, a.width, a.colors)
    best = None                                       # (size, settings, tmp file)
    with tempfile.TemporaryDirectory() as work:
        for i, (fps, width, colors) in enumerate(tries):
            lo = i / len(tries) * 0.95
            hi = (i + 1) / len(tries) * 0.95
            cand = Path(work) / f"try{i}.gif"
            size = encode(src, info, cand, fps, width, colors, a.dither, (lo, hi))
            w_out = min(width, info["w"]) if width else info["w"]
            print(f"Try {i + 1}: {w_out}px wide, {fps:g} fps, {colors} colours -> {size / MB:.1f} MB", flush=True)
            if best is None or size < best[0]:
                best = (size, (fps, w_out, colors), cand)
            if size <= limit:
                break
        size, (fps, w_out, colors), cand = best
        if size > limit:
            print(f"Warning: even the smallest setting is {size / MB:.1f} MB (over {a.max_mb:g} MB).", flush=True)
        shutil.move(str(cand), str(out))              # keep the chosen version before the temp folder is cleared

    progress.report(1.0, "Done")
    print(f"Final: {w_out}px wide, {fps:g} fps, {colors} colours, dither {a.dither}, {size / MB:.1f} MB", flush=True)
    print(f"GIF={out}", flush=True)


if __name__ == "__main__":
    main()
