"""
Her room: one permanent set ("My Room", id "home") that is hers - the home base of the channel - with souvenirs that
build up over the videos: after each render one thing from that video (a cutaway's subject, something she held, or
another thing that appeared) is kept and placed along the room's walls, the newest MAX_SOUVENIRS of them.

    python pipeline/home.py make          build her room (once; a hand-built bedroom base, style A)
    python pipeline/home.py place         re-place the souvenirs (after removing one on the Sets page)
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as S  # noqa: E402

HOME_ID = "home"
IDEA = "her own cozy bedroom - the home of the channel, with a comfy bed, a desk, shelves and warm lights"
MAX_SOUVENIRS = 10
SOUVENIR_H = 0.6              # metres: big things become little keepsakes, small ones stay small
# spots in the wide shot (|x| < 0.36 * (y + 6)) along the back and side walls, front to the middle kept free
SPOTS = [(-2.3, 2.9), (2.3, 2.9), (-1.5, 3.1), (1.5, 3.1), (-2.7, 1.6), (2.7, 1.6), (-0.7, 3.2), (0.7, 3.2),
         (-2.6, 0.4), (2.6, 0.4), (-3.0, 2.4), (3.0, 2.4)]


def path():
    return ROOT / "sets" / f"{HOME_ID}.json"


def exists():
    return path().exists()


def on():
    return bool((S.load_settings().get("home") or {}).get("souvenirs", True))


def make(log=print):
    import make_set
    if exists():
        log("Her room already exists (sets/home.json).")
        return json.loads(path().read_text(encoding="utf-8-sig"))
    rec = make_set.create_set(idea=IDEA, where="inside", light="day", name="My Room", keep_id=HOME_ID, style="base",
                              log=log)
    rec = json.loads(path().read_text(encoding="utf-8-sig"))
    rec.update(home=True, souvenirs=rec.get("souvenirs") or [])
    S.write_json(path(), rec)
    log("Her room is ready: My Room (sets/home.json).")
    return rec


def souvenir_from(ep):
    """The thing from this video to keep: a cutaway's subject first, then something she held, then another thing."""
    cast = ep.get("cast") or {}
    order = []
    for s in ep.get("shots") or []:
        for e in s.get("events") or []:
            w = e.get("who")
            rank = 0 if e.get("cutaway") else 1 if e.get("do") == "hold" and w != "balloons" else 2
            order.append((rank, w))
    for _, who in sorted(order, key=lambda x: x[0]):
        info = cast.get(who) or {}
        d = info.get("def")
        if info.get("type") == "person" or (d or {}).get("explainer") or (d or {}).get("crowd") \
                or (d or {}).get("person") or who == "balloons":
            continue
        if isinstance(d, dict) and (d.get("parts") or d.get("model") or d.get("sprite")):
            return {"kind": who, "def": d, "from": str(ep.get("title") or "")[:80], "time": int(time.time())}
        if info.get("prop"):
            return {"kind": who, "prop": info["prop"], "from": str(ep.get("title") or "")[:80], "time": int(time.time())}
    return None


def place(rec):
    """Souvenir props along the walls: the old ones are taken out and the list is laid out again, newest first."""
    rec["props"] = [p for p in rec.get("props") or [] if not p.get("souvenir")]
    custom = rec.setdefault("custom_props", {})
    for k in [k for k in custom if k.startswith("souv_")]:
        custom.pop(k)
    taken = [tuple(p.get("pos", (0, 0))[:2]) for p in rec["props"]]
    free = [s for s in SPOTS if all(math.dist(s, t) > 0.9 for t in taken)]
    for sv, spot in zip(sorted(rec.get("souvenirs") or [], key=lambda x: -x.get("time", 0)), free):
        key = "souv_" + sv["kind"]
        if sv.get("def"):
            d = dict(sv["def"])
            custom[key] = d
            h = float(d.get("height") or 1.0)
        else:
            key, h = sv["prop"], 1.0
        rot = math.atan2(-spot[0], -(spot[1] - 0.0)) if spot[1] > 1 else 0.0     # turned towards the middle
        rec["props"].append({"kind": key, "pos": [spot[0], spot[1]], "rot": round(rot, 2),
                             "scale": round(min(1.0, SOUVENIR_H / max(0.05, h)), 3), "souvenir": True})
    return rec


def collect(ep, log=print):
    """After a render: keep one thing from the video in her room (when the room exists and souvenirs are on)."""
    if not exists() or not on() or ep.get("set") == HOME_ID and not ep.get("cast"):
        return None
    sv = souvenir_from(ep)
    if not sv:
        return None
    rec = json.loads(path().read_text(encoding="utf-8-sig"))
    have = [x for x in rec.get("souvenirs") or [] if x.get("kind") != sv["kind"]]
    rec["souvenirs"] = (have + [sv])[-MAX_SOUVENIRS:]
    place(rec)
    S.write_json(path(), rec)
    log(f"  her room: kept the {sv['kind'].replace('_', ' ')} from this video as a souvenir")
    return sv


def remove(kind):
    rec = json.loads(path().read_text(encoding="utf-8-sig"))
    rec["souvenirs"] = [x for x in rec.get("souvenirs") or [] if x.get("kind") != kind]
    place(rec)
    S.write_json(path(), rec)
    return rec


def main():
    ap = argparse.ArgumentParser(description="Her room (the home set) and its souvenirs")
    ap.add_argument("what", choices=["make", "place"])
    args = ap.parse_args()
    if args.what == "make":
        make()
    else:
        S.write_json(path(), place(json.loads(path().read_text(encoding="utf-8-sig"))))
        print("Souvenirs placed again.")


if __name__ == "__main__":
    main()
