"""Local 3D models from a drawing (the user, 2026-11-27: "generate 3D models with a local option").

ComfyUI does it all on this PC, with nodes it ships with (no add-ons):
  1. Z-Image draws the object (one thing, centred, plain background) - like a sprite, but for 3D
  2. TRELLIS 2 (Comfy-Org's repackage: trellis_2_int8_convrot + dino_v3 + its shape / texture VAEs, BiRefNet to cut
     the background) turns the drawing into a 3D shape and its colours
  3. the mesh is simplified to a few thousand faces and its corners painted with the colours (flat, N64-like),
     saved as a GLB
The GLB then joins the imported-model library as the "Made 3D" pack (imported.add_made), so it's matched, sized,
pictured, look-checked and reused like any imported model. Nothing here is required: no ComfyUI / no TRELLIS files
= None, and the prop maker carries on with its own shapes.
"""
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import comfy

FILES = {"unet": "trellis_2_int8_convrot.safetensors", "clip_vision": "dino_v3_L_naf_fp32.safetensors",
         "shape_vae": "trellis_2_shape_vae_bf16.safetensors", "texture_vae": "trellis_2_texture_vae_bf16.safetensors",
         "bg": "birefnet.safetensors"}
DRAW_PROMPT = ("{looks}, a single {name}, the whole object fully visible and centered with space around it, "
               "three-quarter front view, simple chunky low poly 3D game asset, flat bright colors, solid shapes, "
               "plain white background, no shadow, no floor, nothing else in the picture, no text")
FACES = 3000          # low-poly: the mesh is simplified to about this many faces (the studio's props are a few hundred)
TIMEOUT = 900
REMESH = 160         # voxel grid of the clean-up remesh (256 ~ 100k faces): enough for a few thousand faces


def missing_files(url):
    """The TRELLIS 2 files ComfyUI doesn't have yet ([] = ready)."""
    have = set()
    for node, field in (("UNETLoader", "unet_name"), ("CLIPVisionLoader", "clip_name"), ("VAELoader", "vae_name"),
                        ("LoadBackgroundRemovalModel", "bg_removal_name")):
        have |= set(comfy._options(url, node, field) or [])
    return [f for f in FILES.values() if f not in have]


def ready(cfg):
    """(ComfyUI url, "") when local 3D can run, else (None, why)."""
    url = comfy.find_server((cfg or {}).get("url", "http://127.0.0.1:8666"))
    if not url:
        return None, "ComfyUI isn't running"
    miss = missing_files(url)
    if miss:
        return None, "ComfyUI is missing the TRELLIS 2 files: " + ", ".join(miss)
    return url, ""


