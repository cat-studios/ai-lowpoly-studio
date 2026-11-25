"""
Turn an episode JSON into a finished vertical Reel.

    python pipeline/run_episode.py episodes/test_coffee_shop.json

Steps: resolve the character, co-stars, scenes, cutaways and cast -> voice lines (local Chatterbox clone / Edge /
ElevenLabs / Windows, cached) -> shot timing -> Blender render (headless, one pass per scene)
-> N64 post filter + captions + audio mix (ffmpeg) -> output/<name>.mp4 + <name>_shots.png
"""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402
from progress import FrameWatcher, report, quiet  # noqa: E402
import sfx as sfxlib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLENDER_DEFAULT = r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe"
AUDIO_LEAD = 0.15   # seconds from shot start until the line starts (mouth uses the same); from settings
TAIL_PAD = 0.6      # seconds of breathing room after a line; from settings
OUT_W, OUT_H = 1080, 1920
FRESH = False       # --fresh-voice: ignore the voice cache


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "episode"


def tool(name, env_var, default=None):
    path = os.environ.get(env_var) or shutil.which(name) or default
    if not path or not Path(path).exists():
        sys.exit(f"Can't find {name}. Install it or set {env_var}.")
    return path


def wav_seconds(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


DEFAULT_VOICE = {"engine": "edge", "name": "en-US-AnaNeural", "rate": "+8%", "pitch": "+15Hz"}


def _tts_windows(text, raw, voice):
    """Offline fallback: Windows built-in speech (robotic)."""
    txt = raw.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    q = lambda p: str(p).replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "try { $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female) } catch {};"
        f"$s.Rate = {int(voice.get('rate', 1)) if str(voice.get('rate', 1)).lstrip('-').isdigit() else 1};"
        f"$s.SetOutputToWaveFile('{q(raw)}');"
        f"$s.Speak((Get-Content -Raw -Encoding UTF8 '{q(txt)}'));"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True)
    txt.unlink(missing_ok=True)


def _tts_edge(text, raw, voice):
    """Free Microsoft neural voices (needs internet). List voices: python -m edge_tts --list-voices"""
    import asyncio
    import edge_tts
    kw = dict(rate=voice.get("rate", "+0%"), pitch=voice.get("pitch", "+0Hz"))
    try:                                   # edge-tts 7 sends sentence boundaries unless asked for words
        comm = edge_tts.Communicate(text, voice.get("name", DEFAULT_VOICE["name"]), boundary="WordBoundary", **kw)
    except TypeError:                      # older edge-tts: words are the default
        comm = edge_tts.Communicate(text, voice.get("name", DEFAULT_VOICE["name"]), **kw)
    words = []

    async def run():
        with open(raw, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":      # offsets in 100 ns units
                    words.append([ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7])
    asyncio.run(run())
    if words:                              # when each word is said: captions and beat cuts follow the voice
        Path(str(raw) + ".words.json").write_text(json.dumps(words), encoding="utf-8")


def _tts_elevenlabs(text, raw, voice):
    """Paid, best quality. Set ELEVENLABS_API_KEY and give "voice_id" in the episode voice block."""
    import urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ElevenLabs voice requested but ELEVENLABS_API_KEY is not set.")
    body = json.dumps({"text": text, "model_id": voice.get("model", "eleven_multilingual_v2"),
                       "voice_settings": voice.get("settings", {"stability": 0.4, "similarity_boost": 0.8})})
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice['voice_id']}?output_format=mp3_44100_128",
        data=body.encode(), headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw.write_bytes(resp.read())


VOICE_PY = ROOT / "tools" / "voice-venv" / "Scripts" / "python.exe"
LOCAL_KEYS = ("ref", "exaggeration", "cfg_weight", "temperature", "seed")


