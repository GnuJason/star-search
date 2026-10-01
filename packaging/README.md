# Packaging: star-search for openSUSE

This directory holds the reproducible packaging inputs for submitting the
`star-search` CLI to openSUSE (target devel project: `utilities`).

The package ships **only** the C/GLSL command-line tool, its man page, its GLSL
shaders, and its docs. It contains **no catalog datasets, no web front-end, and
no generated star portraits**.

## Files
- `star-search.spec` — the RPM spec (openSUSE header, GPL-3.0-or-later, cmake build).

## Dependencies
star-search 1.0 is a lightweight, API-backed CLI written in C. Its only
external libraries are:

| Purpose            | BuildRequires           | Runtime (auto-generated soname dep) |
|--------------------|-------------------------|-------------------------------------|
| HTTP client        | `pkgconfig(libcurl)`    | `libcurl.so.4`                      |
| JSON parsing       | `pkgconfig(libcjson)`   | `libcjson.so.1`                     |

Both are packaged in openSUSE Factory, so the package builds on OBS with no
external-dependency blocker. Plus the toolchain: `gcc`, `cmake >= 3.20`,
`pkgconfig` (no C++ compiler is needed). PNG encoding uses the vendored,
header-only `stb_image_write`.

## Runtime configuration
Catalog lookups go over HTTPS to the star-search API; rendering is local.

| Variable                 | Default                      | Meaning                    |
|--------------------------|------------------------------|----------------------------|
| `STAR_SEARCH_API_URL`    | `https://starsearch.online`  | Catalog API base URL       |
| `STAR_SEARCH_ASSETS_DIR` | `assets/stars/`              | Where `render` writes PNGs |

## Reproduce the source tarball
The **final** submission tarball must come from a clean `git archive` of the
committed API-backed code. `.gitattributes` carries `export-ignore` rules that
strip `/data`, `/web`, `/gaia_datasets`, `/assets`, and `/.vscode`, so no
datasets/website/portraits can leak in.

```sh
cd <repo root>
git archive --format=tar.gz --prefix=star-search-1.0/ \
    -o ~/rpmbuild/SOURCES/star-search-1.0.tar.gz HEAD
# verify it is source-only:
tar tzf ~/rpmbuild/SOURCES/star-search-1.0.tar.gz \
    | grep -iE '\.parquet|/web/|\.png|\.so|duckdb' || echo "clean"
```

(Before the API-backed code is committed, a verification tarball can be built
from the working tree with the same exclusions; it is not meant for submission.)

## Local build + lint
```sh
cp packaging/star-search.spec ~/rpmbuild/SPECS/
rpmlint ~/rpmbuild/SPECS/star-search.spec
rpmbuild -ba ~/rpmbuild/SPECS/star-search.spec     # add --nodeps on a non-openSUSE host
rpm -qlp ~/rpmbuild/RPMS/x86_64/star-search-1.0-1.x86_64.rpm
rpm -qp --requires ~/rpmbuild/RPMS/x86_64/star-search-1.0-1.x86_64.rpm
```

Expected rpmlint result on the spec: 0 errors. Warnings seen under the Ubuntu
rpmlint profile (`no-buildroot-tag`, `invalid-url` on a local Source0) are
cosmetic; OBS supplies packager/signature/compression handling.

## Submit to openSUSE (requires your OBS account/credentials)
These steps need your `osc` login (`~/.config/osc/oscrc`) and network access to
`build.opensuse.org`; run them yourself:

```sh
osc checkout home:gnujason:star-search star-search        # or: osc mkpac star-search
cd home:gnujason:star-search/star-search
cp <repo>/packaging/star-search.spec .
cp ~/rpmbuild/SOURCES/star-search-1.0.tar.gz .
osc addremove
osc commit -m "star-search 1.0: initial openSUSE package (API-backed CLI)"
osc results          # wait for a clean build on the enabled repositories
osc sr home:gnujason:star-search utilities
```

## Roadmap: v2.0 optional local backend
A future release may add an optional offline, DuckDB-backed catalog mode for
power users who want to query local Parquet files. It will plug in behind
`src/catalog.h` and ship as a **separate, non-Factory build**, so this Factory
package stays dependency-light (libcurl + libcjson only).
