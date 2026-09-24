import copy
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow.parquet as pq

from tools.build_catalog import STAR_SCHEMA, build_fixture, fixture_rows, validate_catalog


class CatalogTests(unittest.TestCase):
    def test_parquet_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build_fixture(output)
            stars = pq.read_table(output / "stars.parquet")
            self.assertEqual(stars.schema, STAR_SCHEMA)
            self.assertEqual(stars.num_rows, 5)
            self.assertEqual(stars["gaia_dr3_source_id"][0].as_py(), 9007199254740993)
            self.assertIsNone(stars["distance_pc"][3].as_py())
            self.assertEqual(stars["phot_g_mean_mag"][0].as_py(), 0.0)
            metadata = json.loads((output / "catalog.json").read_text())
            self.assertTrue(metadata["is_fixture"])
            self.assertEqual(metadata["schema_version"], 1)

    def test_invalid_measurements(self):
        stars, aliases = fixture_rows()
        for column, value in [("distance_pc", -1), ("distance_pc", float("nan")),
                              ("distance_method", None), ("ra_deg", 360),
                              ("dec_deg", 91), ("parallax_error_mas", -1),
                              ("gaia_dr3_source_id", 0), ("id", "")]:
            with self.subTest(column=column, value=value):
                invalid = copy.deepcopy(stars)
                invalid[0][column] = value
                with self.assertRaises(ValueError):
                    validate_catalog(invalid, aliases)

    def test_duplicate_and_dangling_ids(self):
        stars, aliases = fixture_rows()
        with self.assertRaises(ValueError):
            validate_catalog(stars + [stars[0]], aliases)
        with self.assertRaises(ValueError):
            validate_catalog(stars, aliases + [aliases[0]])
        with self.assertRaises(ValueError):
            validate_catalog(stars, [{"alias": "Missing", "star_id": "absent"}])

    def test_ambiguous_alias_is_valid(self):
        validate_catalog(*fixture_rows())


if __name__ == "__main__":
    unittest.main()