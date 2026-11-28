"""
Script and title ideas from a local Ollama server. Optional helper: everything can still be
written by hand. Output is plain script lines (with optional [directions]) that go through the
normal auto-director, so the AI never needs to know the JSON format.
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import catalog

DEFAULT_URL = "http://127.0.0.1:11434"


def _req(url, path, payload=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_models(url=DEFAULT_URL):
    tags = _req(url, "/api/tags", timeout=5)
    out = []
    for m in tags.get("models", []):
        fam = (m.get("details") or {}).get("family", "")
        if "embed" in m["name"] or fam in ("nomic-bert", "bert"):
            continue                      # embedding models can't chat
        out.append({"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "params": (m.get("details") or {}).get("parameter_size", "")})
    return out


_REMOTE_DOWN = {}          # big text server -> when it last failed (it's tried again after REMOTE_RETRY seconds)
REMOTE_RETRY = 300
# shared by every job (each is its own process): without it every fact check / script job waited the full
# REMOTE_TIMEOUT for a slow big server before using this PC
_DOWN_FILE = Path(__file__).resolve().parent.parent / "build" / "remote_down.json"


def _down_since(big):
    """When the big server last failed (this process or any other job)."""
    t = _REMOTE_DOWN.get(big, 0)
    try:
        t = max(t, float(json.loads(_DOWN_FILE.read_text(encoding="utf-8")).get(big, 0)))
    except Exception:
        pass
    return t


def _mark_down(big, when):
    _REMOTE_DOWN[big] = when
    try:
        d = json.loads(_DOWN_FILE.read_text(encoding="utf-8")) if _DOWN_FILE.exists() else {}
        d[big] = when
        _DOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DOWN_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def _remote_for(url, has_images):
    """(url, model) of the big text server when Settings -> AI tools sends ALL the AI's writing there
    (ollama.design_scope "text"), else None. Pictures (vision checks) always stay on the main Ollama."""
    if has_images:
        return None
    try:
        import settings as S
        o = S.load_settings()["ollama"]
    except Exception:
        return None
    big = "" if o.get("big_server") is False else str(o.get("design_url") or "").strip()
    if not big or o.get("design_scope") != "text" or url.rstrip("/") != str(o.get("url", "")).rstrip("/"):
        return None
    if time.time() - _down_since(big) < REMOTE_RETRY:
        return None
    model = big_server_model(big, o.get("design_model"))
    if not model:
        _mark_down(big, time.time())
        print(f"[ai] big text server {big} isn't answering (or has no model) - using this PC's Ollama "
              f"for the next {REMOTE_RETRY // 60} min")
        return None
    return big, model


_BIG_MODEL = {}            # big server -> (when asked, the model it uses)
REMOTE_CHECK = 60


def big_server_model(big, wanted=None):
    """The model to use on the big server, whatever it has right now (the user, 2026-11-28: "he swaps models a
    lot"): the model named in Settings only if the server still has it, else the one loaded in its memory
    (/api/ps - it answers fastest), else its newest. None = not answering / no models (-> this PC's Ollama).
    A 4-second look, kept REMOTE_CHECK seconds: when the server was off, every call used to wait 5 minutes first."""
    wanted = str(wanted or "").strip()
    hit = _BIG_MODEL.get(big)
    if hit and time.time() - hit[0] < REMOTE_CHECK and (not wanted or hit[1] == wanted or hit[2]):
        return hit[1]
    try:
        tags = _req(big, "/api/tags", timeout=4).get("models", [])
    except Exception:
        return None
    names = [m.get("name") for m in tags if m.get("name")]
    if not names:
        return None
    if wanted and wanted in names:
        model, auto = wanted, False
    else:
        try:
            loaded = [m.get("name") for m in _req(big, "/api/ps", timeout=4).get("models", []) if m.get("name")]
        except Exception:
            loaded = []
        newest = max(tags, key=lambda m: str(m.get("modified_at") or ""), default={}).get("name") or names[0]
        model, auto = next((n for n in loaded if n in names), newest), True
        if wanted:
            print(f"[ai] the big server has no {wanted} any more - using what it has: {model}")
    _BIG_MODEL[big] = (time.time(), model, auto)
    return model


def _chat_once(url, payload, timeout=300):
    try:
        return _req(url, "/api/chat", payload, timeout=timeout)
    except urllib.error.HTTPError as exc:      # older Ollama / non-thinking models may reject "think"
        if exc.code != 400 or "think" not in payload:
            raise
        payload = {k: v for k, v in payload.items() if k != "think"}
        return _req(url, "/api/chat", payload, timeout=timeout)


OPENROUTER = "https://openrouter.ai/api/v1"
OR_TIMEOUT = 120           # seconds an OpenRouter answer may take before this PC's Ollama does it instead
OR_RETRY = 300             # after a failure (no credit, rate limit, down) OpenRouter is left alone this long
OR_HEADERS = {"X-Title": "Low Poly Studio"}     # shown on openrouter.ai's activity page; nothing about the user


import contextlib
import contextvars

_JOB = contextvars.ContextVar("ai_job", default="text")
JOBS = ("text", "vision", "design")      # writing / picture checks / 3D prop design (Settings -> AI tools)


@contextlib.contextmanager
def job(kind):
    """Calls inside count as this kind of AI job (propgen.design_call: "design") for the local / cloud choice."""
    tok = _JOB.set(kind)
    try:
        yield
    finally:
        _JOB.reset(tok)


class LocalOff(ConnectionError):
    """Local AI is switched off in Settings (an OSError, so callers treat it like Ollama being offline)."""


def ai_cfg():
    try:
        import settings as S
        c = S.load_settings()
    except Exception:
        return {"local": True, "cloud": False}, {}
    return c.get("ai") or {}, c.get("openrouter") or {}


def local_on():
    return (ai_cfg()[0]).get("local", True) is not False


def cloud_model(kind, o):
    """The OpenRouter model for a job: its own pick, else (3D design) the writing model."""
    m = str(o.get(f"{kind}_model" if kind != "text" else "model") or "").strip()
    return m or (str(o.get("model") or "").strip() if kind == "design" else "")


def _openrouter_for(kind):
    """(key, model) when cloud AI is on (Settings -> AI tools), it does this job, has a key and a model, and that
    model hasn't just failed; else None (local AI does it, as before)."""
    a, o = ai_cfg()
    key = str(o.get("key") or "").strip()
    model = cloud_model(kind, o)
    if not (a.get("cloud") and key and o.get(kind) and model):
        return None
    if time.time() - _down_since("openrouter:" + model) < OR_RETRY:
        return None
    if over_limit(o):
        _note_capped(o)
        return None
    return key, model


# ---- today's cloud spending (Settings -> AI tools -> "Most to spend a day"): every job is its own process, so the
# running total lives in a file; the cap switches the cloud off until midnight and local AI does the work
SPEND_FILE = Path(__file__).resolve().parent.parent / "build" / "cloud_spend.json"
_CAPPED_SAID = []


def spend_today():
    """{"day", "spent" (dollars), "calls", "estimated" (calls whose cost OpenRouter didn't report)} for today."""
    today = time.strftime("%Y-%m-%d")
    try:
        d = json.loads(SPEND_FILE.read_text(encoding="utf-8"))
        if d.get("day") == today:
            return d
    except Exception:
        pass
    return {"day": today, "spent": 0.0, "calls": 0, "estimated": 0}


def add_spend(cost, estimated=False):
    d = spend_today()
    d["spent"] = round(float(d.get("spent") or 0) + max(0.0, float(cost or 0)), 6)
    d["calls"] = int(d.get("calls") or 0) + 1
    d["estimated"] = int(d.get("estimated") or 0) + (1 if estimated else 0)
    try:
        SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SPEND_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, SPEND_FILE)
    except Exception:
        pass
    return d


def daily_limit(o):
    try:
        return max(0.0, float(o.get("daily_limit") or 0))
    except (TypeError, ValueError):
        return 0.0


def over_limit(o):
    lim = daily_limit(o)
    return lim > 0 and float(spend_today().get("spent") or 0) >= lim


def _note_capped(o):
    if not _CAPPED_SAID:
        _CAPPED_SAID.append(1)
        print(f"[ai] today's cloud AI limit (${daily_limit(o):.2f}) is reached - "
              + ("local AI does the work until midnight" if local_on() else "local AI is off, so no AI until midnight"))


_PRICES = {}


def _price(model):
    """(dollars per prompt token, per completion token) from OpenRouter's public model list - only when a call's own
    cost wasn't reported. Fetched once per process; None when unknown."""
    if not _PRICES:
        try:
            req = urllib.request.Request(OPENROUTER + "/models", headers={"User-Agent": "LowPolyStudio"})
            with urllib.request.urlopen(req, timeout=20) as r:
                for m in json.loads(r.read().decode("utf-8")).get("data") or []:
                    pr = m.get("pricing") or {}
                    _PRICES[m.get("id")] = (float(pr.get("prompt") or 0), float(pr.get("completion") or 0))
        except Exception:
            _PRICES["?"] = None
    return _PRICES.get(model)


def call_cost(r, model):
    """(dollars, estimated?) of one OpenRouter answer: its reported usage cost, else tokens x the model's price."""
    u = r.get("usage") or {}
    if isinstance(u.get("cost"), (int, float)):
        return float(u["cost"]), False
    p = _price(model)
    if p:
        return p[0] * float(u.get("prompt_tokens") or 0) + p[1] * float(u.get("completion_tokens") or 0), True
    return 0.0, True


def _image_url(b64):
    mime = "image/jpeg" if b64.startswith("/9j/") else "image/webp" if b64.startswith("UklGR") else "image/png"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def openrouter_payload(payload, model):
    """An Ollama /api/chat payload -> OpenRouter's (OpenAI-style) chat request: pictures become data: URLs."""
    msgs = []
    for m in payload.get("messages") or []:
        imgs = m.get("images") or []
        content = ([{"type": "text", "text": m.get("content", "")}] + [_image_url(b) for b in imgs]) if imgs \
            else m.get("content", "")
        msgs.append({"role": m.get("role", "user"), "content": content})
    out = {"model": model, "messages": msgs, "stream": False, "usage": {"include": True},   # = its cost in the answer
           "temperature": float((payload.get("options") or {}).get("temperature", 0.8))}
    if payload.get("format") == "json":
        out["response_format"] = {"type": "json_object"}
    return out


def _or_post(key, body, timeout=OR_TIMEOUT):
    req = urllib.request.Request(OPENROUTER + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          **OR_HEADERS})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def openrouter_chat(key, model, payload):
    """Ask OpenRouter; answers in Ollama's shape ({"message": {"content": ...}}) so every caller stays the same."""
    body = openrouter_payload(payload, model)
    try:
        r = _or_post(key, body)
    except urllib.error.HTTPError as exc:          # a model without JSON mode: ask again without it
        if exc.code != 400 or "response_format" not in body:
            raise
        r = _or_post(key, {k: v for k, v in body.items() if k != "response_format"})
    if r.get("error"):
        raise ValueError(str((r["error"] or {}).get("message") or r["error"])[:200])
    cost, est = call_cost(r, model)
    add_spend(cost, est)                           # counted even when the answer turns out empty: it was paid for
    choice = (r.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise ValueError(f"empty answer ({choice.get('finish_reason') or 'no reason given'})")
    return {"message": {"content": text}}


def _or_why(exc):
    if isinstance(exc, urllib.error.HTTPError):
        why = {401: "the key isn't valid", 402: "out of credit (top up on openrouter.ai)",
               403: "the key isn't allowed to use this model", 404: "no such model",
               429: "rate limit reached"}.get(exc.code)
        if why:
            return why
    return f"{exc.__class__.__name__}: {str(exc)[:80]}"


def _chat(url, payload, has_images=False):
    """Every AI call, traced for the 🔎 Logs page: what was sent (pictures saved), who answered, the answer, how long."""
    import sys
    t0 = time.time()
    caller = ""
    try:      # the function that asked (generate_script, design_set, look_score...) - skip llm's own helpers
        fr = sys._getframe(1)
        for _ in range(6):
            if fr is None:
                break
            if fr.f_code.co_name not in ("chat", "chat_json", "_chat", "<lambda>", "design_call", "_ask"):
                caller = f"{Path(fr.f_code.co_filename).stem}.{fr.f_code.co_name}"
                break
            fr = fr.f_back
    except Exception:
        pass
    _ROUTE.set(None)
    try:
        r = _chat_routed(url, payload, has_images)
    except Exception as exc:
        _trace_ai(payload, caller, has_images, t0, error=f"{exc.__class__.__name__}: {exc}")
        raise
    _trace_ai(payload, caller, has_images, t0, answer=(r.get("message") or {}).get("content", ""), usage=r.get("usage"))
    return r


_ROUTE = contextvars.ContextVar("ai_route", default=None)


def _trace_ai(payload, caller, has_images, t0, answer=None, error=None, usage=None):
    try:
        import studiotrace
        route = _ROUTE.get() or {}
        msgs = studiotrace.messages_for(payload)
        user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
        head = re.sub(r"\s+", " ", str(user))[:80]
        studiotrace.event(
            "ai", f"{caller or 'AI'}: {head}", caller=caller, job_kind="vision" if has_images else _JOB.get(),
            model=route.get("model") or payload.get("model"), where=route.get("where") or "this PC's Ollama",
            fell_back=route.get("fell_back"), seconds=round(time.time() - t0, 1),
            options=payload.get("options"), format=payload.get("format"), messages=msgs, answer=answer,
            error=error, cost=(usage or {}).get("cost") if isinstance(usage, dict) else None)
    except Exception:
        pass


def _note_route(where, model, fell_back=None):
    _ROUTE.set({"where": where, "model": model, "fell_back": fell_back})


def _chat_routed(url, payload, has_images=False):
    """POST /api/chat - on OpenRouter when Settings -> AI tools sends this kind of call there, else on the big text
    server when it's set up for all writing; whatever fails falls back to `url` (this PC's Ollama, or the big server
    for 3D design) with the caller's own model, so a video never stops because an online service didn't answer."""
    kind = "vision" if has_images else _JOB.get()
    orr = _openrouter_for(kind)
    why = ""
    if orr:
        try:
            _note_route("cloud (OpenRouter)", orr[1])
            return openrouter_chat(orr[0], orr[1], payload)
        except (OSError, TimeoutError, ValueError) as exc:
            _mark_down("openrouter:" + orr[1], time.time())
            why = _or_why(exc)
            print(f"[ai] cloud AI ({orr[1]}) failed - {why} - "
                  + (f"using local AI for the next {OR_RETRY // 60} min" if local_on() else "local AI is off"))
    if not local_on():
        capped = ai_cfg()[0].get("cloud") and over_limit(ai_cfg()[1])
        raise LocalOff(f"cloud AI failed ({why}) and local AI is switched off (Settings -> AI tools)" if why else
                       "today's cloud AI limit is reached and local AI is switched off (Settings -> AI tools)" if capped
                       else "local AI is switched off and cloud AI isn't set up for this job (Settings -> AI tools)")
    fell = f"cloud AI ({orr[1]}) failed: {why}" if why else None
    rem = _remote_for(url, has_images)
    if rem:
        p = dict(payload, model=rem[1]) if rem[1] else payload
        try:
            _note_route(f"big server {rem[0]}", p.get("model"), fell)
            return _chat_once(rem[0], p, timeout=REMOTE_TIMEOUT)
        except (OSError, TimeoutError, ValueError) as exc:     # unreachable, no such model, bad answer, too slow
            slow = isinstance(exc, TimeoutError) or "timed out" in str(exc)
            # too slow (a busy 80B model): skip it for longer - every call waited the full time before
            _mark_down(rem[0], time.time() + (REMOTE_SLOW_SKIP - REMOTE_RETRY if slow else 0))
            print(f"[ai] big text server {rem[0]} failed ({exc.__class__.__name__}: {str(exc)[:80]}) - "
                  f"using {url} for the next {(REMOTE_SLOW_SKIP if slow else REMOTE_RETRY) // 60} min")
            fell = f"big server failed: {exc.__class__.__name__}: {str(exc)[:120]}"
    _note_route("this PC's Ollama" if "127.0.0.1" in url or "localhost" in url else url, payload.get("model"), fell)
    return _chat_once(url, payload)


REMOTE_TIMEOUT = 120       # seconds a big-server answer may take before this PC's Ollama does it instead
REMOTE_SLOW_SKIP = 1800    # after a too-slow answer the big server is left alone this long


def chat(url, model, system, user, temperature=0.8):
    payload = {"model": model, "stream": False, "think": False,
               "options": {"temperature": float(temperature)},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = _chat(url, payload)
    text = r.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def chat_json(url, model, system, user, temperature=0.9, images=None):
    """Like chat() but asks Ollama for strict JSON and parses it. images: base64 pictures for a vision model."""
    msg = {"role": "user", "content": user}
    if images:
        msg["images"] = images
    payload = {"model": model, "stream": False, "think": False, "format": "json",
               "options": {"temperature": float(temperature)},
               "messages": [{"role": "system", "content": system}, msg]}
    r = _chat(url, payload, has_images=bool(images))
    text = re.sub(r"<think>.*?</think>", "", r.get("message", {}).get("content", ""), flags=re.S).strip()
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0) if m else text)
    if isinstance(data, list):                 # some models wrap the object in a list
        data = next((d for d in data if isinstance(d, dict)), None)
    if not isinstance(data, dict):             # every caller expects an object: say so instead of crashing later
        raise ValueError(f"the model answered with {type(data).__name__}, not a JSON object")
    return data