def _local_jobs(items):
    """items: [(text, raw_path, voice)] -> one Chatterbox batch (model loads once)."""
    if not VOICE_PY.exists():
        sys.exit("Local voice engine not installed (tools/voice-venv). See README 'Voice'.")
    jobs = []
    for text, raw, voice in items:
        job = {"text": text, "out": str(raw.with_suffix(".src.wav"))}
        job.update({k: voice[k] for k in LOCAL_KEYS if k in voice})
        if job.get("ref"):
            ref = (ROOT / job["ref"]).resolve()
            if not ref.exists():
                sys.exit(f"Reference voice not found: {ref}")
            job["ref"] = str(ref)
        jobs.append(job)
    jf = items[0][1].parent / "local_jobs.json"
    jf.write_text(json.dumps(jobs), encoding="utf-8")
    env = {**os.environ, "TQDM_DISABLE": "1", "PYTHONWARNINGS": "ignore"}
    proc = subprocess.Popen([str(VOICE_PY), str(ROOT / "pipeline" / "local_tts.py"), str(jf)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    tail = []
    for line in proc.stdout:
        tail = (tail + [line.rstrip()])[-40:]
        if line.startswith("[voice]"):
            print("  " + line.rstrip())
    if proc.wait() != 0:
        print("\n".join(tail))
        sys.exit("Local voice generation failed.")
    for (_, raw, _), job in zip(items, jobs):
        Path(job["out"]).replace(raw)
        w = Path(job["out"] + ".words.json")             # Whisper's word times for the take that was kept
        if w.exists():
            w.replace(str(raw) + ".words.json")


def _tts_local(text, raw, voice):
    """Free local voice (Chatterbox). "ref": a 10-30 s wav of the voice to clone (one you own)."""
    _local_jobs([(text, raw, voice)])


ENGINES = {"edge": _tts_edge, "elevenlabs": _tts_elevenlabs, "windows": _tts_windows, "local": _tts_local}


_WARNED_NO_LOCAL = []


def _normalize_voice(voice):
    if voice.get("engine") == "local" and not VOICE_PY.exists():
        # no Chatterbox on this PC (tools/voice-venv): use the free Edge voice instead of stopping the render
        if not _WARNED_NO_LOCAL:
            print("  (local voice engine not installed - tools/voice-venv; using the free Edge voice instead)")
            _WARNED_NO_LOCAL.append(1)
        voice = {"engine": "edge", **({"shift": voice["shift"]} if voice.get("shift") else {})}
    return {**DEFAULT_VOICE, **voice} if voice.get("engine", "edge") == "edge" else dict(voice)


def _cache_key(text, voice):
    return hashlib.sha1(json.dumps([text, voice], sort_keys=True).encode()).hexdigest()[:16]


def prefetch_local(lines, cache_dir):
    """Generate every uncached 'local' line in one batch before the per-line loop."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for text, voice in lines:
        voice = _normalize_voice(voice)
        if voice.get("engine") != "local":
            continue
        key = _cache_key(text, voice)
        raw = cache_dir / f"{key}.raw"
        if FRESH or (not (cache_dir / f"{key}.wav").exists() and not raw.exists()):
            todo.append((text, raw, voice))
    if todo:
        print(f"  generating {len(todo)} line(s) with the local voice model...")
        _local_jobs(todo)


EMOTION = {"angry": 0.85, "surprised": 0.85, "scared": 0.8, "celebrate": 0.75, "happy": 0.65,
           "laugh": 0.75, "smug": 0.55, "sad": 0.4, "think": 0.4}


def line_voice(voice, shot):
    """Episode voice + shot override; the local engine gets more intense on emotional shots."""
    v = S.layered_voice(voice, shot.get("voice"))
    if v.get("engine") == "local" and "exaggeration" not in (shot.get("voice") or {}):
        mood = shot.get("expression") or shot.get("action")
        if mood in EMOTION:
            v["exaggeration"] = EMOTION[mood]
    return v


def tts(text, out_wav, voice, ffmpeg, cache_dir):
    """Speak one line -> wav, with optional extra pitch shift ("shift": 1.2). Results are cached."""
    voice = _normalize_voice(voice)
    engine = voice.get("engine", "edge")
    if engine not in ENGINES:
        sys.exit(f"Unknown voice engine '{engine}'. Use one of: {', '.join(ENGINES)}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(text, voice)
    cached = cache_dir / f"{key}.wav"
    stale = engine == "edge" and cached.exists() and not cached.with_suffix(".words.json").exists()
    if FRESH or not cached.exists() or stale:     # Edge lines cached before word times existed: quick to redo
        raw = cache_dir / f"{key}.raw"
        try:
            if not raw.exists() or (FRESH and engine != "local"):   # local raws were just prefetched
                ENGINES[engine](text, raw, voice)
        except ImportError:
            print("  (edge-tts not installed: pip install edge-tts; falling back to Windows voice)")
            voice = {"engine": "windows", "shift": 1.25}
            cached = cache_dir / f"{_cache_key(text, voice)}.wav"   # cached as the Windows voice, not as Edge
            ENGINES["windows"](text, raw, voice)
        shift = float(voice.get("shift", 1.0))
        af = (f"aresample=44100,asetrate={int(44100 * shift)},aresample=44100,atempo={1 / shift:.5f}"
              if abs(shift - 1.0) > 1e-3 else "aresample=44100")
        part = cached.with_name(cached.stem + ".part.wav")       # a failed or cut-off encode never lands in the cache
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
                        "-af", af + ",silenceremove=start_periods=1:start_threshold=-50dB,"
                        "loudnorm=I=-14:TP=-1.5,aresample=44100",
                        "-ac", "1", str(part)], check=True)
        part.replace(cached)
        words_raw = Path(str(raw) + ".words.json")
        words_out = cached.with_suffix(".words.json")
        words_out.unlink(missing_ok=True)
        if words_raw.exists():
            try:      # the start's silence was cut off: times count from the first word
                ws = json.loads(words_raw.read_text(encoding="utf-8"))
                t0 = min(w[1] for w in ws) if ws else 0.0
                words_out.write_text(json.dumps([[w[0], round(max(0.0, w[1] - t0), 3), round(max(0.0, w[2] - t0), 3)]
                                                 for w in ws]), encoding="utf-8")
            except Exception:
                pass
            words_raw.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
    shutil.copyfile(cached, out_wav)
    out_words = Path(out_wav).with_suffix(".words.json")
    if cached.with_suffix(".words.json").exists():
        shutil.copyfile(cached.with_suffix(".words.json"), out_words)
    else:
        out_words.unlink(missing_ok=True)
    return wav_seconds(out_wav)


def _norm_word(w):
    return re.sub(r"[^a-z0-9]+", "", w.lower())


def word_starts(text, wav, total):
    """When each word of `text` starts in `wav` (seconds), from the voice engine's word times (Edge word
    boundaries, Whisper for the local voice), or None. Words the engine heard differently are matched by
    spelling; the rest are placed between their neighbours. Spreading the words by length over the whole take
    ran ahead of / behind her speech wherever she paused or talked fast."""
    f = Path(wav).with_suffix(".words.json")
    words = text.split()
    if not words or not f.exists():
        return None
    try:
        timed = [w for w in json.loads(f.read_text(encoding="utf-8")) if _norm_word(str(w[0]))]
    except Exception:
        return None
    if not timed:
        return None
    from difflib import SequenceMatcher
    a, b = [_norm_word(w) for w in words], [_norm_word(str(w[0])) for w in timed]
    starts = [None] * len(words)
    for blk in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            starts[blk.a + k] = float(timed[blk.b + k][1])
    if sum(s is not None for s in starts) < max(1, len(words) // 2):
        return None                        # too different to trust
    starts[0] = 0.0 if starts[0] is None else starts[0]
    known = [i for i, s in enumerate(starts) if s is not None]
    end_t = max(total, max(s for s in starts if s is not None) + 0.2)
    for i in range(len(words)):            # fill gaps between known words, by word length
        if starts[i] is None:
            lo = max(k for k in known if k < i)
            hi = next((k for k in known if k > i), None)
            t_hi, n_hi = (starts[hi], hi) if hi is not None else (end_t, len(words))
            wsum = sum(len(words[k]) + 2 for k in range(lo, n_hi)) or 1
            starts[i] = starts[lo] + (t_hi - starts[lo]) * sum(len(words[k]) + 2 for k in range(lo, i)) / wsum
    for i in range(1, len(starts)):        # never backwards
        starts[i] = max(starts[i], starts[i - 1])
    return [round(s, 3) for s in starts]


VOICE_POOL = ["en-US-GuyNeural", "en-US-ChristopherNeural", "en-GB-RyanNeural", "en-US-AndrewNeural",
              "en-US-JennyNeural", "en-AU-WilliamNeural"]


def unique_voice(cid, voice):
    """A main character's own voice: the one they set, else a voice from the pool that is theirs by name
    (the same character always gets the same voice, and two characters usually differ)."""
    if voice.get("engine", "edge") == "edge" and not voice.get("name"):
        idx = int(hashlib.md5(cid.encode()).hexdigest()[:8], 16) % len(VOICE_POOL)
        return {**voice, "engine": "edge", "name": VOICE_POOL[idx]}
    return voice


def resolve_character(ep, cfg):
    """
    Episode "character" can be an id ("puppygirl"), a dict of overrides ({"tail": true}), a dict with an
    "id", or missing (= the active character from settings). Returns the full profile; "model" becomes
    an absolute path, or "placeholder".
    """
    ch = ep.get("character")
    over = {}
    if isinstance(ch, str):
        cid = ch
    elif isinstance(ch, dict):
        over = dict(ch)
        cid = over.pop("id", None) or cfg["active_character"]
    else:
        cid = cfg["active_character"]
    prof = S.deep_merge(S.load_character(cid), over)
    prof["id"] = cid
    prof["voice"] = unique_voice(cid, prof.get("voice") or {})
    model = prof.get("model") or ""
    if model and model != "placeholder" and (ROOT / model).exists():
        prof["model"] = str((ROOT / model).resolve())
    else:
        if model and model != "placeholder":
            print(f"  (model {model} not found - using the placeholder character)")
        prof["model"] = "placeholder"
    return prof


def resolve_co_stars(ep, cfg, log=print):
    """Other main characters in this video: ep "co_stars" = ids, or {"id", "start": mark}. Each gets a full
    profile (model, voice...). Shots name their speaker with "speaker" (a character id); no speaker = the
    episode's character. A speaker nobody is listed for falls back to the episode's character."""
    prim = ep["character"]["id"]
    out, seen = [], {prim}
    for item in ep.get("co_stars") or []:
        over = {"id": item} if isinstance(item, str) else dict(item)
        cid = str(over.get("id") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        prof = resolve_character({"character": over}, cfg)
        prof["start"] = over.get("start")
        out.append(prof)
        log(f"  main character: {prof['name']} ({'placeholder' if prof['model'] == 'placeholder' else Path(prof['model']).name})")
    ep["co_stars"] = out
    ids = {c["id"] for c in out}
    cast = ep.get("cast") or {}
    for shot in ep["shots"]:
        sp = shot.get("speaker")
        if not sp or sp == prim or sp == "main":
            shot.pop("speaker", None)
        elif sp not in ids and not (sp in cast and (cast[sp] or {}).get("type") != "thing"):
            log(f"  (a line is spoken by '{sp}', who isn't in this video - {prim} says it)")
            shot.pop("speaker", None)


def speaker_voice(ep, cfg, shot):
    """The voice for a shot's line: global < its speaker's character voice < episode voice (shot voice on top).
    The episode's own "voice" is the main character's: cast people and co-stars keep theirs."""
    sp = shot.get("speaker")
    if sp and sp not in {c["id"] for c in ep.get("co_stars") or []} and sp in (ep.get("cast") or {}):
        import actors as AC                       # a cast person speaks with their actor's voice
        info = ep["cast"][sp] or {}
        act = AC.get(info.get("actor") or AC.GENERIC_ID) or AC.get(AC.GENERIC_ID)
        own = AC.role_voice(sp, info.get("looks", ""), act.get("voice"))     # "mom" gets a woman's voice
        return S.layered_voice(cfg["voice"], own)
    prof = next((c for c in ep.get("co_stars") or [] if c["id"] == sp), None) if sp else None
    if prof:
        return S.layered_voice(cfg["voice"], prof.get("voice"))
    return S.layered_voice(cfg["voice"], ep["character"].get("voice"), ep.get("voice"))


def ass_time(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def ass_text(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def ass_color(hexs, default="#ffffff"):
    """'#rrggbb' -> ASS '&H00BBGGRR'."""
    h = (hexs or default).lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = default.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


EFFECTS = {   # ASS override tags applied to each caption event (times in ms)
    "none": "",
    "pop": "{\\fscx60\\fscy60\\t(0,90,\\fscx112\\fscy112)\\t(90,160,\\fscx100\\fscy100)}",
    "bounce": "{\\fscy130\\fscx85\\t(0,120,\\fscy100\\fscx100)}",
    "fade": "{\\fad(90,60)}",
}


def write_captions(path, ep, shots, timing, res, cap, brand):
    fps = timing["fps"]
    font = cap["font"].replace(",", " ")
    up = (lambda s: s.upper()) if cap.get("uppercase", True) else (lambda s: s)
    outline = max(0, int(cap.get("outline", 0)))
    border = f"{outline},{0 if outline else 1}"              # Outline, Shadow
    # the title sits over the sky/back wall, often pale: it always gets a thin dark outline (a shadow alone vanished)
    tborder = f"{max(outline, int(cap.get('title_outline', 1)))},1"
    fx = EFFECTS.get(cap.get("effect", "pop"), "")
    col, shadow = ass_color(cap.get("color"), "#dcf5fa"), ass_color(cap.get("shadow_color"), "#302040")
    tcol, tcol2 = ass_color(cap.get("title_color"), "#f0f0f0"), ass_color(cap.get("title_color2"), "#f0e060")
    small = max(4, round(res[1] * 0.028))
    lines = [
        # Captions are drawn at the LOW render resolution, before the upscale, so the text gets the same
        # chunky pixels, blur and colour fringing as the picture (like a game's on-screen text).
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {res[0]}", f"PlayResY: {res[1]}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font},{max(4, round(res[1] * cap['size']))},{col},{col},{shadow},{shadow},"
        f"-1,0,0,0,100,100,1,0,1,{border},2,6,6,{round(res[1] * cap['position'])},1",
        f"Style: Title,{font},{max(4, round(res[1] * cap['title_size']))},{tcol},{tcol},{shadow},{shadow},"
        f"-1,0,0,0,100,100,1,0,1,{tborder},8,8,8,{round(res[1] * 0.06)},1",
        f"Style: Mark,{font},{small},&H40FFFFFF,&H40FFFFFF,&H80000000,&H80000000,-1,0,0,0,100,100,0,0,1,0,1,"
        f"{3 if brand.get('watermark_corner', 'bottom-right').endswith('right') else 1},5,5,{round(res[1] * 0.03)},1",
        f"Style: End,{font},{max(4, round(res[1] * cap['size']))},{tcol2},{tcol2},{shadow},{shadow},"
        f"-1,0,0,0,100,100,1,0,1,{border},5,8,8,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    total = timing["total_frames"] / fps
    if ep.get("title"):
        first = timing["shots"][0]
        end = max(float(cap.get("title_seconds", 3.0)), 1.0) if cap.get("title_seconds") else max(3.0, first["n"] / fps)
        words = ass_text(up(ep["title"])).split()
        half = (len(words) + 1) // 2           # second half of the title in the second colour
        text = " ".join(words[:half]) + f"\\N{{\\c{tcol2}&}}" + " ".join(words[half:])
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(min(end, total))},Title,,0,0,0,,{fx}{text}")
    cyc = [ass_color(c) for c in (cap.get("cycle") or []) if c]   # word colours, in order through the video
    color_i = 0
    for shot, tm in zip(shots, timing["shots"]):
        if not shot.get("line") or cap["mode"] == "off":
            continue
        start = (tm["f0"] - 1) / fps + float(shot.get("lead", AUDIO_LEAD))
        shot_end = (tm["f0"] - 1 + tm["n"]) / fps
        # close shots: her face fills the middle of the frame, so the words sit lower, over her shoulders
        low = round(res[1] * 0.15) if shot.get("camera") in ("closeup", "dramatic", "macro") else 0
        if cap["mode"] == "line":
            end = min(shot_end, start + shot["talk"] + 0.4)
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,{low},,"
                         f"{fx}{ass_text(up(shot['line']))}")
            continue
        # a few words at a time (cap "group"), each word in the next colour of cap "cycle", timed by word length
        words = [w for w in ass_text(up(shot["line"])).split() if w]
        grp = max(1, int(cap.get("group", 1) or 1))
        weights = [len(w) + 2 for w in words]
        total_w = sum(weights) or 1
        wt = shot.get("word_t")
        if not isinstance(wt, list) or len(wt) != len(words):
            wt = None                  # no word times from the voice: spread the words by length
        t = start
        for g0 in range(0, len(words), grp):
            chunk = range(g0, min(len(words), g0 + grp))
            dur = shot["talk"] * sum(weights[k] for k in chunk) / total_w
            last = chunk[-1] == len(words) - 1
            if wt:                     # shown as the first word is said, until the next group's first word
                t = start + wt[g0]
                dur = (wt[chunk[-1] + 1] if not last else shot["talk"]) - wt[g0]
                dur = max(0.12, dur)
            end = min(shot_end, t + dur + (0.35 if last else 0))
            parts = []
            for k in chunk:
                col = cyc[color_i % len(cyc)] if cyc else None
                color_i += 1
                tag = "{\\c" + col + "&}" if col else ""
                parts.append(f"{tag}{words[k]}")
            lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(end)},Caption,,0,0,{low},,{fx}{' '.join(parts)}")
            t += dur
    if brand.get("watermark"):
        top = brand.get("watermark_corner", "bottom-right").startswith("top")
        tag = "{\\an9}" if top and brand["watermark_corner"].endswith("right") else "{\\an7}" if top else ""
        lines.append(f"Dialogue: 2,{ass_time(0)},{ass_time(total)},Mark,,0,0,0,,{tag}{ass_text(brand['watermark'])}")
    if brand.get("end_text"):
        s = max(0.0, total - float(brand.get("end_seconds", 2.0)))
        lines.append(f"Dialogue: 3,{ass_time(s)},{ass_time(total)},End,,0,0,0,,{fx}{ass_text(up(brand['end_text']))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


TINT_FILTERS = {
    "none": "",
    "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.05:bm=-0.05",
    "cool": "colorbalance=rs=-0.06:bs=0.1:rm=-0.04:bm=0.06",
    "purple": "colorbalance=rs=0.05:gs=-0.06:bs=0.1:rm=0.04:gm=-0.04:bm=0.06",
    "sunset": "colorbalance=rs=0.12:gs=-0.02:bs=0.06:rh=0.08:bh=-0.08",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "noir": "hue=s=0,eq=contrast=1.2",
    # 4-shade green palette: grey -> 4 levels -> classic handheld greens
    "gameboy": "hue=s=0,lutrgb=r='if(lt(val,64),15,if(lt(val,128),48,if(lt(val,192),139,155)))'"
               ":g='if(lt(val,64),56,if(lt(val,128),98,if(lt(val,192),172,188)))'"
               ":b='if(lt(val,64),15,if(lt(val,128),48,if(lt(val,192),15,15)))'",
}


def low_res_chain(look):
    """Filters applied at the low render resolution, before captions and the pixel upscale."""
    bits = max(1, min(8, int(look.get("color_bits", 5))))
    mask = 256 - 2 ** (8 - bits)
    step = 2 ** (8 - bits)
    chain = []
    tint = TINT_FILTERS.get(look.get("tint", "none"), "")
    if tint:
        chain.append(tint)
    if look.get("dither") and bits < 8:
        # 2x2 ordered dither: nudge each pixel by a pattern before rounding the colour down
        m = "(2*mod(X,2)*(1-mod(Y,2))+3*mod(Y,2)*(1-mod(X,2))+mod(X,2)*mod(Y,2))"
        off = f"({m}/4-0.375)*{step}"
        chain.append("format=rgb24,geq="
                     f"r='bitand(clip(r(X,Y)+{off},0,255),{mask})':"
                     f"g='bitand(clip(g(X,Y)+{off},0,255),{mask})':"
                     f"b='bitand(clip(b(X,Y)+{off},0,255),{mask})'")
    elif bits < 8:
        chain.append(f"lutrgb=r='bitand(val,{mask})':g='bitand(val,{mask})':b='bitand(val,{mask})'")
    return ",".join(chain)


def scanline_png(path, ffmpeg):
    """Multiply mask: every 4th output row ~13% darker (faint CRT/VHS lines)."""
    if not path.exists():
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"color=c=white:s={OUT_W}x{OUT_H}", "-vf",
                        "format=gray,geq=lum='if(lt(mod(Y\\,4)\\,3)\\,255\\,222)',format=rgb24",
                        "-frames:v", "1", str(path)], check=True)
    return path


def sfx_events(ep, timing, sx):
    """[(slot, seconds, volume)] for the episode. A shot's "sfx" (name or list) wins; "" means none;
    otherwise (if auto) trigger words in the line or the action pick one. Effects triggered by a word
    land roughly when that word is spoken."""
    fps = timing["fps"]
    out = []
    for shot, tm in zip(ep["shots"], timing["shots"]):
        t0 = (tm["f0"] - 1) / fps
        lead = float(shot.get("lead", AUDIO_LEAD))
        if "sfx" in shot:
            names = shot["sfx"] if isinstance(shot["sfx"], list) else ([shot["sfx"]] if shot["sfx"] else [])
        elif sx.get("auto", True):
            s = sfxlib.suggest(shot.get("line"), shot.get("action"))
            names = [s] if s else []
        else:
            names = []
        for name in names:
            if not sfxlib.path_for(name):
                print(f"  (sound effect '{name}' has no file - skipped)")
                continue
            if "sfx_at" in shot:
                at = t0 + float(shot["sfx_at"])
            else:
                at = t0 + 0.05
                words = (shot.get("line_src") or shot.get("line") or "").lower().split()
                trig = sfxlib.all_slots().get(name, {}).get("words", "").split()
                hit = next((k for k, w in enumerate(words)
                            if any(sfxlib.word_rx(t).fullmatch(re.sub(r"[^\w-]", "", w)) for t in trig)), None)
                if hit is not None and shot.get("talk"):
                    weights = [len(w) + 2 for w in words]
                    at = t0 + lead + shot["talk"] * sum(weights[:hit]) / sum(weights)
            out.append((name, at, float(shot.get("sfx_volume", sx.get("volume", 0.55)))))
        for e in shot.get("events", []) or []:      # the rest of the cast makes noise too
            import catalog
            verb = e.get("do", "enter")
            spec = catalog.CAST_VERBS.get(verb)
            snd = e.get("sfx", spec[4] if spec else None)
            if not snd or snd in names or not sfxlib.path_for(snd):      # none, or the line already plays it
                continue
            hit = spec[3] if spec and spec[3] is not None else 0.0
            default_at = 0.1 if verb in ("crash_in", "fall", "fly_by") else 0.0
            out.append((snd, t0 + float(e.get("at", default_at)) + hit, float(sx.get("volume", 0.55)) * 1.2))
    return out


def ambience_slot(ep, sx):
    amb = ep.get("ambience", sx.get("ambience", "auto"))
    if amb == "auto":
        rec = ep.get("set_recipe") or {}
        amb = rec.get("ambience") or sfxlib.ambience_for(rec.get("theme") or ep.get("set", ""))
    if amb and not sfxlib.path_for(amb):
        print(f"  (ambience '{amb}' has no file - skipped)")
        return None
    return amb or None


HAIR = ["#3a2a22", "#7a4a2a", "#26232a", "#f2d89a", "#d0602a", "#8a8f99", "#5a3a6a", "#c96a3c"]
SKIN = ["#ffdcc6", "#f2c4a0", "#d9a27a", "#a8704a", "#7a4a2f"]
CLOTHES = ["#4a7fd9", "#d94a4a", "#4caf50", "#f2d14e", "#8a5ad9", "#2fb3a3", "#f0903a", "#26232a", "#e8e4da"]
PANTS_WORDS = ("man", "boy", "dad", "father", "guy", "brother", "grandpa", "suit", "pants", "jeans", "trousers",
               "police", "cop", "officer", "robot", "knight", "pirate", "ninja", "chef", "boss", "king", "prince",
               "driver", "mailman", "postman", "alien", "zombie", "uncle")
DRESS_WORDS = ("woman", "girl", "mom", "mum", "mother", "grandma", "granny", "dress", "skirt", "lady", "queen",
               "princess", "witch", "sister", "aunt", "waitress", "nurse")


def person_look(who, info):
    """A simple outfit for a cast member, from their description ("tall man, red jacket, grey hair")."""
    import catalog
    rng = random.Random(int(hashlib.md5(who.encode()).hexdigest()[:8], 16))
    words = f"{who} {info.get('looks', '')}".lower().replace("_", " ")
    look = {"hair": rng.choice(HAIR), "skin": rng.choice(SKIN), "dress": rng.choice(CLOTHES),
            "shoes": "#2a2226", "eyes": "#2a2a40", "mouth": "#7a2a3a"}
    if any(re.search(rf"\b{w}\b", words) for w in PANTS_WORDS) and not any(re.search(rf"\b{w}\b", words) for w in DRESS_WORDS):
        look["pants"] = rng.choice(["#2b3a73", "#3a3a40", "#5a4a3a", "#26232a"])
    for col, part in re.findall(r"\b(" + "|".join(catalog.CAST_COLORS) + r")[\s-]+(\w+)", words):
        hexc = catalog.CAST_COLORS[col]
        if part in ("hair", "haired", "beard"):
            look["hair"] = hexc
        elif part in ("pants", "jeans", "trousers", "shorts"):
            look["pants"] = hexc
        elif part in ("skin", "skinned"):
            look["skin"] = hexc
        elif part in ("shoes", "boots"):
            look["shoes"] = hexc
        else:                              # dress, shirt, suit, jacket, uniform, hoodie...
            look["dress"] = hexc
    special = {"robot": {"skin": "#c0c4cc", "hair": "#8a8f99", "dress": "#7a8aa0", "pants": "#5a6070", "eyes": "#3ff0ff"},
               "ghost": {"skin": "#f4f4ff", "hair": "#f4f4ff", "dress": "#e8ecff", "eyes": "#26232a"},
               "alien": {"skin": "#7fd17f", "eyes": "#111111"}, "zombie": {"skin": "#8aa07a", "dress": "#5a5a4a"},
               "police": {"dress": "#2b3a73", "pants": "#2b3a73"}, "chef": {"dress": "#f4f2ee", "pants": "#3a3a40"},
               "doctor": {"dress": "#f4f2ee"}, "nurse": {"dress": "#f4f2ee"}, "grandma": {"hair": "#d8d8de"},
               "grandpa": {"hair": "#d8d8de"}, "granny": {"hair": "#d8d8de"}}
    for k, v in special.items():
        if re.search(rf"\b{k}\b", words):
            look.update(v)
    look.update(info.get("look") or {})        # anything set by hand wins
    height = 1.0
    for ws, hh in ((("baby", "toddler"), 0.55), (("kid", "child", "boy", "girl", "little", "tiny", "small"), 0.75),
                   (("grandma", "granny", "grandpa"), 0.92), (("dad", "father", "man", "boss", "police", "tall"), 1.15),
                   (("giant", "huge", "massive"), 1.5)):
        if any(re.search(rf"\b{w}\b", words) for w in ws):
            height = hh
            break
    return look, float(info.get("height") or height)


CUT_VERBS = [   # words in a cutaway description -> how the subject moves
    (("flying", "flies", "fly", "soaring", "zooming", "passing", "past"), "fly_by"),
    (("falling", "falls", "dropping", "drops", "raining down", "landing", "lands"), "fall"),
    (("crashing", "crashes", "smashing", "slamming"), "crash_in"),
    (("marching", "walking", "running", "crawling", "rolling", "driving", "coming", "arriving"), "enter"),
    (("spinning", "rotating", "turning"), "spin"), (("bouncing", "jumping", "hopping"), "bounce"),
    (("shaking", "trembling", "wobbling", "vibrating"), "shake"),
]
CUT_SKIP = set("a an the of in on at to into with and its their his her some lots many tiny small big giant huge "
               "little very slowly quickly just".split())


def resolve_animations(ep, log=print):
    """Shots whose script asked for an action she can't do yet ("want": "salute") get it made now (animgen: Ollama
    writes it from checked poses, a quick render is checked by the vision model) - or reuse it when it exists. A
    word that isn't a body action ("messy") keeps the shot's own action. Arms-out animations don't stay in close
    shots (they'd be cropped)."""
    wants = {s["want"] for s in ep["shots"] if s.get("want")}
    if not wants:
        return
    import animgen
    import animlib
    made = {}
    for w in sorted(wants):
        report(0.03, f"Making the animation '{w}'")
        line = next((s.get("line", "") for s in ep["shots"] if s.get("want") == w), "")
        made[w] = animgen.ensure(w, line, log=lambda m: log("  " + m))
    lib = animlib.library()
    for s in ep["shots"]:
        name = made.get(s.get("want"))
        if not name:
            continue
        s["action"] = name
        if (lib.get(name) or {}).get("needs_room") and s.get("camera") in ("closeup", "macro", "dramatic"):
            s["camera"] = "medium"
        log(f"  shot '{s.get('line', '')[:30]}': {name}")


def drop_weak_cutaways(ep, log=print):
    """A cutaway only shows something you can recognise: an imported model, a built-in prop, a drawn picture, a person,
    or a made prop that passed the look check (propgen.look_checked). A blocky shape that failed it (and got no
    picture) would fill the screen with boxes - "a feline army marching" - so she stays on screen instead."""
    cast = ep.get("cast") or {}
    for s in ep["shots"]:
        for e in [e for e in s.get("events") or [] if e.get("cutaway")]:
            info = cast.get(e.get("who")) or {}
            d = info.get("def") or {}
            if info.get("type") == "person" or info.get("prop") or d.get("model") or d.get("crowd") or d.get("sprite")                     or d.get("checked") is not False:
                continue
            s["events"].remove(e)
            s.pop("cutaway", None)
            log(f"  cutaway '{e['who']}' skipped - its shape doesn't look like it (and it has no picture)")
    used = {e["who"] for s in ep["shots"] for e in s.get("events") or []}
    for who in [w for w in cast if w not in used]:
        cast.pop(who)


def resolve_cutaways(ep, log=print):
    """Shots with "cutaway": "<what to show>" show that instead of her (her line plays as a voice-over). The
    subject becomes a cast member (reused if the script already has it) with a matching move, flagged so Blender
    frames it with its own camera and hides her."""
    import autodirect
    import catalog
    cast = ep.setdefault("cast", {})
    for i, shot in enumerate(ep["shots"]):
        text = str(shot.get("cutaway") or "").strip()
        if not text:
            continue
        low = text.lower()
        words = [w for w in re.findall(r"[a-z]+", low)]
        who = next((w for w in words if w in cast), None)
        if not who:
            verbs = {w for ws, _ in CUT_VERBS for w in ws}
            nouns = [w for w in words if w not in CUT_SKIP and w not in verbs and not w.endswith("ing")]
            who = re.sub(r"[^a-z0-9_]+", "", "_".join(nouns[:2]) or "thing")[:24] or "thing"
            n = 2
            base = who
            while who in cast and cast[who].get("looks") != text:
                who, n = f"{base}{n}", n + 1
            cast[who] = {"type": autodirect.cast_kind(who), "looks": text}
        verb = next((v for ws, v in CUT_VERBS if any(re.search(rf"\b{w}\b", low) for w in ws)), "appear")
        evs = [e for e in shot.get("events", []) or [] if e.get("who") != who]
        ev = {"who": who, "do": verb if cast[who].get("type") != "person" or verb in ("enter",) else "appear",
              "cutaway": True}
        if cast[who].get("type") == "person":
            act = next((a for a in catalog.ANIMS if a in low), None)
            ev["do"] = act or "appear"
        shot["events"] = evs + [ev]
        log(f"  cutaway (shot {i + 1}): {text} -> {who} ({ev['do']})")


def resolve_cast(ep, cfg, log=print):
    """Fill in what Blender needs for the rest of the cast: a look for people, a 3D prop for things
    (from the prop library, a built-in prop, or designed now by Ollama - a simple stand-in when it's offline)."""
    cast = ep.get("cast") or {}
    if not cast:
        return
    import autodirect
    import propgen
    import setgen
    setting = (ep.get("set_recipe") or {}).get("description", "") or ep.get("set", "")
    comfy_cfg = cfg["comfy"] if cfg["comfy"].get("mode", "auto") != "off" else None
    import actors as AC
    # the main characters are never cast members (the AI cast step once cast "catgirl": a blocky double of her)
    flat = lambda s: re.sub(r"[^a-z0-9]+", "", str(s).lower())    # noqa: E731
    mains = set()
    for prof in [ep.get("character") or {}] + list(ep.get("co_stars") or []):
        if isinstance(prof, dict):
            mains |= {flat(n) for n in [prof.get("id"), prof.get("name"), *S.speaker_names(prof)] if n}
    for who in [w for w in cast if flat(w) in mains]:
        log(f"  cast: dropped '{who}' - that's a main character, not an extra")
        cast.pop(who)
        for s in ep["shots"]:
            if s.get("events"):
                s["events"] = [e for e in s["events"] if e.get("who") != who]
    for who, info in list(cast.items()):
        info = dict(info) if isinstance(info, dict) else {}
        if info.get("explainer") and not (info.get("def") or {}).get("explainer"):
            # "[show: toilet]": a model with moving parts, designed for what the narration says about it
            first = next((i for i, s in enumerate(ep["shots"]) if (s.get("show") or {}).get("who") == who), 0)
            lines = [s.get("line_src") or s.get("line") or "" for s in ep["shots"][first:first + 14]]
            info["type"] = "thing"
            info["def"] = propgen.design_explainer(who, info.get("looks") or "", lines, cfg.get("ollama"),
                                                   log=lambda m: log("  " + m), comfy_cfg=comfy_cfg)
            cast[who] = info
            continue
        if not info.get("def") and not info.get("actor") and not info.get("generated"):
            try:                                     # "crowd", "audience", "herd of cows": imported models in a group
                import imported
                crowd = imported.crowd_def(who, info.get("looks") or "", setting) if imported.is_group(who) else None
            except Exception as exc:
                crowd = None
                log(f"  cast: no crowd for {who} ({exc.__class__.__name__})")
            if crowd:
                info["type"], info["def"] = "thing", crowd
                log(f"  cast: {who} (a crowd of {len(crowd['crowd'])}: {', '.join(sorted({m['name'] for m in crowd['crowd']}))})")
                cast[who] = info
                continue
        explicit = "type" in info                    # the video editor / script can force person or thing
        info.setdefault("type", autodirect.cast_kind(who))
        if info["type"] == "thing" and re.search(r"\bhumans?\b", str(info.get("looks") or ""), re.I):
            info["type"] = "person"                  # "human" is a person: a thing has no mouth, so it can't talk
            explicit = False
            log(f"  cast: {who} is a human, so it's a person (things can't talk)")
        act = AC.pick(who, info.get("actor"), person=info["type"] == "person")   # the actor who plays them
        if act and act["kind"] == "imported":        # a real model: it moves as a whole, like a thing
            info["type"] = "thing"
            info["def"] = AC.imported_def(act) or info.get("def")
            info["actor"] = act["id"]
            log(f"  cast: {who} (actor '{act['name']}', imported model)")
        elif act and not explicit:
            info["type"] = "person"                  # an actor for this name is a person
        if info["type"] == "person":
            act = act if act and act["kind"] != "imported" else AC.get(AC.GENERIC_ID)
            info["actor"] = act["id"]
            had_height = "height" in info             # an explicit height wins over the actor's build
            looks = " ".join(filter(None, [info.get("looks"), act.get("role")]))
            info["look"], info["height"] = person_look(who, {**info, "looks": looks, "look": act.get("look") or {}})
            if not had_height:
                info["height"] = info["height"] * float(act.get("height") or 1.0)
            if act["kind"] == "rigged":                # its own rigged .blend: animated like a character
                info["actor_model"] = str((AC.ROOT / act["model"]).resolve())
            log(f"  cast: {who} (person, actor '{act['name']}' [{act['kind']}], height {info['height']:.2f})")
        elif not info.get("def"):
            kind = propgen.slug(info.get("prop") or who)
            wants_generated = bool(info.get("generated"))     # the video editor's "generate its own"
            real = None if wants_generated else propgen.imported_def(kind, info.get("looks") or "", setting,
                                                                     log=lambda m: log("  " + m))
            if real:                                  # a real imported model beats both built-in and generated
                info["def"] = real
                log(f"  cast: {who} (imported model '{real['name']}')")
            elif kind in setgen.PROPS and kind not in ("hill", "water", "fence", "rug") and not wants_generated:
                info["prop"] = kind
                log(f"  cast: {who} (built-in prop '{kind}')")
            else:
                info["def"] = propgen.design(kind, info.get("looks") or who.replace("_", " "), setting,
                                             cfg.get("ollama"), log=lambda m: log("  " + m), comfy_cfg=comfy_cfg,
                                             use_imported=not wants_generated)
        elif comfy_cfg and not info["def"].get("sprite") and info["def"].get("source") != "imported":
            info["def"] = propgen.add_sprite(dict(info["def"]), comfy_cfg, log=lambda m: log("  " + m))
        cast[who] = info
    ep["cast"] = cast
    # people don't "crash in", "fall" or "fly by" (things' verbs the AI sometimes gives them): they run in - a
    # crashing-in mailman stood at the frame's edge
    for s in ep["shots"]:
        for e in s.get("events") or []:
            if (cast.get(e.get("who")) or {}).get("type") == "person" and e.get("do") in ("crash_in", "fall", "fly_by"):
                e["do"], e["run"] = "enter", True


def encode_with_progress(cmd, cwd, seconds, lo, hi):
    """Run the final ffmpeg pass, turning its -progress output into the job's progress bar."""
    cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats"] + cmd[-1:]
    # ffmpeg's own messages go to a log file (the progress numbers go to stdout), so a failure is readable
    log = Path(cwd) / "encode.log"
    with log.open("w", encoding="utf-8", errors="replace") as errfh:
        errfh.write("COMMAND:\n" + " ".join(f'"{c}"' if " " in c else c for c in cmd) + "\n\nFFMPEG:\n")
        errfh.flush()
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=errfh, text=True,
                                encoding="utf-8", errors="replace")
        last = 0.0
        for line in proc.stdout:
            if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                try:
                    t = int(line.split("=", 1)[1]) / 1e6
                except ValueError:
                    continue
                frac = min(1.0, t / max(0.1, seconds))
                if frac - last >= 0.02:
                    last = frac
                    report(lo + (hi - lo) * frac, f"Encoding the video ({int(frac * 100)}%)")
        rc = proc.wait()
    if rc != 0:
        tail = log.read_text(encoding="utf-8", errors="replace")[-3000:]
        print(f"ffmpeg failed (exit {rc}). Full log: {log}\n{tail}")
        raise subprocess.CalledProcessError(rc, cmd[:3])


