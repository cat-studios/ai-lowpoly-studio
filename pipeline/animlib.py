"""
Animations as data: timed keyframes that name poses from a small vocabulary of poses checked by eye in renders.
Phase 1 of "animations made on the fly": the format, the pose vocabulary and the sampler. blender_build plays
every animation in the library like a built-in one (ANIMS), with the usual breathing, blinks and smoothing on top.
The AI generator (later) writes this same format, so it can only combine poses that are known to look right -
raw joint angles guessed by a model (or by hand) read as salutes and waves (see the facepalm notes in CLAUDE.md).

An animation (assets/anims/<name>.json, or BUILTIN below):
    {"name": "shrug", "description": "...", "length": 1.2, "loop": true,
     "keys": [{"t": 0.0, "R": "rest", "L": "rest"},
              {"t": 0.35, "R": "palm_up_out", "L": "palm_up_out", "head": "head_tilt", "body": "shoulders_up"}],
     "shake": [{"channel": "turn", "amount": 0.1, "speed": 6}]}
 - t in seconds from the start (looped animations repeat every "length" seconds)
 - "R"/"L": an ARM pose for that arm (missing = it keeps the last key's pose; "rest" = hanging relaxed)
 - "head"/"body": a HEAD / BODY pose (missing = neutral); "both": an ARM pose for both arms
 - between keys every value eases smoothly; "shake" adds a small wobble (trembling, head shakes)
Pose channels (blender_build pose dict): arm = swing forward (< 0 = forward), raise = lift out to the side,
rot = twist the upper arm (< 0 turns the bent forearm in across the body, > 0 up/out), elbow = bend (0..2.7, it
only bends forward). The same values work for both arms (blender_build mirrors them). Head/body are added.
"""
import json
import os
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "assets" / "anims"
# words from the AI's brackets that are never body actions - the maker turned them into poses ("nya", "fast",
# "moon", "shine", "closer"...) and then every [nya] made her do that pose (production, 2026-11-27). Never made,
# and animations already saved under these names aren't used (they stay on Assets -> Animations to delete).
NOT_ACTIONS = set("""nya meow mew purr fast faster slow slowly quick quickly closer closerup closer_up close angle shot
moon sun star stars shine shining glow glowing sparkle sparkly seed noodle hold holding omega sideside side_side loop
boom bang zoom blink blinking drool drooling intense sound micro mid goofy dreamy eager sinister celebratory spoiler
drop_spoiler""".split())

# ---------------------------------------------------------------------------- the pose vocabulary
# arm poses: (arm, raise, rot, elbow) - most taken from the built-in animations that render well
ARM = {
    "rest":            (-0.06, 0.16, 0.0, 0.12),    # hanging relaxed (default pose)
    "slump":           (-0.2, 0.08, 0.0, 0.45),     # hanging, a little bent (tired, defeated)
    "hand_to_chin":    (-1.15, 0.22, 0.0, 2.1),     # think
    "hand_at_mouth":   (-2.3, 0.0, -1.6, 2.4),      # forearm across the mouth (sneeze, oops, giggle, gasp)
    "hand_over_eyes":  (-2.3, 0.0, -1.6, 2.4),      # = hand_at_mouth with "head_down" (facepalm, crying, peek)
    "hand_to_forehead": (-0.6, 1.0, 0.6, 2.4),     # fingertips at the brow, elbow out (checked: reads as a salute) - hand at the temple/forehead (salute, "phew", shading the eyes)
    "arm_forward":     (-1.15, 0.5, 0.2, 0.35),     # thrown forward, open hand (blow kiss, "here!", offering)
    "reach_forward":   (-1.4, 0.2, 0.0, 0.15),      # straight out in front (grab, press, push)
    "point_side":      (-0.7, 1.0, 0.25, 0.22),     # pointing out to her side
    "wave_up":         (-0.25, 1.25, 1.45, 1.35),   # forearm up beside the head (wave, "hi!", swear an oath)
    "arm_up_high":     (-0.2, 1.75, 1.3, 0.7),      # fist pumped up high (celebrate, cheer)
    "hand_by_face":    (-0.5, 0.85, 1.1, 1.9),      # hand up beside the face (surprised, scared, "eek", "hands up")
    "fist_up":         (-0.55, 0.5, 0.0, 1.4),      # fist raised in front (angry, determined, "let's go")
    "across_body":     (-0.55, 0.05, 0.0, 1.2),     # forearm across the tummy (holding the other elbow, shy)
    "palm_up_out":     (-0.5, 0.55, 0.9, 1.3),      # forearm out, palm up (shrug, "who knows?", presenting)
    "hand_on_hip":     (0.35, 0.55, -0.9, 1.7),     # hand on the hip (sassy, impatient, proud)
    "behind_back":     (0.45, 0.1, 0.0, 0.6),       # arm behind her back (shy, innocent, hiding something)
    # both arms (use "both"), each picked from rendered variants (2026-11-25):
    "hands_on_head":   (-0.45, 1.9, 1.7, 2.4),      # hands behind/on the head, elbows out (relaxed, "oh no", stunned)
    "praying_hands":   (-0.75, 0.15, -0.5, 2.0),    # hands together under the chin (please, pleading, hoping)
    "arms_crossed":    (-1.0, 0.15, -1.3, 1.9),     # forearms crossed tight over the chest (grumpy, "no", stubborn)
    "cover_ears":      (-0.15, 1.0, 1.0, 2.6),      # hands over the ears (too loud, "la la la", not listening)
    "hug_self":        (-0.95, 0.55, -1.0, 2.1),    # hands to the other shoulders (cold, scared, cosy, shy)
}
HEAD = {   # added to whatever the head is doing (nod > 0 = down; turn > 0 = to her left)
    "": {}, "head_down": {"nod": 0.45}, "head_back": {"nod": -0.35}, "nod_small": {"nod": 0.15},
    "head_tilt": {"tilt": 0.2}, "head_tilt_other": {"tilt": -0.2},
    "look_left": {"turn": 0.45}, "look_right": {"turn": -0.45}, "look_up": {"nod": -0.3},
}
BODY = {   # added to the body
    "": {}, "lean_forward": {"lean": 0.15}, "lean_back": {"lean": -0.12}, "slouch": {"lean": 0.1, "bob": -0.03},
    "crouch": {"bob": -0.14, "lean": 0.12}, "shoulders_up": {"bob": 0.02, "lean": -0.03},
    "twist_left": {"twist": 0.25}, "twist_right": {"twist": -0.25},
    "weight_left": {"shift": 0.03}, "weight_right": {"shift": -0.03},
}
ARM_KEYS = ("arm", "raise", "rot", "elbow")
ADD_KEYS = ("nod", "tilt", "turn", "lean", "bob", "twist", "shift", "sway")
SHAKE_CHANNELS = {"nod", "tilt", "turn", "lean", "sway", "shift", "bob"}


