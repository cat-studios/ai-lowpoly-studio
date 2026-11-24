"""
API for imported real assets (mounted by web/server.py under /api/imported). The logic lives in
pipeline/imported.py; this module only handles the requests and starts the import as a background job.

    GET    /api/imported                -> {packs: [...]}
    POST   /api/imported/upload         -> body = the .zip, headers X-Filename, X-Pack-Name, X-License
    DELETE /api/imported/pack/<id>      -> moves the pack to assets/imported/packs/.trash (never hard-deletes)
    GET    /api/imported/all            -> {models: [... with "category"], packs: [...]} (the Assets page)
    DELETE /api/imported/model/<id>     -> one model's files to packs/.trash/models-<stamp>/
    POST   /api/imported/delete         -> {"ids": [...]} several models at once (same trash)
"""
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote


def handle(h, method, parts, *, submit, Job, root):
    """h is the request handler (server.Handler); submit/Job/root come from server.py."""
    import imported as IM
    arg = parts[0] if parts else ""

    if method == "GET" and not arg:
        return h.send_json({"packs": IM.packs()})

    if method == "GET" and arg == "models":      # every ready model, flat, for the video editor's model picker
        return h.send_json([{"id": m["id"], "name": m["name"], "pack": p["name"], "height": m.get("height")}
                            for p in IM.packs() for m in p.get("models", []) if m.get("status") == "ok"])

    if method == "POST" and arg == "upload":
        fname = Path(unquote(h.headers.get("X-Filename") or "pack.zip")).name
        if Path(fname).suffix.lower() != ".zip":
            raise ValueError("upload a .zip file (the model pack as downloaded)")
        pack_name = unquote(h.headers.get("X-Pack-Name") or "").strip() or Path(fname).stem
        license_text = unquote(h.headers.get("X-License") or "").strip() or None
        dest = IM.UPLOADS / f"{time.strftime('%Y%m%d-%H%M%S')}-{IM.slug(Path(fname).stem)}.zip"
        h.body_to_file(dest)                    # keeps a copy of the zip in assets/imported/.uploads
        cmd = [sys.executable, "-u", str(root / "pipeline" / "imported.py"), "import", str(dest),
               "--pack", pack_name[:80], "--source", fname[:120]]
        if license_text:
            cmd += ["--license", license_text[:200]]
        return h.send_json(submit(Job("import", f"Import pack: {pack_name[:60]}", cmd)).to_dict())

    if method == "GET" and arg == "all":         # every model with its auto category (the Assets page)
        return h.send_json({"models": IM.categorised(),
                            "packs": [{k: p.get(k) for k in ("id", "name", "license", "source", "added", "skipped")}
                                      | {"count": len(p.get("models", []))} for p in IM.packs()]})

    if method == "DELETE" and arg == "model" and len(parts) > 1:   # one model (its files go to the trash)
        return h.send_json({"ok": True, "deleted": IM.delete_models([parts[1]])})

    if method == "POST" and arg == "delete":      # several models at once: {"ids": [...]}
        ids = [str(i) for i in (h.body_json().get("ids") or []) if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", str(i))]
        if not ids:
            raise ValueError("no models chosen")
        return h.send_json({"ok": True, "deleted": IM.delete_models(ids)})

    if method == "DELETE" and arg == "pack" and len(parts) > 1:
        pid = parts[1]
        if not re.fullmatch(r"[a-z0-9_]{1,80}", pid):
            raise ValueError("bad pack id")
        IM.delete_pack(pid)
        return h.send_json({"ok": True})

    return h.fail("not found", 404)
