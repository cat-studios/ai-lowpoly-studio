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
import overlays
import sfx as sfxlib

ANGRY = re.compile(r"\b(hate|ugh|stupid|seriously|enough|grr+|hiss\w*|angry|mad|furious|idiot|fine\.)", re.I)
SAD = re.compile(r"\b(sorry|sad|cry|crying|alone|miss|nobody|sigh|lonely|why me)\b", re.I)
LAUGH = re.compile(r"\b(ha(ha)+|he(he)+|lol|lmao)\b", re.I)
WIN = re.compile(r"\b(yay|yes!|did it|worked|win|genius|perfect|victory|finally)\b", re.I)
SCARED = re.compile(r"\b(help|scary|scared|ghosts?|no no|monsters?)\b|\brun(!|\s+away\b|\s+for (it|your life)\b)", re.I)
# ("run" alone isn't fear: "I run the place", "run by a cat" got the scared pose)
CAPS = re.compile(r"\b[A-Z]{3,}\b")

CAM_CYCLE = ["closeup", "medium", "side", "dramatic", "low", "macro", "high", "closeup", "medium", "tiny", "dramatic"]
# a "camera beat" (move_every): instead of her walking about, the camera does something - a new angle that moves
WALK_GAP = 5          # an automatic walk never comes within this many shots of another walk
TIME_WORDS = re.compile(r"\b(night\w*|dark\w*|evening|sunset|dusk|dawn|sunrise|morning|noon|midday|midnight|"
                        r"afternoon|day(?:time|light|s)?|today|tonight|hours?|o'?clock|sleep\w*|asleep|"
                        r"slept|dream\w*|wak(?:e|es|ing)|woke|bed ?time|moon\w*|stars?|lights? (?:out|off|on))\b", re.I)
MAX_WALKS = 2        # walks in a whole video, the opening walk-in included (the rest become standing shots)
CAMERA_BEATS = [("side", "orbit"), ("low", "push_in"), ("high", "pull_out"), ("wide", "orbit"),
                ("dramatic", "push_in"), ("side", "pull_out")]


# "I'm not mad", "don't be sad", "never scared": a mood word right after a negation isn't that mood
NEGATION = re.compile(r"(?:\bnot|n't|\bnever|\bno longer|\bno need to be)\s+(?:\w+\s+){0,2}$", re.I)


def _says(rx, text):
    """rx matches somewhere in text that isn't negated."""
    return any(not NEGATION.search(text[:m.start()]) for m in rx.finditer(text))


def mood_of(text):
    if _says(SCARED, text):
        return "scared"
    if "?!" in text or "!?" in text or CAPS.search(text):
        return "surprised"
    if _says(ANGRY, text):
        return "angry"
    if _says(SAD, text):
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


# handling something ("turn on the machine"): she points at it - at the thing she stands by if the line names none
HANDLING = re.compile(r"\b(turn(s|ing)? (it )?on|switch(es|ing)? (it )?on|press\w*|push(es|ing)? the|"
                      r"flip(s|ping)? the|button|lever|grab\w*|pick(s|ing)? up|plug\w* in)\b", re.I)

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
    ("point", HANDLING),     # handling something ("turn on the machine"): she points at it
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


# body poses the words ask for whatever the mood (a sad line at a grave still kneels) - checked before ACTION_WORDS
POSE_WORDS = [
    ("kneel_place", re.compile(r"\b(plac\w*|lay\w*|leav\w*|put\w*|set\w*) (down )?(the |some |these |a few |my |her |his )?"
                               r"(flowers?|roses?|bouquet|wreath|candles?)\b", re.I)),
    ("kneel", re.compile(r"\b(kneel\w*|knelt|on (my|her|his|our|their) knees|pray(ing|ed|s)?|"
                         r"(the|a|her|his|my|their|your) grave(stone)?(?! (mistake|danger|error|concern|news|tone))|"
                         r"tombstone|headstone)\b", re.I)),
    ("lie_down", re.compile(r"\b(lie down|lying down|lay down|laid down|lies down|lie (on|in) (the|my|a|her)|"
                            r"lying (on|in) (the|my|a|her)|in bed|(go|went|going) to sleep|fall(ing)? asleep|fell asleep|"
                            r"take a nap|nap time|stretched out on)\b", re.I)),
]
LIE_ON_WORDS = re.compile(r"\b(bed|sofa|couch|bench|hammock|mattress|futon)\b", re.I)
LOW_POSES = {"lie_down", "kneel", "kneel_place"}


def pose_of(text):
    for anim, rx in POSE_WORDS:
        if rx.search(text or ""):
            return anim
    return None


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
    show = re.search(r"\bshow\s*:\s*([^,\]]+)", inner, re.I)          # "show: toilet open" (explainer object)
    if show:
        d["show"] = show.group(1).strip().lower()
        inner = inner[:show.start()] + inner[show.end():]
    for fm in list(re.finditer(r"\bfire\s*:\s*([^,\]]+)", inner, re.I))[::-1]:
        d.setdefault("fire", []).insert(0, fm.group(1).strip().lower())     # "fire: window", "fire: off"
        inner = inner[:fm.start()] + inner[fm.end():]
    hud, inner = overlays.parse(inner)               # "meter: stress 99", "tag: BOSS: ME"... (game overlays)
    if hud:
        d["hud"] = hud
    cut = re.search(r"\bcut(?:away)?\s*:\s*([^,\]]+)", inner, re.I)   # "cutaway: a plane flying past"
    if cut:
        what = cut.group(1).strip()
        cam_only = [w for w in re.split(r"[\s_-]+", what.lower()) if w]
        inner = inner[:cut.start()] + inner[cut.end():]
        if what and all(w in catalog.CAMERAS or w in catalog.MOVES or w in CAM_WORDS or w in MOVE_WORDS
                        or w in ("zoom", "in", "out", "up", "shot", "extreme") for w in cam_only):
            # "[cutaway: macro]" / "[cutaway: zoom_in]": camera words, not a thing to show (the egg video, 2026-11-27)
            inner += ", " + what.replace(" ", "_")
        else:
            d["cutaway"] = what
    sc = re.search(r"@\s*([^,\]]+)", inner)           # "@ falling through clouds" = scene change
    if sc:
        # "[@ kitchen jump, excited]" / "[@library enter]": direction words the AI glued onto the place go back to
        # the directions (the set was made for a "kitchen jump")
        ws = sc.group(1).split()
        vocab = set(catalog.ANIMS) | set(catalog.CAMERAS) | set(catalog.MOVES) | set(catalog.EXPRESSIONS) \
            | set(catalog.CAST_VERBS) | set(getattr(catalog, "LIGHTS", {}))
        tail = []
        while len(ws) > 1 and ws[-1].lower() in vocab:
            tail.insert(0, ws.pop())
        d["scene"] = " ".join(ws).strip()
        inner = inner[:sc.start()] + (", " + ", ".join(tail) + "," if tail else "") + inner[sc.end():]
    tokens = [t.replace("-", "_") for t in re.split(r"[,\s]+", inner.strip().lower()) if t]
    tokens = _take_cast(tokens, marks, d)
    late = []                              # actions named only by the AI's own words ("floating")
    wants = []                             # unknown words that may be actions to make (animgen)
    for i, t in enumerate(tokens):
        joined = re.fullmatch(r"(walk_to|run_to|sneak_to)_(\w+)", t)   # AI often writes walk_to_center
        if joined and joined.group(2) in marks:
            d["action"], d["to"] = joined.group(1), joined.group(2)
            continue
        if t in marks and i and tokens[i - 1] in (*catalog.MOVE_ANIMS, "point"):
            d["to"] = t                    # "[run_to back]", "[point back]": the mark, not the "back" camera
        elif t in catalog.CAMERAS:
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
        elif t in FIRE_WORDS:                       # "[fire]", "[on_fire]": flames beside her (and embers)
            d.setdefault("fire", []).append("here")
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
        elif t in CAM_WORDS:                        # "[mid, happy]": the AI's own camera words
            d.setdefault("camera", CAM_WORDS[t])
        elif t in MOVE_WORDS:                       # "[zoom_in]" was made into a pose by the animation maker
            d.setdefault("move", MOVE_WORDS[t])
        elif t in catalog.CAST_VERBS or t in JUNK_WORDS or re.fullmatch(r"[a-z]+_(to|by|in|out|off)", t):
            pass      # verbs for other things ("hold", "bounce"), film words ("angle"), made-up walks ("swim_by")
        elif t in MOOD_WORDS:                       # "[jump, excited]": the AI's own mood words
            d.setdefault("expression", MOOD_WORDS[t])
        elif t in ANIM_WORDS:                       # "[floating]" - only when no real action was named
            late.append(ANIM_WORDS[t])
        elif t.startswith("do:") and len(t) > 3:    # "[do:salute]": an action she can't do yet - made at render
            d.setdefault("want", t[3:])
        elif re.fullmatch(r"[a-z][a-z_]{2,23}", t):   # an unknown word: maybe an action ("[yawn]") - render decides
            wants.append(t)
    if late and "action" not in d:
        d["action"] = late[0]
    if wants and "want" not in d and "action" not in d:
        d["want"] = wants[0]
    if d.get("action") in catalog.EXPRESSIONS and pose_of(m.group(2)):
        d["expression"] = d.pop("action")  # "[sad] ...lay down on the bed": the mood is a face, the words a pose
    if d.get("action") == "lie_down" and "to" not in d:
        on = LIE_ON_WORDS.search(m.group(1) if m else "")
        if on:
            d["on"] = on.group(1).lower()          # "[lie_down bed]" when the set has no mark called bed
    if "to" in d and d.get("action") == "lie_down":
        d["on"] = d.pop("to")              # "[lie_down bed]": lie ON the bed, don't walk to the mark beside it
    elif "to" in d and d.get("action") == "point":
        d["at"] = d.pop("to")              # "[point counter]": point AT it, don't walk there
    elif "to" in d and d.get("action") not in catalog.MOVE_ANIMS:
        d["action"] = d.get("action") if d.get("action") in catalog.MOVE_ANIMS else "walk_to"
    return d, m.group(2).strip()


