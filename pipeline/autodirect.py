"""
Auto-director: plain script -> shots (camera, action, expression) using simple, predictable rules.

One line per shot. Optional directions in square brackets at the start of a line override the
guesses, in any order:

    [closeup, angry, shake] Fine. I'll hiss back!
    [wide, walk_to counter] Okay! First day at my cafe.
    [sit, sad] Nobody came today...

Words are matched against cameras, camera moves, animations, expressions and the set's marks.

Other people and things join in with "+name" followed by what they do:

    [+mom enter] Mom?! What are you doing here?
    [+mom angry] She is NOT happy about the kitchen.
    [+car crash_in from_left, surprised] A CAR just came through the window?!

People (mom, boss, robot...) get a simple low-poly body; things are designed as props (propgen).
Verbs: catalog.CAST_VERBS, plus every animation for people (wave, angry, walk_to <mark>...).

Scene changes with "@ place" - it lasts until the next one. An existing set is reused when it fits, otherwise
a new set is made for it when the video renders ("new:<place>"):

    [@ falling through the clouds, wide] So I jumped out of the plane.
    [@ on the moon] Then I landed on the moon.

Particle effects by name - [rain], [snow], [confetti], [sparkles], [no_fx] - or automatically from words in the
line ("it started raining").

Cutaways show something else instead of her while her line plays as a voice-over:

    [cutaway: a plane flying past] The plane was already 4000 metres up.
    [cut: ants marching] Every ant on Earth would just... vanish.
"""
import re

import catalog
import sfx as sfxlib

ANGRY = re.compile(r"\b(hate|ugh|stupid|seriously|enough|grr+|hiss\w*|angry|mad|furious|idiot|fine\.)", re.I)
SAD = re.compile(r"\b(sorry|sad|cry|crying|alone|miss|nobody|sigh|lonely|why me)\b", re.I)
LAUGH = re.compile(r"\b(ha(ha)+|he(he)+|lol|lmao)\b", re.I)
WIN = re.compile(r"\b(yay|yes!|did it|worked|win|genius|perfect|victory|finally)\b", re.I)
SCARED = re.compile(r"\b(help|scary|scared|ghost|run!?|no no|monster)\b", re.I)
CAPS = re.compile(r"\b[A-Z]{3,}\b")

CAM_CYCLE = ["closeup", "medium", "side", "dramatic", "low", "macro", "closeup", "medium", "tiny", "dramatic"]


def mood_of(text):
    if SCARED.search(text):
        return "scared"
    if "?!" in text or "!?" in text or CAPS.search(text):
        return "surprised"
    if ANGRY.search(text):
        return "angry"
    if SAD.search(text):
        return "sad"
    if LAUGH.search(text):
        return "laugh"
    if WIN.search(text):
        return "win"
    if text.rstrip().endswith("?"):
        return "question"
    if text.strip().startswith("...") or text.rstrip().endswith("..."):
        return "smug"
    if "!" in text or re.search(r"\bnya\b", text, re.I):
        return "happy"
    return "neutral"


MOOD = {  # mood: (action, expression, preferred camera, camera move)
    "scared": ("scared", "scared", "medium", "shake"),
    "surprised": ("surprised", "surprised", "medium", "shake"),
    "angry": ("angry", "angry", "low", "static"),
    "sad": ("sad", "sad", "closeup", "push_in"),
    "laugh": ("laugh", "happy", "medium", "static"),
    "win": ("celebrate", "happy", "wide", "orbit"),
    "question": ("think", "neutral", "side", "static"),
    "smug": ("idle", "smug", "closeup", "push_in"),
    "happy": ("wave", "happy", "medium", "static"),
    "neutral": ("idle", "neutral", None, "static"),
}


