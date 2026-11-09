#!/usr/bin/env python3
"""Сайты для матрицы GitHub Actions. Учитывает SITES и SITE.

    python common/list_sites.py           JSON-список: ключи сайтов из SITES; поле url заполнено только
                                          у разового сайта из SITE — строкой целиком, вместе с опциями
                                          (её ввели руками в форме запуска, она не секрет)
    python common/list_sites.py --mask    команды ::add-mask:: — спрятать адреса и домены в логах
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import sites  # noqa: E402

sites.load_dotenv()
selected = sites.select()
if "--mask" in sys.argv:
    for s in sites.parse_sites(os.environ.get("SITES")):
        for value in {s["url"], s["url"].rstrip("/"), sites.host(s["url"])}:
            print(f"::add-mask::{value}")
else:
    print(json.dumps([{"key": s["key"], "url": s.get("adhoc") or ""} for s in selected],
                     ensure_ascii=False))
