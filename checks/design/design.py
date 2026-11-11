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


def join_lines(lines, ys=None):
    """Склеить tspan в текст. На одной базовой линии — это куски одной строки с разным стилем
    (жирное слово), их пробелы уже внутри; на разных — переносы строк."""
    out, prev_y = "", None
    for i, raw in enumerate(lines):
        y = ys[i] if ys else None
        if out and y is not None and prev_y is not None and abs(y - prev_y) < 0.5:
            out += raw  # та же строка: «Open» + «AI» → «OpenAI», «научно » + «исследование» как есть
        else:
            line = raw.strip()
            if not out:
                out = raw.lstrip()  # хвостовой пробел первого куска нужен: «Hello » + «world»
            elif out.endswith("-"):
                out += line  # перенос «научно-» + «исследовательских»
            else:
                out = out.rstrip() + " " + line
        prev_y = y
    return out.strip()


TAG_RE = re.compile(r"<(/?)(g|text)\b([^>]*?)(/?)>")
TRANSLATE_RE = re.compile(r"^\s*translate\(\s*([-\d.]+)(?:[\s,]+([-\d.]+))?\s*\)\s*$")


def text_offsets(svg_text):
    """Сдвиг каждого <text> от родительских <g transform="translate(…)">: {позиция тега: (dx, dy) или None}.
    None — под другим преобразованием (поворот, масштаб, матрица): координаты такого текста не верны."""
    stack, out = [], {}
    for m in TAG_RE.finditer(svg_text):
        close, tag, attrs, selfclose = m.groups()
        if close:
            if stack:
                stack.pop()
            continue
        own = attr(attrs, "transform")
        step = (0.0, 0.0)
        if own:
            t = TRANSLATE_RE.match(own)
            step = (float(t.group(1)), float(t.group(2) or 0)) if t else None
        if tag == "text":
            dx = dy = 0.0
            for s in stack + [step]:
                if s is None:
                    dx = None
                    break
                dx, dy = dx + s[0], dy + s[1]
            out[m.start()] = None if dx is None else (dx, dy)
        if not selfclose and tag == "g":
            stack.append(step)
        elif not selfclose:
            stack.append((0.0, 0.0))
    return out


def extract_svg(svg_text):
    """Тексты фрейма: строка, позиция первой строки (левый край, базовая линия), шрифт, цвет."""
    width = float(attr(svg_text[:500], "width", "0"))
    offsets = text_offsets(svg_text)
    texts, skipped = [], 0
    for m in TEXT_RE.finditer(svg_text):
        attrs, body = m.groups()
        offset = offsets.get(m.start(), (0.0, 0.0))
        if offset is None:
            skipped += 1
            continue
        spans = TSPAN_RE.findall(body)
        if not spans and body.strip() and not body.lstrip().startswith("<"):
            spans = [(attrs, body)]  # <text x y>Текст</text> без tspan — координаты на самом <text>
        if not spans:
            continue
        lines = [html.unescape(t) for _, t in spans]
        # tspan без своих x/y наследует координаты <text>
        xs = [float(attr(a, "x", attr(attrs, "x", "0"))) + offset[0] for a, _ in spans]
        ys = [float(attr(a, "y", attr(attrs, "y", "0"))) + offset[1] for a, _ in spans]
        text = join_lines(lines, ys)
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
            "color": with_alpha(NAMED.get(attr(attrs, "fill", "#000000"), attr(attrs, "fill", "#000000")).upper(),
                                attr(attrs, "fill-opacity") or attr(attrs, "opacity")),
        })
    return {"width": width, "texts": texts, "skipped_transformed": skipped}


# Собирает с открытой страницы все текстовые блоки: текст (как видит пользователь, с text-transform),
# левый край и базовая линию первой строки, вычисленные стили. Базовая линия = верх области
# содержимого первой строки + ascent шрифта (canvas.measureText), как у tspan y в SVG.
COLLECT_JS = r"""
() => {
  const ctx = document.createElement('canvas').getContext('2d');
  const out = [];
  const seen = new Set();
  // checkVisibility учитывает и предков: opacity:0 или visibility:hidden у обёртки прячут текст
  const visible = el => el.getClientRects().length && (el.checkVisibility
    ? el.checkVisibility({opacityProperty: true, visibilityProperty: true})
    : getComputedStyle(el).visibility !== 'hidden' && +getComputedStyle(el).opacity > 0);
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
    if (!text || text.length > 5000 || seen.has(el)) continue;  // длинный абзац макета тоже должен найтись
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
    // строки — группы прямоугольников с близким верхом: span с другим шрифтом в той же строке не новая строка
    const lineTops = rects.map(r => r.top).sort((a, b) => a - b)
      .reduce((acc, t) => (acc.length && t - acc[acc.length - 1] < first.height * 0.6 ? acc : [...acc, t]), []);
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
      color: s.color, text_transform: s.textTransform,
      // итоговая прозрачность: opacity элемента и всех предков — полупрозрачность бывает и так, не только rgba
      opacity: (() => {
        let o = 1, n = el;
        while (n && n !== document.documentElement) { o *= +getComputedStyle(n).opacity; n = n.parentElement; }
        return o;
      })(),
    });
  }
  return out;
}
"""


