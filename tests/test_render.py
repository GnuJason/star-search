"""Renderer tests: PNG validity, dimensions, byte-level determinism, parameter fallbacks.

Run: python tests/test_render.py path/to/star-search   (ctest passes the binary path)
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_catalog import STAR_SCHEMA, build_fixture, fixture_rows

BINARY = str(Path(sys.argv.pop(1)).resolve()) if len(sys.argv) > 1 else None

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png(path):
    """Minimal PNG reader: validates chunk CRCs, returns (width, height, rgb rows)."""
    data = Path(path).read_bytes()
    assert data.startswith(PNG_SIGNATURE), "bad PNG signature"
    offset, chunks = 8, []
    while offset < len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == crc, f"bad CRC in {kind!r}"
        chunks.append((kind, body))
        offset += 12 + length
    assert chunks[0][0] == b"IHDR" and chunks[-1][0] == b"IEND"
    width, height, depth, color_type = struct.unpack(">IIBB", chunks[0][1][:10])
    assert (depth, color_type) == (8, 2), "expected 8-bit RGB"
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    stride = width * 3
    assert len(raw) == height * (stride + 1)
    pixels, previous = bytearray(), bytearray(stride)
    for row in range(height):   # undo PNG scanline filters (RFC 2083 section 6)
        kind = raw[row * (stride + 1)]
        line = bytearray(raw[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0
            b = previous[i]
            c = previous[i - 3] if i >= 3 else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        pixels += line
        previous = line
    return width, height, bytes(pixels)


def star(identifier, **values):
    row = {field.name: None for field in STAR_SCHEMA}
    row.update(id=identifier, name=identifier, source_catalog="render-fixture", ra_deg=10.0,
               dec_deg=-10.0, ref_epoch_jyear=2016.0, galactic_longitude_deg=1.0,
               galactic_latitude_deg=1.0)
    row.update(values)
    return row


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="star-render-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        build_fixture(self.data)
        stars, _ = fixture_rows()
        full = [{field.name: s.get(field.name) for field in STAR_SCHEMA} for s in stars]
        full += [
            star("render:gspphot", gaia_dr3_source_id=5853498713190525696, teff_k=2829.0,
                 spectral_type="M5.0 V", phot_g_mean_mag=8.98, parallax_mas=768.07),
            star("render:spectral", spectral_type="G2.0 V", absolute_v_mag=4.38),
            star("render:colour", bp_rp=0.82),
            star("render:wd", spectral_type="DA2"),
            star("render:variable", gaia_dr3_source_id=42, teff_k=3200.0,
                 phot_variable_flag="VARIABLE"),
        ]
        pq.write_table(pa.Table.from_pylist(full, schema=STAR_SCHEMA), self.data / "stars.parquet")
        self.assets = self.root / "assets"
        self.environment = {**os.environ, "STAR_SEARCH_DATA_DIR": str(self.data),
                            "STAR_SEARCH_ASSETS_DIR": str(self.assets)}

    def render(self, *arguments, status=0):
        result = subprocess.run([BINARY, "--json", "render", *arguments], env=self.environment,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_png_header_dimensions_and_default_path(self):
        result = self.render("render:gspphot", "--size", "48")
        path = Path(result["output"])
        self.assertEqual(path, self.assets / "5853498713190525696.png")
        width, height, raw = read_png(path)
        self.assertEqual((width, height, result["width"], result["height"]), (48, 48, 48, 48))
        centre = (24 * 48 + 24) * 3
        self.assertGreater(raw[centre], 100, "disk centre should be bright")
        self.assertGreater(raw[centre], raw[centre + 2], "a 2800 K star is redder than blue")

    def test_byte_identical_rerender(self):
        first = self.root / "a.png"
        second = self.root / "nested" / "dir" / "b.png"
        self.render("render:spectral", "--size", "64", "-o", str(first))
        self.render("render:spectral", "--size", "64", "--output", str(second))
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(),
                         hashlib.sha256(second.read_bytes()).hexdigest())
        other = self.root / "c.png"
        self.render("render:colour", "--size", "64", "-o", str(other))
        self.assertNotEqual(first.read_bytes(), other.read_bytes())

    def test_parameter_fallbacks(self):
        gspphot = self.render("render:gspphot", "--size", "16")["parameters"]
        self.assertEqual(gspphot["teff_source"], "gaia_gspphot")
        self.assertEqual(gspphot["radius_source"], "gaia_g_parallax_bc")
        self.assertAlmostEqual(gspphot["radius_solar"], 0.125, delta=0.03)   # Proxima ~0.15
        spectral = self.render("render:spectral", "--size", "16")["parameters"]
        self.assertEqual((spectral["teff_source"], spectral["radius_source"]),
                         ("spectral_type", "recons_mv_bc"))
        self.assertAlmostEqual(spectral["teff_k"], 5770, delta=1)
        self.assertAlmostEqual(spectral["radius_solar"], 1.22, delta=0.05)  # alpha Cen A
        colour = self.render("render:colour", "--size", "16")["parameters"]
        self.assertEqual(colour["teff_source"], "bp_rp")
        self.assertAlmostEqual(colour["teff_k"], 5770, delta=1)
        self.assertEqual(colour["radius_source"], "main_sequence_teff")
        wd = self.render("render:wd", "--size", "16")["parameters"]
        self.assertEqual((wd["teff_k"], wd["radius_source"]), (25200, "white_dwarf_default"))
        self.assertGreaterEqual(wd["disk_radius_fraction"], 0.22)
        default = self.render("fixture:pair-a", "--size", "16")["parameters"]
        self.assertEqual(default["teff_source"], "default_solar")

    def test_variability_phase(self):
        paths = [self.root / f"v{index}.png" for index in range(3)]
        self.render("render:variable", "--size", "32", "-o", str(paths[0]))
        result = self.render("render:variable", "--size", "32", "--phase", "0.25", "-o", str(paths[1]))
        self.assertTrue(result["parameters"]["variable"])
        self.assertEqual(result["parameters"]["phase"], 0.25)
        self.assertNotEqual(paths[0].read_bytes(), paths[1].read_bytes())
        # Non-variables ignore the phase entirely.
        self.render("render:spectral", "--size", "32", "-o", str(paths[2]))
        again = self.root / "v3.png"
        self.render("render:spectral", "--size", "32", "--phase", "0.25", "-o", str(again))
        self.assertEqual(paths[2].read_bytes(), again.read_bytes())

    def test_non_gaia_default_filename_is_sanitised(self):
        result = self.render("render:wd", "--size", "16")
        self.assertEqual(Path(result["output"]).name, "render-wd.png")

    def test_unwritable_output(self):
        blocker = self.root / "file"
        blocker.write_text("x")
        self.assertEqual(self.render("render:wd", "-o", str(blocker / "x.png"), status=1)["error"],
                         "write_error")


if __name__ == "__main__":
    if BINARY is None:
        sys.exit("usage: test_render.py path/to/star-search")
    unittest.main()
