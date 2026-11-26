"""
The weekly plan: on the day and hour set in Settings (plan.*), the studio picks fresh ideas from the Ideas page and
makes one video from each (a batch, pipeline/batch.py) - and when each render is done, a Postiz DRAFT for it, so
the week's videos are waiting as drafts (never scheduled or published).

The web server checks once every few minutes (web/server.py plan_loop); ▶ Run it now on the Ideas page runs it at
once. State (the last week it ran) in build/weekly_plan.json.
"""
import json
import random
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "build" / "weekly_plan.json"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def week_of(now):
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def due(plan, st, now=None):
    """True when the plan is on, it's the day and hour (or later that day), and it hasn't run this week."""
    now = now or datetime.now()
    if not plan.get("on"):
        return False
    day = DAYS.index(plan.get("day", "mon")) if plan.get("day", "mon") in DAYS else 0
    return now.weekday() == day and now.hour >= int(plan.get("hour", 3)) and st.get("last_week") != week_of(now)


def kind_rank():
    """Kinds of video, best first by average views on the Stats page (kinds with 2+ numbers only)."""
    try:
        import stats
        return [e["value"] for e in stats.summary()["by"].get("kind", []) if e["videos"] >= 2]
    except Exception:              # no numbers (or Stats broken): the plan keeps its plain order
        return []


def pick(db, n, rank=()):
    """n ideas: never used or hidden, starred first, then the newest - mixed kinds of video (one of each before
    a second of any). rank = kinds best first: they're taken first, so with more kinds than slots the weakest drop out."""
    pool = [it for it in db.get("ideas", []) if not it.get("hidden") and not it.get("used")]
    pool.sort(key=lambda it: (not it.get("starred"), -float(it.get("added") or it.get("time") or 0)))
    by_kind, order = {}, []
    for it in pool:
        k = it.get("template") or "what_if"
        if k not in by_kind:
            order.append(k)
        by_kind.setdefault(k, []).append(it)
    order.sort(key=lambda k: rank.index(k) if k in rank else len(rank))     # unranked kinds keep their order
    out = []
    while len(out) < n and any(by_kind.values()):
        for k in order:
            if by_kind[k] and len(out) < n:
                out.append(by_kind[k].pop(0))
    return out


def roll_brainrot(items, chance, rng=random):
    """Brain rot mode by chance (0-100 %) for videos made without you: each item gets "brainrot": True or not
    (batch.py reads it per item)."""
    chance = max(0.0, min(100.0, float(chance or 0)))
    for it in items:
        if rng.random() * 100 < chance:
            it["brainrot"] = True
    return items


def spec_for(plan, db, base, postiz_on):
    ideas = pick(db, max(1, min(10, int(plan.get("count", 5)))), kind_rank())
    items = [{k: it.get(k) for k in ("id", "topic", "angle", "template", "titles")} for it in ideas]
    return {"ideas": roll_brainrot(items, plan.get("brainrot_chance", 0)),
            "length": str(plan.get("length") or "medium"), "note": "", "model": "", "regulars": [],
            "render": True, "drafts": bool(plan.get("drafts", True)) and postiz_on,
            "weekly": datetime.now().strftime("%Y-%m-%d"), "base": base}


def mark_ran(now=None, job=None):
    now = now or datetime.now()
    st = state()
    st.update(last_week=week_of(now), last_run=time.time(), job=job)
    save_state(st)
