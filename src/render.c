/* CPU evaluator for src/shaders/star.frag.
 *
 * SYNC RULE: every function below mirrors the GLSL function of the same name
 * in star.frag, using 32-bit float arithmetic like a highp GPU would. The file
 * is compiled with -ffp-contract=off (see CMakeLists.txt) so the compiler does
 * not fuse multiply-adds; together with integer hashing and a fixed evaluation
 * order this makes the output byte-identical for identical inputs on a given
 * platform/libm. GPU output of the same shader matches to within rounding
 * (visually identical), not bit-for-bit. */
#include "render.h"

#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#include "third_party/stb_image_write.h"

typedef struct { float x, y, z; } vec3;

static const float PI = 3.14159265358979f;
static const float EXPOSURE = 0.92f;
static const vec3 LD_CHROMATIC = {0.85f, 1.0f, 1.18f};
static const float HALO_STRENGTH = 0.22f;
static const float HALO_SCALE = 0.05f;
static const float STARFIELD_DENSITY = 0.0015f;

static float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
static float mixf(float a, float b, float t) { return a * (1.0f - t) + b * t; }   /* GLSL mix */
static float stepf(float edge, float x) { return x < edge ? 0.0f : 1.0f; }       /* GLSL step */

static uint32_t hash32(uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU;
    x ^= x >> 15; x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}
static uint32_t hash3(int32_t x, int32_t y, int32_t z, uint32_t seed) {
    return hash32((uint32_t)x ^ hash32((uint32_t)y ^ hash32((uint32_t)z ^ seed)));
}
static float hash_to_unit(uint32_t h) { return (float)(h >> 8) * (1.0f / 16777216.0f); }

static vec3 planck_rgb(float teff) {
    float t = clampf(teff, 1667.0f, 25000.0f);
    float t1 = 1.0e3f / t;
    float t2 = t1 * t1, t3 = t2 * t1;
    float x = t <= 4000.0f
        ? -0.2661239f * t3 - 0.2343589f * t2 + 0.8776956f * t1 + 0.179910f
        : -3.0258469f * t3 + 2.1070379f * t2 + 0.2226347f * t1 + 0.240390f;
    float x2 = x * x, x3 = x2 * x;
    float y = t <= 2222.0f ? -1.1063814f * x3 - 1.34811020f * x2 + 2.18555832f * x - 0.20219683f
            : t <= 4000.0f ? -0.9549476f * x3 - 1.37418593f * x2 + 2.09137015f * x - 0.16748867f
            :                 3.0817580f * x3 - 5.87338670f * x2 + 3.75112997f * x - 0.37001483f;
    vec3 xyz = {x / y, 1.0f, (1.0f - x - y) / y};
    vec3 rgb = {
         3.2404542f * xyz.x - 1.5371385f * xyz.y - 0.4985314f * xyz.z,
        -0.9692660f * xyz.x + 1.8760108f * xyz.y + 0.0415560f * xyz.z,
         0.0556434f * xyz.x - 0.2040259f * xyz.y + 1.0572252f * xyz.z,
    };
    rgb.x = fmaxf(rgb.x, 0.0f);
    rgb.y = fmaxf(rgb.y, 0.0f);
    rgb.z = fmaxf(rgb.z, 0.0f);
    float peak = fmaxf(fmaxf(rgb.x, rgb.y), rgb.z);
    rgb.x /= peak;
    rgb.y /= peak;
    rgb.z /= peak;
    return rgb;
}

static float limb_darkening(float mu, float u1, float u2) {
    float m = 1.0f - mu;
    return fmaxf(1.0f - u1 * m - u2 * m * m, 0.0f);
}

static float value_noise(vec3 p, uint32_t seed) {
    float flx = floorf(p.x), fly = floorf(p.y), flz = floorf(p.z);
    int32_t ix = (int32_t)flx, iy = (int32_t)fly, iz = (int32_t)flz;
    float fx = p.x - flx, fy = p.y - fly, fz = p.z - flz;
    float wx = fx * fx * fx * (fx * (fx * 6.0f - 15.0f) + 10.0f);
    float wy = fy * fy * fy * (fy * (fy * 6.0f - 15.0f) + 10.0f);
    float wz = fz * fz * fz * (fz * (fz * 6.0f - 15.0f) + 10.0f);
    float n000 = hash_to_unit(hash3(ix + 0, iy + 0, iz + 0, seed));
    float n100 = hash_to_unit(hash3(ix + 1, iy + 0, iz + 0, seed));
    float n010 = hash_to_unit(hash3(ix + 0, iy + 1, iz + 0, seed));
    float n110 = hash_to_unit(hash3(ix + 1, iy + 1, iz + 0, seed));
    float n001 = hash_to_unit(hash3(ix + 0, iy + 0, iz + 1, seed));
    float n101 = hash_to_unit(hash3(ix + 1, iy + 0, iz + 1, seed));
    float n011 = hash_to_unit(hash3(ix + 0, iy + 1, iz + 1, seed));
    float n111 = hash_to_unit(hash3(ix + 1, iy + 1, iz + 1, seed));
    float nx00 = mixf(n000, n100, wx), nx10 = mixf(n010, n110, wx);
    float nx01 = mixf(n001, n101, wx), nx11 = mixf(n011, n111, wx);
    return mixf(mixf(nx00, nx10, wy), mixf(nx01, nx11, wy), wz);
}

