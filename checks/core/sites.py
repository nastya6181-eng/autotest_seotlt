"""Список сайтов из переменных окружения.

SITE_<КЛЮЧ> — один сайт на переменную: «https://адрес [опция=значение ...]».
        Ключ — суффикс имени в нижнем регистре, «_» → «-»: SITE_INNO_TECH → inno-tech.
        В GitHub каждая такая переменная — отдельный секрет репозитория.
SITES — запасной вариант для локального .env: все сайты в одной переменной, по строке
        «ключ=https://адрес [опция=значение ...]».
        Опции: max_pages, delay, max_rps, cooldown, ignore_robots, exclude, workers.
SITE  — прогнать один: ключ или любой адрес (разовый прогон с настройками по умолчанию).

Локально переменные читаются ещё и из файла .env в корне репозитория.
Данные сайта — в sites/<ключ>/: паспорт README.md и папки слоёв (content/, design/, …).
Настройки контента и SEO — sites/<ключ>/content/project.yml и ignore.txt (если есть).
"""
import os
import re
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITES_DIR = os.path.join(ROOT, "sites")
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
    """Настройки контента и SEO сайта: sites/<ключ>/content/ с project.yml или ignore.txt."""
    path = os.path.join(SITES_DIR, key, "content")
    has = any(os.path.exists(os.path.join(path, f)) for f in ("project.yml", "ignore.txt"))
    return path if has else None

def parse_line(line):
    parts = line.split()
    head, opts = parts[0], parts[1:]
    key, url = head.split("=", 1) if re.match(r"^[\w-]+=", head) else ("", head)
    if not re.match(r"^https?://", url):
        url = "https://" + url
    options = {}
    for opt in opts:
        name, sep, value = opt.partition("=")
        who = key or "без ключа"  # адрес в ошибку не пишем: она печатается до маскировки
        if not sep or name not in OPTIONS:
            raise SystemExit(f"Опция «{name}» у сайта {who}: допустимо {', '.join(OPTIONS)}")
        try:
            options[name] = OPTIONS[name](value)
        except ValueError:
            raise SystemExit(f"Опция «{name}» у сайта {who}: неверное значение") from None
    return {"key": key or key_from_url(url), "url": url, "options": options, "keyed": bool(key)}


SITE_VAR = re.compile(r"SITE_[A-Z0-9_]+")


def key_of(var):
    return var[len("SITE_"):].lower().replace("_", "-")


def site_vars(env=None):
    """Переменные SITE_<КЛЮЧ> → строки «ключ=значение» в порядке имён."""
    env = os.environ if env is None else env
    return [f"{key_of(name)}={value.strip()}" for name, value in sorted(env.items())
            if SITE_VAR.fullmatch(name) and value and value.strip()]


def parse_sites(raw, extra_lines=()):
    lines = [l.split("#", 1)[0].strip() for l in (raw or "").splitlines()] + list(extra_lines)
    sites = [parse_line(l) for l in lines if l]
    unkeyed = [s["url"] for s in sites if not s.pop("keyed")]
    if unkeyed:
        raise SystemExit(f"В SITES у {len(unkeyed)} сайт(ов) нет ключа: пиши «ключ=адрес». Ключ из домена "
                         "раскрыл бы адрес в матрице и логах")
    keys = [s["key"] for s in sites]
    if "all" in keys:
        raise SystemExit("Ключ «all» занят: SITE=all значит «все сайты». Переименуй сайт в SITES")
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise SystemExit(f"В SITES повторяются ключи: {', '.join(dupes)} — у каждого сайта свой ключ")
    return sites


def all_sites():
    """Сайты из SITE_<КЛЮЧ> и SITES вместе; ключи не должны повторяться."""
    return parse_sites(os.environ.get("SITES"), site_vars())


def select(site=None):
    """Сайты из SITES, отфильтрованные по SITE: ключ или адрес. Адрес не из списка — разовый прогон."""
    site = (site if site is not None else os.environ.get("SITE", "")).strip()
    sites = all_sites()
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
        line = parse_line(site)
        line.pop("keyed")
        return [{**line, "adhoc": site}]
    raise SystemExit(f"Сайта «{site}» нет ни в SITE_<КЛЮЧ>, ни в SITES")
