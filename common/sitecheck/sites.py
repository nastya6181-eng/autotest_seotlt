"""Список сайтов из переменных окружения и привязка сайта к папке проекта.

SITES — все сайты для прогона: по одному на строку (или через запятую),
        «ключ=https://адрес» или просто «https://адрес». # — комментарий.
SITE  — один сайт: адрес или ключ из SITES / projects/.
Переменные читаются из окружения, а локально ещё и из файла .env в корне репозитория.
"""
import os
import re
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECTS = os.path.join(ROOT, "projects")


def load_dotenv(path=os.path.join(ROOT, ".env")):
    """Значения из .env не перебивают уже заданные в окружении."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    values = {}
    for m in re.finditer(r'^[ \t]*([A-Z_][A-Z0-9_]*)[ \t]*=[ \t]*(?:"([^"]*)"|\'([^\']*)\'|([^\n#]*))', text, re.M):
        values[m.group(1)] = next(v for v in m.groups()[1:] if v is not None).strip()
    for k, v in values.items():
        os.environ.setdefault(k, v)


def host(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def key_from_url(url):
    return re.sub(r"[^a-z0-9]+", "-", host(url) + urlparse(url).path.rstrip("/")).strip("-")


def project_url(key):
    path = os.path.join(PROJECTS, key, "project.yml")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        m = re.search(r"^url:\s*['\"]?(\S+?)['\"]?\s*$", f.read(), re.M)
    return m.group(1) if m else None


def project_keys():
    if not os.path.isdir(PROJECTS):
        return []
    return sorted(d for d in os.listdir(PROJECTS)
                  if not d.startswith("_") and os.path.exists(os.path.join(PROJECTS, d, "project.yml")))


def project_for(url):
    """Папка projects/<ключ>, чей url на том же домене, или None."""
    for key in project_keys():
        purl = project_url(key)
        if purl and host(purl) == host(url):
            return key
    return None


def parse_sites(raw):
    sites = []
    for item in re.split(r"[\n,]+", raw or ""):
        item = item.split("#", 1)[0].strip()
        if not item:
            continue
        key, _, url = item.rpartition("=") if re.match(r"^[\w-]+=", item) else ("", "", item)
        if not re.match(r"^https?://", url):
            url = "https://" + url
        sites.append({"key": key or project_for(url) or key_from_url(url), "url": url})
    return sites


def all_sites():
    """SITES из окружения; если не задан — сайты из папок projects/."""
    sites = parse_sites(os.environ.get("SITES"))
    if sites:
        return sites
    return [{"key": k, "url": project_url(k)} for k in project_keys() if project_url(k)]


def select(site=None):
    """Отфильтровать по SITE: ключ или адрес. Адрес не из списка — разовый прогон."""
    site = (site if site is not None else os.environ.get("SITE", "")).strip()
    sites = all_sites()
    if not site or site == "all":
        return sites
    found = [s for s in sites if s["key"] == site or s["url"].rstrip("/") == site.rstrip("/")]
    if found:
        return found
    if project_url(site):
        return [{"key": site, "url": project_url(site)}]
    if "." in site:
        return parse_sites(site)
    raise SystemExit(f"Сайт «{site}» не найден ни в SITES, ни в projects/")
