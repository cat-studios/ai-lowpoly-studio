"""Video templates: the KIND of video and its pacing - never its look (the N64/VHS look is the same for all).

A template steers three steps:
- titles  (llm.generate_titles: which question starts fit, plus a hint)
- script  (llm.generate_script: extra rules for the writer, a default tone and length)
- shots   (autodirect.direct: how often it cuts, walks, moves the camera, wipes)
Used by the Create page (Template picker), the random-video popup and series (pipeline/series.py).
"""

TEMPLATES = {
    "what_if": {
        "name": "What if…",
        "icon": "💭",
        "about": "A silly 'what if' story: she imagines it and acts it out (the classic).",
        "title_starts": ["What if", "What would happen if"],
        "title_hint": "an impossible or silly situation to imagine",
        "script": "",                      # the writer's normal rules
        "tone": "funny",
        "lines": (6, 8),
        "direct": {"beat_words": 4, "walk_every": 8, "move_every": 3, "wipe_every": 4},
    },
    "how_it_works": {
        "name": "How it works",
        "icon": "🔧",
        "about": "She presents a model of one real thing, opens it up and shows how its parts work.",
        "title_starts": ["How does", "How do", "What happens inside", "How can"],
        "title_hint": "how one real machine, body part or natural thing works inside",
        "script": ("This is an explainer: she shows how ONE real thing works, step by step, with a model of it beside "
                   "her. Start with [show: thing] (one word), then [show: thing open] when you talk about the inside, "
                   "and [show: thing part] for close-ups of the parts that matter. Say what each part DOES in plain "
                   "words, in the order it happens (\"the chain lifts the flap\", \"the water drains\"). Keep the facts "
                   "true and simple, add a joke or two, and end with a short fun wrap-up after [show: off]."),
        "tone": "excited",
        "lines": (6, 9),
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 3, "wipe_every": 5},
    },
    "quick_facts": {
        "name": "Quick facts",
        "icon": "⚡",
        "about": "Fast cuts: a few surprising true facts, each shown with a cutaway.",
        "title_starts": ["Why do", "Why is", "How big is", "How much", "How long", "Is it possible"],
        "title_hint": "a topic with surprising true facts",
        "script": ("Give 3 to 5 surprising TRUE facts about the topic, one fact per line, building up to the most "
                   "amazing one last. Show each fact with a cutaway at the start of its line, e.g. "
                   "[cutaway: a blue whale swimming] A blue whale's heart is as big as a car. Short, punchy lines; "
                   "a one-line hook first."),
        "tone": "excited",
        "lines": (5, 7),
        "direct": {"beat_words": 3, "walk_every": 0, "move_every": 2, "wipe_every": 3},
    },
    "mini_story": {
        "name": "Mini story",
        "icon": "📖",
        "about": "A little story with a problem and a twist: two places and someone who drops in.",
        "title_starts": ["What if", "What would happen if", "What happens if"],
        "title_hint": "a small adventure with a problem to solve",
        "script": ("Tell a tiny story with a beginning, a problem and a twist at the end. It moves to a second place "
                   "halfway with [@ place], and someone drops in with +name (they may say a line). Every line moves "
                   "the story on."),
        "tone": "wholesome",
        "lines": (7, 10),
        "direct": {"beat_words": 4, "walk_every": 6, "move_every": 3, "wipe_every": 4},
    },
}
DEFAULT = "what_if"


def get(tid):
    """The template for an id (unknown / empty = the default)."""
    return TEMPLATES.get(str(tid or ""), TEMPLATES[DEFAULT])


def pacing(tid, beats_on=True):
    """autodirect.direct keyword arguments for a template (beats off = one shot per line, no walks/beats)."""
    d = dict(get(tid)["direct"])
    if not beats_on:
        d = {"beat_words": 0, "walk_every": 0, "move_every": 0, "wipe_every": 0}
    return d


def as_list():
    """For the web app's pickers."""
    return [{"id": k, "name": t["name"], "icon": t["icon"], "about": t["about"], "tone": t["tone"],
             "lines": list(t["lines"])} for k, t in TEMPLATES.items()]
