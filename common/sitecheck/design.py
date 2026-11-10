"""Макет из Figma (экспорт фрейма в SVG) против вёрстки: шрифты, цвета, отступы по текстам.

Опорные точки — тексты: они одинаковы в макете и на сайте, атрибуты в вёрстке не нужны.
Сравниваются не абсолютные координаты, а отступ до соседа сверху и выравнивание,
поэтому съехавший блок даёт одну строку в отчёте, а не красную страницу.
"""
import html
import re

TEXT_RE = re.compile(r"<text([^>]*)>(.*?)</text>", re.S)
TSPAN_RE = re.compile(r"<tspan([^>]*)>(.*?)</tspan>", re.S)
NAMED = {"white": "#FFFFFF", "black": "#000000"}


def attr(attrs, name, default=None):
    m = re.search(rf'\b{name}="([^"]*)"', attrs)
    return m.group(1) if m else default


def normalize(text):
    """Для сопоставления: без регистра, ё=е, неразрывные пробелы и переносы схлопнуты."""
    text = html.unescape(text).replace(" ", " ").replace("­", "").replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", text).strip().casefold()


def join_lines(lines):
    out = ""
    for line in lines:
        line = line.strip()
        if not out:
            out = line
        elif out.endswith("-"):
            out += line  # перенос «научно-» + «исследовательских»
        else:
            out += " " + line
    return out


def extract_svg(svg_text):
    """Тексты фрейма: строка, позиция первой строки (левый край, базовая линия), шрифт, цвет."""
    width = float(attr(svg_text[:500], "width", "0"))
    texts = []
    for attrs, body in TEXT_RE.findall(svg_text):
        spans = TSPAN_RE.findall(body)
        if not spans:
            continue
        lines = [html.unescape(t) for _, t in spans]
        xs = [float(attr(a, "x", "0")) for a, _ in spans]
        ys = [float(attr(a, "y", "0")) for a, _ in spans]
        text = join_lines(lines)
        if not text.strip():
            continue
        line_ys = sorted(set(round(y, 2) for y in ys))
        fs = float(attr(attrs, "font-size", "16"))
        ls = attr(attrs, "letter-spacing", "0em")
        texts.append({
            "text": text,
            "x": round(min(xs), 2),
            "y": round(ys[0], 2),
            "lines": len(line_ys),
            "line_height": round(line_ys[1] - line_ys[0], 2) if len(line_ys) > 1 else None,
            "font_family": attr(attrs, "font-family", ""),
            "font_size": fs,
            "font_weight": int(attr(attrs, "font-weight", "400")),
            "letter_spacing_px": round(float(ls[:-2]) * fs, 2) if ls.endswith("em") else float(ls.rstrip("px") or 0),
            "color": NAMED.get(attr(attrs, "fill", "#000000"), attr(attrs, "fill", "#000000")).upper(),
        })
    return {"width": width, "texts": texts}


# Собирает с открытой страницы все текстовые блоки: текст (как видит пользователь, с text-transform),
# левый край и базовая линию первой строки, вычисленные стили. Базовая линия = верх области
# содержимого первой строки + ascent шрифта (canvas.measureText), как у tspan y в SVG.
COLLECT_JS = r"""
() => {
  const ctx = document.createElement('canvas').getContext('2d');
  const out = [];
  const seen = new Set();
  const visible = el => { const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0 && el.getClientRects().length; };
  const ownText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const blocks = new Set();
  for (const el of document.body.querySelectorAll('*')) {
    if (!ownText(el) || !visible(el)) continue;
    blocks.add(el);
    let p = el.parentElement;
    for (let i = 0; i < 2 && p && p !== document.body; i++, p = p.parentElement) blocks.add(p);
  }
  for (const el of blocks) {
    const text = (el.innerText || '').trim();
    if (!text || text.length > 600 || seen.has(el)) continue;
    // обёртка с тем же текстом, что у потомка (div > span «46»), — берём сам span
    if ([...el.querySelectorAll('*')].some(c => blocks.has(c) && (c.innerText || '').trim() === text)) continue;
    seen.add(el);
    const range = document.createRange(); range.selectNodeContents(el);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    const first = rects.reduce((a, r) => (r.top < a.top - 1 || (Math.abs(r.top - a.top) <= 1 && r.left < a.left)) ? r : a);
    const s = getComputedStyle(el);
    ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    const asc = ctx.measureText(text.slice(0, 50)).fontBoundingBoxAscent;
    const lineTops = [...new Set(rects.map(r => Math.round(r.top)))];
    const right = Math.max(...rects.map(r => r.right));
    const left = Math.min(...rects.map(r => r.left));
    const offscreen = right <= 0 || left >= innerWidth;  // слайд карусели за краем, скрытое меню
    out.push({ offscreen,
      text, tag: el.tagName.toLowerCase(), cls: (el.className && el.className.baseVal === undefined) ? el.className : '',
      x: Math.min(...rects.map(r => r.left)) + scrollX,
      y: first.top + scrollY + asc,
      lines: lineTops.length,
      font_family: s.fontFamily, font_size: parseFloat(s.fontSize), font_weight: parseInt(s.fontWeight),
      letter_spacing_px: s.letterSpacing === 'normal' ? 0 : parseFloat(s.letterSpacing),
      line_height_px: s.lineHeight === 'normal' ? null : parseFloat(s.lineHeight),
      color: s.color, text_transform: s.textTransform, depth: (() => { let d = 0, n = el; while (n = n.parentElement) d++; return d; })(),
    });
  }
  return out;
}
"""


