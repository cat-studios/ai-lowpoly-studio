"""
API for the GIF page (mounted by web/server.py under /api/gif).

    GET  /api/gif                 -> {sources: [...videos to convert], gifs: [...made so far]}
    POST /api/gif/upload          -> body = the video, header X-Filename -> {id} (kept in output/gifs/uploads)
    POST /api/gif/convert         -> {source, width, fps, colors, dither} -> background job (pipeline/gif.py)
    GET  /api/gif/file/<name>.gif -> the GIF itself

Nothing here changes the episode pipeline; the GIFs go to output/gifs/ and are never deleted by the app.
"""
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")
DITHERS = ("sierra2_4a", "floyd_steinberg", "bayer", "none")


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:50] or "clip"


def _entry(p, url=None):
    st = p.stat()
    return {"name": p.name, "url": url, "size": st.st_size, "updated": st.st_mtime}


def _source_path(root, sid):
    kind, _, name = (sid or "").partition(":")
    base = {"out": root / "output", "up": root / "output" / "gifs" / "uploads"}.get(kind)
    if base is None or not name or "/" in name or "\\" in name or Path(name).suffix.lower() not in VIDEO_EXT:
        raise ValueError("pick a video to convert")
    p = base / name
    if not p.is_file():
        raise ValueError("that video is no longer there - pick another")
    return p


def handle(h, method, parts, *, submit, Job, root):
    """h is the request handler (server.Handler); submit/Job/root come from server.py."""
    out = root / "output"
    gifs = out / "gifs"
    ups = gifs / "uploads"
    arg = parts[0] if parts else ""

    if method == "GET" and not arg:
        gifs.mkdir(parents=True, exist_ok=True)
        sources = []
        for p in sorted(out.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            e = _entry(p, f"/media/{p.name}")
            e.update({"id": f"out:{p.name}", "label": p.stem.replace("_", " ")})
            sources.append(e)
        if ups.is_dir():
            for p in sorted(ups.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if p.is_file() and p.suffix.lower() in VIDEO_EXT:
                    e = _entry(p)
                    e.update({"id": f"up:{p.name}", "label": "⬆ " + p.stem})
                    sources.append(e)
        made = []
        if gifs.is_dir():
            for p in sorted(gifs.glob("*.gif"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]:
                made.append(_entry(p, f"/api/gif/file/{p.name}"))
        return h.send_json({"sources": sources, "gifs": made})

    if method == "GET" and arg == "file" and len(parts) > 1:
        name = parts[1]
        if not re.fullmatch(r"[\w .()-]+\.gif", name):
            return h.fail("not found", 404)
        return h.send_file(gifs / name)

    if method == "POST" and arg == "upload":
        fname = Path(unquote(h.headers.get("X-Filename") or "clip.mp4")).name
        ext = Path(fname).suffix.lower()
        if ext not in VIDEO_EXT:
            raise ValueError("upload an mp4, mov, m4v or webm video")
        dest = ups / f"{_slug(Path(fname).stem)}-{_stamp()}{ext}"
        h.body_to_file(dest)
        return h.send_json({"ok": True, "id": f"up:{dest.name}"})

    if method == "POST" and arg == "convert":
        b = h.body_json()
        src = _source_path(root, b.get("source"))
        width = int(b.get("width") or 0)
        if width and not 120 <= width <= 3840:
            raise ValueError("width must be between 120 and 3840 px (or original)")
        fps = float(b.get("fps") or 0)
        if fps and not 1 <= fps <= 50:
            raise ValueError("frame rate must be 1-50 fps (50 is the GIF maximum)")
        colors = int(b.get("colors") or 256)
        if not 2 <= colors <= 256:
            raise ValueError("colours must be 2-256")
        dither = b.get("dither") or "sierra2_4a"
        if dither not in DITHERS:
            raise ValueError("unknown dither")

        gifs.mkdir(parents=True, exist_ok=True)
        dest = gifs / f"{_slug(src.stem)}-{_stamp()}.gif"
        cmd = [sys.executable, "-u", str(root / "pipeline" / "gif.py"), str(src), "--out", str(dest),
               "--width", str(width), "--fps", f"{fps:g}", "--colors", str(colors), "--dither", dither]
        result = {"gif": f"/api/gif/file/{dest.name}", "name": dest.name}
        return h.send_json(submit(Job("gif", f"GIF: {src.stem}", cmd, result=result)).to_dict())

    return h.fail("not found", 404)
