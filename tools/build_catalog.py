"""Build the CLI catalog directory (stars.parquet, aliases.parquet, catalog.json).

Two modes:

* ``--fixture``  writes a deliberately synthetic five-row catalog for tests.
* ``--merged``   projects ``gaia_datasets/merged_catalog.parquet`` (RECONS x
  Gaia DR3 cross-match produced by ``tools/build_merged_catalog.py``) onto the
  CLI star schema documented in ``docs/catalog-contract.md`` and emits RECONS
  names, GJ/LHS designations and Gaia designations as aliases.

Example::

    .venv/bin/python tools/build_catalog.py \
        --merged gaia_datasets/merged_catalog.parquet --output build/catalog
"""

import argparse
import datetime as dt
import json
import math
import shutil
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
    # Optional physical inputs for `star-search render` (schema 1 additive columns;
    # the CLI treats them as NULL when an older catalog lacks them).
    pa.field("teff_k", pa.float64()),
    pa.field("bp_rp", pa.float64()),
    pa.field("absolute_v_mag", pa.float64()),
    pa.field("phot_variable_flag", pa.string()),
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


def _text(value):
    """Return a trimmed string or None for empty / NaN-like values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _finite(value):
    """Return a float or None; NaN and infinities become None."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def star_from_merged(row):
    """Project one merged_catalog row onto the CLI STAR_SCHEMA."""
    parallax = _finite(row.get("parallax_mas"))
    distance = _finite(row.get("distance_pc"))
    parallax_source = _text(row.get("source_of_parallax"))
    method = None
    if distance is not None:
        method = _text(row.get("distance_mode")) or "inverse_parallax"
        if parallax_source:
            method = f"{method}:{parallax_source}"
    return {
        "id": row["id"],
        "gaia_dr3_source_id": row.get("gaia_source_id"),
        "name": _text(row.get("primary_name")),
        "source_catalog": _text(row.get("source_catalogs")),
        "ra_deg": float(row["ra_deg"]),
        "dec_deg": float(row["dec_deg"]),
        "ref_epoch_jyear": float(row.get("ref_epoch_jyear") or 2016.0),
        "parallax_mas": parallax,
        "parallax_error_mas": _finite(row.get("parallax_error_mas")),
        "distance_pc": distance,
        "distance_method": method,
        "galactic_longitude_deg": float(row["galactic_longitude_deg"]),
        "galactic_latitude_deg": float(row["galactic_latitude_deg"]),
        "phot_g_mean_mag": _finite(row.get("phot_g_mean_mag")),
        "phot_bp_mean_mag": _finite(row.get("phot_bp_mean_mag")),
        "phot_rp_mean_mag": _finite(row.get("phot_rp_mean_mag")),
        "spectral_type": _text(row.get("spectral_type")),
        "teff_k": _finite(row.get("teff_gspphot_k")),
        "bp_rp": _finite(row.get("bp_rp")),
        "absolute_v_mag": _finite(row.get("absolute_mag")),
        "phot_variable_flag": _text(row.get("phot_variable_flag")),
    }


def aliases_from_merged(row):
    """Return the alias rows for one merged_catalog row.

    Every name a user might type is emitted once per star (case-insensitive):
    RECONS common name, RECONS component name ("GJ 65 A"), the bare CNS/GJ
    system name, the LHS designation ("LHS 49"), the RECONS row id, the Gaia
    designation and the bare Gaia source_id.  The star's own ``id`` and ``name`` are skipped
    because the CLI already resolves those directly.
    """
    lhs = _text(row.get("lhs_id"))
    if lhs and not lhs.upper().startswith("LHS"):
        lhs = f"LHS {lhs}"
    candidates = [
        _text(row.get("common_name")),
        _text(row.get("recons_name")),
        _text(row.get("recons_system_name")),
        lhs,
        _text(row.get("recons_id")),
        _text(row.get("gaia_designation")),
    ]
    gaia_id = row.get("gaia_source_id")
    if gaia_id is not None:
        candidates.append(str(gaia_id))
    skip = {row["id"].lower()}
    name = _text(row.get("primary_name"))
    if name:
        skip.add(name.lower())
    aliases = []
    for alias in candidates:
        if not alias or alias.lower() in skip:
            continue
        skip.add(alias.lower())
        aliases.append({"alias": alias, "star_id": row["id"]})
    return aliases


