"""On-screen game overlays, drawn with the captions (ASS at the render resolution, so they get the same chunky
pixels as the picture). Inspired by game-HUD Reels (2026-11-27), in the studio's own look:

  [meter: stress 99]        a bar with its name and %; written again with a new number it slides there (-10% pops up)
  [count: cookies 0]        a counter that ticks up or down to the new number when written again
  [tag: BOSS: ME]           a corner tag that stays until another tag ([tag: off] hides it) - flip it for a twist
  [label: SNACK-O-MATIC]    a name sign for the shot (a gadget, a place, a new thing)
  [bubble: in...]           a small speech bubble for the shot (breathing, a whisper)
  [sticker: NOM NOM]        a comic sound word for the shot
  + sound-word stickers by themselves: every sound effect the video plays shows its word ("BOOM!", "WHOOSH!")

autodirect.parse_directions puts these on the shot as "hud": [{"kind", "name"?, "value"?, "text"?}];
run_episode.write_captions calls events() for the extra ASS styles and lines.
"""
import random
import re

KINDS = {"meter": "meter", "bar": "meter", "count": "count", "counter": "count", "score": "count", "tag": "tag",
         "label": "label", "sign": "label", "bubble": "bubble", "sticker": "sticker"}
HUD_RX = re.compile(r"\b(meter|bar|count|counter|score|tag|label|sign|bubble|sticker)\s*:\s*([^,\]]+)", re.I)
# meters where a HIGH number is bad (shown red when high, green when low); others are green when high
BAD_METERS = set("""stress anger angry hunger hungry chaos danger panic fear scared worry anxiety tired tiredness sleepy
boredom bored mess messy cringe heat pain sadness embarrassment awkward drama sus""".split())
STICKER_WORDS = {"boom": "BOOM!", "pop": "POP!", "boing": "BOING!", "jump": "HOP!", "coin": "CHING!", "ding": "DING!",
                 "tada": "TA-DA!", "whoosh": "WHOOSH!", "hiss": "HSSS!", "stomp": "THUD!", "laser": "ZAP!",
                 "fail": "WOMP WOMP", "buzz": "BZZT!", "meow": "NYA!", "click": "CLICK!", "sparkle": "SHINE!"}
CLOSE = ("closeup", "dramatic", "macro", "selfie")      # her face fills the middle there: the name sign goes lower
STICKER_COLORS = ["#ffe14d", "#6fe3ff", "#ff8ad8", "#9dff6a"]
TWEEN = 0.6            # seconds a meter / counter takes to reach its new number
STEPS = 6
STICKER_GAP = 1.2      # at most one sound sticker every this many seconds
MAX_STICKERS = 10


def parse(inner):
    """'[meter: stress 99, count: pats 0, happy]' -> ([hud items], the bracket text without them)."""
    items = []
    for m in list(HUD_RX.finditer(inner)):
        kind, body = KINDS[m.group(1).lower()], m.group(2).strip()
        if kind in ("meter", "count"):
            n = re.match(r"^(.*?)[\s_]*(-?\d[\d.]*)\s*%?$", body)
            if not n or not n.group(1).strip():
                continue
            try:
                val = float(n.group(2))
            except ValueError:
                continue
            name = re.sub(r"[_\s]+", " ", n.group(1)).strip().upper()[:16]
            if kind == "meter":
                val = max(0.0, min(100.0, val))
            items.append({"kind": kind, "name": name, "value": round(val) if kind == "count" else val})
        else:
            text = re.sub(r"\s+", " ", body.replace("_", " ")).strip()[:28]
            if text:
                items.append({"kind": kind, "text": text})
    return items, HUD_RX.sub("", inner)


def _c(hexs):
    h = hexs.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def meter_color(name, v):
    """Green / yellow / red by the value, the right way round for the meter (stress 99 = red, energy 99 = green)."""
    bad = any(w in BAD_METERS for w in name.lower().split())
    good_share = (100 - v) if bad else v
    return "#5fe36a" if good_share >= 60 else "#ffd23f" if good_share >= 30 else "#ff5a5a"


def styles(res, font, shadow):
    """Extra ASS styles: tag box, label sign, bubble, sticker, HUD text."""
    H = res[1]
    sz = lambda f: max(4, round(H * f))  # noqa: E731
    return [
        f"Style: Hud,{font},{sz(0.024)},&H00FFFFFF,&H00FFFFFF,{shadow},{shadow},-1,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1",
        f"Style: Tag,{font},{sz(0.024)},&H00FFFFFF,&H00FFFFFF,&H00302040,&H00302040,-1,0,0,0,100,100,0,0,3,2,0,7,0,0,0,1",
        f"Style: Label,{font},{sz(0.040)},&H00FFFFFF,&H00FFFFFF,&H001E6EF0,&H001E6EF0,-1,0,0,0,100,100,0,0,3,3,0,5,0,0,0,1",
        f"Style: Bubble,{font},{sz(0.032)},&H00302040,&H00302040,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,3,0,5,0,0,0,1",
        f"Style: Sticker,{font},{sz(0.058)},&H00FFFFFF,&H00FFFFFF,{shadow},{shadow},-1,0,0,0,100,100,1,0,1,{max(1, round(H / 160))},0,5,0,0,0,1",
    ]


