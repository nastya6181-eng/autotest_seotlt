"""Сверка с макетом: разбор SVG, сопоставление по текстам, зоны, локальность ошибок."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # корень репозитория
from checks.design import design  # noqa: E402
from checks.core.findings import make  # noqa: E402

SVG = """<svg width="1600" height="900" viewBox="0 0 1600 900" fill="none" xmlns="http://www.w3.org/2000/svg">
<text fill="white" font-family="Montserrat" font-size="48" font-weight="600" letter-spacing="0em">
<tspan x="144" y="100">&#x41d;&#x41e;&#x412;&#x41e;&#x421;&#x422;&#x418;</tspan></text>
<text fill="#444C49" font-family="Montserrat" font-size="16" font-weight="500" letter-spacing="0.01em">
<tspan x="144" y="200">&#x43d;&#x430;&#x443;&#x447;&#x43d;&#x43e;-</tspan><tspan x="144" y="224">&#x438;&#x441;&#x441;&#x43b;&#x435;&#x434;&#x43e;&#x432;&#x430;&#x442;&#x435;&#x43b;&#x44c;&#x441;&#x43a;&#x438;&#x445;</tspan></text>
</svg>"""


def d(text, x, y, **kw):
    base = {"text": text, "x": x, "y": y, "lines": 1, "line_height": None, "font_family": "Montserrat",
            "font_size": 16.0, "font_weight": 500, "letter_spacing_px": 0, "color": "#FFFFFF"}
    return {**base, **kw}


def s(text, x, y, **kw):
    base = {"text": text, "x": x, "y": y, "lines": 1, "font_family": "Montserrat, sans-serif", "font_size": 16.0,
            "font_weight": 500, "letter_spacing_px": 0, "line_height_px": None, "color": "rgb(255, 255, 255)",
            "depth": 5, "offscreen": False}
    return {**base, **kw}


class ExtractTest(unittest.TestCase):
    def test_extract(self):
        data = design.extract_svg(SVG)
        self.assertEqual(data["width"], 1600)
        title, body = data["texts"]
        self.assertEqual((title["text"], title["font_size"], title["font_weight"], title["color"]),
                         ("НОВОСТИ", 48.0, 600, "#FFFFFF"))
        self.assertEqual(body["text"], "научно-исследовательских")
        self.assertEqual((body["lines"], body["line_height"], body["letter_spacing_px"]), (2, 24.0, 0.16))


    def test_runs_on_one_baseline_join_without_space(self):
        svg = ('<svg width="800"><text font-size="16"><tspan x="10" y="20">Open</tspan><tspan x="50" y="20">AI </tspan>'
               '<tspan x="80" y="20">рядом</tspan><tspan x="10" y="44">вторая строка</tspan></text></svg>')
        self.assertEqual(design.extract_svg(svg)["texts"][0]["text"], "OpenAI рядом вторая строка")
        svg = '<svg width="800"><text x="100" y="200" font-size="16"><tspan>Hello </tspan><tspan>world</tspan></text></svg>'
        self.assertEqual([(x["text"], x["x"], x["y"]) for x in design.extract_svg(svg)["texts"]],
                         [("Hello world", 100.0, 200.0)])

    def test_translate_applied_and_rotation_skipped(self):
        svg = ('<svg width="800"><g transform="translate(200,300)"><text font-size="16"><tspan x="10" y="20">А</tspan>'
               '</text></g><g transform="rotate(90)"><text font-size="16"><tspan x="1" y="1">Б</tspan></text></g></svg>')
        data = design.extract_svg(svg)
        self.assertEqual([(t["text"], t["x"], t["y"]) for t in data["texts"]], [("А", 210.0, 320.0)])
        self.assertEqual(data["skipped_transformed"], 1)


class MatchTest(unittest.TestCase):
    def test_repeated_texts_go_one_to_one_by_position(self):
        design_t = [d("9 февраля", 168, 1000), d("9 февраля", 610, 1000)]
        site = [s("9 февраля", 612, 1001), s("9 февраля", 170, 1002)]
        pairs, missing, far = design.match(design_t, site)
        self.assertEqual(sorted((p[0]["x"], p[1]["x"]) for p in pairs), [(168, 170), (610, 612)])
        self.assertEqual((missing, far), ([], []))

    def test_offscreen_and_far(self):
        pairs, missing, far = design.match([d("Слайд", 100, 500), d("Кнопка", 100, 900)],
                                           [s("Слайд", -1500, 500, offscreen=True), s("Кнопка", 100, 3000)])
        self.assertEqual([m["text"] for m in missing], ["Слайд"])
        self.assertEqual([p[0]["text"] for p in far], ["Кнопка"])

    def test_case_and_yo_insensitive(self):
        pairs, _, _ = design.match([d("Ещё новости", 0, 0)], [s("ЕЩЕ НОВОСТИ", 0, 0)])
        self.assertEqual(len(pairs), 1)


class CompareTest(unittest.TestCase):
    def test_shifted_block_is_one_error_not_a_cascade(self):
        """Блок «Б» съехал на 20 px вниз, тексты под ним — вместе с ним: ошибка одна, у «Б»."""
        design_t = [d("А", 100, 100), d("Б", 100, 200), d("В", 100, 300), d("Г", 100, 400)]
        site = [s("А", 100, 100), s("Б", 100, 220), s("В", 100, 320), s("Г", 100, 420)]
        results = design.compare(design.match(design_t, site)[0])
        bad = [(r["design"]["text"], [x[0] for x in r["diffs"]]) for r in results if r["diffs"]]
        self.assertEqual(bad, [("Б", ["gap"])])

    def test_style_diffs(self):
        r = design.compare([(d("Т", 10, 10, font_size=24.0, font_weight=600, color="#0BFFC5"),
                             s("Т", 15, 10, font_size=20.0, font_weight=500, color="rgb(0, 254, 194)"))])[0]
        self.assertEqual({x[0] for x in r["diffs"]}, {"font_size", "font_weight", "color", "left"})


class StrictnessTest(unittest.TestCase):
    def test_empty_design_is_an_error_not_a_pass(self):
        with self.assertRaises(design.EmptyDesign):
            design.check_page({"width": 1600, "texts": []}, [s("Любой", 0, 0)], "https://x.ru/", [],
                              make("design", design.RULES, {}))

    def test_text_without_tspan(self):
        data = design.extract_svg('<svg width="800"><text x="10" y="20" font-size="16">Заголовок</text></svg>')
        self.assertEqual([(t["text"], t["x"], t["y"]) for t in data["texts"]], [("Заголовок", 10.0, 20.0)])

    def test_font_family_exact(self):
        r = design.compare([(d("Т", 10, 10), s("Т", 10, 10, font_family='"Montserrat Alternates", sans-serif'))])[0]
        self.assertIn("font_family", [x[0] for x in r["diffs"]])
        r = design.compare([(d("Т", 10, 10), s("Т", 10, 10, font_family='"Montserrat", sans-serif'))])[0]
        self.assertNotIn("font_family", [x[0] for x in r["diffs"]])

    def test_semi_transparent_color_differs(self):
        r = design.compare([(d("Т", 10, 10), s("Т", 10, 10, color="rgba(255, 255, 255, 0.11)"))])[0]
        self.assertEqual([x[2:] for x in r["diffs"] if x[0] == "color"], [("#FFFFFF", "#FFFFFF 11%")])
        r = design.compare([(d("Т", 10, 10, color="#FFFFFF 80%"), s("Т", 10, 10, opacity=0.8))])[0]
        self.assertNotIn("color", [x[0] for x in r["diffs"]])  # opacity у элемента = тот же полупрозрачный цвет
        svg = '<svg width="800"><text fill="white" fill-opacity="0.5" font-size="16"><tspan x="1" y="1">А</tspan></text></svg>'
        self.assertEqual(design.extract_svg(svg)["texts"][0]["color"], "#FFFFFF 50%")


class ToleranceTest(unittest.TestCase):
    def shifted(self, dx, dy, tol):
        pairs = design.match([d("А", 100, 100), d("Б", 100, 200)], [s("А", 100, 100), s("Б", 100 + dx, 200 + dy)])[0]
        return {x[0] for r in design.compare(pairs, tol) for x in r["diffs"]}

    def test_shift_within_tolerance_is_ok(self):
        self.assertEqual(self.shifted(5, 5, 2), {"left", "gap"})
        self.assertEqual(self.shifted(5, 5, 10), set())
        self.assertEqual(self.shifted(12, 12, 10), {"left", "gap"})
        self.assertEqual(self.shifted(10.4, 10.4, 10), set())  # в отчёте это «±10» — значит, в норме

    def test_style_is_exact_regardless_of_tolerance(self):
        r = design.compare([(d("Т", 10, 10, font_size=24.0), s("Т", 10, 10, font_size=23.0))], tol=50)[0]
        self.assertEqual([x[0] for x in r["diffs"]], ["font_size"])

    def test_message_shows_tolerance(self):
        data = {"width": 1600, "texts": [d("А", 100, 100)]}
        findings, st = design.check_page(data, [s("А", 115, 100)], "https://x.ru/", [],
                                         make("design", design.RULES, {}), tol=10)
        self.assertEqual(st["tolerance"], 10)
        self.assertIn("допуск ±10", findings[0].message)

    def test_tolerance_precedence(self):
        from unittest import mock
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "checks", "design"))
        import design_compare
        with mock.patch.dict(os.environ, {"DESIGN_TOLERANCE_PX": ""}):
            self.assertEqual(design_compare.tolerance({}), 2)
            self.assertEqual(design_compare.tolerance({"tolerance": 10}), 10)
        with mock.patch.dict(os.environ, {"DESIGN_TOLERANCE_PX": "4"}):
            self.assertEqual(design_compare.tolerance({"tolerance": 10}), 4)
        for bad in ("abc", "-1"):
            with mock.patch.dict(os.environ, {"DESIGN_TOLERANCE_PX": bad}), self.assertRaises(SystemExit):
                design_compare.tolerance({})


class PageTest(unittest.TestCase):
    def test_dynamic_zones_partial_and_short(self):
        data = {"width": 1600, "texts": [d("Новость дня", 168, 950), d("Календарь", 300, 8450),
                                         d("158 м", 100, 4359), d("²", 150, 4350), d("Заголовок", 144, 822)]}
        site = [s("158 м²", 100, 4359), s("Заголовок", 144, 822)]
        findings, st = design.check_page(data, site, "https://x.ru/", [[880, 1320], [140, 8390, 1600, 8900]],
                                         make("design", design.RULES, {}))
        self.assertEqual((st["dynamic"], st["matched"], st["missing"], st["short"]), (2, 2, 0, 1))
        self.assertEqual(findings, [])

    def test_partial_match_only_for_short_tail(self):
        data = {"width": 1600, "texts": [d("Подписаться", 100, 100)]}
        findings, st = design.check_page(data, [s("Подписаться на рассылку", 100, 100)], "https://x.ru/", [],
                                         make("design", design.RULES, {}))
        self.assertEqual([f.rule for f in findings], ["missing"])

    def test_partial_tail_cannot_change_a_number(self):
        data = {"width": 1600, "texts": [d("100", 100, 100), d("EN", 300, 100)]}
        findings, _ = design.check_page(data, [s("10000", 100, 100)], "https://x.ru/", [],
                                        make("design", design.RULES, {}))
        self.assertEqual(sorted(f.fragment for f in findings if f.rule == "missing"), ["100", "EN"])

    def test_transparent_text_fails_color(self):
        r = design.compare([(d("Т", 10, 10), s("Т", 10, 10, color="rgba(255, 255, 255, 0)"))])[0]
        self.assertIn("color", [x[0] for x in r["diffs"]])

    def test_isolated_section_shift_is_caught(self):
        results = design.compare(design.match([d("А", 100, 100), d("Б", 100, 2000)],
                                              [s("А", 100, 100), s("Б", 100, 2300)])[0])
        self.assertEqual([r["design"]["text"] for r in results if r["diffs"]], ["Б"])

    def test_whole_page_shift_caught_even_if_first_text_is_low(self):
        results = design.compare(design.match([d("А", 100, 800), d("Б", 100, 900)],
                                              [s("А", 100, 1000), s("Б", 100, 1100)])[0])
        self.assertEqual([r["design"]["text"] for r in results if r["diffs"]], ["А"])

    def test_whole_page_shift_is_caught_at_the_top(self):
        results = design.compare(design.match([d("А", 100, 100), d("Б", 100, 200)],
                                              [s("А", 100, 300), s("Б", 100, 400)])[0])
        self.assertEqual([(r["design"]["text"], [x[0] for x in r["diffs"]]) for r in results if r["diffs"]],
                         [("А", ["gap"])])


if __name__ == "__main__":
    unittest.main()
