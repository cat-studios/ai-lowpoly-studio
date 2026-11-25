"""
Trending topics -> an idea database for video titles (the Ideas page, Custom Video's Idea step, random video
cards, series).

Sources (free, no accounts, nothing about the user is sent - a generic User-Agent only):
  - Google Trends daily trending searches (RSS) for each region in REGIONS (US, UK, Lithuania),
  - Wikipedia's most-read articles of the day (English; Lithuanian for LT),
  - Wikipedia's featured article and "on this day" events,
  - a built-in calendar of upcoming holidays and seasons (no internet needed).
  (Reddit refuses requests without an account - tried 2026-11-25, 403 on the JSON and the RSS.)
Raw items pass a word filter (no tragedies, politics, crime, gossip), then the AI keeps the ones that make a good
family-friendly "What if / How does" video and writes each as {topic, angle, template}. Stored in
assets/ideas/ideas.json (gitignored, the user's data): ideas are never deleted - hidden, starred or marked used
(with the videos that used them).

CLI: python pipeline/ideas.py fetch      (the web app runs it as an "ideas" job)
"""
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "assets" / "ideas"
DB = DIR / "ideas.json"
UA = "LowPolyStudio/1.0 (trending topics for video ideas)"
REGIONS = {"US": "United States", "GB": "United Kingdom", "LT": "Lithuania"}
# upcoming holidays/seasons by month (shown from the month before): (month, day, name)
CALENDAR = [(1, 1, "New Year's Day"), (2, 14, "Valentine's Day"), (2, 16, "Lithuanian Independence Day"),
            (3, 17, "St Patrick's Day"), (3, 20, "the first day of spring"), (4, 1, "April Fools' Day"),
            (4, 22, "Earth Day"), (5, 20, "World Bee Day"), (6, 21, "the longest day of the year"),
            (6, 24, "Midsummer (Joninės)"), (7, 4, "the Fourth of July"), (8, 8, "International Cat Day"),
            (9, 22, "the first day of autumn"), (10, 31, "Halloween"), (11, 1, "All Saints' Day"),
            (11, 27, "Thanksgiving"), (12, 21, "the shortest day of the year"), (12, 24, "Christmas Eve"),
            (12, 25, "Christmas"), (12, 31, "New Year's Eve")]
STALE_HOURS = 12              # the Ideas page fetches again when the newest batch is older than this

# never a cute catgirl video: the AI filter checks too, this keeps the obvious ones from ever reaching it
BLOCK = re.compile(r"\b(dies|died|dead|death|killed|kill|murder|shooting|shot|stabbed|crash|war|attack|bomb|"
                   r"terror\w*|suicide|abuse|assault|rape|arrest\w*|court|trial|lawsuit|sentenced|prison|election|"
                   r"vote|voting|president|senator|minister|parliament|trump|biden|putin|israel|gaza|ukraine|"
                   r"russia|politic\w*|democrat\w*|republican\w*|nazi|porn\w*|sex\w*|drugs?|cocaine|overdose|"
                   r"cancer|obituary|funeral|earthquake|hurricane|flood|wildfire|scandal|divorce|nfl|nba|"
                   r"premier league|vs\.?|odds|bet|betting|lottery|stock|stocks|crypto\w*|bitcoin|guns?|rifles?|sniper\w*|"
                   r"weapons?|missiles?|grenades?)\b", re.I)


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- sources -> raw items
def google_trends(geo):
    """[{text, context, source, region, url}] from Google's daily trending searches RSS."""
    out = []
    root = ET.fromstring(_get(f"https://trends.google.com/trending/rss?geo={geo}"))
    ns = {"ht": "https://trends.google.com/trending/rss"}
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        news = [n.findtext("ht:news_item_title", default="", namespaces=ns) for n in it.findall("ht:news_item", ns)]
        if title:
            out.append({"text": title, "context": " / ".join(x for x in news if x)[:300], "source": "google",
                        "region": geo})
    return out


