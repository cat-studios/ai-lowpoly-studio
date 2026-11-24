"""
Sound effects library.

Every effect is a named slot (boom, coin, boing, ...). Each slot has a built-in sound synthesised with
ffmpeg (retro / chiptune style, made once into assets/sfx/builtin/) and can be overridden by uploading
your own file in the web app (assets/sfx/custom/<slot>.<ext>). You can also add your own slots.

Slots have trigger words (used by the auto-director: a line saying "BOOM" gets the boom effect) and
"ambience" slots are quiet background loops chosen per set theme.
"""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
SFX_DIR = ROOT / "assets" / "sfx"
BUILTIN = SFX_DIR / "builtin"
CUSTOM = SFX_DIR / "custom"
CUSTOM_SLOTS = SFX_DIR / "custom_slots.json"
AUDIO_EXT = (".wav", ".mp3", ".ogg", ".m4a", ".flac")

# name: (label, kind, trigger words, seconds, aevalsrc expression, extra filter)
SLOTS = {
    "boom": ("Boom / explosion", "oneshot", "boom kaboom explode explosion exploded firework fireworks bang blast",
             2.0, "(random(0)*2-1)*exp(-3*t)*0.9+sin(2*PI*(60-25*t)*t)*exp(-2.5*t)", "lowpass=f=700,volume=1.6"),
    "pop": ("Pop", "oneshot", "pop popped bubble poof", 0.2,
            "sin(2*PI*(1100-900*t/0.2)*t)*exp(-30*t)", ""),
    "boing": ("Boing (surprise)", "oneshot", "boing bounce bouncy huh wait what", 0.7,
              "sin(2*PI*(200+110*sin(2*PI*14*t))*t)*exp(-4*t)", ""),
    "jump": ("Jump (8-bit)", "oneshot", "jump hop leap", 0.3,
             "0.35*sgn(sin(2*PI*(220+1400*t)*t))*exp(-5*t)", "lowpass=f=5000"),
    "coin": ("Coin / point", "oneshot", "coin money cash score point points prize", 0.45,
             "0.3*sgn(sin(2*PI*if(lt(t,0.08),988,1319)*t))*if(lt(t,0.08),1,exp(-8*(t-0.08)))", "lowpass=f=6000"),
    "ding": ("Ding (idea!)", "oneshot", "ding idea genius brilliant realized aha got", 1.4,
             "0.6*sin(2*PI*1760*t)*exp(-3*t)+0.25*sin(2*PI*2640*t)*exp(-5*t)", ""),
    "tada": ("Ta-da / power-up", "oneshot", "tada ta-da yay hooray victory win won finally perfect did",
             1.0, "0.28*sgn(sin(2*PI*if(lt(t,0.12),523,if(lt(t,0.24),659,if(lt(t,0.36),784,1047)))*t))"
                  "*if(lt(t,0.36),1,exp(-4*(t-0.36)))", "lowpass=f=6000"),
    "whoosh": ("Whoosh", "oneshot", "whoosh zoom fast swoosh fly flying dash", 0.6,
               "(random(0)*2-1)*sin(PI*t/0.6)", "bandpass=f=900:width_type=h:w=1400"),
    "hiss": ("Cat hiss", "oneshot", "hiss hisss hsss hss", 1.0,
             "(random(0)*2-1)*if(lt(t,0.08),t/0.08,exp(-1.6*(t-0.08)))", "highpass=f=2500,volume=1.4"),
    "stomp": ("Stomp / thud", "oneshot", "stomp thud slam crash fall fell", 0.45,
              "sin(2*PI*(85-50*t)*t)*exp(-9*t)+0.5*(random(0)*2-1)*exp(-25*t)", "lowpass=f=900,volume=1.4"),
    "laser": ("Laser / zap", "oneshot", "laser pew zap blaster", 0.35,
              "0.6*sin(2*PI*(1800-4000*t)*t)*exp(-6*t)", ""),
    "fail": ("Sad trombone (fail)", "oneshot", "fail failed oops nooo wrong nobody sad", 2.0,
             "0.3*sin(2*PI*if(lt(t,0.4),392,if(lt(t,0.8),370,if(lt(t,1.2),349,330+6*sin(2*PI*6*t))))*t)"
             "*if(lt(t,1.2),1,exp(-2*(t-1.2)))", "aeval='val(0)+0.4*sin(2*val(0))'"),
    "buzz": ("Error buzzer", "oneshot", "error buzzer denied", 0.5,
             "0.35*sgn(sin(2*PI*110*t))", "lowpass=f=3000"),
    "meow": ("Meow (synth)", "oneshot", "meow mew nya nyaa", 0.6,
             "0.45*sin(2*PI*(520+380*sin(PI*t/0.6))*t+3*sin(2*PI*5*t))*sin(PI*t/0.6)", "lowpass=f=4000"),
    "click": ("Click / blip", "oneshot", "click tap button press", 0.08,
              "0.5*sgn(sin(2*PI*1600*t))*exp(-60*t)", ""),
    "sparkle": ("Sparkle / magic", "oneshot", "sparkle magic shiny glitter wow", 1.2,
                "0.25*sin(2*PI*(2000+800*sin(2*PI*9*t))*t)*exp(-2.5*t)+0.2*sin(2*PI*3100*t)*exp(-4*t)", ""),
    # quiet background loops (20 s), picked by set theme
    "amb_arcade": ("Ambience: arcade bleeps", "ambience", "", 20.0,
                   "0.12*sgn(sin(2*PI*(440+220*floor(mod(t*3,4)))*t))*lt(mod(t,1.7),0.12)"
                   "+0.08*sgn(sin(2*PI*(660+110*floor(mod(t*5,3)))*t))*lt(mod(t+0.6,2.3),0.09)"
                   "+0.05*(random(0)*2-1)", "lowpass=f=4000"),
    "amb_waves": ("Ambience: ocean waves", "ambience", "", 20.0,
                  "(random(0)*2-1)*(0.35+0.3*sin(2*PI*0.12*t))", "lowpass=f=900,volume=0.9"),
    "amb_wind": ("Ambience: wind", "ambience", "", 20.0,
                 "(random(0)*2-1)*(0.4+0.25*sin(2*PI*0.07*t)+0.1*sin(2*PI*0.31*t))", "bandpass=f=400:width_type=h:w=500"),
    "amb_birds": ("Ambience: birds", "ambience", "", 20.0,
                  "0.18*sin(2*PI*(2600+900*sin(2*PI*18*t))*t)*lt(mod(t,3.1),0.18)"
                  "+0.14*sin(2*PI*(3300-1200*mod(t,0.15)/0.15)*t)*lt(mod(t+1.3,4.7),0.3)"
                  "+0.04*(random(0)*2-1)", "highpass=f=200"),
    "amb_city": ("Ambience: city traffic", "ambience", "", 20.0,
                 "(random(0)*2-1)*(0.45+0.2*sin(2*PI*0.09*t))", "lowpass=f=300,volume=1.3"),
    "amb_space": ("Ambience: space hum", "ambience", "", 20.0,
                  "0.25*sin(2*PI*55*t)+0.12*sin(2*PI*110.5*t)+0.06*sin(2*PI*221*t)*(0.5+0.5*sin(2*PI*0.2*t))", ""),
    "amb_room": ("Ambience: cosy room tone", "ambience", "", 20.0,
                 "(random(0)*2-1)*0.25", "lowpass=f=500,volume=0.8"),
    "amb_spooky": ("Ambience: spooky drone", "ambience", "", 20.0,
                   "0.2*sin(2*PI*(73+2*sin(2*PI*0.1*t))*t)+0.15*sin(2*PI*(110+3*sin(2*PI*0.13*t))*t)"
                   "+0.3*(random(0)*2-1)*(0.5+0.5*sin(2*PI*0.05*t))", "lowpass=f=600"),
}

