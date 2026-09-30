"""Python port of src/star_params.c (star-portrait shader parameter derivation).

The website feeds src/shaders/star.frag the same uniforms as the C CLI, so this
module must stay in lock-step with src/star_params.c. Every formula and its
citation is documented in docs/renderer.md. prepare_web_data.py verifies this
port against the parameters the C renderer recorded in assets/stars/index.json.
"""

import math

SOLAR_TEFF = 5772.0  # IAU 2015 Resolution B3
SOLAR_MBOL = 4.74    # IAU 2015 Resolution B2
MASK32 = 0xFFFFFFFF


def _interpolate(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return table[-1][1]


# Pecaut & Mamajek (2013, ApJS 208, 9), table v2022.04: dwarf Teff by subtype,
# key = class_index*10 + subclass (O=0 ... Y=9).
SPECTRAL_TEFF = [
    (3, 44900), (5, 41400), (8, 35000), (10, 31400), (12, 23000), (15, 15700),
    (18, 11400), (20, 9700), (22, 8840), (25, 8080), (30, 7220), (32, 6810),
    (35, 6510), (38, 6170), (40, 5920), (42, 5770), (45, 5660), (48, 5490),
    (50, 5280), (52, 5040), (55, 4440), (57, 4050), (60, 3850), (61, 3680),
    (62, 3550), (63, 3400), (64, 3200), (65, 3050), (66, 2800), (67, 2650),
    (68, 2500), (69, 2400), (70, 2250), (72, 2050), (75, 1650), (78, 1400),
    (80, 1300), (85, 1100), (89, 700), (90, 450),
]
BP_RP_TEFF = [
    (-0.35, 31400), (-0.25, 20600), (-0.155, 15700), (-0.06, 11400), (0.00, 9700),
    (0.15, 8590), (0.38, 7220), (0.58, 6510), (0.82, 5770), (0.98, 5280),
    (1.24, 4790), (1.43, 4440), (1.84, 3850), (2.22, 3550), (2.51, 3400),
    (2.87, 3200), (3.30, 3050), (4.00, 2800), (4.40, 2650), (4.70, 2500),
    (4.86, 2400), (5.00, 2300),
]
U1_TABLE = [(3.4771, 0.60), (3.5441, 0.56), (3.7612, 0.47), (3.9031, 0.36), (4.0000, 0.30), (4.4771, 0.20)]
U2_TABLE = [(3.4771, 0.20), (3.5441, 0.24), (3.7612, 0.23), (3.9031, 0.26), (4.0000, 0.25), (4.4771, 0.20)]
GRAN_AMPLITUDE = [(3.4771, 0.07), (3.7612, 0.06), (3.8451, 0.03), (3.9031, 0.012), (4.4771, 0.008)]
CLASSES = "OBAFGKMLTY"
WD_LETTERS = "ABOQZCXP"


def is_white_dwarf(spectral_type):
    return bool(spectral_type) and len(spectral_type) > 1 and spectral_type[0] == "D" \
        and spectral_type[1] in WD_LETTERS


def teff_from_spectral_type(spectral_type):
    if not spectral_type:
        return None
    text = spectral_type.lstrip()
    if len(text) > 1 and text[0] == "D" and text[1] in WD_LETTERS:
        # Sion et al. (1983, ApJ 269, 253): Teff = 50400 / n.
        rest = text[1:]
        index = 0
        while index < len(rest) and rest[index].isalpha():
            index += 1
        digits = ""
        while index < len(rest) and (rest[index].isdigit() or rest[index] == "."):
            digits += rest[index]
            index += 1
        try:
            n = float(digits) if digits and digits[0].isdigit() else 0.0
        except ValueError:
            n = 0.0
        return min(50400.0 / n, 150000.0) if n > 0 else 10000.0
    for prefix in ("usd", "esd", "sd", "d"):
        if text.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)] in CLASSES:
            text = text[len(prefix):]
            break
    if not text or text[0] not in CLASSES:
        return None
    subclass = 5.0
    if len(text) > 1 and text[1].isdigit():
        digits = ""
        for char in text[1:8]:
            if char.isdigit() or char == ".":
                digits += char
            else:
                break
        try:
            subclass = min(float(digits.rstrip(".") or "0"), 9.5)
        except ValueError:
            subclass = 0.0
    return _interpolate(SPECTRAL_TEFF, CLASSES.index(text[0]) * 10.0 + subclass)


def teff_from_bp_rp(bp_rp):
    if bp_rp is None or not math.isfinite(bp_rp) or bp_rp < -0.6 or bp_rp > 6.0:
        return None
    return _interpolate(BP_RP_TEFF, bp_rp)


def bolometric_correction_g(teff):
    """Andrae et al. (2018, A&A 616, A8), eq. 7 / Table 8; valid 3300-8000 K."""
    t = min(max(teff, 3300.0), 8000.0) - SOLAR_TEFF
    hot = (6.000e-02, 6.731e-05, -6.647e-08, 2.859e-11, -7.197e-15)
    cool = (1.749e+00, 1.977e-03, 3.737e-07, -8.966e-11, -4.183e-14)
    a = hot if t + SOLAR_TEFF >= 4000.0 else cool
    return a[0] + t * (a[1] + t * (a[2] + t * (a[3] + t * a[4])))


