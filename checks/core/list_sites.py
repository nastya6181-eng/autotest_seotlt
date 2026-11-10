#!/usr/bin/env python3
"""Сайты для матрицы GitHub Actions. Учитывает SITE_<КЛЮЧ>, SITES и SITE.

В пайплайне секреты приходят одной переменной SECRETS_JSON (toJSON(secrets)); отсюда берутся
только SITE_<КЛЮЧ>, остальные секреты не читаются.

    python checks/core/list_sites.py           JSON-список: ключ сайта и имя его секрета. Поле url
                                          заполнено только у разового сайта из SITE — строкой
                                          целиком, с опциями (её ввели руками, она не секрет)
    python checks/core/list_sites.py --mask    команды ::add-mask:: — спрятать адреса и домены в логах
    python checks/core/list_sites.py --design  только сайты с макетами (sites/<ключ>/design/pages.yml)
    python checks/core/list_sites.py --design-pages  по элементу на страницу макета (сайт × страница) —
                                          матрица для параллельной сверки; DESIGN_PAGE оставляет одну
"""
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)  # импорты от корня репозитория: checks.core, checks.content, checks.design
from checks.core import sites  # noqa: E402

sites.load_dotenv()
secrets = json.loads(os.environ.pop("SECRETS_JSON", "") or "{}")
os.environ.update({k: v for k, v in secrets.items() if sites.SITE_VAR.fullmatch(k) and isinstance(v, str)})
secret_of = {sites.key_of(k): k for k in os.environ if sites.SITE_VAR.fullmatch(k)}

if "--mask" in sys.argv:
    if os.environ.get("REPORT_FULL_URLS", "").lower() in ("1", "true", "yes"):
        sys.exit(0)  # полные адреса включены сознательно (приватный репозиторий) — не прячем
    for s in sites.all_sites():
        for value in {s["url"], s["url"].rstrip("/"), sites.host(s["url"])}:
            print(f"::add-mask::{value}")
else:
    selected = sites.select()
    if "--design-pages" in sys.argv:
        from checks.design import pages as design_pages
        want = os.environ.get("DESIGN_PAGE") or None
        print(json.dumps([{"key": s["key"], "secret": secret_of.get(s["key"], ""), "url": "", "page": p["name"]}
                          for s in selected if not s.get("adhoc")
                          for p in design_pages.load(s["key"])[1] if not want or p["name"] == want],
                         ensure_ascii=False))
        sys.exit(0)
    if "--design" in sys.argv:
        selected = [s for s in selected if os.path.exists(os.path.join(sites.SITES_DIR, s["key"], "design", "pages.yml"))]
    print(json.dumps([{"key": s["key"], "secret": "" if s.get("adhoc") else secret_of.get(s["key"], ""),
                       "url": s.get("adhoc") or ""} for s in selected], ensure_ascii=False))
