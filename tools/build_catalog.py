"""Generate a deliberately synthetic catalog for integration tests."""

import argparse
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


STAR_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("gaia_dr3_source_id", pa.int64()),
    pa.field("name", pa.string()),
    pa.field("source_catalog", pa.string()),
    pa.field("ra_deg", pa.float64(), nullable=False),
    pa.field("dec_deg", pa.float64(), nullable=False),
    pa.field("ref_epoch_jyear", pa.float64(), nullable=False),
    pa.field("parallax_mas", pa.float64()),
    pa.field("parallax_error_mas", pa.float64()),
    pa.field("distance_pc", pa.float64()),
    pa.field("distance_method", pa.string()),
    pa.field("galactic_longitude_deg", pa.float64(), nullable=False),
    pa.field("galactic_latitude_deg", pa.float64(), nullable=False),
    pa.field("phot_g_mean_mag", pa.float64()),
    pa.field("phot_bp_mean_mag", pa.float64()),
    pa.field("phot_rp_mean_mag", pa.float64()),
    pa.field("spectral_type", pa.string()),
])
ALIAS_SCHEMA = pa.schema([
    pa.field("alias", pa.string(), nullable=False),
    pa.field("star_id", pa.string(), nullable=False),
])


def validate_catalog(stars, aliases):
    identifiers = set()
    for star in stars:
        identifier = star.get("id")
        if not identifier or identifier != identifier.strip() or identifier in identifiers:
            raise ValueError("star IDs must be unique, nonempty, and trimmed")
        identifiers.add(identifier)
        for field in STAR_SCHEMA:
            value = star.get(field.name)
            if value is None and not field.nullable:
                raise ValueError(f"{identifier}: missing {field.name}")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{identifier}: non-finite {field.name}")
        for column in ("ra_deg", "galactic_longitude_deg"):
            if not 0 <= star[column] < 360:
                raise ValueError(f"{identifier}: invalid {column}")
        for column in ("dec_deg", "galactic_latitude_deg"):
            if not -90 <= star[column] <= 90:
                raise ValueError(f"{identifier}: invalid {column}")
        distance = star.get("distance_pc")
        method = star.get("distance_method")
        if distance is not None and (distance <= 0 or not method):
            raise ValueError(f"{identifier}: distance needs a positive value and method")
        if distance is None and method is not None:
            raise ValueError(f"{identifier}: distance method without distance")
        error = star.get("parallax_error_mas")
        if error is not None and error < 0:
            raise ValueError(f"{identifier}: negative parallax uncertainty")
        gaia_id = star.get("gaia_dr3_source_id")
        if gaia_id is not None and gaia_id <= 0:
            raise ValueError(f"{identifier}: invalid Gaia ID")
    pairs = set()
    for alias in aliases:
        name = alias["alias"]
        pair = (name.lower(), alias["star_id"])
        if not name or name != name.strip() or pair in pairs:
            raise ValueError("aliases must be nonempty, trimmed, and unique per star")
        if alias["star_id"] not in identifiers:
            raise ValueError("alias references an unknown star")
        pairs.add(pair)
    pa.Table.from_pylist(stars, schema=STAR_SCHEMA).validate(full=True)
    pa.Table.from_pylist(aliases, schema=ALIAS_SCHEMA).validate(full=True)


def fixture_rows():
    def star(identifier, name, distance):
        return {
            "id": identifier,
            "name": name,
            "source_catalog": "synthetic-fixture",
            "ra_deg": 266.4049948010461,
            "dec_deg": -28.9361739601387,
            "ref_epoch_jyear": 2016.0,
            "distance_pc": distance,
            "distance_method": "synthetic" if distance is not None else None,
            "galactic_longitude_deg": 0.0,
            "galactic_latitude_deg": 0.0,
        }

    stars = [
        star("fixture:near", "Fixture Near", 1.0),
        star("fixture:pair-a", "Fixture Pair A", 2.0),
        star("fixture:pair-b", "Fixture Pair B", 2.0),
        star("fixture:unknown", None, None),
        star("fixture:special", 'Fixture O\'Brien "100%_" \\ Star', 4.0),
    ]
    stars[0].update(gaia_dr3_source_id=9007199254740993, phot_g_mean_mag=0.0,
                    parallax_mas=1000.0, parallax_error_mas=0.1)
    stars[3]["parallax_mas"] = -0.5
    aliases = [
        {"alias": "Fixture Pair", "star_id": "fixture:pair-a"},
        {"alias": "Fixture Pair", "star_id": "fixture:pair-b"},
        {"alias": "Near", "star_id": "fixture:near"},
        {"alias": "fixture:near", "star_id": "fixture:pair-a"},
    ]
    return stars, aliases


def build_fixture(output):
    stars, aliases = fixture_rows()
    validate_catalog(stars, aliases)
    output.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(stars, schema=STAR_SCHEMA),
                   output / "stars.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(aliases, schema=ALIAS_SCHEMA),
                   output / "aliases.parquet", compression="zstd")
    metadata = {
        "schema_version": 1,
        "catalog_version": "synthetic-fixture-v1",
        "source_catalog": "Synthetic test data; not Gaia observations",
        "selection_rules": "Five invented rows exercising CLI edge cases",
        "distance_policy": "Invented positive distances or null; no scientific inference",
        "limitations": "TEST FIXTURE ONLY. Not suitable for astronomy or navigation.",
        "attribution": "Generated by star-search tools/build_catalog.py",
        "license": "Synthetic test values; no third-party catalog included",
        "is_fixture": True,
    }
    (output / "catalog.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", required=True,
                        help="explicitly generate synthetic, non-scientific data")
    parser.add_argument("--output", type=Path, required=True, help="catalog directory")
    arguments = parser.parse_args()
    build_fixture(arguments.output)


if __name__ == "__main__":
    main()