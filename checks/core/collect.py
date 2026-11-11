#!/usr/bin/env python3
"""Раскладывает скачанные отчёты по папкам report-<ключ>/.

    python checks/core/collect.py collected

download-artifact с v5 кладёт единственный найденный архив прямо в папку, без подпапки с его именем.
Прогон одного сайта (или одной страницы макета) тогда выглядел как «отчётов нет»: сборщик, история
и сводка ищут collected/report-*/summary.json.
"""
import json
import os
import shutil
import sys


def normalize(collected):
    top = os.path.join(collected, "summary.json")
    if not os.path.exists(top):
        return None
    with open(top, encoding="utf-8") as f:
        key = json.load(f)["project_key"]
    target = os.path.join(collected, f"report-{key}")
    os.makedirs(target)
    for name in os.listdir(collected):
        if name != os.path.basename(target):
            shutil.move(os.path.join(collected, name), target)
    return target


if __name__ == "__main__":
    moved = normalize(sys.argv[1])
    print(f"один отчёт, разложен в {moved}" if moved else "отчёты уже по папкам", file=sys.stderr)