def cast_kind(name):
    """'mom' -> person, 'car' -> thing (a guess; the episode's cast entry can say otherwise)."""
    words = set(re.split(r"[_\s]+", name.lower()))
    if words & catalog.PERSON_WORDS or name.rstrip("s") in catalog.PERSON_WORDS or words & ROLE_PEOPLE:
        return "person"
    try:                         # one of your actors has this name or role ("construction_worker"): a person
        import actors as AC
        a = AC.pick(name)
        if a and not a.get("builtin") and a.get("kind") != "thing":
            return "person"
    except Exception:
        pass
    return "thing"


ROLE_PEOPLE = set("""worker builder teacher farmer pilot captain sailor pirate knight wizard witch vampire chef baker
waiter waitress cashier clerk nurse doctor dentist firefighter fireman policeman policewoman officer guard soldier
mailman postman plumber mechanic artist singer dancer coach referee scientist astronaut neighbour neighbor
grandma grandpa auntie uncle cousin""".split())


def _known_word(t, marks):
    """A bracket word that means something on its own (a camera, verb, mark, mood...) - not part of a name."""
    return (t.startswith(("+", "from_", "to:", "fx:", "sfx:", "light:", "face:")) or t in marks
            or t in catalog.CAMERAS or t in catalog.MOVES or t in catalog.ANIMS or t in catalog.EXPRESSIONS
            or t in catalog.CAST_VERBS or t in catalog.LIGHTS or t in catalog.LIGHT_ALIASES
            or t in catalog.PARTICLES or t in catalog.PARTICLE_ALIASES or t in MOOD_WORDS or t in ANIM_WORDS)


# words the AI writes in brackets that aren't in the vocabulary, mapped onto it
CAM_WORDS = {    # -> camera ("[mid, wave]" asked the animation maker to invent a "mid" pose)
    **dict.fromkeys("mid mid_shot midshot medium_shot waist full full_shot two_shot".split(), "medium"),
    **dict.fromkeys("close close_up closeshot close_shot face closer closerup closer_up".split(), "closeup"),
    **dict.fromkeys("wide_shot long long_shot establishing far_shot".split(), "wide"),
    **dict.fromkeys("overhead top_down birds_eye aerial".split(), "high"),
    **dict.fromkeys("low_angle worms_eye".split(), "low"),
    **dict.fromkeys("phone phone_cam front_camera facecam face_cam video_call vlog".split(), "selfie"),
    **dict.fromkeys("extreme_closeup extreme_close_up eyes".split(), "macro"),
}
MOVE_WORDS = {"zoom_in": "push_in", "zoom": "push_in", "dolly_in": "push_in", "zoom_out": "pull_out",
              "dolly_out": "pull_out", "pan": "orbit", "circle": "orbit", "tracking": "follow", "track": "follow",
              "handheld": "shake", "shaky": "shake"}
JUNK_WORDS = set("angle shot cut scene camera cam pov frame focus beat pause transition fade still static_shot "
                 "background foreground center_frame mid_frame dreamy busy serious".split())
BODY_PARTS = set("head heads hand hands arm arms leg legs foot feet eye eyes ear ears nose mouth face tooth teeth "
                 "finger fingers toe toes body tummy belly stomach brain heart skin hair tongue".split())
# things the AI's cast step sometimes calls people ("the sun crashed in" got a human body)
NOT_PEOPLE = set("sun moon star stars cloud clouds rain storm wind lightning rainbow planet comet meteor sky "
                 "light shadow ghost_light clock alarm_clock tv phone robot_arm car bus truck van train plane".split())
MOOD_WORDS = {   # -> expression
    **dict.fromkeys("excited joyful cheerful delighted glad thrilled giddy ecstatic playful".split(), "happy"),
    **dict.fromkeys("shocked amazed startled stunned shook astonished gasp wide_eyes wide_eyed wideeyed".split(), "surprised"),
    **dict.fromkeys("mad furious annoyed grumpy frustrated irritated".split(), "angry"),
    **dict.fromkeys("worried nervous afraid terrified panicked frightened anxious".split(), "scared"),
    **dict.fromkeys("upset gloomy disappointed sorry heartbroken".split(), "sad"),
    **dict.fromkeys("proud confident cocky sassy sly smirking".split(), "smug"),
    **dict.fromkeys("smile smiling grin grinning beaming".split(), "happy"),
    **dict.fromkeys("wink winking".split(), "wink"),
    **dict.fromkeys("blush blushing shy flustered embarrassed".split(), "blush"),
    **dict.fromkeys("eyeroll eye_roll eyerolling unimpressed".split(), "eyeroll"),
    **dict.fromkeys("frown frowning pout pouting sulk sulking teary".split(), "sad"),
    **dict.fromkeys("glare glaring scowl scowling".split(), "angry"),
    **dict.fromkeys("gasp gasping wide_eyed".split(), "surprised"),
}
ANIM_WORDS = {   # -> animation, used only when the brackets name no action of their own
    "floating": "float_up", "flying": "float_up", "hovering": "float_up", "dancing": "dance", "jumping": "jump",
    "waving": "wave", "laughing": "laugh", "giggling": "laugh", "crying": "sad", "sobbing": "sad",
    "pointing": "point", "thinking": "think", "confused": "think", "puzzled": "think", "curious": "think",
    "clapping": "clap", "bowing": "bow", "spinning": "spin", "shivering": "shiver", "sneezing": "sneeze",
    "celebrating": "celebrate", "cheering": "celebrate", "stretching": "stretch", "nodding": "nod",
    "shrug": "shake_head", "shrugging": "shake_head", "facepalming": "facepalm",
    "lying": "lie_down", "sleeping": "lie_down", "asleep": "lie_down", "napping": "lie_down",
    "kneeling": "kneel", "praying": "kneel",
}


# ghost and shadow people (2026-11-27, from an eerie explainer Reel): pale see-through figures for spirits, memories,
# other versions of you; flat dark silhouettes for faceless strangers. By a word after the verb, or by the name.
STYLE_OPTIONS = {"ghost": "ghost", "ghostly": "ghost", "spirit": "ghost", "transparent": "ghost",
                 "shadow": "shadow", "silhouette": "shadow", "dark": "shadow"}
GHOST_NAMES = set("ghost ghosts spirit spirits phantom phantoms specter spectre apparition memory memories echo soul "
                  "souls afterlife".split())
GHOST_PHRASES = ("past_self", "future_self", "other_me", "other_self", "past_me", "future_me", "old_me", "younger_me")
SELF_NAME = re.compile(r"^(?:(?:past|future|younger|older|old|young|little|baby|evil|mirror|other|alternate|"
                       r"dream|tomorrow|yesterday|clone)_?)+(?:self|me|myself)$")


def is_self(who):
    """A cast name that is HER in another form - past_self, future_me, evil_self: played by her own model."""
    return bool(SELF_NAME.match(str(who or "").lower()))


SHADOW_NAMES = set("shadow shadows silhouette silhouettes shade shades".split())
FIGURE_WORDS = set("figure figures stranger strangers person man woman guy girl boy kid child someone".split())


def cast_style(who, info=None, events=()):
    """"ghost", "shadow" or None for a cast member: a style its events ask for, else its name ("ghost_mom",
    "shadow_people", "past_self"), else its looks."""
    for e in events:
        if e.get("who") == who and e.get("style") in ("ghost", "shadow"):
            return e["style"]
    if (info or {}).get("style") in ("ghost", "shadow"):
        return info["style"]
    words = set(re.split(r"[_\s]+", str(who).lower()))
    looks = set(re.findall(r"[a-z]+", str((info or {}).get("looks") or "").lower()))
    if words & GHOST_NAMES or any(p in str(who).lower() for p in GHOST_PHRASES) \
            or looks & {"ghost", "ghostly", "translucent"}:
        return "ghost"
    if words & SHADOW_NAMES or looks & {"silhouette", "shadowy", "faceless"}:
        return "shadow"
    return None


