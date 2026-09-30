/**
 * Temperature -> display colour, the same formula as planck_rgb() in
 * src/shaders/star.frag: Kim et al. (2002) Planckian-locus fit in CIE xy,
 * XYZ -> linear sRGB (IEC 61966-2-1), normalised to a peak channel of 1.
 */
export function planckRgbLinear(teff: number): [number, number, number] {
  const t = Math.min(Math.max(teff, 1667), 25000);
  const t1 = 1e3 / t, t2 = t1 * t1, t3 = t2 * t1;
  const x = t <= 4000
    ? -0.2661239 * t3 - 0.2343589 * t2 + 0.8776956 * t1 + 0.17991
    : -3.0258469 * t3 + 2.1070379 * t2 + 0.2226347 * t1 + 0.24039;
  const x2 = x * x, x3 = x2 * x;
  const y = t <= 2222 ? -1.1063814 * x3 - 1.3481102 * x2 + 2.18555832 * x - 0.20219683
    : t <= 4000 ? -0.9549476 * x3 - 1.37418593 * x2 + 2.09137015 * x - 0.16748867
    : 3.081758 * x3 - 5.8733867 * x2 + 3.75112997 * x - 0.37001483;
  const X = x / y, Y = 1, Z = (1 - x - y) / y;
  const rgb: [number, number, number] = [
    Math.max(3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z, 0),
    Math.max(-0.969266 * X + 1.8760108 * Y + 0.041556 * Z, 0),
    Math.max(0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z, 0),
  ];
  const peak = Math.max(...rgb) || 1;
  return [rgb[0] / peak, rgb[1] / peak, rgb[2] / peak];
}

const encode = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);

export function teffToCss(teff: number | null | undefined): string {
  const [r, g, b] = planckRgbLinear(teff ?? 5772).map((c) => Math.round(encode(Math.min(Math.max(c, 0), 1)) * 255));
  return `rgb(${r}, ${g}, ${b})`;
}
