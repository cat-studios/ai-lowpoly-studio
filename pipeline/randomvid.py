"""Random videos for the server: the same cards as the Create page's 🎲 Make a Random Video (web/app.js MW_STEPS_BASE),
so an idle batch (web/server.py idle_loop) can make one with no browser open. A random item is an "idea" for
pipeline/batch.py with a "random" part: the place, vibe, guest, time and length the browser flow would pick.

tests/test_randomvid.py checks these lists against app.js, so the two can't drift apart.
"""
import random

CARDS = {
    "scene": [
        "a cozy cafe", "a haunted library", "a candy factory", "a busy train station", "a tropical beach", "a snowy mountain cabin",
        "a space station", "a giant kitchen", "a neon arcade", "a misty forest", "an underwater city", "a rooftop at night",
        "a school classroom", "a farm with a red barn", "a desert canyon", "a cloud kingdom in the sky", "a toy shop",
        "a museum after closing", "a bakery at dawn", "a pirate ship", "a bubble bath", "a laundromat", "a volcano island",
        "a supermarket", "a park in autumn", "a hospital waiting room", "a castle courtyard", "a tiny dollhouse",
        "a camping site by a lake", "a city street in the rain", "a greenhouse full of plants", "a bowling alley",
        "an old lighthouse", "a submarine", "the moon", "a music studio", "a bedroom at 3 am", "a zoo"],
    "topic": [
        "gravity", "dreams", "black holes", "why cats purr", "the deepest ocean", "time travel", "volcanoes", "the human brain",
        "lightning", "dinosaurs", "how plants eat", "the speed of light", "money", "sleep", "ants", "chocolate",
        "the moon landing", "rainbows", "earthquakes", "memory", "yawning", "the internet", "bees", "ice ages", "magnets",
        "hiccups", "the pyramids", "octopuses", "snowflakes", "the sun", "hair", "sneezing", "coffee", "sharks", "clouds",
        "robots", "taste buds", "fireflies", "the north pole", "music"],
    "tone": [
        "funny", "wholesome", "chaotic", "dramatic", "spooky", "cute", "deadpan", "excited", "mysterious", "silly",
        "heartfelt", "sarcastic", "nervous", "proud", "motivational", "grumpy"],
    "guest": [
        "nobody - just her", "a mischievous dog", "her mom", "a lost robot", "a tiny dragon", "a grumpy pigeon", "a talking cactus",
        "a confused tourist", "a ghost", "a delivery driver", "a giant snail", "a pirate", "a scientist", "a sleepy bear",
        "an alien", "a chef", "a cow", "a mail truck", "a rubber duck", "a wizard"],
    "time": [
        "a sunny day", "a golden sunset", "a starry night", "day turning into night", "a rainy evening", "a snowy morning",
        "a foggy dawn", "a stormy night", "night turning into dawn"],
    "length": ["short (about 20 s)", "medium (about 40 s)", "long (about a minute)"],
}
LIGHT = {"day": "day", "sunny": "day", "morning": "day", "sunset": "sunset", "golden": "sunset", "evening": "sunset",
         "night": "night", "starry": "night", "stormy": "night", "dawn": "sunset", "foggy": "sunset", "rainy": "sunset",
         "snowy": "day"}
STYLES = ["base", "palette", "judged"]      # the set style is a random pick of the three, as in the browser
NEEDS_CO_STAR = {"conversation"}            # kinds a random video can't be: it has no co-star to talk to


def lines_for(length):
    """Lines of script for the length card (the browser flow's numbers)."""
    return (4, 5) if length.startswith("short") else (10, 13) if length.startswith("long") else (6, 8)


def light_for(time_card):
    """The light a time card starts with (the first word that has one)."""
    return next((LIGHT[w] for w in time_card.replace("-", " ").split() if w in LIGHT), "")


def item(rng=random, template_ids=()):
    """One random video, as an idea for batch.py: picks the way the 🎲 card deck does."""
    pick = {k: rng.choice(v) for k, v in CARDS.items()}
    kinds = [t for t in template_ids if t not in NEEDS_CO_STAR]
    kind = rng.choice(kinds) if kinds else "what_if"
    lo, hi = lines_for(pick["length"])
    return {"id": None, "topic": pick["topic"], "angle": "", "template": kind, "titles": [],
            "random": {"scene": pick["scene"], "tone": pick["tone"], "guest": pick["guest"], "time": pick["time"],
                       "length": pick["length"], "lines": [lo, hi], "light": light_for(pick["time"]),
                       "style": rng.choice(STYLES)}}


def extra(r):
    """The 'extra' note the writer gets (the same words as the browser flow)."""
    guest = "" if r["guest"].startswith("nobody") else f"{r['guest']} shows up and plays a part (bring them in with +name). "
    when = (f"Time: {r['time']} - change the light along the way with [sunset], [night] or [dawn]. "
            if "turning into" in r["time"] else f"Time: {r['time']}. ")
    return f"Place: {r['scene']}. {guest}{when}".strip()
