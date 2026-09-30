import copy
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow.parquet as pq

import pyarrow as pa

from tools.build_catalog import (ALIAS_SCHEMA, STAR_SCHEMA, aliases_from_merged, build_fixture,
                                 build_from_merged, fixture_rows, star_from_merged,
                                 validate_catalog)
from tools.build_merged_catalog import MERGED_SCHEMA


def merged_row(**overrides):
    row = {field.name: None for field in MERGED_SCHEMA}
    row.update({
        "id": "gaia-dr3:5853498713190525696",
        "primary_name": "Proxima Centauri",
        "common_name": "Proxima Centauri",
        "recons_name": "GJ 551",
        "recons_id": "recons:gj-551",
        "recons_system_rank": 1,
        "recons_system_name": "GJ 551",
        "lhs_id": "49",
        "gaia_source_id": 5853498713190525696,
        "gaia_designation": "Gaia DR3 5853498713190525696",
        "source_of_name": "recons_common_name",
        "match_status": "matched",
        "ra_deg": 217.39232147200883,
        "dec_deg": -62.67607511676666,
        "ref_epoch_jyear": 2016.0,
        "source_of_position": "gaia",
        "parallax_mas": 768.0665391873573,
        "parallax_error_mas": 0.0499,
        "source_of_parallax": "gaia",
        "distance_pc": 1.3019698,
        "distance_ly": 4.2464,
        "distance_mode": "inverse_parallax",
        "x_pc": -0.472,
        "y_pc": -0.361,
        "z_pc": -1.157,
        "galactic_longitude_deg": 313.94,
        "galactic_latitude_deg": -1.93,
        "phot_g_mean_mag": 8.98,
        "spectral_type": "M5.5 V",
        "source_catalogs": "RECONS+Gaia DR3",
    })
    row.update(overrides)
    return row


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

    def test_star_from_merged_projection(self):
        star = star_from_merged(merged_row())
        self.assertEqual(set(star), {field.name for field in STAR_SCHEMA})
        self.assertEqual(star["gaia_dr3_source_id"], 5853498713190525696)
        self.assertEqual(star["name"], "Proxima Centauri")
        self.assertEqual(star["source_catalog"], "RECONS+Gaia DR3")
        self.assertEqual(star["distance_method"], "inverse_parallax:gaia")
        self.assertEqual(star["spectral_type"], "M5.5 V")
        self.assertIsNone(star["phot_bp_mean_mag"])
        recons_only = star_from_merged(merged_row(
            id="recons:gj-559:a", gaia_source_id=None, gaia_designation=None,
            match_status="recons_only", source_of_parallax="recons",
            source_catalogs="RECONS", phot_g_mean_mag=float("nan")))
        self.assertIsNone(recons_only["gaia_dr3_source_id"])
        self.assertIsNone(recons_only["phot_g_mean_mag"])
        self.assertEqual(recons_only["distance_method"], "inverse_parallax:recons")

    def test_aliases_from_merged(self):
        aliases = aliases_from_merged(merged_row())
        self.assertEqual([alias["alias"] for alias in aliases],
                         ["GJ 551", "LHS 49", "recons:gj-551", "Gaia DR3 5853498713190525696",
                          "5853498713190525696"])
        self.assertTrue(all(alias["star_id"] == "gaia-dr3:5853498713190525696"
                            for alias in aliases))
        # The primary name and the star id never become aliases; duplicates collapse.
        component = aliases_from_merged(merged_row(
            primary_name="GJ 65 A", common_name="BL Ceti", recons_name="GJ 65 A",
            recons_system_name="GJ 65", lhs_id="LHS 9", recons_id="recons:gj-65:a"))
        self.assertEqual([alias["alias"] for alias in component],
                         ["BL Ceti", "GJ 65", "LHS 9", "recons:gj-65:a",
                          "Gaia DR3 5853498713190525696", "5853498713190525696"])
        gaia_only = aliases_from_merged(merged_row(
            id="gaia-dr3:1", primary_name="Gaia DR3 1", common_name=None, recons_name=None,
            recons_system_name=None, lhs_id=None, recons_id=None,
            gaia_source_id=1, gaia_designation="Gaia DR3 1", match_status="gaia_only"))
        self.assertEqual([alias["alias"] for alias in gaia_only], ["1"])

    def test_build_from_merged_round_trip(self):
        rows = [
            merged_row(),
            merged_row(id="recons:gj-559:a", primary_name="alpha Centauri A",
                       common_name="alpha Centauri A", recons_name="GJ 559 A",
                       recons_id="recons:gj-559:a", recons_system_name="GJ 559", lhs_id="50",
                       gaia_source_id=None, gaia_designation=None, match_status="recons_only",
                       source_of_parallax="recons", parallax_mas=747.23, distance_pc=1.3383,
                       source_catalogs="RECONS"),
            merged_row(id="gaia-dr3:1", primary_name="Gaia DR3 1", common_name=None,
                       recons_name=None, recons_id=None, recons_system_name=None, lhs_id=None,
                       gaia_source_id=1, gaia_designation="Gaia DR3 1", match_status="gaia_only",
                       spectral_type=None, source_catalogs="Gaia DR3", distance_pc=20.0,
                       parallax_mas=50.0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            merged = root / "merged_catalog.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=MERGED_SCHEMA), merged)
            recons = root / "recons_nearest.parquet"
            recons.write_bytes(b"placeholder")
            output = root / "catalog"
            summary = build_from_merged(merged, output, recons)
            self.assertEqual(summary["stars"], 3)
            self.assertTrue(summary["recons_copied"])
            stars = pq.read_table(output / "stars.parquet")
            self.assertEqual(stars.schema, STAR_SCHEMA)
            self.assertEqual(stars["id"].to_pylist(),
                             ["gaia-dr3:5853498713190525696", "recons:gj-559:a", "gaia-dr3:1"])
            aliases = pq.read_table(output / "aliases.parquet")
            self.assertEqual(aliases.schema, ALIAS_SCHEMA)
            self.assertIn("GJ 559 A", aliases["alias"].to_pylist())
            self.assertEqual((output / "recons_nearest.parquet").read_bytes(), b"placeholder")
            metadata = json.loads((output / "catalog.json").read_text())
            self.assertFalse(metadata["is_fixture"])
            self.assertEqual(metadata["schema_version"], 1)
            self.assertEqual(metadata["star_count"], 3)
            self.assertEqual(metadata["match_status_counts"],
                             {"matched": 1, "recons_only": 1, "gaia_only": 1})
            self.assertIn("Gaia", metadata["attribution"])
            self.assertIn("RECONS", metadata["attribution"])


if __name__ == "__main__":
    unittest.main()