"""
Actors: the extra people (and things with people's shapes) that appear in scenes - a store clerk, a customer,
a generic human. They are NOT main characters: those live in assets/characters (the catgirl and co-stars).

An actor is one JSON file in assets/actors/<id>.json:
    name        "Store clerk"
    role        "store clerk"             what they are - matched against cast names (+clerk, +store_clerk)
    description "behind the counter, polo shirt, tired smile"   (fed to the script AI and shown on the page)
    kind        "generic"  - the studio's own body, dressed with `look` (hair, skin, dress, pants, shoes...)
                "rigged"   - a rigged .blend (e.g. one made with prepare_character.py); animated like a character
                "imported" - a real model from an imported pack (assets/imported); it moves as a whole
    look        {...}      generic only: colours, see blender_build.DEFAULT_LOOK
    model       rigged only: path relative to the project, e.g. assets/characters/pokemon.blend
    model_id    imported only: the imported model's id (assets/imported/index.json)
    height      metres (generic: the body's height factor, 1.0 = average adult)
    personality how they talk and act ("grumpy, says 'back in my day'") - the script writer reads it
    regular     true = a recurring cast member: offered in Custom Video's Idea step, and the writer knows them
    catchphrase what they always say ("Back in my day...") - the writer has them say it once
    gag         a running gag ("always losing her glasses") - the writer works it in
    history     what they said in their last videos, kept by the render (remember) - the writer may call back
    voice       their own voice (kept when the actor is edited, so a regular always sounds the same)
    builtin     true for the generic human that always exists (not stored as a file)

Deleting an actor moves its file to assets/actors/.trash - nothing is hard-deleted.
"""
import json
import re
import time
from pathlib import Path

import imported as IMP

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "assets" / "actors"
TRASH = DIR / ".trash"
KINDS = ("generic", "rigged", "imported")
GENERIC_ID = "generic_human"
# every actor speaks with this cheap generic voice unless their file names another one
ACTOR_VOICE = {"engine": "edge", "name": "en-US-EricNeural", "rate": "+0%", "pitch": "+0Hz"}
NOISE = {"the", "a", "an", "of", "and", "with", "in", "on", "at", "one", "some", "person", "people", "actor"}

# role words -> which kind of voice a generic actor gets (a voice set on the actor always wins)
FEMALE_WORDS = set("""mom mum mother mama mommy grandma granny grandmother nana sister sis aunt auntie woman women lady
girl girls wife bride daughter queen princess witch waitress actress nun mrs miss ms she her female girlfriend
""".split())
MALE_WORDS = set("""dad father papa daddy grandpa grandfather brother bro uncle man men guy gentleman boy boys husband
groom son king prince wizard waiter actor mr sir he him male boyfriend""".split())
CHILD_WORDS = set("kid kids child children baby toddler little tiny boy girl son daughter".split())
OLD_WORDS = set("grandma granny grandmother nana grandpa grandfather old elderly".split())
ROLE_VOICES = {   # several per kind: two cast people of the same kind usually sound different
    "female": ["en-US-JennyNeural", "en-US-AriaNeural", "en-US-MichelleNeural", "en-GB-SoniaNeural"],
    "male": ["en-US-EricNeural", "en-US-GuyNeural", "en-US-ChristopherNeural", "en-GB-RyanNeural"],
    "old_female": ["en-GB-SoniaNeural"], "old_male": ["en-US-RogerNeural"],
    "girl": ["en-GB-MaisieNeural"], "boy": ["en-GB-MaisieNeural"],
}


def role_voice(name, looks="", voice=None):
    """The voice a cast person speaks with. An actor's own voice (anything but the generic default) wins; otherwise
    their name and description pick a female/male/child/elderly Edge voice ("mom" no longer sounds like a man)."""
    voice = dict(voice or ACTOR_VOICE)
    if voice != ACTOR_VOICE:
        return voice
    ws = set(re.split(r"[^a-z]+", f"{name} {looks}".lower().replace("_", " ")))
    female, male = ws & FEMALE_WORDS, ws & MALE_WORDS
    if not female and not male:
        return voice
    kind = "female" if len(female) >= len(male) else "male"
    if ws & OLD_WORDS:
        kind = "old_" + kind
    elif ws & CHILD_WORDS:
        kind = "girl" if kind == "female" else "boy"
    pool = ROLE_VOICES[kind]
    pick = pool[sum(map(ord, str(name))) % len(pool)]
    return {**voice, "name": pick, "pitch": "+10Hz" if kind == "boy" else "+0Hz"}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:48]


