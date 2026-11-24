"""
API for actors (extra people for scenes), mounted by web/server.py under /api/actors. The logic lives in
pipeline/actors.py; this module only handles the requests.

    GET    /api/actors            -> {actors: [...], models: {rigs: [...], imported: [...]}}
    POST   /api/actors            -> body = an actor (no id): creates one; returns it
    PUT    /api/actors/<id>       -> body = an actor: updates it
    DELETE /api/actors/<id>       -> moves the actor's file to assets/actors/.trash
"""
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
