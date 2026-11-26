"""A batch from the Ideas page: several picked ideas -> one video each (title, script, shots, saved, queued to render).

Run by the web app's /api/batch job: `python pipeline/batch.py <spec.json>`. Like a series it goes through the
studio's own API (the same steps as Custom Video: script with the set picked from the title, AI cast + scenes,
direct, save, render), so each video gets everything a single video gets; the renders wait in the render queue.
Each idea uses its own kind of video (template) and title (the first one it already has, else a new best one), and
is marked used when its episode is saved. One idea failing doesn't stop the others.
"""
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import randomvid  # noqa: E402
import settings as S  # noqa: E402
import templates  # noqa: E402
from progress import report  # noqa: E402
from series import LENGTHS, call, slug  # noqa: E402

MAX_IDEAS = 10


def wait_job(base, jid, limit=40 * 60):
    """A studio job (the scene) through the API: its finished job, or an error."""
    t0 = time.time()
    while time.time() - t0 < limit:
        j = call(base, "GET", f"/api/jobs/{jid}?from=0")
        if j["status"] == "done":
            return j
        if j["status"] == "failed":
            raise RuntimeError("the scene didn't come out - see the log")
        time.sleep(5)
    raise RuntimeError("the scene took too long")


def title_for(idea, o, model, char):
    """The idea's first title if it has some, else the best new one for its kind of video."""
    if idea.get("titles"):
        return idea["titles"][0]
    tpl = templates.get(idea.get("template"))
    theme = idea["topic"] + (f" - {idea['angle']}" if idea.get("angle") else "")
    got = llm.generate_titles(o["url"], model, char, theme, 4, starts=tpl["title_starts"], hint=tpl["title_hint"])
    return got[0] if got else idea["topic"][:1].upper() + idea["topic"][1:] + "?"


