"""
The rest of the cast: other people and things that show up in a scene. Imported by blender_build.py after the
main character is animated (it needs her per-frame position), with blender_build's globals passed in as B.

Episode data (filled in by autodirect + run_episode.resolve_cast):
    "cast": {"mom": {"type": "person", "look": {...}, "height": 1.1},
             "car": {"type": "thing", "def": {<propgen definition>}, "radius": 1.8}}
    shot "events": [{"who": "car", "do": "crash_in", "from": "left", "at": 0.1, "to": "<mark>"}]

Everything runs on one global timeline: an event starts at its shot's first frame + "at" seconds and simply
plays out, even across a cut. People reuse the main character's animations (walk, wave, angry...); things
move by keyframing their root (enter, crash_in, fall, fly_by, appear, vanish, exit, bounce, spin, shake).
"""
import math
import random
import re

import catalog
from mathutils import Vector

B = None
AWAY = Vector((0.0, -300.0, -60.0))     # where cast members wait when they're not in the scene
OFF = 5.5                               # how far to the side "offstage" is (just outside the shot)


def her(fr):
    fr = max(1, min(B.TOTAL, fr))
    v = B.char_loc[fr].copy()
    v.z = 0.0
    return v


def ease_out(u):
    return 1 - (1 - u) ** 2


def ease_in(u):
    return u * u


def yaw_to(a, b, cur=0.0):
    d = b - a
    return math.atan2(d.x, -d.y) if d.length > 1e-3 else cur


def event_frames(who):
    """[(start_frame, event)] for one cast member, in time order."""
    out = []
    for si, shot in enumerate(B.SHOTS):
        f0 = B.shot_info[si]["f0"]
        for e in shot.get("events", []) or []:
            if e.get("who") != who:
                continue
            verb = e.get("do", "enter")
            default_at = 0.1 if verb in ("crash_in", "fall", "fly_by") else 0.0
            at = float(e.get("at", default_at))
            e = dict(e, _si=si, _end=f0 + B.shot_info[si]["n"] - 1)
            out.append((f0 + round(at * B.FPS), e))
    out.sort(key=lambda x: x[0])
    # a cutaway subject that isn't used again disappears when its shot ends
    for k, (f, e) in enumerate(list(out)):
        if e.get("cutaway") and not any(f2 > f for f2, _ in out[k + 1:]):
            out.append((e["_end"] + 1, {"who": who, "do": "vanish", "duration": 1.0 / B.FPS, "_si": e["_si"],
                                        "_end": e["_end"] + 1}))
    return sorted(out, key=lambda x: x[0])


def dur_frames(e, verb, dist=None):
    if "duration" in e:
        return max(1, round(float(e["duration"]) * B.FPS))
    if verb in catalog.CAST_VERBS:
        sec = catalog.CAST_VERBS[verb][2]
        if verb in ("enter", "exit") and dist:
            sec = max(sec, dist / 2.6)        # walking pace
        return max(1, round(sec * B.FPS))
    return max(1, round(1.8 * B.FPS))        # a person's animation (wave, angry...)


TAKEN = []      # (position, radius) of cast members that have already landed somewhere
CUT = {}        # shot index -> cutaway subject {target, center, h, r, moving} (blender_build points a camera at it)
FOCUS = {}      # shot index -> where something arrives in that shot (cameras frame her and it together)


def hidden(c, radius, h):
    """Would something at c be mostly hidden behind her or another cast member, seen from a camera in front?"""
    cam = h + Vector((0.0, -5.0, 0.0))
    dc = c - cam
    # furniture only hides someone standing right behind it (a table 2 m in front still shows them waist up)
    props = [(Vector((ox, oy, 0.0)), r * 0.8) for ox, oy, r in B.OBST if math.hypot(c.x - ox, c.y - oy) < r + 1.2]
    for p, r in TAKEN + [(h, 0.35)] + props:
        dp = p - cam
        if dp.y >= dc.y - 0.2:        # only things in front of it can hide it
            continue
        sx_c, sx_p = dc.x / max(dc.y, 0.5), dp.x / max(dp.y, 0.5)
        if abs(sx_c - sx_p) < (0.6 * radius) / max(dc.y, 0.5) + r / max(dp.y, 0.5):
            return True
    return False


def _gap(c, h, radius):
    """Clear space between a spot c (for something of `radius`) and everyone already placed, and her."""
    gaps = [(c - p).length - r - radius for p, r in TAKEN]
    gaps += [math.hypot(c.x - ox, c.y - oy) - r - radius - 0.1 for ox, oy, r in B.OBST]   # furniture too
    return min(gaps + [(c - h).length - radius - 0.45])


