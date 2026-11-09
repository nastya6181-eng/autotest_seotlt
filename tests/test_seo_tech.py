"""Разбор метаданных страницы и robots.txt."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from sitecheck import seo  # noqa: E402
from sitecheck.crawler import Page, PageParser  # noqa: E402
from sitecheck.tech import robots_blocks_all  # noqa: E402

HTML = """<html lang="ru"><head><title>Главная — Компания</title>
<meta name="description" content="Описание"><meta name="robots" content="noindex, follow">
<link rel="canonical" href="https://site.ru/"><script src="http://cdn.site.ru/a.js"></script></head>
<body><svg><title>иконка</title></svg><h1>Привет</h1><img src="/a.png"><img src="/b.png" alt="">
<a href="http://other.ru/">ссылка по http — не смешанный контент</a></body></html>"""


def parse(html, url="https://site.ru/"):
    p = PageParser()
    p.feed(html)
    return Page(url, p.text(), p.links, p.ids, p.meta)


class SeoTest(unittest.TestCase):
    def test_meta(self):
        m = parse(HTML).meta
        self.assertEqual(m["title"], "Главная — Компания")
        self.assertEqual((m["description"], m["lang"], m["h1"]), ("Описание", "ru", 1))
        self.assertEqual(m["img_no_alt"], ["/a.png"])

    def test_rules(self):
        page = parse(HTML)
        bare = parse("<html><body><p>текст</p></body></html>", "https://site.ru/x")
        twin = parse(HTML, "https://site.ru/copy")
        rules = {f.rule for f in seo.run([page, bare, twin], {}, {}, {})}
        self.assertTrue({"noindex", "mixed_content", "img_no_alt", "missing_title", "missing_h1",
                         "missing_description", "missing_lang", "duplicate_title"} <= rules)
        mixed = [f.fragment for f in seo.run([page], {}, {}, {}) if f.rule == "mixed_content"]
        self.assertEqual(mixed, ["http://cdn.site.ru/a.js"])


class RelativeTest(unittest.TestCase):
    def test_relative(self):
        from sitecheck.report import relative
        self.assertEqual(relative("https://www.site.ru/a/?x=1", "https://site.ru/"), "/a/?x=1")
        self.assertEqual(relative("https://other.ru/a", "https://site.ru/"), "https://other.ru/a")
        for text in ("//[broken", "http://[broken", "понедельник - пятница"):
            self.assertEqual(relative(text, "https://site.ru/"), text)

    def test_scrub(self):
        from sitecheck.report import scrub
        self.assertEqual(scrub("Пишите: https://www.site.ru/contacts/ или site.ru", "https://site.ru/"),
                         "Пишите: /contacts/ или")
        self.assertNotIn("\n", scrub("a\n::error::forged", "https://site.ru/"))


class RobotsTest(unittest.TestCase):
    def test_blocks_all(self):
        self.assertEqual(robots_blocks_all("User-agent: *\nDisallow: /"), {"*"})
        self.assertEqual(robots_blocks_all("User-agent: Yandex\nUser-agent: *\nDisallow: /\n"), {"*", "yandex"})

    def test_open(self):
        self.assertEqual(robots_blocks_all("User-agent: *\nDisallow: /bitrix/\nDisallow: /search/"), set())
        self.assertEqual(robots_blocks_all("User-agent: *\nDisallow:"), set())
        self.assertEqual(robots_blocks_all("User-agent: *\nDisallow: /\nAllow: /catalog/"), set())
        self.assertEqual(robots_blocks_all("User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nDisallow: /tmp/"), set())


if __name__ == "__main__":
    unittest.main()
