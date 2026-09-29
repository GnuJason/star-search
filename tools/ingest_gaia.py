"""Build a star-search catalog from a Gaia DR3 ECSV/CSV source chunk."""

import argparse
import csv
import json
import math
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

if __package__:
    from .build_catalog import ALIAS_SCHEMA, STAR_SCHEMA, validate_catalog
else:
    from build_catalog import ALIAS_SCHEMA, STAR_SCHEMA, validate_catalog


REQUIRED_COLUMNS = {
    "source_id", "designation", "ref_epoch", "ra", "dec", "parallax",
    "parallax_error", "phot_g_mean_mag", "l", "b", "distance_gspphot",
}


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_gaia_stars(stream, max_ruwe=None):
    rows = (line for line in stream if not line.lstrip().startswith("#"))
    reader = csv.DictReader(rows)
    missing = REQUIRED_COLUMNS.difference(reader.fieldnames or ())
    if missing:
        raise ValueError(f"Gaia input is missing columns: {', '.join(sorted(missing))}")

    counts = {"input": 0, "magnitude": 0, "parallax": 0, "snr": 0,
              "ruwe": 0, "distance": 0}
    stars = []
    for row in reader:
        counts["input"] += 1
        magnitude = _number(row["phot_g_mean_mag"])
        if magnitude is None or magnitude >= 16:
            continue
        counts["magnitude"] += 1

        parallax = _number(row["parallax"])
        parallax_error = _number(row["parallax_error"])
        if parallax is None or parallax_error is None or parallax_error <= 0:
            continue
        counts["parallax"] += 1
        if parallax / parallax_error <= 5:
            continue
        counts["snr"] += 1

        ruwe = _number(row.get("ruwe"))
        if max_ruwe is not None and (ruwe is None or ruwe >= max_ruwe):
            continue
        counts["ruwe"] += 1

        source_id = int(row["source_id"])
        if source_id <= 0:
            raise ValueError(f"row {counts['input']}: source_id must be positive")
        coordinates = {
            "ra_deg": _number(row["ra"]),
            "dec_deg": _number(row["dec"]),
            "ref_epoch_jyear": _number(row["ref_epoch"]),
            "galactic_longitude_deg": _number(row["l"]),
            "galactic_latitude_deg": _number(row["b"]),
        }
        if any(value is None for value in coordinates.values()):
            raise ValueError(f"row {counts['input']}: selected source has invalid coordinates")

        distance = _number(row["distance_gspphot"])
        if distance is not None and distance > 0:
            counts["distance"] += 1
        else:
            distance = None
        designation = row.get("designation", "").strip()
        stars.append({
            "id": f"gaia-dr3:{source_id}",
            "gaia_dr3_source_id": source_id,
            "name": designation or None,
            "source_catalog": "Gaia DR3",
            **coordinates,
            "parallax_mas": parallax,
            "parallax_error_mas": parallax_error,
            "distance_pc": distance,
            "distance_method": "Gaia DR3 GSP-Phot" if distance is not None else None,
            "phot_g_mean_mag": magnitude,
            "phot_bp_mean_mag": _number(row.get("phot_bp_mean_mag")),
            "phot_rp_mean_mag": _number(row.get("phot_rp_mean_mag")),
            "spectral_type": None,
        })
    return stars, counts


def build_gaia_catalog(input_path, output, max_ruwe=None):
    with Path(input_path).open(newline="", encoding="utf-8") as source:
        stars, counts = read_gaia_stars(source, max_ruwe=max_ruwe)
    aliases = []
    validate_catalog(stars, aliases)

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(stars, schema=STAR_SCHEMA),
                   output / "stars.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(aliases, schema=ALIAS_SCHEMA),
                   output / "aliases.parquet", compression="zstd")
    metadata = {
        "schema_version": 1,
        "catalog_version": "v0.1-gaia-chunk1",
        "source_catalog": "Gaia DR3, GaiaSource_000000-003111.csv",
        "selection_rules": (
            "phot_g_mean_mag < 16; finite parallax and parallax_error > 0; "
            "parallax / parallax_error > 5"
            + (f"; ruwe < {max_ruwe}" if max_ruwe is not None else "; no RUWE cut")
        ),
        "distance_policy": (
            "Use positive Gaia DR3 GSP-Phot distance estimates as published; "
            "do not invert parallax. Missing or non-positive estimates are null."
        ),
        "limitations": (
            "One Gaia DR3 source chunk, not a complete stellar census. Quality cuts "
            "select a biased subset; GSP-Phot distances retain their source uncertainties."
        ),
        "attribution": "ESA/Gaia/DPAC; include the required Gaia DR3 acknowledgment and citation.",
        "license": "Gaia Archive source terms; verify attribution and redistribution terms before publication.",
        "is_fixture": False,
    }
    (output / "catalog.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path,
                        default=Path("gaia_datasets/GaiaSource_000000-003111.csv"))
    parser.add_argument("--output", type=Path, required=True,
                        help="catalog directory, e.g. data/processed/v0.1-gaia-chunk1")
    parser.add_argument("--max-ruwe", type=float,
                        help="optional strict RUWE upper bound, e.g. 1.4")
    arguments = parser.parse_args()
    if arguments.max_ruwe is not None and arguments.max_ruwe <= 0:
        parser.error("--max-ruwe must be positive")

    try:
        counts = build_gaia_catalog(arguments.input, arguments.output, arguments.max_ruwe)
    except (OSError, ValueError, pa.ArrowException) as error:
        parser.error(str(error))
    print(f"Rows read: {counts['input']}", file=sys.stderr)
    print(f"After phot_g_mean_mag < 16: {counts['magnitude']}", file=sys.stderr)
    print(f"After valid parallax and uncertainty: {counts['parallax']}", file=sys.stderr)
    print(f"After parallax S/N > 5: {counts['snr']}", file=sys.stderr)
    print(f"After RUWE selection: {counts['ruwe']}", file=sys.stderr)
    print(f"With positive GSP-Phot distances: {counts['distance']}", file=sys.stderr)
    print(f"Catalog written to {arguments.output}", file=sys.stderr)


if __name__ == "__main__":
    main()