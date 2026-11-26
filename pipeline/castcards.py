"""
"Who and what appears": one card per cast member and cutaway of a directed episode, BEFORE the render - what will
play it (one of your actors, an imported model, a built-in prop, a prop from the library with its look-check score,
or "will be designed"), with a picture, so a grey-wolf kudu can be swapped before rendering instead of after.
Nothing is made or asked of the AI here: the same order as run_episode.resolve_cast (imported > built-in > library >
designed), minus the steps that need the AI.

Swaps the cards write into the episode's cast entry (run_episode.resolve_cast reads them):
    "model_id": "<imported model id>"   play it with this imported model (people too: they move as a whole)
    "form": "sprite"                    a drawn 2D picture (ComfyUI) instead of a 3D model
    "generated": true                   the studio designs its own 3D model (not an imported one)
"""
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _imported_pic(mid):
    return f"/impimg/{mid}.png" if mid and (ROOT / "assets" / "imported" / "previews" / f"{mid}.png").exists() else None


def _prop_pic(kind, d):
    if d.get("sprite") and (ROOT / d["sprite"]).exists() and (d.get("complex") or not d.get("parts")):
        return f"/propimg/{Path(d['sprite']).name}"
    if (ROOT / "assets" / "props" / f"{kind}.3d.png").exists():
        return f"/propimg/{kind}.3d.png"
    if d.get("sprite") and (ROOT / d["sprite"]).exists():
        return f"/propimg/{Path(d['sprite']).name}"
    return None


def _model_of(d):
    """(model id, name) of an imported def: one model, or the first of a crowd."""
    if not isinstance(d, dict):
        return None, ""
    if isinstance(d.get("model"), dict):
        return d["model"].get("id"), d.get("name", "")
    if d.get("crowd"):
        return _model_of(d["crowd"][0])[0], d.get("name", "")
    return None, ""


def card_for(who, info, setting="", speaks=False):
    """What will play one cast member: {source, label, picture, score, form}. A speaking person is always one of
    your actors (the user: imported people are posed background figures, for people who don't speak)."""
    import actors as AC
    import imported
    import propgen
    import setgen
    looks = info.get("looks") or who.replace("_", " ")
    if info.get("model_id") and not (speaks and info.get("type") == "person"):    # your own pick on the card
        m = imported.model_def(info["model_id"], kind=who, looks=looks)
        return {"source": "imported", "label": f"Your pick: {(m or {}).get('name') or info['model_id']}",
                "picture": _imported_pic(info["model_id"]), "picked": True}
    if info.get("def") and info["def"].get("source") == "imported":
        mid, name = _model_of(info["def"])
        return {"source": "imported", "label": f"Imported: {name}", "picture": _imported_pic(mid)}
    person = info.get("type") == "person" or (info.get("type") != "thing" and imported_kind(who) == "person")
    if person:
        act = AC.pick(who, info.get("actor"), looks=looks, person=True)
        if (not act or act.get("builtin")) and speaks:
            act = AC.side_character(who, looks)
        if act and not act.get("builtin"):
            return {"source": "actor", "label": f"Your actor: {act['name']}" + (" ⭐" if act.get("regular") else ""),
                    "picture": actor_pic(act), "actor": act["id"]}
        if speaks:
            return {"source": "body", "label": "The studio's own body (add actors on Assets → Actors)", "picture": None}
        pd = imported.person_def(who, looks, setting)
        if pd:
            mid, _n = _model_of(pd)
            return {"source": "imported", "label": f"Imported person: {pd.get('name', '')}", "picture": _imported_pic(mid)}
        return {"source": "body", "label": "The studio's own body", "picture": None}
    kind = propgen.slug(info.get("prop") or who)
    if not info.get("generated"):
        try:
            d = imported.crowd_def(kind, looks, setting) if imported.is_group(kind) else imported.match(kind, looks, setting)
        except Exception:
            d = None
        if d:
            mid, name = _model_of(d)
            return {"source": "imported", "label": f"Imported: {name}", "picture": _imported_pic(mid)}
        if kind in setgen.PROPS and kind not in ("hill", "water", "fence", "rug"):
            return {"source": "builtin", "label": f"Built-in prop: {kind.replace('_', ' ')}", "picture": None}
    lib = propgen.library().get(kind)
    if lib:
        sprite = bool(lib.get("complex")) or info.get("form") == "sprite"
        score = lib.get("look_score")
        return {"source": "library", "label": ("Drawn picture" if sprite else "Made 3D model") + " from your props",
                "picture": _prop_pic(kind, lib), "score": score, "form": "sprite" if sprite else "3d"}
    return {"source": "new", "label": "Will be designed at render (about a minute)" + (
        " as a drawn picture" if info.get("form") == "sprite" else ""), "picture": None,
        "form": info.get("form") or "3d"}


def actor_pic(a):
    if a.get("kind") == "imported":
        return _imported_pic(a.get("model_id"))
    if a.get("kind") == "rigged" and a.get("model"):
        stem = Path(a["model"]).stem
        if (ROOT / "assets" / "characters" / f"{stem}.preview.png").exists():
            return f"/charimg/{stem}.preview.png"
    return None


def imported_kind(who):
    import autodirect
    return autodirect.cast_kind(who)


def cards(ep, log=lambda *_: None):
    """[{who, type, looks, cutaway, shots: [1-based], source, label, picture, score?, form?}] for an episode."""
    import run_episode as R
    e = copy.deepcopy(ep)
    e.setdefault("cast", {})
    R.resolve_cutaways(e, log=log)                           # the cutaways' subjects become cast members, as at render
    setting = str(e.get("set") or "")
    out = []
    for who, info in (e.get("cast") or {}).items():
        info = info if isinstance(info, dict) else {}
        shots = sorted({k + 1 for k, s in enumerate(e["shots"]) for ev in s.get("events") or [] if ev.get("who") == who})
        cut = any(ev.get("who") == who and ev.get("cutaway") for s in e["shots"] for ev in s.get("events") or [])
        speaks = any(s.get("speaker") == who and s.get("line") for s in e["shots"])
        try:
            c = card_for(who, info, setting, speaks)
        except Exception as exc:                          # one odd entry never hides the others
            c = {"source": "?", "label": f"(couldn't tell: {exc.__class__.__name__})", "picture": None}
        out.append({"who": who, "type": info.get("type") or imported_kind(who), "looks": info.get("looks") or "",
                    "cutaway": cut, "shots": shots, "speaks": speaks, **c})
    return out
