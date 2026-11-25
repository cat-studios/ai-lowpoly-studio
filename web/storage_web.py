"""
Settings -> Free up disk space (mounted by web/server.py under /api/storage).

    GET  /api/storage                 -> {"groups": [...], "total": bytes}
    POST /api/storage/clean {what}    -> what = "frames" | "previous" | "trash" | "generated"

What can be cleaned, and what it costs:
  frames   - render work files in build/<episode>/ (PNG frames, Blender scenes). Deleted for good. Renders make them
             again; until then "Re-apply look only" doesn't work for those videos. Voices, timing and logs stay.
  previous - earlier versions of videos (output/previous/) -> moved to output/.trash (nothing freed until emptied).
  trash    - every .trash folder in the project, emptied for good (the page lists them first).
The voice cache (build/tts_cache) is shown but never cleaned here: re-rendering an old video would record new takes.
Refused while a job is queued or running.
"""
import os
import shutil
import stat
import time
from pathlib import Path

TRASH_DIRS = [".trash", "output/.trash", "episodes/.trash", "sets/.trash", "assets/props/.trash",
              "assets/music/.trash", "assets/sfx/custom/.trash", "assets/actors/.trash",
              "assets/imported/packs/.trash", "assets/characters/.trash"]
FRAME_GLOBS = ["build/*/frames", "build/*/scene*/frames", "build/*/scene.blend", "build/*/scene*/scene.blend",
               "build/*/scene.blend1", "build/*/scene*/scene.blend1"]


def _size(p):
    """(bytes, files) of a file or folder."""
    p = Path(p)
    if p.is_file():
        return p.stat().st_size, 1
    total = files = 0
    for dirpath, _dirs, names in os.walk(p):
        for n in names:
            try:
                total += os.stat(os.path.join(dirpath, n)).st_size
                files += 1
            except OSError:
                pass
    return total, files


def _generated(root):
    """Everything the AI made: generated sets (recipe, preview, 3D view, texture folder) and the prop library
    (3D props, sprites, their pictures). Not themes, the hidden list, imported models or anything else."""
    out = []
    sets = root / "sets"
    if sets.is_dir():
        for js in sets.glob("*.json"):
            if js.name.startswith("."):
                continue
            out.append(js)
            out += [p for p in (sets / f"{js.stem}.png", sets / f"{js.stem}.glb", sets / js.stem) if p.exists()]
    props = root / "assets" / "props"
    if props.is_dir():
        out += [p for p in props.iterdir() if p.is_file() and not p.name.startswith(".")
                and p.suffix in (".json", ".png")]
    return out


def _frame_paths(root):
    return [p for g in FRAME_GLOBS for p in root.glob(g) if "tts_cache" not in p.parts]


def report(root):
    root = Path(root)
    groups = []
    fb = ff = 0
    for p in _frame_paths(root):
        b, f = _size(p)
        fb, ff = fb + b, ff + f
    groups.append({"key": "frames", "label": "Render work files (frames, Blender scenes)", "bytes": fb, "files": ff,
                   "action": "delete",
                   "note": "Deleted for good. A new render makes them again; until then “Re-apply look only” "
                           "doesn't work for those videos. Finished videos are not touched."})
    pb, pf = _size(root / "output" / "previous") if (root / "output" / "previous").is_dir() else (0, 0)
    groups.append({"key": "previous", "label": "Earlier versions of videos (output/previous)", "bytes": pb,
                   "files": pf, "action": "trash",
                   "note": "Moved to output/.trash - empty the trash afterwards to free the space."})
    parts, tb, tf = [], 0, 0
    for rel in TRASH_DIRS:
        d = root / rel
        if d.is_dir():
            b, f = _size(d)
            if f:
                parts.append({"path": rel, "bytes": b, "files": f})
                tb, tf = tb + b, tf + f
    groups.append({"key": "trash", "label": "Trash folders", "bytes": tb, "files": tf, "action": "empty",
                   "parts": parts,
                   "note": "Everything you removed in the app (videos, sets, sounds, props, packs...) and the code "
                           "backup. Deleted for good - it can't be undone."})
    gen = _generated(root)
    nsets = sum(1 for p in gen if p.parent.name == "sets" and p.suffix == ".json")
    nprops = sum(1 for p in gen if p.parent.name == "props" and p.suffix == ".json")
    gb = sum(_size(p)[0] for p in gen)
    groups.append({"key": "generated", "label": f"Everything the AI made: {nsets} scene(s), {nprops} prop(s) and "
                                                 f"sprite(s)",
                   "bytes": gb, "files": len(gen), "action": "trash",
                   "note": "Generated sets (with their previews, 3D views and textures) and every made 3D prop and "
                           "2D sprite move to the trash, so new videos make fresh ones. Built-in Legacy Cafe/Park, "
                           "your imported models, characters and finished videos stay. Older videos that used them "
                           "can't be re-rendered until the trash is restored."})
    cb, cf = _size(root / "build" / "tts_cache") if (root / "build" / "tts_cache").is_dir() else (0, 0)
    groups.append({"key": "tts", "label": "Voice cache (build/tts_cache)", "bytes": cb, "files": cf, "action": None,
                   "note": "Kept: re-rendering an old video would otherwise record new voice takes."})
    ob = sum(p.stat().st_size for p in (root / "output").glob("*.mp4"))
    groups.append({"key": "videos", "label": "Finished videos (output)", "bytes": ob,
                   "files": len(list((root / "output").glob("*.mp4"))), "action": None,
                   "note": "Remove single videos on the Videos page (they go to the trash)."})
    return {"groups": groups, "total": sum(g["bytes"] for g in groups)}


def _rm(p):
    """Delete a file or folder for good (read-only files too)."""
    def onerr(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    p = Path(p)
    if p.is_dir():
        shutil.rmtree(p, onexc=onerr)
    elif p.exists():
        try:
            p.unlink()
        except PermissionError:
            os.chmod(p, stat.S_IWRITE)
            p.unlink()


def clean(root, what):
    root = Path(root)
    before = report(root)["total"]
    if what == "frames":
        for p in _frame_paths(root):
            _rm(p)
    elif what == "previous":
        src = root / "output" / "previous"
        if src.is_dir():
            dst = root / "output" / ".trash"
            dst.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for f in src.iterdir():
                f.replace(dst / f"{f.stem}-trashed-{stamp}{f.suffix}")
    elif what == "generated":            # to sets/.trash/cleared-<stamp>/ and assets/props/.trash/cleared-<stamp>/
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for p in _generated(root):
            dst = p.parent / ".trash" / f"cleared-{stamp}"
            dst.mkdir(parents=True, exist_ok=True)
            p.replace(dst / p.name)
    elif what == "trash":
        for rel in TRASH_DIRS:
            d = root / rel
            if d.is_dir():
                for child in d.iterdir():           # the folders themselves stay
                    _rm(child)
    else:
        raise ValueError("unknown clean-up")
    after = report(root)
    return {"ok": True, "freed": max(0, before - after["total"]), **after}


def handle(h, method, parts, *, root, busy):
    arg = parts[0] if parts else ""
    if method == "GET" and not arg:
        return h.send_json(report(root))
    if method == "POST" and arg == "clean":
        if busy:
            raise ValueError(f"{len(busy)} job(s) are queued or running - wait until they finish, then clean up")
        return h.send_json(clean(root, str((h.body_json() or {}).get("what") or "")))
    return h.fail("not found", 404)
