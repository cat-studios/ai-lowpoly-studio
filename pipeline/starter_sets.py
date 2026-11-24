"""
Starter sets: a handful of ordinary, easy-to-recognise places, made with the normal set maker (make_set.py).
The Sets page's "Generate 3 Starter Sets" button runs this with 3.

    python pipeline/starter_sets.py [count]      # default 3, picked from STARTER_IDEAS at random (no repeats)
"""
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STARTER_IDEAS = [
    "cosy bedroom", "busy kitchen", "city street at night", "beach at sunset", "school classroom",
    "snowy mountain path", "haunted castle hall", "space station", "forest path", "office break room",
]


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    picks = random.sample(STARTER_IDEAS, min(count, len(STARTER_IDEAS)))
    print(f"[starter] making {len(picks)} starter set(s): {', '.join(picks)}", flush=True)
    for i, idea in enumerate(picks):
        print(f"[starter] {i + 1}/{len(picks)}: {idea}", flush=True)
        r = subprocess.run([sys.executable, "-u", str(ROOT / "pipeline" / "make_set.py"), "--idea", idea],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        for line in r.stdout.splitlines():
            if line.startswith(("[set]", "SET_ID=", "PROGRESS")):
                print(line, flush=True)
        if r.returncode != 0:
            print(f"[starter] {idea} failed: {(r.stderr or '')[-200:]}", flush=True)
    print("[starter] done", flush=True)


if __name__ == "__main__":
    main()
