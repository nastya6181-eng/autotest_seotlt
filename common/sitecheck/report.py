"""Лог теста и отчёт прогона. Полный отчёт — на странице прогона (summary.md) и в логе каждого теста;
в артефакт идут findings.csv, report.md, summary.json и junit.xml.

REPORT_FULL_URLS=true — полные кликабельные адреса страниц (для приватного репозитория).
По умолчанию — пути (/about/), без домена.
"""
import csv
import json
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import escape, quoteattr

from .hints import hint, source

SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
SEV_TITLE = {"error": "Критично", "warning": "Дефект", "info": "Рекомендация"}
SEV_ICON = {"error": "🔴", "warning": "🟠", "info": "⚪"}
MAX_ROWS = 200


def full_urls():
    return os.environ.get("REPORT_FULL_URLS", "").lower() in ("1", "true", "yes")


def in_actions():
    return os.environ.get("GITHUB_ACTIONS") == "true"


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


def by_rule(groups):
    rules = defaultdict(list)
    for g in groups:
        rules[g["f"].rule_id].append(g)
    return sorted(rules.items(), key=lambda kv: (SEV_ORDER[kv[1][0]["f"].severity], -len(kv[1])))


def build_summary(meta, findings, rules, fail_on):
    active = [f for f in findings if f.severity != "off"]
    by_sev = Counter(f.severity for f in active)
    uniq = Counter(g["f"].severity for g in group(active))
    counts = Counter(f.rule_id for f in active)
    failed = any(uniq[s] for s in fail_on) or meta["pages"] == 0
    return {
        **meta,
        "failed": failed,
        "fail_on": list(fail_on),
        "findings_total": dict(by_sev),
        "findings_unique": dict(uniq),
        "by_rule": {r: counts.get(r, 0) for r in rules},
        "rules_total": sum(1 for sev, _ in rules.values() if sev != "off"),
        "rules_failed": sum(1 for r, (sev, _) in rules.items() if counts.get(r) and sev in fail_on),
    }


def relative(value, base):
    """Адрес своего сайта → путь (/about/)."""
    if not base or not value or not value.lower().startswith(("http://", "https://")):
        return value
    try:
        b, v = urlsplit(base), urlsplit(value)
    except ValueError:
        return value
    if v.netloc and v.netloc.lower().removeprefix("www.") == b.netloc.lower().removeprefix("www."):
        return urlunsplit(("", "", v.path or "/", v.query, v.fragment))
    return value