THEME_AMBIENCE = {
    "arcade": "amb_arcade", "beach": "amb_waves", "forest": "amb_birds", "candyland": "amb_birds",
    "park": "amb_birds", "snow": "amb_wind", "desert": "amb_wind", "graveyard": "amb_spooky",
    "city": "amb_city", "space_station": "amb_space", "cafe": "amb_room", "kitchen": "amb_room",
    "bedroom": "amb_room", "living_room": "amb_room", "classroom": "amb_room",
}
# actions that get an effect automatically (only if the line didn't already trigger one)
ACTION_SFX = {"jump": "jump", "surprised": "boing", "celebrate": "tada", "stomp": "stomp", "spin": "whoosh",
              "run_to": "whoosh"}


def custom_slots():
    if CUSTOM_SLOTS.exists():
        return json.loads(CUSTOM_SLOTS.read_text(encoding="utf-8-sig"))
    return {}


def add_custom_slot(name, label, words, kind="oneshot"):
    if not re.fullmatch(r"[a-z0-9_]{2,30}", name or ""):
        raise ValueError("slot name: 2-30 lowercase letters, numbers or _")
    if name in SLOTS:
        raise ValueError("that slot already exists")
    data = custom_slots()
    data[name] = {"label": label or name, "kind": kind, "words": words or ""}
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_SLOTS.write_text(json.dumps(data, indent=1), encoding="utf-8")


