"""Отчёты: пишутся только в свою папку, содержат ссылки на страницы и подсказки."""
import hashlib
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))
from sitecheck import report  # noqa: E402
from sitecheck.findings import Finding  # noqa: E402

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
    for d, _, files in os.walk(os.path.join(ROOT, "common")):
        for name in sorted(files):
            if name.endswith(".py"):
                with open(os.path.join(d, name), "rb") as f:
                    h.update(f.read())
    return h.hexdigest()


class ReportTest(unittest.TestCase):
    def test_writes_only_into_out_dir(self):
        before, cwd = code_digest(), os.getcwd()
        with tempfile.TemporaryDirectory() as out:
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
        self.assertIn("Правило в коде: `common/sitecheck/seo.py:", page)

    def test_full_urls_are_clickable(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as out, mock.patch.dict(os.environ, {"REPORT_FULL_URLS": "true"}):
            report.write_all(out, META, FINDINGS, RULES, ["error", "warning"])
            page = open(os.path.join(out, "summary.md"), encoding="utf-8").read()
        self.assertIn("[/b/](https://site.ru/b/)", page)

    def test_test_log_marks_rules(self):
        log = report.format_test_log("seo", {"seo.missing_h1": RULES["seo.missing_h1"],
                                             "seo.noindex": ("error", "noindex")},
                                     FINDINGS[:1], ["error", "warning"], base="https://site.ru/")
        self.assertIn("✘ seo.missing_h1", log)
        self.assertIn("✔ seo.noindex", log)
        self.assertIn("✘ /a/", log)
        self.assertIn("Правило в коде: common/sitecheck/seo.py:", log)


if __name__ == "__main__":
    unittest.main()
