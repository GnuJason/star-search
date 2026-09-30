# star-search

An offline-first C CLI using embedded DuckDB to query a local Parquet star
catalog. Python owns catalog preparation; the runtime does not need Python.

**Status: data pipelines complete, CLI running on real data, deterministic
C/GLSL star-portrait renderer implemented; website and packaging pending.** The catalog behind the CLI is a positional cross-match of
the RECONS 100 nearest systems (2012 census, 142 components) with a Gaia DR3
subset (parallax > 40 mas, 5323 sources) — 5356 stars with per-row provenance.
It is a curated 25 pc neighbourhood, not a complete census; production RPMs are
not implemented.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/` | C11 CLI (`main.c`, `catalog.c`, `format.c`) using the DuckDB C API |
| `src/shaders/star.frag`, `star.vert` | Canonical GLSL ES 3.00 star-portrait model (reused by the web client) |
| `src/star_params.c`, `src/render.c` | Physical parameter derivation and the float32 CPU evaluator of `star.frag` |
| `src/third_party/` | Vendored `stb_image_write.h` v1.16 (public domain / MIT) |
| `tools/render_all.py` | Batch portrait renderer → `assets/stars/*.png` + `index.json` |
| `assets/stars/` | Generated portraits (git-ignored except `.gitkeep`) |
| `docs/renderer.md` | Renderer model, formulas, citations and determinism guarantees |
| `tools/ingest_recons.py` | RECONS HTML → `gaia_datasets/recons_nearest.parquet` |
| `tools/ingest_gaia.py` | Gaia DR3 TAP fetch + drop-in normalizer → `gaia_datasets/gaia_dr3_subset.parquet` |
| `tools/build_merged_catalog.py` | RECONS × Gaia cross-match → `gaia_datasets/merged_catalog.parquet` + `merge_report.md` |
| `tools/build_catalog.py` | Merged catalog (or synthetic fixture) → CLI catalog directory |
| `tools/crosscheck_recons_pdf.py` | OCR cross-check of RECONS parallaxes against the RECONS PDF |
| `gaia_datasets/` | Data warehouse (git-ignored; see [its README](gaia_datasets/README.md)) |
| `docs/data-schemas.md` | Column-level schema and provenance rules for every Parquet file |
| `docs/catalog-contract.md` | CLI catalog contract (stars/aliases/manifest, lookup rules, exit codes) |
| `docs/star-search.1` | Manual page |
| `tests/` | Python unit tests (run by ctest) and the CLI black-box suite |

## Data pipeline (real catalog)

```sh
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tools/ingest_recons.py http://recons.org/TOP100.posted.htm \
  --output gaia_datasets/recons_nearest.parquet --csv-output gaia_datasets/recons_nearest.csv
.venv/bin/python tools/ingest_gaia.py fetch            # ESA Gaia TAP, parallax > 40 mas
.venv/bin/python tools/ingest_gaia.py normalize --raw-dir gaia_datasets/raw \
  --output gaia_datasets/gaia_dr3_subset.parquet
.venv/bin/python tools/build_merged_catalog.py         # merged_catalog.parquet + merge_report.md
.venv/bin/python tools/build_catalog.py --merged gaia_datasets/merged_catalog.parquet \
  --output build/catalog
export STAR_SEARCH_DATA_DIR="$PWD/build/catalog"
build/star-search nearest 10
build/star-search info "Barnard's Star"
build/star-search star "GJ 65 A"                       # star == info
build/star-search coords Sirius
build/star-search --json info "Gaia DR3 762815470562110464"
build/star-search recons-nearest 5
build/star-search render "Proxima Centauri"            # assets/stars/5853498713190525696.png
build/star-search --json render --size 1024 -o /tmp/sirius.png Sirius
.venv/bin/python tools/render_all.py                    # all RECONS components (--subset all for 5356)
```

Portraits are deterministic: the same star and options give a byte-identical PNG.
The model, formulas and citations are in [docs/renderer.md](docs/renderer.md).

Larger Gaia exports (CSV/ECSV/VOTable/FITS/Parquet) drop into `gaia_datasets/raw/`
and flow through `normalize` unchanged — see `gaia_datasets/README.md`.

## Build and try

Requires a C11 compiler, CMake 3.20+, Python 3.10+ for development, and the DuckDB C
SDK (tested with 1.4.4). DuckDB must have Parquet and JSON support built in. The
application disables extension auto-installation and auto-loading, and disables
the HTTP filesystem. Missing required support produces a diagnostic.
Dependency installation needs network access unless dependencies are preinstalled;
building and querying do not download anything automatically.

Use your distribution's DuckDB development package, or unpack the official
DuckDB C SDK into `.deps/duckdb` and set `DUCKDB_ROOT` as below. SDK binaries must
match your architecture.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cmake -S . -B build -DDUCKDB_ROOT="$PWD/.deps/duckdb" \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python" -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build
ctest --test-dir build --output-on-failure
.venv/bin/python tools/build_catalog.py --fixture --output build/fixture
export STAR_SEARCH_DATA_DIR="$PWD/build/fixture"
build/star-search --catalog-info
build/star-search info near
build/star-search --json nearest 3
build/star-search coords 'Fixture Pair A'
build/star-search info 'Fixture Pair'
build/star-search
```

An ambiguous lookup exits with status 4 and shows stable IDs to select. Quote
multiword names. Search treats `%` and `_` literally, not as wildcards. An exact
stable ID wins over aliases; exact names/aliases win over substring matches.
`nearest` is nearest **within the installed catalog**, excluding unknown distances.
Coordinates are at the catalog reference epoch, not the current date.

JSON emits identifiers as strings and unknown values as null. Single lookups
produce objects; `nearest` produces an array. JSON distances use parsecs. Text
also shows light-years and light-days. Prompts and diagnostics use stderr.
The interactive form performs one lookup and exits; ambiguity is resolved by
running another lookup with a displayed ID.

## Catalog and installation

See [the versioned contract](docs/catalog-contract.md) for types, units, metadata,
alias rules, and exit codes. `STAR_SEARCH_DATA_DIR` selects a directory containing
`stars.parquet`, `aliases.parquet`, and `catalog.json`. Files must be local regular
files; paths containing glob characters (`*?[]`) are rejected.

With `CMAKE_INSTALL_PREFIX=/usr`, installation places the binary in `/usr/bin`,
the manual in `/usr/share/man/man1`, and documentation in the CMake doc directory.
The default catalog directory is `/usr/share/star-search`. CMake never installs
the synthetic fixture as production data.

The planned `star-search-data` package will own all three catalog files and source
attribution; `star-search` will depend on it and the distribution's DuckDB shared
library package. Exact openSUSE dependency names, licensing, and OBS builds must
be verified before publishing specs. No project license has been chosen yet.

## Gaia DR3 ingestion

`tools/ingest_gaia.py fetch` runs an ADQL query (`parallax > 40` mas by default,
`--min-parallax` or `--adql` to change it) against the ESA Gaia TAP sync endpoint
and stores the CSV plus a sidecar manifest (query, rows, bytes, SHA-256) in
`gaia_datasets/raw/`. `normalize` converts any Gaia export found there into
`gaia_dr3_subset.parquet`: it dedupes on `source_id`, keeps the raw Gaia
astrometry, photometry and GSP-Phot parameters, and derives distance, heliocentric
XYZ and Galactic coordinates. Distances are `1000 / parallax` when
`parallax_over_error >= 5` (`distance_mode = inverse_parallax`), else the GSP-Phot
distance (`gspphot`), else null (`none`); the mode is stored per row. Inversion is
acceptable here only because of the 40 mas / SNR selection — the naive estimator
carries no zero-point or prior correction.

The legacy `ingest_gaia.py catalog <chunk.csv> --output DIR [--max-ruwe]` form
still builds a CLI catalog directly from a bulk `GaiaSource_*.csv` chunk using the
original G < 16 / SNR > 5 cuts and GSP-Phot distances; it is kept for tests and
comparison but the merged catalog is the supported path.

## Cross-match and merged catalog

`tools/build_merged_catalog.py` propagates RECONS J2000 positions to J2016.0 with
RECONS proper motions and matches each component to Gaia sources within 30″ whose
parallax agrees within 20 %. Components sharing one printed RECONS coordinate are
paired to candidates by brightness rank; a 60″ wide pass catches wide secondaries;
a component whose only neighbour fails the parallax gate is linked as
`matched_parallax_conflict` with the Gaia parallax adopted. Current result: 107
matched + 2 conflict links (109 of 142 RECONS components, 90 of 100 systems),
33 RECONS-only rows (bright stars saturated in Gaia, unresolved companions, T
dwarfs), 5214 Gaia-only rows. Every row records `source_of_position`,
`source_of_parallax`, `source_of_name`, `source_of_proper_motion` and
`source_of_spectral_type`; `gaia_datasets/merge_report.md` lists the unmatched,
ambiguous and conflicting entries. Column meanings: `docs/data-schemas.md`.

## RECONS nearest systems

`tools/ingest_recons.py` extracts the fixed-width table from the original
[RECONS page](http://recons.org/TOP100.posted.htm) and writes normalized CSV and
Parquet. It preserves the 100 system ranks and stellar/substellar components,
excludes planet rows, converts J2000 RA/Dec to degrees, derives parsec distances
from the listed parallaxes, and writes heliocentric equatorial XYZ plus Galactic
coordinates. The source is explicitly a snapshot accurate as of 2012-01-01; it
is not a current nearest-star census, and the table’s parallax references vary by
entry.

```sh
.venv/bin/python tools/ingest_recons.py \
  http://recons.org/TOP100.posted.htm \
  --output gaia_datasets/recons_nearest.parquet \
  --csv-output gaia_datasets/recons_nearest.csv
.venv/bin/python tools/crosscheck_recons_pdf.py   # optional: OCR check vs gaia_datasets/raw/RECON_data.pdf
export STAR_SEARCH_DATA_DIR="$PWD/build/catalog"  # build_catalog.py --merged copies recons_nearest.parquet here
build/star-search recons-nearest
build/star-search --json recons-info "Proxima Centauri"
build/star-search --json recons-info "GJ 559"
```

`recons-nearest [N]` selects the first N ranked systems (default 100) and returns
all retained stellar components for those systems. `recons-info` accepts a CNS
name, component ID, or common name; multi-component matches are reported as
ambiguous. `nearest N` queries the merged catalog. RECONS and Gaia stay separate
Parquet files; they meet only in `merged_catalog.parquet`, where the adopted value
and its source are recorded side by side rather than one silently overwriting the
other. There is no website/frontend in this repository yet; `render NAME_OR_ID`
writes a deterministic portrait (see [docs/renderer.md](docs/renderer.md)).

The source page provides attribution and measurement references but no explicit
redistribution license. Review its terms and provide the required citation before
packaging or redistributing the generated dataset.

## Offline acceptance gate

Run tests in a fresh network namespace:

```sh
unshare --user --map-root-user --net ctest --test-dir build --output-on-failure
```

This needs unprivileged user namespaces. If the host disables them, use a VM or
container with networking disabled. Tests create fresh home directories and
check no extension cache appears. The release gate additionally requires an
actual networkless installation of both RPMs and command smoke tests; development
tests alone do not prove that packaging gate.

Next milestones: the Next.js site (reusing `src/shaders/star.frag` and serving
`assets/stars/` with `index.json`) and WebGPU 3D map reading the same
Parquet files, review of attribution and redistribution terms, and a production
data package. Mass/luminosity estimation, `--raw`, unit flags, and online
enrichment are deferred.