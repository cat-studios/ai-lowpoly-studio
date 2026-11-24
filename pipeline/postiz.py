"""
Send finished videos to Postiz (self-hosted or cloud) as DRAFTS - nothing is scheduled or published from here;
times are set by hand in Postiz.

    python pipeline/postiz.py channels                      # check the key, list connected channels
    python pipeline/postiz.py captions <video name>         # print the generated captions (JSON)
    python pipeline/postiz.py draft <video name> [--posts posts.json]

Settings (config/settings.json -> "postiz"): url, api_key, channels {integration id: {enabled, discord_channel}},
youtube_privacy, made_with_ai, extra_hashtags. API: <url>/api/public/v1 (self-hosted) or
https://api.postiz.com/public/v1 (cloud); header "Authorization: <api key>" (no Bearer).
Upload: POST /upload (multipart "file") -> {id, path}. Draft: POST /posts {"type": "draft", ...}.
"""
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TRENDY = {   # always-on discovery tags per platform (+ the topic tags the AI picks)
    "instagram": ["#fyp", "#reels", "#explorepage", "#viral", "#trending"],
    "tiktok": ["#fyp", "#foryou", "#foryoupage", "#viral", "#trending"],
    "youtube": ["#shorts", "#trending", "#viral"],
}
MAX_TAGS = {"instagram": 15, "tiktok": 8, "youtube": 6}


class PostizError(RuntimeError):
    pass


def cfg():
    return S.load_settings().get("postiz", {})


def base_url(c=None):
    c = c or cfg()
    u = str(c.get("url") or "").strip().rstrip("/")
    if not u:
        raise PostizError("Set your Postiz address in Settings first")
    if "api.postiz.com" in u:
        return u if u.endswith("/public/v1") else u + "/public/v1"
    if u.endswith("/api/public/v1") or u.endswith("/public/v1"):
        return u
    return u + "/api/public/v1"


def _req(method, path, body=None, headers=None, c=None, timeout=60, raw=None):
    c = c or cfg()
    key = str(c.get("api_key") or "").strip()
    if not key:
        raise PostizError("Add your Postiz API key in Settings (Postiz: Settings > Developers)")
    h = {"Authorization": key, "Accept": "application/json", "User-Agent": "LowPolyStudio/1.0"}
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(base_url(c) + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", "replace")[:300]
        hint = {401: " - the API key was refused", 403: " - not allowed for this key", 404: " - wrong address?",
                413: " - too big", 429: " - Postiz rate limit, try again later"}.get(exc.code, "")
        raise PostizError(f"Postiz said {exc.code}{hint}: {msg}") from None
    except urllib.error.URLError as exc:
        raise PostizError(f"Can't reach Postiz at {base_url(c)} ({exc.reason})") from None
    try:
        return json.loads(txt) if txt.strip() else {}
    except ValueError:
        raise PostizError(f"Postiz answered with something that isn't JSON (wrong address?): {txt[:120]}") from None


def channels(c=None):
    """Connected channels: [{id, name, identifier (provider), picture, disabled}]."""
    out = _req("GET", "/integrations", c=c, timeout=20)
    rows = out if isinstance(out, list) else out.get("integrations", [])
    return [{"id": r.get("id"), "name": r.get("name") or r.get("profile") or r.get("identifier"),
             "identifier": r.get("identifier") or r.get("providerIdentifier") or "", "picture": r.get("picture"),
             "disabled": bool(r.get("disabled"))} for r in rows if r.get("id")]


class _Multipart:
    """A multipart body read straight from the file (a 200 MB video isn't loaded into memory twice)."""

    def __init__(self, head, path, tail):
        self.parts = [head, path, tail]
        self.size = len(head) + path.stat().st_size + len(tail)
        self._fh = None

    def read(self, n=-1):
        while self.parts:
            part = self.parts[0]
            if isinstance(part, bytes):
                self.parts.pop(0)
                if part:
                    return part
                continue
            if self._fh is None:
                self._fh = part.open("rb")
            chunk = self._fh.read(n if n and n > 0 else 1 << 20)
            if chunk:
                return chunk
            self._fh.close()
            self._fh = None
            self.parts.pop(0)
        return b""


def upload(path, c=None, log=print):
    """Multipart upload of the video -> {"id", "path"}."""
    path = Path(path)
    boundary = "----lowpoly" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = _Multipart(head, path, tail)
    log(f"[postiz] uploading {path.name} ({body.size / 1e6:.1f} MB)")
    r = _req("POST", "/upload", c=c, timeout=600, raw=body,
             headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                      "Content-Length": str(body.size)})
    if not r.get("id") or not r.get("path"):
        raise PostizError(f"Upload didn't return an id/path: {str(r)[:200]}")
    return {"id": r["id"], "path": r["path"]}


