"""
Animations made on the fly (phase 2-3): when a script asks for something she can't do yet ("[salute]",
"[do:yawn]"), Ollama writes it in the animlib format - built only from poses that were checked by eye - then a
quick Blender render (close-up + medium, small, no video) is shown to the vision model ("does this look like a
salute?"). Its critique goes back to the writer, up to three tries. The result is saved to assets/anims/<name>.json
with its check picture <name>.png, and every later video reuses it.

    python pipeline/animgen.py make salute "salutes like a soldier, hand to the forehead"
    python pipeline/animgen.py make shrug            (the description defaults to the name)

Without Ollama nothing is made and the caller falls back to an existing action.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import animlib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLENDER = os.environ.get("BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe")
PASS = 5                                        # vision score (1-10) that counts as "looks right" (forgiving)
ROOMY = {"palm_up_out", "point_side", "wave_up", "arm_up_high", "arm_forward", "reach_forward", "hand_by_face",
         "hands_on_head"}

GUIDE = (
    "You animate a small low-poly anime character for a short video. You build an animation ONLY from these "
    "ready-made poses (each was checked to look right):\n" + animlib.describe_for_ai() + "\n\n"
    "Arm poses: rest = hanging relaxed, slump = hanging tired, hand_to_chin = thinking, hand_at_mouth = forearm "
    "across the mouth, hand_over_eyes = hand over the eyes with the head bowed, hand_to_forehead = hand up at the side of the forehead (salute, wiping sweat, shading the eyes), arm_forward = arm thrown forward "
    "with an open hand, reach_forward = arm straight out in front, point_side = pointing out to her side, wave_up = "
    "forearm up beside the head, arm_up_high = fist up high, hand_by_face = hand up beside her face, fist_up = fist "
    "raised in front, across_body = forearm across the tummy, palm_up_out = forearm out with the palm up, "
    "hand_on_hip = hand on the hip, behind_back = arm behind her back. Two-arm poses (use them with both): "
    "hands_on_head = hands behind the head, elbows out, praying_hands = hands together under the chin, "
    "arms_crossed = forearms crossed over the chest, cover_ears = hands over her ears, hug_self = hugging "
    "herself, hands on the other shoulders. R = her right arm, L = her left arm, both = "
    "both arms. Head/body poses are added on top; leave them out when not needed.\n"
    "Reply with JSON only, in this format:\n"
    '{"name": "...", "description": "...", "length": seconds, "loop": true or false, '
    '"keys": [{"t": 0.0, "R": "rest", "L": "rest"}, {"t": 0.4, "both": "palm_up_out", "head": "head_tilt"}], '
    '"shake": [{"channel": "turn", "amount": 0.1, "speed": 6}]}\n'
    "Rules: 3 to 7 keys; t in seconds, going up; length 0.8 to 2.5 seconds. A one-off gesture starts and ends at "
    "rest; something repeated (laughing, shivering, waving) sets loop true and ends where it starts. shake is "
    "optional (channels: nod, tilt, turn, lean, sway, shift, bob; amount up to 0.3) for trembling or head shakes. "
    "A key that leaves out R or L keeps that arm where it was.\n"
    "Examples:\n" + "\n".join(json.dumps(dict(a, name=n[2:])) for n, a in animlib.BUILTIN.items())
)

IS_ACTION = ("Decide if a word from a script's stage directions is something a character can act out with her "
             "body (a gesture, pose or movement - salute, yawn, shrug, bow, tiptoe, flex) or not (a mood, a look, "
             "a thing, an adjective, or something only the FACE does - messy, excited, pink, table, smile, "
             "frown, wink, blush). Reply with JSON only: "
             '{"action": true or false, "description": "what her body does, in one short sentence"}')


def _ollama():
    import settings as S
    return S.load_settings().get("ollama")


def is_action(word, line="", ollama=None, log=print):
    """(True, description) when the word is a body action she can play, else (False, "")."""
    import llm
    o = ollama or _ollama()
    try:
        r = llm.chat_json(o["url"], o["model"], IS_ACTION, f"Word: {word}\nThe line: {line}", temperature=0.1)
        return bool(r.get("action")), str(r.get("description") or "")[:160]
    except Exception as exc:
        log(f"[anims] couldn't ask about '{word}' ({exc.__class__.__name__})")
        return False, ""


def write(name, description, ollama, feedback="", log=print):
    """Ollama writes the animation; format errors go back to it (up to 3 times). Returns a valid animation."""
    import llm
    user = f"Animation name: {name}\nWhat she does: {description}"
    if feedback:
        user += f"\nYour last try was checked and was wrong: {feedback}\nFix that."
    err = ""
    for _ in range(3):
        try:
            raw = llm.chat_json(ollama["url"], ollama["model"], GUIDE, user + (f"\nFormat error: {err}" if err else ""),
                                temperature=0.4)
            a = animlib.validate(dict(raw, name=name))
            a["description"] = a["description"] or description
            return a
        except Exception as exc:
            err = str(exc)[:200]
            log(f"[anims] '{name}': {err}")
    raise RuntimeError(f"no usable animation for '{name}' ({err})")


def check_render(a, log=print):
    """Render the candidate (close-up + medium) straight in Blender and return a strip picture of 4 moments."""
    import run_episode as R
    import settings as S
    cfg = S.load_settings()
    tmp = Path(tempfile.mkdtemp(prefix="animcheck_"))
    try:
        cand = tmp / "candidate.json"
        cand.write_text(json.dumps(a), encoding="utf-8")
        ep = {"title": "", "set": "cafe", "start": "center", "music": "", "ambience": "", "shots": [], "cast": {},
              "co_stars": [], "_language": "en", "audio_lead": 0.0, "fps": 12, "render_res": [270, 480]}
        ep["character"] = R.resolve_character(ep, cfg)       # her real model, not the stand-in body
        dur = round(a["length"] + 0.3, 2)
        ep["shots"] = [{"action": a["name"], "camera": c, "move": "static", "expression": "neutral",
                        "duration": dur, "line": "", "talk": 0.0, "lead": 0.0} for c in ("closeup", "medium")]
        (tmp / "ep.json").write_text(json.dumps(ep, default=str), encoding="utf-8")
        frames = tmp / "frames"
        frames.mkdir()
        env = dict(os.environ, ANIMLIB_EXTRA=str(cand))
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(ROOT / "pipeline" / "blender_build.py"),
                            "--", str(tmp / "ep.json"), str(frames), str(tmp / "scene.blend")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        pngs = sorted(frames.glob("f_*.png"))
        if r.returncode != 0 or not pngs:
            raise RuntimeError("check render failed: " + (r.stderr or r.stdout or "")[-300:])
        n = len(pngs) // 2
        pick = [pngs[min(len(pngs) - 1, int(n * f))] for f in (0.35, 0.7)] + \
               [pngs[min(len(pngs) - 1, n + int(n * f))] for f in (0.35, 0.7)]
        strip = tmp / "strip.png"
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for p in pick:
            cmd += ["-i", str(p)]
        cmd += ["-filter_complex", "".join(f"[{i}]" for i in range(len(pick))) + f"hstack={len(pick)}", str(strip)]
        subprocess.run(cmd, check=True)
        keep = Path(tempfile.gettempdir()) / f"animcheck_{a['name']}_{int(time.time())}.png"
        shutil.copyfile(strip, keep)
        return keep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


GIF_SIZE = (180, 320)      # the Assets card's animated preview (the user, 2026-11-28: "a gif of the animation")
GIF_FPS = 12


def preview_gif(a, log=print):
    """A looping GIF of one animation (medium camera, her real model, the animation played twice) ->
    assets/anims/<name>.gif. Returns the path or None."""
    import run_episode as R
    import settings as S
    cfg = S.load_settings()
    tmp = Path(tempfile.mkdtemp(prefix="animgif_"))
    try:
        cand = tmp / "candidate.json"
        cand.write_text(json.dumps(a), encoding="utf-8")
        ep = {"title": "", "set": "cafe", "start": "center", "music": "", "ambience": "", "shots": [], "cast": {},
              "co_stars": [], "_language": "en", "audio_lead": 0.0, "fps": GIF_FPS, "render_res": [216, 384]}
        ep["character"] = R.resolve_character(ep, cfg)
        dur = round(float(a.get("length") or 1.5) * (2 if a.get("loop") else 1) + 0.4, 2)
        ep["shots"] = [{"action": a["name"], "camera": "medium", "move": "static", "expression": "neutral",
                        "duration": dur, "line": "", "talk": 0.0, "lead": 0.0}]
        (tmp / "ep.json").write_text(json.dumps(ep, default=str), encoding="utf-8")
        frames = tmp / "frames"
        frames.mkdir()
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(ROOT / "pipeline" / "blender_build.py"),
                            "--", str(tmp / "ep.json"), str(frames), str(tmp / "scene.blend")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, ANIMLIB_EXTRA=str(cand)))
        if r.returncode != 0 or not any(frames.glob("f_*.png")):
            log(f"[anims] no GIF for '{a['name']}': the render failed")
            return None
        out = animlib.LIB / f"{a['name']}.gif"
        w, h = GIF_SIZE
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(GIF_FPS), "-i", str(frames / "f_%04d.png"),
                        "-filter_complex", f"scale={w}:{h}:flags=neighbor,split[a][b];[a]palettegen=max_colors=96[p];"
                                           f"[b][p]paletteuse=dither=bayer:bayer_scale=3",
                        "-loop", "0", str(out)], check=True)
        log(f"[anims] GIF preview -> {out.name}")
        return out
    except Exception as exc:
        log(f"[anims] no GIF for '{a.get('name')}': {exc}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make_gifs(redo=False, log=print):
    """GIF previews for every animation in the library that has none (or all of them with redo)."""
    from progress import report
    lib = animlib.library()
    todo = [a for n, a in sorted(lib.items()) if redo or not (animlib.LIB / f"{n}.gif").exists()]
    log(f"[anims] {len(todo)} GIF preview(s) to make")
    for i, a in enumerate(todo):
        report(0.02 + 0.96 * i / max(1, len(todo)), f"GIF {i + 1}/{len(todo)}: {a['name']}")
        preview_gif(a, log)
    report(1.0, "Done")


def set_verified(name, on):
    """Your own say over the AI's score (Assets -> Animations -> ✅ Verified): a verified animation is used whatever
    its score; un-verifying puts back what the score said."""
    lib = animlib.library()
    if name not in lib:
        raise KeyError(name)
    a = dict(lib[name])
    if on:
        a.update(verified=True, checked=True)
    else:
        a.pop("verified", None)
        a["checked"] = (a.get("score") or 0) >= PASS if a.get("score") is not None else None
    return animlib.save(a)


def rename(old, new):
    """Rename an animation = the word scripts use (the user, 2026-11-28). Its files move to the new name and the old
    word is kept in "aliases", so scripts and videos made before still play it (animlib.aliases)."""
    import catalog
    old, new = animlib.slug(old), animlib.slug(new)
    lib = animlib.library()
    if old not in lib:
        raise KeyError(old)
    if not new or new == old:
        raise ValueError("give it a new name (one or two words)")
    if new in lib or new in catalog.ANIMS or new in animlib.aliases() or new in animlib.NOT_ACTIONS:
        raise ValueError(f"'{new}' is already used by another animation")
    if old in animlib.BUILTIN:
        raise ValueError("the built-in examples can't be renamed")
    a = dict(lib[old], name=new)
    a["aliases"] = sorted(set(a.get("aliases") or []) | {old})
    animlib.save(a)
    for ext in (".png", ".gif"):
        f = animlib.LIB / f"{old}{ext}"
        if f.exists():
            f.replace(animlib.LIB / f"{new}{ext}")
    (animlib.LIB / f"{old}.json").unlink()            # its content now lives in <new>.json (same data, new name)
    return a


def vision_check(strip, name, description, ollama, log=print):
    """(score 1-10 or None, problem): the vision model rates the strip (close-up x2, medium x2, in time order).
    A score, not yes/no: the small vision model turned down every try that wasn't textbook-perfect."""
    import llm
    model = ollama.get("vision_model") or ollama["model"]
    b64 = base64.b64encode(Path(strip).read_bytes()).decode("ascii")
    try:
        r = llm.chat_json(ollama["url"], model,
                          "You check animations of a small anime character. The picture shows 4 moments of one "
                          "animation side by side (two close-up, two from further away). Judge ONLY her body pose "
                          "and arms, and be fair: it is a simple low-poly character, so a clear, recognisable pose "
                          "is enough. Reply with JSON only: "
                          '{"score": 1 to 10 (how well it shows the action; 6 = clearly recognisable), '
                          '"problem": "the main thing to change about her arms/head (empty if none)"}',
                          f"It should show: {name.replace('_', ' ')} - {description}", 0.1, images=[b64])
        sc = max(1, min(10, int(float(r.get("score", 0)))))
        return sc, str(r.get("problem") or "")[:300]
    except Exception as exc:
        log(f"[anims] vision check unavailable ({exc.__class__.__name__}) - kept unchecked")
        return None, ""