def set_exists(sid):
    import catalog
    return sid in catalog.SETS or (ROOT / "sets" / f"{sid}.json").exists()


def resolve_scenes(ep, ep_path=None, log=print):
    """Shots can move to another set ("set" on the shot). "new:<idea>" (or an id that doesn't exist yet) makes
    that set now - once per idea - and the chosen ids are written back into the episode file, so the next
    render reuses them instead of generating again."""
    if ep.get("set") == "auto" or (str(ep.get("set", "")).startswith("new:")) or \
            (ep.get("set") and not set_exists(str(ep["set"]))):        # the video's own set
        import autodirect
        import make_set
        if ep.get("set") == "auto":
            sid, place = autodirect.auto_set(ep.get("title"), "reuse", log=log)
            log(f"  set from the title: {place} -> {sid}")
        else:
            sid = str(ep["set"])
        if not set_exists(sid):
            idea = sid[4:] if sid.startswith("new:") else sid.replace("_", " ")
            log(f"  making the video's set: {idea}")
            report(0.02, f"Making the set: {idea[:40]}")
            quiet(True)
            try:
                sid = make_set.create_set(idea, log=lambda m: log("    " + m))["id"]
            finally:
                quiet(False)
        ep["set"] = sid
        if ep_path and Path(ep_path).exists():
            try:
                disk = json.loads(Path(ep_path).read_text(encoding="utf-8-sig"))
                disk["set"] = sid
                Path(ep_path).write_text(json.dumps(disk, indent=2), encoding="utf-8")
            except Exception as exc:
                log(f"  (couldn't save the set id into the episode: {exc})")
    want = {}
    for i, shot in enumerate(ep["shots"]):
        sid = shot.get("set")
        if not sid or set_exists(str(sid)):
            continue
        idea = str(sid)[4:] if str(sid).startswith("new:") else str(sid).replace("_", " ")
        want.setdefault(idea.strip(), []).append(i)
    if not want:
        return
    import make_set
    made = {}
    for idea, idxs in want.items():
        log(f"  scene change: making a new set for '{idea}' (shots {', '.join(str(i + 1) for i in idxs)})")
        report(0.03, f"Making a set: {idea[:40]}")
        quiet(True)
        try:
            rec = make_set.create_set(idea, log=lambda m: log("    " + m))
        finally:
            quiet(False)
        made[idea] = rec["id"]
        for i in idxs:
            ep["shots"][i]["set"] = rec["id"]
        log(f"  -> new set '{rec['name']}' ({rec['id']}) - it's in your Sets now")
    if ep_path and Path(ep_path).exists():          # remember the choice
        try:
            disk = json.loads(Path(ep_path).read_text(encoding="utf-8-sig"))
            for i, shot in enumerate(disk.get("shots", [])):
                if i < len(ep["shots"]) and shot.get("set") != ep["shots"][i].get("set") and ep["shots"][i].get("set"):
                    shot["set"] = ep["shots"][i]["set"]
            Path(ep_path).write_text(json.dumps(disk, indent=2), encoding="utf-8")
        except Exception as exc:
            log(f"  (couldn't save the new set ids into the episode: {exc})")


