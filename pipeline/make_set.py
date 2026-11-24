"""
Generate a brand-new set: Ollama designs it (if available), the generator lays it out, ComfyUI textures it
(depending on the mode), and Blender renders a preview.

    python pipeline/make_set.py [--idea "haunted bakery"] [--where inside|outside] [--light day|sunset|night]
                                [--ai auto|off] [--comfy required|auto|off] [--name "My Set"]

ComfyUI modes: required = always make textures (picture props + floor + walls/sky), fail if it's offline;
               auto     = only for picture props (posters, signs, windows), skip quietly if offline;
               off      = never.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comfy  # noqa: E402
import llm  # noqa: E402
import settings as S  # noqa: E402
import setgen  # noqa: E402
from run_episode import BLENDER_DEFAULT, tool  # noqa: E402
from set_preview import preview  # noqa: E402


def make_ambience(recipe, ollama):
    """The AI asked for a background sound we don't have: make it (once) as a new ambience slot."""
    import re
    import sfx as sfxlib
    idea = recipe.pop("ambience_idea")
    skip = {"a", "an", "the", "of", "with", "and", "in", "on", "from", "slow", "soft", "deep", "distant", "high",
            "low", "pitched", "loud", "quiet", "gentle", "faint", "constant", "occasional", "fast", "light", "heavy",
            "little", "small", "big", "steady", "random", "background", "sound", "sounds", "ambience", "noise"}
    words = [w for w in re.findall(r"[a-z]+", idea.lower()) if w not in skip and len(w) > 2]
    slot = "amb_" + "_".join(words[:2])[:24]
    if slot in sfxlib.all_slots():
        print(f"[sfx] using ambience '{slot}'")
        recipe["ambience"] = slot
        return
    try:
        sfxlib.add_custom_slot(slot, "Ambience: " + idea[:40], "", kind="ambience")
        sfxlib.generate_sound(slot, idea, ambience=True, ffmpeg=shutil.which("ffmpeg") or "ffmpeg", ollama=ollama)
        recipe["ambience"] = slot
        print(f"[sfx] new ambience '{slot}': {idea}")
    except Exception as exc:
        print(f"[sfx] couldn't make ambience '{idea}' ({exc}) - keeping {recipe['ambience']}")


ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / "tools" / "voice-venv" / "Scripts" / "python.exe"


def backup_set(sid):
    """Copy a set's files to sets/.trash/replaced-<time>/ before it is regenerated (nothing is lost on failure)."""
    import time as _t
    import shutil as _sh
    src = ROOT / "sets"
    dst = src / ".trash" / f"replaced-{sid}-{_t.strftime('%Y%m%d-%H%M%S')}"
    found = [src / f"{sid}.json", src / f"{sid}.png", src / sid]
    found = [p for p in found if p.exists()]
    if not found:
        raise SystemExit(f"[set] no set '{sid}' to regenerate")
    dst.mkdir(parents=True, exist_ok=True)
    for p in found:
        if p.is_dir():
            _sh.copytree(p, dst / p.name)
        else:
            _sh.copy2(p, dst / p.name)
    print(f"[set] backup of {sid} in {dst}", flush=True)


def _apply_overrides(plan, room=None, floor=None):
    """The regenerate popup's choices win over what the model picked (room size, ground)."""
    if room in ("small", "medium", "large"):
        plan["room"] = room
    if floor:
        plan["floor"] = floor
        plan["floor_forced"] = True


