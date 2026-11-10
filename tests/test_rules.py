"""Самопроверка правил: ловят то, что должны, и не ловят нормальный текст.

    python -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # корень репозитория
from checks.content.links import normalize  # noqa: E402
from checks.content.typography import PATTERNS  # noqa: E402


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