def main(spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8-sig"))
    base, ideas = spec["base"], spec["ideas"][:MAX_IDEAS]
    o = S.load_settings()["ollama"]
    model = spec.get("model") or o["model"]
    char = S.load_character(spec.get("character") or S.load_settings()["active_character"])
    stamp = time.strftime("%m%d%H%M")
    print(f"Batch: {len(ideas)} idea(s) -> one video each" + ("" if spec.get("render", True) else " (saved, not rendered)"))
    made, failed, renders = [], [], {}
    for i, idea in enumerate(ideas, 1):
        step = lambda f, what: report(0.02 + 0.96 * ((i - 1) + f) / len(ideas), f"Video {i}/{len(ideas)}: {what}")  # noqa: E731
        tpl_id = idea.get("template") if idea.get("template") in templates.TEMPLATES else templates.DEFAULT
        tpl = templates.get(tpl_id)
        try:
            step(0.02, "picking the title")
            title = title_for(idea, o, model, char)
            lo, hi = LENGTHS.get(spec.get("length"), tpl["lines"])
            rnd = idea.get("random")                     # a random video: its place, vibe and length (randomvid.py)
            if rnd:
                lo, hi = rnd["lines"]
            br_on = bool(spec.get("brainrot") or idea.get("brainrot"))       # 🧠 brain rot mode (Settings tab)
            step(0.1, "writing the script")
            r = call(base, "POST", "/api/ai/script", {
                "title": title, "set": f"new:{rnd['scene']}" if rnd else "auto", "scene_policy": "reuse",
                "character": spec.get("character") or "",
                "model": model, "lines": random.randint(lo, hi), "tone": rnd["tone"] if rnd else "", "co_stars": [],
                "template": tpl_id, "regulars": spec.get("regulars") or [],
                "extra": randomvid.extra(rnd) if rnd else
                ((f"The video's angle: {idea['angle']}." if idea.get("angle") else "")
                 + (f" {spec['note']}" if spec.get("note") else "")),
                "brainrot": br_on})                      # the server picks the words from the bank
            print(f"\n== {i}. {title}  [{tpl['name']}, set {r.get('set')}]\n{r['script']}")
            set_id, start = r["set"], None
            if rnd:                                      # the set for the picked place, made from the title and the script
                step(0.3, "making the scene")
                idea_text = f"{rnd['scene']}. {title}. {' '.join((r.get('lines') or [])[:2])}"[:300]
                job = call(base, "POST", "/api/sets/generate", {"idea": idea_text, "where": "", "light": rnd["light"],
                                                                 "style": rnd["style"]})
                set_id, start = (wait_job(base, job["id"]).get("result") or {}).get("set"), "front"
                if not set_id:
                    raise RuntimeError("the scene was made but its id didn't come back - see the set job's log")
            step(0.5, "directing the shots")
            d = call(base, "POST", "/api/autodirect", {
                "script": r["script"], "set": set_id, "start": start, "cast": {}, "co_stars": [], "beat_words": 4,
                "brainrot": br_on,                       # the server uses brain rot mode's own cutting
                "beat_sets": [], "cast_ai": True, "scene_ai": True, "character": spec.get("character") or "",
                "title": title, "scene_policy": "reuse", "template": tpl_id})
            ep = {"title": title, "set": d["set"], "start": d["start"], "shots": d["shots"], "script": r["script"],
                  "template": tpl_id, "idea": idea.get("id"),
                  "set_style": rnd["style"] if rnd else (spec.get("set_style") or "base"),
                  "batch": {"id": stamp, "part": i, "of": len(ideas)}}      # the Videos page's 🎬 Batch pill
            if br_on:
                ep["brainrot"] = True                  # one-word captions at render (run_episode.py)
            if spec.get("variation_of"):              # 🔁 a part 2 / another kind of video of an earlier one
                ep.pop("batch")
                ep["variation_of"] = spec["variation_of"]
            if not idea.get("id"):
                ep.pop("idea")
            if spec.get("character"):
                ep["character"] = spec["character"]
            cast = d.get("cast") or {}
            for rid in spec.get("regulars") or []:          # regulars are played by their own actor
                if rid in cast:
                    cast[rid].update(type="person", actor=rid)
            if cast:
                ep["cast"] = cast
            eid = f"{slug(title)[:40]}_{stamp}{i}"
            call(base, "PUT", f"/api/episodes/{eid}", ep)
            if spec.get("render", True):
                job = call(base, "POST", "/api/render", {"id": eid, "fresh_voice": False, "reuse_frames": False})
                renders[eid] = job.get("id")
                print(f"  saved as {eid}, render job {job.get('id')} queued")
            else:
                print(f"  saved as {eid} (open it from the Videos page's ✏️ Edit after a render, or Custom Video)")
            made.append(eid)
        except Exception as exc:                            # the next idea still gets its video
            failed.append(idea.get("topic", "?"))
            print(f"  !! '{idea.get('topic')}' failed: {exc.__class__.__name__}: {str(exc)[:200]}")
        step(1.0, "done")
    report(1.0, "All videos queued" if spec.get("render", True) else "All videos saved")
    print(f"\nDone: {len(made)} video(s) " + ("queued to render - they appear on the Videos page as they finish."
                                             if spec.get("render", True) else "saved.")
          + (f" Failed: {', '.join(failed)}." if failed else ""))
    if spec.get("drafts") and renders:
        drafts(base, renders)
    if failed and not made:
        sys.exit("No video could be made - see above.")


def drafts(base, renders, wait=4 * 3600):
    """The weekly plan: as each render finishes, a Postiz draft for it (captions written by the studio, as on the
    Videos page). Drafts only - nothing is scheduled or published."""
    print(f"\nWaiting for {len(renders)} render(s) to make the Postiz drafts...")
    left, t0 = dict(renders), time.time()
    while left and time.time() - t0 < wait:
        for eid, jid in list(left.items()):
            try:
                st = call(base, "GET", f"/api/jobs/{jid}?from=0")["status"]
            except Exception:
                continue
            if st in ("done", "failed"):
                left.pop(eid)
                if st == "failed":
                    print(f"  {eid}: the render failed - no draft")
                    continue
                try:
                    call(base, "POST", "/api/postiz/draft", {"video": eid_key(eid)})
                    print(f"  {eid}: Postiz draft queued")
                except Exception as exc:
                    print(f"  {eid}: couldn't make the draft ({exc.__class__.__name__}: {str(exc)[:120]})")
        if left:
            time.sleep(20)
    if left:
        print(f"  gave up waiting for: {', '.join(left)}")


def eid_key(eid):
    """The Videos page key of an episode (its slug, like run_episode names the mp4)."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", eid.lower()).strip("_") or "episode"     # = run_episode.slug


if __name__ == "__main__":
    main(sys.argv[1])