# Action words: a line that says these gets that animation (checked in order; the first match wins).
# Used when the line's mood is neutral, happy, a question or smug. Strong moods keep their own animations.
ACTION_WORDS = [
    ("sneeze", re.compile(r"\b(achoo|a-?choo|sneez\w*|atchoo)\b", re.I)),
    ("facepalm", re.compile(r"\b(facepalm|face palm|my bad|how embarrassing|ugh+|oh my|sigh+)\b", re.I)),
    ("shiver", re.compile(r"\b(shiver\w*|freezing|chilly|brr+|so cold|too cold)\b", re.I)),
    ("blow_kiss", re.compile(r"\b(kiss(es)?|mwah+|xoxo|love you|blow a kiss)\b", re.I)),
    ("clap", re.compile(r"\b(clap\w*|applause|bravo|hooray)\b", re.I)),
    ("bow", re.compile(r"\b(bow|greetings|welcome to|ladies and gentlemen|nice to meet you)\b", re.I)),
    ("point", re.compile(r"\b(point\w*|look at (that|this)|over there|that way|this way|see that)\b", re.I)),
    ("dance", re.compile(r"\b(dance|dancing|boogie|groove)\b", re.I)),
    ("spin", re.compile(r"\b(spin|spinning|twirl\w*)\b", re.I)),
    ("jump", re.compile(r"\b(jump\w*|hop|hopping|bounce\w*)\b", re.I)),
    ("stretch", re.compile(r"\b(stretch\w*|yawn\w*|wake up|woke up|good morning)\b", re.I)),
    ("sit", re.compile(r"\b(sit|sitting|sat down|take a seat|rest|tired)\b", re.I)),
    ("look_around", re.compile(r"\b(look around|where is|where's|where did|looking for|searching)\b", re.I)),
    ("think", re.compile(r"\b(think|thinking|hmm+|wonder|ponder|maybe)\b", re.I)),
    ("nod", re.compile(r"\b(yes|yeah|sure|agree|nod\w*|exactly)\b", re.I)),
    ("shake_head", re.compile(r"\b(no|nope|never|nah|don't|do not)\b", re.I)),
    ("wave", re.compile(r"\b(hi|hello|hey|bye|goodbye|wave|waving)\b", re.I)),
]


def action_of(text):
    """The animation a line's words ask for, or None."""
    for anim, rx in ACTION_WORDS:
        if rx.search(text):
            return anim
    return None


def parse_directions(line, marks):
    """'[closeup, angry] text' -> ({...}, 'text')."""
    line = re.sub(r"^\s*\[([^\]\)]*)\)", r"[\1]", line)          # "[nod, confident) ..." typo from the AI
    m = re.match(r"\s*\[([^\]]*)\]\s*(.*)$", line)
    if not m:
        return {}, line.strip()
    d = {}
    inner = m.group(1)
    cut = re.search(r"\bcut(?:away)?\s*:\s*([^,\]]+)", inner, re.I)   # "cutaway: a plane flying past"
    if cut:
        d["cutaway"] = cut.group(1).strip()
        inner = inner[:cut.start()] + inner[cut.end():]
    sc = re.search(r"@\s*([^,\]]+)", inner)           # "@ falling through clouds" = scene change
    if sc:
        d["scene"] = sc.group(1).strip()
        inner = inner[:sc.start()] + inner[sc.end():]
    tokens = [t.replace("-", "_") for t in re.split(r"[,\s]+", inner.strip().lower()) if t]
    tokens = _take_cast(tokens, marks, d)
    for i, t in enumerate(tokens):
        joined = re.fullmatch(r"(walk_to|run_to|sneak_to)_(\w+)", t)   # AI often writes walk_to_center
        if joined and joined.group(2) in marks:
            d["action"], d["to"] = joined.group(1), joined.group(2)
            continue
        if t in catalog.CAMERAS:
            d["camera"] = t
        elif t in catalog.MOVES:
            d["move"] = t
        elif t in catalog.ANIMS and "action" in d and t in catalog.EXPRESSIONS:
            d["expression"] = t          # "[run_to_back, scared]": second word is the mood
        elif t in catalog.ANIMS and d.get("action") not in catalog.MOVE_ANIMS:
            d["action"] = t
        elif t in catalog.EXPRESSIONS:
            d["expression"] = t
        elif t in marks:
            d["to"] = t
        elif t in catalog.LIGHTS or t in catalog.LIGHT_ALIASES or t.startswith("light:"):
            name = t.split(":", 1)[-1]
            name = catalog.LIGHT_ALIASES.get(name, name)
            if name in catalog.LIGHTS:
                d["light"] = name          # the light changes from this shot on: [night], [sunset], [dawn]
        elif t in catalog.PARTICLES or t in catalog.PARTICLE_ALIASES or t.startswith("fx:") or t in ("no_fx", "nofx"):
            name = t.split(":", 1)[-1]
            if name in ("no_fx", "nofx", "none"):
                d["particles"] = []
            else:
                name = catalog.PARTICLE_ALIASES.get(name, name)
                if name in catalog.PARTICLES:
                    d.setdefault("particles", [])
                    if name not in d["particles"]:
                        d["particles"].append(name)
        elif t in sfxlib.all_slots() or t.startswith("sfx:"):
            d["sfx"] = t.split(":", 1)[-1]
        elif t.startswith("face:") or t in ("face_left", "face_right", "face_away"):
            d["face"] = t.split(":", 1)[-1].replace("face_", "")
        elif re.fullmatch(r"\d+(\.\d+)?s?", t):
            d["duration"] = float(t.rstrip("s"))
    if "to" in d and d.get("action") not in catalog.MOVE_ANIMS:
        d["action"] = d.get("action") if d.get("action") in catalog.MOVE_ANIMS else "walk_to"
    return d, m.group(2).strip()


