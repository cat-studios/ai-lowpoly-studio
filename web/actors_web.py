"""
API for actors (extra people for scenes), mounted by web/server.py under /api/actors. The logic lives in
pipeline/actors.py; this module only handles the requests.

    GET    /api/actors            -> {actors: [...], models: {rigs: [...], imported: [...]}}
    POST   /api/actors            -> body = an actor (no id): creates one; returns it
    PUT    /api/actors/<id>       -> body = an actor: updates it
    DELETE /api/actors/<id>       -> moves the actor's file to assets/actors/.trash
"""
import json
import re
from pathlib import Path


def _picture(a, root):
    """A picture for the card: rigged actors use their character's preview, imported ones the model's picture."""
    if a["kind"] == "rigged" and a.get("model"):
        stem = Path(a["model"]).stem
        img = root / "assets" / "characters" / f"{stem}.preview.png"
        if img.exists():
            return f"/charimg/{stem}.preview.png?v={int(img.stat().st_mtime)}"
    if a["kind"] == "imported" and a.get("model_id"):
        img = root / "assets" / "imported" / "previews" / f"{a['model_id']}.png"
        if img.exists():
            return f"/impimg/{a['model_id']}.png"
    return None


def handle(h, method, parts, *, submit, Job, root):
    import actors as AC
    arg = parts[0] if parts else ""

    if method == "GET" and not arg:
        out = []
        for a in AC.all_actors():
            out.append({**a, "picture": _picture(a, root)})
        return h.send_json({"actors": out, "models": AC.model_choices()})

    if method == "POST" and not arg:
        return h.send_json(AC.save(h.body_json()))

    if method == "POST" and arg in ("guests", "keep"):
        # the people in a rendered video (build/<name>/resolved.json, where the render wrote how each one looked)
        # -> keep one as a regular: same body, colours, height and voice in later videos
        import run_episode as R
        b = h.body_json() or {}
        eid = str(b.get("episode") or "")
        if not re.fullmatch(r"[\w.-]{1,120}", eid):
            raise ValueError("bad episode id")
        res = Path(root) / "build" / R.slug(eid) / "resolved.json"
        if not res.exists():
            raise ValueError("render this video first - the guests' looks are saved by the render")
        cast = json.loads(res.read_text(encoding="utf-8-sig")).get("cast") or {}
        people = {w: c for w, c in cast.items() if isinstance(c, dict)
                  and (c.get("type") == "person" or (c.get("def") or {}).get("person"))}
        if arg == "guests":
            have = {a["id"] for a in AC.all_actors()}
            return h.send_json({"guests": [{"who": w, "name": w.replace("_", " ").title(), "looks": c.get("looks", ""),
                                            "kept": AC.slug(w) in have} for w, c in people.items()]})
        who = str(b.get("who") or "")
        if who not in people:
            raise ValueError("no such person in that video")
        return h.send_json(AC.from_cast(who, people[who], name=str(b.get("name") or "").strip()[:60], episode=eid))

    if method == "PUT" and arg:
        if not re.fullmatch(r"[a-z0-9_]{1,48}", arg):
            raise ValueError("bad actor id")
        if not AC.get(arg) or arg == AC.GENERIC_ID:
            raise ValueError("no such actor")
        return h.send_json(AC.save(h.body_json(), aid=arg))

    if method == "DELETE" and arg:
        if not re.fullmatch(r"[a-z0-9_]{1,48}", arg):
            raise ValueError("bad actor id")
        AC.remove(arg)
        return h.send_json({"ok": True})

    return h.fail("not found", 404)
