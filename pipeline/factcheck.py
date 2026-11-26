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
import hashlib
import json
import re
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


TEXT_LIMIT = 3500          # characters of the article the judge reads


def _keywords(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def relevant(text, claim, limit=TEXT_LIMIT):
    """The article's first paragraph + the paragraphs that share the most words with the claim, up to `limit`.
    (Wikipedia's own extract stops at 1,200 characters - the intro, which rarely holds the detail being checked.)"""
    paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 40 and not p.strip().startswith("==")]
    if not paras:
        return text[:limit]
    want = _keywords(claim)
    ranked = sorted(paras[1:], key=lambda p: -len(want & _keywords(p)))
    out, size = [paras[0]], len(paras[0])
    for p in ranked:
        if not want & _keywords(p) or size + len(p) > limit:
            continue
        out.append(p)
        size += len(p)
    return "\n\n".join(out)[:limit]


def article(search, claim=""):
    """(url, text) of Wikipedia's best match for a search - the parts about the claim -, or (None, "")."""
    hits = _wiki({"list": "search", "srsearch": search, "srlimit": 1}).get("query", {}).get("search") or []
    if not hits:
        return None, ""
    title = hits[0]["title"]
    pages = _wiki({"prop": "extracts", "explaintext": 1, "exlimit": 1, "titles": title}).get("query", {}).get("pages") or [{}]
    text = pages[0].get("extract") or ""
    return ("https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            relevant(text, claim or search))


def script_key(lines):
    """Same spoken lines = same facts: a re-render with the same script reuses the last check."""
    return hashlib.sha1("\n".join(t for _, t in lines).encode("utf-8")).hexdigest()[:16]


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
    lines = spoken_lines(ep)
    key = script_key(lines)
    try:                                                        # same script as the last check: keep its result
        old = json.loads((build / "facts.json").read_text(encoding="utf-8"))
        if old.get("key") == key and old.get("status") == "done":
            log(f"  fact check: same script as before ({len(old.get('claims') or [])} claims)")
            return old
    except Exception:
        pass
    res = {"status": "skipped", "checked": None, "error": "", "key": key, "claims": []}
    try:
        o = S.load_settings()["ollama"]
        listing = "\n".join(f"{n}. {t}" for n, t in lines)
        got = llm.chat_json(o["url"], o["model"], EXTRACT, listing, temperature=0.2)
        found = got if isinstance(got, list) else (got or {}).get("claims") or []
        shot_of = dict(lines)
        for c in found[:MAX_CLAIMS]:
            if not isinstance(c, dict) or not str(c.get("claim") or "").strip():
                continue
            try:                                                 # one claim that breaks never loses the others
                n = int(str(c.get("n") or 0).strip(". "))
            except ValueError:
                n = 0
            try:
                src, text = article(str(c.get("search") or c["claim"])[:120], str(c["claim"]))
                if not text:
                    verdict, note = "unknown", "no Wikipedia article found for it"
                else:
                    j = llm.chat_json(o["url"], o["model"], JUDGE,
                                      f"FACT: {c['claim']}\n\nARTICLE ({src}):\n{text}", temperature=0.1) or {}
                    verdict = j.get("verdict") if isinstance(j, dict) and j.get("verdict") in VERDICTS else "unknown"
                    note = str(j.get("note") or "")[:300] if isinstance(j, dict) else ""
            except Exception as exc:
                src, verdict, note = "", "unknown", f"couldn't check it ({exc.__class__.__name__})"
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