def all_slots():
    out = {k: {"label": v[0], "kind": v[1], "words": v[2], "builtin": True} for k, v in SLOTS.items()}
    for k, v in custom_slots().items():
        out[k] = {"label": v.get("label", k), "kind": v.get("kind", "oneshot"), "words": v.get("words", ""), "builtin": False}
    return out


def custom_file(slot):
    return next((p for p in sorted(CUSTOM.glob(f"{slot}.*")) if p.suffix.lower() in AUDIO_EXT), None)


def path_for(slot):
    """The file to use for a slot: your upload if there is one, else the built-in sound."""
    c = custom_file(slot)
    if c:
        return c
    b = BUILTIN / f"{slot}.wav"
    return b if b.exists() else None


def generate_builtin(ffmpeg="ffmpeg", force=False, log=print):
    BUILTIN.mkdir(parents=True, exist_ok=True)
    made = 0
    for name, (_, kind, _, secs, expr, extra) in SLOTS.items():
        out = BUILTIN / f"{name}.wav"
        if out.exists() and not force:
            continue
        af = "aformat=channel_layouts=mono,afade=t=out:st=%.2f:d=%.2f" % (max(0.0, secs - 0.05), 0.05)
        if kind == "ambience":    # make the loop seamless-ish: fade the ends
            af = "aformat=channel_layouts=mono,afade=t=in:d=1,afade=t=out:st=%.1f:d=1" % (secs - 1)
        if extra:
            af = extra + "," + af
        raw = out.with_suffix(".raw.wav")
        r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"aevalsrc='{expr}':s=44100:d={secs}", "-af", af, "-ar", "44100", str(raw)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[sfx] {name} failed: {r.stderr.strip()[-300:]}")
            continue
        # even out levels: one-shots peak at -1 dB, ambience loops sit at a calm average level
        if kind == "ambience":
            norm = "loudnorm=I=-26:TP=-6:LRA=7,aresample=44100"
        else:
            det = subprocess.run([ffmpeg, "-hide_banner", "-i", str(raw), "-af", "volumedetect", "-f", "null", "-"],
                                 capture_output=True, text=True).stderr
            m = re.search(r"max_volume: (-?[\d.]+) dB", det)
            norm = f"volume={-1.0 - float(m.group(1)) if m else 0:.1f}dB"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-af", norm,
                        "-ar", "44100", "-ac", "1", str(out)], check=True)
        raw.unlink(missing_ok=True)
        made += 1
    log(f"[sfx] generated {made} built-in sounds in {BUILTIN}")
    return made


_WORD_RX = {}


def word_rx(w):
    """A trigger word as a regex that also matches its endings and stretched letters:
    "hiss" -> hiss, hisses, hissing, hisssss; "hsss" -> hssssss; "pop" -> pops, popped, popping."""
    w = w.lower()
    if w not in _WORD_RX:
        runs = re.findall(r"((.)\2*)", w)
        body = "".join(re.escape(ch) + (f"{{{len(run)},}}" if len(run) > 1 else "+") for run, ch in runs)
        _WORD_RX[w] = re.compile(rf"\b{body}(?:s|es|ed|ing|in)?\b")
    return _WORD_RX[w]