# what each ground looks like: its default colour, and the climates it can belong to
GROUND = {
    "snow": ("#e8f4fc", {"cold"}), "sand": ("#e6c87a", {"hot", "coast"}), "grass": ("#6fb04a", {"temperate", "wet", "cold"}),
    "dirt": ("#8b6b43", {"hot", "temperate", "dry"}), "road": ("#4a4a50", {"temperate", "hot", "cold", "wet"}),
    "stone": ("#8a8a8a", {"cold", "temperate", "hot", "dry"}),
}
CLIMATE_PARTICLES = {"snow": {"cold"}, "dust": {"hot", "dry"}, "leaves": {"temperate", "cold"},
                     "petals": {"temperate"}, "bubbles": {"underwater"}, "stars": {"space"}}


def make_coherent(plan):
    """Make a plan make sense: the ground matches the climate, its colour matches its type, and weather effects
    (snow, dust, leaves...) only appear where they can. Changes are logged in plan['_fixes']."""
    fixes = []
    climate = str(plan.get("climate") or "").lower()
    outside = plan.get("where") == "outside" or (plan.get("where") is None and not plan.get("indoor"))
    floor = str(plan.get("floor") or "")
    if outside and climate and floor in GROUND and climate not in GROUND[floor][1]:
        fallback = next((g for g, (_, ok) in GROUND.items() if climate in ok), "grass")
        fixes.append(f"floor {floor} -> {fallback} (climate {climate})")
        floor = fallback
        plan["floor"] = floor
    if outside and floor in GROUND:
        colours = dict(plan.get("colors") or {})
        colours["floor"] = colours["floor2"] = GROUND[floor][0]
        plan["colors"] = colours
    if not outside:                                  # weather doesn't happen indoors (snow fell in a post office)
        weather = {"snow", "rain", "droplets", "leaves", "petals"}
        gone = [p for p in plan.get("particles") or [] if isinstance(p, str) and p in weather]
        if gone:
            plan["particles"] = [p for p in plan.get("particles") or [] if p not in gone]
            fixes.append(f"removed {', '.join(gone)} (indoors)")
    if climate:
        keep = []
        for p in plan.get("particles") or []:
            if not isinstance(p, str):               # the model sometimes writes an object here: ignore it
                continue
            allowed = CLIMATE_PARTICLES.get(p)
            if allowed is None or climate in allowed:
                keep.append(p)
            else:
                fixes.append(f"removed {p} particles ({climate})")
        plan["particles"] = keep
    plan["_fixes"] = fixes
    return plan