def apply_styles(shots, cast):
    """Every cast member gets its "style" (cast_style); a ghost or shadow that's only a name ("+ghost", "+shadow")
    is a person - "shadow" is otherwise a thing word (NOT_PEOPLE). Changes `cast` in place."""
    evs = [e for s in shots for e in s.get("events") or []]
    for who, info in list((cast or {}).items()):
        if not isinstance(info, dict):
            continue
        st = cast_style(who, info, evs)
        if not st:
            continue
        info["style"] = st
        rest = set(re.split(r"[_\s]+", who.lower())) - GHOST_NAMES - SHADOW_NAMES - {"self", "me", "past", "future",
                                                                                     "other", "old", "younger"}
        if info.get("type") != "person" and not (rest & GROUP_WORDS) and (
                not rest or rest <= FIGURE_WORDS or cast_kind("_".join(rest)) == "person"):
            info["type"] = "person"
    return cast


def _take_cast(tokens, marks, d):
    """Pull '+name verb [from_side] [mark]' groups out of the token list into d['events']."""
    rest, i = [], 0
    # "[huge_crowd enter, shocked]": the AI forgot the "+" - an unknown word right before an arrival verb is someone
    # coming on all the same (only arrival verbs: "[scared run]" is not a cast member called "scared")
    tokens = ["+" + t if (not t.startswith("+") and k + 1 < len(tokens)
                          and tokens[k + 1] in ("enter", "crash_in", "appear", "fall", "fly_by")
                          and re.fullmatch(r"[a-z][a-z0-9_]{1,23}", t) and not _known_word(t, marks)) else t
              for k, t in enumerate(tokens)]
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
        if not verb:
            # "+mail van crash_in": the AI wrote a two- or three-word name - the words up to the verb are the name
            j, extra = i, []
            while j < len(tokens) and len(extra) < 2 and not _known_word(tokens[j], marks):
                extra.append(re.sub(r"[^a-z0-9_]+", "", tokens[j]))
                j += 1
            if extra and j < len(tokens) and (tokens[j] in catalog.CAST_VERBS or tokens[j] in catalog.ANIMS):
                who = "_".join([who, *extra])[:24]
                ev["who"], i = who, j
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
            elif o in STYLE_OPTIONS:          # "+mom enter ghost": she comes on as a ghost
                ev["style"] = STYLE_OPTIONS[o]
            else:
                break
            i += 1
        if who:
            d.setdefault("events", []).append(ev)
    return rest


def _stage_for_events(shot, d):
    """Things crashing or falling in need a camera that shows the room, and a bit of shake."""
    if shot.get("camera") == "selfie":
        return                        # her phone films it: an arrival doesn't move the camera (Talk to you)
    big = [e for e in shot.get("events", []) if e["do"] in ("crash_in", "fall", "fly_by")]
    if big and "camera" not in d:
        shot["camera"] = "wide"
    if any(e["do"] == "crash_in" for e in big) and "move" not in d:
        shot["move"] = "shake"
    if any(e["do"] in ("enter", "appear") and not e.get("cutaway") for e in shot.get("events", [])) \
            and "camera" not in d and shot.get("camera") not in ARRIVAL_CAMS:
        shot["camera"] = "medium"     # only these cameras pull back to show the arrival beside her (a side shot lost the dog)


# words the script writer uses for "the object on stage" in [show: ...] (copied from the prompt's example)
SHOW_PLACEHOLDERS = {"thing", "it", "model", "object", "this", "that", "part"}


GROUP_WORDS = set("army armies crowd crowds team group squad troops audience everyone everybody people herd "
                  "flock swarm gang class family".split())
ARRIVALS = ("enter", "crash_in", "appear", "fall", "fly_by", "run_to", "walk_to")
SELF_WORDS = {"me", "i", "myself", "narrator", "main_character", "the_main_character", "she", "her", "speaker"}


def add_cast_plan(result, plan, skip=()):
    """Merge an AI cast plan (llm.find_cast) into a directed result. Hand-written '+name' directions win.
    skip: the main characters' names/ids - the AI sometimes casts her (a second, blocky "catgirl" in every shot)."""
    if not isinstance(plan, dict):
        return result
    shots, cast = result["shots"], result.setdefault("cast", {})
    flat = lambda s: re.sub(r"[^a-z0-9]+", "", str(s).lower())    # noqa: E731 - "Cat girl" == "catgirl"
    skip = {flat(s) for s in skip if s} | {flat(s) for s in SELF_WORDS} | BODY_PARTS   # a "head" was cast (an imported celebrity head played it)
    skip |= {"bubble", "meter", "counter", "tag", "label", "sticker", "count", "score"}   # [bubble: in...] is an overlay
    for name, info in (plan.get("cast") or {}).items():
        who = re.sub(r"[^a-z0-9_]+", "", str(name).lower().replace(" ", "_"))[:24]
        if not who or not isinstance(info, dict) or flat(who) in skip:
            continue
        if who not in cast and any(set(who.split("_")) < set(k.split("_")) for k in cast):
            continue                         # "past" when the script has +past_self: the same one, half-named
        if set(who.split("_")) & GROUP_WORDS:
            # "crowd", "audience": a group of the user's imported people (or animals) - only when it can be built;
            # a made-up shape for "feline_army" was four boxes
            try:
                import imported
                ok = imported.crowd_def(who, str(info.get("looks") or "")) is not None
            except Exception:
                ok = False
            if not ok:
                continue
            info = dict(info, type="thing")
        cur = cast.get(who) or {}
        if not cur.get("looks") or cur.get("looks") == who.replace("_", " "):
            cur["looks"] = str(info.get("looks") or who.replace("_", " "))[:120]
        cur["type"] = info.get("type") if info.get("type") in ("person", "thing") else cur.get("type") or cast_kind(who)
        if cur["type"] == "person" and who in NOT_PEOPLE:
            cur["type"] = "thing"
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
        if e.get("do") in ARRIVALS and any(x["who"] == who and x.get("do") in ARRIVALS
                                            for s in shots for x in s.get("events", [])):
            continue                         # the script brings them in itself: one entrance, not two
        verb = e.get("do") if (e.get("do") in catalog.CAST_VERBS or e.get("do") in catalog.ANIMS) else "enter"
        if cast[who]["type"] == "thing" and verb in catalog.ANIMS and verb not in catalog.CAST_VERBS:
            verb = "shake"
        ev = {"who": who, "do": verb}
        if e.get("from") in catalog.FROM_SIDES:
            ev["from"] = e["from"]
        shot.setdefault("events", []).append(ev)
        _stage_for_events(shot, {})
    tidy_events(shots, cast)
    apply_styles(shots, cast)
    used = {e["who"] for s in shots for e in s.get("events", [])}
    result["cast"] = {k: v for k, v in cast.items() if k in used}
    return result


ARRIVE_VERBS = {"enter", "crash_in", "appear", "run_to", "walk_to", "fall"}
LEAVE_VERBS = {"exit", "vanish"}


def tidy_events(shots, cast):
    """One entrance per stay: someone already on stage doesn't enter again until they've left (the wizard "entered"
    three times in a row, 2026-11-27), and people are never "held" (hold = a thing in her hand). Cutaway events
    don't count - a cutaway subject comes and goes on its own. Changes `shots` in place."""
    on = set()
    for s in shots:
        evs = s.get("events")
        if not evs:
            continue
        keep = []
        for e in evs:
            who, do = e.get("who"), e.get("do")
            person = ((cast or {}).get(who) or {}).get("type", cast_kind(who or "")) == "person"
            if do == "hold" and person:
                continue
            if not e.get("cutaway") and do in ARRIVE_VERBS and who in on and do not in ("run_to", "walk_to"):
                continue
            if not e.get("cutaway"):
                if do in ARRIVE_VERBS:
                    on.add(who)
                elif do in LEAVE_VERBS:
                    on.discard(who)
            keep.append(e)
        if keep:
            s["events"] = keep
        else:
            s.pop("events", None)
    return shots


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


HOME_WORDS = re.compile(r"\b(her room|my room|my bedroom|her bedroom|at home|home|bedroom)\b", re.I)


AIR_WORDS = re.compile(r"\b(sky|skies|cloud|clouds|air|mid-?air|falling|fall|fell|float\w*|flying|fly|skydiv\w*|"
                       r"space|orbit|zero gravity|weightless|underwater|under the sea|ocean floor|deep sea|core)\b", re.I)


def match_set(place, sets, policy="reuse"):
    """The best existing set for a place description, or "new:<place>" if none fits (or policy == "new")."""
    if place.startswith("new:"):            # already decided (the Create popup's Scenes step)
        return place
    key = re.sub(r"[^a-z0-9]+", "_", place.lower()).strip("_")
    if key in sets:
        return key
    if "home" in sets and HOME_WORDS.search(place):       # her room is the home base of the channel
        return "home"
    if policy == "new":
        return "new:" + place
    q = _words(place)
    if not q:
        return "new:" + place
    best, score = None, 0.0
    airy = AIR_WORDS.search(place)
    for sid, s in sets.items():
        if s.get("air") and not airy:
            continue          # a sky / falling set only for sky words ("Deep Air Bedroom" for an alarm clock story)
        sc = fit_score(place, sid, s)
        if sc > score:
            best, score = sid, sc
    return best if best and score >= 0.5 else "new:" + place