def make(name, description="", ollama=None, log=print, tries=2, check=True):
    """Write, render-check and save an animation. Returns it (also when never confirmed: "checked": false)."""
    name = animlib.slug(name)
    if not name:
        raise ValueError("an animation needs a name")
    o = ollama or _ollama()
    if not o:
        raise RuntimeError("Ollama is off - animations can't be made")
    description = description or name.replace("_", " ")
    t0, feedback, best, best_strip = time.time(), "", None, None
    for attempt in range(1, tries + 1):
        a = write(name, description, o, feedback, log)
        a.update(by="ai", created=time.time(), request=description,
                 needs_room=any(k.get(s) in ROOMY for k in a["keys"] for s in ("R", "L")))
        if not check:
            best = dict(a, checked=None)
            break
        strip = check_render(a, log)
        score, problem = vision_check(strip, name, description, o, log)
        if score is None:                            # no vision model: keep it, marked unchecked
            best, best_strip = dict(a, checked=None), strip
            break
        log(f"[anims] '{name}' try {attempt}: {score}/10" + (f" - {problem}" if problem else ""))
        if best is None or score > best.get("score", 0):  # the best try is kept, not the last
            best, best_strip = dict(a, checked=score >= PASS, score=score, problem=problem), strip
        if score >= PASS:
            break
        feedback = problem
    saved = animlib.save(best)
    if check and best_strip:
        animlib.LIB.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(best_strip, animlib.LIB / f"{name}.png")
    log(f"[anims] made '{name}' in {time.time() - t0:.0f}s" + ("" if best.get("checked") else " (not confirmed)"))
    if check:
        preview_gif(saved, log)                    # the Assets card's moving preview
    return dict(saved, checked=best.get("checked"), problem=best.get("problem", ""))


