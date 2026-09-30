import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { findStar, getDataset } from "@/lib/data";
import StarCard from "@/components/StarCard";
import StarRenderer from "@/components/StarRenderer";
import Portrait from "@/components/Portrait";
import { DataMissing } from "@/components/States";
import type { Star } from "@/lib/types";
import { displayName, fmt, fmtDeg, fmtDistance, fmtSig, provenance } from "@/lib/format";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ source_id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const star = findStar((await params).source_id);
  if (!star) notFound();
  const name = displayName(star);
  return {
    title: name,
    description: `${name}: ${star.spectral_type ?? "unknown type"}, ${fmtDistance(star.distance_pc, star.distance_ly)}, Teff ${Math.round(star.render.teff_k)} K.`,
    openGraph: star.portrait ? { images: [star.portrait] } : undefined,
  };
}

type Row = [label: string, value: React.ReactNode, source?: string | null];

function Section({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <section className="panel">
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <dl className="params">
        {rows.map(([label, value, source]) => (
          <div key={label} style={{ display: "contents" }}>
            <dt>{label}</dt>
            <dd>
              {value}
              {source ? <span className="muted small"> · {provenance(source)}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function sections(star: Star): { title: string; rows: Row[] }[] {
  const r = star.render;
  return [
    {
      title: "Identity & provenance",
      rows: [
        ["Stable ID", <code key="id">{star.id}</code>],
        ["Primary name", star.primary_name ?? "—", star.source_of_name],
        ["Common name", star.common_name ?? "—"],
        ["RECONS name", star.recons_name ?? "—"],
        ["RECONS system", star.recons_system_name ? `${star.recons_system_name} (rank #${star.recons_system_rank})` : "—"],
        ["Component", star.component ?? "—"],
        ["LHS", star.lhs_id ?? "—"],
        ["Gaia source_id", <code key="g">{star.gaia_source_id ?? "—"}</code>],
        ["Gaia designation", star.gaia_designation ?? "—"],
        ["Source catalogs", star.source_catalogs ?? "—"],
        ["Cross-match", star.match_status ? `${star.match_status}${star.match_separation_arcsec !== null ? ` (${fmt(star.match_separation_arcsec, 2)}″, ${star.match_candidates ?? 0} candidates)` : ""}` : "—"],
        ["Match note", star.match_note ?? "—"],
      ],
    },
    {
      title: "Position",
      rows: [
        ["RA", fmtDeg(star.ra_deg), star.source_of_position],
        ["Dec", fmtDeg(star.dec_deg), star.source_of_position],
        ["Reference epoch", star.ref_epoch_jyear ? `J${star.ref_epoch_jyear}` : "—"],
        ["Galactic l, b", `${fmtDeg(star.galactic_longitude_deg)}, ${fmtDeg(star.galactic_latitude_deg)}`],
        ["XYZ (equatorial)", `${fmt(star.x_pc, 3)}, ${fmt(star.y_pc, 3)}, ${fmt(star.z_pc, 3)} pc`],
        ["Proper motion", `${fmt(star.pmra_mas_per_year, 2)}, ${fmt(star.pmdec_mas_per_year, 2)} mas/yr`, star.source_of_proper_motion],
        ["Radial velocity", fmt(star.radial_velocity_km_s, 2, "km/s")],
      ],
    },
    {
      title: "Distance",
      rows: [
        ["Distance", fmtDistance(star.distance_pc, star.distance_ly), star.distance_mode],
        ["Parallax (adopted)", `${fmt(star.parallax_mas, 4, "mas")}${star.parallax_error_mas !== null ? ` ± ${fmt(star.parallax_error_mas, 4)}` : ""}`, star.source_of_parallax],
        ["Parallax (RECONS)", fmt(star.recons_parallax_mas, 2, "mas")],
        ["Parallax (Gaia DR3)", fmt(star.gaia_parallax_mas, 4, "mas")],
        ["RECONS vs Gaia", star.parallax_discrepancy_pct !== null ? `${fmt(star.parallax_discrepancy_pct, 2)} %` : "—"],
      ],
    },
    {
      title: "Photometry & astrophysics",
      rows: [
        ["Spectral type", star.spectral_type ?? "—", star.source_of_spectral_type],
        ["V", fmt(star.v_mag, 2)],
        ["M_V (RECONS)", fmt(star.absolute_mag, 2)],
        ["G / BP / RP", `${fmt(star.phot_g_mean_mag, 3)} / ${fmt(star.phot_bp_mean_mag, 3)} / ${fmt(star.phot_rp_mean_mag, 3)}`],
        ["BP − RP", fmt(star.bp_rp, 3)],
        ["Teff (GSP-Phot)", fmt(star.teff_gspphot_k, 0, "K")],
        ["log g / [M/H]", `${fmt(star.logg_gspphot, 2)} / ${fmt(star.mh_gspphot, 2)}`],
        ["Mass", fmt(star.mass_solar, 3, "M☉")],
        ["RUWE", fmt(star.ruwe, 2)],
        ["Non-single star", star.non_single_star ?? "—"],
        ["Variability flag", star.phot_variable_flag ?? "—"],
        ["Planets", star.planet_count ?? "—"],
      ],
    },
    {
      title: "Render parameters (star_params)",
      rows: [
        ["Teff", fmt(r.teff_k, 0, "K"), r.teff_source],
        ["Absolute mag", r.absolute_mag !== null ? `${fmt(r.absolute_mag, 3)} (${r.absolute_mag_band})` : "—"],
        ["Bolometric corr.", fmt(r.bolometric_correction, 3)],
        ["Luminosity", fmtSig(r.luminosity_solar, 4, "L☉")],
        ["Radius", fmtSig(r.radius_solar, 4, "R☉"), r.radius_source],
        ["Disk radius", fmt(r.disk_radius_fraction, 4)],
        ["Limb darkening u1, u2", `${fmt(r.limb_darkening_u1, 4)}, ${fmt(r.limb_darkening_u2, 4)}`],
        ["Granulation amp / freq", `${fmt(r.granulation_amplitude, 4)} / ${fmt(r.granulation_frequency, 3)}`],
        ["Variability", r.variable ? `amplitude ${fmt(r.variability_amplitude, 3)}, phase ${fmt(r.phase, 3)}` : "none"],
        ["Seed", <code key="s">{r.seed}</code>],
      ],
    },
  ];
}

export default async function StarPage({ params }: Props) {
  if (!getDataset()) return <main><DataMissing /></main>;
  const star = findStar((await params).source_id);
  if (!star) notFound();
  const name = displayName(star);

  return (
    <main>
      <div className="breadcrumbs">
        <Link href="/catalog">Catalog</Link>
        {star.recons_slug && <> / <Link href={`/nearest/${star.recons_slug}`}>{star.recons_system_name ?? "System"}</Link></>} / {name}
      </div>
      <h1>{name}</h1>
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <div>
          <StarRenderer params={star.render} fallbackSrc={star.portrait} label={`${name}, rendered live from catalog parameters`} />
          <p className="muted small">
            Live GPU rendering of <code>star.frag</code> with the parameters below
            {star.render.variable ? " (variability animated)" : ""}. Not to scale; disk size encodes radius.
          </p>
          <div className="star-card compact" style={{ marginTop: 12 }}>
            <Portrait src={star.portrait} alt={`${name} offline portrait`} teff={star.render.teff_k} />
            <p className="muted small" style={{ margin: 0 }}>
              {star.portrait ? "Offline CPU portrait from the star-search CLI (bit-matched model)." : "No offline portrait rendered for this star yet."}{" "}
              <Link href={`/3d-map?focus=${encodeURIComponent(star.key)}`}>Show in 3D map →</Link>
            </p>
          </div>
        </div>
        <StarCard star={star} link={false} />
      </div>
      <div className="grid cols-2" style={{ marginTop: 20 }}>
        {sections(star).map((s) => <Section key={s.title} title={s.title} rows={s.rows} />)}
      </div>
      {star.notes && <p className="muted small">Notes: {star.notes}</p>}
    </main>
  );
}
