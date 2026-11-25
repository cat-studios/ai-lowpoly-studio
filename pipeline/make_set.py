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
import re
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


SET_PASS = 6          # vision score (1-10) for "this looks like the place"
SET_TRIES = 3         # the first design + up to two redesigns from the critique


def judge_picture(pic, place, ollama, log=print):
    """(score 1-10 or None, what's wrong) for a set picture - a BLIND test: the vision model says what place it sees
    and what's in it without being told what it should be (told the target, the small model scored two near-identical
    empty rooms 4/10 and 8/10), then the text model compares that with the idea."""
    import base64
    try:
        seen = llm.chat_json(ollama["url"], ollama.get("vision_model") or ollama["model"],
                             "Describe a simple low-poly 3D set from a cartoon game (ignore the small character in "
                             "the middle). Reply with JSON only: {\"place\": \"what kind of place this looks like, 2-6 "
                             "words\", \"things\": [\"the objects you can see\"], \"odd\": \"anything huge blocking the "
                             "view or absurdly sized (empty if none)\"}", "What place is this?", 0.1,
                             images=[base64.b64encode(Path(pic).read_bytes()).decode("ascii")])
        things = ", ".join(str(t) for t in (seen.get("things") or [])[:15] if isinstance(t, (str, int)))
        r = llm.chat_json(ollama["url"], ollama["model"],
                          "You compare what someone saw in a 3D set with the place it was meant to be. Reply with "
                          'JSON only: {"score": 1 to 10 (how clearly it reads as the meant place; 6 = clearly; 3 or '
                          'less if it reads as a different place or something blocks the view), "problem": "what '
                          'to add or remove so it reads as the meant place (empty if nothing)"}',
                          f"Meant to be: {place}\nThey saw: {seen.get('place')}\nThings in it: {things}\n"
                          f"Odd: {seen.get('odd') or '-'}", 0.1)
        log(f"[set] the picture model sees: {seen.get('place')} ({things[:120]})")
        return max(1, min(10, int(float(r.get("score", 0))))), str(r.get("problem") or "")[:300]
    except Exception as exc:                 # no vision model / Ollama: keep the set unchecked
        log(f"[set] look check skipped ({exc.__class__.__name__})")
        return None, ""


def set_look(recipe, place, ollama, log=print):
    """(score 1-10 or None, what's wrong): the set's quick preview (no textures yet), judged by judge_picture."""
    try:
        preview(recipe["id"], tool("blender", "BLENDER", BLENDER_DEFAULT))
    except BaseException as exc:             # preview() exits on failure
        log(f"[set] look check skipped - no preview ({exc.__class__.__name__})")
        return None, ""
    return judge_picture(ROOT / "sets" / f"{recipe['id']}.png", place, ollama, log)


def _norm_kind(k):
    return re.sub(r"[^a-z0-9]+", "_", str(k or "").lower()).strip("_").removeprefix("imp_").rstrip("s")


def fix_plan(plan, place, critique, ollama, log=print):
    """Turn the look check's critique into concrete changes to the plan: things to add (placed in the wide shot's
    view, "showcase") and things to remove. Re-asking the designer with the critique alone repeated the same set
    three times (a "haunted library" kept its chalkboard and got no bookshelves). Returns the kinds to remove."""
    try:
        r = llm.chat_json(ollama["url"], ollama["model"],
                          "You fix a 3D set from a reviewer's note. Reply with JSON only: "
                          '{"add": [{"kind": "short_name", "count": 1 to 4, "looks": "what it looks like"}], '
                          '"remove": ["kind", ...]} - add what the place is missing (the things that make it '
                          "recognisable), remove what doesn't belong. Use simple object names (bookshelf, desk, "
                          "candle, grave, cauldron).",
                          f"Place: {place}\nReviewer: {critique}", 0.2)
    except Exception as exc:
        log(f"[set] couldn't turn the critique into changes ({exc.__class__.__name__})")
        return set()
    remove = {_norm_kind(k) for k in (r.get("remove") or []) if isinstance(k, str)}
    adds = [a for a in (r.get("add") or []) if isinstance(a, dict) and a.get("kind")][:4]
    added = {_norm_kind(a["kind"]) for a in adds}          # the added ones replace the plan's own (imported) copies
    keep = lambda e, key="kind": _norm_kind(e.get(key)) not in remove | added      # noqa: E731
    plan["props"] = [e for e in plan.get("props") or [] if isinstance(e, dict) and keep(e)]
    plan["wall_pictures"] = [e for e in plan.get("wall_pictures") or [] if isinstance(e, dict) and keep(e)]
    plan["new_props"] = [e for e in plan.get("new_props") or [] if isinstance(e, dict) and keep(e, "name")]
    for a in adds:
        kind = re.sub(r"[^a-z0-9]+", "_", str(a["kind"]).lower()).strip("_")[:28]
        try:
            n = max(1, min(4, int(a.get("count") or 2)))
        except (TypeError, ValueError):
            n = 2
        plan["props"].append({"kind": kind, "count": n, "place": "showcase", "generate": True})
        if kind not in setgen.PROPS:          # not a built-in prop: the designer (or an imported model) makes it
            plan["new_props"].append({"name": kind, "looks": str(a.get("looks") or kind)[:120], "place": "showcase"})
    log(f"[set] fixing: add {', '.join(str(a['kind']) for a in adds) or '-'}; remove {', '.join(sorted(remove)) or '-'}")
    return remove