# --------------------------------------------------------------------------- captions
def _tag(t):
    t = re.sub(r"[^0-9A-Za-z_]", "", str(t).lstrip("#"))
    return f"#{t}" if len(t) >= 2 else ""


def _tags(*groups, limit=15):
    out, seen = [], set()
    for g in groups:
        for t in g:
            t = _tag(t)
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out[:limit]


def platform_of(identifier):
    i = str(identifier or "").lower()
    for p in ("instagram", "tiktok", "youtube", "discord"):
        if p in i:
            return p
    return "other"


def episode_for(video):
    """The episode JSON behind output/<video>.mp4 (title + lines feed the captions)."""
    ep = ROOT / "episodes" / f"{video}.json"
    if ep.exists():
        return json.loads(ep.read_text(encoding="utf-8-sig"))
    return {"title": video.replace("_", " "), "shots": []}


def captions(video, chans=None, log=print):
    """Per-channel text: {integration id: {"platform", "content", "title"?, "tags"?}}. AI-written, with relevant
    topic hashtags plus each platform's trendy ones; falls back to a plain template if Ollama is offline."""
    c = cfg()
    ep = episode_for(video)
    title = ep.get("title") or video.replace("_", " ")
    lines = [s.get("line", "") for s in ep.get("shots", []) if s.get("line")]
    ai = {}
    try:
        import llm
        o = S.load_settings()["ollama"]
        ai = llm.social_copy(o["url"], o["model"], title, lines) or {}
    except Exception as exc:
        log(f"[postiz] AI captions unavailable ({exc.__class__.__name__}) - using a simple caption")
    hook = str(ai.get("caption") or f"{title} 🐾").strip()
    platform_tags = {t.lower() for ts in TRENDY.values() for t in ts} | {"#foryou", "#reel", "#short", "#youtubeshorts",
                                                                          "#tiktok", "#instagram", "#explore"}
    topic = [t for t in (ai.get("hashtags") or []) if isinstance(t, str)
             and _tag(t).lower() not in platform_tags]       # each platform gets only its own discovery tags
    extra = re.findall(r"#?\w+", str(c.get("extra_hashtags") or ""))
    yt_title = str(ai.get("youtube_title") or title).strip()[:95]
    discord = str(ai.get("discord") or f"New video: **{title}**").strip()
    out = {}
    for ch in (chans if chans is not None else channels()):
        conf = (c.get("channels") or {}).get(ch["id"], {})
        if chans is None and not conf.get("enabled"):
            continue
        p = platform_of(ch["identifier"])
        if p == "instagram":
            tags = _tags(topic, extra, TRENDY["instagram"], limit=MAX_TAGS["instagram"])
            out[ch["id"]] = {"platform": p, "content": f"{hook}\n.\n.\n{' '.join(tags)}"}
        elif p == "tiktok":
            tags = _tags(TRENDY["tiktok"][:3], topic, extra, TRENDY["tiktok"][3:], limit=MAX_TAGS["tiktok"])
            tt_title = re.sub(r"\s{2,}", " ", re.sub(r"#\w+", "", yt_title)).strip() or title   # no "#shorts" on TikTok
            out[ch["id"]] = {"platform": p, "content": f"{hook} {' '.join(tags)}", "title": tt_title[:90]}
        elif p == "youtube":
            tags = _tags(["#shorts"], topic, extra, TRENDY["youtube"][1:], limit=MAX_TAGS["youtube"])
            out[ch["id"]] = {"platform": p, "content": f"{hook}\n\n{' '.join(tags)}",
                             "title": (yt_title if len(yt_title) >= 2 else title)[:100],
                             "tags": [t.lstrip("#") for t in _tags(topic, extra, limit=12)]}
        elif p == "discord":
            out[ch["id"]] = {"platform": p, "content": discord}
        else:
            out[ch["id"]] = {"platform": p, "content": f"{hook}\n\n{' '.join(_tags(topic, extra, limit=8))}"}
        out[ch["id"]]["name"] = ch.get("name")
    return out