def words(text):
    return {w for w in re.split(r"[^a-z0-9]+", str(text or "").lower()) if w and w not in NOISE and len(w) > 1}


BUILTIN = {
    "id": GENERIC_ID, "name": "Generic human", "role": "anyone", "kind": "generic", "builtin": True,
    "description": "The studio's own body in plain clothes. Used for any extra person nobody else matches.",
    "look": {}, "height": 1.0, "voice": dict(ACTOR_VOICE),
}


def _load(path):
    try:
        rec = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    rec["id"] = path.stem
    rec.setdefault("kind", "generic")
    rec.setdefault("name", path.stem.replace("_", " ").title())
    rec.setdefault("role", "")
    rec.setdefault("description", "")
    rec.setdefault("look", {})
    rec.setdefault("height", 1.0)
    rec.setdefault("voice", dict(ACTOR_VOICE))
    rec.setdefault("personality", "")
    rec.setdefault("regular", False)
    rec.setdefault("catchphrase", "")
    rec.setdefault("gag", "")
    rec.setdefault("history", [])
    rec["builtin"] = False
    return rec


def all_actors():
    """Built-in first, then the saved actors by name."""
    out = [dict(BUILTIN)]
    if DIR.exists():
        saved = [a for a in (_load(p) for p in sorted(DIR.glob("*.json"))) if a]
        out += sorted(saved, key=lambda a: a["name"].lower())
    return out


def get(aid):
    for a in all_actors():
        if a["id"] == aid:
            return a
    return None


def _tags(a):
    return words(a.get("name")) | words(a.get("role"))


def pick(who, explicit=None, looks="", person=False):
    """The actor for a cast name: the one named by `explicit`, else the one whose name or role matches the
    cast name (at least half its words), else the generic human when `person` is true, else None."""
    if explicit:
        return get(explicit) or (BUILTIN if explicit == GENERIC_ID else None)
    want = words(who)
    best, best_ratio = None, 0.0
    for a in all_actors():
        if a.get("builtin") or not want:
            continue
        ratio = len(want & _tags(a)) / len(want)
        if ratio >= 0.5 and ratio > best_ratio:
            best, best_ratio = a, ratio
    if best:
        return best
    return dict(BUILTIN) if person else None


def model_choices():
    """Everything an actor can be made from: rigged .blend files, and ready imported models."""
    import settings as S
    main = S.load_settings().get("active_character", "catgirl")   # the main character's models are not actors
    rigs = []
    for folder in (ROOT / "assets" / "characters", DIR / "rigs"):
        if folder.exists():
            for p in sorted(folder.glob("*.blend")):
                if folder.name == "characters" and p.stem.startswith(main):
                    continue
                pic = folder / f"{p.stem}.preview.png"
                rigs.append({"path": str(p.relative_to(ROOT)).replace("\\", "/"), "name": p.stem.replace("_", " "),
                             "source": "character" if folder.name == "characters" else "actor rig",
                             "preview": f"/charimg/{p.stem}.preview.png" if folder.name == "characters" and pic.exists() else None})
    imported = []
    cats = IMP.category_map()                 # the same categories as Assets -> Imported (the picker's chips)
    for pack in IMP.packs():
        for m in pack.get("models", []):
            if m.get("status") == "ok":
                imported.append({"id": m["id"], "name": m["name"], "pack": pack["name"],
                                 "category": cats.get(m["id"]) or "Other",
                                 "height": m.get("height"), "preview": m.get("preview")})
    return {"rigs": rigs, "imported": imported}


