"""Список сайтов из переменных окружения.

SITES — все сайты для прогона, по одному на строку:
            ключ=https://адрес [опция=значение ...]
        Опции переопределяют настройки сайта: max_pages, delay, max_rps, cooldown,
        ignore_robots, exclude, workers. В GitHub SITES хранится секретом репозитория.
SITE  — один сайт: ключ из SITES или любой адрес (разовый прогон с настройками по умолчанию).

Локально переменные читаются ещё и из файла .env в корне репозитория.
Если есть папка projects/<ключ>/ с project.yml, её настройки применяются к сайту с этим ключом.
"""
import os
import re
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECTS = os.path.join(ROOT, "projects")
OPTIONS = {"max_pages": int, "delay": float, "max_rps": float, "cooldown": float,
           "ignore_robots": lambda v: v.lower() in ("1", "true", "yes", "да"), "exclude": str,
           "workers": int}


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
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def key_from_url(url):
    return re.sub(r"[^a-z0-9]+", "-", host(url) + urlparse(url).path.rstrip("/")).strip("-")


def project_dir(key):
    path = os.path.join(PROJECTS, key)
    return path if os.path.exists(os.path.join(path, "project.yml")) else None


def parse_line(line):
    parts = line.split()
    head, opts = parts[0], parts[1:]
    key, url = head.split("=", 1) if re.match(r"^[\w-]+=", head) else ("", head)
    if not re.match(r"^https?://", url):
        url = "https://" + url
    options = {}
    for opt in opts:
        name, sep, value = opt.partition("=")
        if not sep or name not in OPTIONS:
            raise SystemExit(f"Опция «{opt}» у сайта {key or url}: допустимо {', '.join(OPTIONS)}")
        try:
            options[name] = OPTIONS[name](value)
        except ValueError:
            raise SystemExit(f"Опция «{opt}» у сайта {key or url}: неверное значение") from None
    return {"key": key or key_from_url(url), "url": url, "options": options}


def parse_sites(raw):
    lines = (l.split("#", 1)[0].strip() for l in (raw or "").splitlines())
    sites = [parse_line(l) for l in lines if l]
    keys = [s["key"] for s in sites]
    if "all" in keys:
        raise SystemExit("Ключ «all» занят: SITE=all значит «все сайты». Переименуй сайт в SITES")
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise SystemExit(f"В SITES повторяются ключи: {', '.join(dupes)} — у каждого сайта свой ключ")
    return sites


def select(site=None):
    """Сайты из SITES, отфильтрованные по SITE: ключ или адрес. Адрес не из списка — разовый прогон."""
    site = (site if site is not None else os.environ.get("SITE", "")).strip()
    sites = parse_sites(os.environ.get("SITES"))
    if not site or site == "all":
        return sites
    head, _, extra = site.partition(" ")
    found = [s for s in sites if s["key"] == head or s["url"].rstrip("/") == head.rstrip("/")]
    if found and extra.strip():
        overrides = parse_line(f"{found[0]['url']} {extra}")["options"]
        return [{**found[0], "options": {**found[0]["options"], **overrides}, "adhoc": site}]
    if found:
        return found
    if "." in site:
        return [{**parse_line(site), "adhoc": site}]
    raise SystemExit(f"Сайта «{site}» нет в SITES")
