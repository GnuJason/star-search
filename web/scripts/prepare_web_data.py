#!/usr/bin/env python3
"""Convert the star-search Parquet warehouse into static data for the website.

Reads (never modifies):
  gaia_datasets/merged_catalog.parquet   RECONS x Gaia DR3 cross-match (the catalog)
  gaia_datasets/recons_nearest.parquet   RECONS 100 nearest systems (2012 snapshot)
  gaia_datasets/gaia_dr3_subset.parquet  normalized Gaia DR3 subset (row counts only)
  assets/stars/*.png + index.json        portraits from tools/render_all.py (optional)

Writes into web/public/data/ (git-ignored) and web/public/stars/ (git-ignored):
  manifest.json   provenance, row counts, field layout of points.bin
  points.bin      little-endian Float32Array, STRIDE floats per star (3D map)
  points.json     keys / names / RECONS system ranks aligned with points.bin
  stars.json      one detail record per star (server-side star cards + catalog)
  recons.json     RECONS systems with components linked to catalog keys
  ../stars/*.png  copied portraits

Every star gets the same shader parameters as the C renderer (web/scripts/star_params.py,
a port of src/star_params.c); the port is verified against assets/stars/index.json.
Re-running on an updated merged_catalog.parquet regenerates everything from scratch.

Usage:  .venv/bin/python web/scripts/prepare_web_data.py [--warehouse DIR] [--assets DIR] [--out DIR]
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import struct
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from star_params import derive_params  # noqa: E402

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
SCHEMA_VERSION = 1
POINT_FIELDS = ["x_pc", "y_pc", "z_pc", "teff_k", "radius_solar", "luminosity_solar", "flags"]
FLAG_RECONS, FLAG_GAIA, FLAG_PORTRAIT, FLAG_VARIABLE = 1, 2, 4, 8
PARITY_KEYS = ["teff_k", "radius_solar", "disk_radius_fraction", "limb_darkening_u1",
               "limb_darkening_u2", "granulation_amplitude", "granulation_frequency",
               "variability_amplitude", "seed"]


def clean(value):
    """JSON-safe scalar: NaN/inf -> None, big ints -> str, trimmed strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    text = str(value).strip()
    return text or None


