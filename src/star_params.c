/* Host-side derivation of star-portrait shader parameters from catalog data.
 * Every formula is documented in docs/renderer.md; the Phase 3 website must
 * reproduce this file (not the shader) to feed star.frag the same uniforms. */
#include "star_params.h"

#include <ctype.h>
#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define SOLAR_TEFF 5772.0      /* IAU 2015 Resolution B3 nominal solar Teff */
#define SOLAR_MBOL 4.74        /* IAU 2015 Resolution B2 nominal solar M_bol */

static double interpolate(const double (*table)[2], size_t count, double x) {
    if (x <= table[0][0]) {
        return table[0][1];
    }
    for (size_t index = 1; index < count; ++index) {
        if (x <= table[index][0]) {
            double t = (x - table[index - 1][0]) / (table[index][0] - table[index - 1][0]);
            return table[index - 1][1] + t * (table[index][1] - table[index - 1][1]);
        }
    }
    return table[count - 1][1];
}

/* Dwarf Teff by spectral subtype, keyed on class_index*10 + subclass with
 * O=0, B=1, A=2, F=3, G=4, K=5, M=6, L=7, T=8, Y=9. Anchor values rounded
 * from Pecaut & Mamajek (2013, ApJS 208, 9), "A Modern Mean Dwarf Stellar
 * Color and Effective Temperature Sequence" (online table v2022.04). */
static const double spectral_teff[][2] = {
    {3, 44900}, {5, 41400}, {8, 35000}, {10, 31400}, {12, 23000}, {15, 15700},
    {18, 11400}, {20, 9700}, {22, 8840}, {25, 8080}, {30, 7220}, {32, 6810},
    {35, 6510}, {38, 6170}, {40, 5920}, {42, 5770}, {45, 5660}, {48, 5490},
    {50, 5280}, {52, 5040}, {55, 4440}, {57, 4050}, {60, 3850}, {61, 3680},
    {62, 3550}, {63, 3400}, {64, 3200}, {65, 3050}, {66, 2800}, {67, 2650},
    {68, 2500}, {69, 2400}, {70, 2250}, {72, 2050}, {75, 1650}, {78, 1400},
    {80, 1300}, {85, 1100}, {89, 700}, {90, 450},
};

double teff_from_spectral_type(const char *spectral_type) {
    if (!spectral_type) {
        return NAN;
    }
    const char *cursor = spectral_type;
    while (*cursor && isspace((unsigned char)*cursor)) {
        ++cursor;
    }
    /* White dwarfs: D + optional spectral letters + temperature index n, Teff = 50400/n
     * (Sion et al. 1983, ApJ 269, 253). */
    if (cursor[0] == 'D' && cursor[1] && strchr("ABOQZCXP", cursor[1])) {
        const char *digits = cursor + 1;
        while (*digits && isalpha((unsigned char)*digits)) {
            ++digits;
        }
        double index = 0.0;
        if (isdigit((unsigned char)*digits)) {
            index = strtod(digits, NULL);
        }
        return index > 0.0 ? fmin(50400.0 / index, 150000.0) : 10000.0;
    }
    /* Skip subdwarf / dwarf prefixes: "sd", "esd", "usd", "d". */
    static const char *prefixes[] = {"usd", "esd", "sd", "d"};
    for (size_t index = 0; index < sizeof(prefixes) / sizeof(prefixes[0]); ++index) {
        size_t length = strlen(prefixes[index]);
        if (strncmp(cursor, prefixes[index], length) == 0 && cursor[length] &&
            strchr("OBAFGKMLTY", cursor[length])) {
            cursor += length;
            break;
        }
    }
    const char *classes = "OBAFGKMLTY";
    const char *found = *cursor ? strchr(classes, *cursor) : NULL;
    if (!found) {
        return NAN;
    }
    double subclass = 5.0;
    if (isdigit((unsigned char)cursor[1])) {
        char buffer[8] = {0};
        size_t length = 0;
        for (const char *digit = cursor + 1; length < sizeof(buffer) - 1 &&
             (isdigit((unsigned char)*digit) || *digit == '.'); ++digit) {
            buffer[length++] = *digit;
        }
        subclass = fmin(atof(buffer), 9.5);
    }
    double key = (double)(found - classes) * 10.0 + subclass;
    return interpolate(spectral_teff, sizeof(spectral_teff) / sizeof(spectral_teff[0]), key);
}