def cast_kind(name):
    """'mom' -> person, 'car' -> thing (a guess; the episode's cast entry can say otherwise)."""
    words = set(re.split(r"[_\s]+", name.lower()))
    return "person" if words & catalog.PERSON_WORDS or name.rstrip("s") in catalog.PERSON_WORDS else "thing"


def _take_cast(tokens, marks, d):
    """Pull '+name verb [from_side] [mark]' groups out of the token list into d['events']."""
    rest, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if not (t.startswith("+") and len(t) > 1):
            rest.append(t)
            i += 1
            continue
        who, _, verb = t[1:].partition(":")
        who = re.sub(r"[^a-z0-9_]+", "", who)[:24]
        ev = {"who": who}
        i += 1
        if not verb and i < len(tokens) and (tokens[i] in catalog.CAST_VERBS or tokens[i] in catalog.ANIMS):
            verb = tokens[i]
            i += 1
        ev["do"] = verb if (verb in catalog.CAST_VERBS or verb in catalog.ANIMS) else "enter"
        while i < len(tokens):           # options that belong to this cast member
            o = tokens[i]
            if o.startswith("from_") and o[5:] in catalog.FROM_SIDES:
                ev["from"] = o[5:]
            elif ev["do"] in catalog.MOVE_ANIMS and o in marks and "to" not in ev:
                ev["to"] = o
            elif o.startswith("to:") and o[3:] in marks:
                ev["to"] = o[3:]
            else:
                break
            i += 1
        if who:
            d.setdefault("events", []).append(ev)
    return rest


def _stage_for_events(shot, d):
    """Things crashing or falling in need a camera that shows the room, and a bit of shake."""
    big = [e for e in shot.get("events", []) if e["do"] in ("crash_in", "fall", "fly_by")]
    if big and "camera" not in d:
        shot["camera"] = "wide"
    if any(e["do"] == "crash_in" for e in big) and "move" not in d:
        shot["move"] = "shake"
    if any(e["do"] == "enter" for e in shot.get("events", [])) and "camera" not in d and shot.get("camera") in ("closeup", "dramatic"):
        shot["camera"] = "medium"


def add_cast_plan(result, plan):
    """Merge an AI cast plan (llm.find_cast) into a directed result. Hand-written '+name' directions win."""
    if not isinstance(plan, dict):
        return result
    shots, cast = result["shots"], result.setdefault("cast", {})
    for name, info in (plan.get("cast") or {}).items():
        who = re.sub(r"[^a-z0-9_]+", "", str(name).lower().replace(" ", "_"))[:24]
        if not who or not isinstance(info, dict):
            continue
        cur = cast.get(who) or {}
        if not cur.get("looks") or cur.get("looks") == who.replace("_", " "):
            cur["looks"] = str(info.get("looks") or who.replace("_", " "))[:120]
        cur["type"] = info.get("type") if info.get("type") in ("person", "thing") else cur.get("type") or cast_kind(who)
        cast[who] = cur
    for e in plan.get("events") or []:
        try:
            i = int(e.get("line"))
        except Exception:
            continue
        who = re.sub(r"[^a-z0-9_]+", "", str(e.get("who", "")).lower().replace(" ", "_"))[:24]
        if not (0 <= i < len(shots)) or who not in cast:
            continue
        shot = shots[i]
        if any(x["who"] == who for x in shot.get("events", [])):
            continue                         # the script already says what they do here
        verb = e.get("do") if (e.get("do") in catalog.CAST_VERBS or e.get("do") in catalog.ANIMS) else "enter"
        if cast[who]["type"] == "thing" and verb in catalog.ANIMS and verb not in catalog.CAST_VERBS:
            verb = "shake"
        ev = {"who": who, "do": verb}
        if e.get("from") in catalog.FROM_SIDES:
            ev["from"] = e["from"]
        shot.setdefault("events", []).append(ev)
        _stage_for_events(shot, {})
    used = {e["who"] for s in shots for e in s.get("events", [])}
    result["cast"] = {k: v for k, v in cast.items() if k in used}
    return result