def _roomiest(h, radius, x0, x1, y0, y1):
    """The point in the set's area with the most clear space around it, preferring spots in the shot."""
    best, best_score = None, -1e9
    steps = int(round((x1 - x0) / 0.25)) + 1
    for i in range(steps + 1):
        for j in range(int(round((y1 - y0) / 0.25)) + 1):
            c = Vector((x0 + i * 0.25, y0 + j * 0.25, 0.0))
            in_shot = abs(c.x - h.x) - radius * 0.8 <= 0.34 * (c.y - h.y + 4)
            score = _gap(c, h, radius) - (0.0 if in_shot else 1.0)
            if score > best_score:
                best, best_score = c, score
    return best


def spot(e, fr, side, radius, claim=True):
    """Where a cast member ends up: a named mark, or next to her - on the side towards the middle of the set,
    inside the walkable area (marks), and not on top of anyone else."""
    to = e.get("to")
    if isinstance(to, str) and to in B.MARKS:
        return Vector((*B.MARKS[to], 0.0))
    if isinstance(to, (list, tuple)) and len(to) >= 2:      # a spot the director chose ([show: ...] objects)
        c = Vector((float(to[0]), float(to[1]), 0.0))
        if claim:
            TAKEN.append((c.copy(), radius))
        return c
    if e.get("cutaway"):
        return her(fr) + Vector((0.0, 0.6, 0.0))
    h = her(fr)
    xs = [m[0] for m in B.MARKS.values()] + [0.0]
    ys = [m[1] for m in B.MARKS.values()] + [0.0]
    x0, x1, y0, y1 = min(xs) - 0.3, max(xs) + 0.3, min(ys) - 0.3, max(ys) + 0.8
    inward = (-1 if h.x > 0 else 1) if abs(h.x) > 1.0 else side
    a = 0.7 + radius
    # beside her first, then further back (a 9:16 medium shot only sees about |dx| < 0.34 * (dy + 4))
    cands = [(a, 0.5), (a, 1.5), (-a, 0.5), (-a, 1.5), (a * 0.7, 2.6), (-a * 0.7, 2.6), (a * 1.3, 2.8),
             (-a * 1.3, 2.8), (a, 3.6), (-a, 3.6), (a * 1.3, 4.6), (-a * 1.3, 4.6)]
    if radius < 1.2:
        cands.insert(8, (0.0, 2.2 + radius))
    else:                 # something big straight behind her fills the background of every later shot: last resort
        cands.append((0.0, 2.2 + radius))
    best, why = None, {}
    for dx, dy in cands:
        if abs(dx) - radius * 0.8 > 0.34 * (dy + 4):      # most of it must be in shot
            continue
        c = h + Vector((inward * dx, dy, 0.0))
        if not (x0 <= c.x <= x1 and y0 <= c.y <= y1):
            reason = "outside the set's places"
        elif not (all((c - p).length > r + radius + 0.25 for p, r in TAKEN) and (c - h).length > radius + 0.45):
            reason = "someone is there"
        elif not all(math.hypot(c.x - ox, c.y - oy) > r + radius + 0.15 for ox, oy, r in B.OBST):
            reason = "furniture"
        elif hidden(c, radius, h):
            reason = "hidden from the camera"
        else:
            best = c
            break
        why[reason] = why.get(reason, 0) + 1
    if best is None:     # no clean spot beside her: search the whole area for the roomiest one
        best = _roomiest(h, radius, x0, x1, y0, y1)
        if claim:                        # a peek (claim=False) is followed by the real call: warn once
            print(f"[cast] warning: no free spot beside her at ({h.x:.1f}, {h.y:.1f}) for a {radius:.2f} m cast "
                  f"member ({', '.join(f'{n}x {k}' for k, n in why.items())}) - moved to ({best.x:.1f}, "
                  f"{best.y:.1f}), clearance {_gap(best, h, radius):.2f} m")
    if claim:
        TAKEN.append((best.copy(), radius))
    return best


def offstage(target, e, side):
    frm = e.get("from") or ("right" if side > 0 else "left")
    return target + {"left": Vector((-OFF, 0, 0)), "right": Vector((OFF, 0, 0)), "back": Vector((0, OFF * 1.8, 0)),
                     "top": Vector((0, 0, 9.0))}.get(frm, Vector((side * OFF, 0, 0)))


# --------------------------------------------------------------------------- people
def talk_at(who, fr):
    """Seconds into the line when `who` is the speaker of this frame's shot, else None (mouth and gestures)."""
    for si, shot in enumerate(B.SHOTS):
        if B.speaker_of(shot) != who or not shot.get("line"):
            continue
        ts = (fr - B.shot_info[si]["f0"]) / B.FPS - float(shot.get("lead", B.AUDIO_LEAD))
        if 0 <= ts <= float(shot.get("talk", 0.0)):
            return ts
    return None


