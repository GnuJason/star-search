# star-search

An offline-first C CLI using embedded DuckDB to query a local Parquet star
catalog. Python owns catalog preparation; the runtime does not need Python.

**Status: fixture-backed prototype, not a scientific catalog or released RPM.**
All fixture values and names are synthetic. Gaia ingestion, scientific selection,
validated name cross-matches, and production RPMs are not implemented.

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

Next milestone: a reproducible Gaia subset builder with documented quality cuts,
Astropy coordinate checks, explicit distance provenance, and validated aliases.
Mass/luminosity estimation, `--raw`, unit flags, and online enrichment are deferred.