"""Страницы с макетами: projects/<ключ>/design/pages.yml, подготовленные JSON и исходники Figma.

    projects/<ключ>/design/
      pages.yml          список страниц (в git)
      <имя>-<ширина>.json  подготовленный макет: тексты, позиции, шрифты (в git, десятки КБ)
      src/               исходники из Figma — SVG и PNG (не в git: SVG весит десятки МБ)

Запись в pages.yml:
    - name: main               имя страницы: задание в CI, папка отчёта (латиница, цифры, «-»)
      page: /                  путь на сайте
      width: 1600              ширина фрейма = ширина окна браузера
      design: main-1600.json   подготовленный макет
      source: src/main-1600.svg  исходник, из которого JSON готовится (prepare)
      dynamic: [[880, 1320]]   зоны с меняющимся контентом
      tolerance: 2             допуск по положению, px
"""
import os
import re

from . import design, sites

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def folder(key):
    return os.path.join(sites.PROJECTS, key, "design")


def load(key):
    """(папка, страницы) — у каждой страницы есть name; без pages.yml — (None, [])."""
    import yaml
    path = os.path.join(folder(key), "pages.yml")
    if not os.path.exists(path):
        return None, []
    with open(path, encoding="utf-8") as f:
        pages = yaml.safe_load(f) or []
    names = []
    for p in pages:
        p.setdefault("name", re.sub(r"[^a-z0-9-]+", "-", os.path.splitext(p["design"])[0].lower()).strip("-"))
        if not isinstance(p.get("page"), str) or not p["page"].startswith("/") or p["page"].startswith("//"):
            raise SystemExit(f"{path}: у страницы «{p['name']}» page должен быть путём от корня, например /catalog/")
        if not NAME_RE.match(p["name"]):
            raise SystemExit(f"{path}: имя страницы «{p['name']}» — только латиница, цифры и «-»")
        names.append(p["name"])
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise SystemExit(f"{path}: повторяются имена страниц: {', '.join(dupes)}")
    return os.path.dirname(path), pages


def select(key, name=None):
    base, pages = load(key)
    if name:
        pages = [p for p in pages if p["name"] == name]
        if base and not pages:
            raise SystemExit(f"У сайта {key} нет страницы «{name}» в pages.yml")
    return base, pages


def prepare(key):
    """Перегенерировать JSON из исходников (source) для всех страниц сайта. Возвращает строки отчёта."""
    import json
    base, pages = load(key)
    out = []
    for p in pages:
        src = os.path.join(base, p["source"]) if p.get("source") else None
        if not src or not os.path.exists(src):
            out.append(f"  – {p['name']}: исходника нет ({p.get('source') or 'source не указан'}), JSON не трогаю")
            continue
        with open(src, encoding="utf-8") as f:
            data = design.extract_svg(f.read())
        with open(os.path.join(base, p["design"]), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        warn = f", пропущено под поворотом: {data['skipped_transformed']}" if data["skipped_transformed"] else ""
        out.append(f"  ✔ {p['name']}: {p['design']} — текстов {len(data['texts'])}, ширина {data['width']:.0f}{warn}")
    return out


def add(key, name, page, svg_path, png_path=None):
    """Новая страница: исходники → src/, JSON рядом, запись в конец pages.yml (комментарии в файле сохраняются)."""
    import json
    import shutil
    if not NAME_RE.match(name):
        raise SystemExit(f"Имя страницы «{name}» — только латиница, цифры и «-», например catalog")
    if not page.startswith("/") or page.startswith("//") or "#" in page:
        raise SystemExit(f"Путь страницы «{page}» должен начинаться с «/» и быть без «#», например /catalog/")
    base = folder(key)
    _, pages = load(key)
    if any(p["name"] == name for p in pages):
        raise SystemExit(f"Страница «{name}» уже есть в pages.yml — для обновления макета используй prepare")
    with open(svg_path, encoding="utf-8") as f:
        data = design.extract_svg(f.read())
    stem = f"{name}-{data['width']:.0f}"
    os.makedirs(os.path.join(base, "src"), exist_ok=True)
    shutil.copyfile(svg_path, os.path.join(base, "src", f"{stem}.svg"))
    if png_path:
        shutil.copyfile(png_path, os.path.join(base, "src", f"{stem}.png"))
    with open(os.path.join(base, f"{stem}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    path = os.path.join(base, "pages.yml")
    entry = (f"\n- name: {name}\n  page: {json.dumps(page, ensure_ascii=False)}\n  width: {data['width']:.0f}\n  design: {stem}.json\n"
             f"  source: src/{stem}.svg\n  dynamic: []     # зоны с меняющимся контентом: [y1, y2] или [x1, y1, x2, y2]\n")
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
    return stem, data
