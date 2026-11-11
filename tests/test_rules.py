"""Самопроверка правил: ловят то, что должны, и не ловят нормальный текст.

    python -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # корень репозитория
from checks.content.links import normalize, where  # noqa: E402
from checks.content.typography import PATTERNS  # noqa: E402
from checks.core.crawler import PageParser  # noqa: E402


def hits(rule, text):
    return [m.group() for m in PATTERNS[rule][2].finditer(text)]


class TypographyTest(unittest.TestCase):
    def assertCatches(self, rule, text, fragment):
        self.assertIn(fragment, hits(rule, text), f"{rule} не поймал «{fragment}» в «{text}»")

    def assertClean(self, rule, text):
        self.assertEqual(hits(rule, text), [], f"{rule} ложно сработал на «{text}»")

    def test_hyphen_as_dash(self):
        self.assertCatches("hyphen_as_dash", "понедельник - пятница", "понедельник - пятница")
        self.assertClean("hyphen_as_dash", "понедельник — пятница")
        self.assertClean("hyphen_as_dash", "IT-компания из Калуги")

    def test_space_before_punct(self):
        self.assertCatches("space_before_punct", "Привет , мир", "Привет ,")
        self.assertClean("space_before_punct", "Цена 1 500 руб.")

    def test_no_space_after_comma(self):
        self.assertCatches("no_space_after_comma", "яблоки,груши", "яблоки,груши")
        self.assertClean("no_space_after_comma", "3,14")

    def test_repeated_word(self):
        self.assertCatches("repeated_word", "мы мы пришли", "мы мы")
        self.assertClean("repeated_word", "мы пришли")

    def test_mixed_alphabet(self):
        self.assertCatches("mixed_alphabet", "Cайт", "Cайт")  # первая C латинская
        self.assertClean("mixed_alphabet", "Сайт и site")

    def test_straight_quotes(self):
        self.assertCatches("straight_quotes", 'ООО "Ромашка"', '"Ромашка"')
        self.assertClean("straight_quotes", "ООО «Ромашка»")

    def test_double_punct(self):
        self.assertCatches("double_punct", "итак,, начнём", ",,")
        self.assertCatches("double_punct", "конец фразы,. Начало", ",.")
        self.assertClean("double_punct", "и т. д.")
        for ok in ("АО «ЭКОН» и др., 2 ВУЗа", "и т. д., а также", "г. Калуга, ул. Ленина, д. 5, кв. 1"):
            self.assertClean("double_punct", ok)

    def test_number_range(self):
        self.assertCatches("number_range_hyphen", "с 10-20 мая", "10-20")
        self.assertClean("number_range_hyphen", "+7 (4842) 555-35-35")


class LinkLocationTest(unittest.TestCase):
    HTML = ('<html><body><header class="top line"><div class="user"><img src="/i.png"><br>'
            '<a href="">Профиль</a></div></header>'
            '<main><p>Текст <a href="https://site.ru/x/?a=1">тут</a></p></main>'
            '<footer id="f"><a href="tel:123">звонок</a></footer></body></html>')

    def links(self):
        p = PageParser()
        p.feed(self.HTML)
        return {lk["text"] or lk["tag"]: lk for lk in p.links}

    def test_block_and_path(self):
        lk = self.links()
        self.assertEqual((lk["Профиль"]["area"], lk["Профиль"]["path"]), ("шапка", "header.top div.user a"))
        self.assertEqual(lk["тут"]["area"], "содержимое")
        self.assertEqual(lk["звонок"]["path"], "footer#f a")

    def test_devtools_selector_without_own_domain(self):
        lk = self.links()
        self.assertEqual(where(lk["Профиль"]), 'шапка · `header.top div.user a[href=""]`')
        self.assertEqual(where(lk["тут"]), 'содержимое · `main p a[href$="/x/?a=1"]`')

    def test_generated_ids_skipped(self):
        from checks.core.crawler import node_token
        self.assertEqual(node_token("div", {"id": "bx_basketFKauiI", "class": "cart"}), "div.cart")
        self.assertEqual(node_token("div", {"id": "header-cart-line"}), "div#header-cart-line")

    def test_locator_survives_tricky_html(self):
        p = PageParser()
        p.feed('<ul class="m"><li><a href="">1</a><li class="md:flex x"><a href="https://s.ru/d#top">2</a></ul>')
        one, two = p.links
        self.assertEqual(two["path"], "ul.m li.x a")
        self.assertEqual(where(two), '`ul.m li.x a[href$="/d#top"]`')

    def test_locator_edge_cases(self):
        p = PageParser()
        p.feed('<main><p>Вступление<div><a href="https://s.ru">a</a><a href="/f/a\\b">b</a>'
               '<a href="/' + 'x' * 100 + '">c</a></div></main>')
        root, slash, long = p.links
        self.assertEqual(root["path"], "main div a")
        self.assertEqual(where(root), "содержимое · `main div a`")
        self.assertEqual(where(slash), "содержимое · `main div a`")
        self.assertEqual(where(long), 'содержимое · `main div a[href^="/' + 'x' * 79 + '"]`')

    def test_siblings_and_depth_limit(self):
        p = PageParser()
        p.feed('<dl><dt>Термин<dd><a href="">x</a></dl>' + '<div>' * 300 + '<a href="">y</a>')
        dd, deep = p.links
        self.assertEqual(dd["path"], "dl dd a")
        self.assertTrue(deep["path"].endswith("div a"))

    def test_old_crawl_without_location_falls_back_to_text(self):
        self.assertEqual(where({"tag": "a", "raw": "", "text": "Профиль"}), "Профиль")


class LinksTest(unittest.TestCase):
    BASE = "https://example.ru/page/"

    def rule(self, href):
        return normalize(href, self.BASE)[1]

    def test_bad_hrefs(self):
        self.assertEqual(self.rule(""), "bad_href")
        self.assertEqual(self.rule("+7 (4842) 55-55-55"), "bad_href")
        self.assertEqual(self.rule("www.site.ru"), "bad_href")
        self.assertEqual(self.rule("info@site.ru"), "bad_href")
        self.assertEqual(self.rule("mailto:info@"), "bad_href")
        self.assertEqual(self.rule("tel:123"), "bad_href")
        self.assertEqual(self.rule("https:/site.ru"), "bad_href")
        self.assertEqual(self.rule("#"), "placeholder_href")

    def test_good_hrefs(self):
        for href in ("/about/", "https://site.ru/", "mailto:info@site.ru", "tel:+74842555555", "#contacts"):
            self.assertEqual(self.rule(href), "", href)
        self.assertEqual(normalize("../x", self.BASE)[0], "https://example.ru/x")


if __name__ == "__main__":
    unittest.main()
