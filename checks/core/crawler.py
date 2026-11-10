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

from checks.core import throttle

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
    meta: dict = field(default_factory=dict)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks, self.links, self.ids = [], [], set()
        self.meta = {"title": "", "description": None, "robots": "", "canonical": "", "lang": "",
                     "h1": 0, "img_no_alt": []}
        self._skip = 0
        self._a = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("id", "name"):
            if a.get(key):
                self.ids.add(a[key])
        if tag in SKIP_TAGS:
            self._skip += 1
        self._collect_meta(tag, a)
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

    def _collect_meta(self, tag, a):
        m = self.meta
        if tag == "html":
            m["lang"] = a.get("lang") or ""
        elif tag == "title" and not self._skip:
            self._in_title = True
        elif tag == "h1":
            m["h1"] += 1
        elif tag == "meta":
            name = (a.get("name") or "").lower()
            if name == "description":
                m["description"] = (a.get("content") or "").strip()
            elif name == "robots":
                m["robots"] = (a.get("content") or "").lower()
        elif tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
            m["canonical"] = a.get("href") or ""
        elif tag == "img" and a.get("src") and a.get("alt") is None:
            m["img_no_alt"].append(a["src"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "a":
            self._a = None
        if tag in BLOCK_END:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.meta["title"] = (self.meta["title"] + data).strip()
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
                    return None, r.geturl(), r.headers
                charset = r.headers.get_content_charset() or "utf-8"
                return r.read().decode(charset, "replace"), r.geturl(), r.headers
        except HTTPError as e:
            if e.code not in RETRY_STATUSES or attempt == retries:
                raise
            if not throttle.rate_limited(url, e.code, e.headers):
                time.sleep(retry_pause(e.headers, attempt))


def same_site(netloc, host):
    return netloc.lower().removeprefix("www.") == host.lower().removeprefix("www.")


def crawl(start, max_pages, delay=0.3, exclude=None, ignore_robots=False, failed=None, skipped=None):
    """Отдаёт Page по каждой открывшейся HTML-странице того же сайта.

    Страницы, которые не открылись, складывает в failed: [(url, ошибка)].
    Пропущенные без запроса или без разбора — в skipped: {причина: [url, …]}, чтобы пустой обход
    объяснял себя, а не молчал.
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
    queue, seen, done = deque([start]), {start}, set()
    while queue and max_pages > 0:
        url = queue.popleft()
        if robots and not robots.can_fetch(UA, url):
            if skipped is not None:
                skipped.setdefault("robots", []).append(url)
            continue
        try:
            html, final, headers = fetch_page(url)
        except Exception as e:
            if failed is not None:
                failed.append((url, str(getattr(e, "code", None) or e)))
            print(f"  ! не открылась {url}: {e}", file=sys.stderr)
            continue
        reason = ("not_html" if html is None else "offsite" if not same_site(urlparse(final).netloc, host)
                  else "duplicate" if final in done else "")
        if reason:
            if skipped is not None:
                where = urlparse(final).netloc  # только домен: в адресе назначения бывают токены
                skipped.setdefault(reason, []).append(f"{url} → {where}" if final != url else url)
            continue
        done.add(final)
        p = PageParser()
        p.feed(html)
        max_pages -= 1
        p.meta["x_robots"] = (headers.get("X-Robots-Tag") or "").lower()
        yield Page(final, p.text(), p.links, p.ids, p.meta)
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
