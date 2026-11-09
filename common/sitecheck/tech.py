"""Техника сайта целиком: robots.txt, SSL, https-редирект, ответ на несуществующую страницу, sitemap."""
import re
import socket
import ssl
import time
import uuid
from urllib.parse import urljoin, urlparse

from .findings import make
from .links import request

NAME = "tech"
RULES = {
    "robots_blocks_all": ("error", "robots.txt закрывает весь сайт от поисковиков (Disallow: /)"),
    "ssl_expiring": ("error", "SSL-сертификат истекает меньше чем через 14 дней"),
    "ssl_expiring_soon": ("warning", "SSL-сертификат истекает меньше чем через 30 дней"),
    "ssl_error": ("error", "SSL-сертификат не проходит проверку"),
    "no_https_redirect": ("warning", "http:// не перенаправляет на https://"),
    "soft_404": ("warning", "Несуществующая страница отвечает 200 вместо 404"),
    "robots_missing": ("info", "Нет robots.txt"),
    "sitemap_missing": ("warning", "Нет sitemap.xml"),
}


def safe_request(url, timeout=15):
    try:
        return request(url, "GET", timeout)
    except Exception as e:
        return f"{type(e).__name__}", {}, None


def fetch_text(url, timeout=15):
    status, headers, resp = safe_request(url, timeout)
    if not resp:
        return status, ""
    try:
        return status, resp.read(2_000_000).decode("utf-8", "replace")
    finally:
        resp.close()


def robots_blocks_all(text):
    """Есть ли группа для * (или Yandex/Googlebot) с «Disallow: /» без разрешающих Allow."""
    blocked, agents, in_rules = set(), [], False
    rules = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
        elif key in ("disallow", "allow"):
            in_rules = True
            for a in agents:
                rules.setdefault(a, []).append((key, value))
    for agent in ("*", "yandex", "googlebot"):
        r = rules.get(agent, [])
        if ("disallow", "/") in r and not any(k == "allow" and v not in ("", "/") for k, v in r) \
                and ("allow", "/") not in r:
            blocked.add(agent)
    return blocked


def ssl_days_left(host, port=443, timeout=10):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            not_after = s.getpeercert()["notAfter"]
    return (ssl.cert_time_to_seconds(not_after) - time.time()) / 86400


def run(pages, cfg, overrides, env):
    finding = make(NAME, RULES, overrides)
    start = env["start_url"]
    root = f"{urlparse(start).scheme}://{urlparse(start).netloc}/"
    host = urlparse(start).hostname
    out = []

    status, robots = fetch_text(urljoin(root, "/robots.txt"))
    sitemaps = []
    if status != 200 or not robots.strip():
        out.append(finding("robots_missing", f"{root}robots.txt", root, message=f"{RULES['robots_missing'][1]} ({status})"))
    else:
        blocked = robots_blocks_all(robots)
        if blocked:
            out.append(finding("robots_blocks_all", "User-agent: " + ", ".join(sorted(blocked)), f"{root}robots.txt"))
        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)

    for url in sitemaps or [urljoin(root, "/sitemap.xml")]:
        status, body = fetch_text(url)
        if status == 200 and ("<urlset" in body or "<sitemapindex" in body):
            env["stats"]["sitemap_urls"] = env["stats"].get("sitemap_urls", 0) + body.count("<loc>")
            break
    else:
        out.append(finding("sitemap_missing", sitemaps[0] if sitemaps else f"{root}sitemap.xml", root))

    if urlparse(start).scheme == "https":
        try:
            days = ssl_days_left(host)
            env["stats"]["ssl_days_left"] = int(days)
            if days < 14:
                out.append(finding("ssl_expiring", f"{days:.0f} дн.", root))
            elif days < 30:
                out.append(finding("ssl_expiring_soon", f"{days:.0f} дн.", root))
        except (ssl.SSLError, ssl.CertificateError) as e:
            out.append(finding("ssl_error", str(getattr(e, "reason", "") or e)[:120], root))
        except OSError as e:
            out.append(finding("ssl_error", f"нет соединения: {e}"[:120], root))

        status, headers, resp = safe_request(f"http://{urlparse(start).netloc}/")
        if resp:
            resp.close()
        location = (headers or {}).get("Location", "") if status else ""
        if not (status in (301, 302, 307, 308) and location.startswith("https://")):
            out.append(finding("no_https_redirect", f"http://{urlparse(start).netloc}/ → {status} {location}".strip(), root))

    missing = urljoin(root, f"/autotest-404-{uuid.uuid4().hex[:8]}/")
    status, _, resp = safe_request(missing)
    if resp:
        resp.close()
    if status == 200:
        out.append(finding("soft_404", missing, root))
    return out