def bolometric_correction_v(teff):
    """Flower (1996) BC_V with the corrected coefficients of Torres (2010, AJ 140, 1158)."""
    x = math.log10(min(max(teff, 2500.0), 50000.0))
    if x < 3.70:
        return -0.190537291496456e5 + x * (0.155144866764412e5 + x * (-0.421278819301717e4 + x * 0.381476328422343e3))
    if x < 3.90:
        return -0.370510203809015e5 + x * (0.385672629965804e5 + x * (-0.150651486316025e5
               + x * (0.261724637119416e4 + x * -0.170623810323864e3)))
    return -0.118115450538963e6 + x * (0.137145973583929e6 + x * (-0.636233812100225e5
           + x * (0.147412923562646e5 + x * (-0.170587278406872e4 + x * 0.788731721804990e2))))


def mix32(x):
    """lowbias32 (Chris Wellons), identical to hash32 in star.frag."""
    x &= MASK32
    x ^= x >> 16
    x = (x * 0x7FEB352D) & MASK32
    x ^= x >> 15
    x = (x * 0x846CA68B) & MASK32
    x ^= x >> 16
    return x


def star_seed(source_id, identifier):
    if source_id is not None:
        value = int(source_id) & 0xFFFFFFFFFFFFFFFF
        return mix32((value & MASK32) ^ mix32(value >> 32))
    h = 2166136261
    for byte in (identifier or "").encode("utf-8"):
        h = ((h ^ byte) * 16777619) & MASK32
    return mix32(h)


def _finite(value):
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def derive_params(*, identifier, source_id, spectral_type, teff_k, bp_rp,
                  phot_g_mean_mag, parallax_mas, absolute_v_mag, variable_flag, phase=0.0):
    out = {"absolute_mag": None, "absolute_mag_band": None, "bolometric_correction": None,
           "luminosity_solar": None}
    teff = None
    if _finite(teff_k) and 2000.0 <= teff_k <= 60000.0:
        teff, out["teff_source"] = float(teff_k), "gaia_gspphot"
    if teff is None:
        teff = teff_from_spectral_type(spectral_type)
        if teff is not None:
            out["teff_source"] = "spectral_type"
    if teff is None:
        teff = teff_from_bp_rp(bp_rp)
        if teff is not None:
            out["teff_source"] = "bp_rp"
    if teff is None:
        teff, out["teff_source"] = SOLAR_TEFF, "default_solar"
    out["teff_k"] = teff

    if _finite(phot_g_mean_mag) and _finite(parallax_mas) and parallax_mas > 0:
        out["absolute_mag"] = phot_g_mean_mag + 5.0 * math.log10(parallax_mas) - 10.0
        out["absolute_mag_band"] = "G"
        out["bolometric_correction"] = bolometric_correction_v(teff) if teff > 8000.0 \
            else bolometric_correction_g(teff)
        out["radius_source"] = "gaia_g_parallax_bc"
    elif _finite(absolute_v_mag):
        out["absolute_mag"] = float(absolute_v_mag)
        out["absolute_mag_band"] = "V"
        out["bolometric_correction"] = bolometric_correction_v(teff)
        out["radius_source"] = "recons_mv_bc"
    if out["absolute_mag"] is not None:
        m_bol = out["absolute_mag"] + out["bolometric_correction"]
        out["luminosity_solar"] = 10.0 ** (-0.4 * (m_bol - SOLAR_MBOL))
        out["radius_solar"] = math.sqrt(out["luminosity_solar"]) * (SOLAR_TEFF / teff) ** 2
    elif is_white_dwarf(spectral_type):
        out["radius_solar"], out["radius_source"] = 0.012, "white_dwarf_default"
    else:
        out["radius_solar"], out["radius_source"] = (teff / SOLAR_TEFF) ** 1.8, "main_sequence_teff"

    log_r = math.log10(max(out["radius_solar"], 1e-6))
    out["disk_radius_fraction"] = min(max(0.62 + 0.14 * log_r, 0.22), 0.86)
    log_t = math.log10(teff)
    out["limb_darkening_u1"] = _interpolate(U1_TABLE, log_t)
    out["limb_darkening_u2"] = _interpolate(U2_TABLE, log_t)
    out["granulation_amplitude"] = _interpolate(GRAN_AMPLITUDE, log_t)
    out["granulation_frequency"] = min(max(14.0 - 3.0 * log_r, 6.0), 22.0)
    out["variable"] = variable_flag == "VARIABLE"
    out["variability_amplitude"] = 0.08 if out["variable"] else 0.0
    out["phase"] = phase - math.floor(phase)
    out["seed"] = star_seed(source_id, identifier)
    return out