def _floor_for(hex_colour, plan_floor, outside=True):
    """The ground type that looks like this colour (the plan's choice is kept when nothing matches)."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    light = (r + g + b) / 3
    if outside:
        if g > r + 8 and g > b + 8:
            return "grass"
        if light > 200:
            return "snow"
        if r > g > b and r - b > 45 and light > 120:
            return "sand" if light > 150 else "dirt"
        if max(r, g, b) - min(r, g, b) < 28:
            return "stone" if light < 170 else plan_floor
    return plan_floor


def apply_picture_colours(plan, image, log=print):
    """Take the colours and ground straight from the picture (measured with Pillow, not guessed)."""
    if not VENV_PY.exists():
        log("[set] tools/voice-venv not found - keeping the model's colours")
        return
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "colours.json"
        r = subprocess.run([str(VENV_PY), str(ROOT / "pipeline" / "picture_colors.py"), str(image), str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            log("[set] could not measure the picture's colours - keeping the model's colours")
            return
        m = json.loads(out.read_text(encoding="utf-8-sig"))
    colours = dict(plan.get("colors") or {})
    colours.update({"sky": m["top"], "walls": m["middle"], "floor": m["bottom"], "floor2": m["bottom"],
                    "accent": m["palette"][0] if m["palette"] else colours.get("accent", "#ff8fb8")})
    plan["colors"] = colours
    outside = plan.get("where") != "inside"
    plan["floor"] = _floor_for(m["bottom"], plan.get("floor") or "grass", outside=outside)
    log(f"[set] colours from the picture: sky {m['top']}, middle {m['middle']}, ground {m['bottom']} -> "
        f"{plan['floor']} floor")


def create_set(idea="", where=None, light=None, seed=None, name=None, ai=None, comfy_mode=None, log=print,
               with_preview=True, image=None, keep_id=None, room=None, floor=None, theme=None):
    """Make and save a brand-new set; returns its recipe. where: inside / outside / air / None (AI decides).
    theme: auto / random / generated / a theme id (see setgen.theme_for).
    image: a picture to copy the place from (needs the vision model, see settings ollama.vision_model)."""
    from progress import report
    cfg = S.load_settings()
    recipe = None
    theme_id = theme
    if theme == "generated":                      # the AI writes a new theme for this place and saves it
        o = cfg["ollama"]
        log(f"[set] writing a new theme for: {idea or 'a place'}")
        try:
            t = llm.make_theme(o["url"], o["model"], idea or "a place")
            theme_id = t["id"]
            log(f"[set] new theme {t['id']}: {t['description']}")
        except Exception as exc:                  # Ollama offline or a bad answer: carry on with the words in the idea
            theme_id = "auto"
            log(f"[set] couldn't write a theme ({exc.__class__.__name__}: {str(exc)[:120]}) - picking one from the idea")
    if image and theme_id in (None, "auto"):     # a picture has its own layout: don't swap in a theme's props
        theme_id = "random"
    report(0.03, "Designing the set")
    if image:
        o = dict(cfg["ollama"])
        o["model"] = o.get("vision_model") or o["model"]
        log(f"[set] looking at the picture with {o['model']}")
        try:
            plan = llm.design_set(o["url"], o["model"], idea, where, light, image=image)
        except Exception as exc:                     # a picture needs the vision model: say so, don't guess
            raise SystemExit(f"[set] could not read the picture ({exc.__class__.__name__}: {str(exc)[:160]}). "
                             f"Is Ollama running and does {o['model']} support images?")
        log(f"[set] from the picture: {plan.get('name')} - {plan.get('description')}")
        apply_picture_colours(plan, image, log)
        _apply_overrides(plan, room, floor)
        plan["_idea"] = idea or plan.get("name", "")
        report(0.2, "Drawing new props" if plan.get("new_props") else "Laying out the set")
        cm = comfy_mode or cfg["comfy"]["mode"]
        recipe = setgen.generate_from_plan(plan, seed, where, light, ollama=o, log=log,
                                           comfy_cfg=cfg["comfy"] if cm != "off" else None, theme=theme_id)
        if recipe.get("ambience_idea"):
            make_ambience(recipe, o)
    use_ai = (ai or ("auto" if cfg["sets"]["use_ollama"] else "off")) == "auto"
    if use_ai and recipe is None:
        o = cfg["ollama"]
        try:
            log(f"[set] asking {o['model']} to design a set" + (f": {idea}" if idea else " (surprise)"))
            plan = llm.design_set(o["url"], o["model"], idea, where, light, temperature=1.0)
        except Exception as exc:
            plan = None
            log(f"[set] Ollama unavailable ({exc.__class__.__name__}: {str(exc)[:120]}) - rolling a random set instead")
        if plan:
            _apply_overrides(plan, room, floor)
            log(f"[set] AI idea: {plan.get('name')} - {plan.get('description')}")
            for fix in plan.get("_fixes") or []:
                log(f"[set] made it fit: {fix}")
            if plan.get("new_props"):
                log("[set] new props wanted: " + ", ".join(str(p.get("name")) for p in plan["new_props"]
                                                          if isinstance(p, dict) and p.get("name")))
            plan["_idea"] = idea
            report(0.2, "Drawing new props" if plan.get("new_props") else "Laying out the set")
            cm = comfy_mode or cfg["comfy"]["mode"]
            recipe = setgen.generate_from_plan(plan, seed, where, light, ollama=o, log=log,
                                               comfy_cfg=cfg["comfy"] if cm != "off" else None, theme=theme_id)
            if recipe.get("ambience_idea"):
                make_ambience(recipe, o)
    if recipe is None:
        recipe = (setgen.generate_air(None, seed, light, name, idea) if where == "air"
                  else setgen.generate_random(seed, where, light, name))
    elif name:
        recipe["name"] = name
    kinds = sorted({p["kind"] for p in recipe["props"]})
    kind = "in the air (" + recipe["air"] + ")" if recipe.get("air") else ("inside" if recipe["indoor"] else "outside")
    log(f"[set] {recipe['name']}: {kind}, {recipe['light']}, {recipe['floor']} floor, {len(recipe['props'])} props "
        f"({', '.join(kinds)})")
    log(f"[set] places: {', '.join(recipe['marks'])} | ambience: {recipe['ambience']}")
    if keep_id:                                  # a regenerated set keeps its name (its files are replaced)
        recipe["id"] = keep_id
    else:                                        # never overwrite another set that happens to get the same id
        import catalog
        base_id, n = recipe["id"], 2
        while (ROOT / "sets" / f"{recipe['id']}.json").exists() or recipe["id"] in catalog.SETS:
            recipe["id"], n = f"{base_id}_{n}", n + 1
    mode = comfy_mode or cfg["comfy"]["mode"]
    report(0.65, "Painting textures" if mode != "off" else "Saving")
    if mode != "off" and not recipe.get("air"):
        try:
            comfy.texture_set(recipe, cfg["comfy"], shutil.which("ffmpeg") or "ffmpeg", mode=mode)
        except Exception as exc:
            if mode == "required":
                raise
            log(f"[comfy] failed ({exc}) - continuing with flat-colour art")
    setgen.save(recipe)
    if with_preview:
        report(0.85, "Rendering the preview")
        preview(recipe["id"], tool("blender", "BLENDER", BLENDER_DEFAULT))
    report(1.0, "Done")
    return recipe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idea", default="")
    ap.add_argument("--where", choices=["inside", "outside", "air", "any"], default="any")
    ap.add_argument("--light", choices=["day", "sunset", "night", "any"], default="any")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--name")
    ap.add_argument("--ai", choices=["auto", "off"], default=None, help="let Ollama design the set")
    ap.add_argument("--comfy", default=None, choices=["required", "auto", "off"])
    ap.add_argument("--image", help="a picture to make the set from (the set copies the place it shows)")
    ap.add_argument("--replace", help="regenerate this set: its files are backed up, then replaced under the same id")
    ap.add_argument("--room", choices=["small", "medium", "large"])
    ap.add_argument("--floor", help="force the ground type (grass, sand, snow, road, stone, dirt...)")
    ap.add_argument("--theme", help="auto (from the words), random (free layout), generated (the AI writes a new theme), or a theme id")
    args = ap.parse_args()
    if args.replace:
        backup_set(args.replace)
    try:
        recipe = create_set(args.idea, None if args.where == "any" else args.where,
                            None if args.light == "any" else args.light, args.seed, args.name, args.ai, args.comfy,
                            image=args.image, keep_id=args.replace, room=args.room, floor=args.floor, theme=args.theme)
    except Exception as exc:
        sys.exit(f"[set] failed: {exc}")
    print(f"SET_ID={recipe['id']}")


if __name__ == "__main__":
    main()