def _final_id(recipe, keep_id):
    """A regenerated set keeps its id; a new one never overwrites another (name slug + _2, _3...)."""
    if keep_id:
        return keep_id
    import catalog
    base_id, sid, n = recipe["id"], recipe["id"], 2
    while (ROOT / "sets" / f"{sid}.json").exists() or sid in catalog.SETS:
        sid, n = f"{base_id}_{n}", n + 1
    return sid


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
    checked_id, best, feedback = None, None, ""
    for attempt in range(1, SET_TRIES + 1):
        if not (use_ai and recipe is None):
            break
        o = cfg["ollama"]
        try:
            log(f"[set] asking {o['model']} to design a set" + (f": {idea}" if idea else " (surprise)")
                + (f" (try {attempt}, fixing: {feedback[:80]})" if feedback else ""))
            plan = llm.design_set(o["url"], o["model"], idea, where, light, temperature=1.0, feedback=feedback)
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
            remove = fix_plan(plan, idea or plan.get("name", ""), feedback, o, log) if feedback else set()
            report(0.2, "Drawing new props" if plan.get("new_props") else "Laying out the set")
            cm = comfy_mode or cfg["comfy"]["mode"]
            recipe = setgen.generate_from_plan(plan, seed, where, light, ollama=o, log=log,
                                               comfy_cfg=cfg["comfy"] if cm != "off" else None,
                                               theme="random" if feedback else theme_id)   # a theme would put them back
            if remove:
                recipe["props"] = [pr for pr in recipe["props"] if _norm_kind(pr.get("kind")) not in remove]
            # look check: a quick untextured preview, scored by the vision model; a fail -> redesign from the
            # critique (the palm trees on a military parade ground, a "haunted library" that was a cafe)
            if with_preview and cfg["sets"].get("look_check", True):
                place = idea or f"{plan.get('name', '')}: {plan.get('description', '')}"
                checked_id = checked_id or _final_id(recipe, keep_id)
                recipe["id"] = checked_id
                if name:
                    recipe["name"] = name
                setgen.save(recipe)
                report(0.4 + 0.1 * attempt, f"Checking the set looks right (try {attempt})")
                score, problem = set_look(recipe, place, o, log)
                if score is not None:
                    recipe["look_score"] = score
                    log(f"[set] looks like '{place[:60]}'? {score}/10" + (f" - {problem}" if problem else ""))
                if best is None or (score or 0) > best.get("look_score", 0):
                    best = recipe
                if score is not None and score < SET_PASS and attempt < SET_TRIES:
                    feedback, recipe = problem or "it doesn't look like this place", None
                    continue
            if best is not None:
                recipe = best                  # the best-looking try (also when none passed)
            if recipe.get("ambience_idea"):
                make_ambience(recipe, o)
        elif best is not None:                 # Ollama dropped out on a retry: keep the best earlier try
            recipe = best
        break
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
    recipe["id"] = checked_id or _final_id(recipe, keep_id)    # the look check already chose (and used) one
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
