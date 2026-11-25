"""
API for animations made as data (mounted by web/server.py under /api/anims). The logic lives in
pipeline/animlib.py (format, library) and pipeline/animgen.py (the AI writes one, a render is checked).

    GET    /api/anims              -> [{name, description, by, checked, score, problem, picture, builtin}]
    POST   /api/anims/make         -> {"name", "description"} - a background job (Ollama + Blender, ~30-100 s)
    DELETE /api/anims/<name>       -> its .json and .png move to assets/anims/.trash (never hard-deleted)
"""
import re
import sys
import time


def handle(h, method, parts, *, submit, Job, root):
    import animlib
    arg = parts[0] if parts else ""

    if method == "GET" and not arg:
        out = []
        for name, a in sorted(animlib.library().items()):
            pic = animlib.LIB / f"{name}.png"
            out.append({"name": name, "description": a.get("description", ""), "by": a.get("by", ""),
                        "checked": a.get("checked"), "score": a.get("score"), "problem": a.get("problem", ""),
                        "length": a.get("length"), "loop": a.get("loop"), "builtin": name in animlib.BUILTIN,
                        "picture": f"/animimg/{name}.png?v={int(pic.stat().st_mtime)}" if pic.exists() else None})
        return h.send_json(out)

    if method == "POST" and arg == "make":
        b = h.body_json()
        name = animlib.slug(b.get("name"))
        if not name:
            raise ValueError("give the animation a name (one or two words, e.g. salute)")
        desc = str(b.get("description") or "").strip()[:200]
        cmd = [sys.executable, "-u", str(root / "pipeline" / "animgen.py"), "make", name] + ([desc] if desc else [])
        return h.send_json(submit(Job("anim", f"Make animation: {name}", cmd)).to_dict())

    if method == "DELETE" and arg:
        name = animlib.slug(arg)
        if name in animlib.BUILTIN:
            raise ValueError("the built-in examples can't be deleted")
        trash = animlib.LIB / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        moved = 0
        for ext in (".json", ".png"):
            f = animlib.LIB / f"{name}{ext}"
            if f.exists():
                f.replace(trash / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}{ext}")
                moved += 1
        if not moved:
            return h.fail("no such animation", 404)
        return h.send_json({"ok": True})

    return h.fail("not found", 404)


def picture(h, name, root):
    """GET /animimg/<name>.png - an animation's check picture."""
    if not re.fullmatch(r"[\w-]+\.png", name):
        return h.fail("not found", 404)
    return h.send_file(root / "assets" / "anims" / name)