def animate_person(who, info, side):
    look = dict(info.get("look") or {})
    if info.get("actor_model"):                      # a rigged actor: their own .blend, animated like a character
        from pathlib import Path
        R = B.VRoidRig(Path(info["actor_model"]), {})
        print(f"[cast] {who}: rigged actor {Path(info['actor_model']).name}")
    else:
        R = B.build_catgirl(look, cat=False)
    h = max(0.5, min(1.6, float(info.get("height", 1.0))))
    R.shadow["r"] = 0.34 * h
    evs = event_frames(who)
    first = evs[0][1].get("do") if evs else None
    present = not (first in ("enter", "appear") or (not evs and not info.get("start")))
    start = info.get("start")
    pos = Vector((*B.MARKS[start], 0.0)) if start in B.MARKS else spot({}, 1, side, 0.3, claim=False)
    if not present and first == "enter":
        # only a peek (claim=False): the enter event below picks - and claims - the same spot. Claiming here made
        # every arriving person collide with their own reservation and fall back to "no free spot".
        pos = offstage(spot(evs[0][1], evs[0][0], side, 0.3, claim=False), evs[0][1], side)
    yaw = yaw_to(pos, her(1))
    # segments: (f0, n, anim, p0, p1, y0, y1, extra) - gaps are idle, facing her
    segs, cur, scale_ev = [], 1, []
    for k, (f, e) in enumerate(evs):
        verb = e.get("do", "enter")
        f = max(f, cur)
        if f > cur:
            segs.append(dict(f0=cur, n=f - cur, anim="idle", p0=pos.copy(), p1=pos.copy(), present=present))
            cur = f
        if verb in ("enter", "walk_to", "run_to", "sneak_to", "exit"):
            if verb == "enter":
                p1 = spot(e, f, side, 0.3)
                p0 = pos if present else offstage(p1, e, side)
            elif verb == "exit":
                p0, p1 = pos.copy(), offstage(pos, e, side)
            else:
                p0, p1 = pos.copy(), spot(e, f, side, 0.3)
            anim = verb if verb in B.MOVE_ANIMS else ("run_to" if e.get("run") else "walk_to")
            n = dur_frames(e, verb, (p1 - p0).length)
            segs.append(dict(f0=f, n=n, anim=anim, p0=p0, p1=p1, present=True, gone_after=verb == "exit"))
            if verb == "enter":
                note_focus(f, p1)
            pos, present = p1, verb != "exit"
        elif verb in ("appear", "vanish"):
            n = dur_frames(e, verb)
            if verb == "appear":
                pos = spot(e, f, side, 0.3) if not present else pos
            scale_ev.append((f, n, verb))
            segs.append(dict(f0=f, n=n, anim="idle", p0=pos.copy(), p1=pos.copy(), present=True,
                             gone_after=verb == "vanish"))
            present = verb == "appear"
        else:
            anim = verb if verb in B.ANIMS else "idle"
            n = dur_frames(e, verb)
            segs.append(dict(f0=f, n=n, anim=anim, p0=pos.copy(), p1=pos.copy(), present=present, a=e,
                             expr=e.get("expression")))
        cur = f + segs[-1]["n"]
    if cur <= B.TOTAL:
        segs.append(dict(f0=cur, n=B.TOTAL - cur + 1, anim="idle", p0=pos.copy(), p1=pos.copy(), present=present))
    for i, s in enumerate(segs):
        s.setdefault("a", {})
        s["prev_same"] = i > 0                 # the Smoother blends between actions
        s["next_same"] = i + 1 < len(segs)
        s["y0"] = yaw
        if s["anim"] in B.MOVE_ANIMS:
            yaw = yaw_to(s["p0"], s["p1"], yaw)
        s["y1"] = yaw
    sm = B.Smoother()
    track = {}                                    # frame -> where they stand (the camera follows a speaking actor)
    yaws = {}                                     # frame -> which way they face (so the camera films their face)
    for s in segs:
        T = s["n"] / B.FPS
        for k in range(s["n"]):
            fr = s["f0"] + k
            if fr > B.TOTAL:
                break
            t = k / B.FPS
            p = B.default_pose()
            p["loc"] = s["p0"].copy()
            face = yaw_to(s["p0"], her(fr), s["y0"])
            p["yaw"] = s["y0"] if s["anim"] in B.MOVE_ANIMS else B.lerp_angle(s["y0"], face, B.smooth(min(1.0, t / 0.4)))
            B.ANIMS[s["anim"]](p, t, T, s)
            if s["anim"] in B.MOVE_ANIMS and t > T - 0.35:       # turn to her when arriving
                p["yaw"] = B.lerp_angle(p["yaw"], yaw_to(p["loc"], her(fr), p["yaw"]), B.smooth((t - (T - 0.35)) / 0.35))
            B.apply_expression(p, s.get("expr") or B.ANIM_EXPR.get(s["anim"], "neutral"))
            B.secondary(p, (fr - 1) / B.FPS + 1.7, talk_at(who, fr))
            g = h
            for f0, n, verb in scale_ev:
                if f0 <= fr < f0 + n:
                    u = (fr - f0) / n
                    g = h * (B.smooth(u) * (1 + 0.25 * math.sin(math.pi * u)) if verb == "appear" else 1 - B.smooth(u))
            sm.apply(p)
            visible = s["present"] or (s.get("gone_after") and k < s["n"] - 1)
            if not visible:
                p["loc"], g = AWAY.copy(), 0.0
            if isinstance(R, B.VRoidRig):
                R.write(p, fr)
            else:
                B.write_pose(R, p, fr)
            track[fr] = p["loc"].copy()
            yaws[fr] = p["yaw"]
            R.root.scale = (max(g, 1e-4),) * 3
            R.root.keyframe_insert("scale", frame=fr)
            R.shadow["r"] = 0.34 * max(g, 1e-4)
            if s["anim"] in B.MOVE_ANIMS and not visible:
                pass
        # keep the last pose's yaw for the next segment
    for f, e in evs:
        if e.get("cutaway"):
            tgt = B.empty(f"cut_target_{who}", R.root, (0, 0, 1.0))
            CUT[e["_si"]] = {"target": tgt, "center": spot(e, f, side, 0.3, claim=False), "h": 1.6 * h, "r": 0.4,
                             "moving": e.get("do") in ("enter", "exit", "walk_to", "run_to")}
    last = AWAY.copy()                            # fill every frame so the camera can always find them
    for fr in range(1, B.TOTAL + 1):
        last = track.get(fr, last)
        track[fr] = last.copy()
    # the studio body has a big cartoon head (about twice hers): head shots pull back further so it fits the frame
    big_head = not isinstance(R, B.VRoidRig)
    B.CAST_TRACKS[who] = {"loc": track, "yaw": yaws, "rig": R, "cam_scale": h if big_head else 1.0,
                          "head_dist": 1.6 if big_head else 1.0}
    print(f"[cast] {who}: person, {len(evs)} events, height {h:.2f}")


