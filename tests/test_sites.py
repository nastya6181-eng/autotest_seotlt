"""Разбор SITES (ключ, адрес, опции) и выбор сайта по SITE."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # корень репозитория
os.environ.pop("REPORT_FULL_URLS", None)  # тесты режима по умолчанию; полные адреса — в своём тесте
from checks.core import sites  # noqa: E402


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

    @mock.patch.dict(os.environ, {"SITES": "", "SITE_INNO_TECH": "https://a.ru/ max_rps=0.8",
                                  "SITE_SHOP": "shop.ru", "SITE_EMPTY": " "})
    def test_per_site_vars(self):
        got = {s["key"]: s for s in sites.select("")}
        self.assertEqual(sorted(got), ["inno-tech", "shop"])
        self.assertEqual(got["inno-tech"]["options"], {"max_rps": 0.8})
        self.assertEqual(sites.select("shop")[0]["url"], "https://shop.ru")

    @mock.patch.dict(os.environ, {"SITES": "shop=https://other.ru/", "SITE_SHOP": "https://shop.ru/"})
    def test_same_key_in_both_sources_rejected(self):
        with self.assertRaises(SystemExit):
            sites.select("")

    def test_list_sites_reads_only_site_secrets(self):
        import json
        import subprocess
        env = {k: v for k, v in os.environ.items() if not k.startswith("SITE")}
        env["SECRETS_JSON"] = json.dumps({"SITE_A": "https://a.ru/ max_pages=5", "github_token": "x",
                                          "OTHER": "https://leak.ru/"})
        script = os.path.join(os.path.dirname(__file__), "..", "checks", "core", "list_sites.py")
        out = json.loads(subprocess.run([sys.executable, script], env=env, capture_output=True,
                                        text=True, check=True).stdout)
        self.assertEqual(out, [{"key": "a", "secret": "SITE_A", "url": ""}])
        masks = subprocess.run([sys.executable, script, "--mask"], env=env, capture_output=True,
                               text=True, check=True).stdout
        self.assertIn("::add-mask::a.ru", masks)
        self.assertNotIn("leak.ru", masks)

    @mock.patch.dict(os.environ, {"SITES": ""})
    def test_no_sites(self):
        self.assertEqual(sites.select(""), [])


if __name__ == "__main__":
    unittest.main()
