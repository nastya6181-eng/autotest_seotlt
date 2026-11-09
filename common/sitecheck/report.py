"""Лог теста и отчёты прогона: report.html, report.md, summary.md, findings.csv, summary.json, junit.xml.

REPORT_FULL_URLS=true — показывать полные адреса страниц в логах, сводке и Checks (для приватного
репозитория). По умолчанию там только пути (/about/), а полные кликабельные ссылки — в report.html.
"""
import csv
import html
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

def format_test_log(name, rules, findings, fail_on, base="", limit=15):
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
            lines.append(f"   … и ещё {rest} — все в report.html / findings.csv")
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
                    "| фрагмент | страниц | пример | контекст |\n|---|---|---|---|\n")
            for g in rows[:MAX_ROWS]:
                y = g["f"]
                f.write(f"| `{cell(y.fragment)[:120]}` | {len(g['pages'])} | {g['pages'][0]} | {cell(y.context)[:160]} |\n")
            f.write("\n")


HTML_CSS = """
:root{--bg:#fff;--fg:#1f2328;--mute:#656d76;--line:#d0d7de;--card:#f6f8fa;--err:#cf222e;--warn:#bc4c00;--ok:#1a7f37;--mark:#fff8c5;--link:#0969da}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mute:#8d96a0;--line:#30363d;--card:#161b22;--err:#f85149;--warn:#db6d28;--ok:#2ea043;--mark:#4b3d00;--link:#4493f8}}
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;padding:24px 16px;max-width:1200px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}a{color:var(--link)}
.meta{color:var(--mute);margin-bottom:16px}.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:13px;font-weight:600}
.error{background:var(--err);color:#fff}.warning{background:var(--warn);color:#fff}.info{background:var(--line);color:var(--fg)}.pass{background:var(--ok);color:#fff}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:var(--card)}td.n{text-align:right;white-space:nowrap}.hint{background:var(--card);border-left:4px solid var(--warn);padding:8px 12px;margin:8px 0}
mark{background:var(--mark);color:inherit;padding:0 2px}details summary{cursor:pointer;color:var(--mute)}code{font-size:13px}.src{color:var(--mute);font-size:13px}
"""


def _h(s):
    return html.escape(str(s or ""))


def _context_html(ctx, fragment):
    c, frag = _h(ctx), _h(fragment)
    return c.replace(frag, f"<mark>{frag}</mark>", 1) if frag and frag in c else c


def _link(url, base):
    return f"<a href='{_h(url)}' target='_blank' rel='noopener'>{_h(relative(url, base))}</a>"


