"""
Logging for the studio server. Everything goes to two places:

  the terminal        a readable line per request that changes something, per job start/finish and per error
                      (routine polling and file downloads are kept out of the terminal, but not out of the files)
  logs/               server-YYYY-MM-DD.log  every request: time, client IP, browser, method, path, status, time taken,
                      and for changes the field names/values that were sent (secrets masked)
                      jobs/<job id>.log      the full output of each background job (renders, GIFs, imports...)
                      server-YYYY-MM-DD.log also records job start/finish with who asked for it (client IP)

Standard library only.
"""
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
JOBS_DIR = LOGS / "jobs"
_lock = threading.Lock()
_local = threading.local()
QUIET_PREFIXES = ("/api/jobs", "/static/", "/media/", "/propimg/", "/fxprev/", "/setimg/", "/sfx/", "/music/",
                  "/favicon", "/apple-touch-icon", "/manifest")
SECRET_WORDS = ("pin", "key", "password", "token", "secret")


def setup():
    LOGS.mkdir(exist_ok=True)
    JOBS_DIR.mkdir(exist_ok=True)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _file():
    return LOGS / f"server-{time.strftime('%Y-%m-%d')}.log"


def _write(line, terminal=True):
    if terminal:
        print(line, flush=True)
    with _lock:
        with open(_file(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def browser(agent):
    a = agent or ""
    for word, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                       ("Macintosh", "Mac"), ("Linux", "Linux"), ("curl", "curl")):
        if word in a:
            return name
    return a[:30] or "-"


def _masked(value):
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def summary(body):
    """'{"id": "x", "pin": "1234"}' -> 'id=x pin=***' (secrets masked, long values cut short)."""
    if not isinstance(body, dict):
        return ""
    parts = []
    for k, v in list(body.items())[:12]:
        if any(w in str(k).lower() for w in SECRET_WORDS):
            parts.append(f"{k}=***")
        elif isinstance(v, (dict, list)):
            parts.append(f"{k}=<{type(v).__name__} {len(v)}>")
        else:
            parts.append(f"{k}={_masked(v)}")
    return " ".join(parts)


def set_request(ip, method, path):
    _local.ctx = (ip, method, path)


def who():
    """The client IP of the request this thread is handling ('-' outside a request)."""
    return getattr(_local, "ctx", ("-", "-", "-"))[0]


def request(ip, method, path, code, ms, agent="", body=""):
    line = f"{_now()}  {ip:<15}  {browser(agent):<10}  {method:<6} {path}  {code}  {ms}ms" + (f"  [{body}]" if body else "")
    terminal = not (method == "GET" and path.startswith(QUIET_PREFIXES) and int(code) < 400)
    _write(line, terminal=terminal)


def event(message, ip=None):
    _write(f"{_now()}  {ip or who():<15}  {message}")


def job_started(job):
    event(f"JOB {job.id} {job.kind} started: {job.title}", job.ip)


_JOB_FILES = {}       # job id -> its log file, kept open while the job runs (a render writes thousands of lines)


def job_finished(job):
    with _lock:
        fh = _JOB_FILES.pop(job.id, None)
        if fh:
            fh.close()
    why = f"  (last line: {job.log[-1][:120]})" if job.status == "failed" and job.log else ""
    event(f"JOB {job.id} {job.kind} {job.status}: {job.title}{why}", job.ip)


def job_line(job, line):
    """Every line of a job's output, kept in its own file (not on the terminal)."""
    with _lock:
        fh = _JOB_FILES.get(job.id)
        if fh is None:
            fh = _JOB_FILES[job.id] = open(JOBS_DIR / f"{job.id}.log", "a", encoding="utf-8", buffering=1)
        fh.write(line + "\n")


def job_created(job):
    with _lock:
        with open(JOBS_DIR / f"{job.id}.log", "w", encoding="utf-8") as fh:
            fh.write(f"# {job.kind} {job.id}: {job.title}\n# asked for by {job.ip} at {_now()}\n")


def error(where, exc=None):
    text = traceback.format_exc() if exc is not None else where
    _write(f"{_now()}  {who():<15}  ERROR {where}\n{text}")
