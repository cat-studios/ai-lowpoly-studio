"""
Stats: how the posted videos did, next to what they were - so you can see which kinds of video work.

Numbers come from Instagram (Graph API: your token + Instagram account id in Settings -> Stats; each Reel is matched
to its video by the title in its caption, or linked by hand on the Stats page) or are typed in by hand. Each video
also records which cover was posted (A or B, from 🖼 Cover). Store: assets/stats/stats.json (personal, gitignored).

    python pipeline/stats.py fetch       get the latest numbers from Instagram (the Stats page's 🔄 button)
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402

STORE = ROOT / "assets" / "stats" / "stats.json"
GRAPH = "https://graph.facebook.com/v21.0"
METRICS = ["views", "likes", "comments", "shares", "saved", "reach"]
NUMBERS = ("views", "likes", "comments", "shares", "saved", "reach")


def load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"videos": {}, "posts": [], "fetched": 0}


def save(db):
    S.write_json(STORE, db)


def update(key, data):
    """The Stats page / Cover popup: posted cover, a link to an Instagram post, or numbers typed in by hand."""
    db = load()
    v = db["videos"].setdefault(key, {})
    if data.get("posted_cover") in ("a", "b", ""):
        v["posted_cover"] = data["posted_cover"]
    if "ig_id" in data:
        v["ig_id"] = str(data["ig_id"] or "")
        post = next((p for p in db.get("posts") or [] if p["id"] == v["ig_id"]), None)
        if post:
            v.update({k: post.get(k) for k in NUMBERS if post.get(k) is not None}, permalink=post.get("permalink"))
    for k in NUMBERS:
        if k in data and str(data[k]).strip() != "":
            v[k] = int(float(data[k]))
            v["manual"] = True
    v["updated"] = time.time()
    save(db)
    return v


def _get(path, token, **params):
    q = urllib.parse.urlencode({**params, "access_token": token})
    req = urllib.request.Request(f"{GRAPH}/{path}?{q}", headers={"User-Agent": "LowPolyStudio/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _words(s):
    return re.sub(r"[^a-z0-9 ]+", " ", str(s).lower()).split()


def match(post, titles):
    """The video a post is about: the one whose title's words (5+ of its first words) are in the caption."""
    cap = " ".join(_words(post.get("caption") or ""))
    best, n = None, 0
    for key, title in titles.items():
        w = [x for x in _words(title) if len(x) > 2][:6]
        if len(w) >= 2 and all(x in cap.split() for x in w) and len(w) > n:
            best, n = key, len(w)
    return best


def fetch(log=print):
    """Instagram: the latest Reels and their numbers; matched / linked posts update their videos."""
    cfg = S.load_settings().get("instagram") or {}
    token, uid = str(cfg.get("token") or "").strip(), str(cfg.get("user_id") or "").strip()
    if not token or not uid:
        raise SystemExit("Add your Instagram token and account id in Settings -> Stats first.")
    try:
        media = _get(f"{uid}/media", token, fields="id,caption,permalink,timestamp,media_product_type", limit=50)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300].replace(token, "***")
        raise SystemExit(f"Instagram said no ({exc.code}): {body}")
    posts = []
    for m in media.get("data") or []:
        if m.get("media_product_type") not in ("REELS", "FEED", None):
            continue
        p = {k: m.get(k) for k in ("id", "caption", "permalink", "timestamp")}
        try:
            ins = _get(f"{m['id']}/insights", token, metric=",".join(METRICS))
            for item in ins.get("data") or []:
                vals = item.get("values") or [{}]
                p[item["name"]] = vals[0].get("value") if vals else item.get("total_value", {}).get("value")
        except Exception as exc:
            log(f"  no numbers for {m.get('permalink')}: {exc.__class__.__name__}")
        posts.append(p)
    db = load()
    db["posts"], db["fetched"] = posts, time.time()
    titles = _video_titles()
    linked = {v.get("ig_id"): k for k, v in db["videos"].items() if v.get("ig_id")}
    n = 0
    for p in posts:
        key = linked.get(p["id"]) or match(p, titles)
        if not key:
            continue
        v = db["videos"].setdefault(key, {})
        v.update({k: p.get(k) for k in NUMBERS if p.get(k) is not None}, ig_id=p["id"], permalink=p.get("permalink"),
                 updated=time.time())
        v.pop("manual", None)
        n += 1
    save(db)
    log(f"Instagram: {len(posts)} posts, {n} matched to your videos")
    return n


def _video_titles():
    out = {}
    for p in (ROOT / "episodes").glob("*.json"):
        try:
            e = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        key = re.sub(r"[^a-z0-9]+", "_", p.stem.lower()).strip("_")
        if (ROOT / "output" / f"{key}.mp4").exists():
            out[key] = e.get("title") or p.stem
    return out


def facts(key):
    """What a video was: its kind, length, set, hook line, regulars - from its episode and render."""
    ep = {}
    for p in (ROOT / "episodes").glob("*.json"):
        if re.sub(r"[^a-z0-9]+", "_", p.stem.lower()).strip("_") == key:
            ep = json.loads(p.read_text(encoding="utf-8-sig"))
            break
    secs = None
    try:
        t = json.loads((ROOT / "build" / key / "timing.json").read_text(encoding="utf-8-sig"))
        secs = round(t["total_frames"] / t["fps"], 1)
    except Exception:
        pass
    shots = ep.get("shots") or []
    return {"title": ep.get("title") or key, "template": ep.get("template") or "what_if", "seconds": secs,
            "set": ep.get("set") or "", "hook": next((s.get("line") for s in shots if s.get("line")), ""),
            "shots": len(shots), "language": ep.get("language") or "en"}


def length_bucket(secs):
    if secs is None:
        return "?"
    return "under 20 s" if secs < 20 else "20-35 s" if secs < 35 else "35-50 s" if secs < 50 else "50 s +"


def summary():
    """Every video with numbers + the averages by kind, length, cover and set (views first, else reach)."""
    db = load()
    rows = []
    for key, v in db["videos"].items():
        if v.get("views") is None and v.get("reach") is None:
            continue
        rows.append({"key": key, **facts(key), **v})
    groups = {}
    for r in rows:
        score = r.get("views") if r.get("views") is not None else r.get("reach")
        for dim, val in (("kind", r["template"]), ("length", length_bucket(r["seconds"])),
                         ("cover", (r.get("posted_cover") or "?").upper()), ("set", r["set"])):
            g = groups.setdefault(dim, {}).setdefault(val, [])
            g.append(score or 0)
    avg = {dim: sorted(({"value": k, "videos": len(x), "avg": round(sum(x) / len(x))} for k, x in d.items()),
                       key=lambda e: -e["avg"]) for dim, d in groups.items()}
    return {"rows": sorted(rows, key=lambda r: -(r.get("views") or r.get("reach") or 0)), "by": avg,
            "posts": [{k: p.get(k) for k in ("id", "caption", "permalink", "timestamp")} for p in db.get("posts") or []],
            "fetched": db.get("fetched"), "covers": {k: v.get("posted_cover") for k, v in db["videos"].items()}}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        fetch()
    else:
        print(json.dumps(summary(), indent=1)[:3000])


if __name__ == "__main__":
    main()