# --------------------------------------------------------------------------- things
def debris(name, at, colors, f_hit, count=12):
    """Bits flying out where something crashes in (incl. glass)."""
    rng = random.Random(hash(name) & 0xffff)
    for i in range(count):
        col = rng.choice(colors + ["#cfe8ff", "#cfe8ff"])
        s = rng.uniform(0.05, 0.14)
        o = B.prim("cube", f"debris_{name}{i}", tuple(AWAY), (s, s * rng.uniform(0.3, 1), s), color=col,
                   unlit=col == "#cfe8ff")
        v = Vector((rng.uniform(-3.5, 3.5), rng.uniform(-3.0, 0.5), rng.uniform(1.5, 4.5)))
        spin = Vector((rng.uniform(-9, 9), rng.uniform(-9, 9), rng.uniform(-9, 9)))
        start = at + Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.2), rng.uniform(0.3, 1.0)))
        for fr in range(max(1, f_hit - 1), min(B.TOTAL, f_hit + round(1.6 * B.FPS)) + 1):
            t = (fr - f_hit) / B.FPS
            if t < 0:
                o.location, o.scale = AWAY, (1e-4,) * 3
            else:
                pz = start.z + v.z * t - 4.9 * t * t
                if pz < s:          # landed: stop where it hit the floor
                    t_land = (v.z + math.sqrt(max(0.0, v.z ** 2 + 19.6 * (start.z - s)))) / 9.8
                    t = t_land
                    pz = s
                o.location = (start.x + v.x * t, start.y + v.y * t, pz)
                o.rotation_euler = tuple(spin * t)
                o.scale = (s, s, s)
            o.keyframe_insert("location", frame=fr)
            o.keyframe_insert("rotation_euler", frame=fr)
            o.keyframe_insert("scale", frame=fr)


