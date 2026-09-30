"""Gaia DR3 ingestion for star-search.

Three modes (see ``--help``):

``fetch``
    Query the ESA Gaia Archive TAP *sync* endpoint with ADQL and save the raw
    CSV response under ``gaia_datasets/raw/``. The default query selects every
    ``gaiadr3.gaia_source`` row with ``parallax > 40`` mas (within 25 pc).

``normalize``
    Read one or more raw Gaia files (CSV/ECSV, VOTable, FITS -- anything the
    user drops into ``gaia_datasets/raw/``) and write a single normalized
    ``gaia_datasets/gaia_dr3_subset.parquet`` with the shared coordinate
    conventions used by the RECONS table: decimal degrees (ICRS, epoch 2016.0),
    ``distance_pc`` and heliocentric equatorial XYZ in parsecs, plus a
    ``distance_mode`` flag describing how the distance was obtained.
    Schema: docs/data-schemas.md.

``catalog`` (legacy)
    The original prototype: build a CLI catalog directory directly from a Gaia
    CSV chunk using GSP-Phot distances only. Kept for backward compatibility.

Distance policy for ``normalize``: for this nearby, high signal-to-noise subset
(``parallax / parallax_error`` is typically in the hundreds) the inverse
parallax is an excellent estimator, so ``distance_pc = 1000 / parallax`` when
``parallax > 0`` and ``parallax_over_error >= --min-parallax-over-error``
(default 5); ``distance_mode`` is then ``inverse_parallax``. Rows failing that
gate fall back to ``distance_gspphot`` (``distance_mode = gspphot``) or are
left with a null distance (``distance_mode = none``). The mode is stored per
row so downstream consumers can filter.
"""

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

if __package__:
    from .build_catalog import ALIAS_SCHEMA, STAR_SCHEMA, validate_catalog
else:
    from build_catalog import ALIAS_SCHEMA, STAR_SCHEMA, validate_catalog


TAP_SYNC_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
DEFAULT_MIN_PARALLAX_MAS = 40.0
LIGHT_YEARS_PER_PARSEC = 3.2615637771674336

# Columns requested from gaiadr3.gaia_source by ``fetch``. Any subset is accepted
# by ``normalize``; missing optional columns become null.
FETCH_COLUMNS = (
    "source_id", "designation", "ref_epoch", "ra", "dec", "ra_error", "dec_error",
    "parallax", "parallax_error", "parallax_over_error",
    "pmra", "pmra_error", "pmdec", "pmdec_error",
    "radial_velocity", "radial_velocity_error", "ruwe",
    "phot_g_mean_mag", "phot_bp_mean_mag", "phot_rp_mean_mag", "bp_rp",
    "phot_variable_flag", "non_single_star",
    "teff_gspphot", "logg_gspphot", "mh_gspphot", "distance_gspphot", "l", "b",
)

NORMALIZE_REQUIRED_COLUMNS = ("source_id", "ra", "dec", "parallax")

GAIA_SUBSET_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("gaia_dr3_source_id", pa.int64(), nullable=False),
    pa.field("designation", pa.string()),
    pa.field("ra_deg", pa.float64(), nullable=False),
    pa.field("dec_deg", pa.float64(), nullable=False),
    pa.field("ra_error_mas", pa.float64()),
    pa.field("dec_error_mas", pa.float64()),
    pa.field("ref_epoch_jyear", pa.float64(), nullable=False),
    pa.field("parallax_mas", pa.float64(), nullable=False),
    pa.field("parallax_error_mas", pa.float64()),
    pa.field("parallax_over_error", pa.float64()),
    pa.field("pmra_mas_per_year", pa.float64()),
    pa.field("pmra_error_mas_per_year", pa.float64()),
    pa.field("pmdec_mas_per_year", pa.float64()),
    pa.field("pmdec_error_mas_per_year", pa.float64()),
    pa.field("radial_velocity_km_s", pa.float64()),
    pa.field("radial_velocity_error_km_s", pa.float64()),
    pa.field("ruwe", pa.float64()),
    pa.field("phot_g_mean_mag", pa.float64()),
    pa.field("phot_bp_mean_mag", pa.float64()),
    pa.field("phot_rp_mean_mag", pa.float64()),
    pa.field("bp_rp", pa.float64()),
    pa.field("phot_variable_flag", pa.string()),
    pa.field("non_single_star", pa.int32()),
    pa.field("teff_gspphot_k", pa.float64()),
    pa.field("logg_gspphot", pa.float64()),
    pa.field("mh_gspphot", pa.float64()),
    pa.field("distance_gspphot_pc", pa.float64()),
    pa.field("distance_pc", pa.float64()),
    pa.field("distance_ly", pa.float64()),
    pa.field("distance_mode", pa.string(), nullable=False),
    pa.field("x_pc", pa.float64()),
    pa.field("y_pc", pa.float64()),
    pa.field("z_pc", pa.float64()),
    pa.field("galactic_longitude_deg", pa.float64(), nullable=False),
    pa.field("galactic_latitude_deg", pa.float64(), nullable=False),
    pa.field("source_file", pa.string(), nullable=False),
    pa.field("source_catalog", pa.string(), nullable=False),
])


