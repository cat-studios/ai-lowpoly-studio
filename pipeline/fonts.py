"""List installed font family names (Windows font folders) by reading each font's 'name' table."""
import os
import struct
from pathlib import Path

FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]


def _family(path):
    with open(path, "rb") as f:
        data = f.read(1 << 20)          # name table is near the start in practice; cap the read
    off = 0
    if data[:4] == b"ttcf":            # collection: use the first font
        off = struct.unpack(">I", data[12:16])[0]
    num = struct.unpack(">H", data[off + 4:off + 6])[0]
    for i in range(num):
        rec = off + 12 + i * 16
        tag, _, toff, length = struct.unpack(">4sIII", data[rec:rec + 16])
        if tag != b"name":
            continue
        if toff + length > len(data):
            with open(path, "rb") as f:
                f.seek(toff)
                table = f.read(length)
        else:
            table = data[toff:toff + length]
        count, sto = struct.unpack(">HH", table[2:6])
        best = {}
        for j in range(count):
            pid, eid, lid, nid, ln, no = struct.unpack(">HHHHHH", table[6 + j * 12:18 + j * 12])
            if nid not in (1, 16):
                continue
            raw = table[sto + no:sto + no + ln]
            if pid == 3:
                if lid not in (0x409, 0):
                    continue
                name = raw.decode("utf-16-be", "ignore")
            elif pid == 1:
                name = raw.decode("latin-1", "ignore")
            else:
                continue
            best.setdefault(nid, name)
        return best.get(1) or best.get(16)     # legacy family = what Windows/libass match on
    return None


_CACHE = None


def list_fonts():
    global _CACHE
    if _CACHE is None:
        names = set()
        for d in FONT_DIRS:
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if p.suffix.lower() in (".ttf", ".otf", ".ttc"):
                    try:
                        n = _family(p)
                    except Exception:
                        n = None
                    if n and not n.startswith((".", "@")):
                        names.add(n.strip())
        _CACHE = sorted(names, key=str.lower)
    return _CACHE


if __name__ == "__main__":
    fs = list_fonts()
    print(len(fs), "fonts:", ", ".join(fs[:40]))
