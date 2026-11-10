"""pages.yml: имена страниц, добавление страницы из SVG, перегенерация JSON."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from sitecheck import design_pages, sites  # noqa: E402

SVG = ('<svg width="1440" height="900"><text font-family="Montserrat" font-size="32" font-weight="600" fill="#1B2321">'
       '<tspan x="100" y="200">КАТАЛОГ</tspan></text></svg>')


class DesignPagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(sites, "PROJECTS", self.tmp.name)
        self.patch.start()
        os.makedirs(os.path.join(self.tmp.name, "shop", "design"))
        with open(os.path.join(self.tmp.name, "shop", "design", "pages.yml"), "w", encoding="utf-8") as f:
            f.write("# комментарий сохраняется\n- page: /\n  width: 1600\n  design: main-1600.json\n")
        self.svg = os.path.join(self.tmp.name, "Каталог.svg")
        with open(self.svg, "w", encoding="utf-8") as f:
            f.write(SVG)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_default_name_from_design_file(self):
        self.assertEqual([p["name"] for p in design_pages.load("shop")[1]], ["main-1600"])

    def test_add_then_prepare(self):
        stem, data = design_pages.add("shop", "catalog", "/catalog/", self.svg)
        self.assertEqual((stem, len(data["texts"])), ("catalog-1440", 1))
        base, pages = design_pages.load("shop")
        cat = pages[-1]
        self.assertEqual((cat["name"], cat["page"], cat["width"], cat["source"]),
                         ("catalog", "/catalog/", 1440, "src/catalog-1440.svg"))
        self.assertTrue(os.path.exists(os.path.join(base, "src", "catalog-1440.svg")))
        self.assertIn("# комментарий сохраняется", open(os.path.join(base, "pages.yml"), encoding="utf-8").read())
        report = design_pages.prepare("shop")
        self.assertTrue(any("✔ catalog" in r for r in report))
        self.assertTrue(any("– main-1600: исходника нет" in r for r in report))

    def test_add_rejects_bad_or_duplicate_name(self):
        for name in ("Каталог", "my page"):
            with self.assertRaises(SystemExit):
                design_pages.add("shop", name, "/x/", self.svg)
        for page in ("#contact", "catalog/", "/a/#b", "//other.example/catalog/"):
            with self.assertRaises(SystemExit):
                design_pages.add("shop", "contact", page, self.svg)
        design_pages.add("shop", "catalog", "/catalog/", self.svg)
        with self.assertRaises(SystemExit):
            design_pages.add("shop", "catalog", "/catalog/", self.svg)

    def test_select_unknown_page(self):
        with self.assertRaises(SystemExit):
            design_pages.select("shop", "nope")


if __name__ == "__main__":
    unittest.main()