def default_adql(min_parallax_mas=DEFAULT_MIN_PARALLAX_MAS, columns=FETCH_COLUMNS):
    return (f"SELECT {', '.join(columns)} FROM gaiadr3.gaia_source "
            f"WHERE parallax > {min_parallax_mas:g}")


# --------------------------------------------------------------------------- fetch

def fetch_tap(query, output_path, url=TAP_SYNC_URL, timeout=600):
    """Run an ADQL query on the Gaia TAP sync endpoint and stream CSV to disk."""
    import requests  # optional dependency; only needed online

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    with requests.post(url, data=payload, stream=True, timeout=timeout) as response:
        if response.status_code != 200:
            raise RuntimeError(f"TAP query failed: HTTP {response.status_code}: "
                               f"{response.text[:500]}")
        content_type = response.headers.get("content-type", "")
        if "csv" not in content_type and "text" not in content_type:
            raise RuntimeError(f"TAP returned unexpected content type {content_type!r}")
        digest = hashlib.sha256()
        rows = -1  # header
        with output_path.open("wb") as destination:
            for chunk in response.iter_content(chunk_size=1 << 20):
                destination.write(chunk)
                digest.update(chunk)
                rows += chunk.count(b"\n")
    if output_path.stat().st_size == 0:
        raise RuntimeError("TAP returned an empty response")
    with output_path.open("rb") as check:
        head = check.read(200).decode("utf-8", "replace")
    if head.lstrip().startswith("<"):
        raise RuntimeError(f"TAP returned an error document instead of CSV: {head!r}")
    manifest = {
        "url": url,
        "query": query,
        "format": "csv",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": digest.hexdigest(),
        "bytes": output_path.stat().st_size,
        "approx_rows": max(rows, 0),
    }
    output_path.with_suffix(output_path.suffix + ".json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


# ----------------------------------------------------------------------- readers

def _read_csv_like(path):
    """Read CSV or ECSV (``#`` comment header) with pyarrow, all columns as strings."""
    from pyarrow import csv as pacsv

    with Path(path).open("rb") as handle:
        prefix = handle.read(4096)
    skip = 0
    if prefix.lstrip().startswith(b"#"):
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lstrip().startswith("#"):
                    skip += 1
                else:
                    break
    read_options = pacsv.ReadOptions(skip_rows=skip)
    convert_options = pacsv.ConvertOptions(
        null_values=["", "null", "NULL", "NaN", "nan", "--"], strings_can_be_null=True)
    return pacsv.read_csv(path, read_options=read_options, convert_options=convert_options)


def _read_astropy_table(path, fmt=None):
    """Read VOTable / FITS / other astropy-supported tables into a pyarrow Table."""
    try:
        from astropy.table import Table
    except ImportError as error:  # pragma: no cover - environment specific
        raise RuntimeError("astropy is required to read VOTable/FITS Gaia files") from error
    table = Table.read(path, format=fmt) if fmt else Table.read(path)
    columns = {}
    for name in table.colnames:
        column = table[name]
        values = column.filled(None).tolist() if hasattr(column, "filled") else column.tolist()
        cleaned = []
        for value in values:
            if isinstance(value, bytes):
                value = value.decode("utf-8", "replace")
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            cleaned.append(value)
        columns[name.lower()] = cleaned
    return pa.table(columns)


def read_gaia_file(path):
    """Dispatch on file extension; returns a pyarrow Table with lower-case column names."""
    path = Path(path)
    suffixes = [suffix.lower() for suffix in path.suffixes]
    name = path.name.lower()
    if name.endswith(".ecsv"):
        # ECSV carries its own dialect in the YAML header (astropy writes it
        # space-delimited); let astropy honour it when available.
        try:
            return _read_astropy_table(path, "ascii.ecsv")
        except RuntimeError:
            pass
    if name.endswith((".csv", ".csv.gz", ".ecsv", ".txt")):
        table = _read_csv_like(path)
        return table.rename_columns([column.lower() for column in table.column_names])
    if name.endswith((".vot", ".votable", ".xml", ".vot.gz", ".xml.gz")):
        return _read_astropy_table(path, "votable")
    if name.endswith((".fits", ".fit", ".fits.gz", ".fit.gz")):
        return _read_astropy_table(path, "fits")
    if name.endswith(".parquet"):
        table = pq.read_table(path)
        return table.rename_columns([column.lower() for column in table.column_names])
    raise ValueError(f"unsupported Gaia input format: {path.name} (suffixes {suffixes})")


# --------------------------------------------------------------------- normalize

def _float_column(table, name):
    if name not in table.column_names:
        return pa.nulls(table.num_rows, pa.float64())
    column = table[name]
    if pa.types.is_string(column.type) or pa.types.is_large_string(column.type):
        column = pc.cast(pc.if_else(pc.equal(pc.utf8_trim_whitespace(column), ""), None, column),
                         pa.float64())
    else:
        column = pc.cast(column, pa.float64())
    finite = pc.and_(pc.is_finite(column), pc.is_valid(column))
    return pc.if_else(finite, column, pa.scalar(None, pa.float64())).combine_chunks()


def _string_column(table, name):
    if name not in table.column_names:
        return pa.nulls(table.num_rows, pa.string())
    column = pc.cast(table[name], pa.string())
    trimmed = pc.utf8_trim_whitespace(column)
    return pc.if_else(pc.equal(trimmed, ""), None, trimmed).combine_chunks()


def _int_column(table, name, bit_width=32):
    target = pa.int64() if bit_width == 64 else pa.int32()
    if name not in table.column_names:
        return pa.nulls(table.num_rows, target)
    column = table[name]
    if pa.types.is_string(column.type) or pa.types.is_large_string(column.type):
        column = pc.if_else(pc.equal(pc.utf8_trim_whitespace(column), ""), None, column)
        column = pc.cast(column, pa.float64())
    if pa.types.is_floating(column.type):
        column = pc.round(column)
    return pc.cast(column, target).combine_chunks()


def _galactic(ra_deg, dec_deg):
    """Equatorial (ICRS) -> Galactic l/b using the IAU 1958 rotation (same matrix as RECONS)."""
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    cos_dec = math.cos(dec)
    x = cos_dec * math.cos(ra)
    y = cos_dec * math.sin(ra)
    z = math.sin(dec)
    gx = -0.0548755604 * x - 0.8734370902 * y - 0.4838350155 * z
    gy = 0.4941094279 * x - 0.4448296300 * y + 0.7469822445 * z
    gz = -0.8676661490 * x - 0.1980763734 * y + 0.4559837762 * z
    longitude = math.degrees(math.atan2(gy, gx)) % 360
    latitude = math.degrees(math.asin(max(-1.0, min(1.0, gz))))
    return longitude, latitude


def normalize_gaia_table(table, source_file, min_parallax_over_error=5.0,
                         min_parallax_mas=None):
    """Turn a raw Gaia table into rows matching ``GAIA_SUBSET_SCHEMA``.

    Returns ``(records, counts)``. Rows with null/invalid ``source_id``, ``ra``,
    ``dec`` or ``parallax`` are dropped and counted; nothing else is filtered
    unless ``min_parallax_mas`` is given.
    """
    missing = [name for name in NORMALIZE_REQUIRED_COLUMNS if name not in table.column_names]
    if missing:
        raise ValueError(f"{source_file}: Gaia input is missing columns: {', '.join(missing)}")

    source_id = _int_column(table, "source_id", 64).to_pylist()
    designation = _string_column(table, "designation").to_pylist()
    ra = _float_column(table, "ra").to_pylist()
    dec = _float_column(table, "dec").to_pylist()
    ra_error = _float_column(table, "ra_error").to_pylist()
    dec_error = _float_column(table, "dec_error").to_pylist()
    epoch = _float_column(table, "ref_epoch").to_pylist()
    parallax = _float_column(table, "parallax").to_pylist()
    parallax_error = _float_column(table, "parallax_error").to_pylist()
    parallax_over_error = _float_column(table, "parallax_over_error").to_pylist()
    pmra = _float_column(table, "pmra").to_pylist()
    pmra_error = _float_column(table, "pmra_error").to_pylist()
    pmdec = _float_column(table, "pmdec").to_pylist()
    pmdec_error = _float_column(table, "pmdec_error").to_pylist()
    rv = _float_column(table, "radial_velocity").to_pylist()
    rv_error = _float_column(table, "radial_velocity_error").to_pylist()
    ruwe = _float_column(table, "ruwe").to_pylist()
    g_mag = _float_column(table, "phot_g_mean_mag").to_pylist()
    bp_mag = _float_column(table, "phot_bp_mean_mag").to_pylist()
    rp_mag = _float_column(table, "phot_rp_mean_mag").to_pylist()
    bp_rp = _float_column(table, "bp_rp").to_pylist()
    variable = _string_column(table, "phot_variable_flag").to_pylist()
    non_single = _int_column(table, "non_single_star").to_pylist()
    teff = _float_column(table, "teff_gspphot").to_pylist()
    logg = _float_column(table, "logg_gspphot").to_pylist()
    mh = _float_column(table, "mh_gspphot").to_pylist()
    dist_gspphot = _float_column(table, "distance_gspphot").to_pylist()
    gal_l = _float_column(table, "l").to_pylist()
    gal_b = _float_column(table, "b").to_pylist()

    counts = {"input": table.num_rows, "dropped_invalid": 0, "dropped_parallax_cut": 0,
              "inverse_parallax": 0, "gspphot": 0, "none": 0}
    records = []
    for index in range(table.num_rows):
        sid = source_id[index]
        if sid is None or sid <= 0 or ra[index] is None or dec[index] is None \
                or parallax[index] is None:
            counts["dropped_invalid"] += 1
            continue
        if not (0 <= ra[index] < 360 and -90 <= dec[index] <= 90):
            counts["dropped_invalid"] += 1
            continue
        if min_parallax_mas is not None and parallax[index] <= min_parallax_mas:
            counts["dropped_parallax_cut"] += 1
            continue

        plx = parallax[index]
        plx_err = parallax_error[index]
        if plx_err is not None and plx_err < 0:
            plx_err = None
        snr = parallax_over_error[index]
        if snr is None and plx_err:
            snr = plx / plx_err

        distance = None
        mode = "none"
        if plx > 0 and snr is not None and snr >= min_parallax_over_error:
            distance = 1000.0 / plx
            mode = "inverse_parallax"
        elif dist_gspphot[index] is not None and dist_gspphot[index] > 0:
            distance = dist_gspphot[index]
            mode = "gspphot"
        counts[mode] += 1

        if gal_l[index] is not None and gal_b[index] is not None:
            longitude, latitude = gal_l[index] % 360, gal_b[index]
        else:
            longitude, latitude = _galactic(ra[index], dec[index])

        x = y = z = None
        if distance is not None:
            ra_rad = math.radians(ra[index])
            dec_rad = math.radians(dec[index])
            x = distance * math.cos(dec_rad) * math.cos(ra_rad)
            y = distance * math.cos(dec_rad) * math.sin(ra_rad)
            z = distance * math.sin(dec_rad)

        records.append({
            "id": f"gaia-dr3:{sid}",
            "gaia_dr3_source_id": sid,
            "designation": designation[index] or f"Gaia DR3 {sid}",
            "ra_deg": ra[index],
            "dec_deg": dec[index],
            "ra_error_mas": ra_error[index],
            "dec_error_mas": dec_error[index],
            "ref_epoch_jyear": epoch[index] if epoch[index] is not None else 2016.0,
            "parallax_mas": plx,
            "parallax_error_mas": plx_err,
            "parallax_over_error": snr,
            "pmra_mas_per_year": pmra[index],
            "pmra_error_mas_per_year": pmra_error[index],
            "pmdec_mas_per_year": pmdec[index],
            "pmdec_error_mas_per_year": pmdec_error[index],
            "radial_velocity_km_s": rv[index],
            "radial_velocity_error_km_s": rv_error[index],
            "ruwe": ruwe[index],
            "phot_g_mean_mag": g_mag[index],
            "phot_bp_mean_mag": bp_mag[index],
            "phot_rp_mean_mag": rp_mag[index],
            "bp_rp": bp_rp[index],
            "phot_variable_flag": variable[index],
            "non_single_star": non_single[index],
            "teff_gspphot_k": teff[index],
            "logg_gspphot": logg[index],
            "mh_gspphot": mh[index],
            "distance_gspphot_pc": dist_gspphot[index],
            "distance_pc": distance,
            "distance_ly": distance * LIGHT_YEARS_PER_PARSEC if distance is not None else None,
            "distance_mode": mode,
            "x_pc": x,
            "y_pc": y,
            "z_pc": z,
            "galactic_longitude_deg": longitude,
            "galactic_latitude_deg": latitude,
            "source_file": str(source_file),
            "source_catalog": "Gaia DR3",
        })
    return records, counts


def _discover_inputs(inputs, raw_dir):
    paths = [Path(path) for path in inputs]
    if raw_dir is not None:
        raw_dir = Path(raw_dir)
        patterns = ("*.csv", "*.csv.gz", "*.ecsv", "*.vot", "*.votable", "*.xml",
                    "*.fits", "*.fit", "*.fits.gz", "*.parquet")
        for pattern in patterns:
            for path in sorted(raw_dir.glob(pattern)):
                if "recons" in path.name.lower():
                    continue  # RECONS snapshots live in the same raw/ directory
                if path not in paths:
                    paths.append(path)
    if not paths:
        raise ValueError("no Gaia input files given; pass paths or --raw-dir gaia_datasets/raw")
    return paths


def build_gaia_subset(inputs, output, raw_dir=None, min_parallax_over_error=5.0,
                      min_parallax_mas=None, dedupe=True):
    """Normalize all Gaia inputs into one Parquet file; returns per-file counts."""
    paths = _discover_inputs(inputs, raw_dir)
    all_records = []
    per_file = {}
    for path in paths:
        table = read_gaia_file(path)
        records, counts = normalize_gaia_table(
            table, path.name, min_parallax_over_error=min_parallax_over_error,
            min_parallax_mas=min_parallax_mas)
        per_file[str(path)] = counts
        all_records.extend(records)

    duplicates = 0
    if dedupe:
        seen = {}
        for record in all_records:
            key = record["gaia_dr3_source_id"]
            if key in seen:
                duplicates += 1
                # Prefer the row with the smaller parallax error (or the first one).
                current = seen[key]
                if (record["parallax_error_mas"] or math.inf) < (current["parallax_error_mas"] or math.inf):
                    seen[key] = record
            else:
                seen[key] = record
        all_records = sorted(seen.values(), key=lambda row: row["gaia_dr3_source_id"])

    table = pa.Table.from_pylist(all_records, schema=GAIA_SUBSET_SCHEMA)
    table.validate(full=True)
    table = table.replace_schema_metadata({
        b"source_catalog": b"Gaia DR3 (gaiadr3.gaia_source), ESA/Gaia/DPAC",
        b"source_files": json.dumps([Path(p).name for p in paths]).encode(),
        b"generated_on": date.today().isoformat().encode(),
        b"row_count": str(table.num_rows).encode(),
        b"duplicates_removed": str(duplicates).encode(),
        b"distance_policy": (
            f"distance_pc = 1000/parallax when parallax > 0 and parallax_over_error >= "
            f"{min_parallax_over_error:g} (distance_mode=inverse_parallax); else GSP-Phot "
            f"distance (gspphot); else null (none)").encode(),
        b"coordinate_frame": b"ICRS, epoch 2016.0; XYZ heliocentric equatorial parsecs; "
                             b"l/b from Gaia when present else IAU 1958 rotation",
        b"schema_doc": b"docs/data-schemas.md#gaia_dr3_subsetparquet",
    })
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output, compression="zstd")
    return {"files": per_file, "rows_written": table.num_rows, "duplicates_removed": duplicates}