def make_theme(url, model, idea):
    """Write a new theme for a place: the props that belong there, where they go, the ground and colours. It is
    checked against what the layout can build, saved to sets/themes/ and returned (its id is in theme['id'])."""
    import setgen
    import re as _re
    zones = ["wall_back", "wall_left", "corner", "hang_back", "hang_left", "center", "scatter", "grid", "near", "far"]
    outside = not any(w in idea.lower() for w in ("inside", "room", "kitchen", "cafe", "bedroom", "office", "school", "shop", "hall"))
    floors = setgen.FLOORS_OUT if outside else setgen.FLOORS_IN
    system = (
        "You design the theme of a small low-poly 3D place (N64 style) for a short video: which objects belong there and "
        "where they stand. Only things that really belong in that place. Reply with JSON only:\n"
        '{"name": "2-3 word name", "description": "one sentence", "indoor": true or false, "room": "small|medium|large" '
        '(indoor only), "floor": one of ' + ", ".join(floors) + ', '
        '"palette": {"floor": ["#rrggbb", "#rrggbb"], "wall": "#rrggbb", "trim": "#rrggbb", "accent": "#rrggbb", '
        '"fog": "#rrggbb"}, "light": "day|sunset|night", '
        '"props": [{"kind": "...", "count": [min, max], "zone": "..."}], "marks": ["short", "walk to places"]}\n'
        f"kind must be one of: {', '.join(sorted(setgen.PROPS))}.\n"
        f"zone: where it stands - {', '.join(zones)}. Walls for wall things (wall_back, wall_left), hang_* for things on "
        "the wall at window height, corner for plants and lamps, center for tables and rugs, scatter for small things "
        "on the ground, far for big things in the background (trees, hills), near for benches and lamps by the path.\n"
        "Use 5 to 9 kinds, the basics of that place first. Never put a thing where it can't be: no snow in a desert, no "
        "sand in a snowy place, no fridge outdoors."
    )
    user = f"Place: {idea}\nWrite the theme for exactly this place."
    t = chat_json(url, model, system, user, 0.5)
    kinds = [p for p in (t.get("props") or []) if isinstance(p, dict) and str(p.get("kind")) in setgen.PROPS]
    if not kinds:
        raise ValueError("the AI couldn't make a theme from that place - try describing it differently")
    props = []
    for p in kinds[:9]:
        c = p.get("count") or [1, 2]
        try:                                   # [min, max], a single number, or junk from the model
            lo, hi = (int(c[0]), int(c[-1])) if isinstance(c, list) and c else (1, int(c))
        except (TypeError, ValueError):
            lo, hi = 1, 2
        zone = str(p.get("zone") or "scatter")
        props.append([str(p["kind"]), max(1, lo), max(max(1, lo), hi), zone if zone in zones else "scatter"])
    name = str(t.get("name") or idea)[:40]
    tid = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "generated_theme"
    tid = f"gen_{tid}"
    indoor = bool(t.get("indoor")) and not outside
    pal = t.get("palette") or {}
    floor = str(t.get("floor") or "")
    if floor not in floors:
        floor = floors[0]
    theme = {"id": tid, "names": ([name], [name]), "indoor": indoor, "room": (t.get("room") or "medium") if indoor else None,
             "description": str(t.get("description") or idea)[:200],
             "palettes": [{"floor": pal.get("floor") or ["#c8b48a", "#a89070"], "wall": pal.get("wall", "#eeeeee"),
                           "trim": pal.get("trim", "#999999"), "accent": pal.get("accent", "#ff8fb8"),
                           "fog": pal.get("fog", "#cfe9ff")}],
             "floor": floor, "props": props,
             "marks": [str(m) for m in (t.get("marks") or ["center"])][:6], "light": t.get("light") or "day",
             "textures": {}, "generated": True, "idea": idea}
    setgen.THEME_DIR.mkdir(parents=True, exist_ok=True)
    (setgen.THEME_DIR / f"{tid}.json").write_text(json.dumps(theme, indent=1), encoding="utf-8")
    setgen.THEMES[tid] = theme
    return theme


def design_set(url, model, idea="", where=None, light=None, temperature=1.0, image=None, feedback=""):
    """Ask the model to invent a set. It may use ready-made props, props the AI made for earlier sets,
    and describe up to a few brand-new props (designed afterwards by propgen)."""
    import propgen
    import setgen
    import sfx as sfxlib
    props_in = sorted(set(setgen.INDOOR_BIG + setgen.INDOOR_SMALL))
    props_out = sorted(set(setgen.OUT_FAR + setgen.OUT_NEAR + ["building"]))
    made = [f"{k} ({(d.get('looks') or k.replace('_', ' '))[:60]})" for k, d in sorted(propgen.library().items())][-60:]
    ambs = [f"{k} ({v['label'].replace('Ambience: ', '')})" for k, v in sfxlib.all_slots().items()
            if v["kind"] == "ambience"]
    system = (
        "You design small low-poly 3D sets (N64 style) for short videos. The jokes come from the script, NOT from "
        "the set: when the user gives an idea, build a believable, ordinary version of exactly that place, the way "
        "most people would picture it. No puns, no giant food, no surreal or whimsical twists, no wordplay on the "
        "idea - unless the idea itself asks for something strange. Example: 'Eastern European kitchen' = a homely "
        "kitchen with a stove, counter, fridge, table and chairs, shelves, pots, maybe a samovar and lace curtains. "
        "Make it unmistakable - a lava pit must have lava and volcanic rocks, not a beach. Only when NO idea is "
        "given, invent one fresh, specific, surprising place. Reply with JSON only, using exactly these keys:\n"
        '{"name": "2-3 word place name", "description": "one sentence", "where": "inside" or "outside" or "air", '
        '"air_kind": "sky" or "space" or "underwater" or "core" (only when where is air), '
        '"climate": "hot" (deserts, tropics, summer) or "cold" (snow, ice, mountains in winter) or "temperate" (ordinary '
        'countryside, towns) or "wet" (swamp, rain, marsh) or "coast" (beach, sea shore) or "dry" (rocky badlands) or '
        '"underwater" or "space" or "indoor", '
        '"room": "small" (inside only: a bathroom, toilet, closet, tiny kitchen, phone booth) or "medium" (a bedroom, a '
        'normal kitchen, a classroom, a shop, an office) or "large" (a living hall, a gym, a big open room; outside: any), '
        '"light": "day" or "sunset" or "night", '
        '"colors": {"floor": "#rrggbb", "floor2": "#rrggbb", "walls": "#rrggbb", "trim": "#rrggbb", '
        '"accent": "#rrggbb", "sky": "#rrggbb"}, '
        '"floor": "planks|checker|checker_small|metal|stone" (inside) or "grass|sand|snow|road|stone|dirt" (outside), '
        '"liquid": {"type": "water|lava|slime|acid|chocolate|honey|...", "shape": "pool|river|sea", "color": "#rrggbb", '
        '"glow": true} or null, '
        '"props": [{"kind": "...", "count": 3}], '
        '"new_props": [{"name": "short_name", "looks": "shape, parts and colours in a few words", '
        '"place": "near|far|scatter|wall|corner"}], '
        '"wall_pictures": [{"kind": "poster|window|chalkboard|neon_sign|star_window", "count": 1, "prompt": "what the picture shows"}], '
        '"particles": [], "extras": [], "ambience": "...", "new_ambience": "" , '
        '"textures": {"floor": "texture idea for the floor", "walls": "wallpaper idea", "sky": "what is on the horizon"}}\n'
        f"Ready-made props INSIDE: {', '.join(props_in)}.\n"
        f"Ready-made props OUTSIDE: {', '.join(props_out)}.\n"
        + (f"Props made for earlier sets - reuse one ONLY if it clearly belongs in this place, most won't: "
           f"{'; '.join(made)}.\n" if made else "")
        + "new_props: up to 4 everyday objects this place really needs that are NOT in the lists above (for a "
        "kitchen: stove, kitchen_cabinet, cooking_pot, samovar; for a garage: car, toolbox). An artist draws each "
        "one from your words, so describe what it really looks like in plain words: material, colour, shape "
        "(e.g. 'old white enamel stove with four black burners'). Solid objects only (no smoke, mist or light). "
        "Also list them in props with a count.\n"
        "liquid: ONLY if the place really has open liquid - a lake, sea, beach, river, swamp, lava pit, swimming "
        "pool. Rooms like kitchens, bedrooms, shops, offices and classrooms have none: use null. "
        "glow=true for lava, slime, magic.\n"
        "where = air when there is no ground to stand on: skydiving or falling through the sky (air_kind sky), "
        "floating in space (space), under the sea (underwater), falling down a hole to the centre of the earth "
        "(core). Standing on the moon or a planet is outside, not air.\n"
        "particles: effects that are always in the air there, usually none - e.g. stars (space, the moon), "
        "snow (snowy places), embers (lava, fire), bubbles (under water), petals (blossom gardens), dust (desert).\n"
        "wall_pictures only exist inside. extras (outside only) may include: hills, fence.\n"
        f"ambience: one of {', '.join(ambs)}. If none of them fits, describe a new background sound in "
        "new_ambience (e.g. \"deep rumbling with slow lava bubbles\"), otherwise leave it empty.\n"
        "Use 5 to 9 different prop kinds in total, counts between 1 and 12 (trees can go up to 20). "
        "Always include the obvious basics for the place from the ready-made list first (a kitchen: counter, "
        "fridge, table, chair; a bedroom: bed, desk_pc...) and add new_props on top of them. "
        "Pick colours that fit the mood."
    )
    want = []
    if where in ("inside", "outside", "air"):
        want.append(f"It must be {where}.")
    if light in ("day", "sunset", "night"):
        want.append(f"Time of day: {light}.")
    if image:
        # a picture is the reference: copy the place it shows, closely
        import base64
        from pathlib import Path as _P
        user = ("The picture attached is the reference. Rebuild the place it shows as closely as you can: the same kind "
                "of place, its colours and light, the floor and sky/walls, and the objects you can see (use a ready-made "
                "prop when one fits, otherwise a new_props entry). COUNT what you see and use about that many: a forest "
                "has many trees (up to 20), a row of shops has several shops, one bench is one bench. Use 6 to 12 prop "
                "kinds, not 4. For every props and new_props entry also give \"side\": \"left\", \"centre\" or \"right\" "
                "- where it sits in the picture from the camera's view. Put big things that are nearer the camera in the "
                "'near' place, things far away in 'far', small things on the ground in 'scatter'. "
                + (f"The user also says: {idea}. " if idea else "") + " ".join(want))
        b64 = base64.b64encode(_P(image).read_bytes()).decode("ascii")
        return make_coherent(chat_json(url, model, system, user, 0.3, images=[b64]))
    user = (f"Idea: {idea}\nBuild this place as described - realistic and ordinary. Everything must belong together: "
            "a desert has no snow, a snowy place has no sand, the weather and ground match the place.\n" if idea
            else "Surprise me with an unusual place.\n") + " ".join(want)
    if feedback:                               # make_set's look check: what was wrong with the last try
        user += (f"\nA set built from your last design was looked at and it did NOT look like this place: {feedback}"
                 "\nDesign it again so it clearly reads as this place: the props it needs, nothing that doesn't belong.")
    return make_coherent(chat_json(url, model, system, user, min(temperature, 0.6) if idea else temperature))


