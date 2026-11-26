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
import settings as S  # noqa: E402
import templates  # noqa: E402
from progress import report  # noqa: E402
from series import LENGTHS, call, slug  # noqa: E402

MAX_IDEAS = 10


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
    made, failed = [], []
    for i, idea in enumerate(ideas, 1):
        step = lambda f, what: report(0.02 + 0.96 * ((i - 1) + f) / len(ideas), f"Video {i}/{len(ideas)}: {what}")  # noqa: E731
        tpl_id = idea.get("template") if idea.get("template") in templates.TEMPLATES else templates.DEFAULT
        tpl = templates.get(tpl_id)
        try:
            step(0.02, "picking the title")
            title = title_for(idea, o, model, char)
            lo, hi = LENGTHS.get(spec.get("length"), tpl["lines"])
            step(0.1, "writing the script")
            r = call(base, "POST", "/api/ai/script", {
                "title": title, "set": "auto", "scene_policy": "reuse", "character": spec.get("character") or "",
                "model": model, "lines": random.randint(lo, hi), "tone": "", "co_stars": [], "template": tpl_id,
                "regulars": spec.get("regulars") or [],
                "extra": (f"The video's angle: {idea['angle']}." if idea.get("angle") else "")
                + (f" {spec['note']}" if spec.get("note") else "")})
            print(f"\n== {i}. {title}  [{tpl['name']}, set {r.get('set')}]\n{r['script']}")
            step(0.5, "directing the shots")
            d = call(base, "POST", "/api/autodirect", {
                "script": r["script"], "set": r["set"], "start": None, "cast": {}, "co_stars": [], "beat_words": 4,
                "beat_sets": [], "cast_ai": True, "scene_ai": True, "character": spec.get("character") or "",
                "title": title, "scene_policy": "reuse", "template": tpl_id})
            ep = {"title": title, "set": d["set"], "start": d["start"], "shots": d["shots"], "script": r["script"],
                  "template": tpl_id, "idea": idea["id"], "set_style": spec.get("set_style") or "base",
                  "batch": {"id": stamp, "part": i, "of": len(ideas)}}      # the Videos page's 🎬 Batch pill
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
    if failed and not made:
        sys.exit("No video could be made - see above.")


if __name__ == "__main__":
    main(sys.argv[1])
