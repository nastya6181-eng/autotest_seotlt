"""Как исправить дефект — для лога, сводки и HTML-отчёта. И где правило живёт в коде."""
import importlib
import inspect

HINTS = {
    "tech.robots_blocks_all": "Убрать «Disallow: /» из robots.txt рабочего сайта, закрывать только служебные разделы. "
                              "Если это тестовая копия — выключить правило для неё (severity: tech.robots_blocks_all: off).",
    "tech.ssl_expiring": "Продлить SSL-сертификат у хостера или настроить автопродление (Let's Encrypt / certbot).",
    "tech.ssl_expiring_soon": "Запланировать продление SSL-сертификата.",
    "tech.ssl_error": "Проверить сертификат: цепочку, домен, срок. Браузеры покажут посетителю предупреждение.",
    "tech.no_https_redirect": "Настроить 301-редирект с http:// на https:// в nginx/.htaccess или панели хостинга.",
    "tech.soft_404": "Несуществующая страница должна отдавать код 404. В Битриксе — константа ERROR_404 и шаблон 404.php.",
    "tech.robots_missing": "Положить robots.txt в корень сайта.",
    "tech.sitemap_missing": "Сгенерировать sitemap.xml (в Битриксе: Маркетинг → Поисковая оптимизация → Карта сайта) "
                            "и указать его в robots.txt строкой Sitemap:.",
    "seo.noindex": "Убрать noindex из meta robots или заголовка X-Robots-Tag, если страница должна быть в поиске.",
    "seo.mixed_content": "Заменить http:// на https:// (или на относительный путь) в адресе ресурса.",
    "seo.missing_title": "Заполнить <title> страницы.",
    "seo.duplicate_title": "Сделать <title> уникальным для каждой страницы: название раздела или товара + сайт.",
    "seo.title_length": "Держать <title> в пределах 10–70 символов: короче — мало для поиска, длиннее — обрежется.",
    "seo.missing_description": "Заполнить meta description: 1–2 предложения о странице, 70–160 символов. "
                               "В Битриксе — свойство страницы или раздела «description».",
    "seo.duplicate_description": "Сделать description уникальным для каждой страницы.",
    "seo.missing_h1": "Добавить на страницу один заголовок H1 с её названием.",
    "seo.multiple_h1": "Оставить на странице один H1, остальные заголовки сделать H2–H3.",
    "seo.img_no_alt": "Добавить картинке атрибут alt с описанием. Для декоративных картинок — пустой alt=\"\".",
    "seo.missing_lang": "Указать язык в теге: <html lang=\"ru\">.",
    "links.page_failed": "Страница не открылась при обходе: проверить её в браузере и в логах сервера.",
    "links.broken_internal": "Исправить или убрать ссылку: адрес на этом сайте отвечает ошибкой.",
    "links.broken_external": "Проверить ссылку в браузере. Если открывается — внешний сайт режет ботов, "
                             "внести адрес в links.ignore с комментарием. Если нет — заменить или убрать ссылку.",
    "links.bad_href": "Исправить href: телефон — tel:+7…, почта — mailto:…, внешний адрес — с https://.",
    "links.placeholder_href": "Поставить реальный адрес или заменить ссылку-заглушку на кнопку (<button>).",
    "links.missing_anchor": "Добавить на целевую страницу элемент с нужным id или поправить якорь в ссылке.",
    "links.redirect": "Поставить в ссылку конечный адрес (часто — добавить «/» в конце).",
    "links.external_same_tab": "Добавить внешней ссылке target=\"_blank\" rel=\"noopener\".",
    "spelling.unknown_word": "Исправить опечатку. Если слово верное (название, термин, фамилия) — "
                             "добавить в projects/<ключ>/ignore.txt или common/dictionaries/ignore.txt.",
    "typography.repeated_word": "Убрать повтор слова.",
    "typography.space_before_punct": "Убрать пробел перед знаком препинания.",
    "typography.no_space_after_comma": "Поставить пробел после запятой.",
    "typography.no_space_after_period": "Поставить пробел после точки.",
    "typography.double_punct": "Оставить один знак препинания.",
    "typography.mixed_alphabet": "Перенабрать слово: в нём латинская буква, похожая на русскую (с, о, р, е, а…).",
    "typography.straight_quotes": "Заменить \"прямые\" кавычки на «ёлочки».",
    "typography.hyphen_as_dash": "Заменить дефис « - » между словами на тире « — ».",
    "typography.dash_without_spaces": "Поставить пробелы вокруг тире: «слово — слово».",
    "typography.hanging_hyphen": "Убрать лишний пробел у дефиса или заменить на тире с пробелами.",
    "typography.space_inside_brackets": "Убрать пробелы сразу после «(» и перед «)».",
    "typography.three_dots": "Заменить три точки на многоточие «…».",
    "typography.number_range_hyphen": "Диапазон чисел писать через короткое тире без пробелов: 10–20.",
}


def hint(rule_id):
    return HINTS.get(rule_id, "")


def source(rule_id):
    """(путь от корня репозитория, строка), где объявлено правило — для отладки самого теста."""
    check, rule = rule_id.split(".", 1)
    try:
        module = importlib.import_module(f"sitecheck.{check}")
        lines, _ = inspect.getsourcelines(module)
        path = inspect.getsourcefile(module)
    except (ImportError, OSError, TypeError):
        return "", 0
    rel = path[path.index("common/"):] if "common/" in path else path
    for n, line in enumerate(lines, 1):
        if f'"{rule}"' in line:
            return rel, n
    return rel, 0
