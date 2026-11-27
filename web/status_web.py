"""
The status panel (the dot in the top bar): GET /api/status -> {"level": ok|warn|bad, "checks": [...]}.
Every check is {name, level, detail, fix?}; they run in parallel with short timeouts, so a server that is off
answers "not reachable" in a few seconds instead of hanging the panel.
"""
import concurrent.futures as cf
import os
import shutil
import time
from pathlib import Path


def _check(name, fn):
    try:
        level, detail, fix = fn()
    except Exception as exc:
        level, detail, fix = "bad", f"{exc.__class__.__name__}: {str(exc)[:120]}", ""
    return {"name": name, "level": level, "detail": detail, **({"fix": fix} if fix else {})}


def checks(root, jobs):
    import comfy
    import llm
    import settings as S
    cfg = S.load_settings()
    o = cfg["ollama"]
    root = Path(root)

    a, orc = cfg.get("ai") or {}, cfg.get("openrouter") or {}

    def local_ollama():
        if a.get("local") is False:
            return "ok", "switched off (Settings → AI tools)", ""
        names = [m["name"] for m in llm.list_models(o["url"])]
        miss = [m for m in (o["model"], o.get("vision_model")) if m and m not in names]
        if miss:
            return "warn", f"running, {len(names)} models - missing: {', '.join(miss)}", \
                "Pick an installed model in Settings → AI tools, or pull it with ollama pull."
        return "ok", f"running - {o['model']} + picture model {o.get('vision_model') or '-'}", ""

    def cloud():
        if not a.get("cloud"):
            return "ok", "off (Settings → AI tools)", ""
        import cloud_web
        r = cloud_web.check(str(orc.get("key") or "").strip())
        if not r["ok"]:
            return "bad", r["error"], "Settings → AI tools → Cloud AI: paste your OpenRouter key and Save."
        jobs = [n for k, n in (("text", "writing"), ("vision", "picture checks"), ("design", "3D design"))
                if orc.get(k) and llm.cloud_model(k, orc)]
        if not jobs:
            return "warn", "on, but no job has a model picked", "Pick a model for writing (and pictures) in Settings → AI tools."
        left = r.get("left")
        if left is not None and left <= 0.05:
            return "warn", "out of credit - local AI does the work", "Top up on openrouter.ai, or raise the key's limit."
        used = f", ${r['used']:.2f} used" if isinstance(r.get("used"), (int, float)) else ""
        return "ok", f"connected - {', '.join(jobs)}{used}", ""

    def big_server():
        if a.get("local") is False:
            return "ok", "local AI switched off", ""
        url = "" if o.get("big_server") is False else (o.get("design_url") or "").strip()
        if not url:
            return "ok", "off or not set up (everything runs on this PC)", ""
        names = [m["name"] for m in llm.list_models(url)]
        want = (o.get("design_model") or "").strip()
        if want and want not in names:
            return "warn", f"reachable, but it has no model {want}", "Pick one of its models in Settings → AI tools."
        scope = "all the AI's writing" if o.get("design_scope") == "text" else "3D design"
        return "ok", f"reachable - {want or 'default model'} for {scope}", ""

    def comfyui():
        mode = cfg["comfy"].get("mode", "auto")
        if mode == "off":
            return "ok", "switched off in Settings", ""
        st = comfy.status(cfg["comfy"].get("url", ""), max_age=0)
        if not st.get("ok"):
            return ("bad" if mode == "required" else "warn"), st.get("error", "not reachable"), \
                "Start ComfyUI Desktop (textures, drawn props and music need it)."
        return "ok", f"running - {', '.join(st.get('checkpoints') or []) or 'no image model'}", ""

    def blender():
        import run_episode as R
        exe = os.environ.get("BLENDER", R.BLENDER_DEFAULT)
        return ("ok", exe, "") if Path(exe).exists() else ("bad", f"not found at {exe}", "Install Blender 5.3.")

    def ffmpeg():
        exe = shutil.which("ffmpeg")
        return ("ok", exe, "") if exe else ("bad", "not found", "Install ffmpeg (a full build with libass).")

    def voice():
        py = root / "tools" / "voice-venv" / "Scripts" / "python.exe"
        if py.exists():
            return "ok", "your cloned voice and drawn props are available", ""
        return "warn", "tools/voice-venv is missing - videos use the free Edge voices, no drawn props", \
            "See README → Installing on a new PC."

    def disk():
        free = shutil.disk_usage(root).free / 1e9
        level = "bad" if free < 5 else "warn" if free < 20 else "ok"
        return level, f"{free:.0f} GB free", ("Settings → Free up disk space." if level != "ok" else "")

    def queue():
        run = [j for j in jobs.values() if j.status == "running"]
        wait = [j for j in jobs.values() if j.status == "queued"]
        failed = [j for j in jobs.values() if j.status == "failed" and time.time() - (j.ended or 0) < 86400]
        detail = (f"{len(run)} running, {len(wait)} waiting" if run or wait else "idle") + \
            (f" - {len(failed)} failed today" if failed else "")
        return ("warn" if failed else "ok"), detail, ("Open the job list (top right) to see why." if failed else "")

    def ideas_db():
        import ideas
        db = ideas.load()
        if not db.get("fetched"):
            return "warn", "no trending ideas fetched yet", "Open the Ideas page."
        hours = (time.time() - db["fetched"]) / 3600
        return "ok", f"{len(db['ideas'])} ideas, updated {hours:.0f} h ago", ""

    def page_errors():
        log = root / "logs" / f"server-{time.strftime('%Y-%m-%d')}.log"
        n = log.read_text(encoding="utf-8", errors="replace").count("PAGE ERROR") if log.exists() else 0
        return ("warn" if n else "ok"), (f"{n} page error(s) today (in logs/server-*.log)" if n else "none today"), \
            ("Tell Claude - they're in the server log." if n else "")

    items = [("Ollama (this PC)", local_ollama), ("Big model server", big_server), ("Cloud AI (OpenRouter)", cloud), ("ComfyUI", comfyui),
             ("Blender", blender), ("ffmpeg", ffmpeg), ("Cloned voice tools", voice), ("Disk space", disk),
             ("Job queue", queue), ("Ideas", ideas_db), ("Page errors", page_errors)]
    with cf.ThreadPoolExecutor(len(items)) as ex:
        out = list(ex.map(lambda it: _check(*it), items))
    order = {"ok": 0, "warn": 1, "bad": 2}
    return {"level": max((c["level"] for c in out), key=order.get), "checks": out, "time": time.time()}


def handle(h, method, parts, *, root, jobs):
    if method == "GET":
        return h.send_json(checks(root, jobs))
    return h.fail("not found", 404)
