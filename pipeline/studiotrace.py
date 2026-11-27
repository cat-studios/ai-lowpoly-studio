"""Everything that happens, for the web app's 🔎 Logs page (the user, 2026-11-27: "see what prompts and EVERYTHING
that is happening when rendering a video or prop, so I can suggest fixes").

event(kind, title, **data) appends one JSON line:
- inside a job (the server starts every job with env STUDIO_JOB_ID): logs/trace/jobs/<job id>.jsonl
- in the server itself (the Create page's AI calls...): logs/trace/app-YYYY-MM-DD.jsonl, tagged with the request
  that made it (`source("POST /api/ai/script")` around each request)
Kinds: ai (every prompt and answer, llm._chat), image (ComfyUI workflows: the prompt words, models, size),
voice (each spoken line), blender, ffmpeg, step (progress stages), plan (the shots / cast as directed), decision,
warn, error, job. Pictures sent to a vision model are saved once under logs/trace/img/ (by hash) and named in the
event, so the page can show what the AI was looking at. Nothing secret goes in: no keys, no headers.
Never raises: a trace that can't be written never stops a render.
"""
import base64
import contextlib
import contextvars
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "logs" / "trace"
IMG = DIR / "img"
MAX_TEXT = 60000             # characters per text field (a whole script, a long prompt; not a 2 MB answer)
KEEP_DAYS = 30
_SRC = contextvars.ContextVar("trace_source", default=None)
_LOCK = threading.Lock()


def job_id():
    return os.environ.get("STUDIO_JOB_ID") or None


def path_for(job=None, day=None):
    job = job or job_id()
    if job:
        return DIR / "jobs" / f"{job}.jsonl"
    return DIR / f"app-{day or time.strftime('%Y-%m-%d')}.jsonl"


@contextlib.contextmanager
def source(name):
    """Events inside are tagged with what asked for them (a web request)."""
    tok = _SRC.set(name)
    try:
        yield
    finally:
        _SRC.reset(tok)


def _clip(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXT else v[:MAX_TEXT] + f"\n… ({len(v) - MAX_TEXT} more characters cut)"
    if isinstance(v, (dict, list, tuple)):
        try:
            s = json.dumps(v, ensure_ascii=False, default=str)
        except Exception:
            return str(v)[:MAX_TEXT]
        return v if len(s) <= MAX_TEXT else s[:MAX_TEXT] + " …(cut)"
    return v


def event(kind, title, job=None, **data):
    """Write one event; returns nothing and never raises."""
    if "unittest" in sys.modules and not os.environ.get("STUDIO_TRACE_TESTS"):
        return            # the tests' fake AI calls don't belong in the real logs
    try:
        rec = {"t": round(time.time(), 3), "kind": kind, "title": str(title)[:400]}
        src = _SRC.get()
        if src and not (job or job_id()):
            rec["src"] = src
        clean = {k: _clip(v) for k, v in data.items() if v is not None and v != ""}
        if clean:
            rec["data"] = clean
        line = json.dumps(rec, ensure_ascii=False, default=str)
        p = path_for(job)
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def save_image(b64_or_bytes):
    """A picture an AI was shown -> logs/trace/img/<hash>.<ext> (once); returns the file name or None."""
    try:
        raw = b64_or_bytes if isinstance(b64_or_bytes, bytes) else base64.b64decode(str(b64_or_bytes).split(",")[-1])
        ext = "png" if raw[:4] == b"\x89PNG" else "jpg" if raw[:2] == b"\xff\xd8" else "webp" if raw[8:12] == b"WEBP" \
            else "bin"
        name = hashlib.sha1(raw).hexdigest()[:20] + "." + ext
        p = IMG / name
        if not p.exists():
            IMG.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".part")
            tmp.write_bytes(raw)
            tmp.replace(p)
        return name
    except Exception:
        return None


def messages_for(payload):
    """An Ollama chat payload's messages, readable: pictures saved and named instead of base64."""
    out = []
    for m in (payload or {}).get("messages") or []:
        item = {"role": m.get("role", "?"), "content": m.get("content", "")}
        imgs = [save_image(i) for i in m.get("images") or []]
        if imgs:
            item["images"] = [i for i in imgs if i]
        out.append(item)
    return out


_STEP = {"last": None}


def step(stage):
    """A progress stage (progress.report): one event each time the stage text changes."""
    s = str(stage or "").strip()
    if s and s != _STEP["last"]:
        _STEP["last"] = s
        event("step", s)


def read(path, after=0, limit=2000):
    """Events from line `after` on: (events, next index). Each event gets its line number as "i"."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < after:
                    continue
                if len(out) >= limit:
                    break
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                e["i"] = i
                out.append(e)
    except OSError:
        return [], after
    return out, (out[-1]["i"] + 1 if out else after)


def prune(days=KEEP_DAYS):
    """Old trace files and pictures (older than `days`) go: they're a debugging aid, not the user's data."""
    cut = time.time() - days * 86400
    n = 0
    for p in list(DIR.glob("app-*.jsonl")) + list((DIR / "jobs").glob("*.jsonl")) + list(IMG.glob("*.*")):
        try:
            if p.stat().st_mtime < cut:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n
