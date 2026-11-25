"""
Local voice generation with Chatterbox (MIT licence, runs on the GPU).
Runs inside tools/voice-venv (Python 3.11). Called by run_episode.py in one batch so the
model loads once per episode:

    tools/voice-venv/Scripts/python.exe pipeline/local_tts.py jobs.json

jobs.json: [{"text": "...", "out": "x.wav", "ref": "assets/voices/catgirl.wav" | null,
             "exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "seed": 1}, ...]

Every take is transcribed with Whisper; takes that drop or garble words are regenerated
with a new seed (up to MAX_TRIES), and the best take is kept.
"""
import json
import os
import re
import sys
import time
import warnings
from difflib import SequenceMatcher
from pathlib import Path

os.environ.setdefault("TQDM_DISABLE", "1")
warnings.filterwarnings("ignore")

import torch  # noqa: E402
import torchaudio  # noqa: E402
from chatterbox.tts import ChatterboxTTS  # noqa: E402

MAX_TRIES = 4
GOOD_ENOUGH = 0.85


NUMS = dict(enumerate("zero one two three four five six seven eight nine ten".split()))


def norm(s):
    s = re.sub(r"\d+", lambda m: NUMS.get(int(m.group()), m.group()), s.lower())
    ws = re.findall(r"[a-z']+", s)
    ws = [w for w in ws if not re.search(r"(.)\1{2,}", w)]   # drop stretched sounds: "hsssss", "nyaaa"
    return "".join(ws).replace("'", "")


def score(expected, heard):
    """0..1 letter-level similarity, tolerant of homophones like hiss/his and nya/nia."""
    e, h = norm(expected), norm(heard)
    return 1.0 if not e else SequenceMatcher(None, e, h).ratio()


def main():
    jobs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    t0 = time.time()
    model = ChatterboxTTS.from_pretrained(device=device)
    try:
        from faster_whisper import WhisperModel
        asr = WhisperModel("base.en", device=device, compute_type="float16" if device == "cuda" else "int8")
    except Exception as exc:     # QA is optional
        print(f"[voice] whisper unavailable ({exc}); skipping checks", flush=True)
        asr = None
    print(f"[voice] models loaded on {device} in {time.time() - t0:.0f}s", flush=True)

    for i, job in enumerate(jobs):
        best = None
        for attempt in range(MAX_TRIES):
            torch.manual_seed(int(job.get("seed", 1)) + attempt * 1000)
            wav = model.generate(
                job["text"],
                audio_prompt_path=job.get("ref") or None,
                exaggeration=float(job.get("exaggeration", 0.5)),
                cfg_weight=float(job.get("cfg_weight", 0.5)),
                temperature=float(job.get("temperature", 0.8)),
            ).cpu()
            if asr is None:
                best = (1.0, wav, "", [])
                break
            tmp = job["out"] + ".take.wav"
            torchaudio.save(tmp, wav, model.sr)
            segs, _ = asr.transcribe(tmp, language="en", beam_size=1, word_timestamps=True)
            segs = list(segs)
            heard = " ".join(s.text for s in segs).strip()
            # when each word is said (captions and beat cuts follow the voice - run_episode.word_starts)
            words = [[w.word.strip(), round(w.start, 3), round(w.end, 3)] for s in segs for w in (s.words or [])]
            os.remove(tmp)
            sc = score(job["text"], heard)
            if best is None or sc > best[0]:
                best = (sc, wav, heard, words)
            if sc >= GOOD_ENOUGH:
                break
        sc, wav, heard, words = best
        torchaudio.save(job["out"], wav, model.sr)
        if words:
            Path(job["out"] + ".words.json").write_text(json.dumps(words), encoding="utf-8")
        flag = "" if sc >= GOOD_ENOUGH else "  <-- CHECK THIS LINE"
        print(f"[voice] {i + 1}/{len(jobs)} match {sc:.0%} after {attempt + 1} take(s): "
              f"{job['text'][:45]!r} heard {heard[:45]!r}{flag}", flush=True)


if __name__ == "__main__":
    main()
