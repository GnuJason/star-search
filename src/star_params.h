#ifndef STAR_SEARCH_STAR_PARAMS_H
#define STAR_SEARCH_STAR_PARAMS_H

#include <stdbool.h>
#include <stdint.h>

/* Catalog inputs for one star. Missing numeric values are NAN, missing text NULL. */
typedef struct {
    const char *id;               /* stable catalog id, e.g. "gaia-dr3:..." or "recons:gj-559:a" */
    bool has_source_id;
    int64_t source_id;            /* Gaia DR3 source_id when has_source_id */
    const char *spectral_type;    /* e.g. "M5.0 V", "DA2", "sdM1" */
    const char *variable_flag;    /* Gaia phot_variable_flag ("VARIABLE", "NOT_AVAILABLE") */
    double teff_k;                /* Gaia GSP-Phot teff_gspphot */
    double bp_rp;                 /* Gaia BP-RP colour */
    double phot_g_mean_mag;       /* Gaia G apparent magnitude */
    double parallax_mas;          /* adopted parallax */
    double absolute_v_mag;        /* RECONS absolute V magnitude */
} star_inputs;

/* Everything the shader needs (uniforms) plus provenance for --json output. */
typedef struct {
    double teff_k;
    const char *teff_source;      /* gaia_gspphot | spectral_type | bp_rp | default_solar */
    double absolute_mag;          /* NAN when unknown */
    const char *absolute_mag_band;/* "G" | "V" | NULL */
    double bolometric_correction; /* NAN when unknown */
    double luminosity_solar;      /* NAN when unknown */
    double radius_solar;
    const char *radius_source;    /* gaia_g_parallax_bc | recons_mv_bc | white_dwarf_default | main_sequence_teff */
    double disk_radius;           /* fraction of the half-image extent */
    double limb_u1, limb_u2;      /* quadratic limb darkening (green channel) */
    double granulation_amplitude;
    double granulation_frequency;
    bool variable;
    double variability_amplitude;
    double phase;
    uint32_t seed;
} star_render_params;

/* Temperature from a spectral type string (Pecaut & Mamajek 2013 scale; white
 * dwarfs via Teff = 50400 K / temperature index). Returns NAN when unparseable. */
double teff_from_spectral_type(const char *spectral_type);
/* Temperature from Gaia BP-RP (dwarf sequence, Pecaut & Mamajek 2013). NAN if unusable. */
double teff_from_bp_rp(double bp_rp);
/* Gaia G bolometric correction (Andrae et al. 2018), clamped to 3300-8000 K. */
double bolometric_correction_g(double teff_k);
/* Johnson V bolometric correction (Flower 1996 as corrected by Torres 2010). */
double bolometric_correction_v(double teff_k);
/* 32-bit render seed from the Gaia source_id, or FNV-1a of the catalog id. */
uint32_t star_seed(const star_inputs *inputs);

void star_derive_params(const star_inputs *inputs, double phase, star_render_params *out);

#endif