# ---------------------------------------------------------------------------- examples (built in)
# The hand-tuned facepalm / sneeze / blow kiss rebuilt in this format: they prove the format and teach the AI.
BUILTIN = {
    "x_facepalm": {"description": "Hand over the eyes, head drops: oh no, how embarrassing.", "length": 1.6,
                   "keys": [{"t": 0.0, "R": "rest", "L": "rest"},
                            {"t": 0.35, "R": "hand_over_eyes", "L": "slump", "head": "head_down"},
                            {"t": 1.6, "R": "hand_over_eyes", "L": "slump", "head": "head_down"}],
                   "shake": [{"channel": "nod", "amount": 0.04, "speed": 2}]},
    "x_sneeze": {"description": "Sneezes into her elbow: breath in with the head back, then snaps forward.",
                 "length": 1.6, "loop": True,
                 "keys": [{"t": 0.0, "R": "rest"}, {"t": 0.55, "R": "hand_at_mouth", "head": "head_back"},
                          {"t": 1.0, "R": "hand_at_mouth", "head": "head_back"},
                          {"t": 1.12, "R": "hand_at_mouth", "head": "head_down", "body": "lean_forward"},
                          {"t": 1.6, "R": "rest"}]},
    "x_blow_kiss": {"description": "Hand to the lips, then throws a kiss towards the camera.", "length": 0.8,
                    "loop": True,
                    "keys": [{"t": 0.0, "R": "hand_at_mouth", "head": "head_tilt"},
                             {"t": 0.3, "R": "hand_at_mouth", "head": "head_tilt"},
                             {"t": 0.5, "R": "arm_forward", "head": "head_tilt"},
                             {"t": 0.8, "R": "hand_at_mouth", "head": "head_tilt"}]},
}


# ---------------------------------------------------------------------------- library
def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")[:32]


