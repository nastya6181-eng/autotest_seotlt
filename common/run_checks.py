#!/usr/bin/env python3
"""Общие проверки сайтов: орфография, типографика, ссылки.

Сайты задаются переменными окружения (локально — ещё и файлом .env в корне):
    SITES       все сайты, по строке на сайт: «ключ=https://адрес [опция=значение ...]».
                Опции: max_pages, delay, max_rps, cooldown, ignore_robots, exclude, workers.
                В GitHub — секрет репозитория SITES.
    SITE        прогнать только один: ключ из SITES или любой адрес
    MAX_PAGES   переопределить лимит страниц
    MAX_RPS     не чаще N запросов в секунду к сайту (поверх max_rps из project.yml)
    CHECKS      только эти проверки: tech,seo,links,spelling,typography

Примеры:
    python common/run_checks.py                                  # все сайты из SITES
    SITE=site-a python common/run_checks.py                      # один по ключу
    SITE=https://example.ru/ MAX_PAGES=30 python common/run_checks.py
    python common/run_checks.py --site site-a --only links       # то же флагами

Настройки сайта: умолчания ← projects/<ключ>/project.yml (если есть) ← опции из строки SITES
← MAX_PAGES / MAX_RPS / CHECKS ← флаги.

Этапы (в пайплайне идут отдельными шагами, локально по умолчанию все подряд):
    --stage crawl             обход сайта → reports/<ключ>/crawl.json
    --stage test --only links один тест по обходу → reports/<ключ>/tests/links.json
    --stage report            сводный отчёт по сайту из всех тестов

Отчёты: reports/<ключ>/ — report.md, findings.csv, summary.json, summary.md, junit.xml.
Код выхода: 0 — дефектов нет, 1 — есть замечания уровня из fail_on (error, warning), 2 — сайт не открылся.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import crawler, links, report, seo, sites, spelling, tech, throttle, typography  # noqa: E402
from sitecheck.findings import SEVERITIES, Finding  # noqa: E402

ROOT = sites.ROOT
COMMON = os.path.join(ROOT, "common")
CHECKS = {m.NAME: m for m in (tech, seo, links, spelling, typography)}
DEFAULTS = {
    "max_pages": 200,
    "delay": 0.3,
    "exclude": None,
    "ignore_robots": False,
    "fail_on": ["error", "warning"],
    "severity": {},
    "checks": {"tech": {}, "seo": {}, "links": {}, "spelling": {}, "typography": {}},
}


def load_config(site, max_pages=None, only=None):
    """Настройки сайта: умолчания ← projects/<ключ>/project.yml ← опции из SITES ← env и флаги."""
    cfg = {**DEFAULTS, "checks": {k: dict(v) for k, v in DEFAULTS["checks"].items()}}
    project_dir = sites.project_dir(site["key"])
    if project_dir:
        with open(os.path.join(project_dir, "project.yml"), encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for k, v in data.items():
            if k == "checks":
                for name, opts in (v or {}).items():
                    cfg["checks"][name] = opts or {}
            else:
                cfg[k] = v
    options = dict(site.get("options", {}))
    if "workers" in options:
        cfg["checks"].setdefault("links", {})["workers"] = options.pop("workers")
    cfg.update(options)
    cfg["url"] = site["url"]
    cfg["key"] = site["key"]
    cfg.setdefault("name", site["key"])
    if max_pages:
        cfg["max_pages"] = int(max_pages)
    if only:
        wanted = {c.strip() for c in only.split(",") if c.strip()}
        unknown = wanted - set(CHECKS)
        if unknown:
            sys.exit(f"Неизвестные проверки: {', '.join(unknown)}. Есть: {', '.join(CHECKS)}")
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


def stage_crawl(cfg, out_dir):
    """Этап 1: обход сайта. Страницы сохраняются в crawl.json — по нему работают все тесты."""
    started = time.time()
    failed_pages, pages = [], []
    exclude = re.compile(cfg["exclude"]) if cfg.get("exclude") else None
    print(f"\n=== {cfg['name']}: {cfg['url']}", file=sys.stderr)
    for page in crawler.crawl(cfg["url"], cfg["max_pages"], cfg["delay"], exclude,
                              cfg["ignore_robots"], failed_pages):
        pages.append(page)
        print(f"[{len(pages)}] {page.url}", file=sys.stderr)
    os.makedirs(os.path.join(out_dir, "tests"), exist_ok=True)
    for old in os.listdir(os.path.join(out_dir, "tests")):
        os.remove(os.path.join(out_dir, "tests", old))  # результаты прошлого обхода не смешиваем
    with open(os.path.join(out_dir, "crawl.json"), "w", encoding="utf-8") as f:
        json.dump({"started": started, "duration_s": round(time.time() - started),
                   "failed": failed_pages,
                   "pages": [{**asdict(p), "ids": sorted(p.ids)} for p in pages]}, f, ensure_ascii=False)
    print(f"обход: страниц {len(pages)}, не открылось {len(failed_pages)}", file=sys.stderr)
    if not pages:
        print("Не открылась ни одна страница — проверь адрес и доступность сайта.", file=sys.stderr)
        return 2
    return 0


def load_crawl(out_dir):
    path = os.path.join(out_dir, "crawl.json")
    if not os.path.exists(path):
        sys.exit(f"Нет {path}: сначала этап crawl")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["pages"] = [crawler.Page(p["url"], p["text"], p["links"], set(p["ids"]), p.get("meta", {}))
                     for p in data["pages"]]
    return data


def stage_test(cfg, out_dir, name):
    """Этап 2: один тест (проверка) по сохранённому обходу. Результат — tests/<имя>.json."""
    started = time.time()
    crawl = load_crawl(out_dir)
    module = CHECKS[name]
    env = {
        "start_url": cfg["url"],
        "failed_pages": crawl["failed"],
        "dict_dir": os.environ.get("DICT_DIR", os.path.join(COMMON, ".cache", "dict")),
        "common_ignore": os.path.join(COMMON, "dictionaries", "ignore.txt"),
        "stats": {},
    }
    print(f"тест {name}…", file=sys.stderr)
    findings = module.run(crawl["pages"], cfg["checks"][name], cfg["severity"], env)
    rules = {f"{name}.{r}": (cfg["severity"].get(f"{name}.{r}", sev), title)
             for r, (sev, title) in module.RULES.items()}
    os.makedirs(os.path.join(out_dir, "tests"), exist_ok=True)
    with open(os.path.join(out_dir, "tests", f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump({"findings": [asdict(x) for x in findings], "rules": rules,
                   "stats": env["stats"], "duration_s": round(time.time() - started)}, f, ensure_ascii=False)
    active = [x for x in findings if x.severity != "off"]
    counts = Counter(x.severity for x in active)
    print(report.format_test_log(name, rules, findings, cfg["fail_on"], base=cfg["url"]), file=sys.stderr)
    return 1 if any(counts[s] for s in cfg["fail_on"]) else 0


def stage_report(cfg, out_dir):
    """Этап 3: сводный отчёт по сайту из результатов всех тестов."""
    crawl = load_crawl(out_dir)
    findings, rules, stats, duration = [], {}, {}, crawl["duration_s"]
    tests_dir = os.path.join(out_dir, "tests")
    for fname in sorted(os.listdir(tests_dir)) if os.path.isdir(tests_dir) else []:
        with open(os.path.join(tests_dir, fname), encoding="utf-8") as f:
            data = json.load(f)
        findings += [Finding(**x) for x in data["findings"]]
        rules.update({k: tuple(v) for k, v in data["rules"].items()})
        stats.update(data["stats"])
        duration += data["duration_s"]
    meta = {
        "project": cfg["name"],
        "project_key": cfg["key"],
        "url": cfg["url"],
        "started_at": dt.datetime.fromtimestamp(crawl["started"], dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "duration_s": duration,
        "pages": len(crawl["pages"]),
        "pages_failed": len(crawl["failed"]),
        "run_url": os.environ.get("RUN_URL", ""),
        **stats,
    }
    summary = report.write_all(out_dir, meta, findings, rules, cfg["fail_on"])
    u = summary["findings_unique"]
    print(f"{cfg['name']}: страниц {meta['pages']}, ошибок {u.get('error', 0)}, "
          f"предупреждений {u.get('warning', 0)}, к сведению {u.get('info', 0)} → {out_dir}",
          file=sys.stderr)
    if not crawl["pages"]:
        return 2
    return 1 if summary["failed"] else 0


def enabled_checks(cfg):
    return [n for n, o in cfg["checks"].items() if o.get("enabled", True) is not False]


def check_site(cfg, out_dir, stage="all"):
    throttle.configure(cfg["url"], os.environ.get("MAX_RPS") or cfg.get("max_rps"), cfg.get("cooldown"))
    if stage == "crawl":
        return stage_crawl(cfg, out_dir)
    if stage == "test":
        return max([stage_test(cfg, out_dir, n) for n in enabled_checks(cfg)] or [0])
    if stage == "report":
        return stage_report(cfg, out_dir)
    if stage_crawl(cfg, out_dir) == 0:
        for name in enabled_checks(cfg):
            stage_test(cfg, out_dir, name)
    return stage_report(cfg, out_dir)


def main():
    sites.load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=os.environ.get("SITE"), help="ключ или адрес (по умолчанию $SITE)")
    ap.add_argument("--max-pages", type=int, default=os.environ.get("MAX_PAGES") or None,
                    help="лимит страниц (по умолчанию $MAX_PAGES или из project.yml)")
    ap.add_argument("--only", default=os.environ.get("CHECKS"), help="spelling,typography,links ($CHECKS)")
    ap.add_argument("--stage", choices=["all", "crawl", "test", "report"], default="all",
                    help="all — всё подряд; crawl/test/report — отдельные этапы для пайплайна")
    ap.add_argument("--list", action="store_true", help="показать сайты и выйти")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports"), help="корень отчётов")
    args = ap.parse_args()

    targets = sites.select(args.site)
    if args.list:
        for s in targets:
            print(f"{s['key']}={s['url']}")
        return
    if not targets:
        sys.exit("Нет сайтов: задай SITES или SITE (в окружении, в .env или секретом в GitHub)")
    codes = [check_site(load_config(s, args.max_pages, args.only), os.path.join(args.out, s["key"]), args.stage)
             for s in targets]
    sys.exit(max(codes))


if __name__ == "__main__":
    main()
