"""
AI-made props. When a set needs something the built-in prop library can't build (a lava rock, a
cauldron, a vending machine...), Ollama designs it as a handful of low-poly primitives (boxes,
cylinders, cones, spheres, rocks) with colours. Each design is validated, saved to
assets/props/<kind>.json and reused by later sets, so the library grows every time you make a set.
Recipes embed the designs they use ("custom_props"), so a set keeps working on its own.
"""
import json
import math
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "assets" / "props"
SHAPES = {"box": "box", "cube": "box", "block": "box", "cuboid": "box",
          "cylinder": "cylinder", "cyl": "cylinder", "tube": "cylinder", "disc": "cylinder", "disk": "cylinder",
          "cone": "cone", "spike": "cone", "pyramid": "pyramid",
          "sphere": "sphere", "ball": "sphere", "dome": "sphere", "ellipsoid": "sphere",
          "rock": "rock", "ico": "rock", "blob": "rock", "lump": "rock"}
PLACES = ("near", "far", "scatter", "wall", "corner", "center")
HEX = re.compile(r"#[0-9a-fA-F]{6}")

GUIDE = (
    "You build ONE small low-poly 3D object (N64 style) out of simple primitive shapes. Reply with JSON only:\n"
    '{"parts": [{"shape": "box|cylinder|cone|pyramid|sphere|rock", "pos": [x, y, z], "size": [w, d, h], '
    '"rot": [rx, ry, rz], "color": "#rrggbb", "glow": false}], "place": "near|far|scatter|wall|corner"}\n'
    "Units are metres. z is up and the object stands on the ground at z=0, so a part's pos is its CENTRE "
    "(a 1 m tall box on the ground has z=0.5). The front faces -y (towards the camera). size is the full "
    "width (x), depth (y) and height (z). rot is in degrees (optional). glow=true for things that give off "
    "light (fire, lava, screens, lamps, magic) - they ignore shading. rock = a lumpy faceted blob.\n"
    'Also reply "complex": true ONLY when the object is too detailed to build from simple boxes, cylinders and '
    "spheres (a person or animal, a face, text, a detailed machine); otherwise false. Simple things (a table, a "
    "tree, a cup, a rock, a car) are false.\n"
    "Use 2 to 14 parts. Keep it chunky and readable from far away: few big parts, bold distinct colours, no "
    "tiny details. Real-world scale: a person is 1.6 m tall.\n"
    "Build it like a sculpture: start with the biggest part on the ground at x=0, y=0, then attach each other "
    "part so it touches or overlaps a part already placed (stack upward, stick to the sides). Nothing floats. "
    "Solid objects only - no smoke, mist or light beams.\n"
    "place: near = a few around the stage, far = many in the background (trees, spires), scatter = small "
    "things lying around, wall = furniture that stands against a wall (inside), corner = room corner.\n"
    'Example "street lamp": {"parts": [{"shape": "cylinder", "pos": [0,0,1.5], "size": [0.12,0.12,3], '
    '"color": "#2f3440"}, {"shape": "box", "pos": [0,0,3.1], "size": [0.4,0.4,0.25], "color": "#2f3440"}, '
    '{"shape": "sphere", "pos": [0,0,2.9], "size": [0.3,0.3,0.25], "color": "#ffe7a0", "glow": true}], '
    '"place": "near"}'
)


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    return s[:28].strip("_")


