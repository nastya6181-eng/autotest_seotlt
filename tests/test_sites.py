"""Разбор SITES и выбор сайта по SITE."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from sitecheck import sites  # noqa: E402


class SitesTest(unittest.TestCase):
    def test_parse(self):
        got = sites.parse_sites("shop=https://shop.ru/\n  # комментарий\nhttps://blog.example.com/news, landing.ru")
        self.assertEqual(got, [
            {"key": "shop", "url": "https://shop.ru/"},
            {"key": "blog-example-com-news", "url": "https://blog.example.com/news"},
            {"key": "landing-ru", "url": "https://landing.ru"},
        ])

    def test_url_maps_to_project_folder(self):
        self.assertEqual(sites.parse_sites("https://www.lazun.com/")[0]["key"], "lazun")

    @mock.patch.dict(os.environ, {"SITES": "a=https://a.ru/\nb=https://b.ru/"})
    def test_select(self):
        self.assertEqual(len(sites.select("")), 2)
        self.assertEqual(sites.select("b"), [{"key": "b", "url": "https://b.ru/"}])
        self.assertEqual(sites.select("https://a.ru"), [{"key": "a", "url": "https://a.ru/"}])
        self.assertEqual(sites.select("https://new.ru/")[0]["url"], "https://new.ru/")
        with self.assertRaises(SystemExit):
            sites.select("unknown")

    @mock.patch.dict(os.environ, {"SITES": ""})
    def test_fallback_to_projects(self):
        self.assertIn("innotech", [s["key"] for s in sites.select("")])


if __name__ == "__main__":
    unittest.main()