def trigger(line):
    """The effect whose trigger words are in the line (your own sounds win over built-ins), else None."""
    text = (line or "").lower()
    ordered = sorted(all_slots().items(), key=lambda kv: kv[1]["builtin"])
    for name, s in ordered:
        if s["kind"] != "oneshot" or not s["words"]:
            continue
        if any(word_rx(w).search(text) for w in s["words"].split()):
            return name
    return None


def suggest(line, action=None):
    """Pick one effect for a shot from trigger words in the line, else from the action."""
    return trigger(line) or ACTION_SFX.get(action or "")


def ambience_for(theme):
    return THEME_AMBIENCE.get(theme or "")


# --------------------------------------------------------------------------- generating new sounds
# A small parametric synthesiser: a tone layer (waveform + pitch sweep + vibrato or arpeggio), a filtered
# noise layer, an envelope and optional repeats. Ollama turns a description into these parameters;
# without Ollama, keywords + randomness choose them.
import random  # noqa: E402

WAVES = {
    "sine": "sin(2*PI*({ph}))",
    "square": "sgn(sin(2*PI*({ph})))",
    "saw": "(2*(({ph})-floor({ph}))-1)",
    "triangle": "(2*abs(2*(({ph})-floor({ph}))-1)-1)",
}


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def build_sound(params, out, ffmpeg="ffmpeg", ambience=False):
    """Render synth parameters to a wav. Returns the cleaned parameters that were used."""
    p = params or {}
    D = 20.0 if ambience else _num(p.get("duration"), 0.05, 4.0, 0.6)
    tone = p.get("tone") or {}
    noise = p.get("noise") or {}
    env = p.get("envelope") or {}
    rep = p.get("repeat") or {}
    wave = tone.get("wave") if tone.get("wave") in WAVES else ("none" if tone.get("wave") == "none" else "sine")
    f0 = _num(tone.get("start_hz"), 20, 8000, 440)
    f1 = _num(tone.get("end_hz"), 20, 8000, f0)
    vib_hz = _num(tone.get("vibrato_hz"), 0, 40, 0)
    vib_d = _num(tone.get("vibrato_depth"), 0, 600, 0)
    tvol = _num(tone.get("volume"), 0, 1, 0.8 if wave != "none" else 0)
    notes = [n for n in (tone.get("notes") or []) if isinstance(n, (int, float)) and 20 <= n <= 8000][:8]
    namt = _num(noise.get("amount"), 0, 1, 0)
    nfilt = noise.get("filter") if noise.get("filter") in ("low", "high", "band") else "none"
    nfreq = _num(noise.get("freq"), 60, 12000, 1200)
    att = _num(env.get("attack"), 0.0, 2.0, 0.005)
    hold = _num(env.get("hold"), 0.0, 4.0, 0.0)
    dec = _num(env.get("decay_rate"), 0.0, 60.0, 4.0)
    count = int(_num(rep.get("count"), 1, 16, 1))
    inter = _num(rep.get("interval"), 0.03, 2.0, D)
    if count > 1:
        D = max(D, count * inter + 0.3) if not ambience else D
    # expressions use the placeholder TT for "local time", swapped for the real variable at the end:
    # plain t, mod(t, interval) for repeats, or mod(t, every) for ambience events
    if ambience:
        amb = p.get("ambience") or {}
        lfo = _num(amb.get("lfo_hz"), 0.01, 2, 0.08)
        every = _num(amb.get("events_every"), 0.3, 10, 2.5)
        elen = _num(amb.get("event_len"), 0.02, 2, 0.25)
        tt, seg = f"mod(t,{every:.3f})", elen
    else:
        tt = f"mod(t,{inter:.4f})" if count > 1 else "t"
        seg = inter if count > 1 else D
    if notes:
        n = len(notes)
        f = f"{notes[-1]:.2f}"
        for k in range(n - 2, -1, -1):
            f = f"if(lt(TT,{seg * (k + 1) / n:.4f}),{notes[k]:.2f},{f})"
        ph = f"({f})*TT"
    else:
        ph = f"({f0:.2f}*TT+({f1 - f0:.2f})*TT*TT/(2*{seg:.4f}))"
    if vib_hz > 0 and vib_d > 0:
        ph += f"+{vib_d / (2 * 3.14159 * vib_hz):.4f}*sin(2*PI*{vib_hz:.2f}*TT)"
    gate = f"*lt(t,{count * inter:.4f})" if count > 1 and not ambience else ""
    if ambience:   # loops: slow swell for the noise bed, short tone "events" repeating
        envx = f"(0.65+0.35*sin(2*PI*{lfo:.3f}*t))"
        tone_expr = (f"{tvol:.3f}*{WAVES[wave].format(ph=ph)}*lt(TT,{elen:.3f})*exp(-6*TT)"
                     if wave != "none" else "0")
    else:
        envx = f"min(1,TT/{max(att, 0.001):.4f})*if(lt(TT,{hold:.3f}),1,exp(-{dec:.3f}*(TT-{hold:.3f})))"
        tone_expr = f"{tvol:.3f}*{WAVES[wave].format(ph=ph)}*{envx}{gate}" if wave != "none" else "0"
    tone_expr = tone_expr.replace("TT", tt)
    envx = envx.replace("TT", tt)
    noise_expr = f"{namt:.3f}*(random(0)*2-1)*{envx}{gate}" if namt > 0 else "0"
    nf = {"low": f"lowpass=f={nfreq:.0f}", "high": f"highpass=f={nfreq:.0f}",
          "band": f"bandpass=f={nfreq:.0f}:width_type=h:w={nfreq * 0.8:.0f}", "none": "anull"}[nfilt]
    fade = "afade=t=in:d=1,afade=t=out:st=19:d=1" if ambience else f"afade=t=out:st={max(0, D - 0.03):.3f}:d=0.03"
    norm = "loudnorm=I=-26:TP=-6" if ambience else "alimiter=limit=0.95"
    graph = (f"[0:a]aformat=channel_layouts=mono[a];[1:a]{nf},aformat=channel_layouts=mono[b];"
             f"[a][b]amix=inputs=2:normalize=0,{fade},{norm}[o]")
    raw = Path(str(out) + ".raw.wav")
    r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"aevalsrc='{tone_expr}':s=44100:d={D:.3f}",
                        "-f", "lavfi", "-i", f"aevalsrc='{noise_expr}':s=44100:d={D:.3f}",
                        "-filter_complex", graph, "-map", "[o]", "-ar", "44100", str(raw)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("sound synthesis failed: " + r.stderr.strip()[-300:])
    if not ambience:   # peak-normalise one-shots to -1 dB like the built-ins
        det = subprocess.run([ffmpeg, "-hide_banner", "-i", str(raw), "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        m = re.search(r"max_volume: (-?[\d.]+) dB", det)
        gain = -1.0 - float(m.group(1)) if m and float(m.group(1)) > -90 else 0
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-af",
                        f"volume={gain:.1f}dB", str(out)], check=True)
        raw.unlink(missing_ok=True)
    else:
        raw.replace(out)
    return {"duration": round(D, 3), "tone": {"wave": wave, "start_hz": f0, "end_hz": f1, "vibrato_hz": vib_hz,
            "vibrato_depth": vib_d, "notes": notes, "volume": tvol}, "noise": {"amount": namt, "filter": nfilt,
            "freq": nfreq}, "envelope": {"attack": att, "hold": hold, "decay_rate": dec},
            "repeat": {"count": count, "interval": inter}}