def build_from_merged(merged_path, output, recons_path=None):
    """Write the CLI catalog directory from merged_catalog.parquet.

    Returns a summary dict (row counts and alias counts).  If ``recons_path``
    exists it is copied next to stars.parquet so the ``recons-nearest`` and
    ``recons-info`` commands work from the same STAR_SEARCH_DATA_DIR.
    """
    merged_path = Path(merged_path)
    output = Path(output)
    table = pq.read_table(merged_path)
    rows = table.to_pylist()
    stars = [star_from_merged(row) for row in rows]
    aliases = [alias for row in rows for alias in aliases_from_merged(row)]
    validate_catalog(stars, aliases)

    output.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(stars, schema=STAR_SCHEMA),
                   output / "stars.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(aliases, schema=ALIAS_SCHEMA),
                   output / "aliases.parquet", compression="zstd")

    source_metadata = {
        key.decode("utf-8"): value.decode("utf-8")
        for key, value in (table.schema.metadata or {}).items()
        if not key.startswith(b"ARROW:") and not key.startswith(b"pandas")
    }
    status_counts = {}
    for row in rows:
        status = row.get("match_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    generated_on = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        "schema_version": 1,
        "catalog_version": f"merged-{generated_on[:10]}",
        "source_catalog": "RECONS 100 nearest systems (recons.org, 2012-01-01 census) "
                          "cross-matched with Gaia DR3 (parallax > 40 mas)",
        "selection_rules": "Gaia DR3 sources with parallax > 40 mas (d < 25 pc) plus every "
                           "RECONS component; positional cross-match with parallax gate "
                           "(see gaia_datasets/merge_report.md)",
        "distance_policy": "distance_pc = 1000 / parallax_mas; distance_method records the "
                           "parallax provenance as inverse_parallax:<gaia|recons>",
        "limitations": "Bright stars saturated in Gaia (alpha Cen A/B, Sirius A, Procyon A, "
                       "Altair) and unresolved RECONS companions carry RECONS-only astrometry "
                       "propagated to epoch 2016.0; Gaia distances are naive parallax "
                       "inversions with no zero-point or prior correction.",
        "attribution": "ESA/Gaia/DPAC (Gaia DR3, https://www.cosmos.esa.int/gaia); "
                       "RECONS (Research Consortium On Nearby Stars, https://www.recons.org)",
        "license": "Gaia data: CC BY-SA 3.0 IGO (ESA/Gaia/DPAC). RECONS list: academic use "
                   "with attribution; verify terms before redistribution.",
        "is_fixture": False,
        "generated_on": generated_on,
        "source_file": merged_path.name,
        "star_count": len(stars),
        "alias_count": len(aliases),
        "match_status_counts": status_counts,
        "merged_catalog_metadata": source_metadata,
    }
    (output / "catalog.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    copied_recons = None
    if recons_path is not None and Path(recons_path).is_file():
        copied_recons = output / "recons_nearest.parquet"
        shutil.copyfile(recons_path, copied_recons)
    return {"stars": len(stars), "aliases": len(aliases),
            "match_status_counts": status_counts,
            "recons_copied": copied_recons is not None}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", action="store_true",
                      help="explicitly generate synthetic, non-scientific data")
    mode.add_argument("--merged", type=Path, metavar="PARQUET",
                      help="build the real catalog from merged_catalog.parquet")
    parser.add_argument("--recons", default=None, metavar="PARQUET",
                        help="RECONS parquet to copy into the catalog directory for "
                             "recons-* commands (default: recons_nearest.parquet next "
                             "to the merged file; pass an empty string to skip)")
    parser.add_argument("--output", type=Path, required=True, help="catalog directory")
    arguments = parser.parse_args(argv)
    if arguments.fixture:
        build_fixture(arguments.output)
        print(f"Wrote synthetic fixture catalog to {arguments.output}")
        return
    if arguments.recons is None:
        recons = arguments.merged.parent / "recons_nearest.parquet"
    elif arguments.recons == "":
        recons = None
    else:
        recons = Path(arguments.recons)
    summary = build_from_merged(arguments.merged, arguments.output, recons)
    print(f"Wrote {summary['stars']} stars and {summary['aliases']} aliases to "
          f"{arguments.output} (match_status: {summary['match_status_counts']}; "
          f"RECONS copied: {summary['recons_copied']})")


if __name__ == "__main__":
    main()