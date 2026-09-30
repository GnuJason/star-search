#version 300 es
// star-search star-portrait fragment shader — CANONICAL VISUAL MODEL.
//
// This file is the single source of truth for how a star portrait looks.
// src/render.c contains a CPU evaluator (render_pixel) that implements the
// SAME math line-for-line so the CLI can render headless, offline and
// deterministically without a GPU. Any change here MUST be mirrored in
// src/render.c (and vice versa); tests/test_render.py pins the CPU output.
// The Phase 3 website reuses this shader (WebGL2 / GLSL ES 3.00).
//
// Physical parameters (teff, radius, limb-darkening coefficients, ...) are
// derived on the host from catalog data — see src/star_params.c and
// docs/renderer.md — and passed in as uniforms.
//
// Pixel convention: integer pixel (px, py) with py = 0 at the TOP row and the
// sample taken at the pixel centre, identical to the CPU evaluator.
precision highp float;
precision highp int;

uniform vec2  u_resolution;      // output size in pixels (width, height)
uniform float u_teff;            // effective temperature, K
uniform float u_disk_radius;     // stellar disk radius as a fraction of min(width,height)/2
uniform vec2  u_limb_darkening;  // quadratic law coefficients (u1, u2) at the green channel
uniform float u_gran_amplitude;  // granulation contrast (fractional intensity modulation)
uniform float u_gran_frequency;  // granulation cells across one stellar radius
uniform float u_var_amplitude;   // variability amplitude (fractional), 0 for non-variables
uniform float u_phase;           // variability phase in [0, 1)
uniform uint  u_seed;            // 32-bit seed derived from the Gaia source_id / catalog id

out vec4 frag_color;

const float PI = 3.14159265358979;
const float EXPOSURE = 0.92;              // disk-centre intensity after normalisation
const vec3  LD_CHROMATIC = vec3(0.85, 1.0, 1.18);  // limb darkening is stronger in the blue
const float HALO_STRENGTH = 0.22;
const float HALO_SCALE = 0.05;            // e-folding length of the halo, in half-image units
const float STARFIELD_DENSITY = 0.0015;   // probability that a background pixel hosts a star

// ---------------------------------------------------------------------------
// Integer hash: "lowbias32" by Chris Wellons (public domain),
// https://nullprogram.com/blog/2018/07/31/ . Pure 32-bit integer math, so the
// GPU and CPU produce bit-identical values.
uint hash32(uint x) {
    x ^= x >> 16; x *= 0x7feb352du;
    x ^= x >> 15; x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}
uint hash3(ivec3 c, uint seed) {
    return hash32(uint(c.x) ^ hash32(uint(c.y) ^ hash32(uint(c.z) ^ seed)));
}
float hash_to_unit(uint h) { return float(h >> 8) * (1.0 / 16777216.0); }  // [0, 1), 24 bits

// ---------------------------------------------------------------------------
// Temperature -> colour.
// Planckian locus in CIE 1931 xy from the cubic-spline fit of
// Kim, Kim, Lee & Park (2002), "Design of advanced color temperature control
// system for HDTV applications", J. Korean Phys. Soc. 41, 865 (valid 1667-25000 K;
// clamped outside). xyY (Y = 1) -> XYZ -> linear sRGB with the IEC 61966-2-1
// matrix, then normalised so the brightest channel is 1 (chromaticity only;
// luminosity is handled by the disk radius, not by brightness).
vec3 planck_rgb(float teff) {
    float t = clamp(teff, 1667.0, 25000.0);
    float t1 = 1.0e3 / t;            // work in kK^-1 to keep float precision
    float t2 = t1 * t1, t3 = t2 * t1;
    float x = t <= 4000.0
        ? -0.2661239 * t3 - 0.2343589 * t2 + 0.8776956 * t1 + 0.179910
        : -3.0258469 * t3 + 2.1070379 * t2 + 0.2226347 * t1 + 0.240390;
    float x2 = x * x, x3 = x2 * x;
    float y = t <= 2222.0 ? -1.1063814 * x3 - 1.34811020 * x2 + 2.18555832 * x - 0.20219683
            : t <= 4000.0 ? -0.9549476 * x3 - 1.37418593 * x2 + 2.09137015 * x - 0.16748867
            :                3.0817580 * x3 - 5.87338670 * x2 + 3.75112997 * x - 0.37001483;
    vec3 xyz = vec3(x / y, 1.0, (1.0 - x - y) / y);
    vec3 rgb = vec3( 3.2404542 * xyz.x - 1.5371385 * xyz.y - 0.4985314 * xyz.z,
                    -0.9692660 * xyz.x + 1.8760108 * xyz.y + 0.0415560 * xyz.z,
                     0.0556434 * xyz.x - 0.2040259 * xyz.y + 1.0572252 * xyz.z);
    rgb = max(rgb, vec3(0.0));
    return rgb / max(max(rgb.r, rgb.g), rgb.b);
}