STOP = set("a an the of in on at to into onto through inside outside with and my our your her his its is was "
           "from out up down all way then now".split()) | set(  # generic place words don't decide a match
    "center centre middle place room area spot big small little tiny giant old new top bottom side edge land "
    "world inside outside day night cozy secret".split())


def _words(text):
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", str(text).lower()) if w not in STOP and len(w) > 2}


def fit_score(place, sid, s):
    q = _words(place)
    if not q:
        return 0.0
    name_w = _words(s.get("name", "")) | _words(sid.rsplit("_", 1)[0])
    desc_w = _words(s.get("description", ""))
    return (2.0 * len(q & name_w) + 1.0 * len(q & desc_w)) / (2.0 * len(q))


def match_set(place, sets, policy="reuse"):
    """The best existing set for a place description, or "new:<place>" if none fits (or policy == "new")."""
    key = re.sub(r"[^a-z0-9]+", "_", place.lower()).strip("_")
    if key in sets:
        return key
    if policy == "new":
        return "new:" + place
    q = _words(place)
    if not q:
        return "new:" + place
    best, score = None, 0.0
    for sid, s in sets.items():
        sc = fit_score(place, sid, s)
        if sc > score:
            best, score = sid, sc
    return best if best and score >= 0.5 else "new:" + place


GENERIC_MARKS = {"center": (0, 0), "front": (0, -2.5), "left": (-3, -0.5), "right": (3, -0.5), "back": (0, 3)}


def auto_set(title, policy="reuse", ollama=None, log=print):
    """Set = "auto": pick where the video starts from its title. Returns (set id or "new:<place>", place)."""
    import llm
    import settings as S
    o = ollama or S.load_settings()["ollama"]
    place = ""
    try:
        place = llm.place_for_title(o["url"], o["model"], title or "an ordinary day")["place"]
    except Exception as exc:
        log(f"[set] couldn't ask the AI for a place ({exc.__class__.__name__}) - using the title words")
    place = place or re.sub(r"^(what if|how does|how do|why is|why do|what does|how can|what happens if)\s+", "",
                            str(title or "").strip(" ?!."), flags=re.I) or "a sunny park"
    return match_set(place, catalog.all_sets(), policy), place


FLOAT_UP = re.compile(   # about HER going up - not "the floating latte" or a title question
    r"\b(i'?m|i am|am i|me|i|i'll|we)\b[^.!?]{0,25}?\b(float(?:s|ing)?|fly(?:ing)?|ris(?:e|ing)|go(?:ing)? up|"
    r"lift(?:ing)? off|levitat\w*|hover(?:ing)?)\b"
    r"|\b(up in the air|off the ground|lift(?:s|ed)? off|take off|taking off|gravity has left|weightless)\b", re.I)
LANDING = re.compile(r"\b(land(?:s|ed|ing)?|back down|com(?:e|ing) down|came down|touch(?:ed)? (?:the )?ground|"
                     r"pop(?:s|ped)?|fell down|crash(?:ed)? down|back on the ground)\b", re.I)
BALLOONS = re.compile(r"\bballoons?\b", re.I)
GROUND_ONLY = {"walk_to", "run_to", "sneak_to", "sit", "jump", "stretch"}


def particles_for(text):
    t = f" {text.lower()} "
    return [fx for fx, words in catalog.PARTICLE_WORDS.items() if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)]


MOVE_VERBS = re.compile(r"\b(fell|fall(?:ing)?|landed|land(?:ing)?|dove|dived|diving|jumped|jump(?:ing)? into|flew|"
                        r"sank|sink(?:ing)?|teleported|crashed|ended up|arrived|"
                        r"woke up|went|go(?:ing)? to|now i'?m (?:in|on|at))\b", re.I)
PLACE_PHRASES = ["centre of the earth", "center of the earth", "earth's core", "outer space", "space", "the moon",
                 "mars", "underwater", "under the sea", "bottom of the ocean", "the ocean", "the clouds", "the sky",
                 "a volcano", "the volcano", "the jungle", "the desert", "the north pole", "the beach", "the forest",
                 "the city", "a cave", "the cave", "a castle", "the castle", "a spaceship", "the spaceship"]