def animate_thing(who, info, side):
    d = info.get("def")
    is_cut = any(e.get("cutaway") for s in B.SHOTS for e in s.get("events", []) or [] if e.get("who") == who)
    if is_cut and d and d.get("sprite") and d.get("parts"):
        d = dict(d, complex=True)     # a cutaway fills the frame: its drawn picture reads better than a few blocks
    root = B.blender_sets.make_thing(who, info.get("prop", who), d, B.types.SimpleNamespace(
        prim=B.prim, empty=B.empty, mat=B.mat, add_fog=B.add_fog, hexcol=B.hexcol, FOG=B.FOG,
        setup_world=B.setup_world, add_sun=B.add_sun, scene=B.scene))
    radius = float((d or {}).get("radius", 0.8))
    height = float((d or {}).get("height", 1.0))
    size = float(info.get("scale", 0) or 0) or min(1.0, 2.2 / max(radius, 0.01), 3.5 / max(height, 0.01))
    if not info.get("scale") and height * size < 0.55:     # tiny things (a pizza, a phone) are shown bigger
        size = 0.55 / max(height, 0.01)
    if d and d.get("explainer") and not info.get("scale"):
        # an explainer object is a demonstration model beside her: about her height, whatever its real size
        size = max(0.25, min(4.0, 1.5 / max(height, 0.01), 1.3 / max(radius, 0.01)))
    r = radius * size
    shadow = B.make_shadow(max(0.2, r * 0.8), f"shadow_{who}")
    colors = [p.get("color", "#888888") for p in (d or {}).get("parts", [])][:4] or ["#888888"]
    evs = event_frames(who)
    first = evs[0][1].get("do") if evs else None
    start = info.get("start")
    present = bool(start) or (evs and first not in ("enter", "crash_in", "fall", "fly_by", "appear", "hold"))
    pos = Vector((*B.MARKS[start], 0.0)) if start in B.MARKS else spot({}, 1, side, r, claim=False)
    yaw = 0.0
    # build a per-frame track: (loc, yaw, tilt, scale)
    cur = 1
    plan, cut_plan, holds = [], [], []
    for f, e in evs:
        verb = e.get("do", "enter")
        f = max(f, cur)
        tgt = spot(e, f, side, r) if (verb in ("enter", "crash_in", "fall", "appear") or e.get("to")) else pos.copy()
        if verb == "fly_by":
            frm = e.get("from") or ("left" if side > 0 else "right")
            sgn = -1 if frm == "left" else 1
            p0 = her(f) + Vector((sgn * (OFF + 3), 2.5, 2.4))
            p1 = her(f) + Vector((-sgn * (OFF + 3), 2.5, 2.4))
            if e.get("cutaway"):     # the whole shot is about it: a short pass the camera can follow up close
                p0 = her(f) + Vector((sgn * 2.2, 1.0, 1.7))
                p1 = her(f) + Vector((-sgn * 2.2, 1.0, 1.7))
        elif verb in ("enter", "crash_in"):
            p0 = offstage(tgt, e, side) if not present else pos.copy()
            if verb == "crash_in" and not present:
                p0 = tgt + (offstage(tgt, e, side) - tgt) * 1.6 + Vector((0, 0, 0.6))
            p1 = tgt
        elif verb == "fall":
            p0, p1 = tgt + Vector((0, 0, 9.0)), tgt
        elif verb == "exit":
            p0, p1 = pos.copy(), offstage(pos, e, side)
        elif verb == "hold":                    # in her hand from now on (a constraint does the following)
            p0 = p1 = pos.copy()
            holds.append(f)
        else:
            p0, p1 = pos.copy(), tgt
        n = dur_frames(e, verb, (p1 - p0).length)
        if verb == "hold":
            n = 1
        if e.get("cutaway") and verb in ("appear", "show"):
            n = max(1, round(0.3 * B.FPS))
        if e.get("cutaway") and verb == "fly_by":       # take the whole shot to cross
            n = max(n, e["_end"] - f + 1)
        plan.append((f, n, verb, p0, p1))
        if e.get("cutaway"):
            cut_plan.append((e["_si"], verb, p0, p1))
        cur = f + n
        pos = p1
        present = verb not in ("vanish", "exit", "fly_by")
    # walk the timeline
    pos, present, yaw = (Vector((*B.MARKS[start], 0.0)) if start in B.MARKS else spot({}, 1, side, r, claim=False)), \
        bool(start) or (evs and first not in ("enter", "crash_in", "fall", "fly_by", "appear", "hold")), 0.0
    pi = 0
    for fr in range(1, B.TOTAL + 1):
        while pi < len(plan) and fr >= plan[pi][0] + plan[pi][1] + (round(0.6 * B.FPS) if plan[pi][2] == "crash_in" else 0):
            f, n, verb, p0, p1 = plan[pi]
            pos = p1.copy()
            if verb in ("enter", "crash_in", "fly_by", "exit") and (p1 - p0).length > 1e-3:
                yaw = yaw_to(p0, p1, yaw)
            present = verb not in ("vanish", "exit", "fly_by")
            pi += 1
        loc, sc, tilt, ry = pos.copy(), 1.0, 0.0, yaw
        vis = present
        if pi < len(plan) and fr >= plan[pi][0]:
            f, n, verb, p0, p1 = plan[pi]
            u = min(1.0, (fr - f) / n)
            vis = True
            travel = yaw_to(p0, p1, yaw) if (p1 - p0).length > 1e-3 else yaw
            if verb == "enter":
                loc, ry = p0.lerp(p1, ease_out(u)), travel
            elif verb == "exit":
                loc, ry = p0.lerp(p1, ease_in(u)), travel
            elif verb == "crash_in":
                if fr < f + n:
                    loc, ry = p0.lerp(p1, u ** 1.3), travel
                    loc.z = p0.z * (1 - u)
                else:          # skid, rock and settle after the hit
                    w = (fr - f - n) / B.FPS
                    loc, ry = p1.copy(), travel + 0.35 * math.exp(-4 * w) * math.sin(w * 18)
                    tilt = 0.25 * math.exp(-5 * w) * math.sin(w * 22)
            elif verb == "fall":
                loc = p0.lerp(p1, ease_in(u))
                if u >= 1:
                    loc = p1.copy()
            elif verb == "fly_by":
                loc, ry = p0.lerp(p1, u), travel
                loc.z += 0.3 * math.sin(u * math.pi * 4)
                tilt = 0.15 * math.sin(u * math.pi * 2)
            elif verb == "appear":
                loc = p1.copy()
                sc = B.smooth(u) * (1 + 0.3 * math.sin(math.pi * u))
            elif verb == "vanish":
                sc = 1 - B.smooth(u)
            elif verb == "bounce":
                loc.z += abs(math.sin(u * math.pi * 3)) * 0.6 * (1 - u)
            elif verb == "spin":
                ry = yaw + math.tau * B.smooth(u)
            elif verb == "shake":
                loc.x += 0.06 * math.sin(u * 90) * (1 - u)
                tilt = 0.08 * math.sin(u * 70) * (1 - u)
            elif verb in B.ANIMS:      # a person's verb given to a thing: just wobble a little
                tilt = 0.1 * math.sin(u * math.pi * 4) * (1 - u)
        if not vis:
            loc, sc = AWAY.copy(), 0.0
        root.location = loc
        root.rotation_euler = (tilt, 0.0, ry)
        root.scale = (max(sc * size, 1e-4),) * 3
        for path in ("location", "rotation_euler", "scale"):
            root.keyframe_insert(path, frame=fr)
        shadow["r"] = max(0.2, r * 0.8) * max(sc, 1e-4)
        B.write_shadow(shadow, loc if vis else AWAY, fr, base_z=0.0 if vis else AWAY.z)
    # what it really looks like on screen: a sprite's drawn height and width, else the shape's size
    if d and d.get("sprite"):
        asp = float(d.get("sprite_aspect", 1.0))
        hs = max(0.2, min(6.0, height))
        if d.get("width"):
            hs = max(0.2, min(hs, float(d["width"]) * 1.15 / asp))
        vis_h, vis_w = hs * size, hs * asp * size
    else:
        vis_h, vis_w = height * size, 2 * r
    if holds:
        attach_to_hand(root, shadow, holds, [f for f, e in evs if e.get("do") != "hold"])
    for si, verb, p0, p1 in cut_plan:
        tgt = B.empty(f"cut_target_{who}", root, (0, 0, max(0.05, vis_h / size / 2)))
        CUT[si] = {"target": tgt, "center": (p0 + p1) / 2 if verb == "fly_by" else p1.copy(),
                   "h": vis_h, "w": vis_w, "r": r, "verb": verb,
                   "moving": verb in ("fly_by", "fall", "crash_in", "enter")}
    if d and d.get("explainer"):
        explain_moves(who, root, d, size, plan)
    for f, n, verb, p0, p1 in plan:
        if verb == "crash_in":
            debris(who, p1, colors, f + n)
        if verb in ("enter", "crash_in", "fall", "appear", "bounce", "spin", "shake"):
            note_focus(f, p1)
    print(f"[cast] {who}: thing ({'AI prop' if d else info.get('prop', '?')}), {len(evs)} events, size x{size:.2f}")