def imported_def(actor):
    """The prop definition for an imported actor (it is placed like a prop, so it goes through the set code)."""
    import imported
    d = imported.model_def(actor.get("model_id", ""), kind="actor_" + actor["id"], looks=actor.get("role", ""))
    if d:
        d["person"] = True                        # p_model lowers the arms of a T-posed person model
    return d


def save(data, aid=None):
    """Create or update an actor. The id comes from the name for new actors."""
    kind = str(data.get("kind") or "generic")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    name = str(data.get("name") or "").strip()[:60]
    if not name:
        raise ValueError("give the actor a name")
    if kind == "rigged" and not str(data.get("model") or "").endswith(".blend"):
        raise ValueError("pick a rigged .blend model for this actor")
    if kind == "imported" and not data.get("model_id"):
        raise ValueError("pick an imported model for this actor")
    aid = aid or slug(name) or f"actor_{int(time.time())}"
    if aid == GENERIC_ID:
        raise ValueError("that name is reserved for the built-in generic human")
    rec = {"name": name, "role": str(data.get("role") or "").strip()[:60],
           "description": str(data.get("description") or "").strip()[:600], "kind": kind,
           "height": round(max(0.5, min(1.6, float(data.get("height") or 1.0))), 2),
           "personality": str(data.get("personality") or "").strip()[:300], "regular": bool(data.get("regular")),
           "catchphrase": str(data.get("catchphrase") or "").strip()[:120], "gag": str(data.get("gag") or "").strip()[:200]}
    for k in ("from_video",):
        if data.get(k):
            rec[k] = str(data[k])[:80]
    old = get(aid) if aid else None
    if old and old.get("history"):
        rec["history"] = old["history"]                   # the render keeps it - an edit doesn't wipe it
    v = data.get("voice")
    if isinstance(v, dict) and v.get("engine"):
        rec["voice"] = {**ACTOR_VOICE, **{k: str(x) for k, x in v.items()}}
    elif old and isinstance(old.get("voice"), dict):
        rec["voice"] = old["voice"]                       # the form doesn't send it: a regular keeps their voice
        if old.get("from_video") and "from_video" not in rec:
            rec["from_video"] = old["from_video"]
    else:
        rec["voice"] = dict(ACTOR_VOICE)
    if kind == "generic":
        rec["look"] = {k: str(v)[:9] for k, v in (data.get("look") or {}).items() if isinstance(v, str)}
    if kind == "rigged":
        rec["model"] = str(data["model"]).replace("\\", "/")
        if not (ROOT / rec["model"]).exists():
            raise ValueError(f"model not found: {rec['model']}")
    if kind == "imported":
        rec["model_id"] = str(data["model_id"])
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{aid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    return {**rec, "id": aid, "builtin": False}


def side_character(who, looks=""):
    """A GENERIC actor of yours (the studio body) for a speaking cast person no actor's role matches ("mom", "a
    grumpy neighbour") - the user: imported people are for people who don't speak, and a role that doesn't fit gets
    a generic actor with random colours (run_episode does the colours), not a random imported character. Prefers
    one of the same kind (woman / man / child, from the words); the same name always gets the same one. None when
    you have no generic actors (the built-in generic human plays them)."""
    import hashlib
    mine = [a for a in all_actors() if not a.get("builtin") and a.get("kind") == "generic"]
    if not mine:
        return None
    want = words(f"{who} {looks}")
    kind = ("child" if want & CHILD_WORDS else "female" if want & FEMALE_WORDS else
            "male" if want & MALE_WORDS else None)

    def kind_of(a):
        ws = words(f"{a.get('name')} {a.get('role')} {a.get('description')}")
        return "child" if ws & CHILD_WORDS else "female" if ws & FEMALE_WORDS else "male" if ws & MALE_WORDS else None
    pool = [a for a in mine if kind and kind_of(a) == kind] or [a for a in mine if kind_of(a) is None] or mine
    k = int(hashlib.md5(str(who).encode()).hexdigest()[:8], 16)
    return sorted(pool, key=lambda a: a["id"])[k % len(pool)]


def regulars():
    """The recurring cast: saved actors marked regular (Custom Video offers them, the writer knows them)."""
    return [a for a in all_actors() if a.get("regular") and not a.get("builtin")]


def writer_note(ids):
    """What the script writer is told about the regulars picked for a video ("" when none)."""
    picked = [a for a in (get(i) for i in ids or []) if a and not a.get("builtin")]
    if not picked:
        return ""
    def one(a):
        bits = [f"{a['name']} (+{a['id']})" + (f" - {a['role']}" if a.get("role") else "")
                + (f", {a['personality']}" if a.get("personality") else "")
                + (f" ({a['description'][:120]})" if a.get("description") else "")]
        if a.get("catchphrase"):
            bits.append(f"their catchphrase, said once: \"{a['catchphrase']}\"")
        if a.get("gag"):
            bits.append(f"running gag: {a['gag']}")
        last = (a.get("history") or [])[-1:]
        if last and last[0].get("lines"):
            bits.append(f"last time (\"{last[0].get('title', '')}\") they said: \"{' / '.join(last[0]['lines'][:2])}\" "
                        "- a short callback to it is welcome")
        return "; ".join(bits)
    who = " | ".join(one(a) for a in picked)
    return ("Regulars of the show who come back in these videos - use ALL of them: " + who + ". Bring each one in "
            "with [+id enter] (that exact id) on their first line, give each at least one line of their own as "
            "'Name: ...', and keep them in character.")


HISTORY_KEEP = 4


def remember(ep, log=print):
    """After a render: what each regular said in it (their own 'Name:' lines), kept on their actor (the last
    HISTORY_KEEP videos), so the next script can call back to it."""
    cast = ep.get("cast") or {}
    for who, info in cast.items():
        aid = (info or {}).get("actor")
        a = get(aid) if aid else None
        if not a or a.get("builtin") or not a.get("regular"):
            continue
        lines = [str(s.get("line_src") or s.get("line") or "").strip() for s in ep.get("shots") or []
                 if s.get("speaker") == who]
        lines = [x for x in lines if x][:4]
        if not lines:
            continue
        path = DIR / f"{aid}.json"
        try:
            rec = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        hist = [h for h in rec.get("history") or [] if h.get("title") != ep.get("title")]
        hist.append({"title": str(ep.get("title") or "")[:80], "lines": lines, "time": int(time.time())})
        rec["history"] = hist[-HISTORY_KEEP:]
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"  regular {a['name']}: remembered {len(lines)} line(s) for next time")


