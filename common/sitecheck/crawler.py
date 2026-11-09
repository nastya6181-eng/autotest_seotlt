"""Обход сайта. Один проход отдаёт всем проверкам текст, ссылки и id каждой страницы."""
import re
import sys
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import quote, urldefrag, urljoin, urlparse
from urllib.request import Request, build_opener

from . import throttle

UA = "Mozilla/5.0 (seotlt-autotest)"
RETRY_STATUSES = {429, 502, 503, 504}
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "code", "pre"}
TEXT_ATTRS = {"alt", "title", "placeholder", "aria-label"}
BLOCK_END = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "br", "title",
             "a", "span", "button", "label", "option", "section", "header", "footer", "nav"}
SRC_TAGS = {"img": "src", "script": "src", "iframe": "src", "source": "src", "link": "href"}
SKIP_EXT = re.compile(
    r"\.(jpe?g|png|gif|webp|svg|ico|pdf|docx?|xlsx?|pptx?|zip|rar|7z|mp4|mp3|avi|css|js|xml|json|txt|woff2?|ttf)$",
    re.I,
)


@dataclass
class Page:
    url: str
    text: str
    links: list = field(default_factory=list)
    ids: set = field(default_factory=set)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks, self.links, self.ids = [], [], set()
        self._skip = 0
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("id", "name"):
            if a.get(key):
                self.ids.add(a[key])
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag in {"br", "hr", "img", "input"}:
            self.chunks.append("\n")
        if tag == "a" and "href" in a:
            self._a = {"tag": "a", "raw": a["href"] or "", "text": a.get("aria-label") or "",
                       "blank": (a.get("target") or "").lower() == "_blank"}
            self.links.append(self._a)
        elif tag in SRC_TAGS and a.get(SRC_TAGS[tag]):
            if not (tag == "link" and (a.get("rel") or "") in {"preconnect", "dns-prefetch"}):
                self.links.append({"tag": tag, "raw": a[SRC_TAGS[tag]], "text": a.get("alt") or ""})
        if tag == "meta" and (a.get("name") or a.get("property", "")).lower() in {
            "description", "og:title", "og:description"
        }:
            self.chunks.append("\n" + (a.get("content") or "") + "\n")
        for k in TEXT_ATTRS:
            if a.get(k):
                self.chunks.append("\n" + a[k] + "\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "a":
            self._a = None
        if tag in BLOCK_END:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._a is not None:
            self._a["text"] = (self._a["text"] + " " + data.strip()).strip()[:80]
        if not self._skip:
            self.chunks.append(data)

    def text(self):
        return re.sub(r"[ \t\xa0]+", " ", "".join(self.chunks))


def retry_pause(headers, attempt):
    try:
        return min(float(headers.get("Retry-After")), 60)
    except (TypeError, ValueError):
        return 2 ** attempt * 2


def fetch_page(url, retries=3):
    req = Request(url, headers={"User-Agent": UA})
    opener = build_opener()
    for attempt in range(retries + 1):
        throttle.wait(url)
        try:
            with opener.open(req, timeout=20) as r:
                if "text/html" not in r.headers.get("Content-Type", ""):
                    return None, r.geturl()
                charset = r.headers.get_content_charset() or "utf-8"
                return r.read().decode(charset, "replace"), r.geturl()
        except HTTPError as e:
            if e.code not in RETRY_STATUSES or attempt == retries:
                raise
            if not throttle.rate_limited(url, e.code, e.headers):
                time.sleep(retry_pause(e.headers, attempt))


def same_site(netloc, host):
    return netloc.lower().removeprefix("www.") == host.lower().removeprefix("www.")


def crawl(start, max_pages, delay=0.3, exclude=None, ignore_robots=False, failed=None):
    """Отдаёт Page по каждой открывшейся HTML-странице того же сайта.

    Страницы, которые не открылись, складывает в failed: [(url, ошибка)].
    """
    host = urlparse(start).netloc
    robots = None
    if not ignore_robots:
        robots = urllib.robotparser.RobotFileParser(urljoin(start, "/robots.txt"))
        try:
            robots.read()
            if robots.crawl_delay(UA):
                delay = max(delay, float(robots.crawl_delay(UA)))
        except Exception:
            robots = None
    queue, seen = deque([start]), {start}
    while queue and max_pages > 0:
        url = queue.popleft()
        if robots and not robots.can_fetch(UA, url):
            continue
        try:
            html, final = fetch_page(url)
        except Exception as e:
            if failed is not None:
                failed.append((url, str(getattr(e, "code", None) or e)))
            print(f"  ! не открылась {url}: {e}", file=sys.stderr)
            continue
        if html is None or not same_site(urlparse(final).netloc, host):
            continue
        p = PageParser()
        p.feed(html)
        max_pages -= 1
        yield Page(final, p.text(), p.links, p.ids)
        for link in p.links:
            if link["tag"] != "a":
                continue
            href = link["raw"].strip()
            if not href or href.lower().startswith(("mailto:", "tel:", "javascript:")):
                continue
            u = quote(urldefrag(urljoin(final, href))[0], safe=":/?&=%#@+,;~")
            pu = urlparse(u)
            if exclude and exclude.search(u):
                continue
            if pu.scheme in {"http", "https"} and same_site(pu.netloc, host) \
                    and not SKIP_EXT.search(pu.path) and u not in seen:
                seen.add(u)
                queue.append(u)
        time.sleep(delay)