def wikipedia_most_read(lang="en", region="US"):
    day = dt.date.today() - dt.timedelta(days=1)
    url = f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/featured/{day:%Y/%m/%d}"
    data = json.loads(_get(url))
    out = []
    for a in ((data.get("mostread") or {}).get("articles") or [])[:40]:
        t = ((a.get("titles") or {}).get("normalized") or "").strip()
        if t and not t.startswith(("Main Page", "Special:", "Wikipedia:", "File:")):
            out.append({"text": t, "context": str(a.get("description") or a.get("extract") or "")[:300],
                        "source": "wikipedia", "region": region,
                        "url": ((a.get("content_urls") or {}).get("desktop") or {}).get("page")})
    return out


def wikipedia_extras(lang="en", region="US"):
    """The featured article and "on this day" events (curious history, inventions, firsts)."""
    day = dt.date.today()
    data = json.loads(_get(f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/featured/{day:%Y/%m/%d}"))
    out = []
    tfa = data.get("tfa") or {}
    if tfa.get("normalizedtitle"):
        out.append({"text": tfa["normalizedtitle"], "context": str(tfa.get("description") or "")[:300],
                    "source": "wikipedia", "region": region})
    for ev in (data.get("onthisday") or [])[:25]:
        txt = str(ev.get("text") or "").strip()
        if txt:
            out.append({"text": txt[:200], "context": f"on this day in {ev.get('year')}", "source": "onthisday",
                        "region": region})
    return out


def calendar_items(today=None):
    """Holidays and seasons in the next 45 days (no internet)."""
    today = today or dt.date.today()
    out = []
    for m, d, name in CALENDAR:
        when = dt.date(today.year, m, d)
        if when < today:
            when = dt.date(today.year + 1, m, d)
        days = (when - today).days
        if days <= 45:
            out.append({"text": name, "context": f"in {days} days" if days else "today", "source": "calendar",
                        "region": "LT" if "Lithuan" in name or "Jonin" in name else "US"})
    return out


def gather(log=print):
    """Every source that answers; one that fails is skipped (logged)."""
    items = []
    jobs = [(f"Google Trends {g}", lambda g=g: google_trends(g)) for g in REGIONS]
    jobs += [("Wikipedia (en)", lambda: wikipedia_most_read("en", "US")),
             ("Wikipedia (lt)", lambda: wikipedia_most_read("lt", "LT"))]
    jobs += [("Wikipedia featured + on this day", lambda: wikipedia_extras("en", "US")),
             ("Holidays and seasons", calendar_items)]
    for name, fn in jobs:
        try:
            got = fn()
            items += got
            log(f"[ideas] {name}: {len(got)}")
        except Exception as exc:
            log(f"[ideas] {name}: skipped ({exc.__class__.__name__}: {str(exc)[:80]})")
    keep = [it for it in items if not BLOCK.search(f"{it['text']} {it.get('context', '')}")]
    log(f"[ideas] {len(items)} trending item(s), {len(keep)} after the word filter")
    return keep


# --------------------------------------------------------------------------- the AI picks and shapes ideas
PICK = (
    "You find ideas for short, funny, family-friendly animated videos where a cute cartoon catgirl answers a "
    "curious question (kinds: what_if = an impossible situation imagined, how_it_works = how a real thing works, "
    "quick_facts = surprising true facts, mini_story = a small adventure). From the trending items, keep ONLY "
    "those that can become such a video for all ages: science, nature, animals, space, food, games, inventions, "
    "places, holidays, sports in general, everyday mysteries. Skip anything about a real person by name, "
    "politics, tragedies, crime, weapons, gossip, betting, adult topics and anything sad, and never name a brand, "
    "company, film, TV show, game, book or franchise or its characters - the videos are original, so take the "
    "general idea behind it instead (a trending space film -> how black holes work; a car game -> why cars "
    "drift). Write topic and angle in ENGLISH even when the item is in another language. "
    "Reply with JSON only: {\"ideas\": [{\"item\": number, "
    "\"topic\": \"2-6 words\", \"angle\": \"the video's angle in one short sentence\", \"template\": "
    "\"what_if|how_it_works|quick_facts|mini_story\"}]}")


def pick_ideas(items, ollama, log=print, batch=30):
    import llm
    out = []
    for k in range(0, len(items), batch):
        chunk = items[k:k + batch]
        listing = "\n".join(f"{i}. {it['text']}" + (f" ({it['context'][:120]})" if it.get("context") else "")
                            for i, it in enumerate(chunk))
        try:
            r = llm.chat_json(ollama["url"], ollama["model"], PICK, f"Trending items:\n{listing}", 0.4)
        except Exception as exc:
            log(f"[ideas] the AI couldn't sort batch {k // batch + 1} ({exc.__class__.__name__})")
            continue
        for x in (r.get("ideas") or []) if isinstance(r, dict) else []:
            try:
                it = chunk[int(x.get("item"))]
            except Exception:
                continue
            topic = re.sub(r"\s+", " ", str(x.get("topic") or "")).strip()[:60]
            if not topic or BLOCK.search(f"{topic} {x.get('angle', '')}"):
                continue
            name = it["text"].strip()
            if len(re.findall(r"\b[A-Z][\w'’]*", name)) >= 2 and name.lower() in topic.lower():
                continue      # the topic is just the trending name (a game, film, person): "Grand Theft Auto VI"
            out.append({"topic": topic, "angle": str(x.get("angle") or "").strip()[:200],
                        "template": x.get("template") if x.get("template") in
                        ("what_if", "how_it_works", "quick_facts", "mini_story") else "what_if",
                        "source": it["source"], "region": it["region"], "trend": it["text"][:120],
                        "url": it.get("url")})
    return out


# --------------------------------------------------------------------------- the database
def load():
    try:
        return json.loads(DB.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"fetched": 0, "ideas": []}


def save(db):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DB)


def _id(topic):
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:40] + "_" + \
        hashlib.sha1(topic.lower().encode()).hexdigest()[:5]