def segments(ep):
    """Consecutive shots that share a set -> one Blender pass each: [(set_id, [shot indexes])]."""
    out = []
    for i, shot in enumerate(ep["shots"]):
        sid = shot.get("set") or ep.get("set", "cafe")
        if out and out[-1][0] == sid:
            out[-1][1].append(i)
        else:
            out.append((sid, [i]))
    return out


def segment_episode(ep, sid, idxs, first):
    """A sub-episode for one set: its own set, start mark, and the shots that happen there."""
    import catalog
    sub = {k: v for k, v in ep.items() if k not in ("set_recipe", "shots")}
    sub["set"] = sid
    embed_set(sub)
    marks = list((sub.get("set_recipe") or {}).get("marks") or catalog.SETS.get(sid, {}).get("marks") or {"center": 0})
    start = ep["shots"][idxs[0]].get("start")
    if not start:
        start = ep.get("start") if first and sid == ep.get("set") else ("center" if "center" in marks else marks[0])
    sub["start"] = start if start in marks else ("center" if "center" in marks else marks[0])
    shots = []
    air = (sub.get("set_recipe") or {}).get("air")
    motion = (sub.get("set_recipe") or {}).get("motion", "float")
    for i in idxs:
        sh = dict(ep["shots"][i])
        if sh.get("to") and sh["to"] not in marks:
            sh.pop("to")
            if sh.get("action") in ("walk_to", "run_to", "sneak_to"):
                sh["action"] = "idle"
        falling = air and motion == "fall"            # skydiving: every shot is the falling pose
        if air and not sh.get("actions") and (falling or sh.get("action", "idle") in ("idle", "walk_to", "run_to", "sneak_to", "turn")):
            sh["action"] = "fall" if motion == "fall" else "float"      # no ground: fall or float instead
            sh.pop("to", None)
        shots.append(sh)
    sub["shots"] = shots
    return sub


