"""
API for actors (extra people for scenes), mounted by web/server.py under /api/actors. The logic lives in
pipeline/actors.py; this module only handles the requests.

    GET    /api/actors            -> {actors: [...], models: {rigs: [...], imported: [...]}}
    POST   /api/actors            -> body = an actor (no id): creates one; returns it
    PUT    /api/actors/<id>       -> body = an actor: updates it
    DELETE /api/actors/<id>       -> moves the actor's file to assets/actors/.trash
    POST   /api/actors/<id>/model -> body = a VRoid .vrm (X-Filename): made into assets/actors/rigs/<id>.blend like a
                                     main character (prepare_character.py), the actor becomes kind "rigged" (a job)
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _import_vrm_job(aid, vrm, root, submit, Job):
    """VRM -> assets/actors/rigs/<id>.blend (the same preparation as a main character), then the actor is rigged
    with it and gets a preview picture."""
    import actors as AC
    from run_episode import BLENDER_DEFAULT, tool
    root = Path(root)
    blend = vrm.with_suffix(".blend")
    cmd = [tool("blender", "BLENDER", BLENDER_DEFAULT), "-b", "--factory-startup", "--python",
           str(root / "pipeline" / "prepare_character.py"), "--", str(vrm), "--out", str(blend)]

    def done(job):
        a = AC.get(aid) or {"name": aid}
        rel = str(blend.relative_to(root)).replace("\\", "/")
        AC.save({**a, "kind": "rigged", "model": rel}, aid=aid)
        job.result = {"actor": aid, "model": rel}
        submit(Job("import", f"Actor preview: {a.get('name', aid)}",
                   [sys.executable, "-u", str(root / "pipeline" / "character_preview.py"), "--actor", aid]))
    return Job("import", f"Import {vrm.name} -> actor {aid}", cmd, done)


def _picture(a, root):
    """A picture for the card: rigged actors use their character's preview, imported ones the model's picture."""
    if a["kind"] == "rigged" and a.get("model"):
        stem = Path(a["model"]).stem
        rig = root / "assets" / "actors" / "rigs" / f"{stem}.preview.png"      # an uploaded VRoid actor
        if rig.exists():
            return f"/actorimg/{stem}.preview.png?v={int(rig.stat().st_mtime)}"
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

    if method == "POST" and arg and len(parts) > 1 and parts[1] == "model":
        from urllib.parse import unquote
        if not re.fullmatch(r"[a-z0-9_]{1,48}", arg) or not AC.get(arg) or arg == AC.GENERIC_ID:
            raise ValueError("save the actor first")
        fname = unquote(h.headers.get("X-Filename") or "model.vrm")
        if not fname.lower().endswith(".vrm"):
            raise ValueError("upload a .vrm file exported from VRoid Studio")
        rigs = Path(root) / "assets" / "actors" / "rigs"
        rigs.mkdir(parents=True, exist_ok=True)
        dest = rigs / f"{arg}.vrm"
        for old in (dest, dest.with_suffix(".blend")):              # keep the previous model, never overwrite it
            if old.exists():
                bak = rigs / ".trash"
                bak.mkdir(exist_ok=True)
                shutil.copy2(old, bak / f"{old.stem}-{_stamp()}{old.suffix}")
        h.body_to_file(dest)
        return h.send_json(submit(_import_vrm_job(arg, dest, root, submit, Job)).to_dict())

    if method == "DELETE" and arg:
        if not re.fullmatch(r"[a-z0-9_]{1,48}", arg):
            raise ValueError("bad actor id")
        AC.remove(arg)
        return h.send_json({"ok": True})

    return h.fail("not found", 404)
