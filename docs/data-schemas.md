# Data schemas

All datasets live under `gaia_datasets/` on the data-warehouse VM and are **never
committed to git** (`.gitignore` keeps only `.gitkeep` and `README.md`). Every
file is Apache Parquet written by PyArrow with key/value metadata recording
provenance; each Parquet schema carries a `schema_doc` key pointing at the section
of this document that describes it.

Downstream consumers (the C CLI, the C/GLSL star-portrait renderer, and the planned
Next.js / WebGPU site) read these files directly. Column names and types are
therefore a contract: add columns freely, but do not rename, retype, or change the
meaning of existing ones without bumping the file's `generated_on` and this
document.

## Shared conventions

| Convention | Value |
| --- | --- |
| Coordinate frame | ICRS right ascension / declination in degrees, `ra_deg` in `[0, 360)`, `dec_deg` in `[-90, 90]` |
| Reference epoch | `ref_epoch_jyear` as a Julian year. Gaia DR3 and the merged catalog are at **J2016.0**; the raw RECONS table is J2000.0 |
| Cartesian frame | `x_pc, y_pc, z_pc` are **heliocentric equatorial** parsecs: `x = d cos δ cos α`, `y = d cos δ sin α`, `z = d sin δ` (ICRS axes, not Galactic) |
| Galactic coordinates | `galactic_longitude_deg` in `[0, 360)`, `galactic_latitude_deg` in `[-90, 90]`; Gaia's own `l`/`b` when present, otherwise the IAU 1958 rotation of the ICRS position |
| Distance | Parsecs are canonical. `distance_ly = distance_pc × 3.2615637771674336` |
| Parallax | `parallax_mas` in milliarcseconds; `parallax_error_mas` is a 1σ uncertainty when the source quotes one |
| Proper motion | `pmra_mas_per_year` is `μα* = μα cos δ`, `pmdec_mas_per_year` is `μδ`, both mas/yr |
| Unknown values | Parquet null. Never zero, NaN, infinity, or sentinel strings |
| Stable IDs | Lower-case, colon-separated: `gaia-dr3:<source_id>` and `recons:<gj-slug>[:<component>]` (see below) |

### Identifier conventions

* `gaia-dr3:<source_id>` – one Gaia DR3 `source_id`, e.g. `gaia-dr3:5853498713190525696`.
* `recons:<slug>` – one RECONS component. The slug is the CNS/GJ system name
  lower-cased with spaces replaced by hyphens, followed by `:<component>` when the
  RECONS row is a lettered component: `recons:gj-551` (Proxima Centauri),
  `recons:gj-559:a` (alpha Centauri A), `recons:gj-65:b` (UV Ceti).
* In `merged_catalog.parquet` a row keeps the Gaia identifier whenever a Gaia
  source was matched (`match_status` = `matched` or `matched_parallax_conflict`)
  or is Gaia-only; RECONS-only rows keep their `recons:` identifier. IDs are
  unique within each file.

## `recons_nearest.parquet`

Produced by `tools/ingest_recons.py` from the RECONS "100 nearest stellar systems"
page (`http://recons.org/TOP100.posted.htm`, snapshot accurate as of 2012-01-01).
One row per stellar or substellar **component**; planet rows are dropped. The
current build contains **142 components in 100 systems**.

