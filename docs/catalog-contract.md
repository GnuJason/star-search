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

## CLI behavior

`info NAME_OR_ID`, `coords NAME_OR_ID`, `nearest N`, `--catalog-info`, `--version`,
and an interactive prompt are the initial surface. `--json` produces one JSON
document on stdout; diagnostics and prompts go to stderr. IDs are always JSON
strings, including Gaia IDs. Null measurements remain JSON null and print as
`unknown` in text. JSON distances stay in parsecs; text adds light-years and
light-days. `--raw`, unit-selection flags, and online enrichment are deferred.

`nearest` excludes missing distances, orders by distance then stable ID, and
accepts 1 through 10000. It means nearest within this catalog, not a claim of
complete coverage of the solar neighborhood. `coords` reports catalog-epoch
coordinates, not positions propagated to the current date.

Exit codes: 0 success, 1 catalog/runtime error, 2 usage error, 3 no match,
4 ambiguous match. JSON errors have `error` and `message`; ambiguous results also
have `match_count`, `truncated`, and `candidates`.