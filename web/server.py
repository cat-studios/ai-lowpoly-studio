"""
Local web app for making episodes.

    python web/server.py            -> http://127.0.0.1:8765

Standard library only. Long tasks (renders, model imports, voice tests) run one at a time in a
background job queue; the page polls their logs.
"""
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("model/gltf-binary", ".glb")
PIPE = ROOT / "pipeline"
sys.path.insert(0, str(PIPE))
import autodirect  # noqa: E402
import catalog  # noqa: E402
import comfy  # noqa: E402
import fonts  # noqa: E402
import logs  # noqa: E402
import llm  # noqa: E402
import settings as S  # noqa: E402
import templates  # noqa: E402
import setgen  # noqa: E402
import sfx as sfxlib  # noqa: E402

SETS_DIR = ROOT / "sets"
MUSIC = ROOT / "assets" / "music"

EPISODES = ROOT / "episodes"
OUTPUT = ROOT / "output"
VOICES = ROOT / "assets" / "voices"
BLENDER = os.environ.get("BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
MAX_UPLOAD = 300 * 1024 * 1024
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,60}")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:60] or "episode"


def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------- jobs
class Job:
    def __init__(self, kind, title, cmd, on_done=None, result=None):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title, self.cmd = kind, title, cmd
        self.status, self.log = "queued", []
        self.created, self.started, self.ended = time.time(), None, None
        self.on_done, self.result = on_done, result or {}
        self.progress, self.stage = None, ""          # from "PROGRESS <0-1> <stage>" lines (pipeline/progress.py)
        self.ip = logs.who()                          # who asked for it (the client IP of that request)
        logs.job_created(self)

    def to_dict(self, log_from=0):
        return {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status,
                "created": self.created, "started": self.started, "ended": self.ended,
                "progress": self.progress, "stage": self.stage,
                "last": self.log[-1] if self.log else "",
                "result": self.result, "log": self.log[log_from:], "log_len": len(self.log)}


JOBS, JOB_ORDER = {}, []
# Three lanes, each one job at a time. Videos queue behind each other; a scene build starts at once even while a
# video renders; everything else (music, sounds, props, previews, Postiz...) has its own lane.
LANES = {"render": queue.Queue(), "scene": queue.Queue(), "other": queue.Queue()}


def lane_of(job):
    return "render" if job.kind in ("render", "preview") else "scene" if job.kind == "set" else "other"


def submit(job):
    JOBS[job.id] = job
    JOB_ORDER.append(job.id)
    # keep the 50 newest jobs; older finished ones (and their logs) are dropped so memory doesn't grow forever
    for old in JOB_ORDER[:-50]:
        j = JOBS.get(old)
        if j is None or j.status in ("done", "failed"):
            JOBS.pop(old, None)
            JOB_ORDER.remove(old)
    LANES[lane_of(job)].put(job)
    return job


def worker(lane):
    while True:
        run_job(LANES[lane].get())


