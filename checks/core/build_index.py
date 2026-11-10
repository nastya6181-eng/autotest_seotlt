#!/usr/bin/env python3
"""Общая таблица по всем сайтам прогона для страницы прогона (Markdown в stdout).

    python checks/core/build_index.py collected/
"""
import json
import os
import sys

root = sys.argv[1]
print("## Общие проверки сайтов\n")
print("| сайт | итог | правил упало | страниц | критично | дефектов | рекомендаций |\n|---|---|---|---|---|---|---|")
for name in sorted(os.listdir(root)):
    d = os.path.join(root, name)
    if not (os.path.isdir(d) and name.startswith("report-")):
        continue
    path = os.path.join(d, "summary.json")
    if not os.path.exists(path):
        print(f"| {name.removeprefix('report-')} | ❌ отчёта нет — см. задание `tests ({name.removeprefix('report-')})` "
              "| — | — | — | — | — |")
        continue
    s = json.load(open(path, encoding="utf-8"))
    u = s["findings_unique"]
    print(f"| {s['project']} | {'❌ есть дефекты' if s['failed'] else '✅ ок'} | "
          f"{s.get('rules_failed', '—')} из {s.get('rules_total', '—')} | "
          f"{s['pages']} | {u.get('error', 0)} | {u.get('warning', 0)} | {u.get('info', 0)} |")
print("\nПодробный отчёт по каждому сайту — ниже на этой странице, в блоке задания `tests (<сайт>)`: "
      "правила, как исправить, страницы, фрагменты и контекст. Лог каждого теста — в шагах «Тест: …» этого задания.")
