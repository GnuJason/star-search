export const PC_TO_LY = 3.2615637771674336;

export function fmt(value: number | null | undefined, digits = 2, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unknown";
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

export function fmtSig(value: number | null | undefined, sig = 3, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unknown";
  const text = Math.abs(value) >= 1e-3 && Math.abs(value) < 1e5 ? String(Number(value.toPrecision(sig))) : value.toExponential(sig - 1);
  return unit ? `${text} ${unit}` : text;
}

export function fmtDistance(pc: number | null | undefined, ly?: number | null): string {
  if (pc === null || pc === undefined || !Number.isFinite(pc)) return "unknown";
  const years = ly ?? pc * PC_TO_LY;
  return `${pc.toFixed(3)} pc · ${years.toFixed(2)} ly`;
}

export function fmtDeg(value: number | null | undefined): string {
  return fmt(value, 5, "°");
}

/** Human label for provenance tokens such as "gaia_gspphot" or "recons". */
export function provenance(token: string | null | undefined): string {
  if (!token) return "unknown";
  const labels: Record<string, string> = {
    gaia: "Gaia DR3",
    recons: "RECONS",
    gaia_gspphot: "Gaia GSP-Phot",
    spectral_type: "spectral type (Pecaut & Mamajek 2013)",
    bp_rp: "BP−RP colour (Pecaut & Mamajek 2013)",
    default_solar: "solar default",
    gaia_g_parallax_bc: "Gaia G + parallax + BC_G (Andrae 2018)",
    recons_mv_bc: "RECONS M_V + BC_V (Flower 1996 / Torres 2010)",
    white_dwarf_default: "white-dwarf default",
    main_sequence_teff: "main-sequence Teff scaling",
    recons_common_name: "RECONS common name",
  };
  return labels[token] ?? token.replaceAll("_", " ");
}

export function displayName(star: { primary_name?: string | null; gaia_designation?: string | null; id: string }): string {
  return star.primary_name ?? star.gaia_designation ?? star.id;
}
