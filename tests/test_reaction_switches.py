"""Her reaction sounds can be switched off one by one (Settings -> Render & audio, 2026-11-27): every sound the
director can pick has a text to say and a switch.  python -m unittest discover tests"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import autodirect as A  # noqa: E402
import run_episode as R  # noqa: E402
import settings as S  # noqa: E402


class ReactionSwitches(unittest.TestCase):
    def test_every_reaction_has_a_text_a_switch_and_a_settings_row(self):
        picked = {r for _, r in A.REACTION_FOR}
        self.assertEqual(picked, set(R.REACT_TEXT))
        self.assertEqual(picked, set(S.DEFAULTS["audio"]["reaction_sounds"]))
        rows = set(re.findall(r'"audio\.reaction_sounds\.(\w+)"', (ROOT / "web" / "app.js").read_text(encoding="utf-8")))
        self.assertEqual(rows, picked)


if __name__ == "__main__":
    unittest.main()
