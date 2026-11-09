"""Орфография по словарям Hunspell (ru_RU + en_US), без ИИ."""
import os
import re
import sys
from urllib.request import urlretrieve

from spylls.hunspell import Dictionary

from .findings import context, make

NAME = "spelling"
RULES = {
    "unknown_word": ("warning", "Слово не найдено в словаре"),
}
DICT_URLS = {
    "ru_RU": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/ru_RU/ru_RU",
    "en_US": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_US",
}
WORD = re.compile(r"[A-Za-zÀ-ÿА-Яа-яЁё]+(?:[-‐‑][A-Za-zÀ-ÿА-Яа-яЁё]+)*")
CYR = re.compile(r"[А-Яа-яЁё]")
LAT = re.compile(r"[A-Za-z]")
NOT_WORDS = re.compile(r"\S+@\S+|https?://\S+|www\.\S+|\S+\.(?:ru|рф|com|org|net)\b\S*")


def ensure_dicts(dict_dir):
    os.makedirs(dict_dir, exist_ok=True)
    for name, base in DICT_URLS.items():
        for ext in (".dic", ".aff"):
            path = os.path.join(dict_dir, name + ext)
            if not os.path.exists(path):
                print(f"скачиваю словарь {name}{ext}", file=sys.stderr)
                urlretrieve(base + ext, path)


def load_words(*paths):
    """Слова-исключения. Строка со звёздочкой на конце (технопарк*) — все формы с этой основой."""
    words, stems = set(), []
    for path in paths:
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    w = line.strip().lower()
                    if not w or w.startswith("#"):
                        continue
                    if w.endswith("*"):
                        stems.append(w[:-1])
                    else:
                        words.add(w)
    return words, tuple(stems)


class Checker:
    def __init__(self, dict_dir, ignore):
        self.ignore, self.stems = ignore
        ensure_dicts(dict_dir)
        self.ru = Dictionary.from_files(os.path.join(dict_dir, "ru_RU"))
        self.en = Dictionary.from_files(os.path.join(dict_dir, "en_US"))
        self.cache = {}

    def ok(self, word):
        if word in self.cache:
            return self.cache[word]
        w = word.replace("‐", "-").replace("‑", "-")
        low = w.lower()
        if low in self.ignore or (self.stems and low.startswith(self.stems)) or len(w) < 3 or w.isupper():
            res = True
        else:
            d = self.ru if CYR.search(w) else self.en
            variants = {w, w.lower(), w.capitalize(), w.replace("ё", "е").replace("Ё", "Е")}
            res = any(d.lookup(v) for v in variants)
            if not res and "-" in w:
                res = all(self.ok(part) for part in w.split("-") if part)
        self.cache[word] = res
        return res

    def suggest(self, word):
        d = self.ru if CYR.search(word) else self.en
        try:
            return ", ".join(s for _, s in zip(range(3), d.suggest(word)))
        except Exception:
            return ""


def run(pages, cfg, overrides, env):
    finding = make(NAME, RULES, overrides)
    checker = Checker(env["dict_dir"], load_words(env["common_ignore"], cfg.get("ignore_file")))
    out = []
    for page in pages:
        text = NOT_WORDS.sub(lambda m: " " * len(m.group()), page.text)
        for m in WORD.finditer(text):
            w = m.group()
            if CYR.search(w) and LAT.search(w):
                continue  # это typography.mixed_alphabet
            if not checker.ok(w):
                out.append(finding("unknown_word", w, page.url, context(page.text, m.start(), m.end())))
    if cfg.get("suggest", True):
        suggestions = {w: checker.suggest(w) for w in {f.fragment for f in out}}
        for f in out:
            if suggestions[f.fragment]:
                f.message = f"{f.message}; возможно: {suggestions[f.fragment]}"
    return out
