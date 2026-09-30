# gaia_datasets/ — the data warehouse directory

This directory holds every dataset the star-search tools read or write. **Only
this README and `.gitkeep` are tracked by git**; everything else is ignored via
`/gaia_datasets/*` in `.gitignore`. GitHub carries code, the VM carries data.
Column-level documentation lives in [`docs/data-schemas.md`](../docs/data-schemas.md).

## Layout

```
gaia_datasets/
├── raw/                                 # immutable downloads / drop-in exports
│   ├── recons_top100.htm                #   RECONS TOP100 page as fetched
│   ├── RECON_data.pdf                   #   RECONS PDF used only as a cross-check
│   ├── gaia_dr3_plx_gt_40.csv           #   Gaia DR3 TAP export, parallax > 40 mas
│   └── gaia_dr3_plx_gt_40.csv.json      #   sidecar manifest: ADQL, rows, bytes, sha256
├── recons_nearest.parquet               # 142 RECONS components / 100 systems (J2000)
├── recons_nearest.csv                   #   same table as CSV for eyeballing
├── recons_pdf_crosscheck.md             #   OCR cross-check of parallaxes vs the PDF
├── gaia_dr3_subset.parquet              # 5323 Gaia DR3 sources within ~25 pc (J2016.0)
├── merged_catalog.parquet               # 5356 rows: RECONS x Gaia positional cross-match
└── merge_report.md                      #   human-readable cross-match report
```

The CLI catalog (`stars.parquet`, `aliases.parquet`, `catalog.json`,
`recons_nearest.parquet`) is generated into `build/catalog/` (also git-ignored)
from `merged_catalog.parquet`.

## Regenerate from scratch

Run from the repository root with the project virtualenv
(`python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt`).

```sh
# 1. RECONS 100 nearest systems (HTML → Parquet, ~1 s)
.venv/bin/python tools/ingest_recons.py http://recons.org/TOP100.posted.htm \
  --output gaia_datasets/recons_nearest.parquet \
  --csv-output gaia_datasets/recons_nearest.csv

# 2. Gaia DR3 subset from the ESA TAP sync endpoint (parallax > 40 mas, ~15 s, ~1.9 MB)
.venv/bin/python tools/ingest_gaia.py fetch
.venv/bin/python tools/ingest_gaia.py normalize --raw-dir gaia_datasets/raw \
  --output gaia_datasets/gaia_dr3_subset.parquet

# 3. Cross-match (writes merged_catalog.parquet and merge_report.md)
.venv/bin/python tools/build_merged_catalog.py

# 4. CLI catalog directory
.venv/bin/python tools/build_catalog.py \
  --merged gaia_datasets/merged_catalog.parquet --output build/catalog
export STAR_SEARCH_DATA_DIR="$PWD/build/catalog"
build/star-search nearest 10
```

## Dropping in a larger Gaia export

`ingest_gaia.py normalize` is the integration point for big datasets. Any Gaia
DR3 `gaia_source` export can be placed in `gaia_datasets/raw/` and normalized
without touching code:

* Accepted formats (by extension): `.csv`, `.csv.gz`, `.ecsv`, `.txt`,
  `.vot`/`.votable`/`.xml` (+`.gz`), `.fits`/`.fit` (+`.gz`), `.parquet`.
* Required columns: `source_id`, `ra`, `dec`, `parallax`. Every other column
  listed in `docs/data-schemas.md` is optional and becomes null when absent.
  Leading `#` comment lines (Gaia archive bulk downloads) are skipped.
* Multiple files are concatenated and deduplicated on `source_id`
  (`--keep-duplicates` disables that).
* Optional cuts: `--min-parallax <mas>` (strict lower bound) and
  `--min-parallax-over-error <n>` (default 5; rows below it fall back to the
  GSP-Phot distance or a null distance, recorded in `distance_mode`).

```sh
# e.g. a 100 pc export in VOTable form plus a bulk CSV chunk
cp ~/Downloads/gaia_100pc.vot gaia_datasets/raw/
cp ~/Downloads/GaiaSource_000000-003111.csv.gz gaia_datasets/raw/
.venv/bin/python tools/ingest_gaia.py normalize --raw-dir gaia_datasets/raw \
  --output gaia_datasets/gaia_dr3_subset.parquet
.venv/bin/python tools/build_merged_catalog.py
.venv/bin/python tools/build_catalog.py \
  --merged gaia_datasets/merged_catalog.parquet --output build/catalog
```

Alternatively fetch a different volume directly:
`.venv/bin/python tools/ingest_gaia.py fetch --min-parallax 10` (100 pc), or pass
`--adql "SELECT … FROM gaiadr3.gaia_source WHERE …"` for a custom selection. TAP
sync requests are limited by ESA to a few million rows; for anything larger use
the Gaia archive's asynchronous download and drop the files in `raw/`.

The downstream steps (cross-match, CLI catalog, renderer, 3D map) only depend on
the Parquet schemas, so a larger subset flows through unchanged; expect the
cross-match to run in seconds for ≤ 10⁵ Gaia rows.

## Attribution

* Gaia: *This work has made use of data from the European Space Agency (ESA)
  mission Gaia (https://www.cosmos.esa.int/gaia), processed by the Gaia Data
  Processing and Analysis Consortium (DPAC).* Data license: CC BY-SA 3.0 IGO.
* RECONS: Research Consortium On Nearby Stars, http://www.recons.org — the 100
  nearest systems list accurate as of 2012-01-01. Cite RECONS and the per-entry
  references when publishing; the page states no explicit redistribution license.