# --------------------------------------------------------------------------- explainer objects
def _stem(w):
    return re.sub(r"[^a-z0-9]+", "", str(w).lower())


def _word_match(spoken, want):
    """'lifts' ~ 'lift', 'flaps' ~ 'flap', 'filling' ~ 'fill' (not 'a' ~ 'an')."""
    if not spoken or not want:
        return False
    if spoken == want:
        return True
    k = max(4, len(want) - 2)
    return len(spoken) >= 4 and len(want) >= 3 and (spoken.startswith(want[:k]) or want.startswith(spoken[:k]))


def word_frames(si):
    """[(word, frame)] for a shot's English words, at the moment each is said (shot "word_t" from the voice's word
    times; a translated video spreads the English words over the speech, since only it was timed)."""
    shot = B.SHOTS[si]
    f0, n = B.shot_info[si]["f0"], B.shot_info[si]["n"]
    lead, talk = float(shot.get("lead", 0) or 0), float(shot.get("talk", 0) or 0)
    words = str(shot.get("line_src") or shot.get("line") or "").split()
    if not words:
        return []
    wt = shot.get("word_t")
    if shot.get("line_src") or not (isinstance(wt, list) and len(wt) == len(words)):
        wt = [talk * k / len(words) for k in range(len(words))]
    return [(_stem(w), min(f0 + n - 1, f0 + round((lead + float(t)) * B.FPS))) for w, t in zip(words, wt)]