# --------------------------------------------------------------------------- drafts
def settings_for(platform, identifier, text, c):
    if platform == "instagram":
        return {"__type": "instagram-standalone" if "standalone" in identifier else "instagram",
                "post_type": "post", "is_trial_reel": False, "collaborators": [],
                "made_with_ai": bool(c.get("made_with_ai"))}
    if platform == "youtube":
        return {"__type": "youtube", "title": text.get("title") or "New video", "type": c.get("youtube_privacy", "public"),
                "selfDeclaredMadeForKids": "no", "tags": [{"value": t, "label": t} for t in text.get("tags", [])],
                "made_with_ai": bool(c.get("made_with_ai"))}
    if platform == "tiktok":
        return {"__type": "tiktok", "title": text.get("title", "")[:90], "privacy_level": "PUBLIC_TO_EVERYONE",
                "duet": False, "stitch": False, "comment": True, "autoAddMusic": "no", "brand_content_toggle": False,
                "brand_organic_toggle": False, "video_made_with_ai": bool(c.get("made_with_ai")),
                "content_posting_method": "DIRECT_POST"}
    if platform == "discord":
        return {"__type": "discord", "channel": str(text.get("discord_channel") or "")}
    return {"__type": identifier}


def draft(video, texts=None, log=print, mp4=None):
    """Upload the video once and create one DRAFT per enabled channel. Returns Postiz's reply.
    mp4 = the file to upload (default output/<video>.mp4; earlier versions pass their own file)."""
    c = cfg()
    mp4 = Path(mp4) if mp4 else ROOT / "output" / f"{video}.mp4"
    if not mp4.exists():
        raise PostizError(f"No video output/{video}.mp4")
    chans = {ch["id"]: ch for ch in channels(c)}
    enabled = {k: v for k, v in (c.get("channels") or {}).items() if v.get("enabled") and k in chans}
    if not enabled:
        raise PostizError("No channels ticked - choose them in Settings > Postiz")
    from progress import report
    report(0.1, "Writing captions")
    texts = texts or captions(video, [chans[k] for k in enabled], log)
    report(0.3, "Uploading the video")
    media = upload(mp4, c, log)
    report(0.85, "Creating drafts")
    posts = []
    for cid, conf in enabled.items():
        ch = chans[cid]
        p = platform_of(ch["identifier"])
        t = dict(texts.get(cid) or {})
        t["discord_channel"] = conf.get("discord_channel", "")
        if p == "discord" and not t["discord_channel"]:
            log(f"[postiz] skipping {ch['name']}: set its Discord channel ID in Settings > Postiz")
            continue
        value = {"content": t.get("content", "")}
        if p != "discord" or conf.get("discord_attach", True):
            value["image"] = [{"id": media["id"], "path": media["path"]}]
        posts.append({"integration": {"id": cid}, "value": [value], "settings": settings_for(p, ch["identifier"], t, c)})
        log(f"[postiz] draft for {ch['name']} ({p})")
    if not posts:
        raise PostizError("Nothing to send")
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    body = {"type": "draft", "date": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "shortLink": False, "tags": [],
            "posts": posts}
    res = _req("POST", "/posts", body, c=c, timeout=120)
    log(f"[postiz] created {len(posts)} draft(s) - open Postiz to set the times")
    report(1.0, "Done")
    return res


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    try:
        if cmd == "channels":
            print(json.dumps(channels(), indent=1))
        elif cmd == "captions":
            print(json.dumps(captions(sys.argv[2]), indent=1, ensure_ascii=False))
        elif cmd == "draft":
            texts = None
            if "--posts" in sys.argv:
                texts = json.loads(Path(sys.argv[sys.argv.index("--posts") + 1]).read_text(encoding="utf-8"))
            mp4 = sys.argv[sys.argv.index("--mp4") + 1] if "--mp4" in sys.argv else None
            res = draft(sys.argv[2], texts, mp4=mp4)
            print("POSTIZ_RESULT=" + json.dumps(res))
        else:
            sys.exit(__doc__)
    except PostizError as exc:
        sys.exit(f"[postiz] {exc}")


if __name__ == "__main__":
    main()
