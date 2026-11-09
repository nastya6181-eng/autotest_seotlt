#!/usr/bin/env python3
"""Сайты для прогона в JSON (матрица GitHub Actions). Учитывает SITES и SITE.

    SITES="innotech=https://inno.seotlt.ru/" SITE=innotech python common/list_sites.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import sites  # noqa: E402

sites.load_dotenv()
print(json.dumps(sites.select(), ensure_ascii=False))