/* Dwarf-sequence BP-RP -> Teff, same source as above (Pecaut & Mamajek 2013, v2022.04). */
static const double bp_rp_teff[][2] = {
    {-0.35, 31400}, {-0.25, 20600}, {-0.155, 15700}, {-0.06, 11400}, {0.00, 9700},
    {0.15, 8590}, {0.38, 7220}, {0.58, 6510}, {0.82, 5770}, {0.98, 5280},
    {1.24, 4790}, {1.43, 4440}, {1.84, 3850}, {2.22, 3550}, {2.51, 3400},
    {2.87, 3200}, {3.30, 3050}, {4.00, 2800}, {4.40, 2650}, {4.70, 2500},
    {4.86, 2400}, {5.00, 2300},
};

double teff_from_bp_rp(double bp_rp) {
    if (!isfinite(bp_rp) || bp_rp < -0.6 || bp_rp > 6.0) {
        return NAN;
    }
    return interpolate(bp_rp_teff, sizeof(bp_rp_teff) / sizeof(bp_rp_teff[0]), bp_rp);
}

/* Andrae et al. (2018, A&A 616, A8), Gaia DR2 FLAME, eq. 7 and Table 8:
 * BC_G = sum a_i (Teff - 5772)^i, i = 0..4, valid 3300-8000 K. */
double bolometric_correction_g(double teff_k) {
    double t = fmin(fmax(teff_k, 3300.0), 8000.0) - SOLAR_TEFF;
    static const double hot[5] = {6.000e-02, 6.731e-05, -6.647e-08, 2.859e-11, -7.197e-15};
    static const double cool[5] = {1.749e+00, 1.977e-03, 3.737e-07, -8.966e-11, -4.183e-14};
    const double *a = t + SOLAR_TEFF >= 4000.0 ? hot : cool;
    return a[0] + t * (a[1] + t * (a[2] + t * (a[3] + t * a[4])));
}

/* Torres (2010, AJ 140, 1158), Table 1 — Flower (1996) BC_V(log Teff) with
 * the corrected coefficients. */
double bolometric_correction_v(double teff_k) {
    double x = log10(fmin(fmax(teff_k, 2500.0), 50000.0));
    if (x < 3.70) {
        return -0.190537291496456e5 + x * (0.155144866764412e5 +
               x * (-0.421278819301717e4 + x * 0.381476328422343e3));
    }
    if (x < 3.90) {
        return -0.370510203809015e5 + x * (0.385672629965804e5 + x * (-0.150651486316025e5 +
               x * (0.261724637119416e4 + x * -0.170623810323864e3)));
    }
    return -0.118115450538963e6 + x * (0.137145973583929e6 + x * (-0.636233812100225e5 +
           x * (0.147412923562646e5 + x * (-0.170587278406872e4 + x * 0.788731721804990e2))));
}

static uint32_t mix32(uint32_t x) {   /* lowbias32, identical to hash32 in star.frag */
    x ^= x >> 16; x *= 0x7feb352dU;
    x ^= x >> 15; x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}

uint32_t star_seed(const star_inputs *inputs) {
    if (inputs->has_source_id) {
        uint64_t value = (uint64_t)inputs->source_id;
        return mix32((uint32_t)value ^ mix32((uint32_t)(value >> 32)));
    }
    uint32_t hash = 2166136261U;   /* FNV-1a 32-bit */
    for (const unsigned char *cursor = (const unsigned char *)(inputs->id ? inputs->id : "");
         *cursor; ++cursor) {
        hash = (hash ^ *cursor) * 16777619U;
    }
    return mix32(hash);
}

static bool is_white_dwarf(const char *spectral_type) {
    return spectral_type && spectral_type[0] == 'D' && spectral_type[1] &&
           strchr("ABOQZCXP", spectral_type[1]);
}

static double lerp_log_teff(double teff, const double (*table)[2], size_t count) {
    return interpolate(table, count, log10(teff));
}

