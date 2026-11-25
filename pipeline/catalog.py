"""
What episodes can use: animations, expressions, cameras, camera moves, sets and their marks.
Shared by the Blender builder (which implements them), the web app (which shows them as
dropdowns) and the auto-director. Plain Python - no Blender imports.
"""

ANIMS = {
    # name: (description, moves the character to a mark?)
    "idle": ("Stand and breathe", False),
    "turn": ("Turn to face a direction (use 'face')", False),
    "walk_to": ("Walk to a mark", True),
    "run_to": ("Run to a mark", True),
    "sneak_to": ("Sneak to a mark", True),
    "jump": ("Jump (times, height)", False),
    "wave": ("Wave", False),
    "surprised": ("Jump back in surprise", False),
    "sad": ("Droop, ears down", False),
    "angry": ("Stomp, fists up", False),
    "think": ("Hand to chin", False),
    "laugh": ("Laugh, hands on belly", False),
    "dance": ("Dance", False),
    "spin": ("Spin around (turns)", False),
    "celebrate": ("Hop with arms up", False),
    "nod": ("Nod yes", False),
    "shake_head": ("Shake head no", False),
    "point": ("Point forward", False),
    "stretch": ("Cat stretch", False),
    "sit": ("Sit down", False),
    "look_around": ("Look left and right", False),
    "scared": ("Tremble, hands up", False),
    "fall": ("Skydive / fall through the air", False),
    "float": ("Float weightless (space, under water)", False),
    "float_up": ("Lift off the ground and float up (balloons!) - stays up until land", False),
    "land": ("Come back down to the ground", False),
    "blow_kiss": ("Blow a kiss", False),
    "clap": ("Clap hands together", False),
    "bow": ("Bow politely", False),
    "sneeze": ("Sneeze: head back, then snap forward", False),
    "facepalm": ("Hand to the forehead, a sigh", False),
    "shiver": ("Shiver from the cold, arms hugged in", False),
}
MOVE_ANIMS = {k for k, (_, moves) in ANIMS.items() if moves}

# animations made as data (pipeline/animlib.py, assets/anims/*.json) are actions too - in script brackets, the
# Create page and the AI writer's list. The built-in "x_" examples only prove the format (they copy built-ins).
try:
    import animlib as _animlib
    for _n, _a in _animlib.library().items():
        usable = _a.get("checked") is not False or (_a.get("score") or 0) >= 5   # not ones that failed the check
        if not _n.startswith("x_") and _n not in ANIMS and usable:
            ANIMS[_n] = (_a["description"] or _n.replace("_", " "), False)
except Exception as _exc:          # a broken library never stops the studio
    print(f"[catalog] animations library skipped: {_exc}")

EXPRESSIONS = ["neutral", "happy", "surprised", "angry", "sad", "smug", "scared"]

CAMERAS = {
    "wide": "Whole scene",
    "medium": "Knees up",
    "closeup": "Head and shoulders",
    "side": "From the side",
    "low": "Low heroic angle",
    "high": "From above",
    "dramatic": "Tight, off-centre",
    "back": "Over the shoulder from behind",
    "macro": "Close-up on the eyes",
    "tiny": "Tiny figure in a big scene",
    "silhouette": "Low, from behind (a dark shape)",
}

MOVES = {
    "static": "Camera stays still",
    "push_in": "Slowly move closer",
    "pull_out": "Slowly move away",
    "orbit": "Circle around",
    "follow": "Follow the character",
    "shake": "Handheld shake",
}

FACING = ["camera", "left", "right", "away"]
# The finished video's language. Scripts are written in English; at render the spoken lines, captions, title and
# end card are translated (Ollama) and spoken by a voice of that language. Your cloned voice (Chatterbox) only
# speaks English, so other languages use Microsoft Edge voices: "female"/"male" below. To add a language, add an
# entry with its Edge voices (python -m edge_tts --list-voices).
LANGUAGES = {
    "en": {"name": "English", "native": "English"},
    "lt": {"name": "Lithuanian", "native": "Lietuvių", "female": "lt-LT-OnaNeural", "male": "lt-LT-LeonasNeural"},
}
# a shot can change the light from that shot on (blender_build LIGHT_KEYS): [night] in the script, or the Light picker
LIGHTS = {"day": "Day", "sunset": "Sunset", "night": "Night", "dawn": "Dawn"}
LIGHT_ALIASES = {"dusk": "sunset", "evening": "sunset", "sunrise": "dawn", "morning": "dawn", "midnight": "night",
                 "noon": "day", "daytime": "day", "nighttime": "night"}