def moved_to(line):
    """'Then I fell all the way to the center of the earth!' -> 'center of the earth' (or None)."""
    t = str(line or "").lower()
    if not MOVE_VERBS.search(t):
        return None
    for ph in PLACE_PHRASES:
        if re.search(rf"\b{re.escape(ph)}\b", t):
            return ph.replace("the ", "", 1) if ph.startswith("the ") else ph
    return None


AI_FX = {"rain", "snow", "confetti", "sparkles", "petals", "leaves", "embers", "bubbles", "stars", "fireflies"}


def add_scene_plan(result, plan, set_name, policy="reuse"):
    """Merge llm.find_scenes into a directed result. Hand-written "@ place" directions win."""
    if not isinstance(plan, dict):
        return result
    sets = catalog.all_sets()
    shots = result["shots"]
    changes = {}
    if not any(s.get("set") for s in shots):      # a script that places its scenes by hand keeps them
        for sc in plan.get("scenes") or []:
            try:
                i = int(sc.get("line"))
            except Exception:
                continue
            if not (0 < i < len(shots)) or not sc.get("place"):
                continue
            line = str(shots[i].get("line", "")).lower()
            if not MOVE_VERBS.search(line) and not (_words(sc["place"]) & _words(line)):
                continue              # weather or talk, not a move ("then it started snowing")
            sid = str(sc.get("set") or "")
            place = str(sc["place"])
            # the AI's pick has to actually share words with the place - it likes to grab any set
            ok = policy == "reuse" and sid in sets and sid != set_name and fit_score(place, sid, sets[sid]) >= 0.34
            changes[i] = sid if ok else match_set(place, {k: v for k, v in sets.items() if k != set_name}, policy)
    if not any(sh.get("set") for sh in shots):          # backstop for moves the AI missed
        for i, sh in enumerate(shots):
            if i == 0 or i in changes:
                continue
            place = moved_to(sh.get("line", ""))
            if place:
                prev = next((changes[j] for j in sorted(changes, reverse=True) if j < i), set_name)
                if fit_score(place, prev.replace("new:", ""), sets.get(prev, {"name": prev.replace("new:", "")})) < 0.5:
                    changes[i] = match_set(place, {k: v for k, v in sets.items() if k != set_name}, policy)
    cur = None
    for i, shot in enumerate(shots):
        if i in changes:
            cur = changes[i] if changes[i] != set_name else None
        if cur and "set" not in shot:
            shot["set"] = cur
            if shot.get("action") in catalog.MOVE_ANIMS and shot.get("to") not in (sets.get(cur) or {}).get("marks", []):
                shot["action"] = "idle"
                shot.pop("to", None)
    for c in (plan.get("cutaways") or [])[:2]:
        try:
            i = int(c.get("line"))
        except Exception:
            continue
        if re.search(r"\b(her|she|herself|catgirl|me|my|i|myself)\b", str(c.get("show", "")), re.I):
            continue                         # a cutaway shows something else - never her
        if 0 < i < len(shots) and c.get("show") and "cutaway" not in shots[i] and not shots[i].get("events"):
            shots[i]["cutaway"] = str(c["show"])[:80]
    for p in plan.get("particles") or []:
        try:
            i = int(p.get("line"))
        except Exception:
            continue
        fx = catalog.PARTICLE_ALIASES.get(str(p.get("effect", "")).lower(), str(p.get("effect", "")).lower())
        if fx not in AI_FX:
            continue
        if 0 <= i < len(shots) and fx in catalog.PARTICLES and "particles" not in shots[i]:
            shots[i].setdefault("particles", [])
            if fx not in shots[i]["particles"]:
                shots[i]["particles"].append(fx)
    return result


SPEAKER = re.compile(r"^\s*([A-Za-z][A-Za-z '-]{0,30}?)\s*:\s+")   # "Ethan: hey there" - a named speaker