def plan_scenes(script, start, title="", policy="reuse", ollama=None, log=print):
    """The places a script needs, in order: where it starts (start = a set id, "new:<place>" or "auto" from the
    title) and every "[@ place]" line. Each = {line (index in script.split("\\n")), place, pick (set id or
    "new:<place>"), options: up to 3 fitting set ids, first: True for the start}."""
    sets = catalog.all_sets()
    if not start or start == "auto":
        start, place0 = auto_set(title, policy, ollama, log)
    else:
        place0 = start[4:] if str(start).startswith("new:") else (sets.get(start) or {}).get("name", start)

    def options(place, pick):
        ranked = sorted(((fit_score(place, sid, s), sid) for sid, s in sets.items()), reverse=True)
        out = [pick] if pick in sets else []
        out += [sid for sc, sid in ranked if sc >= 0.25 and sid not in out]
        return out[:3]
    out = [{"line": 0, "place": place0, "pick": start, "options": options(place0, start), "first": True}]
    for i, raw in enumerate(str(script or "").split("\n")):
        head = re.match(r"^\s*\[([^\]]*)\]", raw)
        sc = head and re.search(r"@\s*([^,\]]+)", head.group(1))
        if not sc:
            continue
        place = sc.group(1).strip()
        pick = match_set(place, sets, policy)
        name = place[4:] if place.startswith("new:") else (sets[place]["name"] if place in sets else place)
        out.append({"line": i, "place": name, "pick": pick, "options": options(name, pick)})
    return out


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
GROUND_ONLY = {"walk_to", "run_to", "sneak_to", "sit", "jump", "stretch", "lie_down", "kneel", "kneel_place"}
FLOAT_LINES = 2       # script lines she floats with nothing holding her up (the lift-off line + one), then lands


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
NOT_PLACE = {"enter", "entering", "exit", "arrive", "appear", "scene", "place", "area", "somewhere"}


def place_words(place, cast=None):
    """The words that name a place the AI scene step picked: only its name (not the description after " - ", which
    repeats the line's own words - "The Void - ... where she is drifting" matched "drifting"), without cast names,
    people, stage verbs and filler. Empty = not a place ("Enter Wizard - a room with a smug wizard")."""
    name = re.split(r"\s+[-–—:(]\s*|,|\.", str(place or ""), maxsplit=1)[0]
    people = set()
    for who in cast or {}:
        people |= _words(who.replace("_", " "))
    drop = NOT_PLACE | people | {w.rstrip("s") for w in catalog.PERSON_WORDS | ROLE_PEOPLE} \
        | set(catalog.CAST_VERBS) | set(catalog.ANIMS)
    return {w for w in _words(name) if w not in drop}


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
            pw = place_words(sc["place"], result.get("cast"))
            if not pw:
                continue              # "Enter Wizard - a room with a smug wizard": a stage direction, not a place
            if not MOVE_VERBS.search(line) and not (pw & _words(line)):
                continue              # weather or talk, not a move ("then it started snowing")
            sid = str(sc.get("set") or "")
            place = str(sc["place"])
            # the AI's pick has to actually share words with the place - it likes to grab any set
            ok = policy == "reuse" and sid in sets and sid != set_name and fit_score(place, sid, sets[sid]) >= 0.34 \
                and (not sets[sid].get("air") or AIR_WORDS.search(place))
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
        g = shots[i].get("beat_group") if 0 < i < len(shots) else None
        line_has = g is not None and any(s.get("cutaway") for s in shots if s.get("beat_group") == g)
        if 0 < i < len(shots) and c.get("show") and "cutaway" not in shots[i] and not shots[i].get("events") \
                and not line_has:
            shots[i]["cutaway"] = str(c["show"])[:80]
    _merge_cutaway_beats(shots)
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


# a whole day in one video: the light goes day -> sunset -> night over the lines
# (not "all day" / "one day" / "my day": "I walked all day" turned a sky set orange, then night - 2026-11-27)
DAY_ARC = re.compile(r"\b(day in the life|from morning|morning (?:till|to|until) night|(?:24|twenty-four) hours in|"
                     r"sunrise to sunset|dawn (?:till|to|until) dusk|morning to night|day to night)\b", re.I)
INDOOR_IDS, OUTDOOR_IDS = {"cafe"}, {"park"}
FESTIVE_FX = {"confetti", "hearts", "sparkles", "music_notes", "candy", "coins", "stars"}


def _indoor(sid, sets):
    if sid in INDOOR_IDS:
        return True
    if sid in OUTDOOR_IDS:
        return False
    rec = sets.get(sid) or {}
    return rec.get("indoor") if rec else None              # None = not known (a place made at render)


def story_weather(shots, text, set_name):
    """Weather and time that follow the story, when the script didn't set them itself:
    - sad lines outdoors: rain for that line (an indoor or unknown place gets none)
    - a big celebration (celebrate / dance): confetti for that shot
    - a whole day in one video ("a day in the life", "from morning to night"): the light goes day -> sunset ->
      night over the lines (only when no shot sets a light)."""
    sets = catalog.all_sets()
    groups = {}
    for k, s in enumerate(shots):
        groups.setdefault(s.get("beat_group", f"s{k}"), []).append(k)
    for idx in groups.values():
        line = [shots[k] for k in idx]
        sad = any(s.get("expression") == "sad" for s in line)
        if sad:            # "Nobody came to my party": the word "party" gave a sad line confetti
            for s in line:
                if s.get("particles") and set(s["particles"]) <= FESTIVE_FX:
                    s.pop("particles")
        if any("particles" in s for s in line) or any(s.get("cutaway") for s in line):
            continue
        sid = line[0].get("set", set_name)
        if sad and _indoor(sid, sets) is False:
            for s in line:
                s["particles"] = ["rain"]
        for s in line:
            if s.get("action") in ("celebrate", "dance") and "particles" not in s:
                s["particles"] = ["confetti"]
    if DAY_ARC.search(text or "") and not any(s.get("light") for s in shots):
        order = list(groups.values())
        n = len(order)
        if n >= 3:
            for j, idx in enumerate(order):
                light = "day" if j < n * 0.45 else "sunset" if j < n * 0.8 else "night"
                prev = shots[order[j - 1][0]].get("_arc") if j else "day"
                shots[idx[0]]["_arc"] = light
                if light != prev:
                    shots[idx[0]]["light"] = light
            for s in shots:
                s.pop("_arc", None)


def low_poses(shots):
    """Lying down / kneeling: a close camera aimed at standing head height loses her - medium instead, and a lie
    down on a line that names a bed / sofa lies ON it (Blender finds the set's nearest one)."""
    for s in shots:
        if s.get("action") not in LOW_POSES:
            continue
        if s.get("camera") in CLOSE_CAMS and s.get("camera") != "selfie":
            s["camera"] = "medium"
        if s.get("move") == "follow":
            s["move"] = "static"
        if s["action"] == "lie_down" and "on" not in s:
            on = LIE_ON_WORDS.search(s.get("line") or "")
            if on:
                s["on"] = on.group(1).lower()


FIRE_WORDS = {"fire", "flames", "on_fire", "burning", "ablaze", "inferno"}
FIRE_OFF = {"off", "out", "none", "stop", "gone"}
# "the house is on fire", "my toast caught fire", "the burning car", "the tree burst into flames" -> what burns
FIRE_PHRASE = re.compile(r"(?:\b([a-z]+)(?:'s| is| are| was| were| just)? (?:on fire|in flames|ablaze|caught fire|"
                         r"catch(?:es|ing)? fire|burst(?:s|ing)? into flames|burning (?:up|down)|went up in flames)|"
                         r"\b(?:a|the|my|our|your|her|his) burning ([a-z]+))", re.I)
FIRE_NOT = {"it", "this", "that", "everything", "something", "world", "heart", "soul", "i", "we", "you", "she", "he",
            "they", "mouth", "tongue", "desire", "passion", "question", "here", "there"}
FIRE_HERE = re.compile(r"\b(fire!|on fire|in flames|ablaze|burst into flames)", re.I)


def fire_of(text):
    """What a line sets burning by its words: a thing's name, "here", or None ("you're fired" isn't a fire)."""
    m = FIRE_PHRASE.search(text or "")
    if m:
        w = (m.group(1) or m.group(2) or "").lower()
        if w in FIRE_NOT:
            return None                   # "my heart is on fire": a feeling, not flames
        if w and w not in FIRE_THINGS_NOT:
            return w
    return "here" if FIRE_HERE.search(text or "") else None


FIRE_THINGS_NOT = {"is", "are", "was", "were", "just"}


def fire_pass(shots):
    """Embers rise wherever something burns (on top of any particles the shot already has)."""
    for s in shots:
        if s.get("fire") and not s.get("cutaway") and "embers" not in (s.get("particles") or []):
            s["particles"] = list(s.get("particles") or []) + ["embers"]


CALM_MOVES = {"shake": "static", "orbit": "push_in"}     # a calm video never shakes; orbits read as busy