def with_alpha(hex_color, alpha):
    """Цвет с прозрачностью: «#FFFFFF» или «#FFFFFF 40%». Полупрозрачный текст — другой цвет, не «почти тот же»."""
    try:
        a = float(alpha) if alpha not in (None, "") else 1.0
    except ValueError:
        a = 1.0
    return hex_color if a >= 0.995 else f"{hex_color} {round(a * 100)}%"


def rgb_to_hex(css, opacity=1.0):
    """CSS-цвет → «#RRGGBB» или «#RRGGBB 80%»; opacity — итоговая прозрачность элемента и предков."""
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?", css or "")
    if not m:
        return (css or "").upper()
    r, g, b = (int(x) for x in m.groups()[:3])
    alpha = (float(m.group(4)) if m.group(4) is not None else 1.0) * (opacity if opacity is not None else 1.0)
    return with_alpha(f"#{r:02X}{g:02X}{b:02X}", alpha)


def family(css_family):
    """Первая гарнитура из font-family без кавычек: '"Montserrat", sans-serif' → 'montserrat'."""
    return css_family.split(",")[0].strip().strip("\"'").lower()


ALNUM = re.compile(r"[0-9a-zа-яё]", re.I)
PARTIAL_TAIL = 2  # «158 м» + «²», «30» + «₽»: хвост не длиннее — иначе это уже другой текст
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


TOL_PX = 2  # допуск по положению по умолчанию; переопределяется tolerance в pages.yml и DESIGN_TOLERANCE_PX
NEIGHBOUR_PX = 600  # сосед сверху ищется рядом; дальше — это уже другой блок страницы

POSITION_RULES = {"left", "gap"}


class EmptyDesign(ValueError):
    """Макет без текстов — сравнивать нечего, «ошибок нет» было бы ложью."""
NAME = "design"
RULES = {
    "missing": ("warning", "Текст из макета не найден на сайте"),
    "moved": ("warning", "Блок на сайте в другом месте страницы, чем в макете"),
    "font_size": ("warning", "Размер шрифта не как в макете"),
    "font_weight": ("warning", "Начертание (жирность) не как в макете"),
    "font_family": ("warning", "Гарнитура не как в макете"),
    "color": ("warning", "Цвет текста не как в макете"),
    "letter_spacing": ("warning", "Межбуквенный интервал не как в макете"),
    "line_height": ("warning", "Межстрочный интервал не как в макете"),
    "lines": ("warning", "Текст переносится на другое число строк"),
    "left": ("warning", "Левый край текста не как в макете"),
    "gap": ("warning", "Отступ до блока сверху не как в макете"),
}


def compare(pairs, tol=TOL_PX):
    """Отличия по каждой паре: стиль — напрямую, положение — относительно соседа сверху в той же колонке.
    Отличие: (правило, что сравниваем, макет, сайт). tol — допуск в px для положения (левый край,
    отступы); стиль (размер, начертание, цвет) сравнивается точно."""
    pairs = sorted(pairs, key=lambda p: (p[0]["y"], p[0]["x"]))
    results = []
    for i, (d, s) in enumerate(pairs):
        diffs = []
        if abs(d["font_size"] - s["font_size"]) > 0.5:
            diffs.append(("font_size", "font-size", d["font_size"], s["font_size"]))
        if d["font_weight"] != s["font_weight"]:
            diffs.append(("font_weight", "font-weight", d["font_weight"], s["font_weight"]))
        if d["font_family"] and family(d["font_family"]) != family(s["font_family"]):
            diffs.append(("font_family", "font-family", d["font_family"], s["font_family"].split(",")[0].strip('"\' ')))
        if d["color"] != rgb_to_hex(s["color"], s.get("opacity")):
            diffs.append(("color", "color", d["color"], rgb_to_hex(s["color"], s.get("opacity"))))
        if abs(d["letter_spacing_px"] - s["letter_spacing_px"]) > 0.3:
            diffs.append(("letter_spacing", "letter-spacing", d["letter_spacing_px"], s["letter_spacing_px"]))
        if d["line_height"] and s["line_height_px"] and abs(d["line_height"] - s["line_height_px"]) > 1:
            diffs.append(("line_height", "line-height", d["line_height"], s["line_height_px"]))
        if d["lines"] != s["lines"] and not s.get("partial"):
            diffs.append(("lines", "строк", d["lines"], s["lines"]))
        # положение сравнивается в целых пикселях — тех же, что видны в отчёте («−10, допуск ±10» — норма)
        if abs(round(d["x"]) - round(s["x"])) > tol:
            diffs.append(("left", "левый край", round(d["x"]), round(s["x"])))
        higher = [p for p in reversed(pairs[:i]) if p[0]["y"] < d["y"] - 1]
        # сосед сверху: в той же колонке рядом, иначе — ближайший текст выше где угодно; отступ
        # всё равно относительный, поэтому съехавшая секция не тянет за собой ошибки ниже
        above = next((p for p in higher if abs(p[0]["x"] - d["x"]) < 40 and d["y"] - p[0]["y"] < NEIGHBOUR_PX),
                     None) or (higher[0] if higher else None)
        if above:
            gap_d, gap_s = d["y"] - above[0]["y"], s["y"] - above[1]["y"]
            if abs(round(gap_d) - round(gap_s)) > tol:
                diffs.append(("gap", f"отступ от «{above[0]['text'][:40]}»", round(gap_d), round(gap_s)))
        elif (i == 0 or d["y"] < NEIGHBOUR_PX) and abs(round(d["y"]) - round(s["y"])) > tol:  # верх страницы: ловит сдвиг всей страницы
            diffs.append(("gap", "отступ от верха страницы", round(d["y"]), round(s["y"])))
        results.append({"design": d, "site": s, "diffs": diffs})
    return results


