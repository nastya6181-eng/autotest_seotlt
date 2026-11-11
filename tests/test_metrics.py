"""История прогонов и расчёты дашборда — без сети, на подставных данных."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # корень репозитория
from checks.core import dashboard, history  # noqa: E402

TODAY = dt.datetime(2026, 11, 11, 12, 0, tzinfo=dt.timezone.utc)


def summary(project, key, started, errors=1, warnings=2, by_rule=None):
    return {"project": project, "project_key": key, "started_at": started, "url": "https://secret.example/",
            "pages": 5, "pages_failed": 1, "urls_checked": 40, "duration_s": 12.5, "failed": True,
            "rules_failed": 2, "rules_total": 10,
            "findings_unique": {"error": errors, "warning": warnings, "info": 3},
            "by_rule": by_rule if by_rule is not None else {"spelling": 2, "broken_link": 1}}


def write_collected(root, summaries):
    for i, s in enumerate(summaries):
        d = os.path.join(root, f"report-{i}")
        os.makedirs(d)
        with open(os.path.join(d, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(s, f)


def issue(number, created, closed=None, labels=()):
    return {"number": number, "title": f"t{number}", "html_url": f"https://gh/{number}",
            "created_at": created, "closed_at": closed, "state": "closed" if closed else "open",
            "labels": [{"name": n} for n in labels]}


def run(name, conclusion, started, minutes=5, reason=None, status="completed"):
    end = dt.datetime.fromisoformat(started.replace("Z", "+00:00")) + dt.timedelta(minutes=minutes)
    return {"name": name, "conclusion": conclusion, "status": status, "run_started_at": started,
            "created_at": started, "updated_at": end.isoformat(), "html_url": "https://gh/run",
            "display_title": name, "reason": reason}


class HistoryTest(unittest.TestCase):
    def test_record_content_site(self):
        r = history.record(summary("innotech", "innotech", "2026-11-10 10:00"), "content", "42", "https://run")
        self.assertEqual((r["site"], r["page"], r["run_id"]), ("innotech", None, "42"))
        self.assertEqual((r["errors"], r["warnings"], r["info"]), (1, 2, 3))
        self.assertNotIn("url", r)

    def test_record_design_splits_site_and_page(self):
        r = history.record(summary("innotech · main", "innotech-main", "2026-11-10 10:00"), "design")
        self.assertEqual((r["site"], r["page"]), ("innotech", "main"))

    def test_append_then_load_skips_repeated_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            col, out = os.path.join(tmp, "collected"), os.path.join(tmp, "h", "runs.jsonl")
            write_collected(col, [summary("a", "a", "2026-11-10 10:00"), summary("b", "b", "2026-11-09 10:00")])
            self.assertEqual(len(history.append(col, out, "content", "7")), 2)
            history.append(col, out, "content", "7")
            rows = history.load(os.path.dirname(out))
            self.assertEqual([r["site"] for r in rows], ["b", "a"])

    def test_append_without_reports_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "h", "runs.jsonl")
            self.assertEqual(history.append(tmp, out, "content"), [])
            self.assertFalse(os.path.exists(out))

    def test_legacy_csv_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "innotech.csv"), "w", encoding="utf-8") as f:
                f.write("date,run,pages,pages_failed,urls,errors,warnings,info,failed,spelling,dash\n")
                f.write('"2026-11-09 13:39","99",10,2,300,10,179,54,true,5,\n')
            [r] = history.load(tmp)
            self.assertEqual((r["site"], r["run_id"], r["errors"], r["failed"]), ("innotech", "99", 10, True))
            self.assertEqual(r["by_rule"], {"spelling": 5})


class IssuesMetricsTest(unittest.TestCase):
    def setUp(self):
        self.m = dashboard.issues_metrics([
            issue(1, "2026-10-01T10:00:00Z", labels=["site-fix", "site:innotech"]),
            issue(2, "2026-11-05T10:00:00Z", "2026-11-07T10:00:00Z", labels=["design"]),
            issue(3, "2026-11-10T10:00:00Z", labels=["site-fix"]),
        ], today=TODAY)

    def test_totals(self):
        self.assertEqual((self.m["total_open"], self.m["opened_7d"], self.m["closed_7d"]), (2, 2, 1))
        self.assertEqual(self.m["median_close_days"], 2.0)

    def test_weeks_and_open_at(self):
        self.assertEqual(len(self.m["weeks"]), dashboard.WEEKS)
        self.assertEqual(self.m["weeks"][-1], "2026-11-09")
        self.assertEqual(self.m["opened"][-2:], [1, 1])
        self.assertEqual(self.m["closed"][-2:], [1, 0])
        self.assertEqual(self.m["open_at"][-2:], [1, 2])

    def test_sla_overdue_only_for_old_site_fix(self):
        overdue = {o["number"]: o["overdue"] for o in self.m["oldest"]}
        self.assertEqual(overdue, {1: True, 3: False})
        self.assertEqual(self.m["overdue"], 1)

    def test_labels(self):
        self.assertEqual(self.m["labels"]["site-fix"], {"open": 2, "closed": 0})
        self.assertEqual(self.m["labels"]["design"], {"open": 0, "closed": 1})
        self.assertIn("site:innotech", self.m["labels"])


class RunsMetricsTest(unittest.TestCase):
    def test_failure_reason(self):
        tests_only = [{"steps": [{"name": "Тест: орфография", "conclusion": "failure"}]}]
        crawl = [{"steps": [{"name": "Тест: ссылки", "conclusion": "failure"},
                            {"name": "Обход сайта", "conclusion": "failure"}]}]
        self.assertEqual(dashboard.failure_reason(tests_only), "defects")
        self.assertEqual(dashboard.failure_reason(crawl), "infra")
        self.assertEqual(dashboard.failure_reason([]), "infra")

    def test_counts_by_outcome_and_window(self):
        m = dashboard.runs_metrics([
            run("Common checks", "success", "2026-11-10T10:00:00Z", minutes=4),
            run("Common checks", "failure", "2026-11-09T10:00:00Z", minutes=6, reason="defects"),
            run("Common checks", "failure", "2026-11-08T10:00:00Z", reason="infra"),
            run("Common checks", "cancelled", "2026-11-07T10:00:00Z"),
            run("Common checks", None, "2026-11-11T10:00:00Z", status="in_progress"),
            run("Common checks", "success", "2026-09-01T10:00:00Z"),
        ], today=TODAY)
        c = m["by_workflow"]["Common checks"]
        self.assertEqual((c["success"], c["defects"], c["infra"], c["other"]), (1, 1, 1, 1))
        self.assertEqual(c["median_min"], 5.0)

    def test_dependabot_runs_grouped(self):
        m = dashboard.runs_metrics([
            run("pip in /. - Update #123", "success", "2026-11-10T10:00:00Z"),
            run("github_actions in /. - Update #124", "success", "2026-11-10T11:00:00Z"),
        ], today=TODAY)
        self.assertEqual(list(m["by_workflow"]), ["Dependabot"])
        self.assertEqual(m["by_workflow"]["Dependabot"]["success"], 2)


class QualityMetricsTest(unittest.TestCase):
    def test_series_per_site_and_page_with_heatmap(self):
        rows = [history.record(summary("innotech", "innotech", f"2026-11-0{d} 10:00", errors=d,
                                       by_rule={"spelling": d, "dash": 0}), "content", str(d)) for d in (1, 2)]
        rows.append(history.record(summary("innotech · main", "innotech-main", "2026-11-03 10:00"), "design", "3"))
        q = {(s["workflow"], s["name"]): s for s in dashboard.quality_metrics(rows)}
        content = q[("content", "innotech")]
        self.assertEqual(content["errors"], [1, 2])
        self.assertEqual(content["defects"], [3, 4])
        self.assertEqual(content["heat"]["rules"], [{"rule": "spelling", "counts": [1, 2]}])
        self.assertIn(("design", "innotech · main"), q)


class SummaryTest(unittest.TestCase):
    def test_empty_data(self):
        self.assertIn("Данных пока нет", dashboard.summary_md({"quality": [], "issues": None, "runs": None}))


if __name__ == "__main__":
    unittest.main()
