"""
The Ideas page (mounted by web/server.py under /api/ideas; data in pipeline/ideas.py).

    GET    /api/ideas                  -> {ideas, fetched, fetching, regions} (starts a fetch when older than 12 h)
    GET    /api/ideas/fresh?n=6        -> a few new ideas for cards (Custom Video, random video, series)
    POST   /api/ideas/fetch            -> job: read what's trending now and add ideas
    POST   /api/ideas {topic, angle?, template?} -> your own idea
    PUT    /api/ideas/<id> {starred?, hidden?}
    POST   /api/ideas/<id>/titles      -> {titles}: video titles from the idea (kept with it)
Ideas are never deleted, only hidden.
"""
import sys
from urllib.parse import parse_qs, urlparse


def _running(jobs):
    return next((j for j in jobs.values() if j.kind == "ideas" and j.status in ("queued", "running")), None)


def start_fetch(submit, Job, root, jobs):
    j = _running(jobs)
    if j:
        return j
    cmd = [sys.executable, "-u", str(root / "pipeline" / "ideas.py"), "fetch"]
    return submit(Job("ideas", "Trending video ideas", cmd))


def handle(h, method, parts, *, submit, Job, root, jobs):
    import ideas
    arg = parts[0] if parts else ""
    sub = parts[1] if len(parts) > 1 else ""

    if method == "GET" and not arg:
        db = ideas.load()
        if ideas.stale() and not _running(jobs):       # old (or none yet): get today's in the background
            start_fetch(submit, Job, root, jobs)
        return h.send_json({"ideas": db["ideas"], "fetched": db.get("fetched", 0), "fetching": bool(_running(jobs)),
                            "regions": ideas.REGIONS,
                            "sources": {k: label for k, (_switch, label) in ideas.SOURCES.items()}})
    if method == "GET" and arg == "fresh":
        q = parse_qs(urlparse(h.path).query)
        n = max(1, min(30, int((q.get("n") or ["6"])[0])))
        if ideas.stale() and not _running(jobs):
            start_fetch(submit, Job, root, jobs)
        return h.send_json({"ideas": ideas.fresh(n)})
    if method == "POST" and arg == "fetch":
        return h.send_json(start_fetch(submit, Job, root, jobs).to_dict())
    if method == "POST" and not arg:
        b = h.body_json() or {}
        topic = " ".join(str(b.get("topic") or "").split())[:80]
        if not topic:
            raise ValueError("write the idea first")
        db = ideas.load()
        it = ideas.add(db, {"topic": topic, "angle": str(b.get("angle") or "")[:200],
                            "template": b.get("template") or "what_if", "source": "mine"})
        it["hidden"] = False
        ideas.save(db)
        return h.send_json(it)

    db = ideas.load()
    it = ideas.find(db, arg)
    if not it:
        return h.fail("no such idea", 404)
    if method == "PUT" and not sub:
        b = h.body_json() or {}
        for k in ("starred", "hidden"):
            if k in b:
                it[k] = bool(b[k])
        ideas.save(db)
        return h.send_json(it)
    if method == "POST" and sub == "titles":
        import llm
        import settings as S
        import templates
        cfg = S.load_settings()
        o = cfg["ollama"]
        b = h.body_json() or {}
        tpl = templates.get(b.get("template") or it.get("template"))
        char = S.load_character(b.get("character") or cfg["active_character"])
        theme = it["topic"] + (f" - {it['angle']}" if it.get("angle") else "")
        titles = llm.generate_titles(o["url"], b.get("model") or o["model"], char, theme, 6,
                                     starts=tpl["title_starts"], hint=tpl["title_hint"])
        it["titles"] = titles
        ideas.save(db)
        return h.send_json({"titles": titles, "idea": it})
    return h.fail("not found", 404)