def ensure(word, line="", log=print):
    """For a script: the animation's name if it exists or could be made, else None (not a body action / no AI)."""
    name = animlib.slug(word)
    name = animlib.aliases().get(name, name)      # a renamed animation's old word
    if not name or name in animlib.NOT_ACTIONS:
        return None
    import catalog
    lib = animlib.library()
    if name in lib and lib[name].get("checked") is False and (lib[name].get("score") or 0) < 5:
        return None                               # made before but it didn't look right: her mood's action instead
    if name in catalog.ANIMS or name in lib:
        return name
    nots = animlib.LIB / ".not_actions.json"      # words already found not to be actions ("messy", "pink")
    try:
        known_not = set(json.loads(nots.read_text(encoding="utf-8"))) if nots.exists() else set()
    except Exception:
        known_not = set()
    if name in known_not:
        return None
    try:
        o = _ollama()
        ok, desc = is_action(word, line, o, log)
        if not ok:
            log(f"[anims] '{word}' isn't something she can act out - using her mood's action")
            animlib.LIB.mkdir(parents=True, exist_ok=True)
            nots.write_text(json.dumps(sorted(known_not | {name})), encoding="utf-8")
            return None
        made = make(name, desc or word, o, log)
        if made.get("checked") is False and (made.get("score") or 0) < 5:
            log(f"[anims] '{name}' doesn't look right yet ({made.get('score')}/10) - using her mood's action")
            return None
        return name
    except Exception as exc:
        log(f"[anims] couldn't make '{word}' ({exc.__class__.__name__}: {str(exc)[:120]})")
        return None


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "make":
        from progress import report
        report(0.1, f"Making the animation '{sys.argv[2]}'")
        out = make(sys.argv[2], " ".join(sys.argv[3:]))
        print(f"ANIM={out['name']} checked={out.get('checked')}", flush=True)
    elif len(sys.argv) >= 2 and sys.argv[1] == "gifs":          # python animgen.py gifs [--redo]
        make_gifs(redo="--redo" in sys.argv)
    else:
        print(__doc__)
