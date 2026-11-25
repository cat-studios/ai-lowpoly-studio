"""
Script and title ideas from a local Ollama server. Optional helper: everything can still be
written by hand. Output is plain script lines (with optional [directions]) that go through the
normal auto-director, so the AI never needs to know the JSON format.
"""
import json
import re
import time
import urllib.error
import urllib.request

import catalog

DEFAULT_URL = "http://127.0.0.1:11434"


def _req(url, path, payload=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_models(url=DEFAULT_URL):
    tags = _req(url, "/api/tags", timeout=5)
    out = []
    for m in tags.get("models", []):
        fam = (m.get("details") or {}).get("family", "")
        if "embed" in m["name"] or fam in ("nomic-bert", "bert"):
            continue                      # embedding models can't chat
        out.append({"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "params": (m.get("details") or {}).get("parameter_size", "")})
    return out


_REMOTE_DOWN = {}          # big text server -> when it last failed (it's tried again after REMOTE_RETRY seconds)
REMOTE_RETRY = 300


def _remote_for(url, has_images):
    """(url, model) of the big text server when Settings -> AI tools sends ALL the AI's writing there
    (ollama.design_scope "text"), else None. Pictures (vision checks) always stay on the main Ollama."""
    if has_images:
        return None
    try:
        import settings as S
        o = S.load_settings()["ollama"]
    except Exception:
        return None
    big = str(o.get("design_url") or "").strip()
    if not big or o.get("design_scope") != "text" or url.rstrip("/") != str(o.get("url", "")).rstrip("/"):
        return None
    if time.time() - _REMOTE_DOWN.get(big, 0) < REMOTE_RETRY:
        return None
    return big, (o.get("design_model") or "").strip() or None


def _chat_once(url, payload):
    try:
        return _req(url, "/api/chat", payload)
    except urllib.error.HTTPError as exc:      # older Ollama / non-thinking models may reject "think"
        if exc.code != 400 or "think" not in payload:
            raise
        payload = {k: v for k, v in payload.items() if k != "think"}
        return _req(url, "/api/chat", payload)


def _chat(url, payload, has_images=False):
    """POST /api/chat - on the big text server when it's set up for all writing (falls back to `url` if it can't
    be reached or doesn't have the model: it is never asked to download one)."""
    rem = _remote_for(url, has_images)
    if rem:
        p = dict(payload, model=rem[1]) if rem[1] else payload
        try:
            return _chat_once(rem[0], p)
        except (OSError, TimeoutError, ValueError) as exc:     # unreachable, no such model, bad answer
            _REMOTE_DOWN[rem[0]] = time.time()
            print(f"[ai] big text server {rem[0]} failed ({exc.__class__.__name__}: {str(exc)[:80]}) - "
                  f"using {url} for the next {REMOTE_RETRY // 60} min")
    return _chat_once(url, payload)


def chat(url, model, system, user, temperature=0.8):
    payload = {"model": model, "stream": False, "think": False,
               "options": {"temperature": float(temperature)},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = _chat(url, payload)
    text = r.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def chat_json(url, model, system, user, temperature=0.9, images=None):
    """Like chat() but asks Ollama for strict JSON and parses it. images: base64 pictures for a vision model."""
    msg = {"role": "user", "content": user}
    if images:
        msg["images"] = images
    payload = {"model": model, "stream": False, "think": False, "format": "json",
               "options": {"temperature": float(temperature)},
               "messages": [{"role": "system", "content": system}, msg]}
    r = _chat(url, payload, has_images=bool(images))
    text = re.sub(r"<think>.*?</think>", "", r.get("message", {}).get("content", ""), flags=re.S).strip()
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0) if m else text)
    if isinstance(data, list):                 # some models wrap the object in a list
        data = next((d for d in data if isinstance(d, dict)), None)
    if not isinstance(data, dict):             # every caller expects an object: say so instead of crashing later
        raise ValueError(f"the model answered with {type(data).__name__}, not a JSON object")
    return data


# what each ground looks like: its default colour, and the climates it can belong to
GROUND = {
    "snow": ("#e8f4fc", {"cold"}), "sand": ("#e6c87a", {"hot", "coast"}), "grass": ("#6fb04a", {"temperate", "wet", "cold"}),
    "dirt": ("#8b6b43", {"hot", "temperate", "dry"}), "road": ("#4a4a50", {"temperate", "hot", "cold", "wet"}),
    "stone": ("#8a8a8a", {"cold", "temperate", "hot", "dry"}),
}
CLIMATE_PARTICLES = {"snow": {"cold"}, "dust": {"hot", "dry"}, "leaves": {"temperate", "cold"},
                     "petals": {"temperate"}, "bubbles": {"underwater"}, "stars": {"space"}}


def make_coherent(plan):
    """Make a plan make sense: the ground matches the climate, its colour matches its type, and weather effects
    (snow, dust, leaves...) only appear where they can. Changes are logged in plan['_fixes']."""
    fixes = []
    climate = str(plan.get("climate") or "").lower()
    outside = plan.get("where") == "outside" or (plan.get("where") is None and not plan.get("indoor"))
    floor = str(plan.get("floor") or "")
    if outside and climate and floor in GROUND and climate not in GROUND[floor][1]:
        fallback = next((g for g, (_, ok) in GROUND.items() if climate in ok), "grass")
        fixes.append(f"floor {floor} -> {fallback} (climate {climate})")
        floor = fallback
        plan["floor"] = floor
    if outside and floor in GROUND:
        colours = dict(plan.get("colors") or {})
        colours["floor"] = colours["floor2"] = GROUND[floor][0]
        plan["colors"] = colours
    if not outside:                                  # weather doesn't happen indoors (snow fell in a post office)
        weather = {"snow", "rain", "droplets", "leaves", "petals"}
        gone = [p for p in plan.get("particles") or [] if isinstance(p, str) and p in weather]
        if gone:
            plan["particles"] = [p for p in plan.get("particles") or [] if p not in gone]
            fixes.append(f"removed {', '.join(gone)} (indoors)")
    if climate:
        keep = []
        for p in plan.get("particles") or []:
            if not isinstance(p, str):               # the model sometimes writes an object here: ignore it
                continue
            allowed = CLIMATE_PARTICLES.get(p)
            if allowed is None or climate in allowed:
                keep.append(p)
            else:
                fixes.append(f"removed {p} particles ({climate})")
        plan["particles"] = keep
    plan["_fixes"] = fixes
    return plan


def make_theme(url, model, idea):
    """Write a new theme for a place: the props that belong there, where they go, the ground and colours. It is
    checked against what the layout can build, saved to sets/themes/ and returned (its id is in theme['id'])."""
    import setgen
    import re as _re
    zones = ["wall_back", "wall_left", "corner", "hang_back", "hang_left", "center", "scatter", "grid", "near", "far"]
    outside = not any(w in idea.lower() for w in ("inside", "room", "kitchen", "cafe", "bedroom", "office", "school", "shop", "hall"))
    floors = setgen.FLOORS_OUT if outside else setgen.FLOORS_IN
    system = (
        "You design the theme of a small low-poly 3D place (N64 style) for a short video: which objects belong there and "
        "where they stand. Only things that really belong in that place. Reply with JSON only:\n"
        '{"name": "2-3 word name", "description": "one sentence", "indoor": true or false, "room": "small|medium|large" '
        '(indoor only), "floor": one of ' + ", ".join(floors) + ', '
        '"palette": {"floor": ["#rrggbb", "#rrggbb"], "wall": "#rrggbb", "trim": "#rrggbb", "accent": "#rrggbb", '
        '"fog": "#rrggbb"}, "light": "day|sunset|night", '
        '"props": [{"kind": "...", "count": [min, max], "zone": "..."}], "marks": ["short", "walk to places"]}\n'
        f"kind must be one of: {', '.join(sorted(setgen.PROPS))}.\n"
        f"zone: where it stands - {', '.join(zones)}. Walls for wall things (wall_back, wall_left), hang_* for things on "
        "the wall at window height, corner for plants and lamps, center for tables and rugs, scatter for small things "
        "on the ground, far for big things in the background (trees, hills), near for benches and lamps by the path.\n"
        "Use 5 to 9 kinds, the basics of that place first. Never put a thing where it can't be: no snow in a desert, no "
        "sand in a snowy place, no fridge outdoors."
    )
    user = f"Place: {idea}\nWrite the theme for exactly this place."
    t = chat_json(url, model, system, user, 0.5)
    kinds = [p for p in (t.get("props") or []) if isinstance(p, dict) and str(p.get("kind")) in setgen.PROPS]
    if not kinds:
        raise ValueError("the AI couldn't make a theme from that place - try describing it differently")
    props = []
    for p in kinds[:9]:
        c = p.get("count") or [1, 2]
        try:                                   # [min, max], a single number, or junk from the model
            lo, hi = (int(c[0]), int(c[-1])) if isinstance(c, list) and c else (1, int(c))
        except (TypeError, ValueError):
            lo, hi = 1, 2
        zone = str(p.get("zone") or "scatter")
        props.append([str(p["kind"]), max(1, lo), max(max(1, lo), hi), zone if zone in zones else "scatter"])
    name = str(t.get("name") or idea)[:40]
    tid = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "generated_theme"
    tid = f"gen_{tid}"
    indoor = bool(t.get("indoor")) and not outside
    pal = t.get("palette") or {}
    floor = str(t.get("floor") or "")
    if floor not in floors:
        floor = floors[0]
    theme = {"id": tid, "names": ([name], [name]), "indoor": indoor, "room": (t.get("room") or "medium") if indoor else None,
             "description": str(t.get("description") or idea)[:200],
             "palettes": [{"floor": pal.get("floor") or ["#c8b48a", "#a89070"], "wall": pal.get("wall", "#eeeeee"),
                           "trim": pal.get("trim", "#999999"), "accent": pal.get("accent", "#ff8fb8"),
                           "fog": pal.get("fog", "#cfe9ff")}],
             "floor": floor, "props": props,
             "marks": [str(m) for m in (t.get("marks") or ["center"])][:6], "light": t.get("light") or "day",
             "textures": {}, "generated": True, "idea": idea}
    setgen.THEME_DIR.mkdir(parents=True, exist_ok=True)
    (setgen.THEME_DIR / f"{tid}.json").write_text(json.dumps(theme, indent=1), encoding="utf-8")
    setgen.THEMES[tid] = theme
    return theme


def design_set(url, model, idea="", where=None, light=None, temperature=1.0, image=None, feedback=""):
    """Ask the model to invent a set. It may use ready-made props, props the AI made for earlier sets,
    and describe up to a few brand-new props (designed afterwards by propgen)."""
    import propgen
    import setgen
    import sfx as sfxlib
    props_in = sorted(set(setgen.INDOOR_BIG + setgen.INDOOR_SMALL))
    props_out = sorted(set(setgen.OUT_FAR + setgen.OUT_NEAR + ["building"]))
    made = [f"{k} ({(d.get('looks') or k.replace('_', ' '))[:60]})" for k, d in sorted(propgen.library().items())][-60:]
    ambs = [f"{k} ({v['label'].replace('Ambience: ', '')})" for k, v in sfxlib.all_slots().items()
            if v["kind"] == "ambience"]
    system = (
        "You design small low-poly 3D sets (N64 style) for short videos. The jokes come from the script, NOT from "
        "the set: when the user gives an idea, build a believable, ordinary version of exactly that place, the way "
        "most people would picture it. No puns, no giant food, no surreal or whimsical twists, no wordplay on the "
        "idea - unless the idea itself asks for something strange. Example: 'Eastern European kitchen' = a homely "
        "kitchen with a stove, counter, fridge, table and chairs, shelves, pots, maybe a samovar and lace curtains. "
        "Make it unmistakable - a lava pit must have lava and volcanic rocks, not a beach. Only when NO idea is "
        "given, invent one fresh, specific, surprising place. Reply with JSON only, using exactly these keys:\n"
        '{"name": "2-3 word place name", "description": "one sentence", "where": "inside" or "outside" or "air", '
        '"air_kind": "sky" or "space" or "underwater" or "core" (only when where is air), '
        '"climate": "hot" (deserts, tropics, summer) or "cold" (snow, ice, mountains in winter) or "temperate" (ordinary '
        'countryside, towns) or "wet" (swamp, rain, marsh) or "coast" (beach, sea shore) or "dry" (rocky badlands) or '
        '"underwater" or "space" or "indoor", '
        '"room": "small" (inside only: a bathroom, toilet, closet, tiny kitchen, phone booth) or "medium" (a bedroom, a '
        'normal kitchen, a classroom, a shop, an office) or "large" (a living hall, a gym, a big open room; outside: any), '
        '"light": "day" or "sunset" or "night", '
        '"colors": {"floor": "#rrggbb", "floor2": "#rrggbb", "walls": "#rrggbb", "trim": "#rrggbb", '
        '"accent": "#rrggbb", "sky": "#rrggbb"}, '
        '"floor": "planks|checker|checker_small|metal|stone" (inside) or "grass|sand|snow|road|stone|dirt" (outside), '
        '"liquid": {"type": "water|lava|slime|acid|chocolate|honey|...", "shape": "pool|river|sea", "color": "#rrggbb", '
        '"glow": true} or null, '
        '"props": [{"kind": "...", "count": 3}], '
        '"new_props": [{"name": "short_name", "looks": "shape, parts and colours in a few words", '
        '"place": "near|far|scatter|wall|corner"}], '
        '"wall_pictures": [{"kind": "poster|window|chalkboard|neon_sign|star_window", "count": 1, "prompt": "what the picture shows"}], '
        '"particles": [], "extras": [], "ambience": "...", "new_ambience": "" , '
        '"textures": {"floor": "texture idea for the floor", "walls": "wallpaper idea", "sky": "what is on the horizon"}}\n'
        f"Ready-made props INSIDE: {', '.join(props_in)}.\n"
        f"Ready-made props OUTSIDE: {', '.join(props_out)}.\n"
        + (f"Props made for earlier sets - reuse one ONLY if it clearly belongs in this place, most won't: "
           f"{'; '.join(made)}.\n" if made else "")
        + "new_props: up to 4 everyday objects this place really needs that are NOT in the lists above (for a "
        "kitchen: stove, kitchen_cabinet, cooking_pot, samovar; for a garage: car, toolbox). An artist draws each "
        "one from your words, so describe what it really looks like in plain words: material, colour, shape "
        "(e.g. 'old white enamel stove with four black burners'). Solid objects only (no smoke, mist or light). "
        "Also list them in props with a count.\n"
        "liquid: ONLY if the place really has open liquid - a lake, sea, beach, river, swamp, lava pit, swimming "
        "pool. Rooms like kitchens, bedrooms, shops, offices and classrooms have none: use null. "
        "glow=true for lava, slime, magic.\n"
        "where = air when there is no ground to stand on: skydiving or falling through the sky (air_kind sky), "
        "floating in space (space), under the sea (underwater), falling down a hole to the centre of the earth "
        "(core). Standing on the moon or a planet is outside, not air.\n"
        "particles: effects that are always in the air there, usually none - e.g. stars (space, the moon), "
        "snow (snowy places), embers (lava, fire), bubbles (under water), petals (blossom gardens), dust (desert).\n"
        "wall_pictures only exist inside. extras (outside only) may include: hills, fence.\n"
        f"ambience: one of {', '.join(ambs)}. If none of them fits, describe a new background sound in "
        "new_ambience (e.g. \"deep rumbling with slow lava bubbles\"), otherwise leave it empty.\n"
        "Use 5 to 9 different prop kinds in total, counts between 1 and 12 (trees can go up to 20). "
        "Always include the obvious basics for the place from the ready-made list first (a kitchen: counter, "
        "fridge, table, chair; a bedroom: bed, desk_pc...) and add new_props on top of them. "
        "Pick colours that fit the mood."
    )
    want = []
    if where in ("inside", "outside", "air"):
        want.append(f"It must be {where}.")
    if light in ("day", "sunset", "night"):
        want.append(f"Time of day: {light}.")
    if image:
        # a picture is the reference: copy the place it shows, closely
        import base64
        from pathlib import Path as _P
        user = ("The picture attached is the reference. Rebuild the place it shows as closely as you can: the same kind "
                "of place, its colours and light, the floor and sky/walls, and the objects you can see (use a ready-made "
                "prop when one fits, otherwise a new_props entry). COUNT what you see and use about that many: a forest "
                "has many trees (up to 20), a row of shops has several shops, one bench is one bench. Use 6 to 12 prop "
                "kinds, not 4. For every props and new_props entry also give \"side\": \"left\", \"centre\" or \"right\" "
                "- where it sits in the picture from the camera's view. Put big things that are nearer the camera in the "
                "'near' place, things far away in 'far', small things on the ground in 'scatter'. "
                + (f"The user also says: {idea}. " if idea else "") + " ".join(want))
        b64 = base64.b64encode(_P(image).read_bytes()).decode("ascii")
        return make_coherent(chat_json(url, model, system, user, 0.3, images=[b64]))
    user = (f"Idea: {idea}\nBuild this place as described - realistic and ordinary. Everything must belong together: "
            "a desert has no snow, a snowy place has no sand, the weather and ground match the place.\n" if idea
            else "Surprise me with an unusual place.\n") + " ".join(want)
    if feedback:                               # make_set's look check: what was wrong with the last try
        user += (f"\nA set built from your last design was looked at and it did NOT look like this place: {feedback}"
                 "\nDesign it again so it clearly reads as this place: the props it needs, nothing that doesn't belong.")
    return make_coherent(chat_json(url, model, system, user, min(temperature, 0.6) if idea else temperature))


def find_cast(url, model, lines, main_name="the main character", place="", temperature=0.4):
    """Read a script and say who/what else shows up and when: {"cast": {...}, "events": [...]}.
    The main character is never part of the cast; things only mentioned in passing are left out."""
    verbs = ", ".join(catalog.CAST_VERBS)
    system = (
        "You are the stage manager for a short animated video. One character, "
        f"{main_name}, speaks every line. Find other people, animals or objects that PHYSICALLY appear or arrive "
        "in the scene (not ones only talked about, remembered or imagined). Reply with JSON only:\n"
        '{"cast": {"short_name": {"type": "person" or "thing", "looks": "a few words: size, shape, colours"}}, '
        '"events": [{"line": 0, "who": "short_name", "do": "verb", "from": "left|right|back|top"}]}\n'
        f"Verbs for things: {verbs}. Verbs for people: enter, exit, appear, vanish, wave, angry, laugh, "
        "surprised, point, dance, scared, sad, jump, nod, shake_head.\n"
        "line is the 0-based line number where it happens. short_name: one lowercase word or two joined with _. "
        "A thing that smashes in uses crash_in, falls from above uses fall, flies past uses fly_by. "
        "Someone arriving uses enter first. If nobody else appears, return empty cast and events. Max 4 cast members."
    )
    user = (f"Place: {place}\n" if place else "") + "Script:\n" + "\n".join(f"{i}: {l}" for i, l in enumerate(lines))
    return chat_json(url, model, system, user, temperature)


def place_for_title(url, model, title, temperature=0.4):
    """Where should a video with this title start? -> {"place": "...", "where": "inside|outside|air"}."""
    system = ("You are the location scout for a short animated explainer video. Given its title, pick the ONE place "
              "where the video should start - the most natural, visual setting for the topic, described plainly "
              "in 2-6 words (e.g. 'What if every ant vanished?' -> 'garden with an ant hill'; 'How heavy is a "
              "cloud?' -> 'grassy hill under big clouds'; 'Why do we dream?' -> 'cozy bedroom at night'). "
              "When the title names a place, the video starts IN that place ('What if cats ran the post office?' "
              "-> 'inside a post office', not the street outside it). "
              'Reply with JSON only: {"place": "...", "where": "inside" or "outside" or "air"}. where = air only '
              "when the place has no ground (sky, space, under the sea).")
    r = chat_json(url, model, system, f"Title: {title}", temperature)
    place = str(r.get("place") or "").strip()[:80]
    where = r.get("where") if r.get("where") in ("inside", "outside", "air") else None
    return {"place": place, "where": where}


def find_scenes(url, model, lines, start_place, sets, policy="reuse", temperature=0.3):
    """Where each line happens + particle effects. sets = {id: {name, description}} the user already has.
    Returns {"scenes": [{"line", "place", "set"}], "particles": [{"line", "effect"}]}."""
    have = "; ".join(f"{k} = {v.get('name') or k}: {str(v.get('description') or '')[:70]}"
                     for k, v in list(sets.items())[:80])
    system = (
        "You are the location manager for a short animated video. Every line is one shot; the video starts in "
        f"'{start_place}'. Find the lines where the story MOVES to a different place (she jumps out of a plane "
        "-> falling through the sky; she lands on the moon -> the moon; she falls into a hole -> falling to the "
        "centre of the earth). List EVERY move, in order - a story can move several times. Only real moves, not "
        "places she just talks about. Reply with JSON only:\n"
        '{"scenes": [{"line": 2, "place": "short description of the new place", "set": "existing set id or new"}], '
        '"cutaways": [{"line": 4, "show": "what the camera shows instead of her, e.g. a plane flying past"}], '
        '"particles": [{"line": 0, "effect": "..."}]}\n'
        + (f"Existing sets you should reuse when one really fits: {have}.\n" if policy == "reuse" and have else
           "Always answer new for set.\n")
        + "cutaways: at most 2, for lines that describe a specific object or creature better shown than told "
        "(\"the plane was already 4000 metres up\" -> a plane flying past). She keeps talking over it.\n"
        + "particles: ONLY for lines where weather or a visual effect is clearly happening (rain, snow, confetti, "
        "magic sparkles, falling through the air = speed_lines). Most lines have none. effect is one of: "
        + ", ".join(catalog.PARTICLES) + "."
    )
    user = "Script:\n" + "\n".join(f"{i}: {l}" for i, l in enumerate(lines))
    return chat_json(url, model, system, user, temperature)


def _clean_lines(text, keep=()):
    """Script lines from the model's answer. "Name: ..." prefixes are dropped (the model likes to label the main
    character) unless the name is in `keep` (co-stars) or is a person the script brings in with "+name" - those
    are who says the line (autodirect turns them into the shot's speaker)."""
    keep = {k.lower() for k in keep}
    keep |= {w.replace("_", " ") for w in re.findall(r"\+([a-z0-9_]+)", text.lower())} | \
        set(re.findall(r"\+([a-z0-9_]+)", text.lower()))
    lines = []
    # some models put the whole script on one line: a new "[directions]" after a sentence starts a new line
    text = re.sub(r"(?<=[.!?\"'])\s+(?=\[)", "\n", text)
    for raw in text.splitlines():
        s = raw.strip().strip('"').strip()
        s = re.sub(r'"\s*,?\s*$', "", s).strip()     # a line the model wrapped like JSON: ... nya!",
        s = re.sub(r"^\*{1,2}([^*:]{1,30})(?:\*{1,2}:|:\*{1,2})\s*", r"\1: ", s)   # **Name:** / **Name**: -> Name:
        s = re.sub(r"^(\d+[.)]|[-*•]|line\s*\d+:)\s*", "", s, flags=re.I)   # numbering / bullets
        m = re.match(r"^([A-Z][\w ]{0,20}):\s+", s) if not s.startswith("[") else None
        if m and m.group(1).strip().lower() not in keep:
            s = s[m.end():]                                                   # "Catgirl: ..." -> "..."
        if not s or s.lower().startswith(("here", "sure", "title", "script")) or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def generate_script(url, model, title, character, set_info, lines=6, tone="funny", extra="", temperature=0.85,
                    others=None, polish=True):
    """others: the other main characters in the video, [{"name", "about"}] - they get some lines too."""
    others = [o for o in (others or []) if isinstance(o, dict) and o.get("name")]
    cams = ", ".join(catalog.CAMERAS)
    anims = ", ".join(k for k in catalog.ANIMS if k not in ("sit", "fall", "float", "turn"))   # no floor-sitting
    exprs = ", ".join(catalog.EXPRESSIONS)
    marks = ", ".join(set_info.get("marks", []))
    import sfx as sfxlib
    sfx_names = ", ".join(k for k, v in sfxlib.all_slots().items() if v["kind"] == "oneshot")
    system = (
        "You write scripts for short vertical videos (Instagram Reels) starring ONE animated character who "
        "talks to the camera. Each line is one shot. Keep every line short and punchy (max 14 words), spoken "
        "in first person by the character, with a clear setup, escalation and a punchline at the end.\n"
        "Keep it family-friendly: no swearing (no damn, hell, crap...) and correct, natural English.\n"
        "Output ONLY the script lines, one per line. No numbering, no names, no stage directions in "
        "parentheses, no title, no commentary.\n"
        "You MAY start a line with directions in square brackets, using ONLY these words:\n"
        f"cameras: {cams}\nactions: {anims}\nexpressions: {exprs}\n"
        "An action that is NOT in that list can be written as do: and one word - [do:salute], [do:yawn], [do:flex] - "
        "and it will be animated for you; use that only for clear body actions.\n"
        f"places to walk to (with walk_to/run_to/sneak_to): {marks} - walk at most once or twice in the whole "
        "script, only when the story needs her somewhere else; for variety change the camera, her action or "
        "expression, bring something on screen or change the place instead of walking about\n"
        f"sound effects (optional, at most one per line, only when it fits): {sfx_names}\n"
        "When another person or a thing actually shows up in the scene, bring it on screen with '+name verb' in "
        "the brackets (ONE lowercase word or words_joined_by_underscores, e.g. +mail_van, never two separate "
        "words; reuse the same name later). A person you brought in may say a "
        "line: start that line with their name and a colon (Mom: You forgot your lunch!). Things never speak; "
        "keep most lines for the main character.\n"
        "Lighting can change at a line with one of: day, sunset, night, dawn in the brackets (it lasts until the "
        "next change) - only when time really passes in the story.\n"
        f"verbs for things: {', '.join(catalog.CAST_VERBS)} (crash_in may add from_left / from_right / from_back)\n"
        "verbs for people: enter, exit, appear, vanish, or any action above (wave, angry, laugh, dance...)\n"
        "Floating: [+balloons hold] gives her a bunch of balloons, [float_up] lifts her off the ground (she stays up), "
        "[land] brings her back down. Always close brackets with ] and never put directions mid-line.\n"
        "Explaining how something works (a toilet, a volcano, a heart, an engine)? Bring a model of it on beside her "
        "with [show: thing] (one word, or words_joined), [show: thing open] when you talk about its inside, "
        "[show: thing part] to look closely at one part (e.g. [show: toilet flap]), and [show: off] when you're "
        "done with it. Name each part and say what it does in plain words (\"the chain lifts the flap\") - the "
        "model's parts move on those words.\n"
        "Example line: [closeup, angry] Fine. I'll do it myself!\n"
        "Example line: [wide, surprised, boom] And then the oven exploded!\n"
        "Example line: [+mom enter, scared] Mom?! You weren't supposed to be home yet!\n"
        "Example line: [+truck crash_in from_left, surprised] WHY IS THERE A TRUCK IN THE KITCHEN?!"
    )
    user = (
        f"Video title: {title}\n"
        f"Character: {character.get('name', 'the character')}. {character.get('about', '')}\n"
        + ("Other main characters in this video (they talk too - give each of them a few lines, reacting to and "
           "talking with the main character). Start each of their lines with EXACTLY the name shown here and a "
           "colon, even if the description calls them something else:\n"
           + "".join(f"- {o['name']} (write \"{o['name']}: ...\"): {str(o.get('about') or '')[:300]}\n"
                     for o in others) if others else "")
        + "Put every line on its own line.\n"
        + f"Location: {set_info.get('name', '')} - {set_info.get('description', '')}\n"
        f"Tone: {tone}. Number of lines: {int(lines)}.\n"
        + (f"Extra notes: {extra}\n" if extra else "")
        + "Write the script now."
    )
    text = chat(url, model, system, user, temperature)
    alias = {a.lower(): o["name"] for o in others for a in (o.get("aliases") or []) + [o["name"]]}
    out = []
    for line in _clean_lines(text, keep=list(alias)):
        # "[cameras: macro, happy]", "[action: shrug]": the prompt's list labels copied into the brackets (the
        # director would try to animate "cameras: macro")
        line = re.sub(r"(?<=[\[,])\s*(?:cameras?|actions?|expressions?|moods?|emotions?)\s*:\s*", " ", line, flags=re.I)
        m = re.match(r"^(\[[^\]]*\]\s*)?([^:\[\]]{1,31}):\s+", line)     # "Ethan: ..." -> the co-star's own name
        if m and m.group(2).strip().lower() in alias:
            line = (m.group(1) or "") + alias[m.group(2).strip().lower()] + ": " + line[m.end():]
        out.append(line)
    out = out[: int(lines) + 2 + len(others) * 2]
    if not out:
        raise RuntimeError("The model returned no usable lines - try again or pick another model.")
    if polish:
        out = polish_script(url, model, title, out, tone)
    return out


_LINE_HEAD = re.compile(r"^\s*((?:\[[^\]]*\]\s*)?(?:[A-Za-z][\w ]{0,30}:\s+)?)(.*)$")


def polish_script(url, model, title, lines, tone="funny", temperature=0.4):
    """An editor's second pass over a script: correct, natural English, each line following from the last, the
    title's question really answered (a true fact, said simply), no joke used twice, a punchline that lands at the
    end, max 14 words a line. Only the spoken words change: every line keeps its own [directions] and "Name:" (the
    model is shown them but its copies are ignored), and the line count stays the same. Any problem -> the script
    as it was."""
    if not lines:
        return lines
    heads, texts = [], []
    for ln in lines:
        m = _LINE_HEAD.match(ln)
        heads.append(m.group(1) if m else "")
        texts.append((m.group(2) if m else ln).strip())
    system = ("You are the script editor for short, funny, family-friendly animated Reels where a character answers "
              "a curious question. First list what is wrong with the script, then rewrite the spoken lines to fix "
              "it. Check: wrong or made-up facts (the title's question must get a real, true answer, said simply - "
              "a joke can exaggerate, but the answer itself is true); broken or unnatural English and made-up words; "
              "lines that don't follow from the one before; a joke or idea used twice; an ending that doesn't land "
              "(the last line is a punchline); more than 14 words in a line; swearing. Keep the same number of "
              "lines in the same order, each line keeping its job (who speaks, names and +name words exactly). "
              "Reply with JSON only: "
              '{"problems": ["..."], "lines": ["...", "..."]}')
    user = (f"Title: {title}\nTone: {tone}\nLines (the part in front of each line is the stage direction - "
            "don't write it in your answer):\n" + "\n".join(f"{i + 1}. {h}{t}" for i, (h, t) in
                                                           enumerate(zip(heads, texts))))
    try:
        r = chat_json(url, model, system, user, temperature)
        new = r.get("lines")
    except Exception:
        return lines
    if not (isinstance(new, list) and len(new) == len(lines) and all(isinstance(x, str) and x.strip() for x in new)):
        return lines
    out = []
    for h, old, nw in zip(heads, texts, new):
        nw = re.sub(r"^\s*\d+[.)]\s*", "", nw.strip().strip('"'))
        m = _LINE_HEAD.match(nw)                   # the editor copied the direction/name anyway: drop its copy
        if m and m.group(1).strip():
            nw = m.group(2).strip()
        lost = set(re.findall(r"\+[a-z0-9_]+", old)) - set(re.findall(r"\+[a-z0-9_]+", nw))
        if not nw or len(nw.split()) > 22 or lost or "[" in nw:
            nw = old                               # too long, or it dropped someone's entrance: keep the original
        out.append(h + nw)
    return out


def translate_lines(url, model, lines, language, temperature=0.2):
    """English lines -> the same lines in `language`, in order. One request for all of them; if the model returns the
    wrong number of lines, each line is translated on its own. Raises when Ollama can't be reached."""
    system = (f"You translate the spoken lines and on-screen text of a short, funny animated video from English into "
              f"{language}. Natural, everyday spoken {language} that sounds good read aloud, same meaning, tone and "
              f"jokes, about the same length. Keep names of people and characters as they are. Write numbers the "
              f"way a {language} speaker would say them. Reply with JSON only: "
              '{"lines": ["...", "..."]} - exactly one translated line for each input line, in the same order.')
    if not lines:
        return []
    user = "Lines:\n" + json.dumps(list(lines), ensure_ascii=False)
    try:
        out = chat_json(url, model, system, user, temperature).get("lines")
    except ValueError:
        out = None
    if isinstance(out, list) and len(out) == len(lines) and all(isinstance(x, str) and x.strip() for x in out):
        return [x.strip() for x in out]
    res = []                                   # one at a time when the batch came back wrong
    for line in lines:
        o = chat_json(url, model, system, "Lines:\n" + json.dumps([line], ensure_ascii=False), temperature).get("lines")
        if not (isinstance(o, list) and o and isinstance(o[0], str) and o[0].strip()):
            raise ValueError(f"the model couldn't translate: {line[:60]}")
        res.append(o[0].strip())
    return res


TITLE_STARTS = ["What if", "How does", "Why is", "Why do", "What does", "How can", "What happens if",
                "How much", "How big", "Is it possible", "What would happen if", "How long"]
TITLE_JUNK = re.compile(r"\b(nya+|nyan|meow+|uwu|owo)\b[!?.,~]*", re.I)     # interjections only ("purr" can be a topic)


def clean_title(t):
    t = TITLE_JUNK.sub("", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)          # no emoji
    t = re.sub(r"\s{2,}", " ", t).strip(" -~,.!")
    if t and not t.endswith("?") and re.match(r"(what|how|why|is|can|does|do|would|will|when|where|who)\b", t, re.I):
        t += "?"
    return t[:1].upper() + t[1:]


def generate_titles(url, model, character, theme="", count=8, temperature=1.0, starts=None, hint=""):
    """Curiosity titles like the reference channel: plain questions about the world ("What if every ant
    vanished?", "How heavy is a cloud?"). The character presents them, so she isn't in the title, and there's no
    "nya", cat words or emoji."""
    system = ("You write titles for short educational-but-funny Reels that answer one curious question about the "
              "world (science, nature, space, the body, history, everyday things). Each title is a simple, "
              "plain-English question that makes people want to know the answer, for example:\n"
              "What if every ant on Earth vanished?\nHow heavy is a cloud?\nWhy is the sky blue?\n"
              "What does the inside of a volcano look like?\nHow can a plane stay in the air?\n"
              f"Start each title with one of: {', '.join(starts or TITLE_STARTS)} (mix them"
              + (", don't only use 'What if').\n" if not starts else ").\n")
              + (f"Each title is about {hint}.\n" if hint else "")
              + "Rules: under 10 words; no character names, no cat sounds or cat words (no 'nya', 'meow', 'purr', "
              "'catgirl'), no emoji, no hashtags, no quotes, no numbering. Output ONLY the titles, one per line.")
    user = ((f"Topic: {theme}\n" if theme else "Any topic - surprise me with things people wonder about.\n")
            + f"Give {int(count)} different titles.")
    out = []
    for t in _clean_lines(chat(url, model, system, user, temperature)):
        t = clean_title(t)
        if 8 < len(t) < 90 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return rank_titles(url, model, out[: int(count)])


def series_titles(url, model, idea, count=3, starts=None, hint="", temperature=0.9):
    """Episode titles for a series about one idea: each a curious question of its own, together telling the idea
    from different angles (no "Part 1" - each video must stand alone), in a good watching order."""
    count = max(1, min(4, int(count)))
    system = ("You plan a short series of educational-but-funny Reels about ONE idea. Each episode answers its own "
              "curious question about the idea, from a different angle, so each video stands alone but together "
              "they cover the idea; order them so the first one hooks people. "
              f"Start each title with one of: {', '.join(starts or TITLE_STARTS)}. "
              + (f"Each title is about {hint}. " if hint else "")
              + "Rules: under 10 words; no character names, no cat words, no emoji, no numbering, no 'Part 1'. "
              'Reply with JSON only: {"titles": ["...", "..."]}')
    # a few extra, then the best ones by rank_titles (it scores "a real question with a real answer" - the first
    # try gave "How does your skin know when you're full?")
    r = chat_json(url, model, system, f"Idea: {idea}\nNumber of episodes: {count + 3}", temperature)
    out = []
    for t in (r.get("titles") or []):
        t = clean_title(str(t))
        if 8 < len(t) < 90 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    if not out:
        raise RuntimeError("The model returned no episode titles - try again")
    return rank_titles(url, model, out)[:count]


def rank_titles(url, model, titles):
    """The titles best first: a second look scores each one (makes you curious, clear, correct English, a real
    question with a real answer). A title with broken grammar is fixed when the fix is small. Any problem -> as
    they were."""
    if len(titles) < 2:
        return titles
    system = ("You judge titles for short educational-but-funny Reels. For each title give a score from 1 to 10: "
              "how much it makes people curious, how clear and short it is, and whether it is a real question with "
              "a real answer. Fix its English if it is wrong (keep the meaning). Reply with JSON only: "
              '{"titles": [{"title": "the title (fixed if needed)", "score": 1-10}, ...]} - same order, same number.')
    try:
        r = chat_json(url, model, system, "Titles:\n" + "\n".join(titles), 0.2).get("titles")
        if not (isinstance(r, list) and len(r) == len(titles)):
            return titles
        scored = []
        for i, (orig, x) in enumerate(zip(titles, r)):
            t = clean_title(str(x.get("title") or orig)) if isinstance(x, dict) else orig
            if not (8 < len(t) < 90) or abs(len(t) - len(orig)) > 25:
                t = orig                           # a rewrite, not a fix: keep the original
            sc = float(x.get("score") or 0) if isinstance(x, dict) else 0.0
            scored.append((-sc, i, t))
        return [t for _, _, t in sorted(scored)]
    except Exception:
        return titles



def social_copy(url, model, title, lines, temperature=0.7):
    """Caption + hashtags for a finished video. -> {"caption", "hashtags": [...], "youtube_title", "discord"}.
    The trendy discovery tags (#fyp, #shorts...) are added per platform by postiz.py; this picks topic tags."""
    script = "\n".join(lines[:16])
    system = ("You write social media copy for short animated Reels/Shorts starring a cute low-poly catgirl who "
              "answers curious questions. Reply with JSON only:\n"
              '{"caption": "1-2 short punchy sentences that hook viewers and tease the answer, may end with a '
              'question to drive comments, at most 2 emoji, no hashtags", '
              '"hashtags": ["8-10 specific hashtags about the TOPIC people actually search, e.g. #science #ants '
              '#funfacts #didyouknow #animation - lowercase, no spaces"], '
              '"youtube_title": "catchy title under 70 characters, may end with #shorts", '
              '"discord": "a friendly 1-2 sentence announcement for a Discord server, no hashtags"}\n'
              "Don't use the words nya or meow. Don't invent facts that aren't in the script.")
    user = f"Title: {title}\nScript:\n{script}"
    r = chat_json(url, model, system, user, temperature)
    tags = [t for t in (r.get("hashtags") or []) if isinstance(t, str)]
    return {"caption": TITLE_JUNK.sub("", str(r.get("caption") or "")).strip(), "hashtags": tags,
            "youtube_title": TITLE_JUNK.sub("", str(r.get("youtube_title") or "")).strip(),
            "discord": TITLE_JUNK.sub("", str(r.get("discord") or "")).strip()}
