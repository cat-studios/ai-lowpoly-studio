"""
Global settings (config/settings.json) and character profiles (assets/characters/<id>.json).
Everything here can be edited from the web app's Settings and Characters pages.
"""
import copy
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = ROOT / "config" / "settings.json"
CHAR_DIR = ROOT / "assets" / "characters"

DEFAULTS = {
    "active_character": "catgirl",
    "language": "en",                     # the finished videos' language (catalog.LANGUAGES); episodes can override
    "render": {"width": 216, "height": 384, "fps": 30,
               "crf": 20},                # x264 quality of the finished mp4: lower = bigger and sharper (18 = ~1.6x size)
    "look": {
        "blur": 1.6,                     # softness after the pixel upscale (0 = razor sharp)
        "fringe": 4,                     # red/blue channel offset in output pixels
        "saturation": 0.78,
        "contrast": 0.9,
        "black": [0.18, 0.17, 0.21],     # output black level per R,G,B (lifted, slightly purple)
        "white": [0.96, 0.94, 0.98],
        "grain": 7,
        "scanlines": True,
        "vignette": True,
        "color_bits": 5,                 # bits per channel before upscale (5 = N64-like 15-bit colour)
        "dither": False,                 # ordered (Bayer) dithering before colour reduction - PS1 style
        "bloom": 0.0,                    # glow around bright areas (0-1)
        "tint": "none",                  # none, warm, cool, purple, sepia, noir, gameboy, sunset
        "sharp_pixels": False,           # True = crisp nearest-neighbour pixels, no blur at all
    },
    "captions": {
        "mode": "words",                 # "words" = a few words at a time mid-screen, "line" = whole line
        "group": 2,                      # words shown together in "words" mode (1 = one at a time)
        "cycle": ["#ffffff", "#f0e060", "#ff8fb8", "#8fe6ff"],   # word colours, cycling (empty = one colour)
        "font": "Arial Black",
        "size": 0.06,                    # fraction of frame height
        "position": 0.33,                # distance from the bottom, fraction of frame height
        "uppercase": True,
        "title_size": 0.04,
        "title_seconds": 3.0,
        "title_outline": 1,              # the title's dark outline (low-res pixels) - it sits over pale skies/walls
        "color": "#dcf5fa",
        "shadow_color": "#302040",
        "outline": 0,                    # 0 = drop shadow only; 1-3 = outline thickness (low-res pixels)
        "title_color": "#f0f0f0",
        "title_color2": "#f0e060",       # second line of the title
        "effect": "pop",                 # none, pop (scale in), bounce, fade
    },
    "branding": {
        "watermark": "",                 # e.g. "@mychannel" - small text in a corner
        "watermark_corner": "bottom-right",
        "end_text": "",                  # e.g. "FOLLOW FOR MORE" - shown at the very end
        "end_seconds": 2.0,
    },
    "voice": {"engine": "edge", "name": "en-US-AnaNeural", "rate": "+8%", "pitch": "+15Hz"},
    "audio": {"lead": 0.15, "tail_pad": 0.6, "music_volume": 0.05, "default_music": "",
              "intro": 0.7,               # seconds of calm before the first line (character idles, title shows)
              "outro": 1.3,               # seconds held after the last line
              "fade": 0.35,               # video + audio fade in/out at the very start and end
              "music_fade": 1.5},         # music fade in/out
    "sfx": {"auto": True,                 # add effects from trigger words / actions when a shot has none set
            "volume": 0.55,
            "ambience": "auto",           # "auto" = from the set's theme, "" = off, or a slot name
            "ambience_volume": 0.35},
    "ollama": {"url": "http://127.0.0.1:11434", "model": "eriktonon/deepseek-v4.1-flash-1017:latest",
               "temperature": 0.85,
               "vision_model": "qwen3.5:4b",         # reads pictures (scene from a picture); must support images
               "design_model": "",                   # builds props / explainer models in 3D ("" = "model")
               "design_url": ""},                    # another Ollama just for that ("" = "url"; unreachable = "url")
    "server": {"pin": ""},                 # optional PIN for phones on your network (empty = no PIN)
    "sets": {"use_ollama": True,           # let Ollama design new sets (falls back to pure random)
             "look_check": True,           # the picture model checks new sets (and redesigns ones that don't fit)
             "prop_check": True},          # ...and new props (a redesign, then a drawn picture) - slower, better
    # Postiz (self-hosted or cloud): finished videos are sent as DRAFTS only
    "postiz": {"url": "", "api_key": "", "channels": {}, "youtube_privacy": "public", "made_with_ai": False,
               "extra_hashtags": "#catgirl #animation #lowpoly"},
    # ComfyUI: "required" = always texture sets (pictures + floor + walls/sky), "auto" = only when a set
    # has picture props, "off" = never. ComfyUI Desktop listens on 8666 (comfy.find_server also tries 8188...)
    "comfy": {"mode": "auto", "url": "http://127.0.0.1:8666", "checkpoint": "", "steps": 20, "cfg": 6.5,
              "texture_size": 128, "style": "low poly retro game texture, simple shapes, flat colors"},
}