def find_cast(url, model, lines, main_name="the main character", place="", temperature=0.4):
    """Read a script and say who/what else shows up and when: {"cast": {...}, "events": [...]}.
    The main character is never part of the cast; things only mentioned in passing are left out."""
    verbs = ", ".join(catalog.CAST_VERBS)
    system = (
        "You are the stage manager for a short animated video. One character, "
        f"{main_name}, speaks every line. Find other people, animals or objects that PHYSICALLY appear or arrive "
        "in the scene (not ones only talked about, remembered or imagined). Reply with JSON only:\n"
        '{"cast": {"short_name": {"type": "person" or "thing", "looks": "a few words: size, shape, colours"}}, '
        '"events": [{"line": 0, "who": "short_name", "do": "verb", "from": "left|right|back|top"}]}\n'
        f"Verbs for things: {verbs}. Verbs for people: enter, exit, appear, vanish, wave, angry, laugh, "
        "surprised, point, dance, scared, sad, jump, nod, shake_head.\n"
        "line is the 0-based line number where it happens. short_name: one lowercase word or two joined with _. "
        "A thing that smashes in uses crash_in, falls from above uses fall, flies past uses fly_by. "
        "Someone arriving uses enter first. If nobody else appears, return empty cast and events. Max 4 cast members."
    )
    user = (f"Place: {place}\n" if place else "") + "Script:\n" + "\n".join(f"{i}: {l}" for i, l in enumerate(lines))
    return chat_json(url, model, system, user, temperature)


def place_for_title(url, model, title, temperature=0.4):
    """Where should a video with this title start? -> {"place": "...", "where": "inside|outside|air"}."""
    system = ("You are the location scout for a short animated explainer video. Given its title, pick the ONE place "
              "where the video should start - the most natural, visual setting for the topic, described plainly "
              "in 2-6 words (e.g. 'What if every ant vanished?' -> 'garden with an ant hill'; 'How heavy is a "
              "cloud?' -> 'grassy hill under big clouds'; 'Why do we dream?' -> 'cozy bedroom at night'). "
              "When the title names a place, the video starts IN that place ('What if cats ran the post office?' "
              "-> 'inside a post office', not the street outside it). "
              'Reply with JSON only: {"place": "...", "where": "inside" or "outside" or "air"}. where = air only '
              "when the place has no ground (sky, space, under the sea).")
    r = chat_json(url, model, system, f"Title: {title}", temperature)
    place = str(r.get("place") or "").strip()[:80]
    where = r.get("where") if r.get("where") in ("inside", "outside", "air") else None
    return {"place": place, "where": where}


def find_scenes(url, model, lines, start_place, sets, policy="reuse", temperature=0.3):
    """Where each line happens + particle effects. sets = {id: {name, description}} the user already has.
    Returns {"scenes": [{"line", "place", "set"}], "particles": [{"line", "effect"}]}."""
    have = "; ".join(f"{k} = {v.get('name') or k}: {str(v.get('description') or '')[:70]}"
                     for k, v in list(sets.items())[:80])
    system = (
        "You are the location manager for a short animated video. Every line is one shot; the video starts in "
        f"'{start_place}'. Find the lines where the story MOVES to a different place (she jumps out of a plane "
        "-> falling through the sky; she lands on the moon -> the moon; she falls into a hole -> falling to the "
        "centre of the earth). List EVERY move, in order - a story can move several times. Only real moves, not "
        "places she just talks about. Reply with JSON only:\n"
        '{"scenes": [{"line": 2, "place": "short description of the new place", "set": "existing set id or new"}], '
        '"cutaways": [{"line": 4, "show": "what the camera shows instead of her, e.g. a plane flying past"}], '
        '"particles": [{"line": 0, "effect": "..."}]}\n'
        + (f"Existing sets you should reuse when one really fits: {have}.\n" if policy == "reuse" and have else
           "Always answer new for set.\n")
        + "cutaways: at most 2, for lines that describe a specific object or creature better shown than told "
        "(\"the plane was already 4000 metres up\" -> a plane flying past). Show exactly the thing that line names - "
        "never a comparison or a joke picture. She keeps talking over it.\n"
        + "particles: ONLY for lines where weather or a visual effect is clearly happening (rain, snow, confetti, "
        "magic sparkles, falling through the air = speed_lines). Most lines have none. effect is one of: "
        + ", ".join(catalog.PARTICLES) + "."
    )
    user = "Script:\n" + "\n".join(f"{i}: {l}" for i, l in enumerate(lines))
    return chat_json(url, model, system, user, temperature)


