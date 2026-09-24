import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_catalog import ALIAS_SCHEMA, STAR_SCHEMA, build_fixture, fixture_rows


BINARY = str(Path(sys.argv.pop(1)).resolve())


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="star-search-'quoted-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        build_fixture(self.data)
        self.home = self.root / "home"
        self.home.mkdir()
        self.environment = {**os.environ, "STAR_SEARCH_DATA_DIR": str(self.data),
                            "HOME": str(self.home), "XDG_CACHE_HOME": str(self.home / "cache"),
                            "XDG_CONFIG_HOME": str(self.home / "config")}

    def cli(self, *arguments, status=0, input=None, json_output=True):
        command = [BINARY, *(["--json"] if json_output else []), *arguments]
        result = subprocess.run(command, env=self.environment, input=input,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout) if json_output else result

    def test_info_ids_nulls_and_zero(self):
        star = self.cli("info", "  nEaR  ")
        self.assertEqual(star["id"], "fixture:near")
        self.assertEqual(star["gaia_dr3_source_id"], "9007199254740993")
        self.assertEqual(star["phot_g_mean_mag"], 0)
        self.assertIsNone(star["spectral_type"])
        self.assertEqual(star["distance_pc"], 1)
        self.assertNotIn("distance_ly", star)

    def test_unknown_measurements(self):
        star = self.cli("info", "fixture:unknown")
        self.assertIsNone(star["name"])
        self.assertIsNone(star["distance_pc"])
        self.assertIsNone(star["gaia_dr3_source_id"])
        self.assertEqual(star["parallax_mas"], -0.5)
        text = self.cli("info", "fixture:unknown", json_output=False).stdout
        self.assertIn("unknown", text)
        self.assertNotIn("nan", text.lower())

    def test_id_precedes_alias(self):
        self.assertEqual(self.cli("info", "fixture:near")["id"], "fixture:near")

    def test_ambiguity(self):
        result = self.cli("info", "Fixture Pair", status=4)
        self.assertEqual(result["error"], "ambiguous")
        self.assertEqual(result["match_count"], 2)
        self.assertFalse(result["truncated"])
        self.assertEqual([candidate["id"] for candidate in result["candidates"]],
                         ["fixture:pair-a", "fixture:pair-b"])

    def test_candidate_limit(self):
        template = fixture_rows()[0][0]
        stars = [{**template, "id": f"many:{index:02}", "name": "Repeated"}
                 for index in range(12)]
        pq.write_table(pa.Table.from_pylist(stars, schema=STAR_SCHEMA), self.data / "stars.parquet")
        pq.write_table(pa.Table.from_pylist([], schema=ALIAS_SCHEMA), self.data / "aliases.parquet")
        result = self.cli("info", "Repeated", status=4)
        self.assertEqual(result["match_count"], 12)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["candidates"]), 10)
        self.assertEqual(result["candidates"][0]["id"], "many:00")

    def test_exact_name_precedes_substring(self):
        self.assertEqual(self.cli("info", "Fixture Pair A")["id"], "fixture:pair-a")

    def test_literal_search_and_json_escaping(self):
        expected = fixture_rows()[0][-1]["name"]
        for term in ["%", "_", "O'Brien", expected]:
            with self.subTest(term=term):
                self.assertEqual(self.cli("info", term)["name"], expected)
        self.assertEqual(self.cli("info", "' OR true --", status=3)["error"], "not_found")

    def test_nearest_order_and_exclusion(self):
        stars = self.cli("nearest", "10")
        self.assertEqual([star["id"] for star in stars],
                         ["fixture:near", "fixture:pair-a", "fixture:pair-b", "fixture:special"])
        self.assertEqual(len(self.cli("nearest", "2")), 2)

    def test_empty_catalog(self):
        pq.write_table(pa.Table.from_pylist([], schema=STAR_SCHEMA), self.data / "stars.parquet")
        pq.write_table(pa.Table.from_pylist([], schema=ALIAS_SCHEMA), self.data / "aliases.parquet")
        self.assertEqual(self.cli("nearest", "1"), [])
        self.assertEqual(self.cli("info", "anything", status=3)["error"], "not_found")

    def test_coords(self):
        star = self.cli("coords", "near")
        self.assertEqual(set(star), {"id", "name", "ra_deg", "dec_deg", "ref_epoch_jyear",
                                     "galactic_longitude_deg", "galactic_latitude_deg"})
        self.assertEqual(star["ref_epoch_jyear"], 2016)

    def test_text_conversions(self):
        output = self.cli("info", "near", json_output=False).stdout
        fields = dict(line.split(maxsplit=1) for line in output.splitlines())
        self.assertAlmostEqual(float(fields["distance_ly"]), 3.2615637771674336, places=6)
        self.assertAlmostEqual(float(fields["distance_ld"]), 3.2615637771674336 * 365.25, places=3)

    def test_interactive(self):
        self.assertEqual(self.cli(input="near\n")["id"], "fixture:near")
        self.assertEqual(self.cli(input="", status=2)["error"], "usage")

    def test_invalid_arguments(self):
        for arguments in [("nearest", "0"), ("nearest", "-1"), ("nearest", "10001"),
                          ("nearest", "1.5"), ("nearest", "1;DROP TABLE stars"),
                          ("nearest", "999999999999999999999999999999"),
                          ("nearest", "+1"), ("info", " "), ("info",),
                          ("coords", "near", "extra"), ("--raw",), ("--online",)]:
            with self.subTest(arguments=arguments):
                self.assertEqual(self.cli(*arguments, status=2)["error"], "usage")

    def test_manifest_and_no_extension_cache(self):
        metadata = self.cli("--catalog-info")
        self.assertEqual(metadata["schema_version"], 1)
        self.assertTrue(metadata["is_fixture"])
        self.cli("info", "near")
        self.assertEqual(list(self.home.rglob("*.duckdb_extension")), [])

    def test_manifest_version_rejected(self):
        path = self.data / "catalog.json"
        metadata = json.loads(path.read_text())
        metadata["schema_version"] = 99
        path.write_text(json.dumps(metadata))
        self.assertEqual(self.cli("info", "near", status=1)["error"], "catalog_error")

    def test_wrong_column_type_rejected(self):
        path = self.data / "stars.parquet"
        table = pq.read_table(path)
        column = table.schema.get_field_index("distance_pc")
        table = table.set_column(column, "distance_pc", table["distance_pc"].cast(pa.string()))
        pq.write_table(table, path)
        self.assertEqual(self.cli("nearest", "1", status=1)["error"], "catalog_error")

    def test_missing_catalog_and_independent_help(self):
        self.environment["STAR_SEARCH_DATA_DIR"] = str(self.root / "absent")
        self.assertEqual(self.cli("info", "near", status=1)["error"], "catalog_error")
        self.assertEqual(self.cli("--version")["version"], "0.1.0")
        self.assertIn("Usage:", self.cli("--help", json_output=False).stdout)


if __name__ == "__main__":
    unittest.main()