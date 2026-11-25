"""
ComfyUI client: set textures (mode "auto" = only picture props like posters and signs; "required" = also the floor,
walls or sky), drawn prop sprites (object_sprite) and server/model discovery. Music (ACE-Step) is in music_gen.py.
Everything works without ComfyUI except "required" mode: pictures fall back to flat-colour art, props to shapes.
"""
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEGATIVE = "text, watermark, signature, blurry, photo, realistic, nsfw, frame border"


def _get(url, path, timeout=5):
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as r:
        data = r.read()
    return data


def _json(url, path, payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


COMMON_PORTS = ["http://127.0.0.1:8188", "http://127.0.0.1:8666", "http://127.0.0.1:8189", "http://127.0.0.1:8000"]
NOT_IMAGE = ("ace_step", "audio", "music", "svd", "video", "wan", "i2v", "t2v", "ltx", "mochi", "hunyuan_video")


def _is_comfy(url):
    try:
        return "comfyui_version" in _json(url, "/system_stats", timeout=2).get("system", {})
    except Exception:
        return False


def find_server(url):
    """The configured URL if it's ComfyUI, else the first common local port that is."""
    if _is_comfy(url):
        return url
    return next((u for u in COMMON_PORTS if u != url and _is_comfy(u)), None)


def _options(url, node, field):
    try:
        return _json(url, f"/object_info/{node}")[node]["input"]["required"][field][0]
    except Exception:
        return []


def image_models(url):
    """Image generators ComfyUI can run here: classic checkpoints, plus Z-Image Turbo diffusion models."""
    out = [{"name": c, "kind": "checkpoint"} for c in _options(url, "CheckpointLoaderSimple", "ckpt_name")
           if not any(k in c.lower() for k in NOT_IMAGE)]
    unets = _options(url, "UNETLoader", "unet_name")
    clips = _options(url, "CLIPLoader", "clip_name")
    vaes = _options(url, "VAELoader", "vae_name")
    for u in unets:
        if "z_image" in u.lower() or "zimage" in u.lower():
            te = next((c for c in clips if "qwen_3_4b" in c or "qwen3_4b" in c), None)
            vae = next((v for v in vaes if v.lower().startswith("ae")), None)
            if te and vae:
                out.insert(0, {"name": u, "kind": "zimage", "clip": te, "vae": vae})
    return out


_STATUS = {}          # url -> (time, result): a set with many sprites asked ComfyUI the same thing every time


def status(url, max_age=30.0):
    """{'ok', 'url', 'devices', 'models' (image generators), 'checkpoints' (their names), 'error'}.
    Answers are reused for max_age seconds (0 = always ask) - probing every port takes seconds when it's off."""
    hit = _STATUS.get(url)
    if hit and max_age and time.time() - hit[0] < max_age:
        return hit[1]
    found = find_server(url)
    if not found:
        res = {"ok": False, "error": f"ComfyUI not reachable at {url} (also tried ports {', '.join(u.rsplit(':', 1)[-1] for u in COMMON_PORTS)})"}
    else:
        stats = _json(found, "/system_stats", timeout=3)
        models = image_models(found)
        res = {"ok": True, "url": found, "version": stats.get("system", {}).get("comfyui_version", ""),
               "devices": [d.get("name", "") for d in stats.get("devices", [])],
               "models": models, "checkpoints": [m["name"] for m in models]}
    _STATUS[url] = (time.time(), res)
    return res


def checkpoints(url):
    return [m["name"] for m in image_models(url)]


def _graph(model, prompt, width, height, steps, cfg, seed):
    save = {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "lowpoly_tex"}}
    if model["kind"] == "zimage":
        # Z-Image Turbo: separate model / text encoder / VAE, ~8 steps, CFG 1, no negative prompt -
        # so "avoid" words go into the prompt itself (otherwise it loves writing fake lettering)
        prompt += ", no text, no letters, no words, no watermark"
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model["name"], "weight_dtype": "default"}},
            "1b": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
            "8": {"class_type": "CLIPLoader", "inputs": {"clip_name": model["clip"], "type": "lumina2"}},
            "9": {"class_type": "VAELoader", "inputs": {"vae_name": model["vae"]}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["8", 0]}},
            "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]}},
            "4": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {"model": ["1b", 0], "positive": ["2", 0], "negative": ["3", 0],
                                                       "latent_image": ["4", 0], "seed": seed, "steps": min(steps, 9),
                                                       "cfg": 1.0, "sampler_name": "res_multistep",
                                                       "scheduler": "simple", "denoise": 1.0}},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["9", 0]}},
            "7": save,
        }
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model["name"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                                                   "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
                                                   "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": save,
    }


