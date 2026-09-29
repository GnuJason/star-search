import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

from tools.ingest_recons import RECONS_SCHEMA, build_recons_catalog, parse_recons_html


def source_row(rank, cns, component=None, object_count="1", lhs="-", ra="14 29 43.0",
              dec="-62 40 46", parallax="0.76885", error="0.00029",
              spectral="M5.0 V", v_source="*", v_mag="11.05", absolute_mag="15.48",
              mass="0.11", notes="", common="", overflow=False):
    prefix = f"{rank:3}. " if rank is not None else "     "
    cns_component = cns if overflow or not component else f"{cns} {component}"
    object_field = f"{component} {object_count}" if overflow and component else object_count
    return (prefix + f"{cns_component:<13}{object_field:<8}{lhs:<8}{ra:<11}{dec:<10}"
            f"{'H':<3}{'3.853':<6}{'281.5':<6}{'H':<4}{parallax:<8}{error:<9}"
            f"{'YHB*':<7}{spectral:<9}{v_source:<4}{v_mag:<8}{absolute_mag:<8}"
            f"{mass:<7}{notes:<20}{common}\n")


def sample_html():
    rows = [
        source_row(1, "GJ 551", object_count="-", lhs="49", common="Proxima Centauri"),
        source_row(None, "GJ 559", "A", "3", "50", ra="14 39 36.5",
                   dec="-60 50 02", parallax="0.74723", error="0.00117",
                   spectral="G2.0 V", v_source="G", v_mag="0.01", absolute_mag="4.38",
                   mass="1.14", common="alpha Centauri A"),
        source_row(None, "GJ 559", "B", "-", "51", ra="14 39 35.1",
                   dec="-60 50 14", parallax="0.74723", error="0.00117",
                   spectral="DA2", v_source="N", v_mag="8.44", absolute_mag="11.34",
                   mass="0.5  *", notes="orbit 8\"", common="alpha Centauri B"),
        source_row(None, "SCR 1845-6357", "A", "2", "", ra="18 45 05.3",
                   dec="-63 57 48", parallax="0.25950", error="0.00111",
                   spectral="M8.5 V", overflow=True),
        source_row(None, "SCR 1845-6357", "B", "-", "", ra="18 45 02.6",
                   dec="-63 57 52", parallax="0.25950", error="0.00111",
                   spectral="T6.0 V", v_mag="", absolute_mag="", mass="0.03",
                   overflow=True),
        source_row(None, "GJ 551", "P1", "-", "", spectral="planet"),
    ]
    return "<HTML><PRE>\n" + "".join(rows) + (
        "FORMER TOP 100 MEMBERS PUSHED OUT BY NEW MEMBERS\n"
        + source_row(101, "GJ 408", spectral="M2.5 V") + "</HTML>"
    )


class ReconsIngestionTests(unittest.TestCase):
    def test_parse_components_coordinates_and_distance(self):
        with patch("tools.ingest_recons.EXPECTED_RANKS", {1}):
            records = parse_recons_html(sample_html())

        self.assertEqual(len(records), 5)
        by_id = {record["id"]: record for record in records}
        proxima = by_id["recons:gj-551"]
        self.assertEqual(proxima["system_rank"], 1)
        self.assertAlmostEqual(proxima["ra_deg"], 217.4291666667)
        self.assertAlmostEqual(proxima["dec_deg"], -62.6794444444)
        self.assertAlmostEqual(proxima["distance_pc"], 1 / 0.76885)
        self.assertAlmostEqual(proxima["parallax_error_mas"], 0.29)
        self.assertAlmostEqual(
            (proxima["x_pc"] ** 2 + proxima["y_pc"] ** 2 + proxima["z_pc"] ** 2) ** 0.5,
            proxima["distance_pc"],
        )
        self.assertEqual(by_id["recons:gj-559:b"]["mass_solar"], 0.5)
        self.assertEqual(by_id["recons:gj-559:b"]["mass_estimate_flag"], "*")
        self.assertIn("recons:scr-1845-6357:a", by_id)
        self.assertIn("recons:scr-1845-6357:b", by_id)
        self.assertNotIn("recons:gj-551:p1", by_id)
        self.assertNotIn("recons:gj-408", by_id)

    def test_write_parquet_and_csv_with_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.html"
            source.write_text(sample_html(), encoding="utf-8")
            parquet_path = root / "recons.parquet"
            csv_path = root / "recons.csv"
            with patch("tools.ingest_recons.EXPECTED_RANKS", {1}):
                records = build_recons_catalog(source, parquet_path, csv_path)

            table = pq.read_table(parquet_path)
            self.assertEqual(table.schema.remove_metadata(), RECONS_SCHEMA)
            self.assertEqual(table.num_rows, len(records))
            self.assertEqual(table.schema.metadata[b"source_epoch"], b"2012-01-01")
            with csv_path.open(newline="", encoding="utf-8") as data:
                self.assertEqual(len(list(csv.DictReader(data))), len(records))


if __name__ == "__main__":
    unittest.main()