# ---- the rest of the cast: other people and things that show up in a scene ("+name verb" in brackets)
# verb: (description, who can do it, seconds it takes, seconds until the "hit", default sound)
CAST_VERBS = {
    "enter":    ("Comes in from the side", "both", 1.4, None, None),
    "exit":     ("Leaves to the side", "both", 1.4, None, None),
    "crash_in": ("Smashes in fast (debris, shake)", "thing", 0.55, 0.55, "boom"),
    "fall":     ("Drops from the sky and lands", "thing", 0.8, 0.8, "stomp"),
    "fly_by":   ("Flies across and away", "thing", 1.6, None, "whoosh"),
    "appear":   ("Pops into existence", "both", 0.4, 0.0, "pop"),
    "vanish":   ("Shrinks away", "both", 0.4, 0.0, "pop"),
    "bounce":   ("Bounces on the spot", "thing", 1.2, None, None),
    "spin":     ("Spins on the spot", "both", 1.2, None, None),
    "shake":    ("Rattles on the spot", "thing", 1.0, None, None),
    "hold":     ("She holds it (balloons, a sign, a cup...)", "thing", 0.1, None, None),
}
FROM_SIDES = ["left", "right", "back", "top"]
PARTICLE_ALIASES = {"water": "droplets", "drops": "droplets", "raindrops": "rain", "bubble": "bubbles",
                    "sparkle": "sparkles", "magic": "sparkles", "glitter": "sparkles", "fire": "embers",
                    "sparks": "embers", "flowers": "petals", "blossom": "petals", "autumn": "leaves",
                    "party": "confetti", "falling": "speed_lines", "speed": "speed_lines", "seeds": "specks",
                    "ash": "dust", "snowflakes": "snow", "love": "hearts", "heart": "hearts", "notes": "music_notes",
                    "music": "music_notes", "coin": "coins", "money": "coins", "candies": "candy", "sweets": "candy",
                    "clouds": "puffs", "cloud": "puffs", "sprinkle": "sprinkles", "pixel": "pixels",
                    "lightning": "bolts", "thunder": "bolts", "bat": "bats", "paw": "paws", "paw_prints": "paws"}
PARTICLE_WORDS = {   # words in a spoken line that switch an effect on (when the shot doesn't choose one)
    "stars": ("star", "stars", "starry", "constellation", "galaxy", "night sky"),
    "beams": ("beam", "beams", "sunbeam", "moonlight", "spotlight", "glowing light"),
    "rain": ("rain", "raining", "rainy", "downpour", "storm"), "snow": ("snow", "snowing", "snowy", "blizzard"),
    "bubbles": ("bubble", "bubbles", "underwater"), "confetti": ("confetti", "party", "birthday"),
    "sparkles": ("sparkle", "sparkles", "sparkly", "magic", "magical", "glitter"),
    "embers": ("fire", "burning", "flames", "lava", "embers"), "petals": ("petals", "blossom", "blossoms"),
    "leaves": ("leaves", "autumn", "fall leaves"), "dust": ("dusty", "sandstorm"),
    "fireflies": ("fireflies", "firefly"), "droplets": ("droplets", "raindrops on"),
    "hearts": ("hearts", "heart", "crush"), "music_notes": ("music notes", "singing", "song"),
    "coins": ("coins", "coin", "jackpot"), "candy": ("candy", "sweets", "candies"), "puffs": ("clouds", "cloud"),
    "sprinkles": ("sprinkles", "sprinkle"), "pixels": ("pixels", "pixel", "8-bit"),
    "bolts": ("lightning", "thunder"), "bats": ("bats", "bat"), "paws": ("paws", "paw prints"),
}
PARTICLES = {   # effect: description (Blender side: blender_fx.FX)
    "rain": "Rain", "snow": "Snow", "droplets": "Floating water droplets", "bubbles": "Rising bubbles",
    "dust": "Drifting dust", "specks": "Falling specks / seeds", "sparkles": "Sparkles / magic",
    "embers": "Glowing embers", "petals": "Flower petals", "leaves": "Autumn leaves", "confetti": "Confetti",
    "stars": "Twinkling stars", "speed_lines": "Speed lines (falling)", "fireflies": "Fireflies",
    "beams": "Light beams drifting down",
    "hearts": "Love hearts", "music_notes": "Music notes", "coins": "Spinning coins", "candy": "Candy",
    "puffs": "Drifting clouds", "sprinkles": "Sprinkles", "pixels": "Pixel bits", "bolts": "Lightning bolts",
    "bats": "Bats", "paws": "Paw prints",
}
PERSON_WORDS = set("""human humans mom mum mother dad father mama papa grandma granny grandpa sister brother sis bro friend bestie
boss teacher student customer waiter waitress chef cook barista man woman guy girl boy kid child baby lady gentleman
neighbor neighbour police cop officer doctor nurse alien robot ghost zombie vampire witch wizard king queen prince
princess knight pirate ninja clown stranger tourist dog_owner mailman postman delivery driver cashier manager
coworker roommate twin clone villain hero fan fans crowd person people someone visitor guest""".split())
CAST_COLORS = {
    "red": "#d94a4a", "pink": "#ff8fb8", "orange": "#f0903a", "yellow": "#f2d14e", "gold": "#e0b040",
    "green": "#4caf50", "lime": "#9fe05a", "teal": "#2fb3a3", "blue": "#4a7fd9", "navy": "#2b3a73",
    "purple": "#8a5ad9", "violet": "#9f6bff", "brown": "#7a4a2a", "black": "#26232a", "white": "#f4f2ee",
    "grey": "#8a8f99", "gray": "#8a8f99", "silver": "#c0c4cc", "blonde": "#f2d89a", "blond": "#f2d89a",
    "ginger": "#d0602a", "beige": "#d9c2a0", "tan": "#c9a27a",
}