SYNTH_GUIDE = (
    "You are a retro video-game sound designer. Turn the description into synthesiser settings. "
    "Reply with JSON only:\n"
    '{"duration": seconds (0.05-3), "tone": {"wave": "sine|square|saw|triangle|none", "start_hz": number, '
    '"end_hz": number, "vibrato_hz": number, "vibrato_depth": number, "notes": [optional list of Hz for an arpeggio], '
    '"volume": 0-1}, "noise": {"amount": 0-1, "filter": "low|high|band|none", "freq": Hz}, '
    '"envelope": {"attack": seconds, "hold": seconds, "decay_rate": 0-60 (higher = shorter)}, '
    '"repeat": {"count": 1-12, "interval": seconds}, '
    '"ambience": {"lfo_hz": 0.02-1, "events_every": seconds, "event_len": seconds}}\n'
    "Tips: explosions = loud low-passed noise (freq 300-800) + low sine sweep 80->30 Hz, slow decay. "
    "Lasers = square/sine sweep down 2000->200. Coins/power-ups = square arpeggio going up. "
    "Footsteps/crackles/knocks = short noise bursts with repeat. Wind/rain/crowd = noise only. "
    "Birds/chirps = high sine with fast vibrato. Use 'ambience' only for background loops."
)


def _fallback_params(desc, ambience, rng):
    d = (desc or "").lower()
    has = lambda *ws: any(w in d for w in ws)
    if ambience:
        if has("rain", "storm", "shower"):
            return {"noise": {"amount": 0.8, "filter": "high", "freq": rng.uniform(1500, 4000)}, "tone": {"wave": "none"},
                    "ambience": {"lfo_hz": 0.05}}
        if has("bird", "forest", "jungle", "chirp"):
            return {"noise": {"amount": 0.1, "filter": "high", "freq": 3000},
                    "tone": {"wave": "sine", "start_hz": rng.uniform(2200, 3500), "end_hz": rng.uniform(1800, 4000),
                             "vibrato_hz": rng.uniform(12, 25), "vibrato_depth": 400, "volume": 0.3},
                    "ambience": {"events_every": rng.uniform(1.5, 4), "event_len": 0.2}}
        return {"noise": {"amount": 0.6, "filter": rng.choice(["low", "band"]), "freq": rng.uniform(200, 900)},
                "tone": {"wave": rng.choice(["none", "sine"]), "start_hz": rng.uniform(50, 120), "volume": 0.2},
                "ambience": {"lfo_hz": rng.uniform(0.03, 0.2)}}
    if has("explo", "boom", "blast", "bang", "firework"):
        return {"duration": rng.uniform(1.2, 2.2), "noise": {"amount": 0.9, "filter": "low", "freq": rng.uniform(300, 900)},
                "tone": {"wave": "sine", "start_hz": rng.uniform(70, 110), "end_hz": 30, "volume": 0.8},
                "envelope": {"decay_rate": rng.uniform(2, 4)},
                "repeat": {"count": rng.choice([1, 1, 3]), "interval": 0.35} if "firework" in d else {}}
    if has("laser", "zap", "shoot", "pew"):
        return {"duration": 0.35, "tone": {"wave": rng.choice(["square", "sine", "saw"]), "start_hz": rng.uniform(1500, 2500),
                "end_hz": rng.uniform(150, 400)}, "envelope": {"decay_rate": 5}}
    if has("coin", "power", "level", "win", "magic", "sparkle", "chime", "bell"):
        root = rng.uniform(400, 900)
        return {"duration": 0.6, "tone": {"wave": rng.choice(["square", "triangle", "sine"]),
                "notes": [root, root * 1.25, root * 1.5, root * 2]}, "envelope": {"hold": 0.4, "decay_rate": 6}}
    if has("step", "knock", "crackle", "tap", "click", "clap"):
        return {"duration": 0.08, "noise": {"amount": 0.9, "filter": "band", "freq": rng.uniform(400, 2500)},
                "tone": {"wave": "none"}, "envelope": {"decay_rate": 40},
                "repeat": {"count": rng.randint(2, 6), "interval": rng.uniform(0.12, 0.35)}}
    if has("squeak", "toy", "cute", "boing", "spring", "bounce"):
        return {"duration": 0.5, "tone": {"wave": "sine", "start_hz": rng.uniform(500, 900), "end_hz": rng.uniform(900, 1600),
                "vibrato_hz": rng.uniform(8, 16), "vibrato_depth": 150}, "envelope": {"decay_rate": 4}}
    if has("whoosh", "swoosh", "wind", "fast", "swing"):
        return {"duration": 0.6, "noise": {"amount": 0.9, "filter": "band", "freq": rng.uniform(500, 1500)},
                "tone": {"wave": "none"}, "envelope": {"attack": 0.25, "decay_rate": 6}}
    if has("fail", "sad", "lose", "wrong", "error"):
        return {"duration": 1.2, "tone": {"wave": "saw", "start_hz": rng.uniform(300, 420), "end_hz": rng.uniform(150, 250),
                "vibrato_hz": 6, "vibrato_depth": 10}, "envelope": {"hold": 0.6, "decay_rate": 3}}
    return {"duration": rng.uniform(0.2, 0.8),         # anything else: a random retro blip
            "tone": {"wave": rng.choice(list(WAVES)), "start_hz": rng.uniform(150, 1800), "end_hz": rng.uniform(150, 1800),
                     "vibrato_hz": rng.choice([0, 0, 8]), "vibrato_depth": 60},
            "noise": {"amount": rng.choice([0, 0, 0.3]), "filter": "high", "freq": 2000},
            "envelope": {"decay_rate": rng.uniform(3, 12)}}


