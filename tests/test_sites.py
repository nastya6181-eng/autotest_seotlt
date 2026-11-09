"""Разбор SITES (ключ, адрес, опции) и выбор сайта по SITE."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from sitecheck import sites  # noqa: E402


class SitesTest(unittest.TestCase):
    def test_parse(self):
        got = sites.parse_sites("shop=https://shop.ru/ max_rps=0.8 ignore_robots=true\n"
                                "  # комментарий\n\nblog=landing.ru")
        self.assertEqual(got, [
            {"key": "shop", "url": "https://shop.ru/", "options": {"max_rps": 0.8, "ignore_robots": True}},
            {"key": "blog", "url": "https://landing.ru", "options": {}},
        ])

    def test_bad_input(self):
        for raw in ("shop=https://shop.ru/ speed=fast", "shop=https://shop.ru/ max_pages=abc",
                    "shop=https://shop.ru/ max_rps=", "a=https://a.ru/\na=https://b.ru/",
                    "all=https://a.ru/", "https://no-key.ru/"):
            with self.assertRaises(SystemExit, msg=raw):
                sites.parse_sites(raw)

    @mock.patch.dict(os.environ, {"SITES": ""})
    def test_adhoc_keeps_options(self):
        adhoc = sites.select("https://new.ru/ max_rps=0.5")[0]
        self.assertEqual(adhoc["options"], {"max_rps": 0.5})
        self.assertEqual(sites.select(adhoc["adhoc"])[0]["options"], {"max_rps": 0.5})

    @mock.patch.dict(os.environ, {"SITES": "a=https://a.ru/\nb=https://b.ru/ max_pages=5"})
    def test_select(self):
        self.assertEqual([s["key"] for s in sites.select("")], ["a", "b"])
        self.assertEqual(sites.select("b")[0]["options"], {"max_pages": 5})
        self.assertEqual(sites.select("https://a.ru")[0]["key"], "a")
        adhoc = sites.select("https://new.ru/")[0]
        self.assertEqual((adhoc["key"], adhoc.get("adhoc")), ("new-ru", "https://new.ru/"))
        with self.assertRaises(SystemExit):
            sites.select("unknown")

    @mock.patch.dict(os.environ, {"SITES": "a=https://a.ru/ max_rps=0.8 cooldown=330"})
    def test_site_with_overrides_keeps_configured_options(self):
        for line in ("a max_pages=10", "https://a.ru/ max_pages=10"):
            got = sites.select(line)[0]
            self.assertEqual(got["key"], "a")
            self.assertEqual(got["options"], {"max_rps": 0.8, "cooldown": 330.0, "max_pages": 10})
            self.assertEqual(sites.select(got["adhoc"])[0]["options"], got["options"])

    @mock.patch.dict(os.environ, {"SITES": ""})
    def test_no_sites(self):
        self.assertEqual(sites.select(""), [])


if __name__ == "__main__":
    unittest.main()
