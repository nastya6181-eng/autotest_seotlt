"""Пробелы, дефисы и тире, кавычки, пунктуация — то, чего не видит словарь."""
import re

from .findings import context, make

NAME = "typography"
L = "А-Яа-яЁёA-Za-z"
RU = "А-Яа-яЁё"

# правило: (уровень, описание, регэксп)
PATTERNS = {
    "repeated_word": ("warning", "Слово повторяется подряд",
                      re.compile(rf"\b([{L}]{{2,}}) +\1\b", re.I)),
    "space_before_punct": ("warning", "Пробел перед знаком препинания",
                           re.compile(rf"[{L}0-9]+ +[,.;:!?](?![\d.])")),
    "no_space_after_comma": ("warning", "Нет пробела после запятой",
                             re.compile(rf"[{RU}]+,[{RU}]+")),
    "no_space_after_period": ("warning", "Нет пробела после точки",
                              re.compile(r"[а-яё]{2,}[.!?][А-ЯЁ][а-яё]+")),
    "double_punct": ("warning", "Двойной знак препинания",
                     # «.,» не ловим: после сокращения запятая законна — «и др., », «т. д., », «г., »
                     re.compile(r"(?<!\.)([,;:])\1|[,;:][.!?](?!\.)")),
    "mixed_alphabet": ("warning", "Латинская буква внутри русского слова",
                       re.compile(rf"\b(?=\w*[{RU}])(?=\w*[A-Za-z])[{L}]+\b")),
    "straight_quotes": ("warning", "Прямые кавычки \"…\" в русском тексте вместо «ёлочек»",
                        re.compile(rf"\"[{RU}][^\"\n]{{0,80}}\"")),
    "hyphen_as_dash": ("warning", "Дефис вместо тире между словами",
                       re.compile(rf"[{RU}0-9»)]+ - [«(]?[{RU}]+")),
    "dash_without_spaces": ("warning", "Тире без пробелов между словами",
                            re.compile(rf"[{RU}]{{2,}}—[{RU}]{{2,}}")),
    "hanging_hyphen": ("warning", "Дефис с пробелом с одной стороны",
                       re.compile(rf"[{RU}]+ -[{RU}]+")),
    "space_inside_brackets": ("warning", "Пробел внутри скобок",
                              re.compile(rf"\( +[{L}0-9]|[{L}0-9.] +\)")),
    "three_dots": ("info", "Три точки вместо многоточия «…»",
                   re.compile(r"(?<!\.)\.\.\.(?!\.)")),
    "number_range_hyphen": ("info", "Диапазон чисел через дефис вместо тире: 10–20",
                            re.compile(r"(?<![\d.,:/-])\d{1,4}-\d{1,4}(?![\d.,:/-])")),
}
RULES = {rule: (sev, title) for rule, (sev, title, _) in PATTERNS.items()}


def run(pages, cfg, overrides, env):
    finding = make(NAME, RULES, overrides)
    out = []
    for page in pages:
        for rule, (_, _, rx) in PATTERNS.items():
            for m in rx.finditer(page.text):
                out.append(finding(rule, m.group().replace("\n", " "), page.url,
                                   context(page.text, m.start(), m.end())))
    return out
