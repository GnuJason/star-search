# Star-portrait renderer

`star-search render NAME_OR_ID` turns a catalog star's physical parameters into a
PNG portrait. It is deterministic, offline, uses no GPU and no AI/ML model.

```
catalog row ──► src/star_params.c ──► uniforms ──► star.frag math ──► PNG
 (teff, G, plx,   (host-side physics:     (teff, disk     (CPU: src/render.c
  SpT, BP-RP,      teff fallback, L, R,    radius, u1,u2,  GPU: Phase 3 website)
  M_V, variable)   limb darkening, seed)   seed, phase…)
```

| File | Role |
| --- | --- |
| `src/shaders/star.frag` | **Canonical visual model** (GLSL ES 3.00 / WebGL2). |
| `src/shaders/star.vert` | Full-screen triangle for the fragment shader. |
| `src/render.c` | CPU evaluator: the same math as `star.frag`, per pixel, in 32-bit float. |
| `src/star_params.c` | Catalog → shader parameters (temperatures, luminosity, radius, …). |
| `src/third_party/stb_image_write.h` | Vendored PNG encoder (v1.16, public domain / MIT). |
| `tools/render_all.py` | Batch renderer → `assets/stars/*.png` + `assets/stars/index.json`. |

**Sync rule.** `star.frag` and `render.c` implement the same functions with the same
names (`hash32`, `hash3`, `planck_rgb`, `limb_darkening`, `value_noise`, `fbm`,
`srgb_encode`, `main`/`render_pixel`) and the same constants. A change to one must
be made to the other in the same commit. `ctest` compiles the GLSL with
`glslangValidator` when installed and pins the CPU output (`tests/test_render.py`).
The website must reproduce `star_params.c` (not the shader) to feed identical
uniforms; `assets/stars/index.json` already contains every star's derived
parameters, so the website can simply read them.

## Inputs and parameter derivation (`src/star_params.c`)

Catalog columns used: `teff_k` (Gaia GSP-Phot), `spectral_type` (RECONS),
`bp_rp`, `phot_g_mean_mag`, `parallax_mas`, `absolute_v_mag` (RECONS),
`phot_variable_flag` (Gaia). The first four new columns were added to
`stars.parquet` as optional columns (see catalog-contract.md); older catalogs
without them render with NULL inputs.

### Effective temperature (first available wins; `teff_source` records which)

1. `gaia_gspphot` — Gaia DR3 `teff_gspphot` if within 2000–60000 K.
2. `spectral_type` — dwarf Teff scale of Pecaut & Mamajek (2013, ApJS 208, 9;
   online table v2022.04), linearly interpolated on `class*10 + subclass`
   (O..Y). Luminosity class is ignored. `sd`/`esd`/`usd`/`d` prefixes are skipped.
   White dwarfs (`DA2`, `DQ6`, …): Teff = 50400 K / temperature index
   (Sion et al. 1983, ApJ 269, 253).
3. `bp_rp` — Gaia BP−RP on the same Pecaut & Mamajek dwarf colour sequence
   (valid −0.35…5.0; clamped at the ends).
4. `default_solar` — 5772 K (IAU 2015 B3 nominal solar Teff).

### Luminosity and radius (`radius_source`)

* `gaia_g_parallax_bc`: M_G = G + 5 log10(ϖ[mas]) − 10. BC_G from
  Andrae et al. (2018, A&A 616, A8, eq. 7/Table 8), a quartic in (Teff − 5772 K)
  valid 3300–8000 K (clamped below 3300 K). Above 8000 K BC_V of Torres (2010) is
  used because G ≈ V for blue stars.
* `recons_mv_bc`: RECONS absolute V with BC_V from Flower (1996) as corrected by
  Torres (2010, AJ 140, 1158, Table 1).
* L/L☉ = 10^(−0.4 (M + BC − 4.74)) (IAU 2015 B2 M_bol,☉ = 4.74);
  R/R☉ = √(L/L☉) · (5772 K / Teff)² (Stefan–Boltzmann).
* Without photometry: white dwarfs 0.012 R☉ (`white_dwarf_default`); others
  R ≈ (Teff/5772)^1.8 (`main_sequence_teff`, ~30 % vs. the dwarf sequence).

Sanity checks from the real catalog: Proxima 0.125 R☉ (literature 0.154),
Barnard's Star 0.21 (0.19), α Cen A 1.23 (1.22), Sirius A 1.84 (1.71),
Sirius B 0.0075 (0.0084), Altair 1.75 (~1.8).

### Rendered disk radius

`disk_radius = clamp(0.62 + 0.14 · log10(R/R☉), 0.22, 0.86)` as a fraction of the
half-frame. The Sun maps to 0.62; a 0.008 R☉ white dwarf to 0.33; giants of
≳ 70 R☉ clamp at 0.86 so the halo still fits.

### Limb darkening