def star_key(row):
    """URL key == portrait stem: Gaia source_id, else the sanitised stable ID (as the CLI)."""
    if row.get("gaia_source_id") is not None:
        return str(row["gaia_source_id"])
    return re.sub(r"[^A-Za-z0-9._-]", "-", row["id"])


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def aliases(row):
    lhs = clean(row.get("lhs_id"))
    if lhs and not lhs.upper().startswith("LHS"):
        lhs = f"LHS {lhs}"
    candidates = [row.get("common_name"), row.get("recons_name"), row.get("recons_system_name"),
                  lhs, row.get("recons_id"), row.get("gaia_designation")]
    seen = {(clean(row.get("primary_name")) or "").lower(), row["id"].lower()}
    out = []
    for alias in (clean(c) for c in candidates):
        if alias and alias.lower() not in seen:
            seen.add(alias.lower())
            out.append(alias)
    return out


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_parity(stars, index_path):
    """Compare the Python port with the C renderer's recorded parameters."""
    if not index_path.exists():
        return {"checked": 0, "mismatches": 0, "note": "assets/stars/index.json not found"}
    portraits = json.loads(index_path.read_text())["portraits"]
    by_id = {s["id"]: s for s in stars}
    checked, mismatches = 0, []
    for star_id, entry in portraits.items():
        star = by_id.get(star_id)
        if not star:
            continue
        checked += 1
        for key in PARITY_KEYS:
            want, got = entry["parameters"].get(key), star["render"].get(key)
            if want is None and got is None:
                continue
            if want is None or got is None or abs(float(want) - float(got)) > 1e-6 * max(1.0, abs(float(want))):
                mismatches.append(f"{star_id}.{key}: C={want} py={got}")
    return {"checked": checked, "mismatches": len(mismatches), "examples": mismatches[:5]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--warehouse", type=Path, default=ROOT / "gaia_datasets")
    parser.add_argument("--assets", type=Path, default=ROOT / "assets" / "stars")
    parser.add_argument("--out", type=Path, default=WEB / "public" / "data")
    parser.add_argument("--portraits-out", type=Path, default=WEB / "public" / "stars")
    parser.add_argument("--strict-parity", action="store_true",
                        help="exit non-zero if the parameter port disagrees with index.json")
    args = parser.parse_args(argv)

    merged_path = args.warehouse / "merged_catalog.parquet"
    recons_path = args.warehouse / "recons_nearest.parquet"
    gaia_path = args.warehouse / "gaia_dr3_subset.parquet"
    for required in (merged_path, recons_path):
        if not required.exists():
            parser.error(f"missing {required}; run the data pipeline first (docs/data-schemas.md)")

    merged_table = pq.read_table(merged_path)
    merged = merged_table.to_pylist()
    recons = pq.read_table(recons_path).to_pylist()
    gaia_rows = pq.ParquetFile(gaia_path).metadata.num_rows if gaia_path.exists() else None

    # Portraits: copy whatever exists; missing ones fall back to the live shader / placeholder.
    args.portraits_out.mkdir(parents=True, exist_ok=True)
    for stale in args.portraits_out.glob("*.png"):
        stale.unlink()
    available = set()
    if args.assets.is_dir():
        for png in args.assets.glob("*.png"):
            shutil.copy2(png, args.portraits_out / png.name)
            available.add(png.stem)

    stars = []
    for row in merged:
        if row.get("x_pc") is None or row.get("distance_pc") is None:
            continue  # the 3D map and distance-sorted views need a position
        key = star_key(row)
        detail = {name: clean(value) for name, value in row.items()}
        if row.get("gaia_source_id") is not None:
            detail["gaia_source_id"] = str(row["gaia_source_id"])  # exceeds 2^53
        render = derive_params(
            identifier=row["id"], source_id=row.get("gaia_source_id"),
            spectral_type=clean(row.get("spectral_type")), teff_k=clean(row.get("teff_gspphot_k")),
            bp_rp=clean(row.get("bp_rp")), phot_g_mean_mag=clean(row.get("phot_g_mean_mag")),
            parallax_mas=clean(row.get("parallax_mas")), absolute_v_mag=clean(row.get("absolute_mag")),
            variable_flag=clean(row.get("phot_variable_flag")))
        detail.update(key=key, aliases=aliases(row),
                      portrait=f"/stars/{key}.png" if key in available else None,
                      recons_slug=slugify(row.get("recons_system_name")) or None, render=render)
        stars.append(detail)
    stars.sort(key=lambda s: (s["distance_pc"], s["id"]))

    parity = verify_parity(stars, args.assets / "index.json")
    if parity["mismatches"]:
        print(f"WARNING: parameter port disagrees with the C renderer: {parity}", file=sys.stderr)
        if args.strict_parity:
            return 1

    # points.bin: little-endian float32, aligned with points.json keys.
    args.out.mkdir(parents=True, exist_ok=True)
    stride = len(POINT_FIELDS)
    with open(args.out / "points.bin", "wb") as handle:
        for s in stars:
            flags = ((FLAG_RECONS if s.get("recons_id") else 0) | (FLAG_GAIA if s.get("gaia_source_id") else 0)
                     | (FLAG_PORTRAIT if s["portrait"] else 0) | (FLAG_VARIABLE if s["render"]["variable"] else 0))
            r = s["render"]
            handle.write(struct.pack(f"<{stride}f", s["x_pc"], s["y_pc"], s["z_pc"], r["teff_k"],
                                     r["radius_solar"], r["luminosity_solar"] or 0.0, float(flags)))
    points = {"count": len(stars), "stride": stride, "fields": POINT_FIELDS,
              "keys": [s["key"] for s in stars],
              "names": [s.get("primary_name") for s in stars],
              "spectral_types": [s.get("spectral_type") for s in stars],
              "distances_pc": [round(s["distance_pc"], 4) for s in stars]}
    (args.out / "points.json").write_text(json.dumps(points, separators=(",", ":")))
    (args.out / "stars.json").write_text(json.dumps(stars, separators=(",", ":")))

    # RECONS systems, components linked to catalog stars through recons_id.
    by_recons = {s["recons_id"]: s for s in stars if s.get("recons_id")}
    systems = {}
    for row in sorted(recons, key=lambda r: (r["system_rank"], r["id"])):
        rank = row["system_rank"]
        system = systems.setdefault(rank, {
            "rank": rank, "cns_name": clean(row["cns_name"]), "slug": slugify(row["cns_name"]),
            "system_name": clean(row["system_name"]), "common_name": None,
            "distance_pc": clean(row["distance_pc"]), "distance_ly": clean(row["distance_ly"]),
            "planet_count": 0, "components": []})
        star = by_recons.get(row["id"])
        component = {name: clean(value) for name, value in row.items() if name != "source_line"}
        component.update(star_key=star["key"] if star else None,
                         portrait=star["portrait"] if star else None,
                         match_status=star.get("match_status") if star else None,
                         teff_k=star["render"]["teff_k"] if star else None)
        system["components"].append(component)
        system["common_name"] = system["common_name"] or clean(row.get("common_name"))
        system["planet_count"] = max(system["planet_count"], row.get("planet_count") or 0)
    recons_out = list(systems.values())
    (args.out / "recons.json").write_text(json.dumps(recons_out, separators=(",", ":")))

    meta = {k.decode(): v.decode() for k, v in (merged_table.schema.metadata or {}).items()
            if k != b"ARROW:schema"}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_on": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "merged_catalog": {"file": merged_path.name, "rows": len(merged), "sha256": sha256(merged_path)},
            "recons_nearest": {"file": recons_path.name, "rows": len(recons), "systems": len(recons_out)},
            "gaia_dr3_subset": {"file": gaia_path.name, "rows": gaia_rows},
        },
        "merged_catalog_metadata": meta,
        "counts": {
            "stars": len(stars),
            "skipped_without_position": len(merged) - len(stars),
            "recons_linked": sum(1 for s in stars if s.get("recons_id")),
            "gaia": sum(1 for s in stars if s.get("gaia_source_id")),
            "portraits": sum(1 for s in stars if s["portrait"]),
            "variables": sum(1 for s in stars if s["render"]["variable"]),
        },
        "points": {"file": "points.bin", "dtype": "float32", "endianness": "little",
                   "stride": stride, "fields": POINT_FIELDS,
                   "flags": {"recons": FLAG_RECONS, "gaia": FLAG_GAIA, "portrait": FLAG_PORTRAIT,
                             "variable": FLAG_VARIABLE}},
        "render_parameter_parity": parity,
        "attribution": "ESA/Gaia/DPAC (Gaia DR3); RECONS 100 Nearest Star Systems (2012-01-01).",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(stars)} stars, {len(recons_out)} RECONS systems, "
          f"{manifest['counts']['portraits']} portraits to {args.out}; "
          f"parity {parity['checked']} checked / {parity['mismatches']} mismatches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