def _t(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _rect(w, h):
    return f"m 0 0 l {w} 0 {w} {h} 0 {h}"


def _bar(x, y, w, h, v, col, a, b):
    """The meter's bar: a dark track with an outline, the coloured fill over it."""
    fill = max(0, round(w * v / 100))
    out = [f"Dialogue: 4,{_t(a)},{_t(b)},Hud,,0,0,0,,{{\\an7\\pos({x},{y})\\p1\\bord1\\3c&H00302040&\\1c&H00403030&}}"
           f"{_rect(w, h)}{{\\p0}}"]
    if fill:
        out.append(f"Dialogue: 5,{_t(a)},{_t(b)},Hud,,0,0,0,,{{\\an7\\pos({x},{y})\\p1\\bord0\\1c{_c(col)}&}}"
                   f"{_rect(fill, h)}{{\\p0}}")
    return out


def _timeline(shots, timing, lead_default):
    """[(time, shot index, hud items)] for the shots that change something, with each shot's start/end/lead."""
    fps = timing["fps"]
    out = []
    for i, (s, tm) in enumerate(zip(shots, timing["shots"])):
        a = (tm["f0"] - 1) / fps
        b = (tm["f0"] - 1 + tm["n"]) / fps
        out.append((a, b, float(s.get("lead", lead_default)), s.get("hud") or [], s.get("camera")))
    return out


def events(shots, timing, res, total, stop_at, stickers=(), lead_default=0.15, seed=0):
    """The ASS Dialogue lines for every overlay in the video. stop_at = when the end card starts (the HUD goes then)."""
    W, H = res
    rng = random.Random(seed)
    lines = []
    tl = _timeline(shots, timing, lead_default)
    meters, counts = {}, {}            # name -> [(time, value)] in order
    tags = []                          # [(time, text or "")]
    for a, b, lead, hud, cam in tl:
        at = a + min(lead, 0.4)
        for h in hud:
            k = h["kind"]
            if k == "meter":
                meters.setdefault(h["name"], []).append((at, float(h["value"])))
            elif k == "count":
                counts.setdefault(h["name"], []).append((at, int(h["value"])))
            elif k == "tag":
                tags.append((at, "" if h["text"].lower() in ("off", "none", "hide") else h["text"].upper()))
            elif k == "label":
                end = min(b, at + 2.6)
                rot = rng.choice((-5, -3, 3, 5))
                lines.append(f"Dialogue: 6,{_t(at)},{_t(end)},Label,,0,0,0,,{{\\pos({W // 2},{round(H * (0.62 if cam in CLOSE else 0.47))})"
                             f"\\frz{rot}\\fscx40\\fscy40\\t(0,120,\\fscx112\\fscy112)\\t(120,220,\\fscx100\\fscy100)"
                             f"\\fad(0,120)}}{_esc(h['text'].upper())}")
            elif k == "bubble":
                end = min(b, at + 2.2)
                lines.append(f"Dialogue: 6,{_t(at)},{_t(end)},Bubble,,0,0,0,,{{\\pos({round(W * 0.66)},{round(H * 0.27)})"
                             f"\\fscx50\\fscy50\\t(0,120,\\fscx100\\fscy100)\\fad(60,120)}}{_esc(h['text'].lower())}")
            elif k == "sticker":
                stickers = list(stickers) + [(h["text"].upper(), at + 0.25)]
    y = round(H * 0.165)
    gap = round(H * 0.012)
    if tags:                                       # the corner tag: until the next tag (or "off")
        for k, (t0, text) in enumerate(tags):
            t1 = tags[k + 1][0] if k + 1 < len(tags) else stop_at
            if text and t1 > t0:
                pop = "\\fscx70\\fscy70\\t(0,120,\\fscx100\\fscy100)" if k else ""
                lines.append(f"Dialogue: 6,{_t(t0)},{_t(t1)},Tag,,0,0,0,,{{\\pos({round(W * 0.05)},{y}){pop}}}"
                             f"{_esc(text)}")
        y += round(H * 0.045)
    bw, bh = round(W * 0.30), max(3, round(H * 0.018))
    for name, pts in meters.items():               # meters: label + bar + %, sliding to each new value
        lab_y, bar_y = y, y + round(H * 0.026)
        x = round(W * 0.05)
        prev = None
        for k, (t0, v) in enumerate(pts):
            t1 = pts[k + 1][0] if k + 1 < len(pts) else stop_at
            if t1 <= t0:
                continue
            frm = prev if prev is not None else v
            steps = STEPS if prev is not None and abs(v - frm) > 0.5 else 1
            dt = min(TWEEN, (t1 - t0) * 0.8) / steps
            for s in range(steps):
                u = (s + 1) / steps
                val = frm + (v - frm) * u
                a = t0 + s * dt
                bb = t0 + (s + 1) * dt if s < steps - 1 else t1
                col = meter_color(name, val)
                lines += _bar(x, bar_y, bw, bh, val, col, a, bb)
                lines.append(f"Dialogue: 5,{_t(a)},{_t(bb)},Hud,,0,0,0,,{{\\an7\\pos({x + bw + round(W * 0.02)},"
                             f"{bar_y - round(bh * 0.25)})\\c{_c(col)}&}}{round(val)}%")
            lines.append(f"Dialogue: 5,{_t(t0 if prev is not None else t0)},{_t(t1)},Hud,,0,0,0,,"
                         f"{{\\an7\\pos({x},{lab_y})\\fscx85\\fscy85}}{_esc(name)}")
            if prev is not None and round(v - prev):   # "-10%" floats up from the bar
                d = round(v - prev)
                px, py = x + bw + round(W * 0.14), bar_y
                lines.append(f"Dialogue: 7,{_t(t0)},{_t(t0 + 1.0)},Hud,,0,0,0,,{{\\an7\\move({px},{py},{px},"
                             f"{py - round(H * 0.04)})\\fad(0,350)\\c{_c(meter_color(name, v))}&}}"
                             f"{'+' if d > 0 else ''}{d}%")
            prev = v
        y += round(H * 0.06) + gap
    for name, pts in counts.items():               # counters: NAME 0 -> 397, ticking
        x = round(W * 0.05)
        prev = None
        for k, (t0, v) in enumerate(pts):
            t1 = pts[k + 1][0] if k + 1 < len(pts) else stop_at
            if t1 <= t0:
                continue
            frm = prev if prev is not None else v
            steps = STEPS if prev is not None and v != frm else 1
            dt = min(TWEEN, (t1 - t0) * 0.8) / steps
            for s in range(steps):
                val = round(frm + (v - frm) * (s + 1) / steps)
                a = t0 + s * dt
                bb = t0 + (s + 1) * dt if s < steps - 1 else t1
                pop = "\\fscx125\\fscy125\\t(0,150,\\fscx100\\fscy100)" if prev is not None and s == steps - 1 else ""
                lines.append(f"Dialogue: 5,{_t(a)},{_t(bb)},Hud,,0,0,0,,{{\\an7\\pos({x},{y}){pop}\\fscx120\\fscy120}}"
                             f"{{\\c{_c('#ffd23f')}&}}{_esc(name)} {{\\c&H00FFFFFF&}}{val:,}")
            prev = v
        y += round(H * 0.045)
    last, n = -99.0, 0
    for text, at in sorted(stickers, key=lambda x: x[1]):          # comic sound words
        if at - last < STICKER_GAP or n >= MAX_STICKERS or at >= stop_at:
            continue
        last, n = at, n + 1
        side = rng.random() < 0.5
        px = round(W * (rng.uniform(0.22, 0.40) if side else rng.uniform(0.60, 0.78)))
        py = round(H * rng.uniform(0.33, 0.46))
        col = STICKER_COLORS[n % len(STICKER_COLORS)]
        rot = rng.choice((-12, -8, -5, 5, 8, 12))
        size = "\\fscx80\\fscy80" if len(text) > 7 else ""
        lines.append(f"Dialogue: 7,{_t(at)},{_t(min(total, at + 0.85))},Sticker,,0,0,0,,{{\\pos({px},{py})\\frz{rot}"
                     f"\\c{_c(col)}&\\fscx30\\fscy30\\t(0,110,\\fscx115\\fscy115)\\t(110,200,\\fscx100\\fscy100)"
                     f"\\fad(0,180){size}}}{_esc(text)}")
    return lines


def _esc(s):
    return str(s).replace("\\", "").replace("{", "(").replace("}", ")")


def sound_stickers(ep, timing, sx, sfx_events, all_slots, word_rx):
    """[(WORD, time)] for the sound effects the video plays: the line's own trigger word ("KABOOM!") when the sound
    came from one, else the sound's word (STICKER_WORDS / a custom sound's first trigger word). Ambience never."""
    fps = timing["fps"]
    starts = [((tm["f0"] - 1) / fps, (tm["f0"] - 1 + tm["n"]) / fps) for tm in timing["shots"]]
    slots = all_slots()
    out = []
    for slot, at, _vol in sfx_events(ep, timing, sx):
        info = slots.get(slot) or {}
        if info.get("kind") == "ambience":
            continue
        i = next((k for k, (a, b) in enumerate(starts) if a <= at < b), None)
        line = (ep["shots"][i].get("line_src") or ep["shots"][i].get("line") or "") if i is not None else ""
        trig = (info.get("words") or "").split()
        word = None
        for w in line.split():
            core = re.sub(r"[^\w-]", "", w)
            if core and any(word_rx(t).fullmatch(core.lower()) for t in trig):
                word = core.upper() + "!"
                break
        word = word or STICKER_WORDS.get(slot) or ((trig[0].upper() + "!") if trig else None)
        if word and len(word) <= 12:
            out.append((word, at))
    return out