| Column | Type | Meaning |
| --- | --- | --- |
| id | string, NOT NULL | Stable ID, `recons:<slug>[:<component>]` |
| is_recons_entry | bool, NOT NULL | Always true; lets consumers distinguish RECONS rows after concatenation |
| system_rank | int32, NOT NULL | RECONS distance rank of the system, 1–100 |
| system_name | string | RECONS system label as printed |
| cns_name | string, NOT NULL | CNS / Gliese-Jahreiß designation of the system, e.g. `GJ 65` |
| component | string | Component letter (`A`, `B`, `C`, …) or null for single stars |
| common_name | string | Common or variable-star name as printed, e.g. `Proxima Centauri`, `UV Ceti` |
| num_objects | string | RECONS object-count column verbatim (stars and known planets) |
| planet_count | int32 | Number of planets RECONS listed for the system |
| lhs_id | string | Luyten Half-Second catalog number without the `LHS` prefix |
| ra_hms, dec_dms | string, NOT NULL | Sexagesimal J2000 coordinates verbatim |
| ra_deg, dec_deg | float64, NOT NULL | The same coordinates in degrees (ICRS/J2000) |
| ref_epoch_jyear | float64, NOT NULL | 2000.0 |
| proper_motion_arcsec_per_year | float64 | Total proper motion as printed |
| proper_motion_angle_deg | float64 | Position angle of the proper motion, degrees east of north |
| proper_motion_reference | string | RECONS reference code for the proper motion |
| pmra_mas_per_year, pmdec_mas_per_year | float64 | Derived components: `μ sin θ`, `μ cos θ` in mas/yr |
| parallax_arcsec | float64, NOT NULL | Weighted trigonometric parallax as printed |
| parallax_mas | float64 | `parallax_arcsec × 1000` |
| parallax_error_mas | float64 | Quoted error × 1000 |
| parallax_reference | string | RECONS reference code(s) for the parallax |
| parallax_source_count | int32 | Number of parallax measurements RECONS combined |
| distance_pc, distance_ly | float64, NOT NULL | `1 / parallax_arcsec` and its light-year conversion |
| x_pc, y_pc, z_pc | float64, NOT NULL | Heliocentric equatorial Cartesian position |
| galactic_longitude_deg, galactic_latitude_deg | float64, NOT NULL | Derived from ra/dec |
| spectral_type | string | Spectral type as printed |
| v_mag | float64 | Johnson V magnitude |
| v_mag_flag | string | RECONS flag beside V (e.g. joint photometry) |
| v_mag_reference | string | Reference code for V |
| absolute_mag | float64 | Absolute V magnitude as printed |
| mass_solar | float64 | RECONS mass estimate in solar masses |
| mass_estimate_flag | string | Flag marking estimated / uncertain masses |
| notes | string | Free-text notes column |
| source_line | string | The original fixed-width line, for audit |
| source_catalog | string, NOT NULL | `RECONS (100 Nearest Star Systems; 2012-01-01)` |

Metadata: `source_url`, `source_sha256` (of the downloaded HTML), `source_epoch`,
`generated_on`, `included_records`, `excluded_planet_rows`, `coordinate_frame`,
`schema_doc`. `gaia_datasets/recons_pdf_crosscheck.md` records the OCR
cross-check of the parallaxes against the uploaded RECONS PDF.

Caveats: RECONS prints one coordinate per system, so companions share the
primary's RA/Dec; parallax references vary per system; the list is a 2012
snapshot, not a current census.

## `gaia_dr3_subset.parquet`

Produced by `tools/ingest_gaia.py` (`fetch` then `normalize`). The default fetch
runs `SELECT … FROM gaiadr3.gaia_source WHERE parallax > 40` against the ESA Gaia
TAP sync endpoint (everything nominally within 25 pc); `normalize` accepts any
Gaia export dropped into `gaia_datasets/raw/` (CSV, ECSV, VOTable, FITS, Parquet)
and deduplicates on `source_id`. The current build contains **5323 sources**.

