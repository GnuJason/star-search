import json
from pathlib import Path
import tempfile
import unittest

import pyarrow.parquet as pq

from tools.ingest_gaia import build_gaia_catalog


HEADER = ("source_id,designation,ref_epoch,ra,dec,parallax,parallax_error,ruwe,"
          "phot_g_mean_mag,phot_bp_mean_mag,phot_rp_mean_mag,l,b,distance_gspphot\n")


class GaiaIngestionTests(unittest.TestCase):
    def test_build_catalog_from_commented_csv_and_apply_cuts(self):
        source_rows = [
            "101,Gaia DR3 101,2016,10,20,1,0.1,1.2,15.9,16.1,15.2,100,30,12\n",
            "102,Gaia DR3 102,2016,10,20,1,0.1,1.2,16,16,15,100,30,12\n",
            "103,Gaia DR3 103,2016,10,20,,0.1,1.2,15,16,15,100,30,12\n",
            "104,Gaia DR3 104,2016,10,20,1,0.2,1.2,15,16,15,100,30,12\n",
            "105,Gaia DR3 105,2016,10,20,1,0.1,1.4,15,16,15,100,30,12\n",
            "106,Gaia DR3 106,2016,10,20,1,0.1,1.2,15,16,15,100,30,0\n",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("# %ECSV 1.0\n# ---\n" + HEADER + "".join(source_rows))
            output = root / "catalog"

            counts = build_gaia_catalog(source, output, max_ruwe=1.4)

            self.assertEqual(counts, {
                "input": 6, "magnitude": 5, "parallax": 4, "snr": 3,
                "ruwe": 2, "distance": 1,
            })
            stars = pq.read_table(output / "stars.parquet")
            self.assertEqual(stars.num_rows, 2)
            self.assertEqual(stars["gaia_dr3_source_id"].to_pylist(), [101, 106])
            self.assertEqual(stars["distance_pc"].to_pylist(), [12.0, None])
            self.assertEqual(stars["distance_method"].to_pylist(),
                             ["Gaia DR3 GSP-Phot", None])
            self.assertEqual(pq.read_table(output / "aliases.parquet").num_rows, 0)
            metadata = json.loads((output / "catalog.json").read_text())
            self.assertFalse(metadata["is_fixture"])
            self.assertIn("parallax / parallax_error > 5", metadata["selection_rules"])
            self.assertIn("ruwe < 1.4", metadata["selection_rules"])
            self.assertIn("do not invert parallax", metadata["distance_policy"])


if __name__ == "__main__":
    unittest.main()
