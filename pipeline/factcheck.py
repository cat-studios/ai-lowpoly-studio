"""
Fact check for fact-heavy videos (Quick facts, Myth or fact): before the render, the facts the video states as true
are looked up in Wikipedia (free, no key, a generic User-Agent) and the local model judges each one against the
article's own text. Nothing is changed in the script - the result is build/<name>/facts.json:

  {"status": "done" | "skipped" | "error", "checked": time, "error": "...",
   "claims": [{"shot": 3, "line": "...", "claim": "...", "verdict": "supported" | "contradicted" | "unknown",
               "source": "https://en.wikipedia.org/wiki/...", "note": "..."}]}

review.py reports contradicted claims (warn) and unchecked ones (info) in the check after the render. A fact check
that can't run (Ollama off, Wikipedia unreachable) never stops a render: status "skipped" or "error".
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import settings as S  # noqa: E402

TEMPLATES = ("quick_facts", "myth_or_fact")      # the kinds that state facts
MAX_CLAIMS = 12                                   # per video (each one is a search and a model call)
WIKI = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "LowPolyStudio/1.0"}
VERDICTS = ("supported", "contradicted", "unknown")

EXTRACT = (
    "You pick out the FACTS a short video states as true. You get numbered spoken lines. Return JSON: "
    '{"claims": [{"n": <line number>, "claim": "<the fact, one plain sentence>", "search": "<2-4 words to look up '
    'on Wikipedia>"}]}. Only checkable facts (numbers, dates, what something is or does), at most 12. If a line calls '
    "something a myth, the claim is the TRUE fact that replaces it, not the myth. Jokes, opinions and questions are "
    'not facts. If there are none, return {"claims": []}.'
)
JUDGE = (
    "You check one fact against the text of a Wikipedia article. Answer JSON: "
    '{"verdict": "supported" | "contradicted" | "unknown", "note": "<one short sentence>"}. "supported" = the text says '
    'so, "contradicted" = the text says otherwise, "unknown" = the text does not cover it. Use only the text.'
)


def applies(ep, cfg=None):
    """Only the kinds that state facts, and only when Settings -> AI tools' fact check is on."""
    on = ((cfg or {}).get("facts") or {}).get("check", True)
    return bool(on) and (ep.get("template") or "") in TEMPLATES


def _wiki(params):
    q = urllib.parse.urlencode({"format": "json", "formatversion": 2, "action": "query", **params})
    with urllib.request.urlopen(urllib.request.Request(f"{WIKI}?{q}", headers=UA), timeout=20) as r:
        return json.load(r)


def article(search):
    """(url, text) of Wikipedia's best match for a search, or (None, "") when nothing matches."""
    hits = _wiki({"list": "search", "srsearch": search, "srlimit": 1}).get("query", {}).get("search") or []
    if not hits:
        return None, ""
    title = hits[0]["title"]
    pages = _wiki({"prop": "extracts", "explaintext": 1, "exchars": 3000, "titles": title}).get("query", {}).get("pages") or [{}]
    text = pages[0].get("extract") or ""
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")), text


def spoken_lines(ep):
    """(shot number, text) for every shot that says something, in English (the source language)."""
    out = []
    for k, s in enumerate(ep.get("shots") or [], 1):
        text = (s.get("line_src") or s.get("line") or "").strip()
        if text:
            out.append((k, text))
    return out


def check_episode(ep, build, log=print):
    """Writes build/<name>/facts.json and returns it. Never raises."""
    build = Path(build)
    build.mkdir(parents=True, exist_ok=True)
    res = {"status": "skipped", "checked": None, "error": "", "claims": []}
    try:
        o = S.load_settings()["ollama"]
        lines = spoken_lines(ep)
        listing = "\n".join(f"{n}. {t}" for n, t in lines)
        found = (llm.chat_json(o["url"], o["model"], EXTRACT, listing, temperature=0.2) or {}).get("claims") or []
        shot_of = dict(lines)
        for c in found[:MAX_CLAIMS]:
            if not isinstance(c, dict) or not str(c.get("claim") or "").strip():
                continue
            n = int(c.get("n") or 0)
            src, text = article(str(c.get("search") or c["claim"])[:120])
            if not text:
                verdict, note = "unknown", "no Wikipedia article found for it"
            else:
                j = llm.chat_json(o["url"], o["model"], JUDGE,
                                  f"FACT: {c['claim']}\n\nARTICLE ({src}):\n{text}", temperature=0.1) or {}
                verdict = j.get("verdict") if j.get("verdict") in VERDICTS else "unknown"
                note = str(j.get("note") or "")[:300]
            res["claims"].append({"shot": n if n in shot_of else 0, "line": shot_of.get(n, ""), "claim": c["claim"],
                                  "verdict": verdict, "source": src or "", "note": note})
        res["status"] = "done"
        res["checked"] = time.time()
        bad = sum(1 for c in res["claims"] if c["verdict"] == "contradicted")
        log(f"  fact check: {len(res['claims'])} claims, {bad} contradicted")
    except Exception as exc:                                   # a check that can't run never stops the render
        res["status"], res["error"] = "error", f"{exc.__class__.__name__}: {str(exc)[:200]}"
        log(f"  fact check skipped: {res['error']}")
    (build / "facts.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res
