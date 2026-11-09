"""Общая модель замечания и уровни важности."""
from dataclasses import dataclass

# error   — сайт сломан для посетителя, прогон падает (красный);
# warning — дефект текста или вёрстки, считаем и следим за трендом;
# info    — к сведению, на результат не влияет;
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