def expand_beats_grouped(lines, n, speakers=None):
    """Split long lines into beats of about n words: each beat becomes its own shot, so the camera cuts about
    every two or three seconds (like the reference videos). Bracket directions stay with the first beat; a
    speaker prefix ("Ethan: ...") is repeated on every beat. n <= 1 keeps the lines as they are."""
    if not n or n < 2:
        return [(l, None) for l in lines]
    out, gid = [], 0
    for raw in lines:
        s = raw.strip()
        dirs = ""
        dm = re.match(r"^\[[^\]]*\]\s*", s)            # "[closeup] Ethan: ..." - directions come first
        if dm:
            dirs, s = dm.group(0), s[dm.end():]
        pre = ""
        m = SPEAKER.match(s)
        if m and speakers and m.group(1).strip().lower() in speakers:
            pre, s = s[:m.end()], s[m.end():]
        words = s.split()
        if len(words) <= n:
            out.append((raw, None))
            continue
        gid += 1
        chunks, cur = [], []
        for w in words:                       # cut at punctuation once a beat has two words, or at n words
            cur.append(w)
            if len(cur) >= n or (len(cur) >= 2 and re.search(r"[.!?,;:]$", w)):
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        for i, c in enumerate(chunks):
            out.append(((dirs if i == 0 else "") + pre + " ".join(c), gid))
    return out


