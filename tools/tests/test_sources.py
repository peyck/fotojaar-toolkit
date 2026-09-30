"""Tests voor de jaartalbronnen en de weekverdeling.  Uitvoeren:  python -m unittest discover tools/tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402


class PathYears(unittest.TestCase):
    def setUp(self):
        self._from = build.PATH_YEAR_FROM
        build.PATH_YEAR_FROM = ["filename", "folder"]

    def tearDown(self):
        build.PATH_YEAR_FROM = self._from

    def test_filename(self):
        self.assertEqual(build.path_years("Kermis_1968.jpg"), [1968, 1968])

    def test_folder(self):
        self.assertEqual(build.path_years("1952 Processie/p1.jpg"), [1952, 1952])

    def test_range_in_folder(self):
        self.assertEqual(build.path_years("Ruilverkaveling/1950-1955/r1.jpg"), [1950, 1955])

    def test_filename_wins_over_folder(self):
        self.assertEqual(build.path_years("1950 Feest/IMG_1962.jpg"), [1962, 1962])

    def test_no_year_or_longer_number(self):
        self.assertEqual(build.path_years("Zonder/IMG_19680512_0001.jpg"), [])

    def test_folder_only(self):
        build.PATH_YEAR_FROM = ["folder"]
        self.assertEqual(build.path_years("1950 Feest/IMG_1962.jpg"), [1950, 1950])


class CsvYears(unittest.TestCase):
    def test_cells(self):
        self.assertEqual(build.parse_year_cell("1952"), [1952, 1952])
        self.assertEqual(build.parse_year_cell(1952.0), [1952, 1952])      # Excel
        self.assertEqual(build.parse_year_cell("1950-1955"), [1950, 1955])
        self.assertEqual(build.parse_year_cell("1955/1950"), [1950, 1955])
        self.assertEqual(build.parse_year_cell("1910~"), [1908, 1912])
        self.assertEqual(build.parse_year_cell("onbekend"), [])

    def test_out_of_range(self):
        self.assertEqual(build.csv_years({"year": "3000"}), [])
        self.assertEqual(build.csv_years({}), [])


class CsvFile(unittest.TestCase):
    def test_read_and_lookup(self):
        old = (build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "lijst.csv"
            f.write_text("Pad;Jaar;Verhaal\nA/b.jpg;1950;Een verhaal\nc.jpg;1960;\n", encoding="utf-8-sig")
            build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES = f, None, ["csv"]
            try:
                self.assertEqual(build.csv_row("A/B.jpg")["story"], "Een verhaal")      # hoofdletterongevoelig
                self.assertEqual(build.csv_row("Map/C.jpg")["year"], "1960")           # enkel bestandsnaam
                self.assertEqual(build.csv_row("onbekend.jpg"), {})
            finally:
                build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES = old

    def test_comma_delimiter(self):
        old = (build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "lijst.csv"
            f.write_text("pad,jaar\nx.jpg,1901\n", encoding="utf-8")
            build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES = f, None, ["csv"]
            try:
                self.assertEqual(build.csv_row("x.jpg")["year"], "1901")
            finally:
                build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES = old


class Priority(unittest.TestCase):
    def test_order_and_override(self):
        old = (build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "l.csv"
            f.write_text("pad;jaar\n1950 Feest/a.jpg;1961\n", encoding="utf-8")
            build.CSV_FILE, build._csv_cache = f, None
            try:
                build.YEAR_SOURCES = ["csv", "path"]
                self.assertEqual(build.resolve_years({}, "1950 Feest/a.jpg", {}, {})[:2], ([1961, 1961], "csv"))
                build.YEAR_SOURCES = ["path", "csv"]
                self.assertEqual(build.resolve_years({}, "1950 Feest/a.jpg", {}, {})[0], [1950, 1950])
                self.assertEqual(build.resolve_years({}, "1950 Feest/a.jpg", {}, {"1950 Feest/a.jpg": 1900})[0],
                                 [1900, 1900])
            finally:
                build.CSV_FILE, build._csv_cache, build.YEAR_SOURCES = old

    def test_metadata_keyword(self):
        old = build.YEAR_SOURCES
        build.YEAR_SOURCES = ["metadata"]
        try:
            ys, src, prob = build.resolve_years({"XMP-dc:Subject": ["1905", "Brussel"]}, "x.jpg", {}, {})
            self.assertEqual((ys, src, prob), ([1905, 1905], "keyword", ""))
        finally:
            build.YEAR_SOURCES = old


class Render(unittest.TestCase):
    def test_optional_blocks_and_values(self):
        values, flags = build.site_values()
        values = dict(values, title="Mijn <Jaar>", site_url="", goatcounter="")
        tpl = 'a<!--?LEARN-->X<!--/LEARN-->b<!--?ANALYTICS-->Y<!--/ANALYTICS-->\n<link href="{{site_url}}">\n{{title}}'
        out = build.render_template(tpl, values, {"LEARN": False, "ANALYTICS": True})
        self.assertEqual(out, "abY\nMijn <Jaar>")      # blok weg, regel met leeg adres weg

    def test_template_has_no_leftover_placeholders(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            build.render_site(Path(d))
            for f in ("index.html", "manifest.webmanifest"):
                self.assertNotIn("{{", (Path(d) / f).read_text(encoding="utf-8"))
            self.assertNotIn("<!--?", (Path(d) / "index.html").read_text(encoding="utf-8"))


class Languages(unittest.TestCase):
    def load(self, code):
        import json
        f = build.TEMPLATE / "lang" / f"{code}.json"
        return {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_")}

    def test_same_keys(self):
        codes = sorted(f.stem for f in (build.TEMPLATE / "lang").glob("*.json"))
        self.assertIn("nl", codes)
        self.assertIn("en", codes)
        base = {k for k in self.load("nl") if not k.endswith("_one")}
        for code in codes:
            keys = {k for k in self.load(code) if not k.endswith("_one")}
            self.assertEqual(base - keys, set(), f"{code}: ontbrekende sleutels")
            self.assertEqual(keys - base, set(), f"{code}: onbekende sleutels")

    def test_same_placeholders(self):
        import re
        nl, en = self.load("nl"), self.load("en")
        for k, v in nl.items():
            if isinstance(v, str):
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", v)), sorted(re.findall(r"\{(\w+)\}", en[k])), k)

    def test_plural_key(self):
        old = build._lang_cache, build.LANG
        try:
            build.LANG, build._lang_cache = "en", None
            self.assertEqual(build.t("too_early", n=1), "1 year too early")
            self.assertEqual(build.t("too_early", n=2), "2 years too early")
            self.assertEqual(build.number_word(5), "five")
            self.assertEqual(build.number_word(1, True), "One")
        finally:
            build._lang_cache, build.LANG = old


class MixWeeks(unittest.TestCase):
    def test_every_photo_once_and_stable(self):
        cands = {f"f{i}.jpg": {"years": [1900 + i, 1900 + i]} for i in range(23)}
        a = build.mix_weeks(list(cands), cands)
        self.assertEqual(sorted(a), sorted(cands))
        self.assertEqual(a, build.mix_weeks(list(cands), cands))            # deterministisch

    def test_each_week_spreads_years(self):
        cands = {f"f{i}.jpg": {"years": [1900 + i, 1900 + i]} for i in range(50)}
        out = build.mix_weeks(list(cands), cands)
        for w in range(10):
            ys = [cands[p]["years"][0] for p in out[w * 5:(w + 1) * 5]]
            self.assertGreater(max(ys) - min(ys), 25)


if __name__ == "__main__":
    unittest.main()