def add(db, idea, log=print):
    """Add an idea unless the same topic is already there (then its trend info is refreshed). Returns it."""
    key = re.sub(r"[^a-z0-9]+", " ", idea["topic"].lower()).strip()
    for old in db["ideas"]:
        if re.sub(r"[^a-z0-9]+", " ", old["topic"].lower()).strip() == key:
            old["seen"] = time.time()
            return old
    idea = {"id": _id(idea["topic"]), "topic": idea["topic"], "angle": idea.get("angle", ""),
            "template": idea.get("template", "what_if"), "source": idea.get("source", "mine"),
            "region": idea.get("region", ""), "trend": idea.get("trend", ""), "url": idea.get("url"),
            "added": time.time(), "seen": time.time(), "starred": False, "hidden": False, "used": [],
            "titles": []}
    db["ideas"].insert(0, idea)
    return idea


def find(db, iid):
    return next((i for i in db["ideas"] if i["id"] == iid), None)


def mark_used(iid, episode_id):
    db = load()
    it = find(db, iid)
    if it and episode_id not in it["used"]:
        it["used"].append(episode_id)
        save(db)


def fresh(limit=12, region=None):
    """New ideas for the cards: not hidden, not used, newest trend first (starred ones first)."""
    db = load()
    out = [i for i in db["ideas"] if not i["hidden"] and not i["used"] and (not region or i["region"] == region)]
    out.sort(key=lambda i: (not i["starred"], -i.get("seen", 0)))
    return out[:limit]


def stale():
    return time.time() - load().get("fetched", 0) > STALE_HOURS * 3600


def fetch(log=print):
    import settings as S
    from progress import report
    report(0.05, "Reading what's trending")
    items = gather(log)
    report(0.4, "Picking video ideas")
    o = S.load_settings()["ollama"]
    picked = pick_ideas(items, o, log) if items else []
    db = load()
    new = sum(1 for p in picked if find(db, _id(p["topic"])) is None and add(db, p))
    db["fetched"] = time.time()
    save(db)
    report(1.0, "Done")
    log(f"[ideas] {len(picked)} idea(s) picked, {new} new - {len(db['ideas'])} in the database")
    return new


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        fetch()
    else:
        print(json.dumps(fresh(), indent=1, ensure_ascii=False))
