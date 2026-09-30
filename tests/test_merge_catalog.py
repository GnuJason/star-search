"""Tests for the RECONS x Gaia DR3 cross-match (``tools/build_merged_catalog.py``).

Synthetic fixtures written with the real ``RECONS_SCHEMA`` and
``GAIA_SUBSET_SCHEMA`` exercise proper-motion propagation, the parallax gate,
brightness-ranked pairing for shared-coordinate binaries, the provenance
rules and the report.
"""

import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from tools import build_merged_catalog as merge  # noqa: E402
from tools.ingest_gaia import GAIA_SUBSET_SCHEMA  # noqa: E402
from tools.ingest_recons import RECONS_SCHEMA  # noqa: E402


def recons_row(identifier, rank, cns, component, common, ra, dec, plx_mas, plx_err,
               pmra=0.0, pmdec=0.0, sptype="M4.0 V", v_mag=11.0):
    row = {field.name: None for field in RECONS_SCHEMA}
    distance = 1000.0 / plx_mas
    row.update({
        "id": identifier, "is_recons_entry": True, "system_rank": rank,
        "system_name": cns, "cns_name": cns, "component": component, "common_name": common,
        "ra_hms": "00 00 00", "dec_dms": "+00 00 00", "ra_deg": ra, "dec_deg": dec,
        "ref_epoch_jyear": 2000.0, "pmra_mas_per_year": pmra, "pmdec_mas_per_year": pmdec,
        "parallax_arcsec": plx_mas / 1000.0, "parallax_mas": plx_mas,
        "parallax_error_mas": plx_err, "distance_pc": distance,
        "distance_ly": distance * merge.LIGHT_YEARS_PER_PARSEC,
        "x_pc": 0.0, "y_pc": 0.0, "z_pc": 0.0,
        "galactic_longitude_deg": 0.0, "galactic_latitude_deg": 0.0,
        "spectral_type": sptype, "v_mag": v_mag, "source_catalog": "RECONS",
    })
    return row


def gaia_row(source_id, ra, dec, plx_mas, plx_err=0.05, g_mag=10.0, pmra=0.0, pmdec=0.0,
             teff=3200.0):
    row = {field.name: None for field in GAIA_SUBSET_SCHEMA}
    distance = 1000.0 / plx_mas
    row.update({
        "id": f"gaia-dr3:{source_id}", "gaia_dr3_source_id": source_id,
        "designation": f"Gaia DR3 {source_id}", "ra_deg": ra, "dec_deg": dec,
        "ref_epoch_jyear": 2016.0, "parallax_mas": plx_mas, "parallax_error_mas": plx_err,
        "parallax_over_error": plx_mas / plx_err, "pmra_mas_per_year": pmra,
        "pmdec_mas_per_year": pmdec, "phot_g_mean_mag": g_mag, "teff_gspphot_k": teff,
        "distance_pc": distance, "distance_ly": distance * merge.LIGHT_YEARS_PER_PARSEC,
        "distance_mode": "inverse_parallax", "x_pc": 0.0, "y_pc": 0.0, "z_pc": 0.0,
        "galactic_longitude_deg": 10.0, "galactic_latitude_deg": 20.0,
        "source_file": "fixture.csv", "source_catalog": "Gaia DR3",
    })
    return row


ARCSEC = 1.0 / 3600.0

# Barnard-like proper motion: 16 years x 10.3 arcsec/yr = ~165 arcsec north.
BARNARD_PMDEC = 10300.0
BARNARD_SHIFT_DEG = BARNARD_PMDEC * 16 / 3.6e6