def library():
    """All saved AI props: kind -> definition."""
    out = {}
    if LIB.exists():
        for p in sorted(LIB.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8-sig"))
                if d.get("parts"):
                    out[d.get("kind", p.stem)] = d
            except Exception:
                continue
    return out


def _num(v, lo, hi, default):
    try:
        v = float(v)
        return default if math.isnan(v) else max(lo, min(hi, v))
    except Exception:
        return default


def _vec(v, n, lo, hi, default):
    if isinstance(v, (int, float)):
        v = [v] * n
    if not isinstance(v, (list, tuple)):
        return list(default)
    v = list(v)[:n] + list(default)[len(v):]
    return [round(_num(x, lo, hi, d), 3) for x, d in zip(v, default)]


def _settle(parts):
    """Gravity: a part hanging in the air (nothing under it) drops onto the part below it, or the ground.
    Parts that overlap something (a canopy around a trunk, a lamp on a pole) are left alone."""
    def box(p):
        (x, y, z), (w, d, h) = p["pos"], p["size"]
        return x - w / 2, x + w / 2, y - d / 2, y + d / 2, z - h / 2, z + h / 2

    done = []
    for p in sorted(parts, key=lambda p: box(p)[4]):
        x0, x1, y0, y1, z0, z1 = box(p)
        under = [box(q) for q in done if box(q)[0] < x1 - 0.02 and box(q)[1] > x0 + 0.02
                 and box(q)[2] < y1 - 0.02 and box(q)[3] > y0 + 0.02 and box(q)[4] < z0]
        support = max([b[5] for b in under], default=0.0)
        if z0 - support > 0.05:
            p["pos"][2] = round(p["pos"][2] - (z0 - support), 3)
        done.append(p)


def clean(raw, kind, looks="", by="ollama"):
    """Validate an AI design. Returns a definition or None if nothing usable came back."""
    if not isinstance(raw, dict):
        return None
    parts_in = raw.get("parts") or raw.get("shapes") or raw.get("objects") or []
    parts = []
    for p in parts_in[:24]:
        if not isinstance(p, dict):
            continue
        shape = SHAPES.get(str(p.get("shape") or p.get("type") or "box").lower().strip())
        if not shape:
            continue
        size = _vec(p.get("size") or p.get("scale"), 3, 0.02, 14.0, (0.5, 0.5, 0.5))
        pos = _vec(p.get("pos") or p.get("position"), 3, -8.0, 16.0, (0.0, 0.0, size[2] / 2))
        rot = _vec(p.get("rot") or p.get("rotation"), 3, -360.0, 360.0, (0.0, 0.0, 0.0))
        col = str(p.get("color") or p.get("colour") or "").strip()
        parts.append({"shape": shape, "pos": pos, "size": size, "rot": rot,
                      "color": col.lower() if HEX.fullmatch(col) else "#9a9180", "glow": bool(p.get("glow"))})
    if not parts:
        return None
    # sit it on the ground: the lowest point touches z=0 (models often forget the centre rule)
    low = min(p["pos"][2] - p["size"][2] / 2 for p in parts)
    # ...and is centred on its footprint, so placement/spacing works
    cx = (min(p["pos"][0] - p["size"][0] / 2 for p in parts) + max(p["pos"][0] + p["size"][0] / 2 for p in parts)) / 2
    cy = (min(p["pos"][1] - p["size"][1] / 2 for p in parts) + max(p["pos"][1] + p["size"][1] / 2 for p in parts)) / 2
    for p in parts:
        p["pos"] = [round(p["pos"][0] - cx, 3), round(p["pos"][1] - cy, 3), round(p["pos"][2] - low, 3)]
    _settle(parts)
    # footprint + height measured from the parts, not trusted from the model
    radius = max(math.hypot(abs(p["pos"][0]) + p["size"][0] / 2, abs(p["pos"][1]) + p["size"][1] / 2) for p in parts)
    height = max(p["pos"][2] + p["size"][2] / 2 for p in parts)
    if radius > 6 or height > 16:            # far too big for a prop - shrink it to a sane size
        f = min(6 / radius, 16 / height)
        for p in parts:
            p["pos"] = [round(x * f, 3) for x in p["pos"]]
            p["size"] = [round(max(0.02, x * f), 3) for x in p["size"]]
        radius, height = radius * f, height * f
    place = str(raw.get("place") or "").lower()
    if place not in PLACES:
        place = "far" if height > 3 else ("scatter" if radius < 0.4 else "near")
    return {"kind": kind, "name": kind.replace("_", " "), "looks": str(looks)[:200], "place": place,
            "radius": round(min(radius, 4.0), 2), "height": round(height, 2), "parts": parts,
            "complex": bool(raw.get("complex")),
            "by": by, "created": time.time()}


def needs_picture(d):
    """Only objects too detailed for simple 3D shapes (or with no shape at all) get a 2D picture.
    Priority: imported model > generated 3D model > 2D picture."""
    return bool(d.get("complex") or not d.get("parts"))


def fallback(kind, looks="", colors=None):
    """No AI available (or it returned junk): a simple stand-in built from the words in the name."""
    words = f"{kind} {looks}".lower()
    c = (colors or ["#8a7f99", "#c4b6a0"])
    glow = any(w in words for w in ("lava", "fire", "glow", "magma", "neon", "lamp", "torch", "crystal", "magic"))
    if any(w in words for w in ("rock", "stone", "boulder", "lava", "magma")):
        parts = [{"shape": "rock", "pos": [0, 0, 0.45], "size": [1.4, 1.1, 0.9], "color": "#3a3438"},
                 {"shape": "rock", "pos": [0.35, -0.2, 0.75], "size": [0.5, 0.4, 0.35], "color": c[0], "glow": glow}]
    elif any(w in words for w in ("tree", "spire", "tower", "pillar", "column", "totem")):
        parts = [{"shape": "cylinder", "pos": [0, 0, 1.2], "size": [0.5, 0.5, 2.4], "color": c[1]},
                 {"shape": "cone", "pos": [0, 0, 3.0], "size": [1.6, 1.6, 1.6], "color": c[0], "glow": glow}]
    else:
        parts = [{"shape": "box", "pos": [0, 0, 0.4], "size": [0.9, 0.7, 0.8], "color": c[1]},
                 {"shape": "sphere", "pos": [0, 0, 1.0], "size": [0.6, 0.6, 0.45], "color": c[0], "glow": glow}]
    for p in parts:
        p.setdefault("rot", [0, 0, 0])
        p.setdefault("glow", False)
    return clean({"parts": parts}, kind, looks, by="fallback")


SIZE_GUIDE = ("You know the real-world size of everyday objects. Reply with JSON only: "
              '{"height_m": number, "width_m": number, "on": "floor" or "table" or "wall"}. '
              "height_m/width_m = a typical real one in metres. on = where it normally stands: floor (furniture, "
              "appliances, plants, vehicles, people-sized things), table (small things you put on a table or "
              "counter: bowls, pots, lamps, samovars, books, food), wall (things that hang).")


def real_size(d, ollama, log=print):
    """Ask once how big the real object is (one number is far more reliable than the shape design's guess) and
    scale the definition to it. Also records where it sits: floor / table / wall."""
    if not ollama or d.get("size_checked"):
        return d
    import llm
    try:
        r = llm.chat_json(ollama["url"], ollama["model"], SIZE_GUIDE,
                          f"Object: {d['kind'].replace('_', ' ')} ({d.get('looks') or ''})", temperature=0.2)
        h = _num(r.get("height_m"), 0.05, 12.0, 0.0)
        wdt = _num(r.get("width_m"), 0.03, 15.0, 0.0)
        on = r.get("on") if r.get("on") in ("floor", "table", "wall") else "floor"
    except Exception as exc:
        log(f"[props] size check for '{d['kind']}' failed ({exc.__class__.__name__})")
        return d
    if h > 0:
        f = h / max(0.05, float(d.get("height", h)))
        for p in d.get("parts", []):
            p["pos"] = [round(x * f, 3) for x in p["pos"]]
            p["size"] = [round(max(0.01, x * f), 3) for x in p["size"]]
        d["height"] = round(h, 2)
        if wdt > 0:
            d["width"] = round(wdt, 2)
        d["radius"] = round(min(4.0, float(d.get("radius", 0.5)) * f), 2)
        d["on"] = on
        if on == "table":
            d["place"] = "scatter"
        d["size_checked"] = True
        log(f"[props] '{d['kind']}' is about {h:.2f} m tall, sits on the {on}")
    return d


def add_sprite(d, comfy_cfg, log=print, force=False):
    """Give a prop a picture: ComfyUI draws it and it's cut out (assets/props/<kind>.png). Blender shows the sprite
    as a camera-facing cut-out (N64 style) - much more recognisable than shapes. The shapes stay as the fallback."""
    if not comfy_cfg or (d.get("sprite") and (ROOT / d["sprite"]).exists() and not force):
        return d
    import comfy
    kind = d["kind"]
    out = LIB / f"{kind}.png"
    try:
        info = comfy.object_sprite(kind, d.get("looks") or kind.replace("_", " "), out, comfy_cfg,
                                   seed=sum(map(ord, kind)) * 31, log=log)
    except Exception as exc:
        log(f"[props] couldn't draw '{kind}' ({exc.__class__.__name__}: {str(exc)[:80]}) - using shapes")
        info = None
    if info:
        d["sprite"] = f"assets/props/{kind}.png"
        d["sprite_aspect"] = info["aspect"]
        log(f"[props] drew '{kind}' ({info['w']}x{info['h']} px sprite)")
    return d


def _save(d):
    LIB.mkdir(parents=True, exist_ok=True)
    (LIB / f"{d['kind']}.json").write_text(json.dumps(d, indent=1), encoding="utf-8")


def imported_def(kind, looks="", setting="", log=print):
    """A real imported model (assets/imported) for `kind`, checked BEFORE anything is generated. None if no match."""
    try:
        import imported
        d = imported.match(kind, looks, setting)
    except Exception as exc:
        log(f"[props] imported models unavailable ({exc.__class__.__name__}: {str(exc)[:80]})")
        return None
    if d:
        log(f"[props] using imported model '{d['name']}' for '{kind}' (from {d['pack']})")
    return d


def design(kind, looks, setting="", ollama=None, log=print, save=True, comfy_cfg=None, use_imported=True):
    """Get the definition for `kind`: a real imported model if one matches, else the library, else designed now.
    Ollama works out its size and a shape version; with comfy_cfg (ComfyUI on) it also gets a drawn sprite."""
    kind = slug(kind)
    real = imported_def(kind, looks, setting, log) if use_imported else None
    if real:
        return real
    have = library().get(kind)
    if have:
        log(f"[props] reusing '{kind}' from the prop library")
        changed = False
        if ollama and not have.get("size_checked"):        # older library props get a real size...
            real_size(have, ollama, log)
            changed = have.get("size_checked", False)
        if comfy_cfg and not have.get("sprite") and needs_picture(have):   # ...and a picture if it needs one
            add_sprite(have, comfy_cfg, log)
            changed = changed or bool(have.get("sprite"))
        if changed and save:
            _save(have)
        return have
    d = None
    if ollama:
        import llm
        user = (f"Object: {kind.replace('_', ' ')}\nWhat it looks like: {looks or kind.replace('_', ' ')}\n"
                + (f"It is part of this place: {setting}\n" if setting else ""))
        for attempt in range(2):
            try:
                d = clean(llm.chat_json(ollama["url"], ollama["model"], GUIDE, user, temperature=0.7), kind, looks)
            except Exception as exc:
                log(f"[props] Ollama failed on '{kind}' ({exc.__class__.__name__}: {str(exc)[:80]})")
                d = None
            if d and len(d["parts"]) >= 2:
                break
    if not d:
        d = fallback(kind, looks)
        log(f"[props] '{kind}': simple stand-in shape (no usable AI design)")
    else:
        log(f"[props] designed new prop '{kind}' ({len(d['parts'])} parts, {d['radius']} m wide, {d['height']} m tall)")
    real_size(d, ollama, log)
    if needs_picture(d):                       # 3D first: a picture only for complicated or shapeless objects
        add_sprite(d, comfy_cfg, log)
    if save and (d.get("by") == "ollama" or d.get("sprite")):
        _save(d)
    return d


def redraw(kind, looks=None, log=print):
    """Draw a library prop again (optionally from a new description) - the Assets page's Redraw button."""
    import settings as S
    d = library().get(kind)
    if not d:
        raise SystemExit(f"no prop '{kind}' in the library")
    if looks:
        d["looks"] = str(looks)[:200]
    cfg = S.load_settings()
    if cfg["comfy"].get("mode", "auto") == "off":
        cfg["comfy"]["mode"] = "auto"            # an explicit redraw always asks ComfyUI
    old = LIB / f"{kind}.png"
    if old.exists():
        (LIB / ".trash").mkdir(exist_ok=True)
        old.replace(LIB / ".trash" / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.png")
    d.pop("sprite", None)
    from progress import report
    report(0.15, "Drawing with ComfyUI")
    add_sprite(d, cfg["comfy"], log, force=True)
    report(0.95, "Saving")
    if not d.get("sprite"):
        raise SystemExit("ComfyUI couldn't draw it (is ComfyUI running?) - the old picture is in assets/props/.trash")
    _save(d)
    log(f"[props] redrew '{kind}'")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import settings as S
    if len(sys.argv) > 2 and sys.argv[1] == "redraw":
        redraw(sys.argv[2], " ".join(sys.argv[3:]) or None)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "missing":     # draw a picture for every prop that has none yet
        from progress import report
        cfg = S.load_settings()["comfy"]
        lib = library()                                   # read once, not once per prop
        todo = [k for k, d in sorted(lib.items())
                if needs_picture(d) and not (d.get("sprite") and (ROOT / d["sprite"]).exists())]
        print(f"[props] {len(todo)} prop(s) without a picture", flush=True)
        for i, k in enumerate(todo):
            report(i / max(1, len(todo)), f"Drawing {k} ({i + 1}/{len(todo)})")
            d = lib[k]
            add_sprite(d, cfg, log=print, force=True)
            if d.get("sprite"):
                _save(d)
            else:
                print(f"[props] '{k}' still has no picture", flush=True)
        report(1.0, "Done")
        sys.exit(0)
    o = S.load_settings()["ollama"]
    print(json.dumps(design(sys.argv[1], " ".join(sys.argv[2:]), ollama=o, save=False), indent=1))