def explain_moves(who, root, d, size, plan):
    """Animate an explainer object's parts (blender_sets.p_explainer): each move plays when its word is said while
    the object is on stage (moves whose word never comes play one after another in its first shot), and the part
    stays where the move left it. The cover comes off at the first shot that shows it open. Also tells the cameras
    what to frame: the object beside her (FOCUS), or one part close up (CUT)."""
    info = B.blender_sets.EXPLAIN.get(root.name)
    if not info:
        return
    on = [(f, f + n) for f, n, verb, p0, p1 in plan if verb in ("appear", "enter", "fall", "crash_in")]
    off = [f for f, n, verb, p0, p1 in plan if verb in ("vanish", "exit")]
    if not on:
        return
    t_on = on[0][0]
    t_off = min([f for f in off if f > t_on] + [B.TOTAL + 1])
    where = next(p1 for f, n, verb, p0, p1 in plan if verb in ("appear", "enter", "fall", "crash_in"))
    shown = [si for si, s in enumerate(B.SHOTS) if (s.get("show") or {}).get("who") == who
             and t_on <= B.shot_info[si]["f0"] + B.shot_info[si]["n"] - 1 and B.shot_info[si]["f0"] < t_off]
    # when each move starts
    said = [(w, fr) for si in range(len(B.SHOTS)) for w, fr in word_frames(si) if t_on <= fr < t_off]
    first = shown[0] if shown else None
    spare = (B.shot_info[first]["f0"] + round(float(B.SHOTS[first].get("lead", 0) or 0) * B.FPS)) if first is not None \
        else t_on + 2
    sched = []
    for mv in d.get("moves") or []:
        if mv.get("part") not in info["groups"]:
            continue
        hit = next((fr for w, fr in said if _word_match(w, _stem(mv.get("word", "")))), None)
        if hit is None:
            hit = spare
            spare += round(0.8 * B.FPS)
        sched.append((max(hit, t_on + 1), mv))
    sched.sort(key=lambda x: x[0])
    dur = max(2, round(0.7 * B.FPS))
    # the cut-open view: the cover comes away at the first shot that asks for it open
    opens = [B.shot_info[si]["f0"] for si in shown if (B.SHOTS[si].get("show") or {}).get("open")]
    t_open = opens[0] if opens else None
    for name, (e, box) in info["groups"].items():
        mine = [(t0, mv) for t0, mv in sched if mv["part"] == name]
        if not mine:
            continue
        base_loc = e.location.copy()
        lv = [mv for _, mv in mine if mv.get("do") in ("fill", "drain")]
        level0 = (0.15 if lv[0]["do"] == "fill" else 1.0) if lv else 1.0
        for fr in range(1, B.TOTAL + 1):
            rot, offv, sc, level = [0.0, 0.0, 0.0], Vector((0.0, 0.0, 0.0)), 1.0, level0
            for t0, mv in mine:
                if fr < t0:
                    break
                do, amt = mv.get("do"), float(mv.get("amount", 0) or 0)
                ax = "xyz".index(mv.get("axis", "z")) if mv.get("axis", "z") in "xyz" else 2
                u = min(1.0, (fr - t0) / dur)
                ease = B.smooth(u)
                if do == "turn":
                    rot[ax] += math.radians(amt) * ease
                elif do == "slide":
                    dv = mv.get("dir") or [0, 0, 1]
                    offv += Vector((float(dv[0]), float(dv[1]), float(dv[2]))) * ease
                elif do == "spin":
                    secs = min(fr - t0, round(float(mv.get("seconds", 2.5)) * B.FPS)) / B.FPS
                    rot[ax] += math.tau * (amt or 1.0) * secs
                elif do in ("fill", "drain"):
                    level = level + (max(0.02, min(1.0, amt)) - level) * ease
                elif do == "pulse":
                    times = max(1, int(mv.get("times", 2) or 2))
                    span = dur * times
                    if fr - t0 < span:
                        sc *= 1.0 + 0.22 * math.sin(math.pi * ((fr - t0) % dur) / dur)
                elif do == "shake":
                    if fr - t0 < dur * 2:
                        offv.x += 0.03 * math.sin((fr - t0) * 2.3) * (1 - (fr - t0) / (dur * 2))
            e.location = base_loc + offv
            e.rotation_euler = rot
            e.scale = (sc, sc, max(1e-3, sc * level))
            for path in ("location", "rotation_euler", "scale"):
                e.keyframe_insert(path, frame=fr)
    if info["cover"] and t_open:
        ce, _ = info["cover"]
        base = ce.location.copy()
        n_open = max(2, round(0.5 * B.FPS))
        for fr in (1, t_open - 1, *range(t_open, t_open + n_open + 1)):
            if fr < 1:
                continue
            u = min(1.0, max(0.0, (fr - t_open) / n_open))
            ce.location = base + Vector((0.0, -0.6 * B.smooth(u), 0.15 * math.sin(math.pi * u)))
            ce.scale = (max(1e-3, 1 - B.smooth(u)),) * 3
            ce.keyframe_insert("location", frame=fr)
            ce.keyframe_insert("scale", frame=fr)
    # cameras: the object beside her, or a part close up
    for si in shown:
        part = (B.SHOTS[si].get("show") or {}).get("part")
        if part and part in info["groups"]:
            lo, hi = info["groups"][part][1]
            mid = Vector([(a + b) / 2 for a, b in zip(lo, hi)])
            tgt = B.empty(f"part_target_{who}_{si}", root, tuple(mid))
            ext = max(hi[0] - lo[0], hi[1] - lo[1])
            CUT[si] = {"target": tgt, "center": where + Vector((mid.x * size, mid.y * size, 0.0)),
                       "z": mid.z * size, "h": max(0.25, (hi[2] - lo[2]) * size * 1.6),
                       "w": max(0.25, ext * size * 1.6), "r": ext * size / 2, "verb": "show", "moving": False,
                       "part": True}
        else:
            FOCUS.setdefault(si, where.copy())
    print(f"[cast] {who}: explainer - {len(sched)} moves"
          + (f", opens at frame {t_open}" if t_open else "") + f", shown in {len(shown)} shots")


