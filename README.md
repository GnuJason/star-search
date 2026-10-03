# star-search

A C CLI for exploring a curated catalog of nearby stars, with a deterministic
C/GLSL star-portrait renderer. As of v1.0 the CLI is an API client: it queries
the live [starsearch.online](https://starsearch.online) HTTP API for catalog
data and renders portraits locally. The website is the single source of truth —
one catalog engine, served over one API, feeds both the web experience and the
CLI. Python owns offline catalog preparation; the CLI runtime needs neither
Python nor a local database.

**Status: live.** The website is deployed in production at
[starsearch.online](https://starsearch.online), the API-backed CLI runs against
it on real data, the deterministic C/GLSL renderer is implemented, and an
openSUSE RPM package is built from this tree (see [`packaging/`](packaging/README.md)).
The catalog behind the API is a positional cross-match of the RECONS 100 nearest
systems (2012 census, 142 components) with a Gaia DR3 subset (parallax > 40 mas,
5323 sources) — 5356 stars with per-row provenance. It is a curated 25 pc
neighbourhood, not a complete census.

A v2.0 release will add an **optional local backend** so the CLI can also run
fully offline against a local catalog; the backend seam already exists behind
`catalog.h` (see [v1.0 → v2.0](#v10--v20-roadmap)).

## Architecture at a glance

```
          offline data prep (Python + DuckDB)                 runtime
  ┌─────────────────────────────────────────────┐   ┌──────────────────────────┐
  RECONS + Gaia DR3  ─►  merged_catalog.parquet  ─►  starsearch.online API ◄── CLI (libcurl + cJSON)
        (tools/)            (gaia_datasets/)          (web/, Next.js)       └── render: local GLSL → PNG
                                                            ▲
                                                       web browser UI
```

DuckDB is a **build-time** warehouse/prep engine used only by the `tools/`
pipeline on a maintainer's machine. It is not a dependency of the deployed
website (which serves pre-built JSON) nor of the CLI (which calls the API).
This is what keeps the engine uniform: the API is the one place catalog
semantics live, and both the web UI and the CLI consume it.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/` | C11 CLI (`main.c`, `catalog.c`, `format.c`, `result.c`) |
| `src/catalog.c` | v1.0 catalog backend: the starsearch.online JSON API (libcurl + cJSON) |
| `src/result.c`, `src/result.h` | Neutral result table that decouples formatting from the data source (the v2.0 local-backend seam) |
| `src/shaders/star.frag`, `star.vert` | Canonical GLSL ES 3.00 star-portrait model (reused by the web client) |
| `src/star_params.c`, `src/render.c` | Physical parameter derivation and the float32 CPU evaluator of `star.frag` |
| `src/third_party/` | Vendored `stb_image_write.h` v1.16 (public domain / MIT) |
| `packaging/` | openSUSE RPM spec + submission notes for the API-backed CLI ([README](packaging/README.md)) |
| `tools/render_all.py` | Batch portrait renderer → `assets/stars/*.png` + `index.json` |
| `assets/stars/` | Generated portraits (git-ignored except `.gitkeep`) |
| `docs/renderer.md` | Renderer model, formulas, citations and determinism guarantees |
| `tools/ingest_recons.py` | RECONS HTML → `gaia_datasets/recons_nearest.parquet` |
| `tools/ingest_gaia.py` | Gaia DR3 TAP fetch + drop-in normalizer → `gaia_datasets/gaia_dr3_subset.parquet` |
| `tools/build_merged_catalog.py` | RECONS × Gaia cross-match → `gaia_datasets/merged_catalog.parquet` + `merge_report.md` |
| `tools/build_catalog.py` | Merged catalog (or synthetic fixture) → CLI catalog directory (feeds web data prep / v2.0 local backend) |
| `tools/crosscheck_recons_pdf.py` | OCR cross-check of RECONS parallaxes against the RECONS PDF |
| `gaia_datasets/` | Data warehouse (git-ignored; see [its README](gaia_datasets/README.md)) |
| `docs/data-schemas.md` | Column-level schema and provenance rules for every Parquet file |
| `docs/catalog-contract.md` | Catalog contract (stars/aliases/manifest, lookup rules, exit codes) |
| `docs/star-search.1` | Manual page |
| `tests/` | Python unit tests (run by ctest) and the CLI black-box suite |
| `web/` | Next.js + Three.js website — **live at [starsearch.online](https://starsearch.online)**; see [web/README.md](web/README.md) |
| `web/scripts/prepare_web_data.py` | Parquet warehouse + portraits → `web/public/data/` and `web/public/stars/` (git-ignored) |

## Build and try the CLI

The CLI needs a C11 compiler, CMake 3.20+, and the development packages for
**libcurl** and **libcjson** (both found via pkg-config). It does not link
DuckDB. Python 3.10+ is required only for the development test suite and the
offline data-prep tools, not to build or run the CLI.

```sh
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build

# The CLI talks to the live API by default (https://starsearch.online).
build/star-search --catalog-info
build/star-search nearest 10
build/star-search info "Barnard's Star"
build/star-search star "GJ 65 A"                 # star == info
build/star-search coords Sirius
build/star-search --json info "Gaia DR3 762815470562110464"
build/star-search recons-nearest 5
build/star-search --json recons-info "Proxima Centauri"
build/star-search render "Proxima Centauri"      # assets/stars/5853498713190525696.png
build/star-search --json render --size 1024 -o /tmp/sirius.png Sirius
```

Point the CLI at another deployment (for example a staging site or a local web
dev server) with the `STAR_SEARCH_API_URL` environment variable:

```sh
export STAR_SEARCH_API_URL="http://localhost:3000"
build/star-search nearest 5
```

`STAR_SEARCH_API_URL` must be an `http(s)://` URL; the default is
`https://starsearch.online`. Catalog queries need network access to that
endpoint. Portrait rendering is always local and offline — it evaluates
`src/shaders/star.frag` on the CPU and writes a byte-identical PNG for the same
star and options. The model, formulas and citations are in
[docs/renderer.md](docs/renderer.md).

### Running the tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cmake -S . -B build -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build
ctest --test-dir build --output-on-failure
```

## Command reference

Synopsis: `star-search [--json] COMMAND [ARGS]`. With no command, the CLI prompts
for one star name or stable ID and performs a single lookup. All catalog queries
need network access to the API; portrait rendering is always local.

### Lookup commands

| Command | Description |
| --- | --- |
| `info NAME_OR_ID` | Identity, distance, coordinates, epoch and available photometry. Unknown fields print as `unknown` (`null` in JSON). |
| `star NAME_OR_ID` | Alias of `info`. |
| `coords NAME_OR_ID` | ICRS and Galactic coordinates in degrees and the reference epoch (not propagated to the current date). |
| `nearest N` | The nearest `N` entries with known positive distance. `N` is 1–10000; ties are ordered by stable ID. |
| `recons-nearest [N]` | RECONS components in the first `N` ranked systems. `N` is 1–100, default 100. This is the 2012 RECONS list, not a current census. |
| `recons-info NAME_OR_ID` | Look up a RECONS CNS name, common name, or component ID. |
| `render NAME_OR_ID` | Render a deterministic PNG portrait (see options below). |

### `render` options

| Option | Description |
| --- | --- |
| `--size PX` | Square image size, 16–4096 pixels, default 512. |
| `-o FILE`, `--output FILE` | Write the portrait to `FILE` instead of the default path; parent directories are created. |
| `--phase P` | Variability phase in `[0, 1]` for stars Gaia flags as VARIABLE, default 0; ignored for non-variable stars. |

The default output path is `$STAR_SEARCH_ASSETS_DIR/<gaia_source_id>.png`
(directory `assets/stars` when unset). Stars without a Gaia ID use their stable
ID with unsafe characters replaced by `-`. The same star with the same options
produces a byte-identical file.

### Info flags

| Flag | Description |
| --- | --- |
| `--json` | Machine-readable output: an object for a single lookup, an array for `nearest`/`recons-nearest`. IDs are strings, distances are in parsecs, errors are JSON objects. Prompts and diagnostics go to stderr. |
| `--catalog-info` | Source release, selection policy, attribution and limitations. |
| `--version` | Print the version without opening a catalog. |
| `--help` | Print command syntax without opening a catalog. |

### Environment variables

| Variable | Description |
| --- | --- |
| `STAR_SEARCH_API_URL` | Base URL of the catalog API. Must be an `http(s)://` URL; default `https://starsearch.online`. |
| `STAR_SEARCH_ASSETS_DIR` | Directory for default `render` output; default `assets/stars` relative to the working directory. |

### Exit status

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Runtime, catalog or file-write error |
| `2` | Invalid usage |
| `3` | No match |
| `4` | Ambiguous match (candidate stable IDs are shown; re-run with one) |

### Examples

```sh
star-search info "Barnard's Star"
star-search star "GJ 65 A"                        # star == info
star-search coords Sirius
star-search nearest 10
star-search recons-nearest 25
star-search recons-info "Proxima Centauri"
star-search --json nearest 5                      # JSON array to stdout
star-search render Betelgeuse --size 1024 --phase 0.3 -o betelgeuse.png
STAR_SEARCH_API_URL=http://localhost:3000 star-search info Vega
star-search --catalog-info
star-search --version
```

Quote names that contain spaces. An exact stable ID wins over exact names and
aliases, which win over literal substring matches.

## CLI behaviour

An ambiguous lookup exits with status 4 and shows stable IDs to select. Quote
multiword names. Search treats `%` and `_` literally, not as wildcards. An exact
stable ID wins over aliases; exact names/aliases win over substring matches.
`nearest` is nearest by distance, excluding unknown distances. Coordinates are
at the catalog reference epoch, not the current date.

JSON emits identifiers as strings and unknown values as null. Single lookups
produce objects; `nearest` produces an array. JSON distances use parsecs. Text
also shows light-years and light-days. Prompts and diagnostics use stderr.
The interactive form performs one lookup and exits; ambiguity is resolved by
running another lookup with a displayed ID. Human-readable `info`, `render`, and
interactive output end with a pointer to starsearch.online; `--json` output
(which the website itself consumes) stays machine-clean.

The command-to-endpoint mapping is: `info`/`star`/`coords` → `/api/star/:id`;
`nearest N` → `/api/stars?sort=distance&limit=N&full=1`; `recons-nearest` /
`recons-info` → `/api/nearest`; `--catalog-info` → `/api/catalog`; `render` →
`/api/star/:id` followed by a local GLSL render.

## Installation

star-search is a lightweight, API-backed CLI: at runtime it depends only on the
libcurl and libcjson shared libraries, ships no catalog data (the binary reaches
the catalog over the API), and needs no C++ toolchain. Building from source works
on any Linux distribution with a C11 compiler; RPM packaging inputs are provided
for openSUSE and other RPM-based systems.

Recommended installation methods:

1. **Build and install from source** — the primary, first-class method, supported
   on every Linux distribution with a C11 compiler, CMake 3.20+, and the libcurl
   and libcjson development packages. See
   [Build and install from source](#build-and-install-from-source).
2. **Source tarball** — a reproducible, dataset-free tarball for users who do not
   want to clone the repository. See
   [Install from the source tarball](#install-from-the-source-tarball).
3. **RPM package (openSUSE / RPM-based)** — build the RPM from the provided spec
   and install it. An openSUSE repository submission is in preparation; see
   [RPM installation](#rpm-installation).
4. **Debian / Ubuntu** — no `.deb` is currently provided; use the from-source
   method above, which builds against your system's own libraries.

Prebuilt downloads (source tarball, RPM, and source RPM) are published on the
[v1.0 GitHub Release](https://github.com/GnuJason/star-search/releases/tag/v1.0),
with `SHA256SUMS` for verification. No project APT or RPM *repository* is hosted
yet, so there is no `apt install star-search` or `zypper install star-search`
(from a repository) path at this time. The sections below describe exactly what
works today.

### Distribution support

- General Linux distributions: source build supported with the documented C11
  toolchain and dependencies (libcurl + libcjson development packages).
- openSUSE / RPM-based: the RPM spec in [`packaging/`](packaging/README.md) builds
  cleanly from the reproducible source tarball; submission to the openSUSE
  `utilities` devel project is in preparation and not yet in the official repos.
- Debian / Ubuntu: build from the source tarball or the repository; no `.deb`
  package is provided.

### Supported platforms

| Platform | Installation method |
| --- | --- |
| General Linux (any distro) | Source build with a C11 compiler, CMake 3.20+, pkg-config, libcurl, and libcjson development packages |
| openSUSE / RPM-based | Build the RPM from `packaging/star-search.spec`; official-repository submission in preparation |
| Debian / Ubuntu | Source build (no `.deb` provided); install `libcurl4-openssl-dev` and `libcjson-dev` |

star-search links only `libcurl.so.4` and `libcjson.so.1`, both widely packaged,
so the source build has no unusual dependency constraints. A trusted CA store is
needed at runtime for HTTPS catalog lookups; portrait rendering is fully local
and offline.

### Build and install from source

Install the build dependencies for your distribution.

Debian / Ubuntu:

```sh
sudo apt update
sudo apt install build-essential cmake pkg-config \
  libcurl4-openssl-dev libcjson-dev
```

Fedora / RHEL-family:

```sh
sudo dnf install gcc cmake pkgconf-pkg-config \
  libcurl-devel libcjson-devel
```

openSUSE:

```sh
sudo zypper install gcc cmake pkg-config \
  libcurl-devel libcjson-devel
```

Then configure, build, install, and verify:

```sh
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build
sudo cmake --install build
star-search --version
```

Build as your ordinary user; only the system-wide install step needs elevated
privileges. With `CMAKE_INSTALL_PREFIX=/usr` the install places the binary in
`/usr/bin`, the manual in `/usr/share/man/man1`, the GLSL shaders under
`/usr/share/star-search/shaders`, and the docs in the CMake doc directory. There
is no catalog data to install.

cJSON development headers must be discoverable by the compiler and pkg-config. If
`libcjson-dev` / `libcjson-devel` is unavailable on your distribution, install
cJSON with your distribution's equivalent package or the
[upstream cJSON build instructions](https://github.com/DaveGamble/cJSON#building);
a custom prefix may require setting `PKG_CONFIG_PATH`.

### Install from the source tarball

If you do not want to clone the repository, download the source tarball from the
[v1.0 release](https://github.com/GnuJason/star-search/releases/tag/v1.0) — it is
reproducible and dataset-free (`.gitattributes` strips the datasets, website, and
portraits, so only the C/GLSL CLI, its man page, shaders, and docs are included).
Download, verify, extract, build, and install:

```sh
wget https://github.com/GnuJason/star-search/releases/download/v1.0/star-search-1.0.tar.gz
wget https://github.com/GnuJason/star-search/releases/download/v1.0/SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing
tar -xvf star-search-1.0.tar.gz
cd star-search-1.0
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build
sudo cmake --install build
star-search --version
```

`wget` is only a download tool; a browser download from the release page works
too. If you already have the repository cloned, you can produce the identical
tarball yourself without the release:

```sh
git archive --format=tar.gz --prefix=star-search-1.0/ \
  -o star-search-1.0.tar.gz HEAD
```

### RPM installation

[`packaging/`](packaging/README.md) contains the openSUSE RPM spec and the OBS
submission notes. The spec builds `star-search` 1.0 against `pkgconfig(libcurl)`
and `pkgconfig(libcjson)` with no DuckDB or bundled dependencies — both libraries
are in openSUSE Factory, which is what makes the package submittable.

A prebuilt x86_64 RPM is attached to the
[v1.0 release](https://github.com/GnuJason/star-search/releases/tag/v1.0).
Download and install it:

```sh
wget https://github.com/GnuJason/star-search/releases/download/v1.0/star-search-1.0-1.x86_64.rpm
sudo zypper install ./star-search-1.0-1.x86_64.rpm # or: sudo rpm -i ./star-search-1.0-1.x86_64.rpm
star-search --version
```

`zypper install ./<file>.rpm` resolves runtime dependencies from your enabled
repositories; `rpm -i` does not. A source RPM (`star-search-1.0-1.src.rpm`) is
also attached for rebuilding on your own system.

To build the RPM yourself from the reproducible tarball instead:

```sh
cp packaging/star-search.spec ~/rpmbuild/SPECS/
git archive --format=tar.gz --prefix=star-search-1.0/ \
  -o ~/rpmbuild/SOURCES/star-search-1.0.tar.gz HEAD
rpmbuild -ba ~/rpmbuild/SPECS/star-search.spec     # add --nodeps on a non-openSUSE host
```

For other RPM-based distributions, rebuild from the tarball (or the source RPM)
with their equivalent libcurl and libcjson development packages.

#### openSUSE submission status

The RPM spec is maintained at
[`packaging/star-search.spec`](packaging/star-search.spec). Submission to the
openSUSE `utilities` devel project is in preparation and documented in
[`packaging/README.md`](packaging/README.md); the OBS steps require an openSUSE
account and are run by the maintainer. star-search is **not** yet in the official
openSUSE repositories, so `zypper install star-search` (from a repository) does
not work yet.

### Staged and user-local installation

Staged installation, without changing the host, using `DESTDIR`:

```sh
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build
DESTDIR="$PWD/stage" cmake --install build
test -x stage/usr/bin/star-search
```

User-local installation under `$HOME/.local` (no sudo):

```sh
cmake -S . -B build -DCMAKE_INSTALL_PREFIX="$HOME/.local"
cmake --build build
cmake --install build
"$HOME/.local/bin/star-search" --version
```

Put `$HOME/.local/bin` on your PATH when using a user-local install.

### Uninstall

CMake records every installed file in `build/install_manifest.txt`. Remove them
(use `sudo` for a system-wide prefix):

```sh
sudo xargs rm -v < build/install_manifest.txt
```

Then remove the now-empty `share/star-search` directory under your install prefix
to drop the installed shaders. An RPM install is removed with
`sudo rpm -e star-search` (or `sudo zypper remove star-search`).

## Offline data preparation (maintainer workflow)

The catalog served by the API is built offline from public sources with the
Python + DuckDB tooling in `tools/`. This runs on a maintainer's machine; end
users never touch it.

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
.venv/bin/python web/scripts/prepare_web_data.py       # warehouse + portraits → web/public/
.venv/bin/python tools/render_all.py                    # all RECONS components (--subset all for 5356)
```

The merged catalog directory (`build/catalog`) feeds `prepare_web_data.py`,
which generates the JSON the deployed site serves. The same directory is the
intended input for the forthcoming v2.0 local CLI backend. Larger Gaia exports
(CSV/ECSV/VOTable/FITS/Parquet) drop into `gaia_datasets/raw/` and flow through
`normalize` unchanged — see `gaia_datasets/README.md`.

### Gaia DR3 ingestion

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

### Cross-match and merged catalog

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

### RECONS nearest systems

`tools/ingest_recons.py` extracts the fixed-width table from the original
[RECONS page](http://recons.org/TOP100.posted.htm) and writes normalized CSV and
Parquet. It preserves the 100 system ranks and stellar/substellar components,
excludes planet rows, converts J2000 RA/Dec to degrees, derives parsec distances
from the listed parallaxes, and writes heliocentric equatorial XYZ plus Galactic
coordinates. The source is explicitly a snapshot accurate as of 2012-01-01; it
is not a current nearest-star census, and the table's parallax references vary by
entry. `recons-nearest [N]` selects the first N ranked systems (default 100) and
returns all retained stellar components; `recons-info` accepts a CNS name,
component ID, or common name (multi-component matches are reported as ambiguous).

The RECONS source page provides attribution and measurement references but no
explicit redistribution license. Review its terms and provide the required
citation before redistributing the generated dataset.

## The website

The website lives in [`web/`](web/README.md) and is **live in production at
[starsearch.online](https://starsearch.online)**: a Next.js App Router site that
runs `src/shaders/star.frag` verbatim in WebGL 2 (with a WGSL port for WebGPU),
a Three.js 3D map, the RECONS nearest-systems pages, and a catalog explorer. It
serves the catalog over the same HTTP API the CLI consumes, so the two clients
never diverge. Its data is generated by `web/scripts/prepare_web_data.py` from
the offline warehouse.

## v1.0 → v2.0 roadmap

- **v1.0 (current): API-backed CLI.** The CLI queries starsearch.online. This
  keeps one engine as the source of truth and ships a light openSUSE package
  (libcurl + libcjson only), with no DuckDB dependency.
- **v2.0: optional local backend.** Add an offline backend behind `catalog.h`
  (the `result.c` abstraction already isolates formatting from the data source)
  so the CLI can also run against a local catalog with no network. This pairs
  with the separate effort to get DuckDB into openSUSE Factory, which would let
  a local-backend build be packaged cleanly.

Deferred: mass/luminosity estimation, `--raw`, unit flags, and online
enrichment.