def rgb_to_hex(css):
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?", css or "")
    if not m:
        return (css or "").upper()
    r, g, b = (int(x) for x in m.groups()[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


MAX_SHIFT_PX = 500  # дальше — уже не «съехало», а «этот текст на сайте в другом месте»


def match(design, site):
    """Один к одному: каждому тексту макета — ближайший видимый блок сайта с тем же текстом.

    Из обёрток одного текста берётся самая глубокая (сам текст). Повторы («9 февраля 2026»
    в каждой карточке) раздаются по близости, а не все одному элементу.
    Возвращает пары, тексты, которых на сайте нет, и найденные далеко от своего места.
    """
    by_text = {}
    for s in site:
        if s.get("offscreen"):
            continue
        key = normalize(s["text"])
        same = [o for o in by_text.get(key, []) if abs(o["x"] - s["x"]) < 1 and abs(o["y"] - s["y"]) < 1]
        if same:  # обёртка того же текста в той же точке — оставляем самый глубокий элемент
            if s["depth"] > same[0]["depth"]:
                by_text[key][by_text[key].index(same[0])] = s
            continue
        by_text.setdefault(key, []).append(s)
    options = []
    for di, d in enumerate(design):
        for s in by_text.get(normalize(d["text"]), []):
            options.append((((s["x"] - d["x"]) ** 2 + (s["y"] - d["y"]) ** 2) ** 0.5, di, id(s), s))
    options.sort(key=lambda o: o[0])
    taken_d, taken_s, pairs, far = set(), set(), [], []
    for dist, di, sid, s in options:
        if di in taken_d or sid in taken_s:
            continue
        taken_d.add(di)
        taken_s.add(sid)
        (pairs if dist <= MAX_SHIFT_PX else far).append((design[di], s))
    missing = [d for di, d in enumerate(design) if di not in taken_d]
    return pairs, missing, far


TOL_PX = 2
NEIGHBOUR_PX = 600  # сосед сверху ищется рядом; дальше — это уже другой блок страницы


def compare(pairs):
    """Отличия по каждой паре: стиль — напрямую, положение — относительно соседа сверху в той же колонке."""
    pairs = sorted(pairs, key=lambda p: (p[0]["y"], p[0]["x"]))
    results = []
    for i, (d, s) in enumerate(pairs):
        diffs = []
        if abs(d["font_size"] - s["font_size"]) > 0.5:
            diffs.append(("font-size", d["font_size"], s["font_size"]))
        if d["font_weight"] != s["font_weight"]:
            diffs.append(("font-weight", d["font_weight"], s["font_weight"]))
        if d["font_family"] and d["font_family"].lower() not in s["font_family"].lower().split(",")[0]:
            diffs.append(("font-family", d["font_family"], s["font_family"].split(",")[0].strip('"\' ')))
        if d["color"] != rgb_to_hex(s["color"]):
            diffs.append(("color", d["color"], rgb_to_hex(s["color"])))
        if abs(d["letter_spacing_px"] - s["letter_spacing_px"]) > 0.3:
            diffs.append(("letter-spacing", d["letter_spacing_px"], s["letter_spacing_px"]))
        if d["line_height"] and s["line_height_px"] and abs(d["line_height"] - s["line_height_px"]) > 1:
            diffs.append(("line-height", d["line_height"], s["line_height_px"]))
        if d["lines"] != s["lines"]:
            diffs.append(("строк", d["lines"], s["lines"]))
        if abs(d["x"] - s["x"]) > TOL_PX:
            diffs.append(("левый край", round(d["x"]), round(s["x"])))
        above = next((p for p in reversed(pairs[:i]) if abs(p[0]["x"] - d["x"]) < 40
                      and d["y"] - NEIGHBOUR_PX < p[0]["y"] < d["y"] - 1), None)
        if above:
            gap_d, gap_s = d["y"] - above[0]["y"], s["y"] - above[1]["y"]
            if abs(gap_d - gap_s) > TOL_PX:
                diffs.append((f"отступ от «{above[0]['text'][:40]}»", round(gap_d), round(gap_s)))
        results.append({"design": d, "site": s, "diffs": diffs})
    return results
