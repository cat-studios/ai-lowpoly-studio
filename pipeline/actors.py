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
    for pack in IMP.packs():
        for m in pack.get("models", []):
            if m.get("status") == "ok":
                imported.append({"id": m["id"], "name": m["name"], "pack": pack["name"],
                                 "height": m.get("height"), "preview": m.get("preview")})
    return {"rigs": rigs, "imported": imported}


def imported_def(actor):
    """The prop definition for an imported actor (it is placed like a prop, so it goes through the set code)."""
    import imported
    return imported.model_def(actor.get("model_id", ""), kind="actor_" + actor["id"], looks=actor.get("role", ""))


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
           "height": round(max(0.5, min(1.6, float(data.get("height") or 1.0))), 2)}
    v = data.get("voice")
    rec["voice"] = {**ACTOR_VOICE, **{k: str(x) for k, x in v.items()}} if isinstance(v, dict) and v.get("engine") else dict(ACTOR_VOICE)
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


def remove(aid):
    if aid == GENERIC_ID:
        raise ValueError("the generic human can't be removed")
    src = DIR / f"{aid}.json"
    if not src.exists():
        raise ValueError("no such actor")
    TRASH.mkdir(parents=True, exist_ok=True)
    src.replace(TRASH / f"{aid}-{time.strftime('%Y%m%d-%H%M%S')}.json")