def _clean_lines(text, keep=(), main=(), people=True):
    """Script lines from the model's answer. "Name: ..." prefixes are dropped (the model likes to label the main
    character) unless the name is in `keep` (co-stars) or is a person the script brings in with "+name" - those
    are who says the line (autodirect turns them into the shot's speaker)."""
    keep = {k.lower() for k in keep}
    # "+ espresso_machine enter" (a space after the +) is still a +name
    text = re.sub(r"(^|[\[,]\s*)\+\s+(?=[A-Za-z])", r"\1+", text, flags=re.M)
    keep |= {w.replace("_", " ") for w in re.findall(r"\+([a-z0-9_]+)", text.lower())} | \
        set(re.findall(r"\+([a-z0-9_]+)", text.lower()))
    main = {m.lower() for m in main} | NOT_SPEAKERS
    brought = set()                     # +names seen so far
    lines = []
    # some models put the whole script on one line: a new "[directions]" after a sentence starts a new line
    text = re.sub(r"(?<=[.!?\"'])\s+(?=\[)", "\n", text)
    pending = ""                        # a bare direction line ("+mom enter, angry") waiting for the next line
    for raw in text.splitlines():
        s = raw.strip().strip('"').strip()
        s = re.sub(r'"\s*,?\s*$', "", s).strip()     # a line the model wrapped like JSON: ... nya!",
        if people:
            # "+name: words" = that person speaking; a line of only "+name verb, mood" = directions for the next
            # line (it was spoken, or half of it: ", angry"), so it goes into that line's brackets
            sm = re.match(r"^\+([a-z0-9_]+):\s*(.+)$", s, re.I)
            if sm:
                who = sm.group(1).lower()
                head = "" if f"+{who}" in pending.lower() or who in brought else f"[+{who} enter] "
                s = f"{head}{who.replace('_', ' ').title()}: {sm.group(2)}"
            elif re.fullmatch(r"\+[a-z0-9_]+(\s+[a-z_]+)*(\s*,\s*[a-z_ ]+)*\s*[.!]?", s, re.I):
                pending = (pending + ", " if pending else "") + s.rstrip(".! ")
                continue
            if pending and s:
                b = re.match(r"^\[([^\]]*)\]\s*", s)
                s = (f"[{pending}, {b.group(1)}] " + s[b.end():]) if b else f"[{pending}] {s}"
                pending = ""
            b = re.match(r"^\[([^\]]*)\]\s*", s)
            if b:
                toks = [t.strip() for t in b.group(1).split(",")]
                said = [t for t in toks if SAID_IN_BRACKETS.match(t)]
                inner = LABEL_CAST.sub("", ", ".join(t for t in toks if t and t not in said)).strip(" ,")
                s = (f"[{inner}] " if inner else "") + " ".join(said + [s[b.end():]]).strip()
        s = re.sub(r"^\*{1,2}([^*:]{1,30})(?:\*{1,2}:|:\*{1,2})\s*", r"\1: ", s)   # **Name:** / **Name**: -> Name:
        s = re.sub(r"^(\d+[.)]|[-*•]|line\s*\d+:)\s*", "", s, flags=re.I)   # numbering / bullets
        m = re.match(r"^(\[[^\]]*\]\s*)?([A-Z][\w ]{0,20}):\s+", s)
        if m and people and SPOKEN_LABEL.match(m.group(2).strip()):
            # "Number 5: ...", "Clue 2: ...", "Myth: ..." are said aloud; directions after the label go first
            rest = s[m.end():]
            dirs = re.match(r"(\[[^\]]*\]\s*)+", rest)
            if dirs:
                s = (m.group(1) or "") + dirs.group(0).strip() + " " + m.group(2).strip() + ": " + rest[dirs.end():]
            m = None
        if m:
            name = m.group(2).strip().lower()
            if name in main or not people:              # titles etc.: no speakers at all
                s = (m.group(1) or "") + s[m.end():]                         # "Catgirl: ..." -> "..."
            elif name not in keep and len(name.split()) <= 3:
                # someone else speaks: they say it themselves with their own voice (she used to read it out,
                # label stripped) - bring them in on their first line if the script didn't
                keep.add(name)
            if name in keep:
                slug = re.sub(r"[^a-z0-9]+", "_", name).strip("_")[:24]
                if slug and slug not in brought and f"+{slug}" not in s.lower():
                    head = m.group(1) or ""
                    head = (head[:1] + f"+{slug} enter, " + head[1:]) if head else f"[+{slug} enter] "
                    s = head + s[len(m.group(1) or ""):]
        brought |= set(re.findall(r"\+([a-z0-9_]+)", s.lower()))
        # *emphasis* the model writes would be read out and captioned with its stars
        s = re.sub(r"\*+([^*\n]+?)\*+", r"\1", s).replace("*", "")
        if not s or s.lower().startswith(("here", "sure", "title", "script")) or s.startswith("#"):
            continue
        lines.append(s)
    return lines


# list labels the formats (Top 5, Myth or fact, Guess what) start lines with: part of what she says, not a person
LABEL_WORDS = r"(number|no|clue|round|reason|step|tip|question|myth|fact|truth|bonus|option|choice|claim|belief)"
ORDINALS = r"(first|second|third|fourth|fifth|final|last|next|another)"
SPOKEN_LABEL = re.compile(rf"(?i)({ORDINALS}\s+)?{LABEL_WORDS}(\s+(\d+|one|two|three|four|five|a|b))?$|.*\d")
# "[+second_claim enter]": the writer brought a list label in as a person - never one
LABEL_CAST = re.compile(rf"(?i)\+({ORDINALS}_)?{LABEL_WORDS}(_(\d+|one|two|three|four|five))?(?![a-z0-9_])[^,\]]*,?\s*")
# "[medium, laugh, Myth!]": words with ! or ? in the brackets are meant to be said - out of the brackets, first
SAID_IN_BRACKETS = re.compile(r"^[A-Z][\w' ]{0,24}[!?]$")
NOT_SPEAKERS = {"narrator", "character", "main character", "host", "me", "i", "she", "you", "speaker", "voice",
                "voiceover", "voice over", "catgirl", "line", "scene", "shot", "note", "wait", "fact", "fun fact",
                "bonus", "ps", "update", "warning", "title", "script", "hook", "ending", "intro", "outro"}


# Hooks: each script is asked for one of these openings (picked at random), so the first line doesn't always
# come out as the same "Did you know..." shape. The ending rule makes the video loop back to its start.
# The style is saved on the episode ("hook_style"), so the Stats page can show which openings keep people watching.
HOOK_STYLES = {
    "number": "a surprising number or fact, stated bluntly",
    "question": "a bold question that the video then answers",
    "wait_what": "a 'wait, what?' reaction to the title",
    "myth_buster": "a confident claim most people think is wrong",
    "confession": "a small confession that sets up the twist",
}
ENDING_RULE = ("The LAST line lands the punchline and, where it fits, echoes the first line's words or idea, so the "
               "video loops back to its start when people replay it.")


def pick_hook_style(rng=random):
    """One hook style id (HOOK_STYLES), at random."""
    return rng.choice(list(HOOK_STYLES))


def hook_rule(style):
    """The hook sentence for one script, for a style id (an unknown id = "number")."""
    return f"Open this one with {HOOK_STYLES.get(style) or HOOK_STYLES['number']}."


def pick_brainrot_words(bank, n=3, rng=random):
    """The words a brain rot video uses: n random ones from the bank (Settings -> Brain rot mode)."""
    bank = [str(w).strip() for w in (bank or []) if str(w).strip()]
    return rng.sample(bank, min(max(1, int(n)), len(bank))) if bank else []


def brainrot_rule(words):
    """The writer's brain rot style: short chaotic lines, a story that jumps about, and the chosen words."""
    # 2026-11-28: "jumps... a random tangent every few lines" gave scripts nobody could follow ("[fanum tax:
    # Lavender 20] OHIO! The sun just ate it all!") - the energy stays, the story has to hold together
    return ("BRAIN ROT STYLE: very short, high-energy lines (3-8 words), escalating fast and getting more absurd - "
            "but it is still ONE story about the title that a viewer can follow from start to end, ending on a "
            "punchline that calls back to the start. Sprinkle in these slang words, each at most once, inside the "
            "spoken words only (never in the [brackets]) and only where they fit: "
            + ", ".join(words) + ". Still family-friendly.")



# The writer's instructions (2026-11-28 review of 18 overnight videos: the old prompt listed ~15 features - cameras,
# walks, floating, ghosts, overlays, sounds, lighting... - and the small local model used them all, everywhere:
# "zero gravity" in 10 of 18 scripts, a ghost mom in a jellyfish riddle, made-up bracket words that became poses,
# and stories that never answered their title). Now the story rules come first and each feature is only explained
# when the title, the kind of video or the notes call for it (`_about`).
FLOAT_WORDS = r"float|floating|fly|flying|balloon|gravity|weightless|space|astronaut|levitat|hover|zero.?g"
GHOST_WORDS = r"ghost|haunt|spirit|memor|past self|past me|future self|eerie|spooky|creepy|shadow|phantom|afterlife"
TIME_WORDS_W = r"night|day|morning|evening|sunset|sunrise|dawn|dusk|midnight|hours?|all day|time"
OVERLAY_WORDS = r"meter|count|score|level|percent|tag|label|bubble|sticker|gadget|invent"


def _about(rx, *texts):
    return bool(re.search(rf"\b({rx})", " ".join(str(t or "") for t in texts), re.I))