def embed_set(ep):
    """Generated sets (sets/<id>.json) travel inside the resolved episode so Blender can build them."""
    import catalog
    sid = ep.get("set", "cafe")
    if sid in catalog.SETS:
        return
    path = ROOT / "sets" / f"{sid}.json"
    if not path.exists():
        sys.exit(f"Unknown set '{sid}' (no sets/{sid}.json)")
    recipe = json.loads(path.read_text(encoding="utf-8-sig"))
    recipe["textures"] = {k: str((ROOT / v).resolve()) for k, v in (recipe.get("textures") or {}).items()
                          if (ROOT / v).exists()}
    if recipe.get("custom_props"):            # AI props: use the library's drawn sprite when there is one
        import propgen
        lib = propgen.library()
        cfg = S.load_settings()
        comfy_cfg = cfg["comfy"] if cfg["comfy"].get("mode", "auto") != "off" else None
        for k, d in list(recipe["custom_props"].items()):
            if lib.get(k, {}).get("sprite"):          # edits made on the Assets page reach every set using it
                recipe["custom_props"][k] = {**d, **{f: lib[k][f] for f in ("sprite", "sprite_aspect", "height", "width",
                                                                            "on", "looks") if f in lib[k]}}
            elif comfy_cfg and not d.get("sprite") and d.get("source") != "imported" and propgen.needs_picture(d):
                nd = propgen.add_sprite(dict(lib.get(k) or d), comfy_cfg)
                if nd.get("sprite"):
                    propgen._save(nd)
                    recipe["custom_props"][k] = {**d, "sprite": nd["sprite"], "sprite_aspect": nd["sprite_aspect"]}
    ep["set_recipe"] = recipe