def set_mood(shots, set_name, weather=None, light=None, line_voice=None, loop_end=False, calm=False):
    """A template's mood over the whole video (after the director's own choices; the script's brackets win):
    weather = particles on every shot without any (blender_fx drops weather indoors at render);
    light = the opening's light when the first shot sets none; line_voice = a shot voice on every spoken shot
    (a calm, slower voice); calm = no shaky / orbiting cameras and no hops; loop_end = the last script line goes
    back to the opening's place, light, weather and framing, so the replay starts where it ended."""
    if not shots:
        return
    if light and not shots[0].get("light"):
        shots[0]["light"] = light
    for s in shots:
        if weather and "particles" not in s and not s.get("cutaway"):
            s["particles"] = list(weather)
        if line_voice and s.get("line") and not s.get("voice"):
            s["voice"] = dict(line_voice)
        if calm:
            if s.get("move") in CALM_MOVES:
                s["move"] = CALM_MOVES[s["move"]]
            if s.get("action") in ("jump", "celebrate", "dance", "spin", "clap"):
                s["action"] = "idle"
    if not loop_end or len(shots) < 3:
        return
    first = shots[0]
    g = shots[-1].get("beat_group")
    last = [s for s in shots if g is not None and s.get("beat_group") == g] or [shots[-1]]
    if last[0] is first:
        return
    first_set = first.get("set", set_name)
    lit = next((s.get("light") for s in reversed(shots[: shots.index(last[0])]) if s.get("light")), None)
    for k, s in enumerate(last):
        if s.get("cutaway") or s.get("show"):
            continue
        if any(x.get("set", set_name) != first_set for x in shots):
            s["set"] = first_set               # back where it began
        if k == len(last) - 1:                 # the very last frame matches the very first
            s["camera"], s["move"] = first.get("camera", "medium"), "static"
        if s.get("action") in catalog.MOVE_ANIMS:
            s["action"] = "idle"
            s.pop("to", None)
        if "particles" in first:
            s["particles"] = list(first["particles"])
    want = first.get("light")
    if want and lit and lit != want:
        last[0]["light"] = want


# small things she can pick up and show while she talks about them ("look at this cup", "my favourite book")
HOLDABLE = set("""cup mug glass bottle book notebook phone letter card map key keys pencil pen crayon brush wand umbrella
flower rose apple banana cookie cupcake donut sandwich candy lollipop sweet icecream cone plush plushie teddy toy
ball balloon remote camera ticket coin gem crystal shell leaf feather egg potion jar box gift present spoon fork
fish magnifier compass torch flashlight lantern clock watch hat sock shoe""".split())
HOLD_CUES = {"this", "my", "holding", "hold", "grab", "grabbed", "picked", "brought", "here's", "heres", "look"}
BIG_WORDS = {"giant", "huge", "big", "massive", "enormous", "gigantic", "colossal", "entire", "whole", "large",
             "tall", "towering", "mega", "jumbo"}
MAX_HOLDS = 3


def held_things(shots, cast, text_of=lambda s: s.get("line", "")):
    """She picks up the small thing a line is about ("look at this cup") and holds it out for that line; it's put
    away (vanishes) at the next line. At most MAX_HOLDS per video, never on a cutaway line, never a thing the script
    already brings in itself."""
    groups, order = {}, []
    for k, s in enumerate(shots):
        g = s.get("beat_group", f"s{k}")
        if g not in groups:
            order.append(g)
        groups.setdefault(g, []).append(k)
    made = 0
    for gi, g in enumerate(order):
        idx = groups[g]
        if made >= MAX_HOLDS or any(shots[k].get("cutaway") or shots[k].get("show") for k in idx):
            continue
        if any(shots[k].get("speaker") for k in idx):
            continue                                     # someone else's line: it's their cup, not hers
        words = re.findall(r"[a-z']+", " ".join(text_of(shots[k]) for k in idx).lower())
        thing = None
        for j, w in enumerate(words):                    # a holdable noun with "this/my/holding..." just before it
            noun = w if w in HOLDABLE else w[:-1] if w.endswith("s") and w[:-1] in HOLDABLE else None
            if noun and BIG_WORDS & set(words[max(0, j - 2):j]):
                continue                                 # "bounce on this giant shell": not in her hand
            if noun and HOLD_CUES & set(words[max(0, j - 4):j]):
                thing = noun
                break
        if not thing:
            continue
        if thing in cast or any(e.get("who") == thing for s in shots for e in s.get("events") or []):
            continue
        cast[thing] = {"type": "thing", "looks": f"a small hand-held {thing}", "held": True}
        shots[idx[0]].setdefault("events", []).append({"who": thing, "do": "hold"})
        for k in idx:                                    # she shows it in her hand - no pointing at it with that hand
            if shots[k].get("action") == "point":
                shots[k]["action"] = "idle"
                shots[k].pop("at", None)
        if gi + 1 < len(order):
            shots[groups[order[gi + 1]][0]].setdefault("events", []).append({"who": thing, "do": "vanish"})
        made += 1


FACE_CUES = [   # close-up reactions: the face shapes she has (blender_build FACE wink / blush / eyeroll)
    ("wink", re.compile(r"\b(just kidding|kidding|jk|between (?:you and me|us)|(?:our|a) (?:little )?secret|"
                        r"trust me|wink\w*|hehe+|you know what i mean)\b", re.I)),
    ("blush", re.compile(r"\b(blush\w*|embarrass\w*|aww+|so cute|stop it|too kind|flatter\w*|crush|shy|"
                         r"compliment\w*|oh my|you think so)\b", re.I)),
    ("eyeroll", re.compile(r"\b(ugh+|seriously|whatever|obviously|as if|of course not|so boring|typical|"
                           r"here we go again|eye ?roll\w*|yeah,? right)\b", re.I)),
]
MAX_FACES = 3


def face_closeups(shots, text_of=lambda s: s.get("line", "")):
    """A wink, a blush or an eye-roll in a close-up on lines that call for it ("just kidding", "aww, stop it",
    "ugh, seriously?") - only when the script set neither the expression nor the camera; never the opening line
    (the hook), someone else's line or a cutaway; at most MAX_FACES per video."""
    groups, order = {}, []
    for k, s in enumerate(shots):
        g = s.get("beat_group", f"s{k}")
        if g not in groups:
            order.append(g)
        groups.setdefault(g, []).append(k)
    made = 0
    for gi, g in enumerate(order):
        idx = groups[g]
        if gi == 0 or made >= MAX_FACES:
            continue
        line = [shots[k] for k in idx]
        if any(s.get("speaker") or s.get("cutaway") or s.get("_set_expr") or s.get("_set_cam") for s in line):
            continue
        text = " ".join(text_of(s) for s in line)
        face = next((f for f, rx in FACE_CUES if rx.search(text)), None)
        if not face:
            continue
        # the beat with the cue word gets the close-up (the whole line keeps the face)
        hit = next((s for s in line if dict(FACE_CUES)[face].search(text_of(s))), line[0])
        for s in line:
            s["expression"] = face
        if hit.get("action") not in MOVE_ANIMS_SET:
            hit["camera"], hit["move"] = "closeup", "static"
        made += 1


MOVE_ANIMS_SET = set(catalog.MOVE_ANIMS)


REACTION_FOR = [   # (shot test, her reaction sound) - run_episode.REACT_TEXT says them in her own voice
    (lambda s: s.get("expression") == "surprised", "gasp"),
    (lambda s: s.get("action") == "laugh", "giggle"),
    (lambda s: s.get("action") == "think", "hmm"),
    (lambda s: s.get("action") == "celebrate", "yay"),
    (lambda s: s.get("expression") == "blush", "aww"),
    (lambda s: s.get("action") == "wave", "nya"),
]
MAX_REACTIONS, REACTION_GAP = 3, 2


def reactions(shots):
    """Her own little sounds before fitting lines (a gasp when surprised, a giggle when she laughs, "hmm" when she
    thinks...): on the first beat of her own lines, at most MAX_REACTIONS per video, REACTION_GAP lines apart,
    never on a cutaway (she isn't on screen) or someone else's line."""
    groups, order = {}, []
    for k, s in enumerate(shots):
        g = s.get("beat_group", f"s{k}")
        if g not in groups:
            order.append(g)
        groups.setdefault(g, []).append(k)
    made, last = 0, -99
    for gi, g in enumerate(order):
        first = shots[groups[g][0]]
        if made >= MAX_REACTIONS or gi - last <= REACTION_GAP or first.get("speaker") or first.get("cutaway") \
                or "react" in first:
            continue
        r = next((r for test, r in REACTION_FOR if test(first)), None)
        if r:
            first["react"] = r
            made, last = made + 1, gi


TO_VIEWER = re.compile(r"\b(comment|let me know|follow|subscribe|what do you think|tell me|you guys|everyone watching|"
                       r"which (?:one|side) are you|like and)\b", re.I)


def conversations(shots, mains):
    """Two main characters talking with each other: every line of a back-and-forth gets "talk_to" (who they're
    answering, else who answers them) - Blender turns the speaker towards them - and every other line of the run
    is a two-shot of both ("both"), unless the script chose the camera. Not with a single main character."""
    if len(mains) < 2:
        return
    groups, order = {}, []
    for k, s in enumerate(shots):
        g = s.get("beat_group", f"s{k}")
        if g not in groups:
            order.append(g)
        groups.setdefault(g, []).append(k)
    who = [shots[groups[g][0]].get("speaker") or "main" for g in order]
    run = 0
    for gi, g in enumerate(order):
        sp = who[gi]
        prev = who[gi - 1] if gi else None
        nxt = who[gi + 1] if gi + 1 < len(order) else None
        to = prev if prev in mains and prev != sp else nxt if nxt in mains and nxt != sp else None
        line_text = " ".join(shots[k].get("line", "") for k in groups[g])
        if gi == 0 or sp not in mains or not to or TO_VIEWER.search(line_text):   # the hook / "comment below!"
            run = 0
            continue
        for k in groups[g]:
            shots[k]["talk_to"] = to
        first = shots[groups[g][0]]
        if run % 2 == 1 and gi and not first.get("_set_cam") and not first.get("cutaway"):
            first["both"] = True
            if first.get("camera") in ("closeup", "macro", "dramatic", "back", "tiny"):
                first["camera"] = "medium"
        run += 1