def writer_system(title, tone="funny", extra="", scenes="auto", explain=False, others=None, hook_style=None):
    """The script writer's system prompt: the story rules, then only the tools this video needs."""
    acts = ", ".join(k for k in catalog.ANIMS if k not in ("sit", "fall", "float", "turn", "walk_to", "run_to",
                                                            "sneak_to", "float_up", "land", "idle")
                     and not k.startswith("x_"))[:900]
    exprs = ", ".join(catalog.EXPRESSIONS)
    parts = [
        "You write scripts for short vertical videos (Instagram Reels) starring ONE animated character who talks "
        "to the camera. Each line is one shot.",
        "THE STORY COMES FIRST:\n"
        "- Every single line is about the title. The video answers the title's question (or plays out its 'what "
        "if') step by step: the hook, then lines where each one follows from the line before - cause and effect, "
        "concrete details a curious viewer enjoys - and a punchline at the end.\n"
        "- Facts you state must be true and simple. If you're not sure, say it as her guess or imagination.\n"
        "- Nothing random: no sudden floating, flying, zero gravity, ghosts, visitors, explosions or new places "
        "unless the title is about them. One idea, followed all the way through.\n"
        "- First person, natural spoken English, max 14 words a line, family-friendly (no swearing).\n"
        "- She never describes herself in the third person or narrates what she does (\"Lavender runs over...\") - "
        "she just talks.",
        "The FIRST line is the hook - at most 8 words, a surprising claim, a bold question or a 'wait, what?' "
        "moment about the title. Never open with a greeting, her name or \"Today we...\". " + hook_rule(hook_style),
        ENDING_RULE,
        "FORMAT: output ONLY the script lines, one per line. No numbering, no names, no titles, no commentary, no "
        "stage directions in parentheses. A catchphrase or sound like \"nya\" at most twice in the whole script.",
        "Most lines need NO brackets: the camera and her moves are chosen for you. When it really helps, start a "
        "line with ONE pair of square brackets holding only words from these lists:\n"
        f"expressions: {exprs}\nactions: {acts}\n"
        "An action not in the list can be written [do:verb] (one word, a clear body action: [do:salute]). "
        "Never write camera words, never invent other bracket words, never put directions in the middle or at the "
        "end of a line.",
        "Example line: [surprised] Wait... the toast is still cold?!\n"
        "Example line: Fine. I'll do it myself!",
    ]
    t = f"{title} {extra}"
    if others or re.search(r"\+\w|\bMom\b|someone|friend|visitor|guest", t):
        parts.append(
            "Another person or a thing that really shows up: bring it on with [+name verb] at the start of that line "
            "(one lowercase word or words_joined_by_underscores: +mail_van; verbs for things: "
            + ", ".join(catalog.CAST_VERBS) + "; for people: enter, exit, appear, vanish). People speak for "
            "themselves with their own lines (Mom: You forgot your lunch!); things never speak. Only bring someone "
            "in when the story needs them.")
    else:
        parts.append("Usually she is alone. Only if the story truly needs someone or something to show up, start "
                     "that line with [+name enter] (one lowercase word); a person then says their own line as "
                     "Name: words.")
    if _about(TIME_WORDS_W, t):
        parts.append("The light can change on a line with day, sunset, night or dawn in its brackets - only when "
                     "time really passes in the story.")
    if scenes != "stay":
        parts.append("If the story really moves somewhere else, start that line with [@ place] (a short "
                     "description: [@ a busy train station]); it lasts until the next one. Never for the starting place.")
    if _about(FLOAT_WORDS, t):
        parts.append("Floating: [+balloons hold] gives her balloons, [float_up] lifts her off the ground (she stays "
                     "up), [land] brings her back down.")
    if _about(GHOST_WORDS, t, tone):
        parts.append("Someone can appear as a pale see-through ghost (a spirit, a memory, her past self) with ghost "
                     "after the verb - [+past_self appear ghost] - or as a dark silhouette with shadow.")
    if _about(OVERLAY_WORDS, t):
        parts.append("On-screen overlays, only for something the video keeps track of: [meter: <name> <0-100>] a "
                     "bar (write it again later with a new number), [count: <name> <number>], "
                     "[label: <NAME>] a name sign, [bubble: <1-3 words>].")
    if re.search(r"cutaway", t, re.I):
        parts.append("A [cutaway: thing] shows exactly the thing that line names (the volcano, the crumb) - never a "
                     "comparison or a joke picture.")
    if explain:
        parts.append(
            "Explaining how something works? Bring a model of it on beside her with [show: thing] (one word), "
            "[show: thing open] when you talk about its inside, [show: thing part] for a close look at one part, "
            "[show: off] when done. Name each part and say what it does in plain words - the model's parts move on "
            "those words.")
    return "\n".join(x for x in parts if x)



# ---- the writer's slips, cleaned before anyone sees them (2026-11-28 review of 18 overnight scripts):
# "[closet, excited]", "[hight, float_up]" (typos), "[sweat_drip]", "[noodle_eat]", "[fanum tax: Lavender 20]",
# "[cleanup: zoom_in]" (made-up bracket words - the animation maker turned them into poses), "+captain crash_in hot!
# The driver yelled", "do:facepalm!", "Sneak to [front]," (directions in the spoken words), 'Huss," my hair...'
# (stray quotes), "...the smug pigeon claims." (narration), "Lavender zooms over to the nurse's station!" (her, in
# the third person), "[day, +lamp_crash_in]" with no words at all.
KEYED = {"cutaway", "cut", "show", "meter", "count", "tag", "label", "bubble", "sticker", "fire", "do"}
PLACEHOLDER = re.compile(r"^<?\s*(?:the |a |an )?(?:thing|things|entry|answer|object|item|it|<.*>|\.\.\.)\s*>?$")
SAY_TAIL = re.compile(r",?\s*(?:the|a|an|his|her)\s+[\w' ]{0,24}?\s+(?:claims?|says?|said|yells?|yelled|shouts?|"
                      r"shouted|whispers?|whispered|asks?|asked|replies|replied)\s*[.!]?\s*$", re.I)
SPOKEN_DIRECTIONS = re.compile(
    r"\+[a-z][a-z0-9_]*(?:\s+(?:enter|exit|appear|vanish|crash_in|fall|fly_by|bounce|spin|shake|hold|run_in|"
    r"walk_in|float_up|[a-z]+_(?:in|out|by|to)))?|\b(?:do:\w+|crash_in|fly_by|from_left|from_right|from_back|"
    r"walk_to|run_to|sneak_to|float_up)\b|\b(?:walk|run|sneak)\s+to\s+\[[^\]]*\]|\[[^\]]*\]", re.I)


def _bracket_ok(tok, vocab):
    t = tok.strip()
    low = t.lower()
    if not t:
        return None
    if t.startswith("+"):
        # "+lamp_crash_in": the verb glued onto the name
        g = re.match(r"^\+([a-z0-9_]+?)_(crash_in|enter|exit|appear|vanish|fall|fly_by|bounce|spin|shake|hold)$", low)
        return f"+{g.group(1)} {g.group(2)}" if g else t
    if t.startswith("@"):
        return t
    k = re.match(r"^([a-z_]+)\s*:\s*(.*)$", low)
    if k:
        if k.group(1) in ("cutaway", "cut") and PLACEHOLDER.match(k.group(2).strip()):
            return None                    # "[cutaway: the thing]" - the template's placeholder, copied as is
        if k.group(1) == "do" and k.group(2).strip().replace(" ", "_") in vocab:
            return vocab[k.group(2).strip().replace(" ", "_")]    # "[do:point]" = the action she already has
        return t if k.group(1) in KEYED else None
    w = re.sub(r"\s+", "_", low)
    if w in vocab:
        return vocab[w]
    import difflib
    near = difflib.get_close_matches(w, list(catalog.CAMERAS), n=1, cutoff=0.75)   # closet, hight, closed
    return near[0] if near else None


def tidy_writer_lines(lines, character=None):
    """The AI writer's lines, tidied: only known words in the brackets (typos of camera names mapped), directions
    taken out of the spoken words (+name verb into the brackets), stray quotes, "the X says" tails, empty lines and
    lines that narrate her in the third person dropped. Returns (lines, how many lines needed fixing or went)."""
    try:
        import autodirect as AD
        extra = {**AD.CAM_WORDS, **AD.MOVE_WORDS, **AD.MOOD_WORDS, **AD.ANIM_WORDS}
    except Exception:
        extra = {}
    vocab = {k: k for k in list(catalog.CAMERAS) + list(catalog.ANIMS) + list(catalog.EXPRESSIONS) + list(catalog.LIGHTS)
             + list(catalog.PARTICLES) + list(catalog.MOVES) + list(catalog.CAST_VERBS)}
    vocab.update({k: v for k, v in {**catalog.LIGHT_ALIASES, **catalog.PARTICLE_ALIASES, **extra}.items()
                  if isinstance(v, str)})
    name = str((character or {}).get("name") or "").strip()
    third = re.compile(rf"^(?:{re.escape(name)}|the catgirl|our catgirl|she)\s+[a-z]+s\b", re.I) if name else \
        re.compile(r"^(?:the catgirl|our catgirl)\s+[a-z]+s\b", re.I)
    out, bad, carry = [], 0, []
    for raw in lines:
        line = raw.strip()
        heads = []
        while True:                                       # every leading bracket group
            m = re.match(r"^\[([^\]]*)\]\s*", line)
            if not m:
                break
            heads += [x for x in m.group(1).split(",")]
            line = line[m.end():]
        label = ""
        lm = re.match(r"^(\+?[A-Za-z][\w ]{0,30}):\s+", line)
        if lm:
            label, line = lm.group(1), line[lm.end():]
            pm = re.match(r"^\+([a-z0-9_]+)(?:\s+([a-z_]+))?$", label.strip(), re.I)
            if pm:                                       # "+scientist bow: You look..." -> brought in, then speaks
                heads.append(f"+{pm.group(1).lower()} {pm.group(2) or 'enter'}")
                label = pm.group(1).replace("_", " ").title()
        text = line
        moved = [mm.group(0).strip() for mm in SPOKEN_DIRECTIONS.finditer(text) if mm.group(0).startswith("+")]
        text2 = SPOKEN_DIRECTIONS.sub(" ", text)
        text2 = SAY_TAIL.sub("", text2)
        if text2.count('"') % 2:
            text2 = text2.replace('"', "")
        text2 = re.sub(r"\s+([,.!?])", r"\1", re.sub(r"\s{2,}", " ", text2)).strip(" ,;:")
        text2 = re.sub(r"^[,.;:!?]+\s*", "", text2)
        kept = [k for k in (_bracket_ok(h, vocab) for h in heads + moved) if k]
        changed = text2 != text.strip() or len(kept) != len([h for h in heads if h.strip()]) + len(moved)
        if third.match(text2):
            bad += 1
            continue
        if not re.search(r"[A-Za-z]{2}", text2):          # nothing left to say: its +cast goes to the next line
            carry += [k for k in kept if k.startswith(("+", "@"))]
            bad += 1
            continue
        kept = carry + kept
        carry = []
        seen, uniq = set(), []
        for k in kept:
            if k.lower() not in seen:
                seen.add(k.lower())
                uniq.append(k)
        head = f"[{', '.join(uniq)}] " if uniq else ""
        out.append(head + (f"{label}: " if label else "") + text2)
        bad += 1 if changed else 0
    return out, bad