void star_derive_params(const star_inputs *in, double phase, star_render_params *out) {
    memset(out, 0, sizeof(*out));
    out->absolute_mag = NAN;
    out->bolometric_correction = NAN;
    out->luminosity_solar = NAN;

    /* 1. Effective temperature: Gaia GSP-Phot > spectral type > BP-RP > solar default. */
    double teff = NAN;
    if (isfinite(in->teff_k) && in->teff_k >= 2000.0 && in->teff_k <= 60000.0) {
        teff = in->teff_k;
        out->teff_source = "gaia_gspphot";
    }
    if (!isfinite(teff) && isfinite(teff = teff_from_spectral_type(in->spectral_type))) {
        out->teff_source = "spectral_type";
    }
    if (!isfinite(teff) && isfinite(teff = teff_from_bp_rp(in->bp_rp))) {
        out->teff_source = "bp_rp";
    }
    if (!isfinite(teff)) {
        teff = SOLAR_TEFF;
        out->teff_source = "default_solar";
    }
    out->teff_k = teff;

    /* 2. Luminosity from absolute magnitude + bolometric correction, then
     *    Stefan-Boltzmann: R/Rsun = sqrt(L/Lsun) (Tsun/Teff)^2. */
    bool white_dwarf = is_white_dwarf(in->spectral_type);
    if (isfinite(in->phot_g_mean_mag) && isfinite(in->parallax_mas) && in->parallax_mas > 0.0) {
        out->absolute_mag = in->phot_g_mean_mag + 5.0 * log10(in->parallax_mas) - 10.0;
        out->absolute_mag_band = "G";
        /* Andrae's BC_G is defined for 3300-8000 K; hotter than that G ~ V for
         * blue stars (|G - V| < 0.1 mag at BP-RP < 0.5), so use BC_V. */
        out->bolometric_correction = teff > 8000.0 ? bolometric_correction_v(teff) :
                                                     bolometric_correction_g(teff);
        out->radius_source = "gaia_g_parallax_bc";
    } else if (isfinite(in->absolute_v_mag)) {
        out->absolute_mag = in->absolute_v_mag;
        out->absolute_mag_band = "V";
        out->bolometric_correction = bolometric_correction_v(teff);
        out->radius_source = "recons_mv_bc";
    }
    if (isfinite(out->absolute_mag)) {
        double m_bol = out->absolute_mag + out->bolometric_correction;
        out->luminosity_solar = pow(10.0, -0.4 * (m_bol - SOLAR_MBOL));
        out->radius_solar = sqrt(out->luminosity_solar) * pow(SOLAR_TEFF / teff, 2.0);
    } else if (white_dwarf) {
        out->radius_solar = 0.012;
        out->radius_source = "white_dwarf_default";
    } else {
        /* Rough main-sequence radius-temperature scaling, R ~ (Teff/Tsun)^1.8
         * (fits Pecaut & Mamajek dwarfs to ~30% from M5 to A0). */
        out->radius_solar = pow(teff / SOLAR_TEFF, 1.8);
        out->radius_source = "main_sequence_teff";
    }

    /* 3. Rendered disk size: logarithmic in physical radius, clamped so white
     *    dwarfs stay visible and giants still fit with their halo. */
    double scaled = 0.62 + 0.14 * log10(fmax(out->radius_solar, 1e-6));
    out->disk_radius = fmin(fmax(scaled, 0.22), 0.86);

    /* 4. Quadratic limb darkening, interpolated in log Teff. Representative
     *    broadband (V-like) values following the trends of Claret (2000,
     *    A&A 363, 1081) for log g ~ 4.5, solar metallicity; not per-star fits. */
    static const double u1_table[][2] = {
        {3.4771, 0.60}, {3.5441, 0.56}, {3.7612, 0.47}, {3.9031, 0.36}, {4.0000, 0.30}, {4.4771, 0.20},
    };
    static const double u2_table[][2] = {
        {3.4771, 0.20}, {3.5441, 0.24}, {3.7612, 0.23}, {3.9031, 0.26}, {4.0000, 0.25}, {4.4771, 0.20},
    };
    out->limb_u1 = lerp_log_teff(teff, u1_table, 6);
    out->limb_u2 = lerp_log_teff(teff, u2_table, 6);

    /* 5. Granulation: convective surfaces (Teff < ~7000 K) show granulation;
     *    radiative envelopes of hotter stars are nearly smooth. Larger stars
     *    (lower gravity) have relatively larger cells -> fewer cells per radius. */
    static const double amplitude_table[][2] = {
        {3.4771, 0.07}, {3.7612, 0.06}, {3.8451, 0.03}, {3.9031, 0.012}, {4.4771, 0.008},
    };
    out->granulation_amplitude = lerp_log_teff(teff, amplitude_table, 5);
    out->granulation_frequency = fmin(fmax(14.0 - 3.0 * log10(fmax(out->radius_solar, 1e-6)), 6.0), 22.0);

    /* 6. Variability: only for Gaia-flagged photometric variables. */
    out->variable = in->variable_flag && strcmp(in->variable_flag, "VARIABLE") == 0;
    out->variability_amplitude = out->variable ? 0.08 : 0.0;
    out->phase = phase - floor(phase);
    out->seed = star_seed(in);
}
