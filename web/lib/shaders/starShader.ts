/**
 * Web port of the canonical star-portrait model.
 *
 *  - WebGL 2 path: uses src/shaders/star.frag and star.vert VERBATIM (copied into
 *    star.generated.ts by scripts/sync_shaders.mjs); only the `#version` line is
 *    stripped because three.js prepends it for GLSL3 materials.
 *  - WebGPU path: STAR_WGSL below is a line-for-line WGSL transliteration of
 *    star.frag (WebGPU cannot consume GLSL). Any change to star.frag must be
 *    mirrored here, in src/render.c, and in scripts/star_params.py.
 */
import type { RenderParams } from "../types";
import { STAR_FRAG, STAR_VERT } from "./star.generated";

const stripVersion = (src: string) => src.replace(/^\s*#version[^\n]*\n/, "");
export const STAR_FRAG_GLSL3 = stripVersion(STAR_FRAG);
export const STAR_VERT_GLSL3 = stripVersion(STAR_VERT);

/** Uniform values for star.frag, as produced by star_params.{c,py}. */
export interface StarUniforms {
  teff: number;
  diskRadius: number;
  u1: number;
  u2: number;
  granAmplitude: number;
  granFrequency: number;
  varAmplitude: number;
  phase: number;
  seed: number; // uint32
}

export function uniformsFromParams(p: RenderParams, phase = p.phase): StarUniforms {
  return {
    teff: p.teff_k,
    diskRadius: p.disk_radius_fraction,
    u1: p.limb_darkening_u1,
    u2: p.limb_darkening_u2,
    granAmplitude: p.granulation_amplitude,
    granFrequency: p.granulation_frequency,
    varAmplitude: p.variability_amplitude,
    phase,
    seed: p.seed >>> 0,
  };
}

/** Helper functions (hash32, planck_rgb, limb darkening, noise) — mirrors star.frag. */
export const STAR_WGSL_HELPERS = /* wgsl */ `
fn ss_hash32(v: u32) -> u32 {
  var x = v;
  x ^= x >> 16u; x *= 0x7feb352du;
  x ^= x >> 15u; x *= 0x846ca68bu;
  x ^= x >> 16u;
  return x;
}
fn ss_hash3(c: vec3<i32>, seed: u32) -> u32 {
  return ss_hash32(u32(c.x) ^ ss_hash32(u32(c.y) ^ ss_hash32(u32(c.z) ^ seed)));
}
fn ss_hash_to_unit(h: u32) -> f32 { return f32(h >> 8u) * (1.0 / 16777216.0); }

fn ss_planck_rgb(teff: f32) -> vec3<f32> {
  let t = clamp(teff, 1667.0, 25000.0);
  let t1 = 1.0e3 / t;
  let t2 = t1 * t1;
  let t3 = t2 * t1;
  let x = select(-3.0258469 * t3 + 2.1070379 * t2 + 0.2226347 * t1 + 0.240390,
                 -0.2661239 * t3 - 0.2343589 * t2 + 0.8776956 * t1 + 0.179910, t <= 4000.0);
  let x2 = x * x;
  let x3 = x2 * x;
  var y = 3.0817580 * x3 - 5.87338670 * x2 + 3.75112997 * x - 0.37001483;
  if (t <= 2222.0) { y = -1.1063814 * x3 - 1.34811020 * x2 + 2.18555832 * x - 0.20219683; }
  else if (t <= 4000.0) { y = -0.9549476 * x3 - 1.37418593 * x2 + 2.09137015 * x - 0.16748867; }
  let xyz = vec3<f32>(x / y, 1.0, (1.0 - x - y) / y);
  var rgb = vec3<f32>( 3.2404542 * xyz.x - 1.5371385 * xyz.y - 0.4985314 * xyz.z,
                      -0.9692660 * xyz.x + 1.8760108 * xyz.y + 0.0415560 * xyz.z,
                       0.0556434 * xyz.x - 0.2040259 * xyz.y + 1.0572252 * xyz.z);
  rgb = max(rgb, vec3<f32>(0.0));
  return rgb / max(max(rgb.r, rgb.g), rgb.b);
}

fn ss_limb_darkening(mu: f32, u: vec2<f32>) -> f32 {
  let m = 1.0 - mu;
  return max(1.0 - u.x * m - u.y * m * m, 0.0);
}

fn ss_value_noise(p: vec3<f32>, seed: u32) -> f32 {
  let fl = floor(p);
  let i = vec3<i32>(fl);
  let f = p - fl;
  let w = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  let n000 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(0, 0, 0), seed));
  let n100 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(1, 0, 0), seed));
  let n010 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(0, 1, 0), seed));
  let n110 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(1, 1, 0), seed));
  let n001 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(0, 0, 1), seed));
  let n101 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(1, 0, 1), seed));
  let n011 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(0, 1, 1), seed));
  let n111 = ss_hash_to_unit(ss_hash3(i + vec3<i32>(1, 1, 1), seed));
  let nx00 = mix(n000, n100, w.x);
  let nx10 = mix(n010, n110, w.x);
  let nx01 = mix(n001, n101, w.x);
  let nx11 = mix(n011, n111, w.x);
  return mix(mix(nx00, nx10, w.y), mix(nx01, nx11, w.y), w.z);
}

fn ss_fbm(p0: vec3<f32>, seed: u32) -> f32 {
  var p = p0;
  var sum = 0.0;
  var amplitude = 0.5;
  for (var octave = 0u; octave < 4u; octave++) {
    sum += amplitude * ss_value_noise(p, seed + octave * 0x9e3779b9u);
    p *= 2.0;
    amplitude *= 0.5;
  }
  return sum / 0.9375;
}

fn ss_srgb_encode(c0: vec3<f32>) -> vec3<f32> {
  let c = clamp(c0, vec3<f32>(0.0), vec3<f32>(1.0));
  return select(12.92 * c, 1.055 * pow(c, vec3<f32>(1.0 / 2.4)) - 0.055, c >= vec3<f32>(0.0031308));
}
`;

/**
 * main() of star.frag as a function of the framebuffer coordinate. WebGPU's
 * fragment position already has its origin at the TOP-left, which is exactly the
 * star.frag pixel convention (py = 0 at the top row), so no flip is needed.
 * The 32-bit seed arrives as two exact 16-bit halves (float uniforms cannot hold
 * all 32-bit integers).
 */
export const STAR_WGSL_MAIN = /* wgsl */ `
fn star_pixel(coord: vec2<f32>, resolution: vec2<f32>, teff: f32, disk_radius: f32,
              ld_coeffs: vec2<f32>, gran: vec2<f32>, variability: vec2<f32>, seed_parts: vec2<f32>) -> vec3<f32> {
  let PI = 3.14159265358979;
  let EXPOSURE = 0.92;
  let LD_CHROMATIC = vec3<f32>(0.85, 1.0, 1.18);
  let HALO_STRENGTH = 0.22;
  let HALO_SCALE = 0.05;
  let STARFIELD_DENSITY = 0.0015;
  let seed = (u32(seed_parts.x) << 16u) | u32(seed_parts.y);

  let pixel = vec2<i32>(floor(coord));
  let half_extent = 0.5 * min(resolution.x, resolution.y);
  let uv = (vec2<f32>(pixel) + 0.5 - 0.5 * resolution) / half_extent;
  let r = length(uv);
  let radius = disk_radius;
  let pixel_size = 1.0 / half_extent;
  let tint = ss_planck_rgb(teff);

  var color = vec3<f32>(0.0);
  let star_hash = ss_hash3(vec3<i32>(pixel, 0), seed ^ 0x51ed270bu);
  if (ss_hash_to_unit(star_hash) < STARFIELD_DENSITY) {
    color = vec3<f32>(0.15 + 0.45 * ss_hash_to_unit(ss_hash32(star_hash)));
  }

  let outside = max(r - radius, 0.0);
  color += tint * HALO_STRENGTH * exp(-outside / HALO_SCALE) * step(radius, r);

  let coverage = clamp((radius - r) / pixel_size + 0.5, 0.0, 1.0);
  if (coverage > 0.0) {
    let rho = min(r / radius, 1.0);
    let mu = sqrt(max(1.0 - rho * rho, 0.0));
    let surface = vec3<f32>(uv / radius, mu);
    let granulation = 1.0 + gran.x * (2.0 * ss_fbm(surface * gran.y, seed) - 1.0);
    let vary = 1.0 + variability.x * sin(2.0 * PI * variability.y);
    let ld = vec3<f32>(ss_limb_darkening(mu, ld_coeffs * LD_CHROMATIC.r),
                       ss_limb_darkening(mu, ld_coeffs * LD_CHROMATIC.g),
                       ss_limb_darkening(mu, ld_coeffs * LD_CHROMATIC.b));
    let disk = tint * ld * (EXPOSURE * granulation * vary);
    color = mix(color, disk, coverage);
  }
  return ss_srgb_encode(color);
}
`;