def generate_script(url, model, title, character, set_info, lines=6, tone="funny", extra="", temperature=0.85,
                    others=None, polish=True, scenes="auto", explain=False, brainrot=None, hook_style=None,
                    _retry=False):
    """others: the other main characters in the video, [{"name", "about"}] - they get some lines too.
    scenes: "stay" (one place), "move" (the story travels: 1-3 [@ place] changes) or "auto" (only when it moves).
    brainrot: the words to use (pick_brainrot_words) - the brain rot style is added to the writer's extra notes.
    hook_style: a HOOK_STYLES id (the caller records it on the episode); None = one at random."""
    if hook_style not in HOOK_STYLES:
        hook_style = pick_hook_style()
    if brainrot:
        extra = (extra + " " + brainrot_rule(brainrot)).strip()
    others = [o for o in (others or []) if isinstance(o, dict) and o.get("name")]
    system = writer_system(title, tone, extra, scenes, explain, others, hook_style)
    user = (
        f"Video title: {title}\n"
        f"Character: {character.get('name', 'the character')}. {character.get('about', '')}\n"
        + name_rule(character) + "\n"
        + ("Other main characters in this video (they talk too - give each of them a few lines, reacting to and "
           "talking with the main character). Start each of their lines with EXACTLY the name shown here and a "
           "colon, even if the description calls them something else:\n"
           + "".join(f"- {o['name']} (write \"{o['name']}: ...\"): {str(o.get('about') or '')[:300]}\n"
                     for o in others) if others else "")
        + "Put every line on its own line.\n"
        + f"Location: {set_info.get('name', '')} - {set_info.get('description', '')}\n"
        f"Tone: {tone}. Number of lines: {int(lines)}.\n"
        + {"stay": "Keep the whole video in this one location - no [@ ...] scene changes.\n",
           "move": "The story travels: move to 1 to 3 other places along the way, each marked with [@ place].\n"}
          .get(scenes, "Only use [@ place] if the story really goes somewhere else.\n")
        + (f"Extra notes: {extra}\n" if extra else "")
        + "Write the script now."
    )
    text = chat(url, model, system, user, temperature)
    alias = {a.lower(): o["name"] for o in others for a in (o.get("aliases") or []) + [o["name"]]}
    out = []
    main_names = [str(character.get("name") or ""), str(character.get("id") or "")]
    for line in _clean_lines(text, keep=list(alias), main=[n for n in main_names if n]):
        # "[cameras: macro, happy]", "[action: shrug]": the prompt's list labels copied into the brackets (the
        # director would try to animate "cameras: macro")
        line = re.sub(r"(?<=[\[,])\s*(?:cameras?|actions?|expressions?|moods?|emotions?)\s*:\s*", " ", line, flags=re.I)
        m = re.match(r"^(\[[^\]]*\]\s*)?([^:\[\]]{1,31}):\s+", line)     # "Ethan: ..." -> the co-star's own name
        if m and m.group(2).strip().lower() in alias:
            line = (m.group(1) or "") + alias[m.group(2).strip().lower()] + ": " + line[m.end():]
        out.append(line)
    out = out[: int(lines) + 2 + len(others) * 2]
    if not out:
        raise RuntimeError("The model returned no usable lines - try again or pick another model.")
    if polish:
        out = polish_script(url, model, title, out, tone)
    out, bad = tidy_writer_lines(out, character)
    if (bad > max(2, len(out) // 3) or len(out) < max(3, int(lines) - 3)) and not _retry:
        # a mess (many lines fixed or dropped): write it once more, a little calmer, and keep the tidier one
        print(f"  [writer] {bad} line(s) needed fixing, {len(out)} left - writing it again")
        try:
            again = generate_script(url, model, title, character, set_info, lines, tone, extra, max(0.5, temperature - 0.2),
                                    others, polish, scenes, explain, None, hook_style, _retry=True)
            if again and len(again) >= len(out):
                return again
        except Exception as exc:
            print(f"  [writer] second try failed ({exc}) - keeping the first")
    return fix_self_names(out, character)


# her name (2026-11-27: "My name is Lila" - the writer made names up: Lila, Luna, Cat...). The Name box on the
# Characters page is the only name she uses.
def real_name(character):
    """Her name = the Name box on the Characters page (the user, 2026-11-27: "pull her name from the character box").
    Empty = she has no name and never names herself."""
    n = str((character or {}).get("name") or "").strip()
    return n if n and len(n) <= 31 else ""


def name_rule(character):
    n = real_name(character)
    return (f"Her name is {n}: if she ever says her name it is exactly \"{n}\" - never any other name."
            if n else "She has NO name: she never introduces herself or names herself (no \"I'm Luna\", no "
                      "\"my name is...\") - she just talks.")


_MY_NAME = re.compile(r"\bmy name(?:'s| is)\s+([A-Z][\w'-]+)(\s+and\s+|\s*[,.!]+\s*|\s+)", re.I)
_IM_NAME = re.compile(r"^((?:(?:hey|hi|hello|hiya|yo)\b[\s,!]*)?(?:(?:guys|everyone|friends|you)\b[\s,!]*)?)"
                      r"(?:i'm|i am)\s+([A-Z][a-z]+)\s*([!,.]+)\s*", re.I)


def fix_self_names(lines, character):
    """A name the writer invented for her ("My name is Lila and...", "Hey guys, I'm Luna!") becomes her real profile
    name, or goes when she has none. Other speakers' lines ("Mom: ...") are left alone."""
    n = real_name(character)
    out = []
    for line in lines:
        m = _LINE_HEAD.match(line)
        head, text = m.group(1), m.group(2)
        label = re.search(r"([A-Za-z][\w ]{0,30}):\s+$", head)
        if label and label.group(1).strip().lower() not in {str((character or {}).get("name") or "").lower(),
                                                            str((character or {}).get("id") or "").lower()}:
            out.append(line)                       # someone else's line
            continue

        def mine(mm):
            if n:
                return mm.group(0).replace(mm.group(1), n) if mm.group(1).lower() != n.lower() else mm.group(0)
            return " " if mm.group(2).strip() in ("and", "") else ""

        new = _MY_NAME.sub(mine, text)
        im = _IM_NAME.match(new)
        if im and im.group(2).lower() not in ("catgirl", n.lower()) and im.group(2).lower() not in _NOT_NAMES:
            greet = im.group(1).strip(" ,")
            new = (f"{greet}, I'm {n}{im.group(3)} " if n else (f"{greet}! " if greet else "")) + new[im.end():]
        new = re.sub(r"\s{2,}", " ", new).strip()
        if new and new != text:
            new = new[0].upper() + new[1:]
        out.append(head + new if new else line)
    return out


_NOT_NAMES = set("""so here back home ready done fine okay ok sorry hungry tired bored scared sure serious not just
the a an in on at stressed happy sad excited going gonna literally totally also still really very""".split())


_LINE_HEAD =re.compile(r"^\s*((?:\[[^\]]*\]\s*)?(?:[A-Za-z][\w ]{0,30}:\s+)?)(.*)$")


def polish_script(url, model, title, lines, tone="funny", temperature=0.4):
    """An editor's second pass over a script: correct, natural English, each line following from the last, the
    title's question really answered (a true fact, said simply), no joke used twice, a punchline that lands at the
    end, max 14 words a line. Only the spoken words change: every line keeps its own [directions] and "Name:" (the
    model is shown them but its copies are ignored), and the line count stays the same. Any problem -> the script
    as it was."""
    if not lines:
        return lines
    heads, texts = [], []
    for ln in lines:
        m = _LINE_HEAD.match(ln)
        heads.append(m.group(1) if m else "")
        texts.append((m.group(2) if m else ln).strip())
    system = ("You are the script editor for short, funny, family-friendly animated Reels where a character answers "
              "a curious question. First list what is wrong with the script, then rewrite the spoken lines to fix "
              "it. Check: wrong or made-up facts (the title's question must get a real, true answer, said simply - "
              "a joke can exaggerate, but the answer itself is true); broken or unnatural English and made-up words; "
              "lines that don't follow from the one before; a joke or idea used twice; a weak first line (it must be a "
              "hook of at most 8 words - a surprising claim or bold question, never a greeting or \"Today we...\"); "
              "an ending that doesn't land "
              "(the last line is a punchline); more than 14 words in a line; swearing; the main character telling "
              "what someone else says (\"Mom says...\") instead of letting them say it, or talking about someone "
              "who never appears; \"nya\" (or any catchphrase) more than twice. Keep the same number of "
              "lines in the same order, each line keeping its job (who speaks, names and +name words exactly). "
              "Reply with JSON only: "
              '{"problems": ["..."], "lines": ["...", "..."]}')
    user = (f"Title: {title}\nTone: {tone}\nLines (the part in front of each line is the stage direction - "
            "don't write it in your answer):\n" + "\n".join(f"{i + 1}. {h}{t}" for i, (h, t) in
                                                           enumerate(zip(heads, texts))))
    try:
        r = chat_json(url, model, system, user, temperature)
        new = r.get("lines")
    except Exception:
        return lines
    if not (isinstance(new, list) and len(new) == len(lines) and all(isinstance(x, str) and x.strip() for x in new)):
        return lines
    out = []
    for h, old, nw in zip(heads, texts, new):
        nw = re.sub(r"^\s*\d+[.)]\s*", "", nw.strip().strip('"'))
        m = _LINE_HEAD.match(nw)                   # the editor copied the direction/name anyway: drop its copy
        if m and m.group(1).strip():
            nw = m.group(2).strip()
        lost = set(re.findall(r"\+[a-z0-9_]+", old)) - set(re.findall(r"\+[a-z0-9_]+", nw))
        if not nw or len(nw.split()) > 22 or lost or "[" in nw:
            nw = old                               # too long, or it dropped someone's entrance: keep the original
        out.append(h + nw)
    return out


def translate_lines(url, model, lines, language, temperature=0.2):
    """English lines -> the same lines in `language`, in order. One request for all of them; if the model returns the
    wrong number of lines, each line is translated on its own. Raises when Ollama can't be reached."""
    system = (f"You translate the spoken lines and on-screen text of a short, funny animated video from English into "
              f"{language}. Natural, everyday spoken {language} that sounds good read aloud, same meaning, tone and "
              f"jokes, about the same length. Keep names of people and characters as they are. Write numbers the "
              f"way a {language} speaker would say them. Reply with JSON only: "
              '{"lines": ["...", "..."]} - exactly one translated line for each input line, in the same order.')
    if not lines:
        return []
    user = "Lines:\n" + json.dumps(list(lines), ensure_ascii=False)
    try:
        out = chat_json(url, model, system, user, temperature).get("lines")
    except ValueError:
        out = None
    if isinstance(out, list) and len(out) == len(lines) and all(isinstance(x, str) and x.strip() for x in out):
        return [x.strip() for x in out]
    res = []                                   # one at a time when the batch came back wrong
    for line in lines:
        o = chat_json(url, model, system, "Lines:\n" + json.dumps([line], ensure_ascii=False), temperature).get("lines")
        if not (isinstance(o, list) and o and isinstance(o[0], str) and o[0].strip()):
            raise ValueError(f"the model couldn't translate: {line[:60]}")
        res.append(o[0].strip())
    return res


TITLE_STARTS = ["What if", "How does", "Why is", "Why do", "What does", "How can", "What happens if",
                "How much", "How big", "Is it possible", "What would happen if", "How long"]
TITLE_JUNK = re.compile(r"\b(nya+|nyan|meow+|uwu|owo)\b[!?.,~]*", re.I)     # interjections only ("purr" can be a topic)


def clean_title(t):
    t = TITLE_JUNK.sub("", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)          # no emoji
    t = re.sub(r"\s{2,}", " ", t).strip(" -~,.!")
    if t and not t.endswith("?") and re.match(r"(what|how|why|is|can|does|do|would|will|when|where|who)\b", t, re.I):
        t += "?"
    return t[:1].upper() + t[1:]


def generate_titles(url, model, character, theme="", count=8, temperature=1.0, starts=None, hint=""):
    """Curiosity titles like the reference channel: plain questions about the world ("What if every ant
    vanished?", "How heavy is a cloud?"). The character presents them, so she isn't in the title, and there's no
    "nya", cat words or emoji."""
    system = ("You write titles for short educational-but-funny Reels that answer one curious question about the "
              "world (science, nature, space, the body, history, everyday things). Each title is a simple, "
              "plain-English question that makes people want to know the answer, for example:\n"
              "What if every ant on Earth vanished?\nHow heavy is a cloud?\nWhy is the sky blue?\n"
              "What does the inside of a volcano look like?\nHow can a plane stay in the air?\n"
              f"Start each title with one of: {', '.join(starts or TITLE_STARTS)} (mix them"
              + (", don't only use 'What if').\n" if not starts else ").\n")
              + (f"Each title is about {hint}.\n" if hint else "")
              + "Rules: under 10 words; no character names, no cat sounds or cat words (no 'nya', 'meow', 'purr', "
              "'catgirl'), no emoji, no hashtags, no quotes, no numbering. Output ONLY the titles, one per line.")
    user = ((f"Topic: {theme}\n" if theme else "Any topic - surprise me with things people wonder about.\n")
            + f"Give {int(count)} different titles.")
    out = []
    for t in _clean_lines(chat(url, model, system, user, temperature), people=False):
        t = clean_title(t)
        if 8 < len(t) < 90 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return rank_titles(url, model, out[: int(count)])


def series_titles(url, model, idea, count=3, starts=None, hint="", temperature=0.9):
    """Episode titles for a series about one idea: each a curious question of its own, together telling the idea
    from different angles (no "Part 1" - each video must stand alone), in a good watching order."""
    count = max(1, min(4, int(count)))
    system = ("You plan a short series of educational-but-funny Reels about ONE idea. Each episode answers its own "
              "curious question about the idea, from a different angle, so each video stands alone but together "
              "they cover the idea; order them so the first one hooks people. "
              f"Start each title with one of: {', '.join(starts or TITLE_STARTS)}. "
              + (f"Each title is about {hint}. " if hint else "")
              # "What if cats ruled the world?" became gravity / naps / silence: the titles must stay on the idea
              + "Every title must clearly be about the idea itself - keep its main subject in the title. "
              + "Rules: under 10 words; no character names, no emoji, no numbering, no 'Part 1'"
              + ("" if re.search(r"\bcats?\b|\bkitt", str(idea), re.I) else ", no cat words") + ". "
              'Reply with JSON only: {"titles": ["...", "..."]}')
    # a few extra, then the best ones by rank_titles (it scores "a real question with a real answer" - the first
    # try gave "How does your skin know when you're full?")
    r = chat_json(url, model, system, f"Idea: {idea}\nNumber of episodes: {count + 3}", temperature)
    out = []
    for t in (r.get("titles") or []):
        t = clean_title(str(t))
        if 8 < len(t) < 90 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    if not out:
        raise RuntimeError("The model returned no episode titles - try again")
    return rank_titles(url, model, out)[:count]


def rank_titles(url, model, titles):
    """The titles best first: a second look scores each one (makes you curious, clear, correct English, a real
    question with a real answer). A title with broken grammar is fixed when the fix is small. Any problem -> as
    they were."""
    if len(titles) < 2:
        return titles
    system = ("You judge titles for short educational-but-funny Reels. For each title give a score from 1 to 10: "
              "how much it makes people curious, how clear and short it is, and whether it is a real question with "
              "a real answer. Fix its English if it is wrong (keep the meaning). Reply with JSON only: "
              '{"titles": [{"title": "the title (fixed if needed)", "score": 1-10}, ...]} - same order, same number.')
    try:
        r = chat_json(url, model, system, "Titles:\n" + "\n".join(titles), 0.2).get("titles")
        if not (isinstance(r, list) and len(r) == len(titles)):
            return titles
        scored = []
        for i, (orig, x) in enumerate(zip(titles, r)):
            t = clean_title(str(x.get("title") or orig)) if isinstance(x, dict) else orig
            if not (8 < len(t) < 90) or abs(len(t) - len(orig)) > 25:
                t = orig                           # a rewrite, not a fix: keep the original
            sc = float(x.get("score") or 0) if isinstance(x, dict) else 0.0
            scored.append((-sc, i, t))
        return [t for _, _, t in sorted(scored)]
    except Exception:
        return titles



def social_copy(url, model, title, lines, temperature=0.7):
    """Caption + hashtags for a finished video. -> {"caption", "hashtags": [...], "youtube_title", "discord"}.
    The trendy discovery tags (#fyp, #shorts...) are added per platform by postiz.py; this picks topic tags."""
    script = "\n".join(lines[:16])
    system = ("You write social media copy for short animated Reels/Shorts starring a cute low-poly catgirl who "
              "answers curious questions. Reply with JSON only:\n"
              '{"caption": "1-2 short punchy sentences that hook viewers and tease the answer, may end with a '
              'question to drive comments, at most 2 emoji, no hashtags", '
              '"hashtags": ["8-10 specific hashtags about the TOPIC people actually search, e.g. #science #ants '
              '#funfacts #didyouknow #animation - lowercase, no spaces"], '
              '"youtube_title": "catchy title under 70 characters, may end with #shorts", '
              '"discord": "a friendly 1-2 sentence announcement for a Discord server, no hashtags"}\n'
              "Don't use the words nya or meow. Don't invent facts that aren't in the script.")
    user = f"Title: {title}\nScript:\n{script}"
    r = chat_json(url, model, system, user, temperature)
    tags = [t for t in (r.get("hashtags") or []) if isinstance(t, str)]
    return {"caption": TITLE_JUNK.sub("", str(r.get("caption") or "")).strip(), "hashtags": tags,
            "youtube_title": TITLE_JUNK.sub("", str(r.get("youtube_title") or "")).strip(),
            "discord": TITLE_JUNK.sub("", str(r.get("discord") or "")).strip()}
