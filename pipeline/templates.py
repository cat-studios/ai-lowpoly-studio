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
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 3, "wipe_every": 4},
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
                   "amazing one last. Show each fact with a cutaway at the start of its line - the cutaway shows "
                   "the very thing that line names, about the video's topic, never a comparison or a joke picture "
                   "(a line about the brain shows a brain, not a whale). Short, punchy lines; a one-line hook "
                   "first."),
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
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 3, "wipe_every": 4},
    },
    "top_five": {
        "name": "Top 5",
        "icon": "🏆",
        "about": "A countdown of five things, from number 5 to the most amazing number 1.",
        "title_starts": ["What are the 5", "Which 5", "What are the five"],
        "title_hint": "five real things of one kind to count down (animals, places, inventions, foods...)",
        "script": ("This is a TOP 5 COUNTDOWN. First line: a one-line hook that says what is being counted. Then one "
                   "line per entry, counting DOWN: each starts with a [cutaway: the thing] that shows exactly that "
                   "entry, then the number (\"[cutaway: <the entry>] Number 5: <the entry>...\"), then one true, "
                   "surprising reason it is on the list. Number 1 is the most amazing and gets a big reaction ([surprised] or [celebrate]). "
                   "End with a short line asking which one the viewer would pick. Keep every fact true."),
        "tone": "excited",
        "lines": (7, 8),
        "direct": {"beat_words": 3, "walk_every": 0, "move_every": 2, "wipe_every": 3},
    },
    "myth_or_fact": {
        "name": "Myth or fact?",
        "icon": "🤔",
        "about": "She reads out things people believe, asks 'myth or fact?' and reveals the truth.",
        "title_starts": ["Is it true that", "Do", "Can", "Does"],
        "title_hint": "a common belief people are not sure about",
        "script": ("This is MYTH OR FACT. First line: a hook. Then 3 claims about the topic, each in TWO lines. "
                   "Line A says the claim as a plain sentence and ends with the words \"Myth or fact?\" - e.g. "
                   "\"[think] <the claim>. Myth or fact?\". Line B is the answer and STARTS with the spoken word "
                   "\"Myth!\" or \"Fact!\" (outside the brackets) followed by the real reason - e.g. \"[closeup, "
                   "surprised] Myth! <what is really true>.\". One of the claims is the title's own question, and "
                   "its answer is the true, well-known one. Only use claims you are SURE about; never invent a fact "
                   "for a joke - the joke goes in how she reacts. No labels like \"Claim 1:\" and nobody else comes "
                   "in. End with one short line asking the viewer which one fooled them."),
        "tone": "silly",
        "lines": (7, 8),
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 2, "wipe_every": 4},
    },
    "this_or_that": {
        "name": "This or that?",
        "icon": "⚖️",
        "about": "Two things side by side: she weighs them up and asks the viewer to pick.",
        "title_starts": ["Which is better", "Would you rather", "Which would win"],
        "title_hint": "two real things to compare (two animals, foods, places, superpowers...)",
        "script": ("This is THIS OR THAT: two things compared. First line: the question, naming both. Then she "
                   "takes turns: a line for the first thing with a [cutaway: first thing], a line for the second "
                   "with a [cutaway: second thing], two or three rounds, each round a different point (speed, size, "
                   "taste, how fun...). Use true facts and fair points. She ends by saying which she would pick and "
                   "asking the viewer to say theirs."),
        "tone": "silly",
        "lines": (6, 8),
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 2, "wipe_every": 4},
    },
    "guess_what": {
        "name": "Guess what?",
        "icon": "🔍",
        "about": "Clues one at a time, from hard to easy - then the big reveal at the end.",
        "title_starts": ["Can you guess", "What could", "Can you tell what"],
        "title_hint": "one real thing (an animal, an object, a place) to guess from clues",
        "script": ("This is GUESS WHAT: the viewer guesses a thing from clues. Never name the thing until the reveal. "
                   "First line: a hook (\"I'm thinking of something...\"). Then 4 to 5 clues, one per line, from "
                   "hardest to easiest, each a true fact ([think], [look_around], [closeup] on the trickiest). One "
                   "line tells the viewer to guess now. The LAST line is the reveal: it starts with [cutaway: the "
                   "thing] [surprised] and says what it is with one last amazing fact."),
        "tone": "mysterious",
        "lines": (6, 8),
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 3, "wipe_every": 4},
    },
    "conversation": {
        "name": "Conversation",
        "icon": "💬",
        "about": "She and a co-star talk WITH each other (pick one under 'Also in it'): a funny back-and-forth.",
        "title_starts": ["What if", "Who would win", "Which is better", "Why do"],
        "title_hint": "a question two friends would argue about or figure out together",
        "script": ("This is a CONVERSATION: the main character and the other main character talk TO EACH OTHER, "
                   "not to the camera - a quick back-and-forth where each line answers the one before (questions, "
                   "disagreements, a joke at the other's expense, a twist). Every line of the other character starts "
                   "with their name and a colon. Only the first line (the hook) and the last line speak to the "
                   "viewer. About half the lines each."),
        "tone": "funny",
        "lines": (7, 9),
        "direct": {"beat_words": 6, "walk_every": 0, "move_every": 0, "wipe_every": 5},
    },
    "talk_to_you": {
        "name": "Talk to you",
        "icon": "🤳",
        "about": "She talks straight to you through her phone camera - comfort, a pep talk, a little challenge - "
                 "with a meter on screen that changes as she helps.",
        "title_starts": ["Are you", "Is your", "Do you", "How tired", "How stressed", "Feeling"],
        "title_hint": "something the viewer feels right now (stressed, tired, bored, nervous, sad) that she helps with",
        "script": ("She talks TO THE VIEWER (\"you\") the whole time, like a video call on her phone: warm, calm, "
                   "kind and a little playful. Pick ONE feeling to track and show it with a meter on the first line, "
                   "e.g. [meter: <feeling> <number>]; then change it on most lines as she helps "
                   "([meter: <feeling> <lower number>] ... down to almost nothing at the end, or up for a good feeling). "
                   "For a breathing or counting moment use a small bubble: [bubble: in...] then [bubble: ...out]. "
                   "No walking, no cutaways, no other people, no scene changes, no camera words (her phone films "
                   "it all), and she never gives herself a new name. The last line is a kind, warm goodbye to the "
                   "viewer."),
        "tone": "warm",
        "lines": (8, 11),
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 0, "wipe_every": 0, "camera": "selfie"},
    },
    "gadget_story": {
        "name": "Gadget story",
        "icon": "🛠️",
        "about": "A small problem, then one silly invention after another, each bigger - with name signs, "
                 "a counter that climbs and a twist ending.",
        "title_starts": ["What if", "What would happen if", "How do you", "What if you built"],
        "title_hint": "a small everyday problem that silly inventions could solve",
        "script": ("Tell it as an escalating GADGET story: the first line is the problem; then 3 or 4 inventions, "
                   "each sillier and bigger than the last. When an invention appears, bring it in with +name (one "
                   "word or words_joined) and show its name sign: [label: <NAME>-O-MATIC] or [label: <NAME> 3000] - "
                   "names you invent, never a real brand. Keep score with a counter that climbs: "
                   "[count: <what you count> 0] early, much bigger numbers later. A corner tag says who's in charge: "
                   "[tag: BOSS: ME]. The LAST line is a twist that flips the whole idea (the helper becomes the boss, "
                   "the pet owns the house) - flip the tag too ([tag: BOSS: <the invention>])."),
        "tone": "funny",
        "lines": (7, 9),
        "direct": {"beat_words": 4, "walk_every": 0, "move_every": 3, "wipe_every": 4},
    },
    "deep_theory": {
        "name": "Deep theory",
        "icon": "🌧️",
        "about": "A slow, serious explainer of a big idea (simulation theory, déjà vu, quantum immortality): calm "
                 "voice, longer shots, rain and night, and an ending that loops back to the opening.",
        "title_starts": ["What if", "Why do we", "Is it possible that", "What is", "Are we"],
        "title_hint": "a famous mind-bending theory or mystery of the mind, time or reality",
        "script": ("This is a slow, SERIOUS explainer of one big idea: calm, quiet, full of wonder, no jokes, no "
                   "\"nya\", no exclamation marks. Explain it step by step in plain words: what the idea says, where "
                   "it comes from (a scientist or thinker by name only if you are sure), the strongest reason people "
                   "believe it, and what it would mean for the viewer. Say honestly that it is a theory, never a fact. "
                   "Use one or two [cutaway: ...] to show what a line talks about, and you may move once with "
                   "[@ place] to somewhere quiet. Lines are a little longer and slower than usual. The LAST line "
                   "repeats the FIRST line's words (or nearly), so the video loops seamlessly."),
        "tone": "calm and mysterious",
        "lines": (8, 11),
        "direct": {"beat_words": 7, "walk_every": 0, "move_every": 2, "wipe_every": 0,
                   "weather": ["rain"], "light": "night", "loop_end": True, "calm": True,
                   "line_voice": {"rate": "-12%", "exaggeration": 0.3, "cfg_weight": 0.3}},
    },
}
DEFAULT = "what_if"
# twist endings (the user, 2026-11-27, from game-HUD Reels): story kinds end on a line that flips the premise
TWIST = ("End on a TWIST: the last line flips the whole idea around (who's in charge, who's the pet, what was "
         "really going on) - set it up quietly earlier so it lands.")
for _k in ("what_if", "mini_story", "conversation"):
    TEMPLATES[_k]["script"] = (TEMPLATES[_k]["script"] + " " + TWIST).strip()


def get(tid):
    """The template for an id (unknown / empty = the default)."""
    return TEMPLATES.get(str(tid or ""), TEMPLATES[DEFAULT])


MOOD_KEYS = ("camera", "weather", "light", "line_voice", "loop_end", "calm")   # kept with beats off too


def pacing(tid, beats_on=True):
    """autodirect.direct keyword arguments for a template (beats off = one shot per line, no walks/beats)."""
    d = dict(get(tid)["direct"])
    if not beats_on:
        d = {"beat_words": 0, "walk_every": 0, "move_every": 0, "wipe_every": 0,
             **{k: d[k] for k in MOOD_KEYS if d.get(k)}}
    return d


def as_list():
    """For the web app's pickers."""
    return [{"id": k, "name": t["name"], "icon": t["icon"], "about": t["about"], "tone": t["tone"],
             "lines": list(t["lines"])} for k, t in TEMPLATES.items()]
