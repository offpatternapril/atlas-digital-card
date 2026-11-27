import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import make_card as mc

GOOD = {"consent": True, "slug": "anna-k", "name": "Anna K.", "qr_url": "https://example.org/a?x=1&y=2",
        "tagline": {"ru": "Юрист", "en": "Lawyer"}, "description": {"ru": "Помогаю", "en": "I help"}}


def data(**changes):
    d = json.loads(json.dumps(GOOD))
    d.update(changes)
    return d


class ValidateTests(unittest.TestCase):
    def test_good(self):
        card = mc.validate(data())
        self.assertEqual(card["link"], card["qr"])
        self.assertEqual(card["tagline"]["pl"], "Юрист")  # missing language falls back to ru
        self.assertEqual(card["tagline"]["en"], "Lawyer")

    def test_consent_required(self):
        for value in (False, None, "yes", 1):
            with self.assertRaises(mc.CardError):
                mc.validate(data(consent=value))
        bad = data(); del bad["consent"]
        with self.assertRaises(mc.CardError):
            mc.validate(bad)

    def test_only_plain_https(self):
        for url in ("http://a.pl", "javascript:alert(1)", "https://u:p@a.pl", "//a.pl", "", None, "https://" + "a" * 2100):
            with self.assertRaises(mc.CardError, msg=url):
                mc.validate(data(qr_url=url))
        with self.assertRaises(mc.CardError):
            mc.validate(data(name_link="http://a.pl"))

    def test_slug(self):
        for slug in ("", "../x", "A b", "-a", "a/b", "x" * 80):
            with self.assertRaises(mc.CardError, msg=slug):
                mc.validate(data(slug=slug))

    def test_limits_and_languages(self):
        with self.assertRaises(mc.CardError):
            mc.validate(data(name="x" * 81))
        with self.assertRaises(mc.CardError):
            mc.validate(data(tagline={"ru": "x" * 91}))
        with self.assertRaises(mc.CardError):
            mc.validate(data(description={"de": "Hallo"}))
        with self.assertRaises(mc.CardError):
            mc.validate(data(tagline={"ru": "  "}))
        with self.assertRaises(mc.CardError):
            mc.validate(data(tagline={}))


class RenderTests(unittest.TestCase):
    def build(self, **changes):
        with tempfile.TemporaryDirectory() as d:
            path = mc.build(data(**changes), d)
            self.assertTrue((Path(d) / "mascot.webp").is_file())
            return path.read_text(encoding="utf-8")

    def test_fields_present_and_template_defaults_gone(self):
        page = self.build()
        self.assertIn("<title>Anna K. — цифровая визитка</title>", page)
        self.assertIn('data-i18n="tagline">Юрист</div>', page)
        self.assertIn("https://example.org/a?x=1\\u0026y=2", page)
        self.assertNotIn("atlas_smart_library_bot?profile", page)
        self.assertEqual(len(re.findall(r"const overrides=", page)), 1)

    def test_hostile_text_cannot_break_out(self):
        evil = '</script><script>alert(1)</script>"><img src=x onerror=alert(2)>'
        page = self.build(name=evil[:80], tagline={"ru": evil[:90]}, description={"ru": evil[:200]})
        self.assertEqual(page.count("</script>"), 1)  # only the template's own closing tag
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<script>alert", page)

    def test_template_drift_is_reported(self):
        with self.assertRaises(mc.CardError):
            mc.render("<html></html>", mc.validate(data()))

    def test_ambiguous_template_is_reported(self):
        template = (Path(mc.__file__).parent / "index.html").read_text(encoding="utf-8")
        with self.assertRaises(mc.CardError):
            mc.render(template.replace("</head>", "<title>second</title></head>"), mc.validate(data()))

    def test_cli_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ok, bad = Path(d, "ok.json"), Path(d, "bad.json")
            ok.write_text(json.dumps(GOOD), encoding="utf-8")
            bad.write_text(json.dumps(data(consent=False)), encoding="utf-8")
            self.assertEqual(mc.main(["x", str(ok), str(Path(d, "out"))]), 0)
            self.assertEqual(mc.main(["x", str(bad), str(Path(d, "out2"))]), 1)
            self.assertFalse(Path(d, "out2").exists())
            self.assertEqual(mc.main(["x", str(Path(d, "missing.json"))]), 1)
            self.assertEqual(mc.main(["x"]), 2)


if __name__ == "__main__":
    unittest.main()