Quadratic law (Kopal 1950): **I(μ)/I(1) = 1 − u1 (1 − μ) − u2 (1 − μ)²**, with
μ = cos θ = √(1 − ρ²). (u1, u2) are representative broadband (V-like) values that
follow the Teff trend of Claret (2000, A&A 363, 1081) for log g ≈ 4.5 and solar
metallicity, interpolated in log Teff: 3000 K (0.60, 0.20), 3500 K (0.56, 0.24),
5772 K (0.47, 0.23), 8000 K (0.36, 0.26), 10000 K (0.30, 0.25), 30000 K (0.20, 0.20).
They are not per-star fits. The shader scales them per channel
(R 0.85, G 1.00, B 1.18) because limb darkening is stronger at shorter wavelengths.

### Granulation, variability, seed

* Granulation: 3-D value noise with quintic interpolation, 4-octave fBm, sampled
  on the visible hemisphere (x, y, μ). Contrast 7 % at 3000 K → 6 % at 5772 K →
  ~1 % above 8000 K (radiative envelopes). Cells per stellar radius
  `clamp(14 − 3 log10 R, 6, 22)` (bigger, lower-gravity stars → larger cells).
* Variability: only Gaia `phot_variable_flag = VARIABLE` stars; brightness ×
  (1 + 0.08 sin 2π·phase). `--phase` defaults to 0 (mean brightness); non-variables
  ignore it.
* Seed: `lowbias32(lo32 ^ lowbias32(hi32))` of the Gaia source_id, or
  `lowbias32(FNV-1a(id))` for stars without one. It drives the granulation pattern
  and the background starfield.

## Colour: temperature → sRGB (`planck_rgb`)

Planckian locus chromaticity from the cubic-spline fit of Kim et al. (2002,
J. Korean Phys. Soc. 41, 865), valid 1667–25000 K (clamped outside — L/T/Y dwarfs
render as 1667 K, O/B stars and hot white dwarfs as 25000 K):

```
x_c = −0.2661239e9/T³ − 0.2343589e6/T² + 0.8776956e3/T + 0.179910      (1667–4000 K)
x_c = −3.0258469e9/T³ + 2.1070379e6/T² + 0.2226347e3/T + 0.240390      (4000–25000 K)
y_c = −1.1063814x³ − 1.34811020x² + 2.18555832x − 0.20219683          (1667–2222 K)
y_c = −0.9549476x³ − 1.37418593x² + 2.09137015x − 0.16748867          (2222–4000 K)
y_c =  3.0817580x³ − 5.87338670x² + 3.75112997x − 0.37001483          (4000–25000 K)
```

xyY (Y = 1) → XYZ → linear sRGB (IEC 61966-2-1 matrix), negatives clipped,
normalised to a peak channel of 1 (colour carries chromaticity only; size carries
luminosity), then the sRGB transfer function and 8-bit quantisation.

## Image composition

Black sky with a sparse seeded point-star field (0.15 % of pixels), a soft
tinted photographic halo outside the limb (exponential, e-fold 0.05 half-frame;
not a physical corona), then the disk with a 1-pixel analytic anti-aliased edge.
No nebulae (those are website-only). Output: square 8-bit RGB PNG, default
512 px (`--size 16..4096`).

## Determinism

* All randomness is integer hashing of pixel/lattice coordinates and the seed —
  no RNG state, clocks, threads or I/O order dependence.
* The CPU evaluator uses 32-bit float with a fixed evaluation order and is compiled
  with `-ffp-contract=off -fno-fast-math` (no FMA contraction), so identical inputs
  produce byte-identical pixels on a given platform/libm; the stb zlib encoder is
  deterministic, so the PNG bytes match too (`tests/test_render.py` asserts this;
  a full re-render of the 142 RECONS portraits reproduced every SHA-256).
* GPU output of `star.frag` matches within float rounding (visually identical),
  not bit-for-bit; cross-platform libm differences can flip individual 8-bit
  values in the CPU output as well.

## Usage

```sh
export STAR_SEARCH_DATA_DIR="$PWD/build/catalog"
build/star-search render "Proxima Centauri"          # -> assets/stars/5853498713190525696.png
build/star-search render Sirius --size 1024 -o /tmp/sirius.png
build/star-search --json render 4472832130942575872  # path + all derived parameters
build/star-search render "Gaia DR3 ..." --phase 0.25 # variables only
.venv/bin/python tools/render_all.py                 # RECONS subset (142 stars) + index.json
.venv/bin/python tools/render_all.py --subset all    # whole merged catalog (5356 stars)
```

Default path: `$STAR_SEARCH_ASSETS_DIR/<gaia source_id>.png` (default directory
`assets/stars`, relative to the working directory). Stars without a Gaia id use
their catalog id with characters outside `[A-Za-z0-9._-]` replaced by `-`
(`recons:gj-559:a` → `recons-gj-559-a.png`). `assets/stars/` is git-ignored
(bulk generated binaries); regenerate with `tools/render_all.py`.

## Caveats

* Parameters are approximate and intended for visualisation: tabulated Teff scales
  ignore luminosity class, BC_G is clamped below 3300 K (late-M radii are
  underestimated by ~20 %), limb-darkening coefficients are representative.
* Unresolved RECONS systems use system-level photometry, so a companion's radius
  may be overestimated.
* The halo and starfield are aesthetic, not physical.