# --------------------------------------------------------------------------- output language
MALE_VOICE_WORDS = ("Guy", "Christopher", "Ryan", "Andrew", "William", "Eric", "Davis", "Tony", "Jason", "Brian",
                    "Roger", "Steffan", "Leonas", "Thomas", "Liam", "Connor", "Mitchell", "Prabhat")


def out_language(ep, cfg):
    import catalog
    lang = str(ep.get("language") or cfg.get("language") or "en")
    if lang not in catalog.LANGUAGES:
        print(f"  (unknown language '{lang}' - the video stays in English)")
        lang = "en"
    return lang


def language_voice(voice, lang, shot=None, ep=None):
    """The voice that speaks `lang`. English: unchanged. Others: an Edge voice of that language, female or male like
    the voice it replaces (the main character is female unless her profile says "gender": "male")."""
    import catalog
    if lang == "en":
        return voice
    L = catalog.LANGUAGES[lang]
    name = str(voice.get("name") or "")
    sp = (shot or {}).get("speaker")
    main = not sp
    prof = (ep or {}).get("character") if main else next((c for c in (ep or {}).get("co_stars") or [] if c["id"] == sp), None)
    gender = str((prof or {}).get("gender") or "").lower()
    if gender not in ("male", "female"):
        male = voice.get("engine") == "edge" and any(w in name for w in MALE_VOICE_WORDS)
        gender = "male" if male else "female"
    out = {"engine": "edge", "name": L[gender], "rate": "+8%" if gender == "female" else "+0%",
           "pitch": "+15Hz" if gender == "female" else "+0Hz"}
    if voice.get("engine") == "edge":
        out.update({k: voice[k] for k in ("rate", "pitch") if k in voice})
    if voice.get("shift"):
        out["shift"] = voice["shift"]
    return out


def voice_for(ep, cfg, shot):
    """Global < speaker's character < episode < shot voice, then switched to the video's language."""
    return language_voice(line_voice(speaker_voice(ep, cfg, shot), shot), ep.get("_language", "en"), shot, ep)


def translation_units(ep, cfg):
    """What gets translated: [(english text, [shot indexes])] for the spoken lines (a line split into beats is one
    unit), plus the title and the end card text (no shots)."""
    units, seen = [], set()
    for i, s in enumerate(ep["shots"]):
        if not s.get("line") or i in seen:
            continue
        g = s.get("beat_group")
        idx = [j for j, t in enumerate(ep["shots"]) if g is not None and t.get("beat_group") == g and t.get("line")] \
            if g is not None else [i]
        seen.update(idx)
        units.append((" ".join(ep["shots"][j]["line"] for j in idx), idx))
    branding = S.deep_merge(cfg["branding"], ep.get("branding", {}))
    units += [(t, []) for t in (ep.get("title"), branding.get("end_text")) if t]
    return units


def translations_for(ep, cfg, lang, texts, log=print):
    """{english: translated} for `texts`: the episode's own (checked by hand on the Create page) first, then the
    cache (build/translations.json), then Ollama for the rest (added to the cache)."""
    import catalog
    import llm
    cache_file = ROOT / "build" / "translations.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8-sig"))
    except Exception:
        cache = {}
    mine = ((ep.get("translations") or {}).get(lang) or {})
    mem = {**cache.get(lang, {}), **{k: v for k, v in mine.items() if isinstance(v, str) and v.strip()}}
    todo = list(dict.fromkeys(t for t in texts if t not in mem))
    if todo:
        o = cfg["ollama"]
        name = catalog.LANGUAGES[lang]["name"]
        log(f"  translating {len(todo)} line(s) into {name} with {o['model']}...")
        new = dict(zip(todo, llm.translate_lines(o["url"], o["model"], todo, name)))
        mem.update(new)
        cache.setdefault(lang, {}).update(new)
        S.write_json(cache_file, cache)
    return {t: mem[t] for t in texts}


def translate_episode(ep, cfg, lang, log=print):
    """Put the spoken lines, title and end card into `lang` (English stays in shot["line_src"] for sound-effect
    triggers). A line split into beats is translated as one sentence, then shared out over its beats. Translations
    are cached in build/translations.json, so a re-render says exactly the same words."""
    import catalog
    L = catalog.LANGUAGES[lang]
    all_units = translation_units(ep, cfg)
    try:
        mem = translations_for(ep, cfg, lang, [t for t, _ in all_units], log)
    except Exception as exc:
        sys.exit(f"Can't make the video in {L['name']}: translating needs Ollama ({exc.__class__.__name__}: "
                 f"{str(exc)[:160]}). Start Ollama, or set the language to English.")
    branding = S.deep_merge(cfg["branding"], ep.get("branding", {}))
    for text, idx in [u for u in all_units if u[1]]:
        words = mem[text].split()
        weights = [len(ep["shots"][j]["line"].split()) for j in idx]
        total, at = sum(weights) or 1, 0
        for k, j in enumerate(idx):               # beats get the translated words in proportion to the English ones
            n = len(words) - at if k == len(idx) - 1 else max(1, round(len(words) * weights[k] / total))
            n = min(n, len(words) - at - (len(idx) - 1 - k))       # leave at least a word for each later beat
            ep["shots"][j]["line_src"] = ep["shots"][j]["line"]
            ep["shots"][j]["line"] = " ".join(words[at:at + max(1, n)]) if at < len(words) else ""
            at += max(1, n)
    if ep.get("title"):
        ep["title"] = mem[ep["title"]]
    if branding.get("end_text"):
        ep["branding"] = {**(ep.get("branding") or {}), "end_text": mem[branding["end_text"]]}
    log(f"  language: {L['name']} - lines, title and end card translated")


