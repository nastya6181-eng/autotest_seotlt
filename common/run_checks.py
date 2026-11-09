#!/usr/bin/env python3
"""Общие проверки сайта: орфография, типографика, ссылки.

Запуск по проекту (настройки в projects/<проект>/project.yml):
    python common/run_checks.py projects/innotech
Разовый запуск по любому адресу:
    python common/run_checks.py --url https://example.ru/ --max-pages 50
Только часть проверок:
    python common/run_checks.py projects/innotech --only links,typography

Отчёты пишутся в reports/<проект>/: report.md, findings.csv, summary.json,
summary.md (для страницы прогона), junit.xml (для GitHub Checks).
Код выхода: 0 — ошибок нет, 1 — есть замечания уровня из fail_on, 2 — сбой запуска.
"""
import argparse
import datetime as dt
import os
import re
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import crawler, links, report, spelling, typography  # noqa: E402
from sitecheck.findings import SEVERITIES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON = os.path.join(ROOT, "common")
CHECKS = {m.NAME: m for m in (spelling, typography, links)}
DEFAULTS = {
    "max_pages": 200,
    "delay": 0.3,
    "exclude": None,
    "ignore_robots": False,
    "fail_on": ["error"],
    "severity": {},
    "checks": {"spelling": {}, "typography": {}, "links": {}},
}


def load_config(args):
    cfg = {**DEFAULTS, "checks": {k: dict(v) for k, v in DEFAULTS["checks"].items()}}
    project_dir = None
    if args.project:
        project_dir = os.path.abspath(args.project)
        with open(os.path.join(project_dir, "project.yml"), encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for k, v in data.items():
            if k == "checks":
                for name, opts in (v or {}).items():
                    cfg["checks"][name] = opts or {}
            else:
                cfg[k] = v
        cfg.setdefault("key", os.path.basename(project_dir))
    if args.url:
        cfg["url"] = args.url
    if not cfg.get("url"):
        sys.exit("Нужен проект (папка с project.yml) или --url")
    cfg.setdefault("key", re.sub(r"\W+", "-", cfg["url"].split("//")[-1]).strip("-"))
    cfg.setdefault("name", cfg["key"])
    if args.max_pages:
        cfg["max_pages"] = args.max_pages
    if args.only:
        wanted = set(args.only.split(","))
        cfg["checks"] = {k: v for k, v in cfg["checks"].items() if k in wanted}
    for name, opts in cfg["checks"].items():
        if name not in CHECKS:
            sys.exit(f"Неизвестная проверка {name}. Есть: {', '.join(CHECKS)}")
        if opts.get("ignore_file") and project_dir:
            opts["ignore_file"] = os.path.join(project_dir, opts["ignore_file"])
    for rule, sev in cfg["severity"].items():
        if sev not in SEVERITIES:
            sys.exit(f"severity.{rule}: «{sev}», допустимо {', '.join(SEVERITIES)}")
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", help="папка проекта с project.yml")
    ap.add_argument("--url", help="адрес сайта (вместо проекта или поверх его url)")
    ap.add_argument("--max-pages", type=int, help="переопределить max_pages")
    ap.add_argument("--only", help="через запятую: spelling,typography,links")
    ap.add_argument("--out", help="папка отчётов, по умолчанию reports/<проект>")
    args = ap.parse_args()
    cfg = load_config(args)
    out_dir = args.out or os.path.join(ROOT, "reports", cfg["key"])

    started = time.time()
    failed_pages = []
    pages = []
    exclude = re.compile(cfg["exclude"]) if cfg.get("exclude") else None
    for page in crawler.crawl(cfg["url"], cfg["max_pages"], cfg["delay"], exclude,
                              cfg["ignore_robots"], failed_pages):
        pages.append(page)
        print(f"[{len(pages)}] {page.url}", file=sys.stderr)

    env = {
        "start_url": cfg["url"],
        "failed_pages": failed_pages,
        "dict_dir": os.environ.get("DICT_DIR", os.path.join(COMMON, ".cache", "dict")),
        "common_ignore": os.path.join(COMMON, "dictionaries", "ignore.txt"),
        "stats": {},
    }
    findings, rules = [], {}
    for name, opts in cfg["checks"].items():
        if opts.get("enabled", True) is False:
            continue
        module = CHECKS[name]
        print(f"проверка {name}…", file=sys.stderr)
        findings += module.run(pages, opts, cfg["severity"], env)
        for rule, (sev, title) in module.RULES.items():
            rules[f"{name}.{rule}"] = (cfg["severity"].get(f"{name}.{rule}", sev), title)

    meta = {
        "project": cfg["name"],
        "project_key": cfg["key"],
        "url": cfg["url"],
        "started_at": dt.datetime.fromtimestamp(started, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "duration_s": round(time.time() - started),
        "pages": len(pages),
        "pages_failed": len(failed_pages),
        "run_url": os.environ.get("RUN_URL", ""),
        **env["stats"],
    }
    summary = report.write_all(out_dir, meta, findings, rules, cfg["fail_on"])
    u = summary["findings_unique"]
    print(f"\n{cfg['name']}: страниц {len(pages)}, ошибок {u.get('error', 0)}, "
          f"предупреждений {u.get('warning', 0)}, к сведению {u.get('info', 0)} → {out_dir}",
          file=sys.stderr)
    if not pages:
        print("Не открылась ни одна страница — проверь адрес и доступность сайта.", file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