CUTAWAY_MIN_WORDS = 4


def _merge_cutaway_beats(shots):
    """A cutaway on a beat of 1-3 words ("Number 5:") was on screen for half a second before cutting back to her:
    the next beats of the same line join it until it has CUTAWAY_MIN_WORDS words ("Number 5: The Cheetah!")."""
    k = 0
    while k < len(shots):
        sh = shots[k]
        g = sh.get("beat_group")
        while sh.get("cutaway") and g is not None and len(str(sh.get("line", "")).split()) < CUTAWAY_MIN_WORDS \
                and k + 1 < len(shots) and shots[k + 1].get("beat_group") == g \
                and not shots[k + 1].get("cutaway") and not shots[k + 1].get("events") \
                and shots[k + 1].get("set") == sh.get("set") and shots[k + 1].get("speaker") == sh.get("speaker"):
            nxt = shots.pop(k + 1)
            sh["line"] = f"{sh.get('line', '')} {nxt.get('line', '')}".strip()
            if nxt.get("wipe"):
                sh["wipe"] = True
        k += 1


ENTER_WORDS = re.compile(r"^(?:enter|enters|entering|in comes|here comes|cue)\s+\+([A-Za-z0-9_]+)\s*[,.!:;-]?\s*", re.I)


def tidy_line(raw):
    """Fix the AI's script slips before a line is cut into beats (cut first, half a bracket was spoken):
    "[mid, sneeze, facepalm) Ahhh!" / "(facepalm] ..." -> one bracket; "Wizard: +Wizard: This..." -> one label;
    "Enter +wizard, smug He just..." (a stage direction in the spoken words) -> "[+wizard enter] He just..."."""
    s = raw
    b = re.match(r"^\s*([\[(])([^\])\[(]{0,160})([\])])", s)
    if b and b.group(1) + b.group(3) in ("[)", "(]"):           # opened one way, closed the other
        s = s[:b.start(1)] + "[" + b.group(2) + "]" + s[b.end(3):]
    while True:     # "[wide, scared] [+past_self appear ghost] ..." - two groups; the second was spoken
        g = re.match(r"^(\s*)\[([^\]]*)\]\s*\[([^\]]*)\]", s)
        if not g:
            break
        s = g.group(1) + "[" + ", ".join(x for x in (g.group(2).strip(), g.group(3).strip()) if x) + "]" + s[g.end():]
    m = re.match(r"^(\s*(?:\[[^\]]*\]\s*)?)(.*)$", s, re.S)
    dirs, text = m.group(1), m.group(2)
    text = re.sub(r"^\+?([A-Za-z][\w '-]{0,30}?)\s*:\s*\+?\1\s*:\s*", r"\1: ", text, flags=re.I)
    extra = []
    while True:
        e = ENTER_WORDS.match(text)
        if not e:
            break
        extra.append(f"+{e.group(1).lower()} enter")
        text = text[e.end():]
        mood = re.match(r"([a-z]+)\s*[,.!:;-]?\s+(?=[A-Z])", text)    # "smug He just..." - how they come in
        if mood and (mood.group(1) in catalog.EXPRESSIONS or mood.group(1) in MOOD_WORDS):
            text = text[mood.end():]
    if extra:
        dirs = (dirs.rstrip()[:-1] + ", " if dirs.strip() else "[") + ", ".join(extra) + "] "
    return dirs + text


LABEL_DROP = {"the", "my", "your", "old", "young", "little", "big"} | set(STYLE_OPTIONS)


def label_speaker(label, speakers):
    """The speaker a "Name:" label means. Exact first; else a label of two or more words that names a speaker with
    her own name or a style word mixed in: "Past Lavender:" = past_self, "Ghost Mom:" = mom. Speaker names in the
    label are dropped (her name), the rest must all be words of ONE speaker's name. None = not a speaker."""
    if not speakers:
        return None
    l = re.sub(r"\s+", " ", str(label).strip().lower())
    if l in speakers:
        return speakers[l]
    words = l.split()
    if len(words) < 2:
        return None
    rest = [w for w in words if w not in speakers and w not in LABEL_DROP] or [w for w in words if w not in LABEL_DROP]
    for want in (rest, [w for w in rest if w not in speakers]):
        hits = {v for k, v in speakers.items() if want and all(w in re.split(r"[ _]+", k) for w in want)}
        if len(hits) == 1:
            return hits.pop()
    return None


def fix_labels(lines, speakers):
    """Rewrite a label that label_speaker understands but isn't a speaker's own name ("Past Lavender:") to that
    speaker's name, so beat cutting and the director both see it (it was cut into "Past" / "Lavender: ...")."""
    out = []
    for raw in lines:
        head = re.match(r"^\s*(\[[^\]]*\]\s*)?", raw).group(0)
        m = SPEAKER.match(raw[len(head):])
        if m and m.group(1).strip().lower() not in speakers:
            who = label_speaker(m.group(1), speakers)
            if who:
                raw = head + who.replace("_", " ") + ": " + raw[len(head) + m.end():]
        out.append(raw)
    return out


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


EXITS = ("door", "far")
ARRIVAL_CAMS = ("wide", "medium", "high", "low")   # blender_build frames her + an arrival together only for these
PLAIN_MARKS = ("center", "front", "left", "right", "back", "far")   # places, not things she could point at                 # walking there mid-line looks like she's leaving
CLOSE_CAMS = ("closeup", "macro", "dramatic", "selfie")   # too tight to follow a walk (the camera ends up in her hair)
HAPPY_ANIMS = ["nod", "laugh", "clap", "idle", "celebrate", "nod", "laugh", "idle"]   # happy lines that aren't greetings
SHOW_ANIMS = ("wave", "blow_kiss", "clap", "celebrate", "point")   # gestures that need the front and her hands


def _xy(sets, set_id, name):
    """A mark's (x, y) in a set, or None. y grows away from the camera."""
    m = GENERIC_MARKS if str(set_id).startswith("new:") else (sets.get(set_id) or {}).get("marks") or {}
    try:
        v = m.get(name) if isinstance(m, dict) else None
        return float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError):
        return None


def _opening_walk(sets, set_id, marks, pos):
    """(from, to) for the opening walk, so she walks TOWARD the camera (face visible) instead of away from it:
    to a mark nearer the camera if there is one, else in from a mark further back to where she starts."""
    p = _xy(sets, set_id, pos)
    xy = {m: _xy(sets, set_id, m) for m in marks if m != pos and m not in EXITS}
    xy = {m: v for m, v in xy.items() if v}
    if p and xy:
        nearer = [m for m, v in xy.items() if v[1] < p[1] - 1.0]
        if nearer:
            return pos, min(nearer, key=lambda m: xy[m][1])
        back = [m for m, v in xy.items() if v[1] > p[1] + 1.0]
        if back:
            return ("center" if "center" in back else
                    min(back, key=lambda m: (xy[m][0] - p[0]) ** 2 + (xy[m][1] - p[1]) ** 2)), pos
    return pos, next((m for m in marks if m not in (pos, "front", "far")), "center")


def _pick_dest(marks, pos, visits):
    """Where a walk with no "to" goes: a mark she's been to least, not where she is, not an exit."""
    options = [m for m in marks if m != pos and m not in EXITS] or [m for m in marks if m != pos] or ["center"]
    return min(options, key=lambda m: (visits.get(m, 0), options.index(m)))