def run_job(job):
    job.status, job.started = "running", time.time()
    logs.job_started(job)
    try:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(job.cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("PROGRESS "):           # progress bar update, not shown in the log
                parts = line.split(" ", 2)
                try:
                    job.progress = max(0.0, min(1.0, float(parts[1])))
                    job.stage = parts[2] if len(parts) > 2 else job.stage
                except ValueError:
                    pass
                continue
            if line:
                job.log.append(line)
                del job.log[:-3000]
                logs.job_line(job, line)           # the whole output also goes to logs/jobs/<id>.log
        ok = proc.wait() == 0
        if ok:
            job.progress = 1.0
        if ok and job.on_done:
            job.on_done(job)
        job.status = "done" if ok else "failed"
    except Exception as exc:  # keep the worker alive
        job.log.append(f"ERROR: {exc}")
        job.log.extend(traceback.format_exc().splitlines())
        job.status = "failed"
    job.ended = time.time()
    logs.job_finished(job)


for _lane in LANES:
    threading.Thread(target=worker, args=(_lane,), daemon=True).start()


# --------------------------------------------------------------------------- helpers
def episode_path(eid):
    if not ID_RE.fullmatch(eid or ""):
        raise ValueError("bad episode id")
    return EPISODES / f"{eid}.json"


FONT_CACHE = {}


def run_weekly_plan(plan=None, label="WEEKLY PLAN", mark=True):
    """Start a batch of fresh ideas now (the weekly plan's settings unless `plan` says otherwise; + Postiz drafts when
    Postiz is set up and the plan wants them). mark=False: this batch doesn't count as this week's plan (idle
    auto-make). None if there are no unused ideas."""
    import ideas as IDB
    import weekly
    cfg = S.load_settings()
    spec = weekly.spec_for(plan if plan is not None else (cfg.get("plan") or {}), IDB.load(),
                           f"http://127.0.0.1:{SERVER_INFO.get('port', 8765)}",
                           bool((cfg.get("postiz") or {}).get("url")))
    if not spec["ideas"]:
        logs.event(f"{label}: no unused ideas - nothing made")
        if mark:
            weekly.mark_ran()
        return None
    f = ROOT / "build" / "series" / f"{stamp()}-weekly.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(spec), encoding="utf-8")
    job = submit(Job("batch", f"Weekly plan: {len(spec['ideas'])} videos" + (" + Postiz drafts" if spec["drafts"] else ""),
                     [sys.executable, "-u", str(PIPE / "batch.py"), str(f)]))
    if mark:
        weekly.mark_ran(job=job.id)
    logs.event(f"{label} started: {len(spec['ideas'])} ideas (job {job.id})")
    return job


def run_idle_batch(cfg):
    """An idle batch: `count` videos, each a random video (the 🎲 cards, randomvid.py) with `random_chance` %, else one
    of the fresh ideas (weekly.pick). Old trending ideas are refreshed first and waited for, as the weekly plan does.
    Never reaches Postiz, and doesn't count as the week's plan."""
    import random
    import ideas as IDB
    import randomvid
    import templates
    import weekly
    db = IDB.load()
    if time.time() - float(db.get("fetched") or 0) > 12 * 3600:
        fetch = submit(Job("ideas", "Trending ideas (idle auto-make)",
                           [sys.executable, "-u", str(PIPE / "ideas.py"), "fetch"]))
        while fetch.status in ("queued", "running"):
            time.sleep(15)
        db = IDB.load()
    count = max(1, min(3, int(cfg.get("count", 1))))
    chance = max(0, min(100, int(cfg.get("random_chance", 50))))
    plan = {"count": count, "length": (S.load_settings().get("plan") or {}).get("length", "medium"), "drafts": False}
    spec = weekly.spec_for(plan, db, f"http://127.0.0.1:{SERVER_INFO.get('port', 8765)}", False)
    ideas, kinds = list(spec["ideas"]), list(templates.TEMPLATES)
    items = []
    for _ in range(count):
        if ideas and random.random() * 100 >= chance:
            items.append(ideas.pop(0))
        else:
            items.append(randomvid.item(template_ids=kinds))
    spec["ideas"] = items
    f = ROOT / "build" / "series" / f"{stamp()}-idle.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(spec), encoding="utf-8")
    n_random = sum(1 for i in items if i.get("random"))
    job = submit(Job("batch", f"Idle auto-make: {len(items)} video(s)", [sys.executable, "-u", str(PIPE / "batch.py"), str(f)]))
    logs.event(f"IDLE AUTO-MAKE started: {len(items)} video(s), {n_random} random (job {job.id})")
    return job


ACTIVITY = {"at": time.time()}                  # last time someone used the studio (see route())
IDLE_IGNORE = ("/api/jobs", "/api/status", "/api/comfy/status", "/static/", "/media/", "/propimg/", "/favicon",
               "/apple-touch-icon", "/manifest", "/sfx/", "/music/", "/fxprev/", "/setimg/", "/animimg/", "/actorimg/")


def idle_loop():
    """Every minute: after `idle.minutes` with nobody using the studio and nothing queued, running or just finished,
    make a batch (`idle.count` videos, Settings -> Idle auto-make), `idle.per_day` batches a day at most. Requests
    the studio makes itself (batch.py, series.py: X-Studio-Job) don't count as use. Doesn't count as the week's plan."""
    import weekly
    while True:
        time.sleep(60)
        try:
            cfg = S.load_settings().get("idle") or {}
            if not cfg.get("on"):
                continue
            jobs = list(JOBS.values())                  # a copy: requests add jobs meanwhile
            if any(j.status in ("queued", "running") for j in jobs):
                continue
            # quiet = since the last time someone used it AND since the last job finished (so after a batch and its
            # renders, the next one waits another quiet spell); up to `per_day` batches a day
            last_end = max([j.ended or 0 for j in jobs] + [0])
            if time.time() - max(ACTIVITY["at"], last_end) < float(cfg.get("minutes", 10)) * 60:
                continue
            st = weekly.state()
            today = time.strftime("%Y-%m-%d")
            made = int(st.get("idle_count") or 0) if st.get("idle_day") == today else 0
            if made >= int(cfg.get("per_day", 3)):
                continue
            st.update(idle_day=today, idle_count=made + 1)
            weekly.save_state(st)
            run_idle_batch(cfg)
        except Exception as exc:
            logs.event(f"IDLE AUTO-MAKE error: {exc.__class__.__name__}: {str(exc)[:200]}")


def plan_loop():
    """Every 5 minutes: is it time for the weekly plan? (the ideas are refreshed first when they're old)"""
    import ideas as IDB
    import weekly
    while True:
        time.sleep(300)
        try:
            if not weekly.due(S.load_settings().get("plan") or {}, weekly.state()):
                continue
            db = IDB.load()
            if time.time() - float(db.get("fetched") or 0) > 12 * 3600:      # old ideas: get today's first
                fetch = submit(Job("ideas", "Trending ideas (weekly plan)",
                                   [sys.executable, "-u", str(PIPE / "ideas.py"), "fetch"]))
                while fetch.status in ("queued", "running"):
                    time.sleep(15)
            run_weekly_plan()
        except Exception as exc:
            logs.event(f"WEEKLY PLAN error: {exc.__class__.__name__}: {str(exc)[:200]}")


def queue_render(p, fresh_voice=False, reuse_frames=False):
    """The render job for an episode file (the render route, remixes)."""
    remember_look(p)                            # the first render keeps the look this video is made with
    cmd = [sys.executable, "-u", str(PIPE / "run_episode.py"), str(p)]
    if fresh_voice:
        cmd.append("--fresh-voice")
    if reuse_frames:
        cmd.append("--no-render")
    name = slug(p.stem)
    if not reuse_frames:                        # keep the video this render replaces (output/previous/)
        when = stamp()                          # one stamp for both, so the sheet matches its video
        for old in (OUTPUT / f"{name}.mp4", OUTPUT / f"{name}_shots.png", OUTPUT / f"{name}_cover.jpg"):
            if old.exists():
                (OUTPUT / "previous").mkdir(exist_ok=True)
                shutil.copy2(old, OUTPUT / "previous" / f"{old.stem}-{when}{old.suffix}")
    job = Job("render", f"Render {p.stem}" + (" (look only)" if reuse_frames else ""), cmd,
              result={"video": f"/media/{name}.mp4", "sheet": f"/media/{name}_shots.png", "episode": p.stem})
    return submit(job)


def remember_look(path):
    """Save the look, captions and watermark a video is made with, the first time it renders.
    A video that already has them keeps them, so later changes to your global settings don't change it.
    A video set to a look preset keeps using that preset (presets don't change)."""
    try:
        ep = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return
    cfg = S.load_settings()
    changed = False
    if "look" not in ep and "look_preset" not in ep:
        ep["look"] = json.loads(json.dumps(cfg["look"]))
        changed = True
    for key in ("captions", "branding"):
        if key not in ep:
            ep[key] = json.loads(json.dumps(cfg[key]))
            changed = True
    if changed:
        path.write_text(json.dumps(ep, indent=2), encoding="utf-8")


def list_episodes():
    out = []
    for p in sorted(EPISODES.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            ep = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        vid = OUTPUT / f"{slug(p.stem)}.mp4"
        out.append({"id": p.stem, "title": ep.get("title", ""), "shots": len(ep.get("shots", [])),
                    "updated": p.stat().st_mtime, "video": f"/media/{vid.name}" if vid.exists() else None})
    return out


def list_videos():
    out = []
    by_slug = {slug(p.stem): p.stem for p in EPISODES.glob("*.json")}     # one folder scan, not one per video
    for v in sorted(OUTPUT.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        sheet = v.with_name(v.stem + "_shots.png")
        ep = by_slug.get(v.stem)
        title, series, batch = "", None, None
        variation = remix = None
        if ep:
            try:
                e = json.loads((EPISODES / f"{ep}.json").read_text(encoding="utf-8-sig"))
                title, series, batch = e.get("title", ""), e.get("series"), e.get("batch")
                variation, remix = e.get("variation_of"), e.get("remix")
            except Exception:
                pass
        cover = v.with_name(v.stem + "_cover.jpg")
        chk = v.with_name(v.stem + "_check.json")          # pipeline/review.py: what the check after the render found
        try:
            check = json.loads(chk.read_text(encoding="utf-8")) if chk.exists() else None
        except Exception:
            check = None
        out.append({"key": v.stem, "name": v.stem, "title": title, "episode": ep, "url": f"/media/{v.name}",
                    "series": series if isinstance(series, dict) else None,
                    "batch": batch if isinstance(batch, dict) else None,
                    "variation": variation if isinstance(variation, dict) else None,
                    "remix": remix if isinstance(remix, dict) else None,
                    "cover": f"/media/{cover.name}?v={int(cover.stat().st_mtime)}" if cover.exists() else None,
                    "cover_b": (f"/media/{v.stem}_cover_b.jpg?v={int(v.with_name(v.stem + '_cover_b.jpg').stat().st_mtime)}"
                                if v.with_name(v.stem + "_cover_b.jpg").exists() else None),
                    "check": check.get("issues") if isinstance(check, dict) else None,
                    "sheet": f"/media/{sheet.name}" if sheet.exists() else None,
                    "size": v.stat().st_size, "updated": v.stat().st_mtime})
    return out


def video_file(key):
    """The mp4 for a video key: "<name>" (output/) or "previous/<name>" (output/previous/)."""
    if key.startswith("previous/"):
        stem = key[len("previous/"):]
        if not re.fullmatch(r"[\w.-]+", stem):
            raise ValueError("bad video name")
        return OUTPUT / "previous" / f"{stem}.mp4"
    if not re.fullmatch(r"[\w.-]+", key):
        raise ValueError("bad video name")
    return OUTPUT / f"{key}.mp4"


def postiz_base(key):
    """The episode name behind a video key (an earlier version drops its "-<stamp>")."""
    stem = key.split("/")[-1]
    base = re.sub(r"-\d{8}-\d{6}$", "", stem) if key.startswith("previous/") else stem
    if not ID_RE.fullmatch(base):
        raise ValueError("bad video name")
    return base


LABELS_FILE = OUTPUT / "labels.json"        # names shown in the Videos list (never change the scripts or the files)


def load_labels():
    try:
        return json.loads(LABELS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def delete_video(key):
    """Moves the video (and its shot sheet) to output/.trash. The script (episode) is kept."""
    mp4 = video_file(key)
    if not mp4.exists():
        raise ValueError("no such video")
    trash = OUTPUT / ".trash"
    trash.mkdir(exist_ok=True)
    sheet = mp4.with_name(mp4.stem + "_shots.png")
    cover = mp4.with_name(mp4.stem + "_cover.jpg")
    m = re.fullmatch(r"(.+)-(\d{8}-\d{6})", mp4.stem)
    if key.startswith("previous/") and m:        # earlier versions keep their sheet as "<name>_shots-<stamp>.png"
        sheet = mp4.with_name(f"{m.group(1)}_shots-{m.group(2)}.png")
        cover = mp4.with_name(f"{m.group(1)}_cover-{m.group(2)}.jpg")
    for f in (mp4, sheet, cover, mp4.with_name(mp4.stem + "_check.json"), mp4.with_name(mp4.stem + "_cover_b.jpg")):
        if f.exists():
            f.replace(trash / f"{f.stem}-{stamp()}{f.suffix}")
    labels = load_labels()
    if labels.pop(key, None) is not None:
        LABELS_FILE.write_text(json.dumps(labels, indent=1), encoding="utf-8")


def list_previous_videos():
    """Earlier versions kept when a video was re-rendered (output/previous/), newest first."""
    out = []
    folder = OUTPUT / "previous"
    if not folder.is_dir():
        return out
    by_slug = {slug(p.stem): p.stem for p in EPISODES.glob("*.json")}
    for v in sorted(folder.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        base = re.sub(r"-\d{8}-\d{6}$", "", v.stem)          # "<name>-<stamp>" -> "<name>"
        ep = by_slug.get(base)
        title = ""
        if ep:
            try:
                title = json.loads((EPISODES / f"{ep}.json").read_text(encoding="utf-8-sig")).get("title", "")
            except Exception:
                pass
        m = re.fullmatch(r"(.+)-(\d{8}-\d{6})", v.stem)       # its sheet was kept as "<name>_shots-<stamp>.png"
        sheet = v.with_name(f"{m.group(1)}_shots-{m.group(2)}.png") if m else None
        out.append({"key": f"previous/{v.stem}", "name": v.stem, "title": title or base, "episode": ep, "previous": True,
                    "url": f"/media/previous/{v.name}",
                    "sheet": f"/media/previous/{sheet.name}" if sheet and sheet.exists() else None,
                    "size": v.stat().st_size, "updated": v.stat().st_mtime})
    return out


def character_info(cid):
    prof = S.load_character(cid)
    model = ROOT / prof["model"] if prof.get("model") else None
    info = {"profile": prof, "has_model": bool(model and model.exists()), "report": None,
            "active": S.load_settings()["active_character"] == cid}
    rep = (model.with_suffix(".report.json") if model else None)
    if rep and rep.exists():
        r = json.loads(rep.read_text(encoding="utf-8-sig"))
        bones = list(r.get("bones", {}))
        keys = [k for m in r.get("meshes", {}).values() for k in m.get("shape_keys", [])]
        info["report"] = {
            "source": r.get("source"), "height_m": r.get("height_m"), "tris": r.get("tris_after"),
            "ears": [b for b in bones if "ear" in b.lower() and not b.endswith("_end")][:6],
            "tail_bones": [b for b in bones if "tail" in b.lower()][:6],
            "face_shapes": len(keys), "has_expressions": any(k.startswith("Fcl_ALL_") for k in keys),
        }
    ref = (prof.get("voice") or {}).get("ref")
    info["voice_ref_exists"] = bool(ref and (ROOT / ref).exists())
    pic = S.CHAR_DIR / f"{cid}.preview.png"
    info["preview"] = f"/charimg/{cid}.preview.png" if pic.exists() else None
    return info


def import_model_job(cid, vrm):
    blend = S.CHAR_DIR / f"{cid}.blend"
    cmd = [BLENDER, "-b", "--factory-startup", "--python", str(PIPE / "prepare_character.py"), "--",
           str(vrm), "--out", str(blend)]

    def done(job):
        prof = S.load_character(cid)
        prof["model"] = f"assets/characters/{cid}.blend"
        S.save_character(cid, prof)
        job.result = character_info(cid)
        # every character gets a preview as soon as it has a model
        pcmd = [sys.executable, "-u", str(PIPE / "character_preview.py"), cid]
        submit(Job("preview", f"Character preview: {cid}", pcmd))
    return Job("import", f"Import {vrm.name} -> {cid}", cmd, done)


def prop_info(kind, d, used=None):
    """A made prop is a 3D model OR a 2D sprite (propgen.shown_as_sprite): "form", and the picture that shows it -
    the drawing for a sprite, the look check's render (<kind>.3d.png) for a 3D model."""
    import propgen
    img, img3 = ROOT / "assets" / "props" / f"{kind}.png", ROOT / "assets" / "props" / f"{kind}.3d.png"
    sprite = propgen.shown_as_sprite(d) and img.exists()
    return {"kind": kind, "name": d.get("name") or kind.replace("_", " "), "looks": d.get("looks", ""),
            "height": d.get("height"), "width": d.get("width"), "on": d.get("on") or "floor",
            "place": d.get("place"), "parts": len(d.get("parts", [])), "by": d.get("by", ""),
            "created": d.get("created") or 0, "explainer": bool(d.get("explainer")),
            "form": "sprite" if propgen.needs_picture(d) else "3d",
            "needs_picture": propgen.needs_picture(d),
            "sprite": f"/propimg/{kind}.png?v={int(img.stat().st_mtime)}" if sprite else None,
            "preview3d": f"/propimg/{kind}.3d.png?v={int(img3.stat().st_mtime)}" if img3.exists() else None,
            "used_in": used if used is not None else []}


def list_props():
    """AI-made props + which sets use them (newest first)."""
    import propgen
    usage = {}
    for js in SETS_DIR.glob("*.json"):
        try:
            rec = json.loads(js.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        kinds = {p.get("kind") for p in rec.get("props", [])} & set((rec.get("custom_props") or {}).keys())
        for k in kinds:
            usage.setdefault(k, []).append({"id": rec.get("id", js.stem), "name": rec.get("name", js.stem)})
    out = [prop_info(k, d, usage.get(k, [])) for k, d in propgen.library().items()]
    out.sort(key=lambda p: -p["created"])
    return out


def fx_info(name, ov):
    import blender_fx
    import catalog
    base, eff = blender_fx.FX[name], blender_fx.effective(name, ov)
    prev = ROOT / "assets" / "fx_previews"
    mp4, jpg = prev / f"{name}.mp4", prev / f"{name}.jpg"
    o = ov.get(name) or {}
    return {"name": name, "label": catalog.PARTICLES.get(name, name), "colors": eff["colors"],
            "default_colors": base["colors"], "amount": o.get("amount", 1.0), "speed": o.get("speed", 1.0),
            "size": o.get("size", 1.0), "count": eff["n"], "edited": bool(o),
            "video": f"/fxprev/{name}.mp4?v={int(mp4.stat().st_mtime)}" if mp4.exists() else None,
            "poster": f"/fxprev/{name}.jpg?v={int(jpg.stat().st_mtime)}" if jpg.exists() else None,
            "stale": bool(o) and mp4.exists() and blender_fx.OVERRIDES.exists()
                     and blender_fx.OVERRIDES.stat().st_mtime > mp4.stat().st_mtime}


IMP_PREFIX = "imp_"                     # a placed imported model is the prop kind "imp_<model id>"
HIDDEN_BUILTIN = {"liquid", "hill", "water", "fence", "rug"}


def _def_preview(kind, d):
    """The picture of a prop definition for the map editor and picker, or None."""
    if d.get("model"):
        mid = d["model"].get("id", "")
        return f"/impimg/{mid}.png" if mid and (ROOT / "assets" / "imported" / "previews" / f"{mid}.png").exists() else None
    import propgen
    img, img3 = ROOT / "assets" / "props" / f"{kind}.png", ROOT / "assets" / "props" / f"{kind}.3d.png"
    if propgen.shown_as_sprite(d) and img.exists():
        return f"/propimg/{kind}.png?v={int(img.stat().st_mtime)}"
    return f"/propimg/{kind}.3d.png?v={int(img3.stat().st_mtime)}" if img3.exists() else None


def layout_choices():
    """Everything the map editor's picker offers: built-in shapes, made props (the library), imported models."""
    import imported
    import propgen
    out = []
    for k in sorted(set(setgen.PROPS) - HIDDEN_BUILTIN):
        out.append({"key": k, "label": k.replace("_", " "), "group": "built-in", "preview": None,
                    "height": None, "radius": 0.6, "pack": ""})
    for k, d in propgen.library().items():
        out.append({"key": k, "label": str(d.get("name") or k.replace("_", " ")), "group": "made",
                    "preview": _def_preview(k, d), "height": d.get("height"),
                    "radius": round(float(d.get("radius", 0.6)), 2), "pack": ""})
    for pack in imported.packs():
        for m in pack.get("models", []):
            if m.get("status") != "ok":
                continue
            width = max(m.get("width") or 0.0, m.get("depth") or 0.0, 0.3)
            out.append({"key": IMP_PREFIX + m["id"], "label": m["name"], "group": "imported",
                        "preview": _def_preview("", {"model": {"id": m["id"]}}),
                        "height": m.get("height") if m.get("height") and 0.005 <= m["height"] <= 12 else 1.2,
                        "radius": round(width / 2, 2), "pack": pack["name"]})
    return out


def _new_prop_def(kind):
    """The definition to store in a set when the editor adds a made prop or an imported model."""
    import imported
    import propgen
    if kind.startswith(IMP_PREFIX):
        d = imported.model_def(kind[len(IMP_PREFIX):], kind=kind)
        if d is None:
            raise ValueError(f"'{kind}' is not a ready imported model")
        return d
    lib = propgen.library()
    if kind in lib:
        return json.loads(json.dumps(lib[kind]))
    raise ValueError(f"'{kind}' can't be placed")


def set_layout(sid):
    """A scene's props for the map editor: where each one stands (metres), turned (radians), scaled, and how it looks."""
    path = SETS_DIR / f"{sid}.json"
    if not path.exists():
        raise ValueError("no such set")
    rec = json.loads(path.read_text(encoding="utf-8-sig"))
    custom = rec.get("custom_props") or {}
    picker = layout_choices()                       # scanned once: the library and every pack
    choices = {c["key"]: c for c in picker}
    props = []
    for i, p in enumerate(rec.get("props", [])):
        kind = str(p.get("kind"))
        liquid = kind == "liquid"
        d = custom.get(kind) or {}
        c = choices.get(kind) or {}
        radius = float(p.get("r", 1.5)) if liquid else float(d.get("radius", c.get("radius", 0.6)))
        label = d.get("name") or c.get("label") or kind.replace("_", " ")
        preview = _def_preview(kind, d) if d else c.get("preview")
        props.append({"i": i, "kind": kind, "label": str(label), "pos": p.get("pos", [0, 0]),
                      "rot": float(p.get("rot", 0.0)), "scale": float(p.get("scale", 1.0)),
                      "radius": round(radius, 2), "liquid": liquid, "preview": preview,
                      "height": d.get("height") or c.get("height"), "group": "imported" if d.get("model") else
                      ("made" if d else "built-in")})
    return {"id": sid, "name": rec.get("name", sid), "indoor": bool(rec.get("indoor")),
            "room": rec.get("room") if rec.get("indoor") else None, "props": props, "choices": picker,
            "marks": rec.get("marks", {})}


def save_set_layout(sid, body):
    """Save the edited positions. The old recipe is copied to sets/.trash first."""
    path = SETS_DIR / f"{sid}.json"
    if not path.exists():
        raise ValueError("no such set")
    rec = json.loads(path.read_text(encoding="utf-8-sig"))
    trash = SETS_DIR / ".trash"
    trash.mkdir(exist_ok=True)
    shutil.copy2(path, trash / f"layout-{sid}-{stamp()}.json")
    old = rec.get("props", [])
    custom = rec.get("custom_props") or {}
    out = []
    for item in body.get("props") or []:
        kind = str(item.get("kind") or "")
        if kind not in setgen.PROPS and kind != "liquid" and kind not in custom:
            custom[kind] = _new_prop_def(kind)      # a made prop or an imported model picked in the editor
        x, y = (max(-30.0, min(30.0, float(v))) for v in item["pos"][:2])
        base = {}
        i = item.get("i")
        if isinstance(i, int) and 0 <= i < len(old) and old[i].get("kind") == kind:
            base = dict(old[i])                     # keep the other settings of this prop (r, glow, z...)
        base.update({"kind": kind, "pos": [round(x, 2), round(y, 2)], "rot": round(float(item.get("rot", 0.0)), 4),
                     "scale": round(max(0.2, min(3.0, float(item.get("scale", 1.0)))), 3)})
        out.append(base)
    rec["props"] = out
    if custom:
        rec["custom_props"] = custom
    path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return {"ok": True, "count": len(out)}


def list_sets():
    """All sets, no categories - newest first."""
    out = []
    for sid, s in catalog.all_sets().items():
        img = SETS_DIR / (f"_{sid}.png" if s.get("builtin") else f"{sid}.png")
        rec, js = {}, SETS_DIR / f"{sid}.json"
        if js.exists():
            try:
                rec = json.loads(js.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
        indoor = rec.get("indoor", sid == "cafe")
        light = rec.get("light") or ("night" if rec.get("night") else "day")
        out.append({"id": sid, "name": s["name"], "description": rec.get("description") or s["description"],
                    "marks": list(s["marks"]), "builtin": sid in catalog.SETS,
                    "has_3d": (SETS_DIR / f"{sid}.glb").exists(),
                    "preview": f"/setimg/{img.name}?v={int(img.stat().st_mtime)}" if img.exists() else None,
                    "props": len(rec.get("props", [])), "textures": list((rec.get("textures") or {}).keys()),
                    "where": "inside" if indoor else "outside", "light": light, "style": rec.get("style") or "classic",
                    "updated": rec.get("created") or (js.stat().st_mtime if js.exists() else 0)})
    out.sort(key=lambda s: -s["updated"])
    return out


def set_job(args, title):
    cmd = [sys.executable, "-u", str(PIPE / "make_set.py")] + args

    def done(job):
        sid = next((l.split("=", 1)[1] for l in reversed(job.log) if l.startswith("SET_ID=")), None)
        job.result = {"set": sid}
    return Job("set", title, cmd, done)


EDGE_VOICES = None


def edge_voices():
    global EDGE_VOICES
    if EDGE_VOICES is None:
        try:
            import asyncio
            import edge_tts
            vs = asyncio.run(edge_tts.list_voices())
            EDGE_VOICES = sorted(({"name": v["ShortName"], "gender": v.get("Gender", ""),
                                   "locale": v.get("Locale", "")} for v in vs), key=lambda v: v["name"])
        except Exception:
            return []
    return EDGE_VOICES


# --------------------------------------------------------------------------- PIN (optional, for LAN use)
import hashlib  # noqa: E402
import hmac  # noqa: E402

PUBLIC_PATHS = ("/login", "/manifest.webmanifest", "/favicon.ico", "/favicon.svg", "/apple-touch-icon.png",
                "/static/style.css", "/static/icons/")


def current_pin():
    return os.environ.get("LOWPOLY_PIN") or (S.load_settings().get("server") or {}).get("pin", "")


def pin_token(pin):
    return hashlib.sha256(f"lowpoly:{pin}".encode()).hexdigest()[:32]


LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#17141f">
<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="manifest" href="/manifest.webmanifest"><title>Low Poly Studio</title>
<link rel="stylesheet" href="/static/style.css"></head><body>
<main style="max-width:360px;margin:12vh auto;padding:20px"><div class="panel" style="text-align:center">
<img src="/static/icons/icon-192.png" alt="" style="width:96px;border-radius:22px">
<h2 style="margin-top:12px">Low Poly Studio</h2>
<form method="post" action="/login"><label>PIN<input type="password" name="pin" inputmode="numeric" autofocus
 style="text-align:center;font-size:22px;letter-spacing:6px"></label>
<div class="btns" style="justify-content:center"><button class="primary" type="submit">Enter</button></div>
{msg}</form></div></main></body></html>"""


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "LowPolyStudio/1.0"

    def authorised(self, path):
        pin = current_pin()
        if not pin or self.client_address[0] in ("127.0.0.1", "::1"):
            return True                       # no PIN set, or it's this PC itself
        if path.startswith(PUBLIC_PATHS):
            return True
        cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
        return hmac.compare_digest(cookies.get("lp_auth", ""), pin_token(pin))

    def login(self, method):
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            from urllib.parse import parse_qs
            given = parse_qs(self.rfile.read(n).decode("utf-8", "ignore")).get("pin", [""])[0]
            if given and hmac.compare_digest(given, current_pin()):
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"lp_auth={pin_token(given)}; Path=/; Max-Age=31536000; "
                                               "HttpOnly; SameSite=Lax")
                self.end_headers()
                return
            time.sleep(1.0)                   # slow down guessing
            msg = '<p class="err">Wrong PIN</p>'
        else:
            msg = ""
        body = LOGIN_PAGE.replace("{msg}", msg).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # replaced by log_request (web/logs.py)
        pass

    def log_request(self, code="-", size="-"):
        ms = int((time.time() - getattr(self, "_t0", time.time())) * 1000)
        logs.request(self.client_address[0], self.command, self.path.split("?")[0], code, ms,
                     self.headers.get("User-Agent", ""), getattr(self, "_logbody", ""))

    # ---- responses
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, msg, status=400):
        self.send_json({"error": msg}, status)

    # ------------------------------------------------------------------ Assets page
    def assets_api(self, method, arg, rest):
        import propgen
        import blender_fx
        sub = rest[0] if rest else ""
        if arg == "props":
            if method == "GET" and not sub:
                return self.send_json(list_props())
            if not re.fullmatch(r"[a-z0-9_]+", sub or ""):
                raise ValueError("bad prop name")
            lib = propgen.library()
            if sub not in lib:
                return self.fail("no such prop", 404)
            if method == "PUT" and len(rest) == 1:
                b, d = self.body_json(), lib[sub]
                if isinstance(b.get("looks"), str):
                    d["looks"] = b["looks"].strip()[:200]
                for k, lo, hi in (("height", 0.05, 12.0), ("width", 0.03, 15.0)):
                    if b.get(k) not in (None, ""):
                        d[k] = round(max(lo, min(hi, float(b[k]))), 2)
                if b.get("on") in ("floor", "table", "wall"):
                    d["on"] = b["on"]
                    d["size_checked"] = True
                if b.get("form") == "3d" and d.get("parts"):      # back to its 3D shapes (Assets: Use the 3D model)
                    d["complex"], d["form"] = False, "3d"
                propgen._save(d)
                return self.send_json({"ok": True, "prop": prop_info(sub, d)})
            if method == "POST" and sub == "missing":    # pictures for every prop that has none yet
                cmd = [sys.executable, "-u", str(PIPE / "propgen.py"), "missing"]
                return self.send_json(submit(Job("props", "Draw missing prop pictures", cmd)).to_dict())
            if method == "POST" and rest[1:] == ["redraw"]:
                b = self.body_json()
                cmd = [sys.executable, "-u", str(PIPE / "propgen.py"), "redraw", sub]
                if b.get("looks"):
                    cmd.append(str(b["looks"])[:200])
                return self.send_json(submit(Job("props", f"Redraw {sub}", cmd)).to_dict())
        if arg == "fx":
            ov = blender_fx.overrides()
            if method == "GET" and not sub:
                return self.send_json([fx_info(n, ov) for n in blender_fx.FX])
            if method == "POST" and sub == "preview":
                names = [n for n in (self.body_json().get("names") or []) if n in blender_fx.FX]
                cmd = [sys.executable, "-u", str(PIPE / "fx_preview.py"), *names]
                return self.send_json(submit(Job("fx", "Effect previews" + (f": {', '.join(names)}" if names else ""), cmd)).to_dict())
            if sub not in blender_fx.FX:
                return self.fail("no such effect", 404)
            if method == "PUT":
                b = self.body_json()
                cols = [c for c in (b.get("colors") or []) if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c)][:8]
                ov[sub] = {"colors": cols, **{k: round(max(0.1, min(4.0, float(b.get(k, 1.0)))), 2)
                                              for k in ("amount", "speed", "size")}}
            elif method == "DELETE":
                ov.pop(sub, None)
            else:
                return self.fail("unknown", 405)
            blender_fx.OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
            blender_fx.OVERRIDES.write_text(json.dumps(ov, indent=1), encoding="utf-8")
            return self.send_json({"ok": True, "fx": fx_info(sub, ov)})
        return self.fail("unknown assets call", 404)

    def send_file(self, path, cache=False):
        if not path.is_file():
            return self.fail("not found", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-cache")
        self.end_headers()
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def body_json(self):
        raw = getattr(self, "_raw_body", None)           # already read for the log (small JSON bodies)
        if raw is not None:
            return json.loads(raw or b"{}") if raw else {}
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def body_to_file(self, dest):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_UPLOAD:
            raise ValueError(f"upload must be 1 byte to {MAX_UPLOAD // 2**20} MB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            left = n
            while left:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                fh.write(chunk)
                left -= len(chunk)
        return dest

    # ---- routing
    def route(self, method):
        path = unquote(urlparse(self.path).path)
        self._t0, self._logbody, self._raw_body = time.time(), "", None
        logs.set_request(self.client_address[0], method, path)
        if not path.startswith(IDLE_IGNORE) and not self.headers.get("X-Studio-Job"):
            ACTIVITY["at"] = time.time()                  # someone is using the studio (polling and its own jobs don't count)
        if method != "GET" and "json" in (self.headers.get("Content-Type") or "") and path != "/login":
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= 256 * 1024:                      # small JSON changes: keep the body for the log
                self._raw_body = self.rfile.read(n)
                try:
                    self._logbody = logs.summary(json.loads(self._raw_body or b"{}"))
                except Exception:
                    self._logbody = "(not JSON)"
        try:
            if path == "/login":
                return self.login(method)
            if not self.authorised(path):
                if path.startswith("/api/"):
                    return self.fail("PIN required - open the app page to log in", 401)
                self.send_response(303)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            # app icons / manifest at the root, where browsers and iOS look for them
            roots = {"/manifest.webmanifest": "manifest.webmanifest", "/favicon.ico": "icons/favicon.ico",
                     "/favicon.svg": "icons/favicon.svg", "/apple-touch-icon.png": "icons/apple-touch-icon.png"}
            if method == "GET" and path in roots:
                return self.send_file(WEB / roots[path], cache=True)
            if method == "GET" and (path == "/" or path.startswith("/static/")):
                name = "index.html" if path == "/" else path[len("/static/"):]
                target = (WEB / name).resolve()
                if WEB.resolve() not in target.parents:
                    return self.fail("not found", 404)
                return self.send_file(target)
            if method == "GET" and path.startswith("/media/previews/"):   # quick previews (output/previews/)
                name = path[len("/media/previews/"):]
                if not re.fullmatch(r"([\w.-]+/)?[\w.-]+\.(mp4|png|json)", name) or ".." in name:
                    return self.fail("not found", 404)
                return self.send_file(OUTPUT / "previews" / name)
            if method == "GET" and path.startswith("/media/previous/"):   # earlier versions (output/previous/)
                name = path[len("/media/previous/"):]
                if not re.fullmatch(r"[\w.-]+\.(mp4|png|jpg)", name):
                    return self.fail("not found", 404)
                return self.send_file(OUTPUT / "previous" / name)
            if method == "GET" and path.startswith("/media/"):
                name = path[len("/media/"):]
                if not re.fullmatch(r"[\w.-]+\.(mp4|png|wav|jpg)", name):
                    return self.fail("not found", 404)
                return self.send_file(OUTPUT / name)
            if method == "GET" and path.startswith("/propimg/"):
                name = path[len("/propimg/"):]
                if not re.fullmatch(r"[\w-]+(\.3d)?\.png", name):     # the drawing, or a 3D prop's check render
                    return self.fail("not found", 404)
                return self.send_file(ROOT / "assets" / "props" / name)
            if method == "GET" and path.startswith("/animimg/"):         # animations' check pictures
                import anims_web
                return anims_web.picture(self, path[len("/animimg/"):], ROOT)
            if method == "GET" and path.startswith("/fxprev/"):
                name = path[len("/fxprev/"):]
                if not re.fullmatch(r"[\w-]+\.(mp4|jpg)", name):
                    return self.fail("not found", 404)
                return self.send_file(ROOT / "assets" / "fx_previews" / name)
            if method == "GET" and path.startswith("/impimg/"):          # pictures of imported models
                name = path[len("/impimg/"):]
                if not re.fullmatch(r"[\w.-]+\.png", name):
                    return self.fail("not found", 404)
                return self.send_file(ROOT / "assets" / "imported" / "previews" / name)
            if method == "GET" and path.startswith("/charimg/"):
                name = path[len("/charimg/"):]
                if not re.fullmatch(r"[a-z0-9_-]+\.preview\.png", name):
                    return self.fail("not found", 404)
                return self.send_file(S.CHAR_DIR / name)
            if method == "GET" and path.startswith("/actorimg/"):         # rigged actors' previews (VRoid uploads)
                name = path[len("/actorimg/"):]
                if not re.fullmatch(r"[a-z0-9_-]+\.preview\.png", name):
                    return self.fail("not found", 404)
                return self.send_file(ROOT / "assets" / "actors" / "rigs" / name)
            if method == "GET" and path.startswith("/setimg/"):
                name = path[len("/setimg/"):]
                if not re.fullmatch(r"[\w.-]+\.png", name):
                    return self.fail("not found", 404)
                return self.send_file(SETS_DIR / name, cache=True)      # the URL has a version: safe to cache
            if method == "GET" and path.startswith("/sfx/"):
                m = re.fullmatch(r"/sfx/(builtin|custom)/([\w.-]+\.(wav|mp3|ogg|m4a|flac))", path, re.I)
                if not m:
                    return self.fail("not found", 404)
                return self.send_file((sfxlib.BUILTIN if m.group(1) == "builtin" else sfxlib.CUSTOM) / m.group(2))
            if method == "GET" and path.startswith("/music/"):
                name = path[len("/music/"):]
                if not re.fullmatch(r"[\w .()-]+\.(mp3|wav|ogg|m4a|flac)", name, re.I):
                    return self.fail("not found", 404)
                return self.send_file(MUSIC / name)
            if path.startswith("/api/"):
                return self.api(method, path[5:].strip("/").split("/"))
            return self.fail("not found", 404)
        except ValueError as exc:
            return self.fail(str(exc))
        except Exception as exc:
            logs.error(f"{method} {path}", exc)
            return self.fail(f"server error: {exc}", 500)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    # ---- API
    def api(self, method, parts):
        head = parts[0]
        arg = parts[1] if len(parts) > 1 else None
        sub = parts[2] if len(parts) > 2 else None

        if head == "meta" and method == "GET":
            return self.send_json({"catalog": catalog.as_dict(), "characters": S.character_ids(),
                                   "settings": S.public_settings(), "defaults": S.DEFAULTS,
                                   "presets": S.LOOK_PRESETS, "tints": S.TINTS, "effects": S.CAPTION_EFFECTS,
                                   "sfx": sfxlib.all_slots(),
                                   "network": {"lan": SERVER_INFO["lan"], "port": SERVER_INFO["port"],
                                               "urls": [f"http://{ip}:{SERVER_INFO['port']}" for ip in lan_addresses()]}})

        # ---- AI helpers (Ollama) - optional, synchronous
        if head == "ollama" and arg == "models":
            # Settings -> AI tools lists the models of the address typed in the box (?url=), before it's saved;
            # /models/big = the big model server's (default: its saved address)
            from urllib.parse import parse_qs
            o = S.load_settings()["ollama"]
            url = (parse_qs(urlparse(self.path).query).get("url")
                   or [o.get("design_url") if sub == "big" else o["url"]])[0] or ""
            url = url.strip().rstrip("/")
            if not url:
                return self.send_json({"ok": False, "error": "Type the server's address first", "models": []})
            if "://" not in url:
                url = "http://" + url
            try:
                return self.send_json({"ok": True, "models": llm.list_models(url)})
            except Exception as exc:
                return self.send_json({"ok": False, "error": f"Ollama not reachable at {url} ({exc})", "models": []})
        if head == "ai" and method == "POST":
            b, cfg = self.body_json(), S.load_settings()
            o = cfg["ollama"]
            model = b.get("model") or o["model"]
            char = S.load_character(b.get("character") or cfg["active_character"])
            if arg == "script":
                sets = catalog.all_sets()
                chosen = b.get("set") or ""
                if chosen == "auto":           # pick (or plan) the set from the title first
                    chosen, place = autodirect.auto_set(b.get("title"), b.get("scene_policy", "reuse"), o)
                if str(chosen).startswith("new:"):
                    s = {"name": chosen[4:], "description": chosen[4:], "marks": autodirect.GENERIC_MARKS}
                else:
                    s = sets.get(chosen) or next(iter(sets.values()))
                others = []                    # co-stars: the script gives them lines ("Ethan: ...")
                for cid in [str(c) for c in (b.get("co_stars") or []) if S.valid_id(str(c))]:
                    prof = S.load_character(cid)
                    others.append({"name": prof.get("name") or cid, "about": prof.get("about", ""),
                                   "aliases": S.speaker_names(prof)})
                tpl = templates.get(b.get("template"))     # the kind of video: its own rules for the writer
                import actors as AC                            # regulars picked in Custom Video: the writer knows them
                regs = [str(r) for r in (b.get("regulars") or []) if re.fullmatch(r"[a-z0-9_]{1,48}", str(r))]
                extra = " ".join(x for x in (tpl["script"], AC.writer_note(regs), b.get("extra", "")) if x)
                br = S.load_settings().get("brainrot") or {}           # 🧠 brain rot mode: the words from its bank
                lines = llm.generate_script(o["url"], model, b.get("title") or "an ordinary day", char,
                                            {"name": s["name"], "description": s["description"],
                                             "marks": list(s["marks"])},
                                            lines=int(b.get("lines", 6)), tone=b.get("tone") or tpl["tone"],
                                            extra=extra, temperature=o["temperature"], others=others,
                                            scenes=str(b.get("scenes") or "auto"),
                                            explain=b.get("template") == "how_it_works",   # [show:] models only there
                                            brainrot=(llm.pick_brainrot_words(br.get("words"), br.get("words_per_video", 3))
                                                      if b.get("brainrot") else None))
                return self.send_json({"lines": lines, "script": "\n".join(lines), "model": model, "set": chosen})
            if arg == "titles":
                tpl = templates.get(b.get("template")) if b.get("template") else None
                titles = llm.generate_titles(o["url"], model, char, b.get("theme", ""), int(b.get("count", 8)),
                                             starts=tpl and tpl["title_starts"], hint=tpl["title_hint"] if tpl else "")
                return self.send_json({"titles": titles, "model": model})

        # ---- sets
        if head == "assets":         # the Assets page: AI-made props + particle effects
            return self.assets_api(method, arg, parts[2:])

        if head == "props":          # AI-made props (assets/props) that new sets reuse
            import propgen
            if method == "GET" and not arg:
                return self.send_json([{"kind": k, "looks": d.get("looks", ""), "parts": len(d.get("parts", [])),
                                        "height": d.get("height"), "place": d.get("place")}
                                       for k, d in sorted(propgen.library().items())])
            if method == "DELETE" and arg and re.fullmatch(r"[a-z0-9_]+", arg):
                f = propgen.LIB / f"{arg}.json"
                if f.exists():        # sets that already use it keep their own copy
                    (propgen.LIB / ".trash").mkdir(exist_ok=True)
                    st = stamp()
                    f.replace(propgen.LIB / ".trash" / f"{arg}-{st}.json")
                    # its 3D picture goes with it (the drawing stays: sets using it point at that file)
                    if (propgen.LIB / f"{arg}.3d.png").exists():
                        (propgen.LIB / f"{arg}.3d.png").replace(propgen.LIB / ".trash" / f"{arg}-{st}.3d.png")
                return self.send_json({"ok": True})

        if head == "sets":
            if method == "GET" and not arg:
                return self.send_json(list_sets())
            if method == "POST" and arg == "starter":        # "Generate 3 Starter Sets" (pipeline/starter_sets.py)
                cmd = [sys.executable, "-u", str(PIPE / "starter_sets.py"), "3"]
                return self.send_json(submit(Job("set", "Generate 3 starter sets", cmd)).to_dict())
            if method == "POST" and arg == "from-image":     # a scene copied from a picture (pipeline/make_set.py --image)
                fname = Path(unquote(self.headers.get("X-Filename") or "picture.png")).name
                ext = Path(fname).suffix.lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    raise ValueError("use a PNG, JPG or WEBP picture")
                refs = ROOT / "build" / "set_refs"
                dest = refs / f"{stamp()}-{slug(Path(fname).stem)}{ext}"
                self.body_to_file(dest)
                idea = unquote(self.headers.get("X-Idea") or "").strip()[:200]
                args = ["--image", str(dest)] + (["--idea", idea] if idea else [])
                return self.send_json(submit(set_job(args, f"Scene from picture: {idea or fname}")).to_dict())
            if method == "POST" and arg == "generate":
                b = self.body_json()
                args = []
                if b.get("idea"):
                    args += ["--idea", str(b["idea"])[:200]]
                if b.get("ai") in ("auto", "off"):
                    args += ["--ai", b["ai"]]
                if b.get("where") in ("inside", "outside", "air"):
                    args += ["--where", b["where"]]
                if b.get("light") in ("day", "sunset", "night"):
                    args += ["--light", b["light"]]
                if b.get("name"):
                    args += ["--name", str(b["name"])[:40]]
                if b.get("comfy") in ("required", "auto", "off"):
                    args += ["--comfy", b["comfy"]]
                if b.get("theme") and re.fullmatch(r"[a-z0-9_]{1,40}", str(b["theme"])):
                    args += ["--theme", str(b["theme"])]          # auto / random / generated / a theme id
                if b.get("style") in ("base", "palette", "judged", "classic"):
                    args += ["--style", b["style"]]               # how it's made (set styles A, B, C, classic)
                title = f"New set: {b['idea'][:30]}" if b.get("idea") else "New random set"
                return self.send_json(submit(set_job(args, title)).to_dict())
            if not re.fullmatch(r"[a-z0-9_]{1,80}", arg or ""):
                raise ValueError("bad set id")
            if method == "GET" and sub == "model.glb":      # the 3D file for the 3D view
                if not (SETS_DIR / f"{arg}.glb").exists():
                    return self.fail("no 3D view yet - make it first", 404)
                return self.send_file(SETS_DIR / f"{arg}.glb", cache=True)
            if method == "POST" and sub == "3d":            # make the 3D file (pipeline/set_export.py)
                if arg in catalog.SETS:
                    raise ValueError("the built-in sets have no 3D file yet")
                if not (SETS_DIR / f"{arg}.json").exists():
                    raise ValueError("no such set")
                cmd = [sys.executable, "-u", str(PIPE / "set_export.py"), arg]
                return self.send_json(submit(Job("set", f"3D view: {arg}", cmd)).to_dict())
            if sub == "layout" and method == "GET":         # the map editor: where each prop stands
                return self.send_json(set_layout(arg))
            if sub == "layout" and method == "PUT":
                return self.send_json(save_set_layout(arg, self.body_json()))
            if method == "POST" and sub == "regenerate":    # the regenerate popup: rebuild this set with the chosen settings
                if arg in catalog.SETS:
                    raise ValueError("the original sets are built in - they can't be regenerated")
                if not (SETS_DIR / f"{arg}.json").exists():
                    raise ValueError("no such set")
                b = self.body_json()
                args = ["--replace", arg]
                for key, flag in (("idea", "--idea"), ("name", "--name"), ("room", "--room"), ("floor", "--floor"),
                                  ("where", "--where"), ("light", "--light"), ("ai", "--ai"), ("comfy", "--comfy"),
                                  ("theme", "--theme"), ("style", "--style")):
                    val = str(b.get(key) or "").strip()
                    if val and val not in ("any", "auto-room"):
                        args += [flag, val[:200]]
                if b.get("seed") not in (None, ""):
                    args += ["--seed", str(int(b["seed"]))]
                title = f"Regenerate set: {b.get('name') or arg}"
                return self.send_json(submit(set_job(args, title)).to_dict())
            if method == "POST" and sub == "preview":
                cmd = [sys.executable, "-u", str(PIPE / "set_preview.py"), arg]
                return self.send_json(submit(Job("set", f"Preview {arg}", cmd, result={"set": arg})).to_dict())
            if method == "DELETE":
                if arg in catalog.SETS:          # hand-made sets live in code: just hide them
                    setgen.hide(arg)
                    return self.send_json({"ok": True})
                trash = SETS_DIR / ".trash"
                trash.mkdir(exist_ok=True)
                when = stamp()
                for f in (SETS_DIR / f"{arg}.json", SETS_DIR / f"{arg}.png", SETS_DIR / f"{arg}.glb", SETS_DIR / arg):
                    if f.exists():                    # recipe, preview, 3D file and its textures folder
                        f.replace(trash / f"{arg}-{when}{f.suffix}")
                return self.send_json({"ok": True})

        if head == "comfy" and arg == "status":
            return self.send_json(comfy.status(S.load_settings()["comfy"]["url"], max_age=0))   # always ask now

        if head == "themes" and method == "GET":        # the theme picker: auto, random, generated, then every theme
            return self.send_json({"options": [{"id": "auto", "name": "Auto (from the words)"},
                                               {"id": "random", "name": "Random (free, can be odd)"},
                                               {"id": "generated", "name": "✨ Generated theme (AI writes one)"}],
                                   "themes": setgen.theme_list()})
        if head == "fonts":                  # scanning the system fonts is slow: do it once per server run
            if "list" not in FONT_CACHE:
                FONT_CACHE["list"] = fonts.list_fonts()
            return self.send_json(FONT_CACHE["list"])

        if head == "music":
            if method == "GET":
                MUSIC.mkdir(parents=True, exist_ok=True)
                default = S.load_settings()["audio"].get("default_music", "")
                out = []
                for p in sorted(MUSIC.iterdir(), key=lambda p: p.name.lower()):
                    if p.is_file() and p.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac"):
                        rel = f"assets/music/{p.name}"
                        out.append({"name": p.name, "path": rel, "url": f"/music/{p.name}", "size": p.stat().st_size,
                                    "default": rel == default})
                return self.send_json(out)
            if method == "POST" and arg == "generate":
                b = self.body_json()
                cmd = [sys.executable, "-u", str(PIPE / "music_gen.py"),
                       "--style", str(b.get("style") or "cheerful retro chiptune, video game, cute")[:300],
                       "--seconds", str(max(10, min(240, float(b.get("seconds") or 60)))),
                       "--engine", b.get("engine") if b.get("engine") in ("auto", "ace", "synth") else "auto"]
                if b.get("name"):
                    cmd += ["--name", str(b["name"])[:40]]

                def done(job):
                    name = next((l.split("=", 1)[1] for l in reversed(job.log) if l.startswith("MUSIC=")), None)
                    job.result = {"music": f"assets/music/{name}" if name else None}
                return self.send_json(submit(Job("music", "Generate music", cmd, done)).to_dict())
            if method == "POST":
                fname = Path(unquote(self.headers.get("X-Filename") or "music.mp3")).name
                fname = re.sub(r"[^\w .()-]", "_", fname)
                if not re.fullmatch(r"[\w .()-]+\.(mp3|wav|ogg|m4a|flac)", fname, re.I):
                    raise ValueError("music must be an mp3, wav, ogg, m4a or flac file")
                if (MUSIC / fname).exists():
                    stem, ext = fname.rsplit(".", 1)
                    fname = f"{stem}-{stamp()}.{ext}"
                self.body_to_file(MUSIC / fname)
                return self.send_json({"name": fname, "path": f"assets/music/{fname}", "url": f"/music/{fname}"})
            if method == "DELETE" and arg:     # moves to assets/music/.trash
                f = MUSIC / Path(arg).name
                if f.exists():
                    (MUSIC / ".trash").mkdir(exist_ok=True)
                    f.replace(MUSIC / ".trash" / f"{stamp()}-{f.name}")
                cfg = S.load_settings()
                if cfg["audio"].get("default_music") == f"assets/music/{f.name}":
                    cfg["audio"]["default_music"] = ""
                    S.save_settings(cfg)
                return self.send_json({"ok": True})

        # ---- sound effects library
        if head == "sfx":
            if method == "GET" and not arg:
                return self.send_json(sfxlib.list_library())
            if method == "POST" and arg == "regenerate":
                cmd = [sys.executable, "-u", str(PIPE / "sfx.py")]
                return self.send_json(submit(Job("sfx", "Regenerate built-in sound effects", cmd)).to_dict())
            if method == "POST" and arg == "slots":
                b = self.body_json()
                name = re.sub(r"[^a-z0-9_]+", "_", (b.get("name") or b.get("label") or "").strip().lower()).strip("_")
                kind = "ambience" if b.get("kind") == "ambience" else "oneshot"
                if kind == "ambience" and not name.startswith("amb_"):
                    name = "amb_" + name
                sfxlib.add_custom_slot(name, b.get("label", ""), b.get("words", ""), kind)
                if b.get("generate"):       # make the sound right away from the description
                    cfg = S.load_settings()
                    sfxlib.generate_sound(name, b.get("description") or b.get("label") or name, kind == "ambience",
                                          FFMPEG, cfg["ollama"] if cfg["sets"]["use_ollama"] else None)
                return self.send_json({"slot": name, "library": sfxlib.list_library()})
            if arg not in sfxlib.all_slots():
                raise ValueError("unknown sound effect slot")
            if method == "POST" and sub == "generate":
                b, cfg = self.body_json(), S.load_settings()
                s = sfxlib.all_slots()[arg]
                desc = (b.get("description") or "").strip() or f"{s['label']} ({s['words']})"
                sfxlib.generate_sound(arg, desc, s["kind"] == "ambience", FFMPEG,
                                      cfg["ollama"] if cfg["sets"]["use_ollama"] else None)
                return self.send_json(sfxlib.list_library())
            if method == "POST" and not sub:    # upload your own sound for this slot
                ext = Path(unquote(self.headers.get("X-Filename") or "x.wav")).suffix.lower()
                if ext not in sfxlib.AUDIO_EXT:
                    raise ValueError("sound must be wav, mp3, ogg, m4a or flac")
                old = sfxlib.custom_file(arg)
                if old:
                    (sfxlib.CUSTOM / ".trash").mkdir(parents=True, exist_ok=True)
                    old.replace(sfxlib.CUSTOM / ".trash" / f"{stamp()}-{old.name}")
                (sfxlib.CUSTOM / f"{arg}.json").unlink(missing_ok=True)   # it's an upload now, not generated
                self.body_to_file(sfxlib.CUSTOM / f"{arg}{ext}")
                return self.send_json(sfxlib.list_library())
            if method == "DELETE" and not sub:     # remove one of YOUR slots entirely (files go to .trash)
                if arg in sfxlib.SLOTS:
                    raise ValueError("built-in sounds can't be removed - upload or generate a replacement instead")
                data = sfxlib.custom_slots()
                data.pop(arg, None)
                sfxlib.CUSTOM_SLOTS.write_text(json.dumps(data, indent=1), encoding="utf-8")
                (sfxlib.CUSTOM / ".trash").mkdir(parents=True, exist_ok=True)
                for f in sfxlib.CUSTOM.glob(f"{arg}.*"):
                    f.replace(sfxlib.CUSTOM / ".trash" / f"{stamp()}-{f.name}")
                return self.send_json(sfxlib.list_library())
            if method == "DELETE" and sub == "custom":   # back to the built-in sound (upload kept in .trash)
                old = sfxlib.custom_file(arg)
                (sfxlib.CUSTOM / f"{arg}.json").unlink(missing_ok=True)
                if old:
                    (sfxlib.CUSTOM / ".trash").mkdir(parents=True, exist_ok=True)
                    old.replace(sfxlib.CUSTOM / ".trash" / f"{stamp()}-{old.name}")
                return self.send_json(sfxlib.list_library())

        if head == "series" and method == "POST":      # one idea -> 1-4 episodes, each queued to render
            b = self.body_json()
            idea = str(b.get("idea") or "").strip()[:200]
            if not idea:
                raise ValueError("give the series an idea")
            spec = {"idea": idea, "count": max(1, min(4, int(b.get("count") or 3))),
                    "template": b.get("template") if b.get("template") in templates.TEMPLATES else templates.DEFAULT,
                    "character": str(b.get("character") or ""), "length": str(b.get("length") or "medium"),
                    "tone": str(b.get("tone") or ""), "note": str(b.get("note") or "")[:300],
                    "model": str(b.get("model") or ""), "idea_id": str(b.get("idea_id") or "")[:80],
                    "base": f"http://127.0.0.1:{SERVER_INFO.get('port', 8765)}",
                    "brainrot": bool(b.get("brainrot"))}                  # 🧠 the Create page's checkmark
            f = ROOT / "build" / "series" / f"{stamp()}-{slug(idea)[:30]}.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(spec), encoding="utf-8")
            cmd = [sys.executable, "-u", str(PIPE / "series.py"), str(f)]
            return self.send_json(submit(Job("series", f"Series: {idea[:40]} ({spec['count']} episodes)",
                                             cmd)).to_dict())

        if head == "batch" and method == "POST":       # Ideas page: several ideas -> one video each, queued to render
            import ideas as IDB
            b = self.body_json()
            want = [str(x) for x in (b.get("ideas") or [])][:10]
            have = {it["id"]: it for it in IDB.load().get("ideas", [])}
            picked = [have[x] for x in want if x in have]
            if not picked:
                raise ValueError("pick at least one idea")
            spec = {"ideas": [{k: it.get(k) for k in ("id", "topic", "angle", "template", "titles")} for it in picked],
                    "length": str(b.get("length") or "medium"), "character": str(b.get("character") or ""),
                    "note": str(b.get("note") or "")[:300], "model": str(b.get("model") or ""),
                    "regulars": [str(r) for r in (b.get("regulars") or []) if re.fullmatch(r"[a-z0-9_]{1,48}", str(r))],
                    "render": True, "base": f"http://127.0.0.1:{SERVER_INFO.get('port', 8765)}",
                    "brainrot": bool(b.get("brainrot"))}                  # 🧠 the Create page's checkmark
            f = ROOT / "build" / "series" / f"{stamp()}-batch.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(spec), encoding="utf-8")
            cmd = [sys.executable, "-u", str(PIPE / "batch.py"), str(f)]
            return self.send_json(submit(Job("batch", f"{len(picked)} videos from ideas", cmd)).to_dict())

        if head == "scenes" and arg == "plan" and method == "POST":    # the Create popup's Scenes step
            b = self.body_json()
            policy = "new" if b.get("scene_policy") == "new" else "reuse"
            return self.send_json({"scenes": autodirect.plan_scenes(b.get("script", ""), b.get("set") or "auto",
                                                                    b.get("title", ""), policy)})

        if head == "autodirect" and method == "POST":
            b = self.body_json()
            policy = "new" if b.get("scene_policy") == "new" else "reuse"
            if b.get("set") == "auto":                 # pick where it starts from the title
                b["set"], _place = autodirect.auto_set(b.get("title"), policy)
            co = [str(c) for c in (b.get("co_stars") or []) if str(c)]
            speakers = {}
            for cid in co:                              # the names a line can start with: "Ethan: ..."
                try:
                    for nm in S.speaker_names(S.load_character(cid)) + [cid]:
                        speakers.setdefault(nm.lower(), cid)
                except Exception:
                    pass
            pace = templates.pacing(b.get("template"), beats_on=bool(int(b.get("beat_words", 4) or 0)))
            if b.get("brainrot") and pace.get("beat_words"):    # 🧠 brain rot mode: its own (faster) cutting
                br = S.load_settings().get("brainrot") or {}
                pace["beat_words"] = max(1, int(br.get("beat_words", 2)))
                pace["move_every"] = min(pace.get("move_every") or 2, 2)
            res = autodirect.direct(b.get("script", ""), b.get("set", "cafe"), b.get("start"), b.get("cast"), policy,
                                    speakers=speakers, title=b.get("title") or "",
                                    beat_sets=[x for x in (b.get("beat_sets") or [])
                                               if x in catalog.all_sets() or str(x).startswith("new:")] or None,
                                    **pace)
            res["set"] = b.get("set", "cafe")
            res["co_stars"] = co
            if b.get("scene_ai") and res["shots"]:      # let Ollama spot scene changes + weather/effects
                try:
                    o = S.load_settings()["ollama"]
                    sets = catalog.all_sets()
                    start = sets.get(b.get("set", "cafe"), {"name": str(b.get("set", ""))[4:], "description": ""})
                    plan = llm.find_scenes(o["url"], o["model"], [s.get("line", "") for s in res["shots"]],
                                           f"{start.get('name', '')} - {start.get('description', '')}", sets, policy)
                    autodirect.add_scene_plan(res, plan, b.get("set", "cafe"), policy)
                except Exception as exc:
                    res["scene_note"] = f"AI scene check skipped ({exc.__class__.__name__})"
            if b.get("cast_ai") and res["shots"]:       # let Ollama spot people/things the script brings in
                cfg = S.load_settings()
                try:
                    o = cfg["ollama"]
                    place = (catalog.all_sets().get(b.get("set", "cafe")) or {}).get("description", "")
                    cid = b.get("character") or cfg["active_character"]
                    prof = S.load_character(cid)
                    char = prof.get("name", "")
                    plan = llm.find_cast(o["url"], o["model"], [s.get("line", "") for s in res["shots"]],
                                         char or "the main character", place)
                    skip = [cid, *S.speaker_names(prof)]          # never cast the main characters themselves
                    for c in co:
                        try:
                            skip += [c, *S.speaker_names(S.load_character(c))]
                        except Exception:
                            skip.append(c)
                    autodirect.add_cast_plan(res, plan, skip)
                except Exception as exc:
                    res["cast_note"] = f"AI cast check skipped ({exc.__class__.__name__})"
            return self.send_json(res)

        # episodes
        if head == "episodes":
            if method == "GET" and not arg:
                return self.send_json(list_episodes())
            p = episode_path(arg)
            if method == "POST" and sub == "apply":      # the video editor's save (web/episode_edit.py)
                import episode_edit
                return self.send_json(episode_edit.apply(p, self.body_json()))
            if method == "GET":
                if not p.exists():
                    return self.fail("no such episode", 404)
                return self.send_json(json.loads(p.read_text(encoding="utf-8-sig")))
            if method == "PUT":
                ep = self.body_json()
                if not isinstance(ep.get("shots"), list):
                    raise ValueError("episode needs a shots list")
                EPISODES.mkdir(exist_ok=True)
                p.write_text(json.dumps(ep, indent=2), encoding="utf-8")
                if ep.get("idea"):            # made from an idea (Ideas page): it's used now
                    import ideas
                    ideas.mark_used(str(ep["idea"]), arg)
                return self.send_json({"ok": True, "id": arg})
            if method == "DELETE":   # never destroys: moves to episodes/.trash
                if p.exists():
                    trash = EPISODES / ".trash"
                    trash.mkdir(exist_ok=True)
                    p.replace(trash / f"{arg}-{stamp()}.json")
                return self.send_json({"ok": True})

        if head == "render" and method == "POST":
            b = self.body_json()
            p = episode_path(b.get("id"))
            if not p.exists():
                return self.fail("save the episode first", 404)
            return self.send_json(queue_render(p, b.get("fresh_voice"), b.get("reuse_frames")).to_dict())

        if head == "variation" and method == "POST":   # Videos: 🔁 part 2, or the same idea as another kind of video
            b = self.body_json()
            p = episode_path(b.get("episode"))
            if not p.exists():
                raise ValueError("no such video")
            ep = json.loads(p.read_text(encoding="utf-8-sig"))
            title = ep.get("title") or p.stem.replace("_", " ")
            said = " / ".join(s.get("line", "") for s in ep.get("shots") or [] if s.get("line"))[:500]
            part2 = b.get("mode") != "kind"
            tpl = ep.get("template") if part2 else str(b.get("template") or "")
            if tpl not in templates.TEMPLATES:
                tpl = templates.DEFAULT
            idea = {"id": None, "topic": title, "template": tpl, "titles": [],
                    "angle": ("a follow-up with NEW facts or a new twist on the same topic" if part2
                              else f"the same topic told as a {templates.get(tpl)['name']} video")}
            note = (f"This is PART 2 of the video \"{title}\". Part 1 said: {said}. Don't repeat it - new facts, a "
                    "new angle, and a quick nod to part 1 in the first line." if part2 else
                    f"This retells the idea of the video \"{title}\" (it said: {said}) in a new form.")
            spec = {"ideas": [idea], "length": str(b.get("length") or "medium"), "note": note, "model": "",
                    "character": ep.get("character") if isinstance(ep.get("character"), str) else "",
                    "variation_of": {"id": p.stem, "title": title, "mode": "part2" if part2 else "kind"},
                    "render": True, "base": f"http://127.0.0.1:{SERVER_INFO.get('port', 8765)}"}
            f = ROOT / "build" / "series" / f"{stamp()}-variation.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(spec), encoding="utf-8")
            label = "Part 2 of" if part2 else f"{templates.get(tpl)['name']} from"
            return self.send_json(submit(Job("batch", f"{label} {title[:40]}",
                                             [sys.executable, "-u", str(PIPE / "batch.py"), str(f)])).to_dict())

        if head == "remix" and arg == "pick" and method == "POST":   # ⚖️ Compare -> ⭐ keep this one
            p = episode_path((self.body_json() or {}).get("episode"))
            ep = json.loads(p.read_text(encoding="utf-8-sig"))
            group = (ep.get("remix") or {}).get("group")
            if not group:
                raise ValueError("not a remix")
            for q in EPISODES.glob("*.json"):
                try:
                    e = json.loads(q.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                if (e.get("remix") or {}).get("group") == group:
                    e["remix"]["picked"] = q == p
                    q.write_text(json.dumps(e, indent=2), encoding="utf-8")
            return self.send_json({"ok": True})

        if head == "remix" and method == "POST":       # Videos: 🎛 the same script in another set / look / language
            b = self.body_json()
            p = episode_path(b.get("episode"))
            if not p.exists():
                raise ValueError("no such video")
            src = json.loads(p.read_text(encoding="utf-8-sig"))
            variants = [v for v in (b.get("variants") or []) if isinstance(v, dict) and any(v.values())][:3]
            if not variants:
                raise ValueError("pick at least one change")
            group = (src.get("remix") or {}).get("group") or f"rmx{stamp()}"
            if not src.get("remix"):                   # the original joins the group, so Compare shows it too
                src["remix"] = {"group": group, "of": p.stem, "what": "original"}
                p.write_text(json.dumps(src, indent=2), encoding="utf-8")
            jobs = []
            for n, v in enumerate(variants, 1):
                ep = json.loads(json.dumps(src))
                what = []
                if v.get("set") and v["set"] != ep.get("set"):
                    if v["set"] not in catalog.all_sets():
                        raise ValueError(f"no such set: {v['set']}")
                    # walks and pointing use the new set's places: direct the same script again there
                    res = autodirect.direct(ep.get("script") or "\n".join(s.get("line", "") for s in ep["shots"]),
                                            v["set"], None, ep.get("cast"), title=ep.get("title") or "",
                                            **templates.pacing(ep.get("template")))
                    ep.update(set=v["set"], start=res["start"], shots=res["shots"])
                    ep["cast"] = {**(ep.get("cast") or {}), **(res.get("cast") or {})}
                    what.append(catalog.all_sets()[v["set"]].get("name", v["set"]))
                if v.get("look_preset"):
                    ep["look_preset"] = v["look_preset"]
                    ep.pop("look", None)
                    what.append(v["look_preset"])
                if v.get("language") and v["language"] in catalog.LANGUAGES:
                    ep["language"] = v["language"]
                    what.append(catalog.LANGUAGES[v["language"]].get("name", v["language"]) if isinstance(
                        catalog.LANGUAGES[v["language"]], dict) else v["language"])
                ep["remix"] = {"group": group, "of": src["remix"]["of"], "what": ", ".join(what) or "copy"}
                ep.pop("translations", None) if v.get("language") else None
                q = EPISODES / f"{p.stem[:50]}_rmx{n}_{stamp()[-6:]}.json"
                q.write_text(json.dumps(ep, indent=2), encoding="utf-8")
                jobs.append(queue_render(q).to_dict())
            return self.send_json({"jobs": jobs, "group": group})

        if head == "stats":                           # 📊 Stats: numbers per video, by kind / length / cover / set
            import stats as ST
            if method == "GET":
                res = ST.summary()
                res["videos"] = [{"key": v["key"], "title": v["title"] or v["name"].replace("_", " ")} for v in list_videos()]
                res["connected"] = bool((S.load_settings().get("instagram") or {}).get("user_id")
                                        or (S.load_settings().get("youtube") or {}).get("channel_id"))
                return self.send_json(res)
            if method == "POST" and arg == "fetch":
                cmd = [sys.executable, "-u", str(PIPE / "stats.py"), "fetch"]
                return self.send_json(submit(Job("stats", "Numbers from Instagram / YouTube", cmd)).to_dict())
            if method == "PUT" and arg:
                if not ID_RE.fullmatch(arg):
                    raise ValueError("bad video")
                return self.send_json(ST.update(arg, self.body_json() or {}))

        if head == "plan":                            # the weekly plan: its state, or ▶ run it now
            import weekly
            if method == "GET":
                st = weekly.state()
                return self.send_json({**st, "plan": S.load_settings().get("plan") or {}})
            if method == "POST" and arg == "run":
                job = run_weekly_plan()
                return self.send_json(job.to_dict() if job else {"error": "no fresh ideas to make"})

        if head == "home":                            # her room: make it, list / remove its souvenirs
            import home
            if method == "GET":
                rec = json.loads(home.path().read_text(encoding="utf-8-sig")) if home.exists() else {}
                return self.send_json({"exists": home.exists(), "on": home.on(),
                                       "souvenirs": [{k: v for k, v in s.items() if k != "def"}
                                                     for s in rec.get("souvenirs") or []]})
            if method == "POST" and arg == "make":
                cmd = [sys.executable, "-u", str(PIPE / "home.py"), "make"]
                return self.send_json(submit(Job("set", "Make her room", cmd, result={"set": home.HOME_ID})).to_dict())
            if method == "DELETE" and arg == "souvenir" and len(parts) > 2:
                home.remove(parts[2])
                return self.send_json({"ok": True})

        if head == "castcards" and method == "POST":  # Custom Video: who and what appears, before the render
            import castcards
            ep = (self.body_json() or {}).get("episode") or {}
            if not isinstance(ep.get("shots"), list):
                raise ValueError("direct the shots first")
            return self.send_json({"cards": castcards.cards(ep)})

        if head == "preview" and method == "POST":   # a quick look before the full render (storyboard / rough)
            b = self.body_json()
            p = episode_path(b.get("id"))
            if not p.exists():
                return self.fail("save the episode first", 404)
            kind = "rough" if b.get("kind") == "rough" else "storyboard"
            name = slug(p.stem)
            cmd = [sys.executable, "-u", str(PIPE / "run_episode.py"), str(p), "--preview", kind]
            result = ({"video": f"/media/previews/{name}_rough.mp4"} if kind == "rough" else
                      {"storyboard": f"/media/previews/{name}/storyboard.json", "base": f"/media/previews/{name}/"})
            job = Job("preview", ("Rough preview " if kind == "rough" else "Storyboard ") + p.stem, cmd,
                      result=dict(result, kind=kind, episode=p.stem))
            return self.send_json(submit(job).to_dict())

        if head == "server" and arg == "restart" and method == "POST":   # Settings -> Restart the app
            b = self.body_json()
            running = [j for j in JOBS.values() if j.status in ("queued", "running")]
            if running and not b.get("force"):
                return self.fail(f"{len(running)} job(s) are still running - restarting stops them. Restart anyway?", 409)
            logs.event(f"RESTART requested ({len(running)} job(s) stopped)")
            self.send_json({"ok": True, "stopped_jobs": len(running)})
            self.wfile.flush()
            threading.Thread(target=restart_app, daemon=True).start()
            return

        if head == "translate" and method == "POST":   # Create -> Check translation: every line, English + translated
            import run_episode
            b = self.body_json()
            ep, lang = b.get("episode") or {}, str(b.get("language") or "")
            if lang not in catalog.LANGUAGES or lang == "en":
                raise ValueError("pick a language other than English")
            if not isinstance(ep.get("shots"), list) or not ep["shots"]:
                raise ValueError("direct the shots first")
            cfg = S.load_settings()
            texts = [t for t, _ in run_episode.translation_units(ep, cfg)]
            try:
                mem = run_episode.translations_for(ep, cfg, lang, texts, log=lambda m: None)
            except Exception as exc:
                return self.fail(f"Translating needs Ollama ({exc.__class__.__name__}: {str(exc)[:160]})", 503)
            return self.send_json({"language": lang, "lines": [{"en": t, "out": mem[t]} for t in texts]})

        if head == "storage":        # Settings -> Free up disk space (web/storage_web.py)
            import storage_web
            busy = [j for j in JOBS.values() if j.status in ("queued", "running")]
            return storage_web.handle(self, method, parts[1:], root=ROOT, busy=busy)

        if head == "gif":            # the GIF page: video -> high-quality GIF (web/gif_web.py, pipeline/gif.py)
            import gif_web
            return gif_web.handle(self, method, parts[1:], submit=submit, Job=Job, root=ROOT)

        if head == "imported":       # imported real asset packs (web/imported_web.py, pipeline/imported.py)
            import imported_web
            return imported_web.handle(self, method, parts[1:], submit=submit, Job=Job, root=ROOT)

        if head == "status":           # the status dot / panel in the top bar (web/status_web.py)
            import status_web
            return status_web.handle(self, method, parts[1:], root=ROOT, jobs=JOBS)
        if head == "client-error" and method == "POST":   # the web page's own errors (app.js reportError)
            b = self.body_json() or {}
            msg = " ".join(str(b.get("message") or "?").split())[:300]
            stack = "\n".join(str(b.get("stack") or "").splitlines()[:6])[:1200]
            logs.event(f"PAGE ERROR on #{str(b.get('page') or '')[:30]}: {msg}"
                       + (f" (after: {str(b.get('action') or '')[:80]})" if b.get("action") else "")
                       + (f"\n{stack}" if stack else ""))
            return self.send_json({"ok": True})
        if head == "ideas":          # trending topics -> video ideas (web/ideas_web.py, pipeline/ideas.py)
            import ideas_web
            return ideas_web.handle(self, method, parts[1:], submit=submit, Job=Job, root=ROOT, jobs=JOBS)
        if head == "anims":          # animations as data (web/anims_web.py, pipeline/animlib.py + animgen.py)
            import anims_web
            return anims_web.handle(self, method, parts[1:], submit=submit, Job=Job, root=ROOT)

        if head == "actors":         # extra people for scenes (web/actors_web.py, pipeline/actors.py)
            import actors_web
            return actors_web.handle(self, method, parts[1:], submit=submit, Job=Job, root=ROOT)

        if head == "jobs":
            if not arg:
                return self.send_json([JOBS[j].to_dict(log_from=10**9) for j in reversed(JOB_ORDER)][:20])
            if method == "POST" and sub == "retry":        # run a failed job again, same command and settings
                old = JOBS.get(arg)
                if not old:
                    return self.fail("no such job", 404)
                if old.status != "failed":
                    raise ValueError("only a failed job can be retried")
                return self.send_json(submit(Job(old.kind, old.title, old.cmd, old.on_done, dict(old.result))).to_dict())
            job = JOBS.get(arg)
            if not job:
                return self.fail("no such job", 404)
            q = urlparse(self.path).query
            m = re.search(r"from=(\d+)", q)
            return self.send_json(job.to_dict(int(m.group(1)) if m else 0))

        if head == "videos" and method == "GET":
            items = list_videos() + list_previous_videos()
            labels = load_labels()
            for it in items:                          # names you gave a video win over the script's title
                if it["key"] in labels:
                    it["title"] = labels[it["key"]]
            return self.send_json(items)
        if head == "videos" and method == "POST" and len(parts) == 3 and parts[2] == "cover":
            # 🖼 Cover -> 🔄 pick again (the AI) or a shot picked by hand: pipeline/cover.py on the render's frames
            key, b = parts[1], self.body_json() or {}
            p = episode_path(b.get("episode"))
            if not video_file(key).exists() or not p.exists() or slug(p.stem) != key:
                raise ValueError("no such video (or its script is gone)")
            shot = int(b.get("shot") or 0)
            cmd = [sys.executable, "-u", str(PIPE / "cover.py"), str(p)] + (["--shot", str(shot)] if shot > 0 else [])
            job = Job("cover", f"Cover {key}", cmd, result={"cover": f"/media/{key}_cover.jpg", "video": key})
            return self.send_json(submit(job).to_dict())
        if head == "videos" and method in ("PUT", "DELETE") and len(parts) > 1:
            key = "/".join(parts[1:])
            if method == "DELETE":
                delete_video(key)
                return self.send_json({"ok": True})
            title = str((self.body_json() or {}).get("title") or "").strip()[:120]
            if not title:
                raise ValueError("give the video a name")
            if not video_file(key).exists():          # the video must exist
                raise ValueError("no such video")
            labels = load_labels()
            labels[key] = title
            LABELS_FILE.write_text(json.dumps(labels, indent=1), encoding="utf-8")
            return self.send_json({"ok": True, "title": title})

        if head == "postiz":                     # drafts on the user's Postiz (nothing is published from here)
            import postiz
            if arg == "channels" and method == "GET":
                try:
                    chans = postiz.channels()
                    conf = (S.load_settings().get("postiz") or {}).get("channels") or {}
                    for c in chans:
                        c["platform"] = postiz.platform_of(c["identifier"])
                        c.update({k: conf.get(c["id"], {}).get(k) for k in ("enabled", "discord_channel")})
                    return self.send_json({"ok": True, "channels": chans})
                except Exception as exc:
                    return self.send_json({"ok": False, "error": str(exc), "channels": []})
            if arg == "captions" and method == "POST":
                b = self.body_json()
                video = postiz_base(str(b.get("video") or ""))
                try:
                    return self.send_json({"ok": True, "captions": postiz.captions(video)})
                except Exception as exc:
                    return self.send_json({"ok": False, "error": str(exc)})
            if arg == "draft" and method == "POST":
                b = self.body_json()
                key = str(b.get("video") or "")
                video = postiz_base(key)
                mp4 = video_file(key)
                if not mp4.exists():
                    raise ValueError("no such video")
                cmd = [sys.executable, "-u", str(PIPE / "postiz.py"), "draft", video, "--mp4", str(mp4)]
                if isinstance(b.get("captions"), dict):
                    tmp = ROOT / "build" / f"postiz_{video}.json"
                    tmp.parent.mkdir(exist_ok=True)
                    tmp.write_text(json.dumps(b["captions"]), encoding="utf-8")
                    cmd += ["--posts", str(tmp)]
                return self.send_json(submit(Job("postiz", f"Postiz drafts: {key}", cmd)).to_dict())

        if head == "settings":
            if method == "GET":
                return self.send_json(S.public_settings())
            if method == "PUT":
                S.save_settings(self.body_json())
                return self.send_json(S.public_settings())

        if head == "voices" and arg == "edge":
            return self.send_json(edge_voices())

        # characters
        if head == "characters":
            if method == "GET" and not arg:
                return self.send_json([character_info(c) for c in S.character_ids()])
            if not S.valid_id(arg or ""):
                raise ValueError("character id must be lowercase letters, numbers, - or _")
            if method == "POST" and sub == "preview":         # one still of this character (pipeline/character_preview.py)
                if not (S.CHAR_DIR / f"{arg}.blend").exists():
                    raise ValueError("this character has no model yet - import one first")
                cmd = [sys.executable, "-u", str(PIPE / "character_preview.py"), arg]
                return self.send_json(submit(Job("preview", f"Character preview: {arg}", cmd)).to_dict())
            if method == "GET" and not sub:
                return self.send_json(character_info(arg))
            if method == "PUT" and not sub:
                prof = self.body_json()
                S.save_character(arg, prof)
                return self.send_json(character_info(arg))
            if method == "DELETE" and not sub:      # never destroys: everything goes to assets/characters/.trash
                if arg == S.load_settings().get("active_character"):
                    raise ValueError("that's the active character - make another one active first")
                if not (S.CHAR_DIR / f"{arg}.json").exists():
                    return self.fail("no such character", 404)
                bin_ = S.CHAR_DIR / ".trash" / f"{arg}-{stamp()}"
                bin_.mkdir(parents=True, exist_ok=True)
                mine = re.compile(rf"{re.escape(arg)}(\..+|-\d{{8}}-\d{{6}}\.\w+)")     # catgirl.blend, catgirl-<stamp>.vrm
                moved = []
                for folder in (S.CHAR_DIR, VOICES):
                    for f in list(folder.glob(f"{arg}*")):
                        if f.is_file() and mine.fullmatch(f.name):
                            f.replace(bin_ / f.name)
                            moved.append(f.name)
                return self.send_json({"ok": True, "moved": moved, "trash": str(bin_.relative_to(ROOT))})
            if method == "POST" and sub == "activate":
                cfg = S.load_settings()
                cfg["active_character"] = arg
                S.save_settings(cfg)
                return self.send_json({"ok": True})
            if method == "POST" and sub == "model":
                fname = unquote(self.headers.get("X-Filename") or "model.vrm")
                if not fname.lower().endswith(".vrm"):
                    raise ValueError("upload a .vrm file exported from VRoid Studio")
                dest = S.CHAR_DIR / f"{arg}.vrm"
                if dest.exists():
                    dest.replace(S.CHAR_DIR / f"{arg}-{stamp()}.vrm")      # keep the previous export
                blend = S.CHAR_DIR / f"{arg}.blend"
                if blend.exists():
                    shutil.copy2(blend, S.CHAR_DIR / f"{arg}-{stamp()}.blend")  # and the previous model
                self.body_to_file(dest)
                if not (S.CHAR_DIR / f"{arg}.json").exists():
                    S.save_character(arg, {"name": arg})
                return self.send_json(submit(import_model_job(arg, dest)).to_dict())
            if method == "POST" and sub == "voice-ref":
                fname = unquote(self.headers.get("X-Filename") or "voice.wav")
                tmp = VOICES / f".upload-{stamp()}{Path(fname).suffix.lower()[:6]}"
                self.body_to_file(tmp)
                out = VOICES / f"{arg}.wav"
                if out.exists():
                    out.replace(VOICES / f"{arg}-{stamp()}.wav")
                r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp),
                                    "-ac", "1", "-ar", "48000", str(out)], capture_output=True, text=True)
                tmp.unlink(missing_ok=True)
                if r.returncode != 0:
                    raise ValueError("could not read that audio file: " + r.stderr[-300:])
                prof = S.load_character(arg)
                prof["voice"] = {**(prof.get("voice") or {}), "engine": "local",
                                 "ref": f"assets/voices/{arg}.wav"}
                S.save_character(arg, prof)
                return self.send_json(character_info(arg))
            if method == "POST" and sub == "say":
                text = (self.body_json().get("text") or "").strip()[:300]
                if not text:
                    raise ValueError("type something to say")
                out = OUTPUT / f"voice_test_{arg}.wav"
                cmd = [sys.executable, "-u", str(PIPE / "run_episode.py"), "--say", text, "--character", arg,
                       "--out", str(out)]
                job = Job("voice", f"Voice test: {arg}", cmd,
                          result={"audio": f"/media/{out.name}?t={int(time.time())}"})
                return self.send_json(submit(job).to_dict())

        return self.fail("unknown API call", 404)


SERVER_INFO = {"lan": False, "port": 8765}


class StudioServer(ThreadingHTTPServer):
    """On Windows, SO_REUSEADDR lets a second copy bind a port that is already in use (two copies of the app would
    both listen and split the requests). Ask for the port exclusively instead, so a second start waits or fails."""
    if os.name == "nt":
        allow_reuse_address = False

        def server_bind(self):
            import socket
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()


def lan_addresses():
    import socket
    ips = set()
    try:     # the address used to reach the internet = the one other devices on the LAN can reach
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def restart_app():
    """Start a fresh copy of this server (same arguments), then let this one exit. The new copy waits for the port."""
    time.sleep(1.0)                                  # let the browser get its reply first
    logs.event("RESTART: starting a new copy of the app")
    flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0   # detached, own process group on Windows
    subprocess.Popen([sys.executable, str(WEB / "server.py")] + sys.argv[1:], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)
    time.sleep(0.5)
    os._exit(0)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Low Poly Studio web app")
    ap.add_argument("--lan", action="store_true", help="also allow phones/tablets on your local network")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = ap.parse_args()
    lan = args.lan or os.environ.get("LOWPOLY_LAN") == "1"
    host = "0.0.0.0" if lan else "127.0.0.1"
    SERVER_INFO.update(lan=lan, port=args.port)
    logs.setup()
    for attempt in range(60):                        # after a restart the old copy may still hold the port for a moment
        try:
            srv = StudioServer((host, args.port), Handler)
            break
        except OSError:
            if attempt == 59:
                raise
            time.sleep(1)
    logs.event(f"server started on {host}:{args.port} (logs in {logs.LOGS})")
    if not (sfxlib.BUILTIN / "boom.wav").exists():    # a fresh install: synthesise the built-in sounds once
        submit(Job("sfx", "Make the built-in sound effects (first start)", [sys.executable, "-u", str(PIPE / "sfx.py")]))
    print(f"Low Poly Studio running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    print(f"  logging to {logs.LOGS}  (requests, changes, jobs and job output)")
    if lan:
        for ip in lan_addresses():
            print(f"  On your phone (same Wi-Fi):  http://{ip}:{args.port}")
        print("  PIN: " + ("on" if current_pin() else "off - anyone on your network can use the app "
                                                     "(set one in Settings -> Phone & network)"))
    threading.Thread(target=plan_loop, daemon=True).start()      # the weekly plan (Settings -> Weekly plan)
    threading.Thread(target=idle_loop, daemon=True).start()      # idle auto-make (Settings -> Idle auto-make)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