| Column | Type | Meaning |
| --- | --- | --- |
| id | string, NOT NULL | `gaia-dr3:<source_id>` |
| gaia_dr3_source_id | int64, NOT NULL | Gaia DR3 `source_id` |
| designation | string | `Gaia DR3 <source_id>` |
| ra_deg, dec_deg | float64, NOT NULL | ICRS position at J2016.0 |
| ra_error_mas, dec_error_mas | float64 | Gaia positional uncertainties |
| ref_epoch_jyear | float64, NOT NULL | 2016.0 |
| parallax_mas | float64, NOT NULL | Gaia parallax (no zero-point correction applied) |
| parallax_error_mas, parallax_over_error | float64 | Gaia uncertainty and signal-to-noise |
| pmra_mas_per_year, pmra_error_mas_per_year, pmdec_mas_per_year, pmdec_error_mas_per_year | float64 | Gaia proper motion |
| radial_velocity_km_s, radial_velocity_error_km_s | float64 | Gaia RVS radial velocity |
| ruwe | float64 | Renormalised unit weight error (astrometric quality) |
| phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, bp_rp | float64 | Gaia photometry |
| phot_variable_flag | string | `VARIABLE`, `NOT_AVAILABLE`, … |
| non_single_star | int32 | Gaia non-single-star flag bitmask |
| teff_gspphot_k, logg_gspphot, mh_gspphot | float64 | GSP-Phot astrophysical parameters |
| distance_gspphot_pc | float64 | GSP-Phot distance, kept for comparison |
| distance_pc, distance_ly | float64 | Adopted distance (see `distance_mode`) |
| distance_mode | string, NOT NULL | `inverse_parallax` (parallax > 0 and `parallax_over_error ≥ 5`), `gspphot` (fallback to GSP-Phot), or `none` |
| x_pc, y_pc, z_pc | float64 | Heliocentric equatorial Cartesian position, null when distance is null |
| galactic_longitude_deg, galactic_latitude_deg | float64, NOT NULL | Gaia `l`/`b` when present, else derived |
| source_file | string, NOT NULL | Raw file the row came from |
| source_catalog | string, NOT NULL | `Gaia DR3 (gaiadr3.gaia_source), ESA/Gaia/DPAC` |

Metadata: `source_catalog`, `source_files` (JSON list), `generated_on`,
`row_count`, `duplicates_removed`, `distance_policy`, `coordinate_frame`,
`schema_doc`. The raw download keeps a sidecar `<file>.json` manifest with the
ADQL query, row count, byte size and SHA-256.

Caveats: inverse parallax is a naive estimator that is only acceptable because
of the 40 mas / SNR ≥ 5 selection; very bright stars (Sirius A, alpha Centauri
A/B, Procyon A, Altair, …) are absent from Gaia DR3 astrometry; the 25 pc volume
is incomplete for faint brown dwarfs.

## `merged_catalog.parquet`

Produced by `tools/build_merged_catalog.py` by positionally cross-matching the two
files above. This is **the** catalog for the CLI (`tools/build_catalog.py
--merged`), the renderer and the 3D map. Rows are sorted by `distance_pc`. The
current build contains **5356 rows**: 107 `matched`, 2
`matched_parallax_conflict`, 33 `recons_only`, 5214 `gaia_only`.

### Matching algorithm

1. RECONS J2000 positions are propagated to J2016.0 with the RECONS proper
   motion.
2. **Primary pass** – each RECONS component is matched to Gaia sources within
   30″ whose parallax agrees within 20 %. Components of a RECONS system that
   share one printed coordinate are paired with the candidate Gaia sources by
   brightness rank (brightest component ↔ brightest Gaia G), so binaries such as
   UV Ceti / BL Ceti resolve to two distinct sources.
3. **Wide pass** – still-unmatched components of shared-coordinate systems get a
   second look out to 60″ (catches wide binaries whose secondary sits far from
   the printed primary position, e.g. GJ 15 B).
4. **Conflict pass** – if a component's only positional neighbour failed the
   parallax gate, the pair is still linked but flagged
   `matched_parallax_conflict`; the Gaia parallax is adopted and the discrepancy
   recorded.
5. RECONS components without any Gaia counterpart become `recons_only`; Gaia
   sources never claimed become `gaia_only`.

Parameters and counts are stored in the Parquet metadata (`match_parameters`,
`match_counts`) and narrated in `gaia_datasets/merge_report.md` (unmatched list,
ambiguous groups, parallax conflicts, worst disagreements, full matched list).