# One-click looks for the Settings page and per-episode overrides (only keys listed are changed).
LOOK_PRESETS = {
    "N64 Haze": {"blur": 1.6, "fringe": 4, "saturation": 0.78, "contrast": 0.9, "black": [0.18, 0.17, 0.21],
                 "white": [0.96, 0.94, 0.98], "grain": 7, "scanlines": True, "vignette": True, "color_bits": 5,
                 "dither": False, "bloom": 0.0, "tint": "none", "sharp_pixels": False},
    "Clean Retro": {"blur": 0.6, "fringe": 1, "saturation": 1.0, "contrast": 1.0, "black": [0.03, 0.03, 0.04],
                    "white": [1.0, 1.0, 1.0], "grain": 2, "scanlines": False, "vignette": False, "color_bits": 6,
                    "dither": False, "bloom": 0.1, "tint": "none", "sharp_pixels": False},
    "VHS Tape": {"blur": 2.6, "fringe": 8, "saturation": 0.65, "contrast": 0.85, "black": [0.2, 0.18, 0.2],
                 "white": [0.94, 0.92, 0.9], "grain": 16, "scanlines": True, "vignette": True, "color_bits": 6,
                 "dither": False, "bloom": 0.25, "tint": "warm", "sharp_pixels": False},
    "PS1 Crunch": {"blur": 0.0, "fringe": 0, "saturation": 1.05, "contrast": 1.05, "black": [0.02, 0.02, 0.03],
                   "white": [1.0, 1.0, 1.0], "grain": 0, "scanlines": False, "vignette": False, "color_bits": 5,
                   "dither": True, "bloom": 0.0, "tint": "none", "sharp_pixels": True},
    "Game Boy": {"blur": 0.4, "fringe": 0, "saturation": 1.0, "contrast": 1.0, "black": [0.0, 0.0, 0.0],
                 "white": [1.0, 1.0, 1.0], "grain": 0, "scanlines": False, "vignette": False, "color_bits": 8,
                 "dither": True, "bloom": 0.0, "tint": "gameboy", "sharp_pixels": True},
    "Dreamy Pastel": {"blur": 1.8, "fringe": 2, "saturation": 0.9, "contrast": 0.85, "black": [0.22, 0.2, 0.26],
                      "white": [1.0, 0.97, 1.0], "grain": 4, "scanlines": False, "vignette": True, "color_bits": 6,
                      "dither": False, "bloom": 0.45, "tint": "purple", "sharp_pixels": False},
    "Spooky Night": {"blur": 1.4, "fringe": 5, "saturation": 0.55, "contrast": 1.1, "black": [0.06, 0.07, 0.1],
                     "white": [0.85, 0.9, 0.95], "grain": 12, "scanlines": True, "vignette": True, "color_bits": 5,
                     "dither": False, "bloom": 0.2, "tint": "cool", "sharp_pixels": False},
}
TINTS = ["none", "warm", "cool", "purple", "sunset", "sepia", "noir", "gameboy"]
CAPTION_EFFECTS = ["none", "pop", "bounce", "fade"]

CHARACTER_DEFAULTS = {
    "name": "",
    "about": "",
    "model": "",                 # .blend made by the importer; empty = built-in placeholder
    "voice": {},
    "tail": False,
    "tail_color": "#c9aed8",
    "tail_tip": False,
    "camera_scale": 0.72,
}


def write_json(path, data, indent=2):
    """Write JSON atomically (temp file + rename): a crash or a second writer can't leave half a file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings():
    data = {}
    if SETTINGS_FILE.exists():
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    return deep_merge(DEFAULTS, data)


MASK = "__saved__"   # stands in for secrets in anything sent to the browser


def public_settings(data=None):
    """Settings for the web page: secrets replaced by MASK (or "" when not set)."""
    out = copy.deepcopy(data or load_settings())
    pz = out.get("postiz") or {}
    if pz.get("api_key"):
        pz["api_key"] = MASK
    return out


def save_settings(data):
    data = copy.deepcopy(data)
    pz = data.get("postiz")
    if isinstance(pz, dict) and pz.get("api_key") == MASK:     # unchanged secret: keep the stored one
        pz["api_key"] = load_settings().get("postiz", {}).get("api_key", "")
    write_json(SETTINGS_FILE, deep_merge(DEFAULTS, data))


def valid_id(cid):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", cid or ""))


def character_ids():
    return sorted(p.stem for p in CHAR_DIR.glob("*.json")
                  if not p.stem.endswith(".report") and valid_id(p.stem))


def load_character(cid):
    """Profile with defaults filled in. Unknown id -> placeholder profile."""
    data = {}
    path = CHAR_DIR / f"{cid}.json"
    if valid_id(cid) and path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    prof = deep_merge(CHARACTER_DEFAULTS, data)
    prof["id"] = cid
    prof["name"] = prof["name"] or cid
    # older profiles had no "model" key: the convention is <id>.blend next to the profile
    if not prof["model"] and (CHAR_DIR / f"{cid}.blend").exists():
        prof["model"] = f"assets/characters/{cid}.blend"
    return prof


def speaker_names(prof):
    """Every name a script may use for a character: its id, its name, and a "Name: ..." line in its about text
    (the AI writer reads that and uses it, e.g. a profile called Pokemon whose about says "Name: Ethan")."""
    names = {str(prof.get("id") or ""), str(prof.get("name") or "")}
    m = re.search(r"(?im)^\s*name\s*:\s*([^\n(,]+)", str(prof.get("about") or ""))
    if m:
        names.add(m.group(1).strip())
    return [n for n in names if n and len(n) <= 31]


def save_character(cid, data):
    if not valid_id(cid):
        raise ValueError("Character id must be lowercase letters, numbers, - or _")
    data = {k: v for k, v in data.items() if k != "id"}
    write_json(CHAR_DIR / f"{cid}.json", data)


def layered_voice(*layers):
    """Merge voice dicts; a layer naming a different engine replaces the ones before it."""
    out = {}
    for layer in layers:
        if not layer:
            continue
        if layer.get("engine") and layer["engine"] != out.get("engine"):
            out = {}
        out.update(layer)
    return out
