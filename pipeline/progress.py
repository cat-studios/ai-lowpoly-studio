"""
Progress reporting for background jobs. A pipeline script prints

    PROGRESS 0.420 Rendering frames (210/500)

and the web server turns it into the job's progress bar (the line itself is kept out of the visible log).
"""
import sys
import threading
import time
from pathlib import Path

_quiet = False


def report(frac, stage=""):
    if _quiet:
        return
    frac = max(0.0, min(1.0, float(frac)))
    print(f"PROGRESS {frac:.3f} {stage}".rstrip(), flush=True)
    sys.stdout.flush()


def quiet(on=True):
    """Nested steps (a set made inside a render) shouldn't move the outer bar around."""
    global _quiet
    _quiet = on


class FrameWatcher:
    """While Blender renders, count the PNG frames written and report lo..hi of the bar."""

    def __init__(self, folder, total, lo, hi, label="Rendering frames", already=0):
        folders = folder if isinstance(folder, (list, tuple)) else [folder]
        self.folders = [Path(f) for f in folders]
        self.total, self.lo, self.hi, self.label = max(1, int(total)), lo, hi, label
        self.already = already
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _count(self):
        try:
            return sum(1 for f in dict.fromkeys(self.folders) if f.exists() for _ in f.glob("f_*.png"))
        except Exception:
            return 0

    def _run(self):
        last = -1
        while not self._stop.wait(1.0):
            n = min(self.total, self._count())
            if n != last:
                last = n
                done = n / self.total
                stage = f"{self.label} ({n}/{self.total})" if n else "Building the 3D scene"
                report(self.lo + (self.hi - self.lo) * done, stage)

    def __enter__(self):
        report(self.lo, "Building the 3D scene")
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=2)