def validate(a, name=""):
    """A clean animation, or raises ValueError saying what's wrong (unknown pose, bad times...)."""
    if not isinstance(a, dict):
        raise ValueError("an animation is a JSON object")
    keys = a.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("it needs a list of keys")
    out, last_t = [], -1.0
    for k in keys[:24]:
        if not isinstance(k, dict):
            raise ValueError("each key is an object")
        t = float(k.get("t", 0.0))
        if t < last_t:
            raise ValueError(f"key times must go up (got {t} after {last_t})")
        last_t = t
        c = {"t": round(max(0.0, min(30.0, t)), 3)}
        both = k.get("both")
        for side in ("R", "L"):
            pose = k.get(side, both)
            if pose is not None:
                if pose not in ARM:
                    raise ValueError(f"unknown arm pose '{pose}' (known: {', '.join(ARM)})")
                c[side] = pose
        for slot, table in (("head", HEAD), ("body", BODY)):
            pose = k.get(slot) or ""
            if pose not in table:
                raise ValueError(f"unknown {slot} pose '{pose}' (known: {', '.join(x for x in table if x)})")
            if pose:
                c[slot] = pose
        out.append(c)
    shakes = []
    for s in (a.get("shake") or [])[:3]:
        if isinstance(s, dict) and s.get("channel") in SHAKE_CHANNELS:
            shakes.append({"channel": s["channel"], "amount": max(0.0, min(0.3, float(s.get("amount", 0.05)))),
                           "speed": max(0.5, min(30.0, float(s.get("speed", 6))))})
    length = float(a.get("length") or out[-1]["t"] or 1.0)
    return {"name": slug(a.get("name") or name), "description": str(a.get("description") or "")[:200],
            "length": round(max(0.2, min(30.0, length)), 3), "loop": bool(a.get("loop")),
            "keys": out, "shake": shakes, **({k: a[k] for k in ("by", "checked", "created", "problem", "needs_room", "request", "score") if k in a})}


def library():
    """name -> animation: the built-in examples, then assets/anims/*.json (a file wins over a built-in)."""
    out = {n: validate(dict(a, name=n)) for n, a in BUILTIN.items()}
    extra = os.environ.get("ANIMLIB_EXTRA")        # animgen's check render: a candidate that isn't saved yet
    files = sorted(p for p in LIB.glob("*.json") if not p.name.startswith(".")) if LIB.exists() else []   # not .not_actions.json
    for p in files + ([Path(extra)] if extra and Path(extra).exists() else []):
        try:
            a = validate(json.loads(p.read_text(encoding="utf-8-sig")), p.stem)
            out[a["name"] or p.stem] = a
        except Exception as exc:              # a broken file never breaks a render
            print(f"[anims] {p.name} skipped: {exc}")
    return out


def save(a):
    a = validate(a)
    LIB.mkdir(parents=True, exist_ok=True)
    (LIB / f"{a['name']}.json").write_text(json.dumps(a, indent=1), encoding="utf-8")
    return a


# ---------------------------------------------------------------------------- sampling
def _smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _channels(k, prev):
    """Absolute arm values + additive head/body values of one key (arms it doesn't name keep prev's pose)."""
    v = {}
    for side in ("R", "L"):
        pose = k.get(side) or prev.get(side) or "rest"
        for name, val in zip(ARM_KEYS, ARM[pose]):
            v[name + side] = val
        if pose == "hand_over_eyes":               # the hand only reaches the eyes with the head bowed into it
            v["nod"] = v.get("nod", 0.0) + 0.2
    for slot, table in (("head", HEAD), ("body", BODY)):
        for name, val in table.get(k.get(slot, ""), {}).items():
            v[name] = v.get(name, 0.0) + val
    return v


def resolved_keys(a):
    """[(t, channel values)] with the arm poses carried forward from key to key."""
    out, prev = [], {}
    for k in a["keys"]:
        v = _channels(k, prev)
        prev = {s: k.get(s) or prev.get(s) for s in ("R", "L")}
        out.append((k["t"], v))
    return out


def sample(a, t, keys=None):
    """Channel values at time t: {"armR": ..., "nod": ...}. Arm values are absolute, the rest are added."""
    keys = keys or resolved_keys(a)
    if a["loop"] and a["length"] > 0:
        t = t % a["length"]
    if t <= keys[0][0]:
        v = dict(keys[0][1])
    elif t >= keys[-1][0]:
        v = dict(keys[-1][1])
    else:
        i = next(j for j in range(1, len(keys)) if keys[j][0] >= t)
        (t0, v0), (t1, v1) = keys[i - 1], keys[i]
        u = _smooth((t - t0) / max(1e-6, t1 - t0))
        v = {n: v0.get(n, 0.0) + (v1.get(n, 0.0) - v0.get(n, 0.0)) * u for n in set(v0) | set(v1)}
    for s in a.get("shake") or []:
        v[s["channel"]] = v.get(s["channel"], 0.0) + s["amount"] * math.sin(t * s["speed"] * math.tau / 2)
    return v


def describe_for_ai():
    """The vocabulary as text, for the generator's prompt (phase 2)."""
    return ("arm poses (R, L or both): " + ", ".join(ARM) + "\nhead poses: " + ", ".join(x for x in HEAD if x)
            + "\nbody poses: " + ", ".join(x for x in BODY if x))