def say(text, char_id, out, ffmpeg):
    """Voice test: speak one line in a character's voice -> out (wav)."""
    cfg = S.load_settings()
    prof = S.load_character(char_id or cfg["active_character"])
    voice = S.layered_voice(cfg["voice"], prof.get("voice"))
    out.parent.mkdir(parents=True, exist_ok=True)
    prefetch_local([(text, voice)], ROOT / "build" / "tts_cache")
    secs = tts(text, out, voice, ffmpeg, ROOT / "build" / "tts_cache")
    print(f"Done: {out} ({secs:.1f}s, {voice.get('engine')} voice)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", type=Path, nargs="?")
    ap.add_argument("--no-tts", action="store_true", help="skip voice; estimate line timing instead")
    ap.add_argument("--no-render", action="store_true", help="reuse frames from the last render")
    ap.add_argument("--fresh-voice", action="store_true", help="regenerate voice lines instead of using the cache")
    ap.add_argument("--say", metavar="TEXT", help="voice test: speak TEXT in a character's voice")
    ap.add_argument("--character", help="character id for --say (default: active character)")
    ap.add_argument("--out", type=Path, help="output file for --say")
    args = ap.parse_args()
    global FRESH, AUDIO_LEAD, TAIL_PAD
    FRESH = args.fresh_voice
    cfg = S.load_settings()
    AUDIO_LEAD, TAIL_PAD = float(cfg["audio"]["lead"]), float(cfg["audio"]["tail_pad"])

    ffmpeg = tool("ffmpeg", "FFMPEG")
    if not (sfxlib.BUILTIN / "boom.wav").exists():      # first run: synthesise the built-in effects
        sfxlib.generate_builtin(ffmpeg)
    if args.say:
        return say(args.say, args.character, args.out or ROOT / "output" / "voice_test.wav", ffmpeg)
    if not args.episode:
        ap.error("give an episode file (or --say TEXT)")
    blender = tool("blender", "BLENDER", BLENDER_DEFAULT)
    ep = json.loads(args.episode.read_text(encoding="utf-8-sig"))
    name = slug(args.episode.stem)
    build = ROOT / "build" / name
    audio_dir, frames_dir = build / "audio", build / "frames"
    audio_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report(0.01, "Getting ready")

    prof = resolve_character(ep, cfg)
    ep["character"] = prof
    resolve_co_stars(ep, cfg)
    ep.setdefault("render_res", [cfg["render"]["width"], cfg["render"]["height"]])
    ep.setdefault("fps", cfg["render"]["fps"])
    resolve_scenes(ep, args.episode)
    embed_set(ep)
    resolve_cutaways(ep)
    resolve_animations(ep)
    resolve_cast(ep, cfg)
    drop_weak_cutaways(ep)
    ep["_language"] = out_language(ep, cfg)
    if ep["_language"] != "en":
        report(0.05, "Translating")
        translate_episode(ep, cfg, ep["_language"])
    print(f"Character: {prof['name']}  ({'placeholder' if prof['model'] == 'placeholder' else Path(prof['model']).name})")

    # 1. voice + timing: global default < character voice < episode voice < shot voice
    wavs = []
    n_lines = sum(1 for s in ep["shots"] if s.get("line"))
    report(0.06, f"Recording the voice ({n_lines} lines)")
    # beats of one script line (shot "beat_group") are voiced ONCE, as one take; each beat then takes the share
    # of the recording its words take (by word length), so the picture cuts on the beats while the voice runs on
    groups = {}
    for i, s in enumerate(ep["shots"]):
        if s.get("beat_group") is not None:
            groups.setdefault(s["beat_group"], []).append(i)
    grouped = {j for idx in groups.values() for j in idx}
    def group_text(idx):
        return " ".join(ep["shots"][j]["line"] for j in idx if ep["shots"][j].get("line"))
    if not args.no_tts:
        items = [(group_text(idx), voice_for(ep, cfg, ep["shots"][idx[0]]))
                 for idx in groups.values()]
        items += [(s["line"], voice_for(ep, cfg, s)) for i, s in enumerate(ep["shots"])
                  if s.get("line") and i not in grouped]
        prefetch_local(items, ROOT / "build" / "tts_cache")
    shares, group_total = {}, {}
    for g, idx in groups.items():                       # one recording per line, cut into shares for its beats
        first = ep["shots"][idx[0]]
        text = group_text(idx)
        if args.no_tts:
            total = 0.33 * len(text.split()) + 0.3
        else:
            wav = audio_dir / f"line_{idx[0]:02d}.wav"
            total = tts(text, wav, voice_for(ep, cfg, first), ffmpeg,
                        ROOT / "build" / "tts_cache")
            wavs.append((idx[0], wav))
        weights = [sum(len(w) + 2 for w in ep["shots"][j].get("line", "").split()) or 1 for j in idx]
        marks = None if args.no_tts else word_starts(text, wav, total)
        if marks:
            # each beat starts when its first word is said, so the cut lands on the voice
            k, firsts = 0, []
            for j in idx:
                firsts.append(k)
                k += len(ep["shots"][j].get("line", "").split())
            b0 = [0.0] + [marks[min(k, len(marks) - 1)] - 0.05 for k in firsts[1:]]
            b1 = b0[1:] + [total]
            for n_, j in enumerate(idx):
                shares[j] = max(0.25, b1[n_] - b0[n_])
                nw = len(ep["shots"][j].get("line", "").split())
                ep["shots"][j]["word_t"] = [round(max(0.0, m - b0[n_]), 3) for m in marks[firsts[n_]:firsts[n_] + nw]]
            scale = total / sum(shares[j] for j in idx)    # the 0.25 s floor can't make the line longer
            for j in idx:
                shares[j] *= scale
        else:
            for j, wt in zip(idx, weights):
                shares[j] = total * wt / sum(weights)
                ep["shots"][j].pop("word_t", None)
        group_total[g] = total
        print(f"  beats {idx[0]}-{idx[-1]}: one line, {total:.1f}s in {len(idx)} beats")
    for i, shot in enumerate(ep["shots"]):
        # breathing room: a calm intro before the first line and a hold after the last one
        intro = float(cfg["audio"].get("intro", 0.7)) if i == 0 else 0.0
        outro = float(cfg["audio"].get("outro", 1.3)) if i == len(ep["shots"]) - 1 else 0.0
        if i in grouped:
            g = shot["beat_group"]
            idx = groups[g]
            talk = shares[i]
            first, last = i == idx[0], i == idx[-1]
            shot["talk"] = round(talk, 3)
            shot["lead"] = round(AUDIO_LEAD + intro, 3) if first else 0.0    # the line's voice starts once, here
            dur = talk + (AUDIO_LEAD + intro if first else 0.0) + (TAIL_PAD + outro if last else 0.0)
            shot["duration"] = round(dur, 3)
            if first:
                print(f"  shot {i}: beat line {group_total[g]:.1f}s")
            report(0.10 + 0.18 * (i + 1) / max(1, len(ep["shots"])), f"Voice line {i + 1}/{len(ep['shots'])}")
            continue
        talk = 0.0
        if shot.get("line"):
            if args.no_tts:
                talk = 0.33 * len(shot["line"].split()) + 0.3
            else:
                wav = audio_dir / f"line_{i:02d}.wav"
                talk = tts(shot["line"], wav, voice_for(ep, cfg, shot), ffmpeg,
                           ROOT / "build" / "tts_cache")
                wavs.append((i, wav))
                marks = word_starts(shot["line"], wav, talk)
                if marks:
                    shot["word_t"] = marks
                else:
                    shot.pop("word_t", None)
            print(f"  shot {i}: line {talk:.1f}s")
            report(0.10 + 0.18 * (i + 1) / max(1, len(ep["shots"])), f"Voice line {i + 1}/{len(ep['shots'])}")
        shot["talk"] = round(talk, 3)
        shot["lead"] = round(AUDIO_LEAD + intro, 3)
        shot["duration"] = max(float(shot.get("duration", 2.0)), AUDIO_LEAD + talk + TAIL_PAD) + intro + outro
    ep["audio_lead"] = AUDIO_LEAD
    resolved = build / "resolved.json"
    resolved.write_text(json.dumps(ep, indent=2), encoding="utf-8")

    # 2. Blender
    segs = segments(ep)
    expected = sum(round(float(s.get("duration", 2.0)) * int(ep.get("fps", 24))) for s in ep["shots"])
    if not args.no_render:
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        multi = len(segs) > 1 or segs[0][0] != ep.get("set", "cafe")
        print("Rendering in Blender..." + (f" ({len(segs)} scenes: {' -> '.join(s for s, _ in segs)})" if multi else ""))
        merged, offset = {"fps": None, "total_frames": 0, "shots": [None] * len(ep["shots"])}, 0
        for gi, (sid, idxs) in enumerate(segs):
            seg_dir = build / f"scene{gi}" if multi else build
            seg_dir.mkdir(parents=True, exist_ok=True)
            seg_json = seg_dir / "resolved.json"
            sub = segment_episode(ep, sid, idxs, gi == 0) if multi else ep
            seg_json.write_text(json.dumps(sub, indent=2), encoding="utf-8")
            seg_frames = seg_dir / "frames" if multi else frames_dir
            if multi and seg_frames.exists():
                shutil.rmtree(seg_frames)
            log = seg_dir / "blender.log"
            label = f"Rendering scene {gi + 1}/{len(segs)}" if multi else "Rendering frames"
            with log.open("w", encoding="utf-8", errors="replace") as fh, \
                    FrameWatcher([frames_dir, seg_frames], expected, 0.30, 0.88, label):
                res = subprocess.run([blender, "-b", "--factory-startup", "--python",
                                      str(ROOT / "pipeline" / "blender_build.py"), "--",
                                      str(seg_json), str(seg_frames), str(seg_dir / "scene.blend")],
                                     stdout=fh, stderr=subprocess.STDOUT)
            text = log.read_text(encoding="utf-8", errors="replace")
            check_only = bool(ep.get("_no_render"))      # a build check: scene + timing.json, no frames
            if res.returncode != 0 or "Traceback" in text or (not check_only and not any(seg_frames.glob("f_*.png"))):
                print(text[-4000:])
                sys.exit(f"Blender failed - full log: {log}")
            if not multi:
                break
            tm = json.loads((seg_dir / "timing.json").read_text(encoding="utf-8-sig"))
            frames_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(seg_frames.glob("f_*.png")):         # renumber into one continuous sequence
                n = int(f.stem[2:])
                f.replace(frames_dir / f"f_{offset + n:04d}.png")
            for k, i in enumerate(idxs):
                merged["shots"][i] = {"f0": tm["shots"][k]["f0"] + offset, "n": tm["shots"][k]["n"], "set": sid}
            merged["fps"] = tm["fps"]
            offset += tm["total_frames"]
            print(f"  scene {gi + 1}/{len(segs)}: {sid} ({tm['total_frames']} frames)")
        if multi:
            merged["total_frames"] = offset
            (build / "timing.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
        if ep.get("_no_render"):
            print(f"Build check done (_no_render: no frames, no video) - {build / 'timing.json'}")
            return
    if not (build / "timing.json").exists():
        sys.exit("No earlier render to reuse (build/<episode>/timing.json is missing) - render it in full first.")
    timing = json.loads((build / "timing.json").read_text(encoding="utf-8-sig"))
    if args.no_render and len(timing["shots"]) != len(ep["shots"]):
        sys.exit(f"The last render had {len(timing['shots'])} shots but the episode now has {len(ep['shots'])} - "
                 "the shots changed, so it needs a full render (re-applying the look only works on the same shots).")
    fps, total = timing["fps"], timing["total_frames"]

    # 3. captions + ffmpeg
    res = ep.get("render_res", [216, 384])
    write_captions(build / "captions.ass", ep, ep["shots"], timing, res,
                   S.deep_merge(cfg["captions"], ep.get("captions", {})),
                   S.deep_merge(cfg["branding"], ep.get("branding", {})))
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{name}.mp4"
    # look = global settings < episode preset < episode overrides
    look = S.deep_merge(cfg["look"], S.LOOK_PRESETS.get(ep.get("look_preset") or "", {}))
    look = S.deep_merge(look, ep.get("look", {}))
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", "frames/f_%04d.png"]
    n_in = 1
    pre = low_res_chain(look)
    v = ("[0:v]" + (pre + "," if pre else "")                                  # tint, dither, colour depth
         + "subtitles=captions.ass,"                                           # text at low res
         + f"scale={OUT_W}:{OUT_H}:flags=neighbor")                            # chunky pixels
    if look["blur"] and not look.get("sharp_pixels"):
        v += f",gblur=sigma={look['blur']}"
    if look["fringe"]:
        v += f",rgbashift=rh={-look['fringe']}:bh={look['fringe']}:edge=smear"
    b, w = look["black"], look["white"]
    v += (f",eq=saturation={look['saturation']}:contrast={look['contrast']},"
          f"colorlevels=romin={b[0]}:gomin={b[1]}:bomin={b[2]}:romax={w[0]}:gomax={w[1]}:bomax={w[2]},"
          "format=gbrp")
    bloom = float(look.get("bloom") or 0)
    if bloom > 0:   # glow: blurred copy of the bright parts, screened on top
        v += (f",split[base][glow];[glow]curves=all='0/0 0.6/0.1 1/1',gblur=sigma=28[glowb];"
              f"[base][glowb]blend=all_mode=screen:all_opacity={min(1.0, bloom):.2f},format=gbrp")
    v += "[graded]"
    fc = [v]
    last = "[graded]"
    if look["scanlines"]:
        cmd += ["-loop", "1", "-t", f"{total / fps + 0.5:.3f}", "-i", str(scanline_png(ROOT / "build" / "scanlines.png", ffmpeg))]
        # both inputs must be planar RGB, or multiply runs on YUV chroma and tints everything green
        fc.append(f"[{n_in}:v]format=gbrp[mask]")
        fc.append(f"{last}[mask]blend=all_mode=multiply:shortest=1[scan]")
        last, n_in = "[scan]", n_in + 1
    # blurred foreground wipes: a soft brown blob sweeps across the frame at each marked cut (no sound)
    wipes = [(tm["f0"] - 1) / fps for s, tm in zip(ep["shots"], timing["shots"]) if s.get("wipe") and tm]
    if wipes:
        blob = build / "wipe_blob.png"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=black:s=1080x1920,format=rgba,geq=r='107':g='74':b='51':"
                        "a='255*exp(-3*((X-540)*(X-540)/230400+(Y-960)*(Y-960)/490000))'",
                        "-frames:v", "1", str(blob)], check=True)
        cmd += ["-i", str(blob)]
        bi, n_in = n_in, n_in + 1
        fc.append(f"[{bi}:v]format=rgba,split={len(wipes)}" + "".join(f"[bw{k}]" for k in range(len(wipes))))
        D = 0.5
        for k, T in enumerate(wipes):
            fc.append(f"{last}[bw{k}]overlay=x='W-(t-{T:.3f})*(W+w)/{D}':y=0:"
                      f"enable='between(t,{T:.3f},{T + D:.3f})'[wp{k}]")
            last = f"[wp{k}]"
    tail = []
    if look["grain"]:
        tail.append(f"noise=alls={look['grain']}:allf=t")
    if look["vignette"]:
        tail.append("vignette=angle=PI/6")
    dur = total / fps
    fade = float(cfg["audio"].get("fade", 0.35))
    if fade > 0:
        tail += [f"fade=t=in:st=0:d={fade}", f"fade=t=out:st={max(0, dur - fade):.3f}:d={fade}"]
    tail += ["fps=30", "format=yuv420p"]
    fc.append(f"{last}{','.join(tail)}[v]")
    labels = []
    for k, (i, wav) in enumerate(wavs):
        cmd += ["-i", str(wav)]
        delay = int(((timing["shots"][i]["f0"] - 1) / fps + float(ep["shots"][i].get("lead", AUDIO_LEAD))) * 1000)
        fc.append(f"[{n_in}:a]adelay={delay}:all=1[a{k}]")
        labels.append(f"[a{k}]")
        n_in += 1
    # music: quiet bed (default 5%), fades in and out
    music = ep.get("music", cfg["audio"].get("default_music")) or None
    if music and not (ROOT / music).exists():
        print(f"  (music file {music} not found - no music)")
        music = None
    if music:
        mf = float(cfg["audio"].get("music_fade", 1.5))
        cmd += ["-stream_loop", "-1", "-t", f"{dur + 0.5:.3f}", "-i", str((ROOT / music).resolve())]
        fc.append(f"[{n_in}:a]atrim=0:{dur:.3f},volume={ep.get('music_volume', cfg['audio']['music_volume'])},"
                  f"afade=t=in:d={mf},afade=t=out:st={max(0, dur - mf):.3f}:d={mf}[mus]")
        labels.append("[mus]")
        n_in += 1
        print(f"  music: {Path(music).name}")
    # sound effects (per shot) and a background ambience loop
    sx = S.deep_merge(cfg["sfx"], ep.get("sfx", {}))
    for k, (slot, at, vol) in enumerate(sfx_events(ep, timing, sx)):
        cmd += ["-i", str(sfxlib.path_for(slot))]
        fc.append(f"[{n_in}:a]volume={vol:.2f},adelay={int(at * 1000)}:all=1[s{k}]")
        labels.append(f"[s{k}]")
        n_in += 1
        print(f"  sfx: {slot} at {at:.1f}s")
    amb_parts = []                    # (slot, start s, end s): the ambience changes with the set
    if (len(segs) > 1 or segs[0][0] != ep.get("set", "cafe")) and ep.get("ambience", sx.get("ambience", "auto")) == "auto":
        for sid, idxs in segs:
            a0 = (timing["shots"][idxs[0]]["f0"] - 1) / fps
            a1 = (timing["shots"][idxs[-1]]["f0"] + timing["shots"][idxs[-1]]["n"] - 1) / fps
            sub = {"set": sid, "ambience": "auto"}
            embed_set(sub)
            slot = ambience_slot(sub, sx)
            if slot:
                amb_parts.append((slot, a0, a1))
    else:
        slot = ambience_slot(ep, sx)
        if slot:
            amb_parts.append((slot, 0.0, dur))
    for k, (amb, a0, a1) in enumerate(amb_parts):
        ln = max(0.1, a1 - a0)
        # finite input (-t before -i): an endless loop here made ffmpeg buffer GBs while a delayed track waited
        cmd += ["-stream_loop", "-1", "-t", f"{ln + 0.5:.3f}", "-i", str(sfxlib.path_for(amb))]
        fi, fo = (1.0 if a0 == 0 else 0.4), (1.2 if a1 >= dur - 0.05 else 0.4)
        fc.append(f"[{n_in}:a]atrim=0:{ln:.3f},volume={float(sx['ambience_volume']):.2f},"
                  f"afade=t=in:d={fi},afade=t=out:st={max(0, ln - fo):.3f}:d={fo},adelay={int(a0 * 1000)}:all=1[amb{k}]")
        labels.append(f"[amb{k}]")
        n_in += 1
        print(f"  ambience: {amb}" + (f" ({a0:.1f}-{a1:.1f}s)" if len(amb_parts) > 1 else ""))
    afades = (f",afade=t=in:d={fade},afade=t=out:st={max(0, dur - fade):.3f}:d={fade}" if fade > 0 else "")
    if labels:
        # apad to exactly the video's length (a bare apad never ends - one less way for the encode to hang)
        fc.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                  f"apad=whole_dur={dur:.3f}{afades}[a]")
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
        fc.append(f"[{n_in}:a]anull[a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total / fps:.3f}",
            "-c:v", "libx264", "-preset", "medium",
            "-crf", str(max(14, min(30, int(cfg["render"].get("crf", 20))))), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out)]
    report(0.89, "Adding the look, captions and sound")
    encode_with_progress(cmd, build, total / fps, 0.89, 0.98)

    # 4. contact sheet: middle of every shot from the FINISHED video (filter + captions), for review
    picks = "+".join(f"eq(n\\,{round(((s['f0'] - 1 + s['n'] / 2) / fps) * 30)})" for s in timing["shots"])
    sheet = out_dir / f"{name}_shots.png"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(out), "-vf",
                    f"select='{picks}',scale=432:768,tile={len(timing['shots'])}x1",
                    "-frames:v", "1", "-update", "1", str(sheet)], cwd=build, check=True)

    report(1.0, "Done")
    print(f"Done in {time.time() - t0:.0f}s -> {out}  ({total / fps:.1f}s video)")
    print(f"Shot sheet -> {sheet}")


if __name__ == "__main__":
    main()
