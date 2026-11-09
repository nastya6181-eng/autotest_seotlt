"""Отчёты прогона: report.md, summary.md, findings.csv, summary.json, junit.xml."""
import csv
import json
import os
from collections import Counter, defaultdict
from xml.sax.saxutils import escape, quoteattr

SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
SEV_TITLE = {"error": "Ошибки", "warning": "Предупреждения", "info": "К сведению"}
MAX_ROWS = 200


def cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def group(findings):
    """Одна строка из шапки или подвала повторяется на многих страницах — сворачиваем."""
    groups = {}
    for f in findings:
        g = groups.setdefault((f.rule_id, f.fragment), {"f": f, "pages": []})
        if f.page not in g["pages"]:
            g["pages"].append(f.page)
    return sorted(groups.values(),
                  key=lambda g: (SEV_ORDER[g["f"].severity], g["f"].rule_id, -len(g["pages"])))


def build_summary(meta, findings, rules, fail_on):
    active = [f for f in findings if f.severity != "off"]
    by_sev = Counter(f.severity for f in active)
    uniq = Counter(g["f"].severity for g in group(active))
    by_rule = Counter(f.rule_id for f in active)
    failed = any(uniq[s] for s in fail_on) or meta["pages"] == 0
    return {
        **meta,
        "failed": failed,
        "fail_on": list(fail_on),
        "findings_total": dict(by_sev),
        "findings_unique": dict(uniq),
        "by_rule": {r: by_rule.get(r, 0) for r in rules},
    }


def write_csv(path, findings):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["уровень", "проверка", "правило", "описание", "фрагмент", "страница", "контекст"])
        for x in sorted(findings, key=lambda x: (SEV_ORDER[x.severity], x.rule_id)):
            wr.writerow([x.severity, x.check, x.rule, x.message, x.fragment, x.page, x.context])


def write_markdown(path, summary, groups):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {summary['project']}: {summary['url']}\n\n")
        f.write(f"Прогон {summary['started_at']}, страниц {summary['pages']}, "
                f"адресов проверено {summary.get('urls_checked', 0)}. "
                f"Итог: {'**есть ошибки**' if summary['failed'] else 'ошибок нет'}.\n\n")
        for sev in ("error", "warning", "info"):
            rows = [g for g in groups if g["f"].severity == sev]
            if not rows:
                continue
            f.write(f"## {SEV_TITLE[sev]} ({len(rows)})\n\n"
                    "| правило | описание | фрагмент | страниц | пример | контекст |\n"
                    "|---|---|---|---|---|---|\n")
            for g in rows[:MAX_ROWS]:
                x = g["f"]
                f.write(f"| {x.rule_id} | {cell(x.message)} | `{cell(x.fragment)[:120]}` | "
                        f"{len(g['pages'])} | {g['pages'][0]} | {cell(x.context)[:160]} |\n")
            if len(rows) > MAX_ROWS:
                f.write(f"\nЕщё {len(rows) - MAX_ROWS} строк — в findings.csv.\n")
            f.write("\n")


def write_step_summary(path, summary, rules):
    """Короткая сводка для страницы прогона в GitHub Actions."""
    u = summary["findings_unique"]
    icon = "❌" if summary["failed"] else "✅"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"### {icon} {summary['project']} — {summary['url']}\n\n"
                f"Страниц: {summary['pages']} · адресов: {summary.get('urls_checked', 0)} · "
                f"ошибок: {u.get('error', 0)} · предупреждений: {u.get('warning', 0)} · "
                f"к сведению: {u.get('info', 0)} · {summary['duration_s']} с\n\n"
                "| правило | уровень | замечаний |\n|---|---|---|\n")
        for rule, n in sorted(summary["by_rule"].items(), key=lambda kv: -kv[1]):
            if n:
                f.write(f"| {rules[rule][1]} (`{rule}`) | {rules[rule][0]} | {n} |\n")
        f.write("\nПолный отчёт — в артефакте прогона.\n")


def write_junit(path, summary, groups, rules):
    """Правило = тест-кейс. Красный, если у правила есть замечания уровня из fail_on."""
    by_rule = defaultdict(list)
    for g in groups:
        by_rule[g["f"].rule_id].append(g)
    suites = defaultdict(list)
    for rule_id in rules:
        suites[rule_id.split(".")[0]].append(rule_id)
    parts = []
    for check, rule_ids in suites.items():
        cases, failures = [], 0
        for rule_id in rule_ids:
            sev, title = rules[rule_id]
            rows = by_rule.get(rule_id, [])
            name = quoteattr(f"{title} [{rule_id}]")
            classname = quoteattr(f"{summary['project_key']}.{check}")
            if sev == "off":
                cases.append(f'<testcase name={name} classname={classname}><skipped/></testcase>')
                continue
            details = "\n".join(f"{g['f'].fragment} — {g['pages'][0]} (страниц: {len(g['pages'])})"
                                for g in rows[:50])
            if rows and sev in summary["fail_on"]:
                failures += 1
                cases.append(f'<testcase name={name} classname={classname}>'
                             f'<failure message={quoteattr(f"{len(rows)} замечаний")}>'
                             f'{escape(details)}</failure></testcase>')
            else:
                out = f"<system-out>{escape(details)}</system-out>" if rows else ""
                cases.append(f'<testcase name={name} classname={classname}>{out}</testcase>')
        suite = quoteattr(f"{summary['project_key']}.{check}")
        parts.append(f'<testsuite name={suite} tests="{len(cases)}" failures="{failures}">'
                     + "".join(cases) + "</testsuite>")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>' + "".join(parts) + "</testsuites>\n")


def write_all(out_dir, meta, findings, rules, fail_on):
    os.makedirs(out_dir, exist_ok=True)
    active = [f for f in findings if f.severity != "off"]
    groups = group(active)
    summary = build_summary(meta, findings, rules, fail_on)
    write_csv(os.path.join(out_dir, "findings.csv"), active)
    write_markdown(os.path.join(out_dir, "report.md"), summary, groups)
    write_step_summary(os.path.join(out_dir, "summary.md"), summary, rules)
    write_junit(os.path.join(out_dir, "junit.xml"), summary, groups, rules)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary
