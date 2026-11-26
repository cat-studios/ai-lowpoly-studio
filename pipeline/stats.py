"""
Stats: how the posted videos did, next to what they were - so you can see which kinds of video work.

Numbers come from two places, each optional:
  - Instagram (Graph API: your token + Instagram account id in Settings -> Stats; each Reel is matched to its video
    by the title in its caption, or linked by hand on the Stats page).
  - YouTube (Settings -> Stats: your channel id; the YouTube API key from Settings -> Ideas). Views, likes, comments
    and the channel's subscriber count come from the public Data API. Average view duration / percentage viewed and
    subscribers gained per video need Analytics: a Google OAuth client plus a refresh token (Settings -> Stats).
    Each YouTube upload is matched to its video by its title.
Numbers can also be typed in by hand. Each video also records which cover was posted (A or B, from 🖼 Cover).
Store: assets/stats/stats.json (personal, gitignored).

    python pipeline/stats.py fetch       get the latest numbers (the Stats page's 🔄 button)
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402

STORE = ROOT / "assets" / "stats" / "stats.json"
GRAPH = "https://graph.facebook.com/v21.0"
YT_DATA = "https://www.googleapis.com/youtube/v3"
YT_ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
YT_TOKEN = "https://oauth2.googleapis.com/token"
YT_MAX = 200                      # newest uploads looked at per fetch
YT_HISTORY = 200                  # subscriber counts kept per channel
UA = {"User-Agent": "LowPolyStudio/1.0"}
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
    req = urllib.request.Request(f"{GRAPH}/{path}?{q}", headers=UA)
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


# ----------------------------------------------------------------------------- Instagram
def _ig_configured():
    cfg = S.load_settings().get("instagram") or {}
    return bool(str(cfg.get("token") or "").strip() and str(cfg.get("user_id") or "").strip())


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


# ----------------------------------------------------------------------------- YouTube
def _yt_configured():
    cfg = S.load_settings()
    return bool(str((cfg.get("youtube") or {}).get("channel_id") or "").strip()
                and str((cfg.get("ideas") or {}).get("youtube_key") or "").strip())


def _yt_analytics_configured(cfg):
    return all(str(cfg.get(k) or "").strip() for k in ("client_id", "client_secret", "refresh_token"))


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _yt_get(path, api_key, **params):
    """One Data API call. The key is in the URL, so error text is reduced to the HTTP code (never the URL)."""
    q = urllib.parse.urlencode({**params, "key": api_key})
    req = urllib.request.Request(f"{YT_DATA}/{path}?{q}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"YouTube said no to {path} ({exc.code}) - check the channel id and the API key")


def _yt_videos(api_key, channel):
    """(subscriber count or None when hidden, the newest uploads with their public numbers)."""
    ch = _yt_get("channels", api_key, part="contentDetails,statistics", id=channel)
    items = ch.get("items") or []
    if not items:
        raise SystemExit("YouTube: no channel with that id (it starts with UC; Settings -> Stats)")
    item = items[0]
    subs = _int((item.get("statistics") or {}).get("subscriberCount"))
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while len(ids) < YT_MAX:
        extra = {"pageToken": token} if token else {}
        pl = _yt_get("playlistItems", api_key, part="contentDetails", playlistId=uploads, maxResults=50, **extra)
        ids += [i["contentDetails"]["videoId"] for i in pl.get("items") or []]
        token = pl.get("nextPageToken")
        if not token:
            break
    ids = ids[:YT_MAX]
    videos = []
    for i in range(0, len(ids), 50):
        vs = _yt_get("videos", api_key, part="snippet,statistics", id=",".join(ids[i:i + 50]))
        for v in vs.get("items") or []:
            st = v.get("statistics") or {}
            videos.append({"id": v["id"], "title": (v.get("snippet") or {}).get("title") or "",
                           "views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
                           "comments": _int(st.get("commentCount"))})
    return subs, videos


def _yt_access_token(cfg):
    body = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                   "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request(YT_TOKEN, data=body, headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def _yt_analytics(cfg, start, end):
    """Per video: average view duration (s), average percentage viewed, subscribers gained (net)."""
    token = _yt_access_token(cfg)
    q = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": start, "endDate": end, "dimensions": "video",
                                "metrics": "views,averageViewDuration,averageViewPercentage,subscribersGained,"
                                           "subscribersLost", "sort": "-views", "maxResults": 200})
    req = urllib.request.Request(f"{YT_ANALYTICS}?{q}", headers={**UA, "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    cols = [c["name"] for c in data.get("columnHeaders") or []]
    out = {}
    for row in data.get("rows") or []:
        r = dict(zip(cols, row))
        out[r["video"]] = {"avg_view_secs": round(r.get("averageViewDuration") or 0),
                           "avg_view_pct": round(float(r.get("averageViewPercentage") or 0), 1),
                           "subs_gained": int(r.get("subscribersGained") or 0) - int(r.get("subscribersLost") or 0)}
    return out


def fetch_youtube(log=print):
    """YouTube: your newest uploads' numbers, matched to videos by title, plus the channel's subscriber count."""
    cfg = S.load_settings().get("youtube") or {}
    channel = str(cfg.get("channel_id") or "").strip()
    api_key = str((S.load_settings().get("ideas") or {}).get("youtube_key") or "").strip()
    if not channel or not api_key:
        raise SystemExit("Add your YouTube channel id (Settings -> Stats) and the YouTube API key (Settings -> Ideas).")
    subs, videos = _yt_videos(api_key, channel)
    analytics = {}
    if _yt_analytics_configured(cfg):
        try:
            analytics = _yt_analytics(cfg, "2010-01-01", date.today().isoformat())
        except urllib.error.HTTPError as exc:
            log(f"  YouTube Analytics said no ({exc.code}): retention numbers skipped - check the OAuth settings")
        except Exception as exc:
            log(f"  YouTube Analytics failed ({exc.__class__.__name__}): retention numbers skipped")
    now = time.time()
    db = load()
    titles = _video_titles()
    linked = {(v.get("yt") or {}).get("id"): k for k, v in db["videos"].items() if (v.get("yt") or {}).get("id")}
    n = 0
    for v in videos:
        key = linked.get(v["id"]) or match({"caption": v["title"]}, titles)
        if not key:
            continue
        yt = dict((db["videos"].setdefault(key, {}).get("yt") or {}))      # keep the retention numbers if this fetch has none
        yt.update({"id": v["id"], "title": v["title"], "views": v["views"], "likes": v["likes"],
                   "comments": v["comments"], "updated": now}, **(analytics.get(v["id"]) or {}))
        db["videos"][key]["yt"] = yt
        n += 1
    hist = ((db.get("youtube") or {}).get("history") or []) + ([[now, subs]] if subs is not None else [])
    db["youtube"] = {"channel": channel, "subscribers": subs, "fetched": now, "history": hist[-YT_HISTORY:]}
    save(db)
    log(f"YouTube: {len(videos)} uploads, {n} matched to your videos, {subs if subs is not None else 'hidden'} subscribers")
    return n


# ----------------------------------------------------------------------------- both
def fetch_all(log=print):
    """Whatever is connected: Instagram, YouTube or both. One failing does not stop the other."""
    if not _ig_configured() and not _yt_configured():
        raise SystemExit("Connect Instagram or YouTube first (Settings -> Stats).")
    errors = []
    for ok, run in ((_ig_configured(), fetch), (_yt_configured(), fetch_youtube)):
        if ok:
            try:
                run(log)
            except (SystemExit, Exception) as exc:       # a network error must not stop the other one
                errors.append(str(exc) or exc.__class__.__name__)
    if errors:
        raise SystemExit("; ".join(errors))


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
            "hook_style": ep.get("hook_style") or "?",                 # llm.HOOK_STYLES id ("?" = made before 2026-11-27)
            "brainrot": bool(ep.get("brainrot")),
            "shots": len(shots), "language": ep.get("language") or "en"}


def length_bucket(secs):
    if secs is None:
        return "?"
    return "under 20 s" if secs < 20 else "20-35 s" if secs < 35 else "35-50 s" if secs < 50 else "50 s +"


def _score(r):
    """The number averages use: Instagram views, else reach, else YouTube views."""
    if r.get("views") is not None:
        return r["views"]
    if r.get("reach") is not None:
        return r["reach"]
    return (r.get("yt") or {}).get("views")


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _yt_by(rows, field):
    """YouTube by one fact (kind, hook style): views, how much of each video people watch, subscribers it brought."""
    groups = {}
    for r in rows:
        if r.get("yt"):
            groups.setdefault(r.get(field) or "?", []).append(r["yt"])
    return sorted(({"value": k, "videos": len(x), "avg_views": _avg([y.get("views") for y in x]),
                    "avg_view_pct": _avg([y.get("avg_view_pct") for y in x]),
                    "avg_view_secs": _avg([y.get("avg_view_secs") for y in x]),
                    "subs": sum(y.get("subs_gained") or 0 for y in x)} for k, x in groups.items()),
                  key=lambda e: -(e["avg_views"] or 0))


def summary():
    """Every video with numbers + the averages by kind, length, cover and set; and YouTube's by kind."""
    db = load()
    rows = []
    for key, v in db["videos"].items():
        if v.get("views") is None and v.get("reach") is None and not v.get("yt"):
            continue
        rows.append({"key": key, **facts(key), **v})
    groups = {}
    for r in rows:
        score = _score(r)
        for dim, val in (("kind", r["template"]), ("length", length_bucket(r["seconds"])),
                         ("cover", (r.get("posted_cover") or "?").upper()), ("set", r["set"]),
                         ("hook", r.get("hook_style") or "?"), ("brainrot", "on" if r.get("brainrot") else "off")):
            g = groups.setdefault(dim, {}).setdefault(val, [])
            g.append(score or 0)
    avg = {dim: sorted(({"value": k, "videos": len(x), "avg": round(sum(x) / len(x))} for k, x in d.items()),
                       key=lambda e: -e["avg"]) for dim, d in groups.items()}
    yt = db.get("youtube") or {}
    return {"rows": sorted(rows, key=lambda r: -(_score(r) or 0)), "by": avg,
            "yt_by": _yt_by(rows, "template"), "yt_by_hook": _yt_by(rows, "hook_style"),
            "youtube": {"channel": yt.get("channel"), "subscribers": yt.get("subscribers"),
                        "fetched": yt.get("fetched"), "history": (yt.get("history") or [])[-60:]},
            "posts": [{k: p.get(k) for k in ("id", "caption", "permalink", "timestamp")} for p in db.get("posts") or []],
            "fetched": db.get("fetched"), "covers": {k: v.get("posted_cover") for k, v in db["videos"].items()}}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        fetch_all()
    else:
        print(json.dumps(summary(), indent=1)[:3000])


if __name__ == "__main__":
    main()
