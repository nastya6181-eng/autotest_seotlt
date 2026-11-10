#!/usr/bin/env python3
"""Сверка вёрстки с макетом Figma по текстам: шрифты, цвета, переносы, отступы.

1. Выгрузить фрейм из Figma: Export → SVG (Outline text — выключено, 1x).
2. Извлечь из SVG тексты в компактный JSON (сам SVG большой, в репозиторий не кладём):
       python common/design_compare.py extract Главная.svg projects/<ключ>/design/main-1600.json
3. Описать страницу в projects/<ключ>/design/pages.yml (путь, ширина, файл макета, динамические зоны).
4. Прогнать — сайты те же, что у общих проверок (SITE_<КЛЮЧ>, SITE):
       SITE=<ключ> python common/design_compare.py run
   Отчёты — в reports/<ключ>-design/, в том же формате, что у общих проверок.

Нужен Playwright: pip install -r requirements-design.txt && python -m playwright install chromium
(или CHROME_PATH=путь к уже скачанному Chromium).
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from urllib.parse import urljoin

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import design, report, sites  # noqa: E402
from sitecheck.findings import make  # noqa: E402

FAIL_ON = ["error", "warning"]


def tolerance(page):
    """Допуск по положению, px: DESIGN_TOLERANCE_PX (разовый прогон) → tolerance страницы в pages.yml → 2."""
    for value in (os.environ.get("DESIGN_TOLERANCE_PX"), page.get("tolerance")):
        if value not in (None, ""):
            try:
                tol = float(value)
            except ValueError:
                sys.exit(f"Допуск «{value}» — не число пикселей")
            if tol < 0:
                sys.exit(f"Допуск {tol:g} px — должен быть не меньше 0")
            return tol
    return design.TOL_PX


def cmd_extract(args):
    with open(args.svg, encoding="utf-8") as f:
        data = design.extract_svg(f.read())
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{args.out}: ширина {data['width']:.0f}, текстов {len(data['texts'])}")
    if data["skipped_transformed"]:
        print(f"  пропущено текстов под поворотом/масштабом: {data['skipped_transformed']} — их позицию из SVG не узнать")


def collect(browser, url, width):
    page = browser.new_page(viewport={"width": int(width), "height": 1000})
    try:
        page.goto(url, wait_until="load", timeout=90_000)  # networkidle не наступает из-за счётчиков и карт
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1500)
        # прокрутка подгружает ленивые блоки; мгновенная — у сайта может быть scroll-behavior: smooth,
        # и замер, начатый посреди анимации, прибавит к фиксированной шапке недокрученный scrollY
        page.evaluate("""async () => {
            const go = y => window.scrollTo({top: y, behavior: 'instant'});
            for (let y = 0; y < document.body.scrollHeight; y += 800) { go(y); await new Promise(r => setTimeout(r, 60)); }
            go(0);
            for (let i = 0; i < 50 && window.scrollY !== 0; i++) await new Promise(r => setTimeout(r, 20));
        }""")
        return page.evaluate(design.COLLECT_JS)
    finally:
        page.close()


def design_pages(key):
    path = os.path.join(sites.PROJECTS, key, "design", "pages.yml")
    if not os.path.exists(path):
        return None, []
    with open(path, encoding="utf-8") as f:
        return os.path.dirname(path), yaml.safe_load(f) or []


def check_site(browser, site, out_root):
    folder, pages = design_pages(site["key"])
    rules = {f"design.{r}": v for r, v in design.RULES.items()}
    finding = make("design", design.RULES, {})
    started, findings, lines, texts = time.time(), [], [], 0
    print(f"\n=== {site['key']}: макет против вёрстки, страниц {len(pages)}", file=sys.stderr)
    for p in pages:
        with open(os.path.join(folder, p["design"]), encoding="utf-8") as f:
            data = json.load(f)
        width = p.get("width", data["width"])
        url = urljoin(site["url"], p["page"])
        tol = tolerance(p)
        found, st = design.check_page(data, collect(browser, url, width), url, p.get("dynamic", []), finding, tol)
        findings += found
        texts += st["matched"]
        lines.append(f"{p['page']} ({width:.0f}, допуск ±{tol:g} px): текстов в макете {st['texts']}, "
                     f"динамических пропущено {st['dynamic']}, сопоставлено {st['matched']}, "
                     f"в другом месте {st['moved']}, не найдено {st['missing']}")
    meta = {"project": site["key"], "project_key": site["key"], "url": site["url"],
            "started_at": dt.datetime.fromtimestamp(started, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "duration_s": round(time.time() - started), "pages": len(pages), "pages_failed": 0,
            "urls_checked": texts, "run_url": os.environ.get("RUN_URL", ""),
            "note": "Допуск по положению (левый край, отступы): "
                    + ", ".join(sorted({f"±{tolerance(p):g} px" for p in pages})) + "; стиль сравнивается точно."}
    summary = report.write_all(os.path.join(out_root, f"{site['key']}-design"), meta, findings, rules, FAIL_ON)
    print("\n".join(["Покрытие:"] + [f"  {x}" for x in lines]), file=sys.stderr)
    print(report.format_test_log("макет", rules, findings, FAIL_ON, base=site["url"]), file=sys.stderr)
    return 1 if summary["failed"] else 0


def with_design(selected):
    return [s for s in selected if design_pages(s["key"])[0]]


def cmd_run(args):
    targets = with_design(sites.select(args.site))
    if not targets:
        sys.exit("Нет сайтов с макетами: нужен projects/<ключ>/design/pages.yml и секрет SITE_<КЛЮЧ>")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
        codes = [check_site(browser, s, args.out) for s in targets]
        browser.close()
    sys.exit(max(codes))


def cmd_list(args):
    """Ключи сайтов с макетами — для матрицы пайплайна. Адресов не печатает."""
    print(json.dumps([s["key"] for s in with_design(sites.select(args.site))]))


def main():
    sites.load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="SVG из Figma → JSON с текстами")
    e.add_argument("svg")
    e.add_argument("out")
    e.set_defaults(fn=cmd_extract)
    for name, fn, help_ in (("run", cmd_run, "сравнить сайты с макетами"),
                            ("list", cmd_list, "ключи сайтов с макетами (для матрицы)")):
        c = sub.add_parser(name, help=help_)
        c.add_argument("--site", default=os.environ.get("SITE"), help="ключ или адрес (по умолчанию $SITE)")
        c.add_argument("--out", default=os.path.join(sites.ROOT, "reports"))
        c.set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
