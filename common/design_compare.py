#!/usr/bin/env python3
"""Сверка вёрстки с макетом Figma по текстам: шрифты, цвета, отступы.

1. Выгрузить фрейм из Figma: Export → SVG (Outline text — выключено, 1x).
2. Извлечь из SVG тексты в компактный JSON (сам SVG большой, в репозиторий не кладём):
       python common/design_compare.py extract Главная.svg projects/<ключ>/design/main-1600.json
3. Сравнить с сайтом (ширина окна = ширина фрейма):
       python common/design_compare.py compare projects/<ключ>/design/main-1600.json https://site.ru/

Нужен Playwright: pip install playwright && playwright install chromium
(или CHROME_PATH=путь к уже скачанному Chromium).
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecheck import design  # noqa: E402


def cmd_extract(args):
    with open(args.svg, encoding="utf-8") as f:
        data = design.extract_svg(f.read())
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{args.out}: ширина {data['width']:.0f}, текстов {len(data['texts'])}")


def collect(url, width):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
        page = browser.new_page(viewport={"width": int(width), "height": 1000})
        page.goto(url, wait_until="load", timeout=90_000)  # networkidle не наступает из-за счётчиков и карт
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1500)
        page.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 800) {
            window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); } window.scrollTo(0, 0); }""")
        site = page.evaluate(design.COLLECT_JS)
        browser.close()
    return site


def report(results, missing, far, total, url):
    bad = [r for r in results if r["diffs"]]
    kinds = Counter(k.split(" от ")[0] for r in bad for k, _, _ in r["diffs"])
    lines = [f"━━━ Макет против вёрстки: {url} ━━━",
             f"Текстов в макете: {total} · сопоставлено: {len(results)} · с отличиями: {len(bad)} · "
             f"в другом месте страницы: {len(far)} · не найдено: {len(missing)}",
             "Отличия по видам: " + ", ".join(f"{k} — {n}" for k, n in kinds.most_common()), ""]
    for r in sorted(bad, key=lambda r: r["design"]["y"]):
        d = r["design"]
        lines.append(f"✘ «{d['text'][:70]}»  (макет: y={d['y']:.0f}, {d['font_family']} {d['font_size']:g}/{d['font_weight']})")
        for name, want, got in r["diffs"]:
            delta = f"  ({got - want:+g})" if isinstance(want, (int, float)) and isinstance(got, (int, float)) else ""
            lines.append(f"     {name}: макет {want}, сайт {got}{delta}")
    if far:
        lines.append(f"\nЕсть на сайте, но далеко от места в макете (больше {design.MAX_SHIFT_PX} px) — "
                     "блок переставлен или съехал целиком:")
        for d, s in sorted(far, key=lambda p: p[0]["y"]):
            lines.append(f"   ↕ «{d['text'][:70]}»  макет y={d['y']:.0f} x={d['x']:.0f} → сайт y={s['y']:.0f} x={s['x']:.0f}")
    if missing:
        lines.append("\nНе найдено на сайте (другой текст, блок не свёрстан или текст картинкой):")
        for d in sorted(missing, key=lambda d: d["y"]):
            lines.append(f"   ? «{d['text'][:80]}»  (y={d['y']:.0f})")
    return "\n".join(lines)


def cmd_compare(args):
    with open(args.design, encoding="utf-8") as f:
        data = json.load(f)
    site = collect(args.url, data["width"])
    pairs, missing, far = design.match(data["texts"], site)
    results = design.compare(pairs)
    text = report(results, missing, far, len(data["texts"]), args.url)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    sys.exit(1 if any(r["diffs"] for r in results) or missing or far else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="SVG из Figma → JSON с текстами")
    e.add_argument("svg")
    e.add_argument("out")
    c = sub.add_parser("compare", help="сравнить JSON макета с сайтом")
    c.add_argument("design")
    c.add_argument("url")
    c.add_argument("--out", help="сохранить отчёт в файл")
    args = ap.parse_args()
    {"extract": cmd_extract, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    main()
