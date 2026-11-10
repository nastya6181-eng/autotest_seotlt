"""Отчёты: пишутся только в свою папку, содержат ссылки на страницы и подсказки."""
import hashlib
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)  # корень репозитория
os.environ.pop("REPORT_FULL_URLS", None)  # тесты режима по умолчанию; полные адреса — в своём тесте
from checks.core import report  # noqa: E402
from checks.core.findings import Finding  # noqa: E402

RULES = {"seo.missing_h1": ("warning", "Нет заголовка H1"), "links.redirect": ("info", "Редирект"),
         "typography.hyphen_as_dash": ("warning", "Дефис вместо тире")}
FINDINGS = [
    Finding("seo", "missing_h1", "warning", "Нет заголовка H1", "", "https://site.ru/a/"),
    Finding("typography", "hyphen_as_dash", "warning", "Дефис вместо тире", "пн - пт", "https://site.ru/b/", "часы пн - пт"),
    Finding("links", "redirect", "info", "Редирект 301", "https://site.ru/c", "https://site.ru/b/", "c"),
]
META = {"project": "t", "project_key": "t", "url": "https://site.ru/", "started_at": "now", "duration_s": 1,
        "pages": 2, "pages_failed": 0, "run_url": ""}


def code_digest():
    h = hashlib.sha256()
    for d, _, files in os.walk(os.path.join(ROOT, "checks")):
        for name in sorted(files):
            if name.endswith(".py"):
                with open(os.path.join(d, name), "rb") as f:
                    h.update(f.read())
    return h.hexdigest()


class ReportTest(unittest.TestCase):
    def test_writes_only_into_out_dir(self):
        from unittest import mock
        before, cwd = code_digest(), os.getcwd()
        with tempfile.TemporaryDirectory() as out, mock.patch.dict(os.environ, {"REPORT_FULL_URLS": ""}):
            os.chdir(ROOT)
            try:
                report.write_all(out, META, FINDINGS, RULES, ["error", "warning"])
            finally:
                os.chdir(cwd)
            self.assertEqual(sorted(os.listdir(out)),
                             ["findings.csv", "junit.xml", "report.md", "summary.json", "summary.md"])
            page = open(os.path.join(out, "summary.md"), encoding="utf-8").read()
        self.assertEqual(code_digest(), before, "отчёт перезаписал файл кода")
        self.assertIn("| /b/ | пн - пт | часы пн - пт |", page)
        self.assertIn("| /a/ | — |", page)
        self.assertIn("**Как исправить:**", page)
        self.assertIn("Правило в коде: `checks/content/seo.py:", page)

    def test_full_urls_are_clickable(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as out, mock.patch.dict(os.environ, {"REPORT_FULL_URLS": "true"}):
            report.write_all(out, META, FINDINGS, RULES, ["error", "warning"])
            page = open(os.path.join(out, "summary.md"), encoding="utf-8").read()
        self.assertIn("[/b/](https://site.ru/b/)", page)
        self.assertIn("[пн - пт](https://site.ru/b/#:~:text=%D0%BF%D0%BD%20%2D%20%D0%BF%D1%82)", page)

    def test_log_lists_pages_and_how_to_find(self):
        twice = [Finding("typography", "hyphen_as_dash", "warning", "Дефис вместо тире", "пн - пт", u, "часы пн - пт")
                 for u in ("https://site.ru/", "https://site.ru/b/", "https://site.ru/c/")]
        log = report.format_test_log("typography", {"typography.hyphen_as_dash": RULES["typography.hyphen_as_dash"]},
                                     twice, ["warning"], base="https://site.ru/")
        self.assertIn("✘ / (главная)", log)
        self.assertIn("то же ещё на 2 стр.: /b/, /c/", log)
        self.assertIn("найти:    Ctrl+F «пн - пт»", log)

    def test_page_level_reason_is_kept(self):
        failed = Finding("links", "page_failed", "error", "Страница не открылась: 403", "", "https://site.ru/x/")
        rules = {"links.page_failed": ("error", "Страница сайта не открылась при обходе")}
        log = report.format_test_log("links", rules, [failed], ["error"], base="https://site.ru/")
        self.assertIn("почему:   Страница не открылась: 403", log)
        text = report.summary_text({**META, "failed": True, "fail_on": ["error"], "findings_unique": {"error": 1},
                                    "by_rule": {"links.page_failed": 1}}, rules, report.group([failed]), 200)
        self.assertIn("Страница не открылась: 403", text)

    def test_summary_fits_github_limit(self):
        many = [Finding("spelling", "unknown_word", "warning", "Слово", f"слово{i}" * 10,
                        f"https://site.ru/{'p' * 200}{i}/", "к" * 160) for i in range(3000)]
        rules = {"spelling.unknown_word": ("warning", "Слово")}
        summary = report.build_summary(META, many, rules, ["warning"])
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "s.md")
            report.write_step_summary(path, summary, rules, report.group(many))
            self.assertLessEqual(os.path.getsize(path), report.MAX_SUMMARY_BYTES)

    def test_test_log_marks_rules(self):
        log = report.format_test_log("seo", {"seo.missing_h1": RULES["seo.missing_h1"],
                                             "seo.noindex": ("error", "noindex")},
                                     FINDINGS[:1], ["error", "warning"], base="https://site.ru/")
        self.assertIn("✘ seo.missing_h1", log)
        self.assertIn("✔ seo.noindex", log)
        self.assertIn("✘ /a/", log)
        self.assertIn("Правило в коде: checks/content/seo.py:", log)


if __name__ == "__main__":
    unittest.main()