// Quadratic limb-darkening law (Kopal 1950; coefficients in the style of
// Claret 2000, A&A 363, 1081):  I(mu)/I(1) = 1 - u1 (1 - mu) - u2 (1 - mu)^2.
float limb_darkening(float mu, vec2 u) {
    float m = 1.0 - mu;
    return max(1.0 - u.x * m - u.y * m * m, 0.0);
}

// 3-D value noise with quintic (C2) interpolation, and a 4-octave fBm.
float value_noise(vec3 p, uint seed) {
    vec3 fl = floor(p);
    ivec3 i = ivec3(fl);
    vec3 f = p - fl;
    vec3 w = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    float n000 = hash_to_unit(hash3(i + ivec3(0, 0, 0), seed));
    float n100 = hash_to_unit(hash3(i + ivec3(1, 0, 0), seed));
    float n010 = hash_to_unit(hash3(i + ivec3(0, 1, 0), seed));
    float n110 = hash_to_unit(hash3(i + ivec3(1, 1, 0), seed));
    float n001 = hash_to_unit(hash3(i + ivec3(0, 0, 1), seed));
    float n101 = hash_to_unit(hash3(i + ivec3(1, 0, 1), seed));
    float n011 = hash_to_unit(hash3(i + ivec3(0, 1, 1), seed));
    float n111 = hash_to_unit(hash3(i + ivec3(1, 1, 1), seed));
    float nx00 = mix(n000, n100, w.x), nx10 = mix(n010, n110, w.x);
    float nx01 = mix(n001, n101, w.x), nx11 = mix(n011, n111, w.x);
    return mix(mix(nx00, nx10, w.y), mix(nx01, nx11, w.y), w.z);
}
float fbm(vec3 p, uint seed) {
    float sum = 0.0, amplitude = 0.5;
    for (int octave = 0; octave < 4; ++octave) {
        sum += amplitude * value_noise(p, seed + uint(octave) * 0x9e3779b9u);
        p *= 2.0;
        amplitude *= 0.5;
    }
    return sum / 0.9375;   // normalise the 4-octave amplitude sum to [0, 1)
}

vec3 srgb_encode(vec3 c) {   // IEC 61966-2-1 transfer function
    c = clamp(c, 0.0, 1.0);
    return mix(12.92 * c, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

void main() {
    ivec2 pixel = ivec2(int(gl_FragCoord.x), int(u_resolution.y) - 1 - int(gl_FragCoord.y));
    float half_extent = 0.5 * min(u_resolution.x, u_resolution.y);
    vec2 uv = (vec2(pixel) + 0.5 - 0.5 * u_resolution) / half_extent;   // [-1, 1] on the short axis
    float r = length(uv);
    float radius = u_disk_radius;
    float pixel_size = 1.0 / half_extent;
    vec3 tint = planck_rgb(u_teff);

    // Background: black sky with a sparse, seeded field of faint point stars.
    vec3 color = vec3(0.0);
    uint star_hash = hash3(ivec3(pixel, 0), u_seed ^ 0x51ed270bu);
    if (hash_to_unit(star_hash) < STARFIELD_DENSITY) {
        color = vec3(0.15 + 0.45 * hash_to_unit(hash32(star_hash)));
    }

    // Soft photographic halo around the disk (not a physical corona).
    float outside = max(r - radius, 0.0);
    color += tint * HALO_STRENGTH * exp(-outside / HALO_SCALE) * step(radius, r);

    // Stellar disk.
    float coverage = clamp((radius - r) / pixel_size + 0.5, 0.0, 1.0);   // 1-pixel analytic AA
    if (coverage > 0.0) {
        float rho = min(r / radius, 1.0);
        float mu = sqrt(max(1.0 - rho * rho, 0.0));
        vec3 surface = vec3(uv / radius, mu);                      // point on the unit sphere
        float granulation = 1.0 + u_gran_amplitude *
            (2.0 * fbm(surface * u_gran_frequency, u_seed) - 1.0);
        float variability = 1.0 + u_var_amplitude * sin(2.0 * PI * u_phase);
        vec3 ld = vec3(limb_darkening(mu, u_limb_darkening * LD_CHROMATIC.r),
                       limb_darkening(mu, u_limb_darkening * LD_CHROMATIC.g),
                       limb_darkening(mu, u_limb_darkening * LD_CHROMATIC.b));
        vec3 disk = tint * ld * (EXPOSURE * granulation * variability);
        color = mix(color, disk, coverage);
    }
    frag_color = vec4(srgb_encode(color), 1.0);
}