def direct(script, set_name="cafe", start=None, cast=None, scene_policy="reuse", speakers=None, beat_words=0,
           beat_sets=None, walk_every=0, wipe_every=0):
    """walk_every: every Nth beat she walks, with the camera following her (0 = never).
    wipe_every: a blurred foreground wipe at every Nth cut (0 = never)."""
    """speakers: {lower-case name or id: character id} for the main characters in this video. A line that
    starts with one of their names ("Ethan: ...") is said by them; other lines are said by the episode's character."""
    sets = catalog.all_sets()
    if str(set_name).startswith("new:"):               # made at render - it will have the standard places
        chosen = {"marks": GENERIC_MARKS}
    else:
        chosen = sets.get(set_name) or next(iter(sets.values()), {"marks": {"center": (0, 0), "front": (0, -2.5)}})
    marks = list(chosen["marks"])
    start_marks = list(marks)              # "start" belongs to the first set, even if the script moves on
    lines = [l for l in (script or "").splitlines() if l.strip()]
    speakers = dict(speakers or {})
    for who in re.findall(r"\+([a-z0-9_]+)", "\n".join(re.findall(r"\[[^\]]*\]", (script or "").lower()))):
        if cast_kind(who) == "person":     # "[+mom enter] ..." then "Mom: ..." - mom says that line
            speakers.setdefault(who.replace("_", " "), who)
            speakers.setdefault(who, who)
    pairs = expand_beats_grouped(lines, beat_words, speakers)
    lines, line_groups = [t for t, _ in pairs], [g for _, g in pairs]
    shots, prev_cam, pos = [], None, start or marks[0]
    cast = dict(cast or {})
    for who in cast:                       # cast people can say lines too: "Clerk: ..." or "store clerk: ..."
        if (cast[who] or {}).get("type") != "thing":
            speakers.setdefault(who.replace("_", " ").lower(), who)
            speakers.setdefault(who.lower(), who)
    cur_set = set_name                     # scene changes ("@ place") carry on until the next one
    airborne = holding = False             # floating (float_up ... land), holding balloons
    set_k = 0                              # beat_sets: each script line starts in the next set of the list
    for i, raw in enumerate(lines):
        starts_line = i == 0 or line_groups[i] is None or line_groups[i - 1] != line_groups[i]
        if beat_sets and starts_line and i > 0:
            nxt = beat_sets[set_k % len(beat_sets)]
            set_k += 1
            if nxt != cur_set:
                cur_set = nxt
                marks = list((sets.get(cur_set) or {}).get("marks") or ["center", "front", "left", "right", "back"])
                if pos not in marks:
                    pos = "center" if "center" in marks else marks[0]
        speaker = None
        head = re.match(r"^\s*(\[[^\]]*\]\s*)?", raw).group(0)     # directions may come before the name
        m = SPEAKER.match(raw[len(head):])
        if m and speakers and m.group(1).strip().lower() in speakers:
            speaker = speakers[m.group(1).strip().lower()]
            raw = head + raw[len(head) + m.end():]
        if "@" in raw[: raw.find("]") + 1 if raw.lstrip().startswith("[") else 0]:
            # peek: a scene change switches the marks this line can use
            pd, _ = parse_directions(raw, [])
            if pd.get("scene"):
                cur_set = match_set(pd["scene"], sets, scene_policy)
                marks = list((sets.get(cur_set) or {}).get("marks") or ["center", "front", "left", "right", "back"])
                if pos not in marks:
                    pos = "center" if "center" in marks else marks[0]
        d, text = parse_directions(raw, marks)
        d.pop("scene", None)
        mood = mood_of(text)
        action, expr, cam, move = MOOD[mood]
        if mood in ("neutral", "happy", "question", "smug") and action_of(text):
            action = action_of(text)                 # the words say what she does
        shot = {}
        if i == 0 and "action" not in d:
            # open by walking in to somewhere interesting
            dest = next((m for m in marks if m not in (pos, "front", "far")), "center")
            shot.update(action="walk_to", to=dest, camera="wide", move="static",
                        expression=expr if expr != "neutral" else "happy")
        else:
            if i == len(lines) - 1 and action in ("idle", "wave") and "action" not in d:
                action, cam, move = "nod", "wide", "orbit"
            if cam is None or cam == prev_cam:
                cam = next(c for c in CAM_CYCLE[i % len(CAM_CYCLE):] + CAM_CYCLE if c != prev_cam)
            shot.update(action=action, camera=cam, move=move, expression=expr)
            if walk_every and i % walk_every == walk_every - 1 and action in ("idle", "wave", "nod") and "action" not in d:
                shot.update(action="walk_to", camera="medium", move="follow")     # a tracking shot as she walks
        shot.update(d)
        if wipe_every and i and i % wipe_every == 0:
            shot["wipe"] = True                  # a blurred foreground wipe covers this cut (run_episode)
        if line_groups[i] is not None:
            shot["beat_group"] = line_groups[i]      # beats of one script line share one voice recording
        if speaker:
            shot["speaker"] = speaker
        if cur_set != set_name:
            shot["set"] = cur_set
        if "particles" not in shot:
            fx = particles_for(text)
            if fx:
                shot["particles"] = fx
        # balloons + floating: she gets the balloons, lifts off, stays up, comes down
        if BALLOONS.search(text) and not holding and not any(e["who"] == "balloons" for e in shot.get("events", [])):
            shot.setdefault("events", []).append({"who": "balloons", "do": "hold"})
            holding = True
        if any(e["who"] == "balloons" and e["do"] == "hold" for e in shot.get("events", [])):
            holding = True
        if not airborne and FLOAT_UP.search(text) and "action" not in d and not shot.get("set"):
            shot["action"] = "float_up"
        elif airborne and LANDING.search(text) and "action" not in d:
            shot["action"] = "land"
            if holding and re.search(r"\bpop", text, re.I):
                shot.setdefault("events", []).append({"who": "balloons", "do": "vanish"})
                holding = False
        if shot.get("action") == "float_up":
            airborne = True
        elif shot.get("action") == "land":
            airborne = False
        elif airborne and shot.get("action") in GROUND_ONLY:
            shot["action"] = "idle"          # up in the air: no sitting or walking - just hover
            shot.pop("to", None)
        _stage_for_events(shot, d)
        for ev in shot.get("events", []):
            if ev["who"] not in cast:
                cast[ev["who"]] = {"type": cast_kind(ev["who"]), "looks": ev["who"].replace("_", " ")}
        if shot.get("action") in catalog.MOVE_ANIMS:
            shot.setdefault("to", next((m for m in marks if m != pos), "center"))
            pos = shot["to"]
        else:
            shot.pop("to", None)
        shot["line"] = re.sub(r"\s{2,}", " ", re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text)).strip() or text
        if "sfx" not in shot:
            fx = sfxlib.suggest(text, shot.get("action"))
            if fx:
                shot["sfx"] = fx
        prev_cam = shot["camera"]
        shots.append(shot)
    used = {e["who"] for s in shots for e in s.get("events", [])}
    return {"start": start if start in start_marks else ("front" if "front" in start_marks else start_marks[0]),
            "shots": shots,
            "cast": {k: v for k, v in cast.items() if k in used}}


if __name__ == "__main__":
    import json
    demo = """Okay! First day running my very own cafe. Nya!
How hard can making coffee be?
Step one. Turn on the big shiny machine.
Why is it HISSING at me?!
[low, angry] Fine. I'll hiss back. Hsssss!
It worked. I am a genius barista.
[+mom enter] Mom?! Why are you here?
[+car crash_in from_left] AND WHY IS THERE A CAR IN MY CAFE?!"""
    print(json.dumps(direct(demo, "cafe", "door"), indent=1))
