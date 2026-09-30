/** Shader parameters derived exactly as in src/star_params.c (see docs/renderer.md). */
export interface RenderParams {
  teff_k: number;
  teff_source: "gaia_gspphot" | "spectral_type" | "bp_rp" | "default_solar";
  absolute_mag: number | null;
  absolute_mag_band: "G" | "V" | null;
  bolometric_correction: number | null;
  luminosity_solar: number | null;
  radius_solar: number;
  radius_source: string;
  disk_radius_fraction: number;
  limb_darkening_u1: number;
  limb_darkening_u2: number;
  granulation_amplitude: number;
  granulation_frequency: number;
  variable: boolean;
  variability_amplitude: number;
  phase: number;
  seed: number;
}

/** One merged_catalog.parquet row (docs/data-schemas.md) plus web fields. */
export interface Star {
  id: string;
  key: string;
  primary_name: string | null;
  common_name: string | null;
  recons_name: string | null;
  recons_id: string | null;
  recons_system_rank: number | null;
  recons_system_name: string | null;
  recons_slug: string | null;
  component: string | null;
  lhs_id: string | null;
  gaia_source_id: string | null;
  gaia_designation: string | null;
  source_of_name: string | null;
  match_status: string | null;
  match_separation_arcsec: number | null;
  match_candidates: number | null;
  match_note: string | null;
  ra_deg: number;
  dec_deg: number;
  ref_epoch_jyear: number | null;
  source_of_position: string | null;
  parallax_mas: number | null;
  parallax_error_mas: number | null;
  source_of_parallax: string | null;
  recons_parallax_mas: number | null;
  gaia_parallax_mas: number | null;
  parallax_discrepancy_pct: number | null;
  distance_pc: number;
  distance_ly: number | null;
  distance_mode: string | null;
  x_pc: number;
  y_pc: number;
  z_pc: number;
  galactic_longitude_deg: number | null;
  galactic_latitude_deg: number | null;
  pmra_mas_per_year: number | null;
  pmdec_mas_per_year: number | null;
  source_of_proper_motion: string | null;
  radial_velocity_km_s: number | null;
  spectral_type: string | null;
  source_of_spectral_type: string | null;
  v_mag: number | null;
  absolute_mag: number | null;
  mass_solar: number | null;
  phot_g_mean_mag: number | null;
  phot_bp_mean_mag: number | null;
  phot_rp_mean_mag: number | null;
  bp_rp: number | null;
  teff_gspphot_k: number | null;
  logg_gspphot: number | null;
  mh_gspphot: number | null;
  ruwe: number | null;
  non_single_star: number | null;
  phot_variable_flag: string | null;
  planet_count: number | null;
  notes: string | null;
  source_catalogs: string | null;
  aliases: string[];
  portrait: string | null;
  render: RenderParams;
}

/** Compact row for tables, lists and search results. */
export interface StarSummary {
  key: string;
  id: string;
  name: string;
  spectral_type: string | null;
  distance_pc: number;
  distance_ly: number | null;
  teff_k: number;
  teff_source: string;
  phot_g_mean_mag: number | null;
  v_mag: number | null;
  source_catalogs: string | null;
  recons_slug: string | null;
  portrait: string | null;
}

export interface ReconsComponent {
  id: string;
  cns_name: string | null;
  component: string | null;
  common_name: string | null;
  lhs_id: string | null;
  ra_hms: string | null;
  dec_dms: string | null;
  parallax_mas: number | null;
  parallax_error_mas: number | null;
  parallax_reference: string | null;
  distance_pc: number | null;
  distance_ly: number | null;
  spectral_type: string | null;
  v_mag: number | null;
  absolute_mag: number | null;
  mass_solar: number | null;
  notes: string | null;
  star_key: string | null;
  portrait: string | null;
  match_status: string | null;
  teff_k: number | null;
}

export interface ReconsSystem {
  rank: number;
  cns_name: string;
  slug: string;
  system_name: string | null;
  common_name: string | null;
  distance_pc: number | null;
  distance_ly: number | null;
  planet_count: number;
  components: ReconsComponent[];
}

export interface Manifest {
  schema_version: number;
  generated_on: string;
  sources: Record<string, { file: string; rows: number | null; sha256?: string; systems?: number }>;
  merged_catalog_metadata: Record<string, string>;
  counts: Record<string, number>;
  points: { file: string; stride: number; fields: string[]; flags: Record<string, number> };
  render_parameter_parity: { checked: number; mismatches: number };
  attribution: string;
}

export interface PointsIndex {
  count: number;
  stride: number;
  fields: string[];
  keys: string[];
  names: (string | null)[];
  spectral_types: (string | null)[];
  distances_pc: number[];
}