### Columns

| Column | Type | Meaning |
| --- | --- | --- |
| id | string, NOT NULL | Stable ID (`gaia-dr3:…` when a Gaia source is linked, else `recons:…`) |
| primary_name | string, NOT NULL | Display name: RECONS common name → RECONS CNS/component name → Gaia designation |
| common_name | string | RECONS common name |
| recons_name | string | RECONS CNS name with component letter, e.g. `GJ 65 A` |
| recons_id | string | `id` of the RECONS row (`recons:…`), null for Gaia-only rows |
| recons_system_rank | int32 | RECONS rank 1–100 |
| recons_system_name | string | Bare CNS system name, e.g. `GJ 65` |
| component | string | RECONS component letter |
| lhs_id | string | LHS number (no prefix) |
| gaia_source_id | int64 | Gaia DR3 `source_id`, null for RECONS-only rows |
| gaia_designation | string | `Gaia DR3 <source_id>` |
| source_of_name | string, NOT NULL | `recons_common_name`, `recons_cns_name`, or `gaia_designation` |
| match_status | string, NOT NULL | `matched`, `matched_parallax_conflict`, `recons_only`, `gaia_only` |
| match_separation_arcsec | float64 | Separation between propagated RECONS position and Gaia position |
| match_candidates | int32 | Gaia candidates inside the search radius before disambiguation |
| match_note | string | Free text: brightness-rank pairing, wide pass, conflict details |
| ra_deg, dec_deg | float64, NOT NULL | ICRS position at J2016.0 |
| ref_epoch_jyear | float64, NOT NULL | 2016.0 |
| source_of_position | string, NOT NULL | `gaia` or `recons_propagated` |
| parallax_mas | float64, NOT NULL | Adopted parallax |
| parallax_error_mas | float64 | Uncertainty of the adopted parallax |
| source_of_parallax | string, NOT NULL | `gaia` or `recons`. Gaia is preferred; RECONS wins only when it is the sole source or quotes a smaller error |
| recons_parallax_mas, gaia_parallax_mas | float64 | Both measurements when available |
| parallax_discrepancy_pct | float64 | `100 × |plx_recons − plx_gaia| / plx_gaia` |
| distance_pc, distance_ly | float64, NOT NULL | `1000 / parallax_mas` |
| distance_mode | string, NOT NULL | Always `inverse_parallax` in this build |
| x_pc, y_pc, z_pc | float64, NOT NULL | Heliocentric equatorial Cartesian position (J2016.0) |
| galactic_longitude_deg, galactic_latitude_deg | float64, NOT NULL | Galactic coordinates of the adopted position |
| pmra_mas_per_year, pmdec_mas_per_year | float64 | Adopted proper motion |
| source_of_proper_motion | string | `gaia` or `recons` |
| radial_velocity_km_s | float64 | Gaia RVS |
| spectral_type | string | RECONS spectral type |
| source_of_spectral_type | string | `recons` when present |
| v_mag, absolute_mag, mass_solar | float64 | RECONS photometry and mass estimate |
| phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, bp_rp | float64 | Gaia photometry |
| teff_gspphot_k, logg_gspphot, mh_gspphot | float64 | Gaia GSP-Phot parameters |
| ruwe | float64 | Gaia RUWE |
| non_single_star | int32 | Gaia NSS flag |
| phot_variable_flag | string | Gaia variability flag |
| planet_count | int32 | RECONS planet count |
| notes | string | RECONS notes |
| source_catalogs | string, NOT NULL | `RECONS+Gaia DR3`, `Gaia DR3`, or `RECONS` |

Metadata: `description`, `generated_on`, `match_parameters` (JSON),
`match_counts` (JSON), `coordinate_frame`, `schema_doc`.

### Known disagreements and caveats