def generate_sound(slot, description, ambience=False, ffmpeg="ffmpeg", ollama=None, log=print):
    """Make a new sound for `slot` from a description -> assets/sfx/custom/<slot>.wav (old one to .trash)."""
    rng = random.Random()
    params, by = None, "random"
    if ollama:
        try:
            import llm
            params = llm.chat_json(ollama["url"], ollama["model"], SYNTH_GUIDE,
                                   f"Sound: {description}\n" + ("This is a 20-second background ambience loop."
                                                                if ambience else "This is a short sound effect."),
                                   temperature=0.9)
            by = "ollama"
        except Exception as exc:
            log(f"[sfx] Ollama unavailable ({exc.__class__.__name__}) - using the built-in designer")
    if not isinstance(params, dict):
        params = _fallback_params(description, ambience, rng)
    CUSTOM.mkdir(parents=True, exist_ok=True)
    new = CUSTOM / f".{slot}.new.wav"           # made first; the current sound is only replaced once this worked
    try:
        used = build_sound(params, new, ffmpeg, ambience)
    except Exception as exc:       # odd AI parameters: fall back to the built-in designer
        log(f"[sfx] those settings didn't work ({exc}) - trying the built-in designer")
        used = build_sound(_fallback_params(description, ambience, rng), new, ffmpeg, ambience)
        by = "random"
    old = custom_file(slot)
    if old:
        (CUSTOM / ".trash").mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        old.replace(CUSTOM / ".trash" / f"{stamp}-{old.name}")
    out = CUSTOM / f"{slot}.wav"
    new.replace(out)
    (CUSTOM / f"{slot}.json").write_text(json.dumps({"source": "generated", "by": by, "description": description,
                                                     "params": used}, indent=1), encoding="utf-8")
    log(f"[sfx] generated '{slot}' from '{description}' ({by})")
    return out


def list_library():
    out = []
    for name, s in all_slots().items():
        c = custom_file(name)
        b = BUILTIN / f"{name}.wav"
        meta = {}
        if c and (CUSTOM / f"{name}.json").exists():
            try:
                meta = json.loads((CUSTOM / f"{name}.json").read_text(encoding="utf-8-sig"))
            except Exception:
                pass
        out.append({"slot": name, **s, "custom": c.name if c else None, "has_builtin": b.exists(),
                    "generated": meta.get("source") == "generated" and c is not None and c.suffix == ".wav",
                    "description": meta.get("description", ""),
                    "url": f"/sfx/{'custom/' + c.name if c else 'builtin/' + name + '.wav'}" if (c or b.exists()) else None})
    return out


if __name__ == "__main__":
    generate_builtin(shutil.which("ffmpeg") or "ffmpeg", force=True)
