"""The 🔎 Logs page's API (pipeline/studiotrace.py writes the events):
GET /api/trace                     -> recent jobs (in memory + older ones from their trace files) and app days
GET /api/trace/job/<id>?after=N    -> that job's events from line N on (+ its live state when it's still known)
GET /api/trace/app/<YYYY-MM-DD>?after=N -> what the app itself did that day (the Create page's AI calls...)
"""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import studiotrace as T

ID_RE = re.compile(r"[0-9a-f]{6,32}")
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_LIST = 120


def _first_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.loads(f.readline() or "{}")
    except (OSError, ValueError):
        return {}


def _last_line(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
        return json.loads(tail[-1]) if tail else {}
    except (OSError, ValueError):
        return {}


def job_list(jobs):
    out, seen = [], set()
    for j in sorted(jobs.values(), key=lambda j: j.created, reverse=True):
        p = T.path_for(job=j.id)
        out.append({"id": j.id, "title": j.title, "kind": j.kind, "status": j.status, "started": j.started,
                    "ended": j.ended, "progress": j.progress, "stage": j.stage, "traced": p.exists()})
        seen.add(j.id)
    files = sorted((T.DIR / "jobs").glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        if len(out) >= MAX_LIST:
            break
        if p.stem in seen:
            continue
        first, last = _first_line(p), _last_line(p)
        title = re.sub(r"^Started: ", "", first.get("title", p.stem))
        status = ((last.get("data") or {}).get("status") if last.get("kind") == "job" else None) or "old"
        out.append({"id": p.stem, "title": title, "kind": (first.get("data") or {}).get("job_kind", ""),
                    "status": status, "started": first.get("t"), "ended": last.get("t"), "traced": True})
    return out[:MAX_LIST]


def days():
    return sorted((p.stem[4:] for p in T.DIR.glob("app-*.jsonl") if DAY_RE.fullmatch(p.stem[4:])), reverse=True)[:30]


def handle(h, method, parts, jobs):
    if method != "GET":
        return h.fail("read only", 405)
    q = parse_qs(urlparse(h.path).query)
    after = int((q.get("after") or ["0"])[0] or 0)
    if not parts:
        return h.send_json({"jobs": job_list(jobs), "days": days()})
    if parts[0] == "job" and len(parts) > 1 and ID_RE.fullmatch(parts[1]):
        ev, nxt = T.read(T.path_for(job=parts[1]), after)
        j = jobs.get(parts[1])
        live = {k: v for k, v in j.to_dict(log_from=len(j.log)).items() if k not in ("log", "result")} if j else None
        return h.send_json({"events": ev, "next": nxt, "job": live})
    if parts[0] == "app" and len(parts) > 1 and DAY_RE.fullmatch(parts[1]):
        ev, nxt = T.read(T.path_for(day=parts[1]), after)
        return h.send_json({"events": ev, "next": nxt})
    return h.fail("not found", 404)
