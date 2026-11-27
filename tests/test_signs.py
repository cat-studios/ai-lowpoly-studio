"""Signs, tags and symbols (propgen sign template): a Black Friday "discount tag" was built from AI shapes as a
yellow cone, two red boxes and a ball.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import propgen as P  # noqa: E402


class Signs(unittest.TestCase):
    def test_sign_like_things_get_the_template(self):
        self.assertEqual(P.template_for("discount_tag", "massive discount tag"), ("sign", "tag"))
        self.assertEqual(P.template_for("sale_sign"), ("sign", "board"))
        self.assertEqual(P.template_for("black_friday_banner"), ("sign", "banner"))
        self.assertEqual(P.template_for("discount_symbol"), ("sign", "round"))
        self.assertEqual(P.template_for("stop_sign"), ("sign", "board"))

    def test_other_things_dont(self):
        self.assertIsNone(P.sign_family("dog_tag"))           # a dog tag is a little metal thing, not a price tag
        self.assertIsNone(P.sign_family("sign_language_book"))
        self.assertEqual(P.template_for("delivery_van")[0], "vehicle")
        self.assertEqual(P.template_for("golden_retriever")[0], "animal")

    def test_what_is_written(self):
        self.assertEqual(P.sign_text("discount_tag", "massive discount tag"), "-50%")
        self.assertEqual(P.sign_text("percent_symbol"), "-50%")
        self.assertEqual(P.sign_text("sale_banner"), "SALE")
        self.assertEqual(P.sign_text("black_friday_banner"), "SALE")
        self.assertEqual(P.sign_text("price_tag"), "$9.99")
        self.assertEqual(P.sign_text("stop_sign"), "STOP")
        self.assertEqual(P.sign_text("welcome_sign", "a big wooden welcome sign"), "WELCOME")
        self.assertEqual(P.sign_text("bakery_sign", "a cute bakery sign"), "BAKERY")   # its own words

    def test_the_template_replaces_the_ai_shapes_and_carries_the_text(self):
        d = {"kind": "discount_tag", "parts": [{"shape": "cone", "pos": [0, 0, 0.05], "size": [0.06, 0.04, 0.1],
                                                "color": "#ffcc00"}], "sprite": "x.png"}
        P.apply_template(d, "discount_tag", "massive discount tag", ("sign", "tag"))
        self.assertEqual(d["sign"]["text"], "-50%")
        self.assertNotIn("cone", [p["shape"] for p in d["parts"]])
        self.assertTrue(d["size_checked"])                      # its size isn't asked again
        self.assertNotIn("sprite", d)
        self.assertLess(d["sign"]["y"], 0)                      # the text sits on the face that looks at the camera


if __name__ == "__main__":
    unittest.main()