def write_html(path, summary, groups, rules):
    """Отчёт для человека: что сломано, на какой странице (ссылка), фрагмент, контекст, как исправить."""
    rows_of = dict(by_rule(groups))
    u = summary["findings_unique"]
    base = summary["url"]
    status = ("<span class='badge error'>есть дефекты</span>" if summary["failed"]
              else "<span class='badge pass'>дефектов нет</span>")
    out = [f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Отчёт: {_h(summary['project'])}</title><style>{HTML_CSS}</style></head><body>",
           f"<h1>{_h(summary['project'])} {status}</h1>",
           f"<div class='meta'><a href='{_h(base)}'>{_h(base)}</a> · {_h(summary['started_at'])} · "
           f"страниц {summary['pages']} · адресов {summary.get('urls_checked', 0)} · "
           f"критично {u.get('error', 0)} · дефектов {u.get('warning', 0)} · рекомендаций {u.get('info', 0)}"
           + (f" · <a href='{_h(summary['run_url'])}'>прогон в GitHub</a>" if summary.get("run_url") else "")
           + "</div>",
           "<h2>Правила</h2><div class='wrap'><table><tr><th>правило</th><th>уровень</th><th>результат</th></tr>"]
    for rule_id, (sev, title) in sorted(rules.items(), key=lambda kv: (-len(rows_of.get(kv[0], [])), kv[0])):
        rows = rows_of.get(rule_id, [])
        res = ("выключено" if sev == "off" else f"<a href='#{rule_id}'>{len(rows)} замечаний</a>" if rows
               else "<span class='badge pass'>ок</span>")
        out.append(f"<tr><td>{_h(title)}<br><code>{rule_id}</code></td>"
                   f"<td><span class='badge {sev if sev != 'off' else 'info'}'>{SEV_TITLE.get(sev, sev)}</span></td>"
                   f"<td>{res}</td></tr>")
    out.append("</table></div>")
    for rule_id, rows in rows_of.items():
        sev, title = rules[rule_id]
        src, line = source(rule_id)
        out.append(f"<h2 id='{rule_id}'><span class='badge {sev}'>{SEV_TITLE[sev]}</span> {_h(title)} — {len(rows)}</h2>"
                   f"<div class='hint'><b>Как исправить:</b> {_h(hint(rule_id))}</div>"
                   f"<div class='src'>Правило <code>{rule_id}</code>, код <code>{src}:{line}</code></div>"
                   "<div class='wrap'><table><tr><th>страница</th><th>что</th><th>контекст</th><th>страниц</th></tr>")
        for g in rows:
            f, pages = g["f"], g["pages"]
            more = ""
            if len(pages) > 1:
                more = (f"<details><summary>ещё {len(pages) - 1}</summary>"
                        + "<br>".join(_link(p, base) for p in pages[1:]) + "</details>")
            if f.fragment.startswith(("http://", "https://")):
                what = _link(f.fragment, base)
            else:
                what = _h(f.fragment) if f.fragment and f.fragment != f.page else "—"
            why = f"<br><span class='src'>{_h(f.message)}</span>" if f.message != title else ""
            out.append(f"<tr><td>{_link(pages[0], base)}{more}</td><td>{what}{why}</td>"
                       f"<td>{_context_html(f.context, f.fragment)}</td><td class='n'>{len(pages)}</td></tr>")
        out.append("</table></div>")
    out.append("</body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def write_step_summary(path, summary, rules, groups=()):
    """Сводка для страницы прогона в GitHub Actions: правила и что где чинить."""
    u = summary["findings_unique"]
    base = summary["url"]
    icon = "❌" if summary["failed"] else "✅"
    rows_of = dict(by_rule(groups))
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"### {icon} {summary['project']}\n\n"
                f"Страниц: {summary['pages']} · адресов: {summary.get('urls_checked', 0)} · "
                f"критично: {u.get('error', 0)} · дефектов: {u.get('warning', 0)} · "
                f"рекомендаций: {u.get('info', 0)} · {summary['duration_s']} с\n\n"
                "| | правило | уровень | замечаний |\n|---|---|---|---|\n")
        for rule, n in sorted(summary["by_rule"].items(), key=lambda kv: -kv[1]):
            if n:
                sev = rules[rule][0]
                mark = "✘" if sev in summary["fail_on"] else "•"
                f.write(f"| {mark} | {rules[rule][1]} (`{rule}`) | {SEV_TITLE.get(sev, sev)} | "
                        f"{len(rows_of.get(rule, []))} |\n")
        f.write("\n#### Что и где чинить\n\n")
        for rule_id, rows in rows_of.items():
            f.write(f"<details><summary>{SEV_ICON[rows[0]['f'].severity]} <b>{escape(rules[rule_id][1])}</b> "
                    f"— {len(rows)} <code>{rule_id}</code></summary>\n\n"
                    f"**Как исправить:** {cell(hint(rule_id))}\n\n"
                    "| где | что | контекст |\n|---|---|---|\n")
            for g in rows[:20]:
                y, pages = g["f"], g["pages"]
                what = cell(show_fragment(y.fragment, base))[:100] if y.fragment and y.fragment != y.page else "—"
                where = cell(show(pages[0], base)) + (f" (+ ещё {len(pages) - 1})" if len(pages) > 1 else "")
                f.write(f"| {where} | {what} | {cell(scrub(y.context, base))[:140]} |\n")
            if len(rows) > 20:
                f.write(f"\nЕщё {len(rows) - 20} — в report.html.\n")
            f.write("\n</details>\n")


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
    write_html(os.path.join(out_dir, "report.html"), summary, groups, rules)
    write_step_summary(os.path.join(out_dir, "summary.md"), summary, rules, groups)
    write_junit(os.path.join(out_dir, "junit.xml"), summary, groups, rules)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary
