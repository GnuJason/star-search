"""Tests for the Gaia DR3 subset pipeline (``tools/ingest_gaia.py normalize``).

Small synthetic fixtures exercise the drop-in file readers (CSV, ECSV and
VOTable), the distance policy, the derived XYZ/galactic coordinates and the
duplicate handling. No network access is required.
"""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyarrow.parquet as pq  # noqa: E402

from tools import ingest_gaia  # noqa: E402

try:  # astropy is optional for the VOTable/FITS readers
    from astropy.table import Table as AstropyTable
except ImportError:  # pragma: no cover - exercised only without astropy
    AstropyTable = None


CSV_HEADER = ",".join(ingest_gaia.FETCH_COLUMNS)

# Proxima-like row, Barnard-like row, a row with a poor parallax that must fall
# back to GSP-Phot, and a row with no usable distance at all.
CSV_ROWS = [
    "5853498713190525696,Gaia DR3 5853498713190525696,2016.0,217.39232,-62.67607,0.02,0.03,"
    "768.0665,0.0499,15392.0,-3781.741,0.031,769.465,0.051,-21.94,0.22,1.01,8.98,11.36,7.58,3.78,"
    "NOT_AVAILABLE,0,2961.0,4.99,-0.8,1.3,313.9,-1.9",
    "4472832130942575872,Gaia DR3 4472832130942575872,2016.0,269.44851,4.73942,0.02,0.02,"
    "546.9759,0.0402,13600.0,-801.551,0.032,10362.394,0.036,-110.11,0.15,1.09,8.19,9.75,7.05,2.70,"
    "NOT_AVAILABLE,0,3170.0,5.0,-0.5,1.83,31.0,14.0",
    "100,Gaia DR3 100,2016.0,10.0,20.0,1.0,1.0,45.0,20.0,2.25,,,,,,,1.2,15.0,,,,"
    "NOT_AVAILABLE,0,,,,22.5,,",
    "200,Gaia DR3 200,2016.0,15.0,-30.0,1.0,1.0,41.0,30.0,1.37,,,,,,,1.5,17.0,,,,"
    "NOT_AVAILABLE,0,,,,,,",
]


def write_csv(directory, name="gaia_chunk.csv", rows=None):
    path = Path(directory) / name
    body = "\n".join([CSV_HEADER] + (CSV_ROWS if rows is None else rows)) + "\n"
    path.write_text(body, encoding="utf-8")
    return path


class NormalizeGaiaTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv_path = write_csv(self.tmp.name)

    def test_distance_policy_and_geometry(self):
        table = ingest_gaia.read_gaia_file(self.csv_path)
        records, counts = ingest_gaia.normalize_gaia_table(table, self.csv_path.name)
        self.assertEqual(counts["input"], 4)
        self.assertEqual(counts["inverse_parallax"], 2)
        self.assertEqual(counts["gspphot"], 1)
        self.assertEqual(counts["none"], 1)
        by_id = {row["gaia_dr3_source_id"]: row for row in records}

        proxima = by_id[5853498713190525696]
        self.assertEqual(proxima["id"], "gaia-dr3:5853498713190525696")
        self.assertEqual(proxima["distance_mode"], "inverse_parallax")
        self.assertAlmostEqual(proxima["distance_pc"], 1000.0 / 768.0665, places=6)
        self.assertAlmostEqual(proxima["distance_ly"],
                               proxima["distance_pc"] * ingest_gaia.LIGHT_YEARS_PER_PARSEC)
        radius = math.sqrt(proxima["x_pc"] ** 2 + proxima["y_pc"] ** 2 + proxima["z_pc"] ** 2)
        self.assertAlmostEqual(radius, proxima["distance_pc"], places=9)
        self.assertAlmostEqual(proxima["z_pc"],
                               proxima["distance_pc"] * math.sin(math.radians(-62.67607)))
        # Gaia-provided l/b are used verbatim when present.
        self.assertAlmostEqual(proxima["galactic_longitude_deg"], 313.9)
        self.assertEqual(proxima["source_catalog"], "Gaia DR3")

        fallback = by_id[100]
        self.assertEqual(fallback["distance_mode"], "gspphot")
        self.assertAlmostEqual(fallback["distance_pc"], 22.5)
        self.assertIsNotNone(fallback["x_pc"])
        # Missing l/b are derived from RA/Dec (astropy gives 119.2694, -42.7904).
        self.assertAlmostEqual(fallback["galactic_longitude_deg"], 119.2694, delta=0.001)
        self.assertAlmostEqual(fallback["galactic_latitude_deg"], -42.7904, delta=0.001)

        empty = by_id[200]
        self.assertEqual(empty["distance_mode"], "none")
        self.assertIsNone(empty["distance_pc"])
        self.assertIsNone(empty["x_pc"])

    def test_invalid_rows_are_dropped_and_counted(self):
        rows = CSV_ROWS + [
            ",Gaia DR3 nothing,2016.0,1.0,1.0,,,50.0,,,,,,,,,,,,,,,,,,,,,",  # no source_id
            "300,Gaia DR3 300,2016.0,400.0,1.0,,,50.0,,,,,,,,,,,,,,,,,,,,,",  # bad RA
            "400,Gaia DR3 400,2016.0,1.0,1.0,,,,,,,,,,,,,,,,,,,,,,,,",  # no parallax
        ]
        path = write_csv(self.tmp.name, "with_bad_rows.csv", rows)
        table = ingest_gaia.read_gaia_file(path)
        records, counts = ingest_gaia.normalize_gaia_table(table, path.name)
        self.assertEqual(counts["dropped_invalid"], 3)
        self.assertEqual(len(records), 4)

    def test_parallax_cut_and_missing_required_column(self):
        table = ingest_gaia.read_gaia_file(self.csv_path)
        records, counts = ingest_gaia.normalize_gaia_table(
            table, "x.csv", min_parallax_mas=100.0)
        self.assertEqual(counts["dropped_parallax_cut"], 2)
        self.assertEqual({row["gaia_dr3_source_id"] for row in records},
                         {5853498713190525696, 4472832130942575872})
        with self.assertRaises(ValueError):
            ingest_gaia.normalize_gaia_table(table.drop(["parallax"]), "x.csv")


class BuildGaiaSubsetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw_dir = Path(self.tmp.name) / "raw"
        self.raw_dir.mkdir()

    def test_raw_dir_discovery_dedupes_and_skips_recons_files(self):
        write_csv(self.raw_dir, "gaia_a.csv")
        # A second file repeating Barnard with a *worse* parallax error plus one new star.
        write_csv(self.raw_dir, "gaia_b.csv", [
            "4472832130942575872,Gaia DR3 4472832130942575872,2016.0,269.44851,4.73942,0.02,0.02,"
            "546.9,0.5,1093.0,,,,,,,1.09,8.19,,,,NOT_AVAILABLE,0,,,,,,",
            "500,Gaia DR3 500,2016.0,100.0,10.0,0.1,0.1,60.0,0.1,600.0,,,,,,,1.0,12.0,,,,"
            "NOT_AVAILABLE,0,,,,,,",
        ])
        (self.raw_dir / "recons_top100.htm").write_text("<pre>not gaia</pre>")
        (self.raw_dir / "recons_nearest.csv").write_text("id,ra\n1,2\n")
        output = Path(self.tmp.name) / "gaia_dr3_subset.parquet"

        summary = ingest_gaia.build_gaia_subset([], output, raw_dir=self.raw_dir)
        self.assertEqual(summary["duplicates_removed"], 1)
        self.assertEqual(summary["rows_written"], 5)
        self.assertEqual(sorted(Path(p).name for p in summary["files"]),
                         ["gaia_a.csv", "gaia_b.csv"])

        table = pq.read_table(output)
        self.assertEqual(table.schema.names, ingest_gaia.GAIA_SUBSET_SCHEMA.names)
        rows = {row["gaia_dr3_source_id"]: row for row in table.to_pylist()}
        # The better-measured duplicate (smaller parallax error) wins.
        self.assertAlmostEqual(rows[4472832130942575872]["parallax_error_mas"], 0.0402)
        self.assertEqual(rows[4472832130942575872]["source_file"], "gaia_a.csv")
        self.assertIn(b"distance_policy", table.schema.metadata)

    def test_no_inputs_is_an_error(self):
        with self.assertRaises(ValueError):
            ingest_gaia.build_gaia_subset([], Path(self.tmp.name) / "out.parquet",
                                          raw_dir=self.raw_dir)

    @unittest.skipIf(AstropyTable is None, "astropy not installed")
    def test_votable_and_ecsv_drop_in_files(self):
        csv_path = write_csv(self.raw_dir, "seed.csv")
        seed = AstropyTable.read(str(csv_path), format="ascii.csv")
        vot_path = self.raw_dir / "gaia_archive_export.vot"
        ecsv_path = self.raw_dir / "gaia_archive_export.ecsv"
        seed.write(str(vot_path), format="votable", overwrite=True)
        seed.write(str(ecsv_path), format="ascii.ecsv", overwrite=True)
        os.remove(csv_path)

        for path in (vot_path, ecsv_path):
            table = ingest_gaia.read_gaia_file(path)
            records, counts = ingest_gaia.normalize_gaia_table(table, path.name)
            self.assertEqual(counts["input"], 4, path.name)
            self.assertEqual(len(records), 4, path.name)
            ids = {row["gaia_dr3_source_id"] for row in records}
            self.assertIn(5853498713190525696, ids, path.name)
            proxima = next(r for r in records if r["gaia_dr3_source_id"] == 5853498713190525696)
            self.assertAlmostEqual(proxima["parallax_mas"], 768.0665, places=4)
            self.assertEqual(proxima["designation"], "Gaia DR3 5853498713190525696")

        output = Path(self.tmp.name) / "subset.parquet"
        summary = ingest_gaia.build_gaia_subset([], output, raw_dir=self.raw_dir)
        self.assertEqual(summary["rows_written"], 4)  # same 4 stars via two formats
        self.assertEqual(summary["duplicates_removed"], 4)


class DefaultAdqlTests(unittest.TestCase):
    def test_default_query_targets_gaia_dr3_with_parallax_cut(self):
        query = ingest_gaia.default_adql(40)
        self.assertIn("gaiadr3.gaia_source", query)
        self.assertIn("parallax > 40", query)
        for column in ("source_id", "parallax", "distance_gspphot", "ruwe"):
            self.assertIn(column, query)


if __name__ == "__main__":
    unittest.main()
