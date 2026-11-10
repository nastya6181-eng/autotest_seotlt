"""SEO по каждой странице обхода: индексация, title, description, H1, alt, смешанный контент."""
from collections import defaultdict
from urllib.parse import urljoin, urlparse

from checks.core.findings import make

NAME = "seo"
RULES = {
    "noindex": ("error", "Страница закрыта от поисковиков (noindex)"),
    "mixed_content": ("error", "Ресурс по http:// на странице под https:// — браузер его заблокирует"),
    "missing_title": ("error", "Нет <title>"),
    "duplicate_title": ("warning", "Одинаковый <title> на разных страницах"),
    "title_length": ("info", "Длина <title> вне 10–70 символов"),
    "missing_description": ("warning", "Нет meta description"),
    "duplicate_description": ("info", "Одинаковый meta description на разных страницах"),
    "missing_h1": ("warning", "Нет заголовка H1"),
    "multiple_h1": ("info", "Несколько H1 на странице"),
    "img_no_alt": ("warning", "Картинка без атрибута alt"),
    "missing_lang": ("info", "Не указан язык страницы <html lang>"),
}


def run(pages, cfg, overrides, env):
    finding = make(NAME, RULES, overrides)
    out = []
    titles, descriptions = defaultdict(list), defaultdict(list)
    for page in pages:
        m = page.meta or {}
        robots = f"{m.get('robots', '')} {m.get('x_robots', '')}"
        if "noindex" in robots:
            out.append(finding("noindex", robots.strip(), page.url))
        title = m.get("title", "")
        if not title:
            out.append(finding("missing_title", "", page.url))
        else:
            titles[title].append(page.url)
            if not 10 <= len(title) <= 70:
                out.append(finding("title_length", title, page.url, message=f"{RULES['title_length'][1]}: {len(title)}"))
        desc = m.get("description")
        if not desc:
            out.append(finding("missing_description", "", page.url))
        else:
            descriptions[desc].append(page.url)
        if m.get("h1", 0) == 0:
            out.append(finding("missing_h1", "", page.url))
        elif m["h1"] > 1:
            out.append(finding("multiple_h1", str(m["h1"]), page.url))
        if not m.get("lang"):
            out.append(finding("missing_lang", "", page.url))
        for src in m.get("img_no_alt", []):
            out.append(finding("img_no_alt", urljoin(page.url, src), page.url))
        if urlparse(page.url).scheme == "https":
            for link in page.links:
                if link["tag"] != "a" and link["raw"].strip().lower().startswith("http://"):
                    out.append(finding("mixed_content", link["raw"].strip(), page.url))
    for title, urls in titles.items():
        if len(urls) > 1:
            out += [finding("duplicate_title", title, u) for u in urls]
    for desc, urls in descriptions.items():
        if len(urls) > 1:
            out += [finding("duplicate_description", desc[:120], u) for u in urls]
    return out
