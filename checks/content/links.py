"""Ссылки и ресурсы: битые адреса, кривые href, якоря, редиректы."""
import re
import ssl
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urldefrag, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from checks.core import throttle
from checks.core.crawler import RETRY_STATUSES, SRC_TAGS, UA, retry_pause, same_site
from checks.core.findings import make

NAME = "links"
RULES = {
    "page_failed": ("error", "Страница сайта не открылась при обходе"),
    "broken_internal": ("error", "Битая ссылка или ресурс на этом сайте"),
    "broken_external": ("warning", "Битая ссылка на другой сайт"),
    "bad_href": ("error", "Неправильно оформленная ссылка"),
    "placeholder_href": ("warning", "Ссылка-заглушка «#», клик никуда не ведёт"),
    "missing_anchor": ("warning", "Якорь #id отсутствует на странице"),
    "redirect": ("info", "Ссылка ведёт через редирект, лучше поставить конечный адрес"),
    "external_same_tab": ("info", "Внешняя ссылка открывается в той же вкладке"),
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = build_opener(NoRedirect)


def request(url, method, timeout):
    req = Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    throttle.wait(url)
    try:
        r = OPENER.open(req, timeout=timeout)
        return r.status, r.headers, r
    except HTTPError as e:
        return e.code, e.headers, None


def check_url(url, timeout=15, max_redirects=10, retries=3):
    """(статус, итоговый URL, цепочка редиректов, ошибка)."""
    chain, current = [], url
    for _ in range(max_redirects):
        try:
            for attempt in range(retries + 1):
                status, headers, resp = request(current, "HEAD", timeout)
                if status in {400, 403, 404, 405, 501} or status >= 500 or status == 429:
                    status, headers, resp = request(current, "GET", timeout)
                if resp:
                    resp.close()
                if status not in RETRY_STATUSES or attempt == retries:
                    break
                if not throttle.rate_limited(current, status, headers):
                    time.sleep(retry_pause(headers, attempt))
        except ssl.SSLError as e:
            return None, current, chain, f"SSL: {e.reason or e}"
        except URLError as e:
            reason = e.reason
            if isinstance(reason, ssl.SSLError):
                return None, current, chain, f"SSL: {reason.reason or reason}"
            return None, current, chain, str(reason)
        except Exception as e:
            return None, current, chain, f"{type(e).__name__}: {e}"
        if status in {301, 302, 303, 307, 308} and headers.get("Location"):
            chain.append(status)
            current = urljoin(current, headers["Location"])
            continue
        return status, current, chain, ""
    return None, current, chain, "слишком много редиректов"


def normalize(raw, base):
    """(абсолютный URL или None, правило, описание проблемы)."""
    href = raw.strip()
    low = href.lower()
    if not href:
        return None, "bad_href", "пустой href"
    if href == "#":
        return None, "placeholder_href", ""
    if low.startswith("javascript:"):
        return None, "", ""
    if low.startswith("mailto:"):
        addr = unquote(href[7:].split("?")[0]).strip()
        ok = addr and all(EMAIL.match(a.strip()) for a in addr.split(",") if a.strip())
        return None, ("" if ok else "bad_href"), ("" if ok else f"кривой mailto: «{addr}»")
    if low.startswith("tel:"):
        ok = 10 <= len(re.sub(r"[^\d]", "", href[4:])) <= 13
        return None, ("" if ok else "bad_href"), ("" if ok else f"кривой tel: «{href[4:]}»")
    if re.match(r"^\+?[\d\s()\-]{7,}$", href):
        return None, "bad_href", "телефон без tel:"
    if low.startswith("www.") or re.match(
            r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(ru|рф|su|com|org|net|dev|io|info|pro|online|site|biz)(/\S*)?$", low):
        return None, "bad_href", "адрес без https:// (откроется как страница вашего сайта)"
    if re.match(r"^[\w.-]+@[\w.-]+\.\w+$", href):
        return None, "bad_href", "e-mail без mailto:"
    rule, problem = "", ""
    if " " in href:
        rule, problem = "bad_href", "пробел в адресе"
    if re.match(r"^https?:/(?!/)", low):
        rule, problem = "bad_href", "сломанный протокол"
    url = urljoin(base, href)
    if urlparse(url).scheme not in {"http", "https"}:
        return None, rule, problem
    return quote(url, safe=":/?&=%#@+,;~!$'()*[]"), rule, problem


def element(link):
    """Ссылка так, как её искать в коде страницы: тег, href и текст."""
    tag, text = link["tag"], link["text"][:60] + ("…" if len(link["text"]) > 60 else "")
    if tag == "a":
        return f'<a href="{link["raw"]}">{text}</a>'
    return f'<{tag} {SRC_TAGS.get(tag, "src")}="{link["raw"]}">'


def where(link):
    """Где ссылка на странице: блок и путь для поиска в DevTools (F12 → Elements → Ctrl+F)."""
    if not link.get("path"):
        return link["text"]
    attr = "href" if link["tag"] == "a" else SRC_TAGS.get(link["tag"], "src")
    raw, op = link["raw"], "="
    if re.match(r"(?i)^https?://", raw):  # без домена: адрес сайта в публичный отчёт не попадает
        u = urlparse(raw)
        raw, op = u.path + (f"?{u.query}" if u.query else "") + (f"#{u.fragment}" if u.fragment else ""), "$="
    if len(raw) > 80:
        raw, op = (raw[-80:], "$=") if op == "$=" else (raw[:80], "^=")
    if (op == "$=" and not raw) or re.search(r'[\\\n\r"]', raw):
        selector = link["path"]  # такой адрес в селектор не вставить без экранирования — ищем по пути
    else:
        selector = re.sub(r"[^ ]+$", lambda m: f'{m.group(0)}[{attr}{op}"{raw}"]', link["path"])
    return f"{link['area'] + ' · ' if link.get('area') else ''}`{selector}`"


def run(pages, cfg, overrides, env):
    finding = make(NAME, RULES, overrides)
    host = urlparse(env["start_url"]).netloc
    external = cfg.get("external", True)
    skip = re.compile(cfg["ignore"]) if cfg.get("ignore") else None
    out = [finding("page_failed", url, url, message=f"Страница не открылась: {err}")
           for url, err in env["failed_pages"]]

    uses = defaultdict(list)  # адрес -> [(страница, текст ссылки)]
    page_ids = {urldefrag(p.url)[0]: p.ids for p in pages}
    for page in pages:
        for link in page.links:
            url, rule, problem = normalize(link["raw"], page.url)
            if rule:
                out.append(finding(rule, element(link), page.url, where(link),
                                   message=f"{RULES[rule][1]}: {problem}" if problem else None))
            if not url:
                continue
            base, frag = urldefrag(url)
            internal = same_site(urlparse(base).netloc, host)
            if frag and link["tag"] == "a" and internal:
                ids = page_ids.get(base)
                if ids is not None and unquote(frag) not in ids:
                    out.append(finding("missing_anchor", f"{base}#{frag}", page.url, where(link)))
            if link["tag"] == "a" and not internal and not link.get("blank"):
                out.append(finding("external_same_tab", url, page.url, where(link)))
            if (internal or external) and not (skip and skip.search(base)):
                uses[base].append((page.url, where(link) or link["tag"]))

    with ThreadPoolExecutor(cfg.get("workers", 3)) as pool:
        results = dict(zip(uses, pool.map(check_url, uses)))

    for url, (status, final, chain, err) in results.items():
        internal = same_site(urlparse(url).netloc, host)
        if err or status is None or status >= 400:
            rule = "broken_internal" if internal else "broken_external"
            for page, text in uses[url]:
                out.append(finding(rule, url, page, text,
                                   message=f"{RULES[rule][1]}: {err or status}"))
        elif chain:
            for page, text in uses[url]:
                out.append(finding("redirect", url, page, text,
                                   message=f"Редирект {'→'.join(map(str, chain))} на {final}"))
    env["stats"]["urls_checked"] = len(uses)
    return out
