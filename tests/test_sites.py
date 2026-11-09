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
                                "  # комментарий\n\nhttps://blog.example.com/news\nlanding.ru")
        self.assertEqual(got, [
            {"key": "shop", "url": "https://shop.ru/", "options": {"max_rps": 0.8, "ignore_robots": True}},
            {"key": "blog-example-com-news", "url": "https://blog.example.com/news", "options": {}},
            {"key": "landing-ru", "url": "https://landing.ru", "options": {}},
        ])

    def test_unknown_option(self):
        with self.assertRaises(SystemExit):
            sites.parse_sites("shop=https://shop.ru/ speed=fast")

    @mock.patch.dict(os.environ, {"SITES": "a=https://a.ru/\nb=https://b.ru/ max_pages=5"})
    def test_select(self):
        self.assertEqual([s["key"] for s in sites.select("")], ["a", "b"])
        self.assertEqual(sites.select("b")[0]["options"], {"max_pages": 5})
        self.assertEqual(sites.select("https://a.ru")[0]["key"], "a")
        adhoc = sites.select("https://new.ru/")[0]
        self.assertEqual((adhoc["key"], adhoc.get("adhoc")), ("new-ru", True))
        with self.assertRaises(SystemExit):
            sites.select("unknown")

    @mock.patch.dict(os.environ, {"SITES": ""})
    def test_no_sites(self):
        self.assertEqual(sites.select(""), [])


if __name__ == "__main__":
    unittest.main()
