#!/usr/bin/env python3
"""Общий отчёт по всем сайтам прогона: index.html со ссылками на report.html каждого сайта
и таблица для страницы прогона (stdout, Markdown).

    python common/build_index.py collected/ [ссылка на артефакт logs-all]
"""
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck.report import HTML_CSS  # noqa: E402

root = sys.argv[1]
artifact = sys.argv[2] if len(sys.argv) > 2 else ""
sites = []
for name in sorted(os.listdir(root)):
    d = os.path.join(root, name)
    if not (os.path.isdir(d) and name.startswith("report-")):
        continue
    path = os.path.join(d, "summary.json")
    summary = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    sites.append((name.removeprefix("report-"), name, summary))


def row_html(key, folder, s):
    if not s:
        return (f"<tr><td>{html.escape(key)}</td><td colspan='5'><span class='badge error'>отчёта нет</span> "
                f"см. <a href='{folder}/logs/'>логи</a></td></tr>")
    u = s["findings_unique"]
    badge = "<span class='badge error'>есть дефекты</span>" if s["failed"] else "<span class='badge pass'>ок</span>"
    return (f"<tr><td><a href='{folder}/report.html'>{html.escape(s['project'])}</a></td><td>{badge}</td>"
            f"<td class='n'>{s['pages']}</td><td class='n'>{u.get('error', 0)}</td>"
            f"<td class='n'>{u.get('warning', 0)}</td><td class='n'>{u.get('info', 0)}</td></tr>")


with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as f:
    f.write("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Общие проверки сайтов</title><style>{HTML_CSS}</style></head><body>"
            "<h1>Общие проверки сайтов</h1><div class='wrap'><table><tr><th>сайт</th><th>итог</th>"
            "<th>страниц</th><th>критично</th><th>дефектов</th><th>рекомендаций</th></tr>"
            + "".join(row_html(*s) for s in sites)
            + "</table></div><p class='src'>Открой отчёт сайта: там каждое замечание со ссылкой на страницу, "
              "фрагментом, контекстом и подсказкой, как исправить.</p></body></html>")

print("## Общие проверки сайтов\n")
print("| сайт | итог | страниц | критично | дефектов | рекомендаций |\n|---|---|---|---|---|---|")
for key, _, s in sites:
    if not s:
        print(f"| {key} | ❌ отчёта нет, см. логи задания | — | — | — | — |")
        continue
    u = s["findings_unique"]
    print(f"| {s['project']} | {'❌ есть дефекты' if s['failed'] else '✅ ок'} | {s['pages']} | "
          f"{u.get('error', 0)} | {u.get('warning', 0)} | {u.get('info', 0)} |")
print("\n**Как разобрать:** скачай артефакт "
      + (f"[logs-all]({artifact})" if artifact else "**logs-all**")
      + " и открой `index.html`, оттуда отчёт каждого сайта: замечание, ссылка на страницу, фрагмент, "
        "контекст и как исправить. Подробный лог каждого теста — в задании `tests (<сайт>)`, шаг «Тест: …».")