def scrub(text, base):
    """Одна строка (перевод строки в логе Actions — это команда); без домена своего сайта,
    если не включены полные адреса."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    host = urlsplit(base).netloc.lower().removeprefix("www.") if base and not full_urls() else ""
    if host:
        text = re.sub(rf"(?i)(?<![\w.-])(https?://)?(www\.)?{re.escape(host)}(?![\w-]|\.[\w-])", "", text).strip()
    return text.replace("::", ": :")


def show(url, base):
    """Адрес для публичных мест (лог, сводка, Checks): полный или путём своего сайта."""
    return scrub(url if full_urls() else relative(url, base), base) or "/"


def show_fragment(fragment, base):
    return show(fragment, base) if fragment.startswith(("http://", "https://")) else scrub(fragment, base)


# ─────────────────────────────── лог теста ───────────────────────────────

def format_test_log(name, rules, findings, fail_on, base="", limit=100):
    """Лог одного теста в стиле тест-раннера: правила ✔/✘, затем подробности по каждому правилу
    с замечаниями. В GitHub Actions подробности сворачиваются в группы, упавшие правила — аннотации."""
    gh = in_actions()
    rows_of = dict(by_rule(group([f for f in findings if f.severity != "off"])))
    lines = [f"━━━ Тест «{name}»: {len(rules)} правил ━━━"]
    failed = []
    width = max((len(r) for r in rules), default=10)
    for rule_id, (sev, title) in rules.items():
        rows = rows_of.get(rule_id, [])
        total = sum(len(g["pages"]) for g in rows)
        pages = len({p for g in rows for p in g["pages"]})
        if sev == "off":
            mark, tail = "–", "выключено"
        elif not rows:
            mark, tail = "✔", "ок"
        elif sev in fail_on:
            mark, tail = "✘", f"УПАЛО [{sev}] замечаний: {total}, страниц: {pages}"
            failed.append(rule_id)
        else:
            mark, tail = "•", f"[{sev}, на статус не влияет] замечаний: {total}, страниц: {pages}"
        lines.append(f"  {mark} {rule_id.ljust(width)}  {title} — {tail}")
    lines.append(f"Итог «{name}»: " + (f"упало {len(failed)} из {len(rules)} правил: {', '.join(failed)}"
                                       if failed else f"все {len(rules)} правил прошли"))

    for rule_id, rows in rows_of.items():
        sev, title = rules[rule_id]
        src, line = source(rule_id)
        head = f"{SEV_ICON[sev]} {rule_id} — {title}: {sum(len(g['pages']) for g in rows)}"
        lines.append(f"::group::{head}" if gh else f"\n{head}")
        lines.append(f"   Как исправить: {hint(rule_id)}")
        lines.append(f"   Правило в коде: {src}:{line}")
        shown = 0
        for g in rows:
            f, pages = g["f"], g["pages"]
            if shown >= limit:
                break
            if not f.fragment or f.fragment == f.page:
                for p in pages[:limit - shown]:
                    lines.append(f"   ✘ {show(p, base)}")
                    if f.message != title:
                        lines.append(f"       почему:   {scrub(f.message, base)[:160]}")
                    shown += 1
                continue
            shown += 1
            where = show(pages[0], base) + (f"  (+ ещё {len(pages) - 1} стр.)" if len(pages) > 1 else "")
            lines.append(f"   ✘ {where}")
            if f.fragment and f.fragment != f.page:
                lines.append(f"       что:      «{show_fragment(f.fragment, base)[:120]}»")
            if f.message != title:
                lines.append(f"       почему:   {scrub(f.message, base)[:160]}")
            if f.context and f.context != f.fragment:
                lines.append(f"       контекст: …{scrub(f.context, base)[:140]}…")
        rest = sum(len(g["pages"]) if not g["f"].fragment or g["f"].fragment == g["f"].page else 1 for g in rows) - shown
        if rest > 0:
            lines.append(f"   … и ещё {rest} — все в findings.csv (артефакт прогона)")
        if gh:
            lines.append("::endgroup::")
            if rule_id in failed:
                first = show(rows[0]["pages"][0], base)
                lines.append(f"::error file={src},line={line},title={rule_id}::"
                             f"{scrub(title, base)} — замечаний: {sum(len(g['pages']) for g in rows)}, например {first}. "
                             f"{scrub(hint(rule_id), base)}")
    return "\n".join(lines)


# ─────────────────────────────── отчёты ───────────────────────────────

def write_csv(path, findings):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["уровень", "проверка", "правило", "описание", "фрагмент", "страница", "контекст", "как исправить"])
        for x in sorted(findings, key=lambda x: (SEV_ORDER[x.severity], x.rule_id)):
            wr.writerow([x.severity, x.check, x.rule, x.message, x.fragment, x.page, x.context, hint(x.rule_id)])


def write_markdown(path, summary, groups):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {summary['project']}: {summary['url']}\n\n")
        f.write(f"Прогон {summary['started_at']}, страниц {summary['pages']}, "
                f"адресов проверено {summary.get('urls_checked', 0)}. "
                f"Итог: {'**есть дефекты**' if summary['failed'] else 'дефектов нет'}.\n\n")
        for rule_id, rows in by_rule(groups):
            x = rows[0]["f"]
            f.write(f"## {SEV_ICON[x.severity]} {rule_id} — {len(rows)}\n\n{hint(rule_id)}\n\n"
                    "| фрагмент | почему | страниц | пример | контекст |\n|---|---|---|---|---|\n")
            for g in rows[:MAX_ROWS]:
                y = g["f"]
                f.write(f"| `{cell(y.fragment)[:120]}` | {cell(y.message)[:160]} | {len(g['pages'])} | "
                        f"{g['pages'][0]} | {cell(y.context)[:160]} |\n")
            f.write("\n")


def link(url, base):
    """Страница в сводке: кликабельная ссылка при полных адресах, иначе путь."""
    shown = cell(show(url, base))[:150]
    if full_urls() and url.startswith("http") and len(url) <= 2000:
        return f"[{cell(relative(url, base))[:150]}]({url})"
    return shown


MAX_SUMMARY_BYTES = 900_000  # GitHub не показывает сводку шага больше 1 МиБ


def write_step_summary(path, summary, rules, groups=()):
    """Полный отчёт на странице прогона. Если не влезает в лимит GitHub — меньше строк на правило."""
    for limit in (200, 60, 20, 5):
        text = summary_text(summary, rules, groups, limit)
        if len(text.encode("utf-8")) <= MAX_SUMMARY_BYTES:
            break
    else:
        text = text.encode("utf-8")[:MAX_SUMMARY_BYTES].decode("utf-8", "ignore") \
            + "\n\n…отчёт обрезан по лимиту GitHub, полностью — findings.csv в артефакте прогона.\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def summary_text(summary, rules, groups, limit):
    """Правила, и по каждому с замечаниями — как исправить, страницы, фрагмент, контекст."""
    from io import StringIO
    f = StringIO()
    u = summary["findings_unique"]
    base = summary["url"]
    rows_of = dict(by_rule(groups))
    failed_rules = [r for r in rows_of if rules[r][0] in summary["fail_on"]]
    passed = [r for r, (sev, _) in rules.items() if sev != "off" and r not in rows_of]
    icon = "❌" if summary["failed"] else "✅"
    if True:
        f.write(f"## {icon} {summary['project']}\n\n"
                f"Страниц: {summary['pages']} · адресов: {summary.get('urls_checked', 0)} · "
                f"правил упало: {len(failed_rules)} из {len(rules)} · "
                f"критично: {u.get('error', 0)} · дефектов: {u.get('warning', 0)} · "
                f"рекомендаций: {u.get('info', 0)} · {summary['duration_s']} с\n\n"
                + ("| | правило | уровень | замечаний | страниц |\n|---|---|---|---|---|\n" if rows_of else ""))
        for rule_id, rows in rows_of.items():
            sev = rules[rule_id][0]
            mark = "✘" if sev in summary["fail_on"] else "•"
            pages = len({p for g in rows for p in g["pages"]})
            f.write(f"| {mark} | {cell(rules[rule_id][1])} `{rule_id}` | "
                    f"{SEV_TITLE.get(sev, sev)} | {sum(len(g['pages']) for g in rows)} | {pages} |\n")
        if summary.get("crawl_problem"):
            f.write(f"\n> ⛔ **Сайт не обошли, тесты не запускались.** {cell(summary['crawl_problem'])}\n")
        if passed and summary["pages"]:
            f.write(f"\n✔ Прошли ({len(passed)}): " + ", ".join(f"`{r}`" for r in passed) + "\n")
        for rule_id, rows in rows_of.items():
            sev, title = rules[rule_id]
            src, line = source(rule_id)
            f.write(f"\n<details><summary>{SEV_ICON[sev]} <b>{escape(title)}</b> — "
                    f"{sum(len(g['pages']) for g in rows)} <code>{rule_id}</code></summary>\n\n"
                    f"**Как исправить:** {cell(hint(rule_id))}  \n"
                    f"Правило в коде: `{src}:{line}`\n\n"
                    "| страница | что | контекст |\n|---|---|---|\n")
            n = 0
            for g in rows:
                y, pages = g["f"], g["pages"]
                page_level = not y.fragment or y.fragment == y.page
                what = "—" if page_level else cell(show_fragment(y.fragment, base))[:120]
                if y.message != title:
                    what += f"<br><sub>{cell(scrub(y.message, base))[:120]}</sub>"
                ctx = cell(scrub(y.context, base))[:160]
                for p in pages if page_level else pages[:1]:
                    if n >= limit:
                        break
                    more = f" <sub>и ещё {len(pages) - 1} стр.: " + ", ".join(link(x, base) for x in pages[1:10]) \
                        + (" …" if len(pages) > 10 else "") + "</sub>" if not page_level and len(pages) > 1 else ""
                    f.write(f"| {link(p, base)}{more} | {what} | {ctx} |\n")
                    n += 1
            total = sum(len(g["pages"]) if not g["f"].fragment or g["f"].fragment == g["f"].page else 1 for g in rows)
            if total > n:
                f.write(f"\nЕщё {total - n} — в артефакте прогона, файл findings.csv.\n")
            f.write("\n</details>\n")
    return f.getvalue()


def write_junit(path, summary, groups, rules):
    """Правило = тест-кейс. Красный, если у правила есть замечания уровня из fail_on."""
    rows_of = dict(by_rule(groups))
    base = summary["url"]
    suites = defaultdict(list)
    for rule_id in rules:
        suites[rule_id.split(".")[0]].append(rule_id)
    parts = []
    for check, rule_ids in suites.items():
        cases, failures = [], 0
        for rule_id in rule_ids:
            sev, title = rules[rule_id]
            rows = rows_of.get(rule_id, [])
            name = quoteattr(f"{title} [{rule_id}]")
            classname = quoteattr(f"{summary['project_key']}.{check}")
            if sev == "off":
                cases.append(f'<testcase name={name} classname={classname}><skipped/></testcase>')
                continue
            details = f"Как исправить: {hint(rule_id)}\n" + "\n".join(
                f"{show(g['pages'][0], base)} — {show_fragment(g['f'].fragment, base)[:120]} (страниц: {len(g['pages'])})"
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
    write_step_summary(os.path.join(out_dir, "summary.md"), summary, rules, groups)
    write_junit(os.path.join(out_dir, "junit.xml"), summary, groups, rules)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary
