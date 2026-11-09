"""Темп запросов к своему сайту и пауза после бана."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from sitecheck import throttle  # noqa: E402


class ThrottleTest(unittest.TestCase):
    def setUp(self):
        throttle._next_at[0] = throttle._paused_until[0] = 0.0

    def test_spacing_for_own_site_only(self):
        throttle.configure("https://site.ru/", max_rps=20)
        t0 = time.time()
        for _ in range(5):
            throttle.wait("https://www.site.ru/page")
        self.assertGreaterEqual(time.time() - t0, 0.19)
        t1 = time.time()
        for _ in range(5):
            throttle.wait("https://other.ru/")
        self.assertLess(time.time() - t1, 0.05)

    def test_rate_limit_pauses_everyone(self):
        throttle.configure("https://site.ru/", max_rps=100, cooldown=0.3)
        self.assertTrue(throttle.rate_limited("https://site.ru/x", 503, {}))
        t0 = time.time()
        throttle.wait("https://site.ru/y")
        self.assertGreaterEqual(time.time() - t0, 0.25)

    def test_plain_503_without_limit_is_breakage(self):
        throttle.configure("https://site.ru/")
        self.assertFalse(throttle.rate_limited("https://site.ru/x", 503, {}))
        self.assertTrue(throttle.rate_limited("https://site.ru/x", 429, {"Retry-After": "0"}))
        self.assertFalse(throttle.rate_limited("https://other.ru/x", 429, {}))


if __name__ == "__main__":
    unittest.main()