# ------------------------------------------------------------ legacy prototype

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


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="download a Gaia DR3 subset via TAP sync")
    fetch.add_argument("--min-parallax", type=float, default=DEFAULT_MIN_PARALLAX_MAS,
                       help="parallax lower bound in mas for the default query (default 40 = 25 pc)")
    fetch.add_argument("--adql", help="custom ADQL query overriding the default")
    fetch.add_argument("--output", type=Path,
                       help="raw CSV path (default gaia_datasets/raw/gaia_dr3_plx_gt_<N>.csv)")
    fetch.add_argument("--url", default=TAP_SYNC_URL)
    fetch.add_argument("--timeout", type=float, default=600)

    normalize = subparsers.add_parser(
        "normalize", help="normalize raw Gaia files (CSV/ECSV/VOTable/FITS/Parquet) to Parquet")
    normalize.add_argument("inputs", nargs="*", type=Path, help="raw Gaia files")
    normalize.add_argument("--raw-dir", type=Path,
                           help="also ingest every Gaia file found in this directory")
    normalize.add_argument("--output", type=Path,
                           default=Path("gaia_datasets/gaia_dr3_subset.parquet"))
    normalize.add_argument("--min-parallax-over-error", type=float, default=5.0,
                           help="gate for inverse-parallax distances (default 5)")
    normalize.add_argument("--min-parallax", type=float,
                           help="optional strict lower bound on parallax (mas) applied to inputs")
    normalize.add_argument("--keep-duplicates", action="store_true",
                           help="do not deduplicate repeated source_ids across files")

    legacy = subparsers.add_parser("catalog", help="legacy: build a CLI catalog dir from a CSV chunk")
    legacy.add_argument("input", type=Path)
    legacy.add_argument("--output", type=Path, required=True)
    legacy.add_argument("--max-ruwe", type=float)

    arguments = parser.parse_args(argv)

    if arguments.command == "fetch":
        query = arguments.adql or default_adql(arguments.min_parallax)
        output = arguments.output or Path(
            f"gaia_datasets/raw/gaia_dr3_plx_gt_{arguments.min_parallax:g}.csv")
        try:
            manifest = fetch_tap(query, output, url=arguments.url, timeout=arguments.timeout)
        except Exception as error:  # network errors, HTTP errors, malformed replies
            parser.error(f"fetch failed: {error}")
        print(f"Saved {manifest['bytes']} bytes (~{manifest['approx_rows']} rows) to {output}",
              file=sys.stderr)
        print(f"Manifest: {output}.json", file=sys.stderr)
        return

    if arguments.command == "normalize":
        try:
            summary = build_gaia_subset(
                arguments.inputs, arguments.output, raw_dir=arguments.raw_dir,
                min_parallax_over_error=arguments.min_parallax_over_error,
                min_parallax_mas=arguments.min_parallax, dedupe=not arguments.keep_duplicates)
        except (OSError, ValueError, RuntimeError, pa.ArrowException) as error:
            parser.error(str(error))
        for path, counts in summary["files"].items():
            print(f"{path}: {counts}", file=sys.stderr)
        print(f"Duplicates removed: {summary['duplicates_removed']}", file=sys.stderr)
        print(f"Rows written: {summary['rows_written']} -> {arguments.output}", file=sys.stderr)
        return

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