static float fbm(vec3 p, uint32_t seed) {
    float sum = 0.0f, amplitude = 0.5f;
    for (uint32_t octave = 0; octave < 4; ++octave) {
        sum += amplitude * value_noise(p, seed + octave * 0x9e3779b9U);
        p.x *= 2.0f;
        p.y *= 2.0f;
        p.z *= 2.0f;
        amplitude *= 0.5f;
    }
    return sum / 0.9375f;
}

static float srgb_encode(float c) {
    c = clampf(c, 0.0f, 1.0f);
    return mixf(12.92f * c, 1.055f * powf(c, 1.0f / 2.4f) - 0.055f, stepf(0.0031308f, c));
}

static uint8_t quantize(float c) {   /* matches an 8-bit UNORM render target */
    return (uint8_t)floorf(clampf(c, 0.0f, 1.0f) * 255.0f + 0.5f);
}

/* Mirror of main() in star.frag for one pixel (py = 0 is the top row). */
static void render_pixel(const star_render_params *params, float width, float height,
                         int32_t px, int32_t py, vec3 tint, uint8_t *out) {
    float half_extent = 0.5f * fminf(width, height);
    float uvx = ((float)px + 0.5f - 0.5f * width) / half_extent;
    float uvy = ((float)py + 0.5f - 0.5f * height) / half_extent;
    float r = sqrtf(uvx * uvx + uvy * uvy);
    float radius = (float)params->disk_radius;
    float pixel_size = 1.0f / half_extent;
    uint32_t seed = params->seed;

    vec3 color = {0.0f, 0.0f, 0.0f};
    uint32_t star_hash = hash3(px, py, 0, seed ^ 0x51ed270bU);
    if (hash_to_unit(star_hash) < STARFIELD_DENSITY) {
        float level = 0.15f + 0.45f * hash_to_unit(hash32(star_hash));
        color.x = color.y = color.z = level;
    }

    float outside = fmaxf(r - radius, 0.0f);
    float halo = HALO_STRENGTH * expf(-outside / HALO_SCALE) * stepf(radius, r);
    color.x += tint.x * halo;
    color.y += tint.y * halo;
    color.z += tint.z * halo;

    float coverage = clampf((radius - r) / pixel_size + 0.5f, 0.0f, 1.0f);
    if (coverage > 0.0f) {
        float rho = fminf(r / radius, 1.0f);
        float mu = sqrtf(fmaxf(1.0f - rho * rho, 0.0f));
        float frequency = (float)params->granulation_frequency;
        vec3 surface = {uvx / radius * frequency, uvy / radius * frequency, mu * frequency};
        float granulation = 1.0f + (float)params->granulation_amplitude *
            (2.0f * fbm(surface, seed) - 1.0f);
        float variability = 1.0f + (float)params->variability_amplitude *
            sinf(2.0f * PI * (float)params->phase);
        float u1 = (float)params->limb_u1, u2 = (float)params->limb_u2;
        float scale = EXPOSURE * granulation * variability;
        vec3 disk = {
            tint.x * limb_darkening(mu, u1 * LD_CHROMATIC.x, u2 * LD_CHROMATIC.x) * scale,
            tint.y * limb_darkening(mu, u1 * LD_CHROMATIC.y, u2 * LD_CHROMATIC.y) * scale,
            tint.z * limb_darkening(mu, u1 * LD_CHROMATIC.z, u2 * LD_CHROMATIC.z) * scale,
        };
        color.x = mixf(color.x, disk.x, coverage);
        color.y = mixf(color.y, disk.y, coverage);
        color.z = mixf(color.z, disk.z, coverage);
    }
    out[0] = quantize(srgb_encode(color.x));
    out[1] = quantize(srgb_encode(color.y));
    out[2] = quantize(srgb_encode(color.z));
}

void render_star(const star_render_params *params, int width, int height, uint8_t *rgb) {
    vec3 tint = planck_rgb((float)params->teff_k);
    for (int32_t py = 0; py < height; ++py) {
        for (int32_t px = 0; px < width; ++px) {
            render_pixel(params, (float)width, (float)height, px, py, tint,
                         rgb + ((size_t)py * (size_t)width + (size_t)px) * 3);
        }
    }
}

bool make_parent_directories(const char *path) {
    char *copy = strdup(path);
    if (!copy) {
        return false;
    }
    char *slash = strrchr(copy, '/');
    bool ok = true;
    if (slash && slash != copy) {
        *slash = '\0';
        for (char *cursor = copy + 1; ok; ++cursor) {
            if (*cursor == '/' || *cursor == '\0') {
                char saved = *cursor;
                *cursor = '\0';
                if (mkdir(copy, 0755) != 0 && errno != EEXIST) {
                    ok = false;
                }
                *cursor = saved;
                if (!saved) {
                    break;
                }
            }
        }
    }
    free(copy);
    return ok;
}

bool write_png(const char *path, int width, int height, const uint8_t *rgb) {
    if (!make_parent_directories(path)) {
        return false;
    }
    /* stb's built-in zlib is deterministic, so identical pixels give identical files. */
    return stbi_write_png(path, width, height, 3, rgb, width * 3) != 0;
}