def in_zone(t, zones):
    """Зона — [y1, y2] (вся ширина) или [x1, y1, x2, y2] в координатах макета."""
    for z in zones or ():
        x1, y1, x2, y2 = (0, z[0], 10 ** 6, z[1]) if len(z) == 2 else z
        if x1 <= t["x"] <= x2 and y1 <= t["y"] <= y2:
            return True
    return False


def match_partial(missing, site, taken):
    """Второй проход: текст макета — начало блока сайта («158 м» + «²» в макете, «158 м²» на сайте)."""
    found, rest = [], []
    for d in missing:
        key = normalize(d["text"])
        cands = [s for s in site if not s.get("offscreen") and id(s) not in taken and len(key) >= 2
                 and normalize(s["text"]).startswith(key) and len(normalize(s["text"])) - len(key) <= PARTIAL_TAIL
                 and not ALNUM.search(normalize(s["text"])[len(key):])
                 and ((s["x"] - d["x"]) ** 2 + (s["y"] - d["y"]) ** 2) ** 0.5 <= MAX_SHIFT_PX]
        if cands:
            best = min(cands, key=lambda s: ((s["x"] - d["x"]) ** 2 + (s["y"] - d["y"]) ** 2, -s["depth"]))
            taken.add(id(best))
            found.append((d, {**best, "partial": True}))
        else:
            rest.append(d)
    return found, rest


def check_page(design_data, site, url, zones=(), make=None, tol=TOL_PX):
    """Сравнить одну страницу. Возвращает замечания (Finding) и статистику покрытия."""
    if not design_data["texts"]:
        raise EmptyDesign("в макете нет ни одного текста: скорее всего, SVG выгружен с «Outline text» "
                          "(текст превращён в кривые) — выгрузи фрейм заново с выключенной опцией")
    texts = [t for t in design_data["texts"] if not in_zone(t, zones)]
    pairs, missing, far = match(texts, site)
    taken = {id(s) for _, s in pairs + far}
    partial, missing = match_partial(missing, site, taken)
    short = [d for d in missing if not ALNUM.search(normalize(d["text"]))]  # «²», «₽», «–» — нечего сопоставлять
    missing = [d for d in missing if d not in short]
    results = compare(pairs + partial, tol)
    findings = []
    for r in results:
        d, s = r["design"], r["site"]
        for rule, label, want, got in r["diffs"]:
            delta = f" ({got - want:+g})" if isinstance(want, (int, float)) and isinstance(got, (int, float)) else ""
            findings.append(make(rule, d["text"], url, f"макет: y={d['y']:.0f}, x={d['x']:.0f}",
                                 message=f"{label}: макет {want}, сайт {got}{delta}"
                                         + (f", допуск ±{tol:g}" if rule in POSITION_RULES else "")))
    for d, s in far:
        findings.append(make("moved", d["text"], url, f"макет: y={d['y']:.0f}, x={d['x']:.0f}",
                             message=f"в макете y={d['y']:.0f} x={d['x']:.0f}, на сайте y={s['y']:.0f} x={s['x']:.0f}"))
    for d in missing:
        findings.append(make("missing", d["text"], url, f"макет: y={d['y']:.0f}, x={d['x']:.0f}"))
    stats = {"tolerance": tol, "texts": len(design_data["texts"]), "dynamic": len(design_data["texts"]) - len(texts),
             "matched": len(pairs) + len(partial), "moved": len(far), "missing": len(missing), "short": len(short)}
    return findings, stats