def from_cast(who, info, name="", episode=""):
    """An actor from a cast member of a rendered video (build/<name>/resolved.json): the same body, colours,
    height and voice next time. A person played by an imported model stays that model."""
    info = info or {}
    data = {"name": name or who.replace("_", " ").title(), "role": who.replace("_", " "),
            "description": str(info.get("looks") or "")[:600], "regular": True, "from_video": episode}
    d = info.get("def") or {}
    if info.get("actor") and info["actor"] != GENERIC_ID and get(info["actor"]):
        base = get(info["actor"])                        # already played by one of your actors: copy it
        data.update(kind=base["kind"], look=base.get("look") or {}, height=base.get("height", 1.0))
        for k in ("model", "model_id"):
            if base.get(k):
                data[k] = base[k]
    elif isinstance(d.get("model"), dict) and d["model"].get("id"):
        data.update(kind="imported", model_id=d["model"]["id"])     # an imported person (or thing) played them
    else:                                                # the studio's own body: its colours and build
        data.update(kind="generic", look={k: v for k, v in (info.get("look") or {}).items() if isinstance(v, str)},
                    height=float(info.get("height") or 1.0))
    data["voice"] = role_voice(who, info.get("looks") or "", info.get("voice"))
    return save(data)


def remove(aid):
    if aid == GENERIC_ID:
        raise ValueError("the generic human can't be removed")
    src = DIR / f"{aid}.json"
    if not src.exists():
        raise ValueError("no such actor")
    TRASH.mkdir(parents=True, exist_ok=True)
    src.replace(TRASH / f"{aid}-{time.strftime('%Y%m%d-%H%M%S')}.json")