def txt2img(url, prompt, model, width=512, height=512, steps=20, cfg=6.5, seed=None, timeout=300):
    """model: an entry from image_models() (dict) or a checkpoint file name."""
    if isinstance(model, str):
        model = {"name": model, "kind": "checkpoint"}
    seed = seed if seed is not None else int(time.time() * 1000) % 2**31
    graph = _graph(model, prompt, width, height, steps, cfg, seed)
    pid = _json(url, "/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = _json(url, f"/history/{pid}")
        if pid in hist:
            outs = hist[pid].get("outputs", {})
            for node in outs.values():
                for img in node.get("images", []):
                    q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                                "type": img.get("type", "output")})
                    return _get(url, f"/view?{q}", timeout=60)
            state = hist[pid].get("status", {})
            if state.get("status_str") == "error":
                raise RuntimeError("ComfyUI reported an error for the texture prompt")
            if state.get("completed"):          # finished but saved no picture: don't wait out the timeout
                raise RuntimeError("ComfyUI finished without making a picture")
        time.sleep(1.0)
    raise TimeoutError("ComfyUI took too long")


SPRITE_PROMPT = ("{looks}, a single {name}, the whole object fully visible and centered with space around it, "
                 "three-quarter front view, simple low poly 3D game asset, chunky shapes, flat colors, isolated on a "
                 "solid flat pure magenta background, no shadow, no floor, nothing else in the picture")
VENV_PY = ROOT / "tools" / "voice-venv" / "Scripts" / "python.exe"


def object_sprite(name, looks, out_png, cfg, seed=None, log=print, max_px=128):
    """Draw one object with the image model and cut it out -> RGBA sprite at out_png.
    Returns {"aspect": w/h, ...} or None (ComfyUI offline, no image model, or the cut-out failed)."""
    if not VENV_PY.exists():         # before drawing: a picture that can't be cut out is wasted GPU time (and it
        log("[props] tools/voice-venv not found - can't cut a sprite out, so nothing is drawn")   # pushed Ollama's
        return None                  # models out of the 12 GB GPU, so every next AI call reloaded them)
    st = status(cfg.get("url", "http://127.0.0.1:8666"))
    if not st["ok"] or not st["models"]:
        return None
    model = next((m for m in st["models"] if m["name"] == cfg.get("checkpoint")), None) or st["models"][0]
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    raw = out_png.with_name(out_png.stem + "_full.png")
    prompt = SPRITE_PROMPT.format(looks=looks or name, name=name.replace("_", " "))
    for attempt in range(4):                     # a new seed each time: most cut-outs fail on a bad picture, not on the idea
        raw.write_bytes(txt2img(st["url"], prompt, model, 512, 512, steps=int(cfg.get("steps", 20)),
                                cfg=float(cfg.get("cfg", 6.5)), seed=(seed or 1) + attempt * 7919))
        r = subprocess.run([str(VENV_PY), str(ROOT / "pipeline" / "sprite_cut.py"), str(raw), str(out_png), str(max_px)],
                           capture_output=True, text=True)
        try:
            info = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            info = {"error": (r.stderr or "no output")[-200:]}
        # a good cut-out covers a sensible part of the picture and isn't clipped by the frame
        if "error" not in info and 0.03 < info["coverage"] < 0.75 and not info.get("touches_edge"):
            return info
        log(f"[props] sprite for '{name}' didn't cut out cleanly ({info}) - " + ("retrying" if attempt < 3 else "giving up"))
    return None


