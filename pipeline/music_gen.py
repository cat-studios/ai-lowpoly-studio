"""
Generate background music and add it to the music library (assets/music/).

Engines:
  ace   - ACE-Step 1.5 through ComfyUI (real instrumental music from a style description)
  synth - built-in retro chiptune generator (instant, no AI, always available)

    python pipeline/music_gen.py --style "cheerful lofi chiptune, cute" --seconds 60 [--engine ace|synth|auto]
"""
import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comfy  # noqa: E402
import settings as S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MUSIC = ROOT / "assets" / "music"


def ace_model(url):
    for c in comfy._options(url, "CheckpointLoaderSimple", "ckpt_name"):
        if "ace_step" in c.lower() or "acestep" in c.lower():
            return c
    return None


def ace_generate(url, ckpt, tags, seconds, bpm, key, seed, out_mp3, log=print):
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["1", 1], "tags": tags, "lyrics": "[instrumental]", "seed": seed, "bpm": bpm,
            "duration": float(seconds), "timesignature": "4", "language": "en", "keyscale": key,
            "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9, "top_k": 0,
            "min_p": 0.0}},
        "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]}},
        "4": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0],
                                                   "latent_image": ["4", 0], "seed": seed, "steps": 8, "cfg": 1.0,
                                                   "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["7", 0], "filename_prefix": "lowpoly_music",
                                                       "quality": "V0"}},
    }
    pid = comfy._json(url, "/prompt", {"prompt": graph, "client_id": "lowpoly"})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        hist = comfy._json(url, f"/history/{pid}")
        if pid in hist:
            st = hist[pid].get("status", {})
            for node in hist[pid].get("outputs", {}).values():
                for a in node.get("audio", []):
                    q = urllib.parse.urlencode({"filename": a["filename"], "subfolder": a.get("subfolder", ""),
                                                "type": a.get("type", "output")})
                    out_mp3.write_bytes(comfy._get(url, f"/view?{q}", timeout=120))
                    return out_mp3
            if st.get("status_str") == "error":
                msg = next((m[1].get("exception_message", "") for m in st.get("messages", [])
                            if m[0] == "execution_error"), "")
                raise RuntimeError(f"ComfyUI error: {msg[:300]}")
        time.sleep(2)
    raise TimeoutError("ACE-Step took too long")


# ---------------------------------------------------------------- built-in chiptune synth
def synth_generate(seconds, bpm, seed, out_mp3, ffmpeg, mood="happy"):
    """A random 4-chord chiptune loop: square-wave arpeggio + bass + noise hats."""
    rng = random.Random(seed)
    root = rng.choice([48, 50, 52, 53, 55, 57])                    # MIDI root (C3..A3)
    minor = mood in ("sad", "spooky", "dark", "chill")
    scale = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    prog = rng.choice([[0, 5, 3, 4], [0, 3, 4, 3], [0, 4, 5, 3], [5, 3, 0, 4], [0, 0, 3, 4]])
    beat = 60.0 / bpm
    bar = beat * 4

    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    def chord(deg):
        return [root + scale[(deg + k) % 7] + 12 * ((deg + k) // 7) for k in (0, 2, 4)]

    # build piecewise expressions per bar (cycle of 4 bars)
    arp, bass = [], []
    for i, deg in enumerate(prog):
        c = chord(deg)
        arp.append((i, [hz(n + 12) for n in c] + [hz(c[0] + 24)]))
        bass.append((i, hz(c[0] - 12)))
    cyc = f"mod(t,{bar * 4:.4f})"
    bar_idx = f"floor({cyc}/{bar:.4f})"
    step = f"floor(mod(t,{bar:.4f})/{beat / 4:.4f})"   # 16th notes

    def pick(items, idx_expr):
        fmt = lambda v: v if isinstance(v, str) else f"{v:.2f}"
        expr = fmt(items[-1])
        for k in range(len(items) - 2, -1, -1):
            expr = f"if(lt({idx_expr},{k + 1}),{fmt(items[k])},{expr})"
        return expr

    arp_f = pick([pick(notes, f"mod({step},4)") for _, notes in arp], bar_idx)
    bass_f = pick([b for _, b in bass], bar_idx)
    env16 = f"(1-mod(t,{beat / 4:.4f})/{beat / 4:.4f})"
    lead = f"0.16*sgn(sin(2*PI*{arp_f}*t))*{env16}"
    bas = f"0.22*sgn(sin(2*PI*{bass_f}*t))*(0.6+0.4*(1-mod(t,{beat:.4f})/{beat:.4f}))"
    hat = f"0.06*(random(0)*2-1)*lt(mod(t,{beat / 2:.4f}),0.03)"
    expr = f"{lead}+{bas}+{hat}"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=44100:d={seconds}",
                    "-af", f"lowpass=f=4500,afade=t=out:st={max(0, seconds - 2)}:d=2,loudnorm=I=-16:TP=-1.5",
                    "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3)], check=True)
    return out_mp3


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "track"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="cheerful retro chiptune, video game, cute, upbeat")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--engine", choices=["auto", "ace", "synth"], default="auto")
    ap.add_argument("--name", default="")
    args = ap.parse_args()
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cfg = S.load_settings()
    seed = random.randrange(1, 2**31)
    bpm = args.bpm or random.choice([90, 100, 110, 120, 128, 140])
    MUSIC.mkdir(parents=True, exist_ok=True)
    out = MUSIC / f"gen-{slug(args.name or args.style)}-{time.strftime('%m%d-%H%M%S')}.mp3"
    engine = args.engine
    url = None
    if engine in ("auto", "ace") and cfg["comfy"]["mode"] != "off":
        st = comfy.status(cfg["comfy"]["url"])
        url = st["url"] if st["ok"] else None
        ckpt = ace_model(url) if url else None
        if ckpt:
            engine = "ace"
        elif engine == "ace":
            sys.exit("ACE-Step isn't available in ComfyUI (is ComfyUI running, with the ace_step checkpoint?)")
        else:
            engine = "synth"
    elif engine == "auto":
        engine = "synth"
    if engine == "ace":
        key = random.choice(["C major", "G major", "D major", "A minor", "E minor", "F major"])
        print(f"[music] ACE-Step via ComfyUI: '{args.style}', {args.seconds:.0f}s, {bpm} bpm, {key}")
        __import__("progress").report(0.15, "Composing with ACE-Step")
        ace_generate(url, ckpt, args.style, args.seconds, bpm, key, seed, out)
        tmp = out.with_suffix(".tmp.mp3")      # gentle fades + level match so loops sit well under voices
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(out), "-af",
                        f"afade=t=in:d=0.5,afade=t=out:st={max(0, args.seconds - 2)}:d=2,loudnorm=I=-16:TP=-1.5",
                        "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k", str(tmp)], check=True)
        tmp.replace(out)
    else:
        mood = "sad" if re.search(r"sad|melanchol|spooky|dark|creepy|chill|night", args.style, re.I) else "happy"
        print(f"[music] built-in chiptune synth: {args.seconds:.0f}s, {bpm} bpm, {mood}")
        __import__("progress").report(0.3, "Synthesising chiptune")
        synth_generate(args.seconds, bpm, seed, out, ffmpeg, mood)
    meta = out.with_suffix(".json")
    meta.write_text(json.dumps({"style": args.style, "engine": engine, "bpm": bpm, "seed": seed,
                                "seconds": args.seconds}), encoding="utf-8")
    print(f"[music] saved {out.name}")
    __import__("progress").report(1.0, "Done")
    print(f"MUSIC={out.name}")


if __name__ == "__main__":
    main()