* **Absent from Gaia:** alpha Centauri A/B, Sirius A, Procyon A, Altair are too
  bright for Gaia DR3 astrometry and stay `recons_only` with RECONS parallaxes
  and RECONS positions propagated to J2016.0. Sirius B is matched to its own
  Gaia source; Procyon B has no Gaia counterpart in the subset and is also
  `recons_only`.
* **Unresolved multiples:** RECONS prints one coordinate per system, so B/C
  components of tight or unresolved systems (EZ Aquarii A/B/C, Kruger 60 A/B,
  Ross 614 A/B, GJ 1005 A/B, GJ 661 A/B, Wolf 630 A/B/C, GJ 570 B/C/D, …) have
  no separate Gaia source and are `recons_only`.
* **Sub-stellar companions:** T/L dwarfs (GJ 229 B, epsilon Indi C, SCR 1845-6357
  B, the 2MASS objects) are below Gaia's limit.
* **Parallax conflicts:** LP 944-020 (RECONS 201 mas vs Gaia 155.9 mas, 29 %)
  and G 180-060 (76 % apart) are linked as `matched_parallax_conflict` with the
  Gaia parallax adopted; treat the RECONS values as superseded.
* **RECONS parallax adopted for matched rows:** epsilon Eridani, tau Ceti and
  epsilon Indi B use RECONS parallaxes because RECONS quotes a smaller error than
  Gaia DR3 for those bright / problematic sources. Check `source_of_parallax`
  before assuming a Gaia value.
* **Epoch:** RECONS positions are 2000.0 and were propagated with RECONS proper
  motions; residual offsets of a few arcseconds against Gaia are expected for
  high-proper-motion stars and appear in `match_separation_arcsec`.

## CLI catalog directory (`stars.parquet`, `aliases.parquet`, `catalog.json`)

The C CLI reads a 21-column projection of the merged catalog described in
[catalog-contract.md](catalog-contract.md): the 17 required star columns plus the
optional renderer inputs `teff_k` (from `teff_gspphot_k`), `bp_rp`,
`absolute_v_mag` (from RECONS `absolute_mag`) and `phot_variable_flag`. Build it with

```sh
.venv/bin/python tools/build_catalog.py \
  --merged gaia_datasets/merged_catalog.parquet --output build/catalog
```

## Star portraits (`assets/stars/*.png`, `assets/stars/index.json`)

Generated by `star-search render` / `tools/render_all.py` (see
[renderer.md](renderer.md)); git-ignored. Each portrait is a square 8-bit RGB PNG
named `<gaia_source_id>.png`, or the sanitised stable ID for stars without a Gaia
match (`recons-gj-244-a.png`). `index.json` is one JSON object:

| Field | Meaning |
| --- | --- |
| schema_version | Integer, currently 1 |
| renderer | Renderer identifier and version string |
| subset | `recons` or `all` |
| size | Image edge length in pixels |
| portraits | Object keyed by catalog `id`: `file`, `name`, `gaia_dr3_source_id` (string or null), `parameters` (the `render --json` parameter object with provenance) |

## Regenerating everything

```sh
.venv/bin/python tools/ingest_recons.py http://recons.org/TOP100.posted.htm \
  --output gaia_datasets/recons_nearest.parquet --csv-output gaia_datasets/recons_nearest.csv
.venv/bin/python tools/ingest_gaia.py fetch                      # ESA TAP, parallax > 40 mas
.venv/bin/python tools/ingest_gaia.py normalize --raw-dir gaia_datasets/raw \
  --output gaia_datasets/gaia_dr3_subset.parquet
.venv/bin/python tools/build_merged_catalog.py                   # writes merged_catalog.parquet + merge_report.md
.venv/bin/python tools/build_catalog.py --merged gaia_datasets/merged_catalog.parquet \
  --output build/catalog
.venv/bin/python tools/render_all.py --catalog-dir build/catalog     # assets/stars/
```

Each step is deterministic for a given set of raw inputs; only `generated_on`
changes between runs. Portraits are byte-identical across runs on the same
platform.