RECONS_FIXTURE = [
    # 1. plain match; Gaia parallax error smaller -> Gaia parallax wins
    recons_row("recons:gj-551", 1, "GJ 551", None, "Proxima Centauri", 217.4, -62.7, 768.7, 0.3,
               sptype="M5.0 V", v_mag=11.05),
    # 2. high proper motion: only matches if J2000 -> 2016 propagation is applied
    recons_row("recons:gj-699", 2, "GJ 699", None, "Barnard's Star", 269.45, 4.69, 545.5, 0.3,
               pmdec=BARNARD_PMDEC, sptype="M3.5 V", v_mag=9.57),
    # 3. bright star absent from Gaia -> recons_only with propagated position
    recons_row("recons:gj-244:a", 3, "GJ 244", "A", "Sirius", 101.29, -16.72, 380.0, 1.3,
               pmra=-546.0, pmdec=-1223.0, sptype="A1.0 V", v_mag=-1.43),
    # 4. shared-coordinate binary resolved by Gaia: brighter V must get brighter G
    recons_row("recons:gj-65:a", 4, "GJ 65", "A", "BL Ceti", 24.76, -17.95, 373.7, 2.7,
               sptype="M5.5 V", v_mag=12.61),
    recons_row("recons:gj-65:b", 4, "GJ 65", "B", "UV Ceti", 24.76, -17.95, 373.7, 2.7,
               sptype="M6.0 V", v_mag=13.06),
    # 5. parallax conflict: positional match but RECONS parallax 30% off
    recons_row("recons:lp-944-020", 5, "LP 944-020", None, None, 52.0, -35.4, 201.0, 4.0,
               sptype="M9.0 V", v_mag=18.69),
    # 6. RECONS parallax more precise than Gaia -> RECONS parallax wins
    recons_row("recons:gj-144", 6, "GJ 144", None, "epsilon Eridani", 53.23, -9.46, 311.2, 0.09,
               sptype="K2.0 V", v_mag=3.73),
    # 7. shared coordinate, single Gaia source: only one component can match
    recons_row("recons:gj-280:a", 7, "GJ 280", "A", "Procyon", 114.83, 5.22, 285.0, 1.0,
               sptype="F5 IV-V", v_mag=0.37),
    recons_row("recons:gj-280:b", 7, "GJ 280", "B", "Procyon B", 114.83, 5.22, 285.0, 1.0,
               sptype="DQZ", v_mag=10.70),
]

GAIA_FIXTURE = [
    gaia_row(5853498713190525696, 217.4 + 0.5 * ARCSEC / math.cos(math.radians(-62.7)), -62.7,
             768.07, 0.05, g_mag=8.98),
    gaia_row(4472832130942575872, 269.45, 4.69 + BARNARD_SHIFT_DEG, 546.98, 0.04, g_mag=8.19,
             pmdec=BARNARD_PMDEC),
    gaia_row(5140693571158946048, 24.76 + 2.5 * ARCSEC, -17.95, 373.8, 0.3, g_mag=10.82),
    gaia_row(5140693571158739840, 24.76 - 2.5 * ARCSEC, -17.95, 367.7, 0.3, g_mag=10.51),
    gaia_row(4838051225417927168, 52.0, -35.4 + 3 * ARCSEC, 155.9, 0.1, g_mag=16.0),
    gaia_row(5164707970261890560, 53.23, -9.46, 310.58, 0.12, g_mag=3.47),
    gaia_row(3111000000000000000, 114.83, 5.22 + 4 * ARCSEC, 284.5, 0.3, g_mag=10.8),  # Procyon B
    # Gaia-only neighbours: one far away, one within 30" of Proxima but with a
    # wildly different parallax (must be rejected and stay gaia_only)
    gaia_row(1000000000000000001, 100.0, 40.0, 60.0, 0.02, g_mag=12.0),
    gaia_row(1000000000000000002, 217.4, -62.7 + 10 * ARCSEC, 45.0, 0.02, g_mag=15.0),
]


class MergeCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.recons_path = base / "recons_nearest.parquet"
        cls.gaia_path = base / "gaia_dr3_subset.parquet"
        cls.output = base / "merged_catalog.parquet"
        cls.report = base / "merge_report.md"
        pq.write_table(pa.Table.from_pylist(RECONS_FIXTURE, schema=RECONS_SCHEMA), cls.recons_path)
        pq.write_table(pa.Table.from_pylist(GAIA_FIXTURE, schema=GAIA_SUBSET_SCHEMA), cls.gaia_path)
        cls.summary = merge.build_merged_catalog(cls.recons_path, cls.gaia_path, cls.output,
                                                 cls.report)
        cls.table = pq.read_table(cls.output)
        cls.rows = {row["id"]: row for row in cls.table.to_pylist()}
        cls.by_recons = {row["recons_id"]: row for row in cls.table.to_pylist()
                         if row["recons_id"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_counts_schema_and_unique_ids(self):
        counts = self.summary["counts"]
        self.assertEqual(counts, {"matched": 6, "matched_parallax_conflict": 1,
                                  "recons_only": 2, "gaia_only": 2})
        self.assertEqual(self.table.num_rows, 11)
        self.assertEqual(self.table.schema.names, merge.MERGED_SCHEMA.names)
        ids = self.table.column("id").to_pylist()
        self.assertEqual(len(ids), len(set(ids)))
        distances = self.table.column("distance_pc").to_pylist()
        self.assertEqual(distances, sorted(distances))
        self.assertIn(b"match_counts", self.table.schema.metadata)

    def test_plain_match_provenance(self):
        row = self.by_recons["recons:gj-551"]
        self.assertEqual(row["id"], "gaia-dr3:5853498713190525696")
        self.assertEqual(row["match_status"], "matched")
        self.assertEqual(row["primary_name"], "Proxima Centauri")
        self.assertEqual(row["source_of_name"], "recons_common_name")
        self.assertEqual(row["recons_name"], "GJ 551")
        self.assertEqual(row["gaia_source_id"], 5853498713190525696)
        self.assertEqual(row["source_of_parallax"], "gaia")
        self.assertAlmostEqual(row["parallax_mas"], 768.07)
        self.assertAlmostEqual(row["recons_parallax_mas"], 768.7)
        self.assertEqual(row["source_of_spectral_type"], "recons")
        self.assertEqual(row["spectral_type"], "M5.0 V")
        self.assertEqual(row["source_of_position"], "gaia")
        self.assertEqual(row["ref_epoch_jyear"], 2016.0)
        self.assertAlmostEqual(row["match_separation_arcsec"], 0.5, places=2)
        self.assertEqual(row["match_candidates"], 1)  # the 45 mas neighbour was rejected
        self.assertAlmostEqual(row["phot_g_mean_mag"], 8.98)  # Gaia fills photometry
        self.assertAlmostEqual(row["teff_gspphot_k"], 3200.0)
        self.assertAlmostEqual(row["distance_pc"], 1000.0 / 768.07)
        radius = math.sqrt(row["x_pc"] ** 2 + row["y_pc"] ** 2 + row["z_pc"] ** 2)
        self.assertAlmostEqual(radius, row["distance_pc"], places=9)
        self.assertEqual(row["source_catalogs"], "RECONS+Gaia DR3")

    def test_proper_motion_propagation_enables_high_pm_match(self):
        row = self.by_recons["recons:gj-699"]
        self.assertEqual(row["match_status"], "matched")
        self.assertEqual(row["gaia_source_id"], 4472832130942575872)
        self.assertLess(row["match_separation_arcsec"], 1.0)
        # Without propagation the separation would be ~165 arcsec.
        ra, dec = merge.propagate_position(269.45, 4.69, 0.0, BARNARD_PMDEC, 2000.0, 2016.0)
        self.assertAlmostEqual(dec, 4.69 + BARNARD_SHIFT_DEG)
        self.assertGreater(merge.angular_separation_arcsec(269.45, 4.69, ra, dec), 160.0)

    def test_unmatched_bright_star_keeps_recons_data(self):
        row = self.by_recons["recons:gj-244:a"]
        self.assertEqual(row["id"], "recons:gj-244:a")
        self.assertEqual(row["match_status"], "recons_only")
        self.assertIsNone(row["gaia_source_id"])
        self.assertEqual(row["source_of_parallax"], "recons")
        self.assertEqual(row["source_of_position"], "recons_propagated")
        self.assertEqual(row["ref_epoch_jyear"], 2016.0)
        expected_ra, expected_dec = merge.propagate_position(
            101.29, -16.72, -546.0, -1223.0, 2000.0, 2016.0)
        self.assertAlmostEqual(row["ra_deg"], expected_ra)
        self.assertAlmostEqual(row["dec_deg"], expected_dec)
        self.assertEqual(row["source_catalogs"], "RECONS")
        self.assertEqual(row["spectral_type"], "A1.0 V")

    def test_shared_coordinate_binary_paired_by_brightness(self):
        a = self.by_recons["recons:gj-65:a"]
        b = self.by_recons["recons:gj-65:b"]
        self.assertEqual(a["match_status"], "matched")
        self.assertEqual(b["match_status"], "matched")
        self.assertNotEqual(a["gaia_source_id"], b["gaia_source_id"])
        self.assertLess(a["phot_g_mean_mag"], b["phot_g_mean_mag"])  # brighter V -> brighter G
        self.assertEqual(a["match_candidates"], 2)
        self.assertIn("ambiguous", a["match_note"])

    def test_parallax_conflict_is_linked_not_duplicated(self):
        row = self.by_recons["recons:lp-944-020"]
        self.assertEqual(row["match_status"], "matched_parallax_conflict")
        self.assertEqual(row["gaia_source_id"], 4838051225417927168)
        self.assertEqual(row["source_of_parallax"], "gaia")
        self.assertAlmostEqual(row["parallax_mas"], 155.9)
        self.assertAlmostEqual(row["recons_parallax_mas"], 201.0)
        self.assertGreater(row["parallax_discrepancy_pct"], 25.0)
        self.assertIn("parallax conflict", row["match_note"])
        self.assertEqual(row["primary_name"], "LP 944-020")
        self.assertEqual(row["source_of_name"], "recons_cns_name")
        self.assertNotIn("gaia-dr3:4838051225417927168",
                         [r["id"] for r in self.rows.values() if r["match_status"] == "gaia_only"])

    def test_recons_parallax_wins_when_more_precise(self):
        row = self.by_recons["recons:gj-144"]
        self.assertEqual(row["match_status"], "matched")
        self.assertEqual(row["source_of_parallax"], "recons")
        self.assertAlmostEqual(row["parallax_mas"], 311.2)
        self.assertAlmostEqual(row["parallax_error_mas"], 0.09)
        self.assertAlmostEqual(row["gaia_parallax_mas"], 310.58)
        self.assertAlmostEqual(row["distance_pc"], 1000.0 / 311.2)

    def test_single_gaia_source_goes_to_best_component(self):
        primary = self.by_recons["recons:gj-280:a"]
        secondary = self.by_recons["recons:gj-280:b"]
        self.assertEqual(secondary["match_status"], "matched")  # V 10.7 vs G 10.8
        self.assertEqual(primary["match_status"], "recons_only")
        self.assertIn("sibling", primary["match_note"])
        self.assertIn("contested", secondary["match_note"])

    def test_gaia_only_rows(self):
        far = self.rows["gaia-dr3:1000000000000000001"]
        near = self.rows["gaia-dr3:1000000000000000002"]
        for row in (far, near):
            self.assertEqual(row["match_status"], "gaia_only")
            self.assertEqual(row["source_of_name"], "gaia_designation")
            self.assertEqual(row["source_of_parallax"], "gaia")
            self.assertIsNone(row["spectral_type"])
            self.assertEqual(row["source_catalogs"], "Gaia DR3")
        self.assertEqual(far["primary_name"], "Gaia DR3 1000000000000000001")

    def test_report_contents(self):
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("RECONS components matched to Gaia DR3 | 7 / 9", text)
        self.assertIn("recons:gj-244:a | Sirius", text)
        self.assertIn("## Parallax conflicts linked to avoid duplicates", text)
        self.assertIn("recons:lp-944-020", text)
        self.assertIn("recons:gj-65:a | BL Ceti", text)

    def test_cli_main(self):
        output = Path(self.tmp.name) / "cli.parquet"
        status = merge.main(["--recons", str(self.recons_path), "--gaia", str(self.gaia_path),
                             "--output", str(output), "--report", ""])
        self.assertEqual(status, 0)
        self.assertEqual(pq.read_metadata(output).num_rows, 11)


class GeometryTests(unittest.TestCase):
    def test_angular_separation(self):
        self.assertAlmostEqual(merge.angular_separation_arcsec(10.0, 20.0, 10.0, 20.0), 0.0)
        self.assertAlmostEqual(merge.angular_separation_arcsec(0.0, 0.0, 0.0, 1.0 / 3600), 1.0, places=6)
        self.assertAlmostEqual(merge.angular_separation_arcsec(0.0, 60.0, 2.0 / 3600, 60.0),
                               1.0, places=3)  # RA step scaled by cos(dec)
        self.assertAlmostEqual(merge.angular_separation_arcsec(0.0, 0.0, 180.0, 0.0), 648000.0)

    def test_propagation_without_proper_motion_is_identity(self):
        self.assertEqual(merge.propagate_position(1.0, 2.0, None, None, 2000.0, 2016.0), (1.0, 2.0))
        ra, dec = merge.propagate_position(359.9999, 0.0, 3600.0, 0.0, 2000.0, 2016.0)
        self.assertLess(ra, 1.0)  # wraps around 360


if __name__ == "__main__":
    unittest.main()
