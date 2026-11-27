"""Cloud AI (OpenRouter) for Settings -> AI tools: the model list for the pickers and a key check with the credit
used. The calls themselves are in pipeline/llm.py (_chat -> openrouter_chat). Nothing about the user is sent:
the model list is public, the key check only sends the key."""
import json
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1"
_MODELS = {"at": 0, "list": []}
MODELS_TTL = 3600


def _get(path, key=None, timeout=20):
    headers = {"User-Agent": "LowPolyStudio"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with urllib.request.urlopen(urllib.request.Request(API + path, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def per_million(price):
    """OpenRouter prices are dollars per token (as text) -> dollars per million tokens (None = unknown)."""
    try:
        return round(float(price) * 1e6, 3)
    except (TypeError, ValueError):
        return None


def trim(raw):
    """OpenRouter's /models -> what the pickers need, chat models only (no :batch copies, nothing that can't write)."""
    out = []
    for m in raw:
        mid = str(m.get("id") or "")
        arch = m.get("architecture") or {}
        if not mid or mid.endswith(":batch") or "text" not in (arch.get("output_modalities") or ["text"]):
            continue
        pr = m.get("pricing") or {}
        out.append({"id": mid, "name": m.get("name") or mid,
                    "vision": "image" in (arch.get("input_modalities") or []),
                    "free": mid.endswith(":free") or (per_million(pr.get("prompt")) == 0 and per_million(pr.get("completion")) == 0),
                    "in": per_million(pr.get("prompt")), "out": per_million(pr.get("completion")),
                    "context": m.get("context_length")})
    return sorted(out, key=lambda m: m["id"])


def models(fresh=False):
    if fresh or time.time() - _MODELS["at"] > MODELS_TTL or not _MODELS["list"]:
        _MODELS["list"] = trim(_get("/models").get("data") or [])
        _MODELS["at"] = time.time()
    return _MODELS["list"]


def check(key):
    """The key's state on OpenRouter: {ok, label, used, limit, left, free_tier} or {ok: False, error}."""
    if not key:
        return {"ok": False, "error": "no key yet - paste it and press Save"}
    try:
        d = _get("/key", key=key).get("data") or {}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "the key isn't valid" if exc.code in (401, 403) else f"OpenRouter said {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": f"can't reach OpenRouter ({exc.__class__.__name__})"}
    return {"ok": True, "label": d.get("label") or "", "used": d.get("usage"), "limit": d.get("limit"),
            "left": d.get("limit_remaining"), "free_tier": bool(d.get("is_free_tier"))}


def today(o):
    """Today's cloud spending (llm.spend_today, kept by every job) against the daily limit."""
    import llm
    d = llm.spend_today()
    lim = llm.daily_limit(o)
    return {"spent": round(float(d.get("spent") or 0), 4), "calls": d.get("calls", 0),
            "estimated": d.get("estimated", 0), "limit": lim, "capped": lim > 0 and d.get("spent", 0) >= lim}


def handle(h, method, parts):
    import settings as S
    what = parts[0] if parts else ""
    if method == "GET" and what == "models":
        try:
            return h.send_json({"ok": True, "models": models(fresh="fresh" in (h.path or ""))})
        except Exception as exc:
            return h.send_json({"ok": False, "error": f"can't reach OpenRouter ({exc.__class__.__name__})", "models": []})
    if method == "GET" and what == "check":
        o = S.load_settings().get("openrouter") or {}
        return h.send_json({**check(str(o.get("key") or "").strip()), "today": today(o)})
    return h.fail("not found", 404)