def _upload(url, png_bytes, name):
    """POST /upload/image -> the name ComfyUI stored it under."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + png_bytes + \
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url.rstrip("/") + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read().decode("utf-8"))
    return (out.get("subfolder") + "/" if out.get("subfolder") else "") + out["name"]


def graph(image_name, seed, prefix, faces=FACES, upsample=False):
    """ComfyUI's own "Pixal3D & TRELLIS.2: Image to Model" template, TRELLIS 2 path only, ending in a simplified
    mesh painted with the voxel colours (instead of 4K PBR textures + normal / AO bakes) -> SaveGLB."""
    S = lambda n, k, steps, cfg, sch: {"class_type": "KSampler", "inputs": {  # noqa: E731
        "model": n, "seed": seed + k, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": sch,
        "positive": None, "negative": None, "latent_image": None, "denoise": 1}}
    g = {
        "img": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "bgm": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": FILES["bg"]}},
        "bg": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["bgm", 0], "image": ["img", 0]}},
        "crop": {"class_type": "ImageCropToMask", "inputs": {"images": ["img", 0], "masks": ["bg", 0], "width": 1024,
                                                               "height": 1024, "pad_factor": 1.0, "grow_mask": 0,
                                                               "background": "#000000"}},
        "cv": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": FILES["clip_vision"]}},
        "cond": {"class_type": "Trellis2Conditioning", "inputs": {"clip_vision_model": ["cv", 0], "image": ["crop", 0]}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": FILES["unet"], "weight_dtype": "default"}},
        "svae": {"class_type": "VAELoader", "inputs": {"vae_name": FILES["shape_vae"]}},
        "tvae": {"class_type": "VAELoader", "inputs": {"vae_name": FILES["texture_vae"]}},
        # structure (the template's CFG tweaks, kept "to match the original default pipeline behaviour")
        "m1a": {"class_type": "CFGOverride", "inputs": {"model": ["unet", 0], "cfg": 1, "start_percent": 0.667,
                                                        "end_percent": 1}},
        "m1b": {"class_type": "RescaleCFG", "inputs": {"model": ["m1a", 0], "multiplier": 0.7}},
        "m1": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["m1b", 0], "shift": 5}},
        "m2a": {"class_type": "CFGOverride", "inputs": {"model": ["unet", 0], "cfg": 1, "start_percent": 0.769,
                                                        "end_percent": 1}},
        "m2": {"class_type": "RescaleCFG", "inputs": {"model": ["m2a", 0], "multiplier": 0.5}},
        "empty": {"class_type": "EmptyTrellis2LatentStructure", "inputs": {"batch_size": 1}},
        "k_struct": S(["m1", 0], 0, 12, 7.5, "normal"),
        "struct": {"class_type": "VaeDecodeStructureTrellis2", "inputs": {"samples": ["k_struct", 0],
                                                                          "vae": ["svae", 0], "resolution": "32"}},
        "shape_stage": {"class_type": "Trellis2ShapeStage", "inputs": {"positive": ["cond", 0], "negative": ["cond", 1],
                                                                       "voxel": ["struct", 0]}},
        "k_shape": S(["m2", 0], 1, 20, 7.5, "normal"),
        "up_stage": {"class_type": "Trellis2UpsampleStage", "inputs": {"positive": ["shape_stage", 0],
                                                                       "negative": ["shape_stage", 1],
                                                                       "shape_latent": ["k_shape", 0], "vae": ["svae", 0],
                                                                       "target_resolution": 1024}},
        "k_up": S(["m2", 0], 2, 12, 7.5, "simple"),
        "shape": {"class_type": "VaeDecodeShapeTrellis", "inputs": {"samples": ["k_up", 0], "vae": ["svae", 0]}},
        "tex_stage": {"class_type": "Trellis2TextureStage", "inputs": {"positive": ["up_stage", 0],
                                                                       "negative": ["up_stage", 1],
                                                                       "shape_latent": ["k_up", 0]}},
        "k_tex": S(["unet", 0], 3, 12, 1, "normal"),
        "colours": {"class_type": "VaeDecodeTextureTrellis", "inputs": {"samples": ["k_tex", 0], "vae": ["tvae", 0],
                                                                         "shape_subdivides": ["shape", 1]}},
        # a closed, clean surface first: simplified straight from TRELLIS's raw mesh it fell apart into loose
        # triangles (the first duck); the template remeshes before it decimates too
        "clean": {"class_type": "RemeshMesh", "inputs": {"mesh": ["shape", 0], "resolution": REMESH,
                                                          "sign_mode": "solid", "sign_mode.fill": 20.0,
                                                          "sign_mode.qef": False, "band": 1.0, "project_back": 0.0,
                                                          "fix_poles": False, "smooth_iters": 2,
                                                          "drop_small_components": 0.01,
                                                          "precluster_max_verts": 20000000}},
        "low": {"class_type": "DecimateMesh", "inputs": {"mesh": ["clean", 0], "target_face_count": int(faces),
                                                          "placement_mode": "midpoint"}},
        "paint": {"class_type": "PaintMesh", "inputs": {"mesh": ["low", 0], "voxel_colors": ["colours", 0]}},
        "save": {"class_type": "SaveGLB", "inputs": {"mesh": ["paint", 0], "filename_prefix": prefix}},
    }
    g["k_struct"]["inputs"].update(positive=["cond", 0], negative=["cond", 1], latent_image=["empty", 0])
    g["k_shape"]["inputs"].update(positive=["shape_stage", 0], negative=["shape_stage", 1], latent_image=["shape_stage", 2])
    g["k_up"]["inputs"].update(positive=["up_stage", 0], negative=["up_stage", 1], latent_image=["up_stage", 2])
    g["k_tex"]["inputs"].update(positive=["tex_stage", 0], negative=["tex_stage", 1], latent_image=["tex_stage", 2])
    if not upsample:          # the 512-voxel shape is plenty for a few thousand faces: skip the 1024 upsample pass
        for k in ("up_stage", "k_up"):
            g.pop(k)
        g["shape"]["inputs"]["samples"] = ["k_shape", 0]
        g["tex_stage"]["inputs"].update(positive=["shape_stage", 0], negative=["shape_stage", 1],
                                        shape_latent=["k_shape", 0])
    return g


def _find_file(outputs, ext=".glb"):
    """The first output file with this ending in a /history entry (SaveGLB's output key isn't "images")."""
    for node in (outputs or {}).values():
        for v in node.values() if isinstance(node, dict) else []:
            for f in v if isinstance(v, list) else []:
                if isinstance(f, dict) and str(f.get("filename", "")).lower().endswith(ext):
                    return f
    return None


def run(url, png_bytes, out_glb, seed=None, faces=FACES, log=print, timeout=TIMEOUT):
    """A drawing (PNG bytes) -> out_glb through TRELLIS 2. Returns out_glb, or raises."""
    seed = seed if seed is not None else int(time.time()) % 100000
    name = _upload(url, png_bytes, f"lowpoly_{uuid.uuid4().hex[:8]}.png")
    pid = comfy._json(url, "/prompt", {"prompt": graph(name, seed, f"3d/lowpoly_studio/{Path(out_glb).stem}", faces),
                                       "client_id": uuid.uuid4().hex}, timeout=30)["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = comfy._json(url, f"/history/{pid}", timeout=30)
        if pid in hist:
            st = hist[pid].get("status", {})
            if st.get("status_str") == "error":
                msg = next((m[1].get("exception_message", "") for m in st.get("messages", [])
                            if m and m[0] == "execution_error"), "")
                raise RuntimeError(f"ComfyUI couldn't make the 3D model: {str(msg)[:200]}")
            f = _find_file(hist[pid].get("outputs"))
            if f:
                q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                            "type": f.get("type", "output")})
                Path(out_glb).parent.mkdir(parents=True, exist_ok=True)
                Path(out_glb).write_bytes(comfy._get(url, f"/view?{q}", timeout=120))
                log(f"[3d] made a 3D model in {time.time() - t0:.0f}s -> {Path(out_glb).name}")
                return out_glb
            if st.get("completed"):
                raise RuntimeError("ComfyUI finished but saved no GLB")
        time.sleep(2.0)
    raise TimeoutError("TRELLIS 2 took too long")


def draw(url, name, looks, cfg, seed=None):
    """The object drawn by Z-Image (the same image model as the sprites), 1024 px, plain background."""
    st = comfy.status(url)
    if not st.get("ok") or not st.get("models"):
        raise RuntimeError("ComfyUI has no image model to draw with")
    model = next((m for m in st["models"] if m["name"] == (cfg or {}).get("checkpoint")), None) or st["models"][0]
    prompt = DRAW_PROMPT.format(looks=looks or name.replace("_", " "), name=name.replace("_", " "))
    return comfy.txt2img(url, prompt, model, 1024, 1024, steps=int((cfg or {}).get("steps", 20)),
                         cfg=float((cfg or {}).get("cfg", 6.5)), seed=seed)


def make(kind, looks, comfy_cfg, out_glb, seed=None, faces=FACES, log=print):
    """Draw it, make it 3D. Returns the GLB path, or None (not set up / failed - the caller makes its own shape)."""
    url, why = ready(comfy_cfg)
    if not url:
        log(f"[3d] no local 3D model for '{kind}': {why}")
        return None
    try:
        png = draw(url, kind, looks, comfy_cfg, seed)
        Path(out_glb).parent.mkdir(parents=True, exist_ok=True)
        Path(out_glb).with_suffix(".drawing.png").write_bytes(png)
        return run(url, png, out_glb, seed, faces, log)
    except Exception as exc:
        log(f"[3d] couldn't make a 3D model of '{kind}' ({exc.__class__.__name__}: {str(exc)[:160]}) - "
            "making it from shapes instead")
        return None


if __name__ == "__main__":                       # python pipeline/model3d.py "rubber duck" "a yellow rubber duck" out.glb
    import sys
    import settings as S
    print(make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", S.load_settings().get("comfy"),
               sys.argv[3] if len(sys.argv) > 3 else f"{sys.argv[1].replace(' ', '_')}.glb"))
