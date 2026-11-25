"""A series: one idea -> 1-4 episodes, each with its own title, script and shots, each queued to render.

Run by the web app's /api/series job: `python pipeline/series.py <spec.json>`. It goes through the studio's own API
(the same steps as the Create page: script with the set picked from the title, AI cast + scenes, direct, save,
render), so a series gets everything a single video gets. Renders wait in the render queue one after another.
Every episode is saved with "series": {id, idea, part, of} and its "template".
"""
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import settings as S  # noqa: E402
import templates  # noqa: E402
from progress import report  # noqa: E402

LENGTHS = {"short": (4, 5), "long": (10, 13)}       # "medium" = the template's own


def call(base, method, path, body=None, timeout=1800):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:44] or "episode"


def main(spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8-sig"))
    base, idea, n = spec["base"], spec["idea"], int(spec["count"])
    tpl_id = spec.get("template") or templates.DEFAULT
    tpl = templates.get(tpl_id)
    o = S.load_settings()["ollama"]
    model = spec.get("model") or o["model"]
    sid = f"{slug(idea)[:24]}_{time.strftime('%m%d%H%M')}"
    print(f"Series '{idea}' - {n} episode(s), template {tpl['name']}")
    report(0.03, "Planning the episodes")
    titles = llm.series_titles(o["url"], model, idea, n, starts=tpl["title_starts"], hint=tpl["title_hint"])
    for i, t in enumerate(titles, 1):
        print(f"  {i}. {t}")
    lo, hi = LENGTHS.get(spec.get("length"), tpl["lines"])
    made = []
    for i, title in enumerate(titles, 1):
        step = lambda f, what: report(0.08 + 0.9 * ((i - 1) + f) / len(titles), f"Episode {i}/{len(titles)}: {what}")  # noqa: E731
        others = [t for t in titles if t != title]
        extra = (f"This is episode {i} of {len(titles)} of a series about: {idea}."
                 + (f" The other episodes are: {'; '.join(others)} - don't repeat what they cover." if others else "")
                 + (" End with a one-line hook for the next episode." if i < len(titles) else "")
                 # "dreaming and wakes up at the end" was followed in 1 of 4 episodes as a soft "Also:"
                 + (f" A MUST for this episode (the person who ordered the series asked for it): {spec['note']}"
                    if spec.get("note") else ""))
        step(0.05, "writing the script")
        r = call(base, "POST", "/api/ai/script", {"title": title, "set": "auto", "scene_policy": "reuse",
                                                  "character": spec.get("character") or "", "model": model,
                                                  "lines": random.randint(lo, hi), "tone": spec.get("tone") or "",
                                                  "extra": extra, "co_stars": [], "template": tpl_id})
        print(f"\n== Episode {i}: {title}  (set {r.get('set')})\n{r['script']}")
        step(0.45, "directing the shots")
        d = call(base, "POST", "/api/autodirect", {"script": r["script"], "set": r["set"], "start": None, "cast": {},
                                                   "co_stars": [], "beat_words": 4, "beat_sets": [],
                                                   "cast_ai": True, "scene_ai": True,
                                                   "character": spec.get("character") or "", "title": title,
                                                   "scene_policy": "reuse", "template": tpl_id})
        ep = {"title": title, "set": d["set"], "start": d["start"], "shots": d["shots"], "script": r["script"],
              "template": tpl_id, "series": {"id": sid, "idea": idea, "part": i, "of": len(titles)}}
        if spec.get("character"):
            ep["character"] = spec["character"]
        if d.get("cast"):
            ep["cast"] = d["cast"]
        eid = f"{slug(title)}_{sid[-8:]}{i}"
        call(base, "PUT", f"/api/episodes/{eid}", ep)
        step(0.9, "queued to render")
        job = call(base, "POST", "/api/render", {"id": eid, "fresh_voice": False, "reuse_frames": False})
        print(f"  saved as {eid}, render job {job.get('id')} queued")
        made.append(eid)
    report(1.0, "All episodes queued")
    print(f"\nDone: {len(made)} episode(s) queued to render - they appear on the Videos page as they finish.")


if __name__ == "__main__":
    main(sys.argv[1])
