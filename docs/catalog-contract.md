# Catalog contract, version 1

A catalog is a directory containing `stars.parquet`, `aliases.parquet`, and
`catalog.json`. Production installs use `/usr/share/star-search`. The environment
variable `STAR_SEARCH_DATA_DIR` can select another local directory. The application
never downloads a catalog or extensions.

## Stars

One row represents one stellar component, not an unresolved named system. Stable
IDs belong to this catalog; a Gaia cross-match is a separate nullable identifier.
All columns are required in the schema. Only `id`, coordinates, and epoch are
non-nullable. Unknown measurements must be null, never zero, NaN, or infinity.

| Column | Arrow / Parquet logical type | Units / meaning |
| --- | --- | --- |
| id | string | Unique nonempty stable ID |
| gaia_dr3_source_id | int64 | Positive Gaia DR3 source ID, nullable |
| name | string | Preferred display name, nullable |
| source_catalog | string | Origin of the primary row, nullable |
| ra_deg | float64 | ICRS right ascension, [0, 360) degrees |
| dec_deg | float64 | ICRS declination, [-90, 90] degrees |
| ref_epoch_jyear | float64 | Julian year of the coordinates |
| parallax_mas | float64 | Measured parallax in milliarcseconds, nullable |
| parallax_error_mas | float64 | Nonnegative uncertainty, nullable |
| distance_pc | float64 | Positive adopted heliocentric distance, nullable |
| distance_method | string | Required when distance is known, otherwise null |
| galactic_longitude_deg | float64 | Galactic longitude, [0, 360) degrees |
| galactic_latitude_deg | float64 | Galactic latitude, [-90, 90] degrees |
| phot_g_mean_mag | float64 | Gaia G apparent magnitude, nullable |
| phot_bp_mean_mag | float64 | Gaia BP apparent magnitude, nullable |
| phot_rp_mean_mag | float64 | Gaia RP apparent magnitude, nullable |
| spectral_type | string | Documented classification, nullable |

Distances have one canonical representation: parsecs. Display uses
`1 pc = 3.2615637771674336 ly` and `1 ly = 365.25 light-days` (Julian year).
Future real-data builders must record the distance estimator and quality cuts.
Inverting arbitrary Gaia parallaxes is prohibited; negative parallaxes may be
retained as measurements but must not yield negative distances.

## Aliases

`alias: string NOT NULL`, `star_id: string NOT NULL`. Each alias references an
existing star. Exact duplicate pairs are rejected. Multiple IDs per alias are
valid and represent ambiguity. Preferred names participate in lookup even when
not duplicated in this file.

Lookup trims outer ASCII whitespace and resolves an exact, case-sensitive stable
ID first, then case-insensitive exact names/aliases, then literal substring
names/aliases. No wildcards, punctuation removal, accent folding, or transliteration
are implied. DuckDB's lowercase mapping defines case matching for version 1.
Matches are deduplicated by ID and sorted by ID. Multiple matches are never
silently resolved. At most ten candidates are displayed, with total match count
and a truncation indicator in JSON. Entering a displayed ID selects that component.

## Manifest

`catalog.json` is exactly one JSON object with these fields:

- `schema_version`: integer, currently 1.
- `catalog_version`: nonempty string identifying release and selection revision.
- `source_catalog`: string describing the source release(s).
- `selection_rules`: string describing coverage and quality selection.
- `distance_policy`: string describing adopted estimators.
- `limitations`: string describing incompleteness and scientific caveats.
- `attribution`: string containing source acknowledgments.
- `license`: string describing redistribution terms, verified before publication.
- `is_fixture`: boolean, true for synthetic test data.

The fixture is not derived from Gaia and makes no claims about real stars. It
must never be published as `star-search-data`. Production data and OBS submission
remain gated on real source selection, cross-match validation, attribution,
redistribution review, and an offline installation test.

Catalogs built with `--merged` add informative fields that readers must tolerate
and may ignore: `generated_on`, `source_file`, `star_count`, `alias_count`,
`match_status_counts`, and `merged_catalog_metadata` (the Parquet key/value
metadata of the merged catalog it was built from).

## Building a catalog from the merged RECONS x Gaia DR3 data

`tools/build_catalog.py --merged gaia_datasets/merged_catalog.parquet --output DIR`
projects the merged catalog (schema in [data-schemas.md](data-schemas.md)) onto the
star table above:

| Star column | Merged source |
| --- | --- |
| id | `id` (`gaia-dr3:<source_id>` or `recons:<slug>`) |
| gaia_dr3_source_id | `gaia_source_id` (null for RECONS-only rows) |
| name | `primary_name` |
| source_catalog | `source_catalogs` (`RECONS+Gaia DR3`, `Gaia DR3`, or `RECONS`) |
| ra_deg, dec_deg, ref_epoch_jyear | ICRS position at J2016.0 (Gaia, or RECONS propagated) |
| parallax_mas, parallax_error_mas | adopted parallax (`source_of_parallax` decides) |
| distance_pc | `1000 / parallax_mas` |
| distance_method | `inverse_parallax:gaia` or `inverse_parallax:recons` |
| galactic_longitude_deg, galactic_latitude_deg | derived from the adopted ICRS position |
| phot_g/bp/rp_mean_mag | Gaia photometry (null for RECONS-only rows) |
| spectral_type | RECONS spectral type (null for Gaia-only rows) |

Aliases emitted per star, deduplicated case-insensitively and never equal to the
star's own `id` or `name`: RECONS common name, RECONS component name (`GJ 65 A`),
the bare CNS/GJ system name (`GJ 65`, shared by components and therefore
ambiguous by design), `LHS <n>`, the RECONS row id (`recons:gj-65:a`), the Gaia
designation (`Gaia DR3 <source_id>`), and the bare Gaia `source_id`. The builder
also copies `recons_nearest.parquet` into the output directory so the
`recons-*` commands work from the same `STAR_SEARCH_DATA_DIR`.

Inverse-parallax distances are permitted here because the selection guarantees
parallax > 40 mas with `parallax_over_error` >= 5 for Gaia rows, and RECONS lists
only trigonometric parallaxes; the manifest records this policy and the naive
inversion caveat (no zero-point or prior correction).

## CLI behavior

`info NAME_OR_ID`, `star NAME_OR_ID` (an exact alias of `info`), `coords NAME_OR_ID`,
`nearest N`, `recons-nearest [N]`, `recons-info NAME_OR_ID`, `--catalog-info`,
`--version`, and an interactive prompt are the current surface. `render NAME_OR_ID`
is reserved for the deterministic C/GLSL portrait renderer; until it ships the
command accepts exactly one argument, writes nothing, and exits 5 with error code
`not_implemented` without opening the catalog. `--json` produces one JSON
document on stdout; diagnostics and prompts go to stderr. IDs are always JSON
strings, including Gaia IDs. Null measurements remain JSON null and print as
`unknown` in text. JSON distances stay in parsecs; text adds light-years and
light-days. `--raw`, unit-selection flags, and online enrichment are deferred.

`nearest` excludes missing distances, orders by distance then stable ID, and
accepts 1 through 10000. It means nearest within this catalog, not a claim of
complete coverage of the solar neighborhood. `coords` reports catalog-epoch
coordinates, not positions propagated to the current date.

Exit codes: 0 success, 1 catalog/runtime error, 2 usage error, 3 no match,
4 ambiguous match, 5 not implemented (`render`). JSON errors have `error` and `message`; ambiguous results also
have `match_count`, `truncated`, and `candidates`.