SURFACE_PROMPTS = {   # what Required mode adds on top of picture props
    "floor": "seamless tileable texture of {x}, top-down view, flat even lighting, no perspective",
    "walls": "seamless tileable wallpaper pattern, {x}, flat, no perspective",
    "sky": "wide panoramic distant horizon, {x}, sky and far scenery only, no foreground, no people",
}
def colour_word(hex_colour):
    """A plain colour name the image model understands (it ignores hex codes). "" for anything that isn't #rrggbb."""
    h = str(hex_colour or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", h):
        return ""
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    light = (r + g + b) / 3
    if max(r, g, b) - min(r, g, b) < 28:
        return "white" if light > 200 else ("light grey" if light > 130 else "dark grey")
    if b >= r and b >= g:
        return "icy blue-white" if light > 190 else "blue"
    if g >= r and g >= b:
        return "green"
    if r >= g >= b:
        if g > 170 and r - b > 60:
            return "pale yellow"
        if r - b > 60 and light > 150:
            return "sandy beige"
        return "brown"
    return "pink" if b > g else "orange"


def floor_prompt(recipe):
    """The ground picture: the ground TYPE (snow, sand...), its COLOUR and the scene's own description. All three,
    so the picture can't come out as the wrong material (a snow path used to come out as sand)."""
    prompts = recipe.get("texture_prompts") or {}
    kind = SURFACE_DEFAULTS.get(recipe.get("floor"), "floor tiles")
    col = ((recipe.get("palette") or {}).get("floor") or [""])[0]
    word = colour_word(col)
    parts = [kind, f"{word} colour" if word else "", prompts.get("floor", "")]
    return ", ".join(p for p in parts if p)


SURFACE_DEFAULTS = {
    "planks": "wooden floor planks", "checker": "checkered floor tiles", "checker_small": "small kitchen floor tiles",
    "metal": "sci-fi metal floor panels", "grass": "grass and small flowers", "sand": "soft beach sand",
    "snow": "fresh snow", "road": "old asphalt with cracks", "stone": "rough stone slabs", "dirt": "dry dirt ground",
}


def texture_set(recipe, cfg, ffmpeg="ffmpeg", log=print, mode="auto"):
    """mode 'auto' (only when needed): just the picture props in the set (posters, signs, windows).
    mode 'required': always - picture props plus the floor, walls (inside) or a sky backdrop (outside);
    fails loudly if ComfyUI isn't reachable. Returns the list of slots made."""
    prompts = dict(recipe.get("texture_prompts") or {})
    wanted = {k: v for k, v in prompts.items() if any(p["kind"] == k for p in recipe.get("props", []))}
    if mode == "required" or "floor" in wanted:
        wanted["floor"] = SURFACE_PROMPTS["floor"].format(x=floor_prompt(recipe))
    if mode == "required":
        if recipe.get("indoor"):
            wanted["walls"] = SURFACE_PROMPTS["walls"].format(x=prompts.get("walls") or "soft pastel pattern")
        else:
            sky = prompts.get("sky") or f"{recipe.get('light', 'day')} sky over {recipe.get('description', 'distant hills')}"
            wanted["sky"] = SURFACE_PROMPTS["sky"].format(x=sky)
    if not wanted:
        log("[comfy] this set has no picture props - ComfyUI not needed")
        return []
    st = status(cfg.get("url", "http://127.0.0.1:8666"), max_age=0 if mode == "required" else 30)
    if not st["ok"]:
        if mode == "required":
            raise RuntimeError(f"ComfyUI is set to Required but isn't reachable: {st['error']}")
        log(f"[comfy] {st['error']} - using flat-colour art instead")
        return []
    url = st["url"]
    models = st["models"]
    model = next((m for m in models if m["name"] == cfg.get("checkpoint")), None) or (models[0] if models else None)
    if not model:
        log("[comfy] no image models found in ComfyUI - skipping textures")
        return []
    ckpt = model["name"]
    log(f"[comfy] using {url} ({model['kind']})")
    out_dir = ROOT / "sets" / recipe["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for slot, prompt in wanted.items():
        log(f"[comfy] generating '{slot}' with {ckpt}: {prompt}")
        w, h = (1024, 512) if slot == "sky" else (512, 512)
        png = txt2img(url, f"{prompt}, {cfg.get('style', 'low poly retro game texture, simple shapes')}", model,
                      width=w, height=h, steps=int(cfg.get("steps", 20)), cfg=float(cfg.get("cfg", 6.5)),
                      seed=recipe.get("seed"))
        raw = out_dir / f"{slot}_full.png"
        raw.write_bytes(png)
        small = out_dir / f"{slot}.png"      # tiny texture = N64 look
        size = int(cfg.get("texture_size", 128)) * (2 if slot == "sky" else 1)
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-vf",
                        f"scale={size}:-1:flags=area", str(small)], check=True)
        recipe.setdefault("textures", {})[slot] = f"sets/{recipe['id']}/{slot}.png"
        made.append(slot)
    return made
