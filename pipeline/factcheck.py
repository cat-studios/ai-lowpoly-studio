"""
Fact check for fact-heavy videos (Quick facts, Myth or fact): before the render, the facts the video states as true
are looked up in Wikipedia (free, no key, a generic User-Agent) and the local model judges each one against the
article's own text. Nothing is changed in the script - the result is build/<name>/facts.json:

  {"status": "done" | "skipped" | "error", "checked": time, "error": "...",
   "claims": [{"shot": 3, "line": "...", "claim": "...", "verdict": "supported" | "contradicted" | "unknown",
               "source": "https://en.wikipedia.org/wiki/...", "note": "..."}]}

review.py reports contradicted claims (warn) and unchecked ones (info) in the check after the render. A fact check
that can't run (Ollama off, Wikipedia unreachable) never stops a render: status "skipped" or "error".

    python pipeline/factcheck.py episodes/<id>.json     check now (Custom Video's 🔎 Check facts, /api/factcheck);
                                                         the render reuses the result while the script stays the same
"""
import hashlib
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
import llm  # noqa: E402
import settings as S  # noqa: E402

TEMPLATES = ("quick_facts", "myth_or_fact")      # the kinds that state facts
MAX_CLAIMS = 12                                   # per video (each one is a search and a model call)
WIKI = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "LowPolyStudio/1.0"}
VERDICTS = ("supported", "contradicted", "unknown")

EXTRACT = (
    "You pick out the FACTS ABOUT THE WORLD a short video states as true. You get numbered spoken lines. Return JSON: "
    '{"claims": [{"n": <line number>, "claim": "<the fact, one plain sentence that names its subject>", "search": '
    '"<2-4 words to look up on Wikipedia>"}]}. Only checkable facts about science, nature, animals, history, places, '
    "numbers, dates or how something works - at most 12. If a line calls something a myth, the claim is the TRUE fact "
    "that replaces it, not the myth. NOT facts: what the speaker says, does, feels or asks, jokes, greetings, "
    'opinions, questions, the story. Most funny scripts have none: then return {"claims": []}.'
)
JUDGE = (
    "You check one fact against the text of a Wikipedia article. Answer JSON: "
    '{"verdict": "supported" | "contradicted" | "unknown", "note": "<one short sentence>"}. "supported" = the text '
    'says the same thing about the same subject, "contradicted" = the text says otherwise about that subject, '
    '"unknown" = the text is about something else or does not cover it. Use only the text; when unsure, "unknown".'
)
# a world fact names its subject: a "claim" starting like this is about the speaker or the story, not checkable
NOT_A_SUBJECT = {"i", "i'm", "you", "you're", "she", "she's", "he", "he's", "we", "they", "it", "it's", "this",
                 "that", "my", "your", "her", "his", "our", "their"}


def applies(ep, cfg=None):
    """Only the kinds that state facts, and only when Settings -> AI tools' fact check is on."""
    on = ((cfg or {}).get("facts") or {}).get("check", True)
    return bool(on) and (ep.get("template") or "") in TEMPLATES


WIKI_GAP = 1.0              # seconds between Wikipedia calls (it answers 429 "too many requests" to bursts)
_LAST_CALL = [0.0]


def _user_agent():
    """Wikimedia asks API users for a contact; Settings -> AI tools -> fact check contact adds one if you choose
    (empty by default: nothing about you is sent)."""
    try:
        contact = str((S.load_settings().get("facts") or {}).get("contact") or "").strip()
    except Exception:
        contact = ""
    return {"User-Agent": UA["User-Agent"] + (f" ({contact})" if contact else "")}


def _wiki(params, tries=3):
    q = urllib.parse.urlencode({"format": "json", "formatversion": 2, "action": "query", **params})
    for attempt in range(tries):
        wait = WIKI_GAP - (time.time() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{WIKI}?{q}", headers=_user_agent()), timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == tries - 1:
                raise
            try:                                      # too many requests: wait as long as it asks (at most 20 s)
                time.sleep(min(20.0, float(exc.headers.get("Retry-After") or 5)))
            except ValueError:
                time.sleep(5)


TEXT_LIMIT = 3500          # characters of the article the judge reads


def _keywords(s):
    """The words that say something (4+ letters), cut to 5 letters so endings don't matter (octopuses ~ octopus)."""
    return {w[:5] for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


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
    """(url, text) of the Wikipedia article about the claim's subject - the parts about the claim -, or (None, "").
    The first of the top hits whose TITLE shares a word with the claim (the model's search words first, then the
    claim itself): "honey shelf life" once led to an actress who starred in a film called Honey."""
    want = _keywords(claim or search)
    for q in dict.fromkeys(x for x in (search, claim) if x):
        hits = _wiki({"list": "search", "srsearch": q, "srlimit": 3}).get("query", {}).get("search") or []
        title = next((h["title"] for h in hits if want & _keywords(h["title"])), None)
        if not title:
            continue
        pages = _wiki({"prop": "extracts", "explaintext": 1, "exlimit": 1, "titles": title}).get("query", {}).get("pages") or [{}]
        text = relevant(pages[0].get("extract") or "", claim or search)
        if want & _keywords(text):                # an article about something else is no source at all
            return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")), text
    return None, ""


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
            if shot_of.get(n) and not _keywords(str(c["claim"])) & _keywords(shot_of[n]):
                continue        # nothing in its line says so: the model made it up ("Just between us" -> "It is a secret")
            first = (re.findall(r"[a-z']+", str(c["claim"]).lower()) or [""])[0]
            if first in NOT_A_SUBJECT:
                continue        # about the speaker or the story ("She asks seriously..."), not a fact to look up
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


def build_dir(ep_path):
    """The render's build folder for an episode file (= run_episode: build/<slug of the file name>)."""
    name = re.sub(r"[^a-z0-9]+", "_", Path(ep_path).stem.lower()).strip("_") or "episode"
    return ROOT / "build" / name


def main(ep_path):
    ep = json.loads(Path(ep_path).read_text(encoding="utf-8-sig"))
    res = check_episode(ep, build_dir(ep_path))
    for c in res["claims"]:
        print(f"[{c['verdict']}] {c['claim']}" + (f" - {c['note']}" if c.get("note") else ""))
    if res["status"] != "done":
        sys.exit(f"The fact check couldn't run: {res['error'] or res['status']}")


if __name__ == "__main__":
    main(sys.argv[1])
