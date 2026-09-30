#!/usr/bin/env python3
"""Batch-render star portraits with the star-search CLI.

Renders every star of a CLI catalog (or only the RECONS-nearest subset) into
assets/stars/ by invoking ``star-search --json render <stable id>`` per star,
and writes ``assets/stars/index.json`` mapping catalog ids to portrait files
and the physical parameters used (consumed by the Phase 3 website).

Examples:
    .venv/bin/python tools/render_all.py                      # RECONS subset (~142 stars)
    .venv/bin/python tools/render_all.py --subset all --jobs 4
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]


def select_ids(catalog_dir: Path, subset: str, limit: int | None) -> list[str]:
    stars = catalog_dir / "stars.parquet"
    where = "WHERE contains(lower(coalesce(source_catalog, '')), 'recons')" if subset == "recons" else ""
    sql = f"SELECT id FROM read_parquet(?) {where} ORDER BY distance_pc NULLS LAST, id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [row[0] for row in duckdb.execute(sql, [str(stars)]).fetchall()]


def render_one(binary: Path, env: dict, identifier: str, size: int) -> dict:
    completed = subprocess.run(
        [str(binary), "--json", "render", "--size", str(size), "--", identifier],
        env=env, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"error": "invalid_output", "message": completed.stderr.strip()}
    payload["exit_code"] = completed.returncode
    payload.setdefault("id", identifier)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--binary", type=Path, default=ROOT / "build" / "star-search")
    parser.add_argument("--catalog-dir", type=Path, default=ROOT / "build" / "catalog")
    parser.add_argument("--assets-dir", type=Path, default=ROOT / "assets" / "stars")
    parser.add_argument("--subset", choices=("recons", "all"), default="recons")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args(argv)

    if not args.binary.is_file():
        parser.error(f"binary not found: {args.binary} (build with cmake first)")
    ids = select_ids(args.catalog_dir, args.subset, args.limit)
    env = dict(os.environ, STAR_SEARCH_DATA_DIR=str(args.catalog_dir.resolve()),
               STAR_SEARCH_ASSETS_DIR=str(args.assets_dir.resolve()))
    args.assets_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(lambda i: render_one(args.binary, env, i, args.size), ids))

    failures = [r for r in results if r["exit_code"] != 0]
    index = {
        "schema_version": 1,
        "renderer": "star-search render (CPU evaluator of src/shaders/star.frag)",
        "subset": args.subset,
        "size": args.size,
        "portraits": {
            r["id"]: {
                "file": Path(r["output"]).name,
                "name": r.get("name"),
                "gaia_dr3_source_id": r.get("gaia_dr3_source_id"),
                "parameters": r.get("parameters"),
            }
            for r in results if r["exit_code"] == 0
        },
    }
    (args.assets_dir / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    total = sum((args.assets_dir / v["file"]).stat().st_size for v in index["portraits"].values())
    print(f"Rendered {len(index['portraits'])}/{len(ids)} portraits into {args.assets_dir} "
          f"({total / 1e6:.1f} MB); failures: {len(failures)}")
    for failure in failures:
        print(f"  {failure['id']}: {failure.get('error')} {failure.get('message', '')}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