SETS = {
    "cafe": {
        "name": "Legacy Cafe",               # the original hand-made set (kept: the iconic first look)
        "description": "Cosy cafe with counter, espresso machine and tables",
        "marks": {"door": (-5.5, -2.0), "center": (0.0, 0.0), "counter": (2.5, 2.3),
                  "table": (-2.0, 0.8), "front": (0.0, -2.5), "machine": (3.4, 2.4)},
    },
    "park": {
        "name": "Legacy Park",               # the original hand-made set (kept: the iconic first look)
        "description": "Sunny park with trees, a path, a bench and a pond",
        "marks": {"left": (-3.5, 0.0), "right": (3.5, 0.0), "center": (0.0, 0.0), "front": (0.0, -2.5),
                  "tree": (-2.6, 3.4), "bench": (2.8, 2.3), "pond": (4.0, 4.0), "far": (0.0, 9.0)},
    },
}


for _k, _v in SETS.items():
    _v.setdefault("name", _k.capitalize())
    _v.setdefault("theme", _k)
    _v["builtin"] = True


def all_sets():
    """Every usable set, all treated the same: the two hand-made ones (cafe, park) plus every recipe
    in sets/*.json. Sets you removed are left out. (id -> {name, description, marks, ...})"""
    import setgen
    gone = setgen.hidden()
    out = {k: v for k, v in SETS.items() if k not in gone}
    for sid, r in setgen.load_all().items():
        if sid in gone:
            continue
        out[sid] = {"name": r.get("name", sid), "description": r.get("description", ""), "theme": r.get("theme", ""),
                    "marks": r.get("marks", {}), "builtin": False, "light": r.get("light"),
                    "indoor": r.get("indoor")}
    return out


def as_dict():
    """JSON-friendly catalog for the web app."""
    return {
        "anims": {k: {"description": d, "moves": m} for k, (d, m) in ANIMS.items()},
        "expressions": EXPRESSIONS,
        "cameras": CAMERAS,
        "moves": MOVES,
        "facing": FACING,
        "lights": LIGHTS,
        "languages": {k: f"{v['native']} ({v['name']})" if v["native"] != v["name"] else v["name"]
                      for k, v in LANGUAGES.items()},
        "cast_verbs": {k: {"description": v[0], "who": v[1]} for k, v in CAST_VERBS.items()},
        "from_sides": FROM_SIDES,
        "particles": PARTICLES,
        "particle_aliases": PARTICLE_ALIASES,
        "sets": {k: {"name": v["name"], "description": v["description"], "marks": list(v["marks"])}
                 for k, v in all_sets().items()},
    }