def attach_to_hand(root, shadow, starts, others):
    """From each "hold" until the cast member's next event, it follows her right hand (strings stay upright)."""
    obj, sub = getattr(B.RIG, "hand", (None, ""))
    if obj is None:
        return
    con = root.constraints.new("COPY_LOCATION")
    con.target = obj
    if sub:
        con.subtarget = sub
    try:
        B.bpy.context.preferences.edit.keyframe_new_interpolation_type = "CONSTANT"
    except Exception:
        pass
    keys = {1: 0.0}                     # hold the value flat between keys (Blender would ease 1 -> 0 otherwise)
    for f in starts:
        end = min([o for o in others if o > f] + [B.TOTAL + 1])
        keys[max(1, f) - 1] = keys.get(max(1, f) - 1, 0.0) if f > 1 else 1.0
        keys[max(1, f)] = 1.0
        keys[min(end, B.TOTAL + 1) - 1] = 1.0
        keys[min(end, B.TOTAL + 1)] = 0.0
        for fr in range(max(1, f), min(end, B.TOTAL + 1)):
            root.scale = (1.0, 1.0, 1.0)
            root.keyframe_insert("scale", frame=fr)
            shadow.hide_render = True
    for fr, v in sorted(keys.items()):
        if fr >= 1:
            con.influence = v
            con.keyframe_insert("influence", frame=fr)



def note_focus(f, where):
    for si, info in enumerate(B.shot_info):
        if info["f0"] <= f < info["f0"] + info["n"]:
            FOCUS.setdefault(si, where.copy())
            return


def build(ns):
    global B
    B = ns
    cast = B.EP.get("cast") or {}
    side = 1
    for who, info in cast.items():
        if not event_frames(who) and not info.get("start"):
            continue                  # never shows up
        info = info if isinstance(info, dict) else {}
        if info.get("type") != "person" and any(B.speaker_of(s) == who for s in B.SHOTS):
            print(f"[cast] warning: {who} has lines but is a thing - things have no mouth, so it won't look like it talks")
        if info.get("type") == "person":
            animate_person(who, info, side)
        else:
            animate_thing(who, info, side)
        side = -side
