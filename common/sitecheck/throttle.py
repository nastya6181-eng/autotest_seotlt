"""Бережная нагрузка на проверяемый сайт.

max_rps  — не чаще стольких запросов в секунду к домену сайта (обход и проверка ссылок
           вместе, сколько бы ни было потоков). Внешние сайты не ограничиваются.
cooldown — сколько ждать, если сайт ответил «слишком много запросов» (429 или 503 без
           Retry-After). Битрикс с «Контролем активности» банит IP на ~5 минут.
"""
import threading
import time
from urllib.parse import urlparse

SETTINGS = {"host": None, "max_rps": None, "cooldown": 60}
_lock = threading.Lock()
_next_at = [0.0]
_paused_until = [0.0]


def configure(start_url, max_rps=None, cooldown=60):
    SETTINGS.update(host=urlparse(start_url).netloc.lower().removeprefix("www."),
                    max_rps=float(max_rps) if max_rps else None, cooldown=float(cooldown or 60))


def own(url):
    return urlparse(url).netloc.lower().removeprefix("www.") == SETTINGS["host"]


def wait(url):
    """Перед запросом к своему сайту: дождаться очереди и конца паузы после бана."""
    if not own(url):
        return
    with _lock:
        now = time.time()
        start = max(now, _next_at[0], _paused_until[0])
        if SETTINGS["max_rps"]:
            _next_at[0] = start + 1 / SETTINGS["max_rps"]
    if start > now:
        time.sleep(start - now)


def rate_limited(url, status, headers):
    """Сайт ограничил частоту — поставить все запросы к нему на паузу. True, если это оно."""
    if not own(url) or status not in (429, 503):
        return False
    retry_after = (headers or {}).get("Retry-After")
    if status == 503 and retry_after is None and SETTINGS["max_rps"] is None:
        return False  # обычный 503 у сайта без настроенного лимита — это поломка, а не бан
    try:
        pause = float(retry_after)
    except (TypeError, ValueError):
        pause = SETTINGS["cooldown"]
    with _lock:
        _paused_until[0] = max(_paused_until[0], time.time() + pause)
    print(f"  ⏸ сайт ограничил частоту ({status}), пауза {pause:.0f} с", flush=True)
    return True