def direct(script, set_name="cafe", start=None, cast=None, scene_policy="reuse", speakers=None, beat_words=0,
           beat_sets=None, walk_every=0, wipe_every=0, move_every=0, opening="hook", title="", story_fx=True,
           camera=None, weather=None, light=None, line_voice=None, loop_end=False, calm=False):
    """weather / light / line_voice / loop_end / calm: a template's mood ("Deep theory": rain, night, a slower calm
    voice on every line, the last line back in the opening's place and framing, no gasps or comic face close-ups).
    walk_every: every Nth beat she walks, with the camera following her (0 = never), never within WALK_GAP shots
    of another walk. move_every: every Nth beat the camera moves instead (orbit / push in / pull out from a new
    angle) - she walked about too much when every 3rd beat was a walk.
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
    lines = [tidy_line(l) for l in (script or "").splitlines() if l.strip()]
    speakers = dict(speakers or {})
    brought = [ev["who"] for l in lines for ev in parse_directions(l, marks)[0].get("events", [])]
    for who in brought:
        if cast_kind(who) == "person" or cast_style(who):   # "[+mom enter] ..." then "Mom: ..." - mom says it
            speakers.setdefault(who.replace("_", " "), who)
            speakers.setdefault(who, who)
    for who in (cast or {}):               # cast people can say lines too: "Clerk: ..." or "store clerk: ..."
        if ((cast or {})[who] or {}).get("type") != "thing":
            speakers.setdefault(who.replace("_", " ").lower(), who)
            speakers.setdefault(who.lower(), who)
    lines = fix_labels(lines, speakers)
    pairs = expand_beats_grouped(lines, beat_words, speakers)
    lines, line_groups = [t for t, _ in pairs], [g for _, g in pairs]
    line_text = {}                         # beat group -> the whole script line (a pointed-at thing may be named later)
    for t, g in pairs:
        if g is not None:
            line_text[g] = f"{line_text.get(g, '')} {t}"
    start = start if start in start_marks else ("front" if "front" in start_marks else start_marks[0])
    shots, prev_cam, pos = [], None, start
    visits, prev_set = {}, set_name        # where she has walked (walks spread over the set); the last shot's set
    cast = dict(cast or {})
    for who in cast:                       # cast people can say lines too: "Clerk: ..." or "store clerk: ..."
        if (cast[who] or {}).get("type") != "thing":
            speakers.setdefault(who.replace("_", " ").lower(), who)
            speakers.setdefault(who.lower(), who)
    cur_set = set_name                     # scene changes ("@ place") carry on until the next one
    burning = []                           # what's on fire ("[fire: window]" ... "[fire: off]")
    shown = None                           # the explainer object on stage ("[show: toilet]"): {who, at, open}
    airborne = holding = False             # floating (float_up ... land), holding balloons
    float_line = line_no = 0               # the script line she lifted off on / this beat's script line (lines are beats)
    set_k = 0                              # beat_sets: each script line starts in the next set of the list
    for i, raw in enumerate(lines):
        starts_line = i == 0 or line_groups[i] is None or line_groups[i - 1] != line_groups[i]
        if starts_line and i > 0:
            line_no += 1
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
        if d.get("want") in catalog.CAST_VERBS:     # "[@library enter]": a verb for other things, not a pose to make
            d.pop("want")
        if d.get("light") and i and not TIME_WORDS.search(text):
            # the AI uses [night] like a mood ("[night, surprised] Wait... why is the sun here?") - it went dark at
            # noon. The light only changes on a line that talks about the time of day (or sleep / waking up).
            d.pop("light")
        show_now, shot_events_pre = None, []
        if "show" in d:
            # "[show: toilet]" brings an explainer object on beside her (it stays until another is shown or
            # "[show: off]"); "[show: toilet open]" takes its cover off; "[show: toilet flap]" = close on that part
            ws = [w for w in re.split(r"[\s]+", d.pop("show")) if w]
            if ws and ws[0] in ("off", "none", "away", "hide"):
                if shown:
                    shot_events_pre.append({"who": shown["who"], "do": "vanish"})
                shown = None
            elif ws:
                who = re.sub(r"[^a-z0-9_]+", "", ws[0])[:24]
                if shown and who in SHOW_PLACEHOLDERS:
                    who = shown["who"]             # "[show: thing part]" / "[show: it open]": the one on stage
                is_open = any(w in ("open", "inside", "opened", "cut", "cutaway", "cross_section") for w in ws[1:])
                part = next((re.sub(r"[^a-z0-9_]+", "", w) for w in ws[1:]
                             if w not in ("open", "inside", "opened", "cut", "cutaway", "cross_section", "closed")
                             and w not in SHOW_PLACEHOLDERS), None)     # "[show: eye model]": not a part
                if who and (not shown or shown["who"] != who):
                    if shown:
                        shot_events_pre.append({"who": shown["who"], "do": "vanish"})
                    at = [0.0, 0.0]                  # beside where she ends up this shot (set below)
                    shot_events_pre.append({"who": who, "do": "appear", "to": at})
                    cast[who] = {**(cast.get(who) or {}), "type": "thing", "looks": who.replace("_", " "),
                                 "explainer": True}
                    shown = {"who": who, "at": at, "open": False}
                if shown:
                    shown["open"] = shown["open"] or is_open or bool(part)    # a part close-up shows the inside
                    show_now = {"who": shown["who"], "open": shown["open"], **({"part": part} if part else {})}
        mood = mood_of(text)
        action, expr, cam, move = MOOD[mood]
        if pose_of(text) and mood not in ("angry", "scared"):
            action = pose_of(text)                   # "at her grave", "lie down on the bed": whatever the mood
        elif mood in ("neutral", "happy", "question", "smug") and action_of(text):
            action = action_of(text)                 # the words say what she does
        elif mood in ("neutral", "happy") and not starts_line and shots \
                and shots[-1].get("beat_group") == line_groups[i] \
                and shots[-1].get("expression") in ("angry", "surprised", "scared", "sad"):
            # the rest of an emotional line ("Fine. I'll hiss back." ... "Hsssss!") keeps its feeling
            action, expr = shots[-1]["action"], shots[-1]["expression"]
            if action in catalog.MOVE_ANIMS:
                action = "idle"
        if mood == "happy" and action == "wave":
            # a wave is a greeting (hi/bye words are caught by action_of above); other happy lines get an upbeat
            # move that changes from shot to shot - every "nya!" used to be a wave
            recent = [s.get("action") for s in shots[-2:]]
            action = next((a for a in HAPPY_ANIMS[i % len(HAPPY_ANIMS):] + HAPPY_ANIMS if a not in recent), "nod")
        shot = {}
        if i == 0 and opening == "hook" and "action" not in d and "want" not in d and not shown:
            # the hook: the first line is said straight to the camera while it pushes in on her (a walk-in spent
            # the first seconds - the ones that decide if people stay - on her feet). A close-up: a "medium" push-in
            # starts at 1.3x its 4 m, so the first test video opened on a small full-body figure
            shot.update(action=action if action not in catalog.MOVE_ANIMS else "idle", camera="closeup",
                        move="push_in", expression=expr if expr != "neutral" else "happy")
        elif i == 0 and "action" not in d and "want" not in d:
            # open by walking in, toward the camera so her face is seen (she may start further back)
            origin, dest = _opening_walk(sets, cur_set, marks, pos)
            if cur_set == set_name and origin in start_marks:
                start = pos = origin
            shot.update(action="walk_to", to=dest, camera="wide", move="static",
                        expression=expr if expr != "neutral" else "happy")
        else:
            if i == len(lines) - 1 and action in ("idle", "wave") and "action" not in d:
                action, cam, move = "nod", "wide", "orbit"
            if cam is None or cam == prev_cam:
                cam = next(c for c in CAM_CYCLE[i % len(CAM_CYCLE):] + CAM_CYCLE if c != prev_cam)
            shot.update(action=action, camera=cam, move=move, expression=expr)
            walked = any(s.get("action") in catalog.MOVE_ANIMS for s in shots[-WALK_GAP:])
            if walk_every and i % walk_every == walk_every - 1 and action in ("idle", "wave", "nod") \
                    and "action" not in d and len(text.split()) > 2 and not walked and not shown \
                    and d.get("camera") not in CLOSE_CAMS:   # not on a short "Nya!", nor in a close shot asked for
                shot.update(action="walk_to", camera="medium", move="follow")     # a tracking shot as she walks
            elif move_every and i % move_every == move_every - 1 and move == "static" \
                    and "camera" not in d and "move" not in d:
                cb = CAMERA_BEATS[(i // move_every) % len(CAMERA_BEATS)]
                if cb[0] == prev_cam:
                    cb = CAMERA_BEATS[(i // move_every + 1) % len(CAMERA_BEATS)]
                shot.update(camera=cb[0], move=cb[1])
        hook_cam = shot.get("camera") if i == 0 and opening == "hook" and shot.get("move") == "push_in" else None
        fire_d = d.pop("fire", None)
        if not fire_d and fire_of(text):
            fire_d = [fire_of(text)]
        for f in fire_d or []:              # what burns carries on from shot to shot until "[fire: off]"
            words = f.split()
            if f in FIRE_OFF:
                burning.clear()
            elif len(words) > 1 and words[-1] in FIRE_OFF:
                burning[:] = [b for b in burning if b != "_".join(words[:-1])]
            elif "_".join(words) not in burning:
                burning.append("_".join(words))
        shot.update(d)
        if burning:
            shot["fire"] = list(burning)
        if "expression" in d:
            shot["_set_expr"] = True     # the script chose it: face_closeups leaves it
        if "camera" in d:
            shot["_set_cam"] = True
        if hook_cam and shot.get("camera") in ("wide", "high", "tiny", "side", "back", "low"):
            shot["camera"], shot["move"] = hook_cam, "push_in"   # the first seconds are on her face
        if shot_events_pre:
            shot["events"] = shot_events_pre + list(shot.get("events") or [])
        for ev in shot_events_pre:
            if ev.get("do") == "appear" and shown and ev["who"] == shown["who"]:
                # beside where she stands at the end of this shot (the opening line may walk her in), on the
                # side towards the middle of the set
                end = shot.get("to") if shot.get("action") in catalog.MOVE_ANIMS and shot.get("to") else pos
                me = (list(end) if isinstance(end, (list, tuple)) else _xy(sets, cur_set, end)) or (0.0, 0.0)
                side = -1.0 if me[0] > 0.3 else 1.0
                ev["to"][:] = [round(me[0] + side * 1.5, 2), round(me[1] + 0.35, 2)]
        if shown:
            # an explainer object is on stage: every shot carries it (its parts move on their words in any shot)
            shot["show"] = show_now or {"who": shown["who"], "open": shown["open"]}
            if show_now and show_now.get("part") and "camera" not in d:
                shot.update(camera="closeup", move="push_in")          # close on the part being talked about
            elif show_now and "camera" not in d:
                shot.update(camera="medium", move="static")            # her and the object, side by side
                if "action" not in d and "want" not in d and shot.get("action") not in catalog.MOVE_ANIMS:
                    shot.update(action="point", at=shown["at"])   # she points at it (an opening walk-in stays a walk)
            elif "camera" not in d and shot.get("camera") in ("side", "back", "silhouette", "tiny", "macro"):
                shot["camera"] = "medium"     # cameras that would lose the object
        if shot.get("action") in catalog.MOVE_ANIMS and shot.get("camera") in CLOSE_CAMS and "camera" not in d:
            shot.update(camera="medium", move="follow")      # a walk gets a tracking shot, not an eye close-up
        if shot.get("action") in SHOW_ANIMS and "camera" not in d \
                and shot.get("camera") in CLOSE_CAMS + ("side", "back", "silhouette"):
            shot["camera"] = "medium"     # a wave seen from the front with her hands in frame (closeups cut them off)
        if i and cur_set != prev_set and "camera" not in d:
            shot.update(camera="wide", move="static")        # a new place opens on a wide shot of it
        prev_set = cur_set
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
        elif airborne and not holding and line_no >= float_line + FLOAT_LINES and "action" not in d:
            # nothing holds her up: she comes down after the lift-off line and the next one. Writers ask for
            # [float_up] and never land her - she floated the rest of the video (two production videos, 2026-11-27)
            shot["action"] = "land"
        if shot.get("action") == "float_up":
            airborne = True
            float_line = line_no
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
            shot.setdefault("to", _pick_dest(marks, pos, visits))
            a_, b_ = _xy(sets, cur_set, pos), _xy(sets, cur_set, shot["to"]) if isinstance(shot["to"], str) else None
            if a_ and b_ and b_[1] - a_[1] > 1.0 and abs(b_[1] - a_[1]) > abs(b_[0] - a_[0]) \
                    and shot.get("camera") not in ("lead", "back", "side", "silhouette", "tiny"):
                # walking away from the camera: from the front that's her back for the whole line - a camera
                # ahead of her looking back shows her face (side still showed her three-quarters from behind).
                # Also when the script named the camera: "[mid, run_to, center]" was her back (2026-11-27)
                shot.update(camera="lead", move="follow")
            pos = shot["to"]
            visits[pos] = visits.get(pos, 0) + 1
        elif shot.get("action") == "point":
            # what she points at: "[point machine]", else a place named in the line, else the thing she stands at
            whole = line_text.get(line_groups[i], raw) if line_groups[i] is not None else raw
            words = set(re.findall(r"[a-z]+", re.sub(r"\[[^\]]*\]", " ", whole.lower())))
            named = [m for m in marks if m not in PLAIN_MARKS and set(m.split("_")) <= words]
            near = pos if pos in marks and pos not in PLAIN_MARKS and HANDLING.search(text) else None
            at = shot.get("at") or shot.pop("to", None) or (named[0] if named else None) or near
            if at:
                shot["at"] = at
                a_ = _xy(sets, cur_set, pos)
                b_ = at if isinstance(at, (list, tuple)) else _xy(sets, cur_set, at)
                if a_ and b_ and b_[1] - a_[1] > 1.0 and abs(b_[0] - a_[0]) < b_[1] - a_[1] \
                        and "camera" not in d:
                    # it's behind her: from the front no arm pose reads as "back there" (her arm only swings out
                    # sideways), from the side the arm reaching back and the thing itself are both in frame
                    shot.update(camera="side", move="static")
        else:
            shot.pop("to", None)
        # "+mom enter from_left Mom! You're..." - a stage direction the AI wrote after the brackets: it was spoken
        # and captioned ("from left mom"). A leading +name followed by verbs / from_x / places is a direction.
        lead = re.match(r"\s*\+([A-Za-z0-9_]+)((?:\s+[a-z_]+)*)", text)
        if lead:
            words = lead.group(2).split()
            n = 0
            while n < len(words) and (words[n] in catalog.CAST_VERBS or words[n] in catalog.ANIMS
                                      or words[n].startswith("from_") or words[n] in marks):
                n += 1
            if n:
                who = lead.group(1).lower()[:24]
                ev = {"who": who, "do": next((w for w in words[:n] if w in catalog.CAST_VERBS or w in catalog.ANIMS), "enter")}
                side = next((w[5:] for w in words[:n] if w.startswith("from_") and w[5:] in catalog.FROM_SIDES), None)
                if side:
                    ev["from"] = side
                if not any(e["who"] == who and e.get("do") == ev["do"] for e in shot.get("events") or []):
                    shot.setdefault("events", []).append(ev)
                cast.setdefault(who, {"type": cast_kind(who), "looks": who.replace("_", " ")})
                rest = lead.group(2).split(None, n)
                text = (rest[n] if len(rest) > n else "") + text[lead.end():]
        for who in re.findall(r"\+([a-z0-9_]+)", text, re.I):    # "Hi there, +tiny_dragon!" (outside the brackets)
            who = who.lower()[:24]
            if who not in cast and not any(e["who"] == who for s in shots for e in s.get("events", [])):
                shot.setdefault("events", []).append({"who": who, "do": "enter"})
                cast[who] = {"type": cast_kind(who), "looks": who.replace("_", " ")}
        text = re.sub(r"\+([A-Za-z0-9_]+)", lambda m: m.group(1).replace("_", " "), text)   # said as "tiny dragon"
        shot["line"] = re.sub(r"\s{2,}", " ", re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text)).strip() or text
        if "sfx" not in shot:
            # a trigger word always counts; the action's sound only on a line's first beat, and never the same
            # sound twice in a row inside one line ("" = none, so the render doesn't add it back)
            fx = sfxlib.trigger(text) or (sfxlib.ACTION_SFX.get(shot.get("action") or "") if starts_line else None)
            same_line = not starts_line and shots and shots[-1].get("beat_group") == shot.get("beat_group")
            if fx and same_line and shots[-1].get("sfx") == fx:
                fx = None
            if fx:
                shot["sfx"] = fx
            elif sfxlib.suggest(text, shot.get("action")):
                shot["sfx"] = ""
        prev_cam = shot["camera"]
        shots.append(shot)
    # someone who walks in and talks in the same shot says the line walking, often with their back to the camera:
    # they arrive during the shot before instead, so they're there and turned to her when they speak
    for k in range(1, len(shots)):
        sp = shots[k].get("speaker")
        evs = shots[k].get("events") or []
        arrive = [e for e in evs if e["who"] == sp and e.get("do") in ("enter", "run_to", "walk_to", "crash_in")]
        if not arrive or shots[k - 1].get("set", set_name) != shots[k].get("set", set_name) \
                or any(e["who"] == sp for e in shots[k - 1].get("events") or []) or shots[k - 1].get("cutaway"):
            continue
        for e in arrive:
            evs.remove(e)
            shots[k - 1].setdefault("events", []).append(e)
        if shots[k - 1].get("camera") not in ARRIVAL_CAMS:
            shots[k - 1]["camera"] = "medium"            # wide enough to see them arrive beside her
        if not evs:
            shots[k].pop("events")
    # she walks too much (the user, twice): at most MAX_WALKS walks in a video, the opening walk-in included -
    # later ones stay where she is and the camera does the moving
    walks = [k for k, s in enumerate(shots) if s.get("action") in catalog.MOVE_ANIMS]
    for k in walks[MAX_WALKS:]:
        s = shots[k]
        s["action"] = "look_around" if s.get("expression") in ("surprised", "scared") else "idle"
        s.pop("to", None)
        if s.get("move") == "follow":
            s["move"] = "push_in"
    if story_fx:
        story_weather(shots, f"{title} {script}", set_name)
        held_things(shots, cast)
        if not calm:
            face_closeups(shots)
    conversations(shots, {"main"} | set((speakers or {}).values()))
    if story_fx and not calm:
        reactions(shots)
    low_poses(shots)
    fire_pass(shots)
    set_mood(shots, set_name, weather=weather, light=light, line_voice=line_voice, loop_end=loop_end, calm=calm)
    if camera in catalog.CAMERAS:          # a template that films the whole video one way ("Talk to you": selfie)
        for s in shots:                    # - also over the writer's own camera words ([wide] broke the phone call)
            if not s.get("cutaway") and not s.get("show"):
                s["camera"], s["move"] = camera, "static"
                if s.get("action") in catalog.MOVE_ANIMS:
                    s["action"] = "idle"
                    s.pop("to", None)
    for s in shots:
        s.pop("_set_expr", None)
        s.pop("_set_cam", None)
    _merge_cutaway_beats(shots)
    tidy_events(shots, cast)
    apply_styles(shots, cast)
    used = {e["who"] for s in shots for e in s.get("events", [])}
    return {"start": start,
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
