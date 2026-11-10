#!/usr/bin/env python3
"""Сайты для матрицы GitHub Actions. Учитывает SITE_<КЛЮЧ>, SITES и SITE.

В пайплайне секреты приходят одной переменной SECRETS_JSON (toJSON(secrets)); отсюда берутся
только SITE_<КЛЮЧ>, остальные секреты не читаются.

    python common/list_sites.py           JSON-список: ключ сайта и имя его секрета. Поле url
                                          заполнено только у разового сайта из SITE — строкой
                                          целиком, с опциями (её ввели руками, она не секрет)
    python common/list_sites.py --mask    команды ::add-mask:: — спрятать адреса и домены в логах
    python common/list_sites.py --design  только сайты с макетами (projects/<ключ>/design/pages.yml)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import sites  # noqa: E402

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
    if "--design" in sys.argv:
        selected = [s for s in selected if os.path.exists(os.path.join(sites.PROJECTS, s["key"], "design", "pages.yml"))]
    print(json.dumps([{"key": s["key"], "secret": "" if s.get("adhoc") else secret_of.get(s["key"], ""),
                       "url": s.get("adhoc") or ""} for s in selected], ensure_ascii=False))
