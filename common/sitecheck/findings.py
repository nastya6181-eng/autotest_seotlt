"""Общая модель замечания и уровни важности."""
from dataclasses import dataclass

# Уровень — приоритет исправления. Тест красный, если у правила есть замечания уровня из fail_on
# (по умолчанию error и warning): полная картина дефектов, даже если сейчас падает всё.
# error   — критично: сайт сломан для посетителя или выпал из поиска;
# warning — дефект: текст, вёрстка, SEO;
# info    — рекомендация, на статус теста не влияет;
# off     — правило выключено для проекта.
SEVERITIES = ("error", "warning", "info", "off")


@dataclass
class Finding:
    check: str
    rule: str
    severity: str
    message: str
    fragment: str
    page: str
    context: str = ""

    @property
    def rule_id(self):
        return f"{self.check}.{self.rule}"


def make(check, rules, overrides):
    """Фабрика замечаний для одной проверки с учётом переопределений проекта."""
    def finding(rule, fragment, page, context="", message=None):
        default, title = rules[rule]
        severity = overrides.get(f"{check}.{rule}", default)
        return Finding(check, rule, severity, message or title, fragment, page, context)
    return finding


def context(text, start, end, pad=40):
    return text[max(0, start - pad):end + pad].replace("\n", " ").strip()
