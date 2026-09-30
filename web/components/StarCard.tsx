import Link from "next/link";
import type { Star } from "@/lib/types";
import { fmt, fmtDistance, provenance, displayName } from "@/lib/format";
import { teffToCss } from "@/lib/color";
import Portrait from "./Portrait";

/**
 * Reusable star card: portrait, name/aliases, distance (pc + ly), spectral type, Teff,
 * magnitudes, parallax and provenance of each value.
 */
export default function StarCard({ star, compact = false, link = true }: { star: Star; compact?: boolean; link?: boolean }) {
  const name = displayName(star);
  const aliases = star.aliases.filter((a) => a !== name).slice(0, compact ? 3 : 12);
  const href = `/star/${encodeURIComponent(star.key)}`;
  return (
    <article className={`panel star-card${compact ? " compact" : ""}`}>
      <Portrait src={star.portrait} alt={`${name} portrait`} teff={star.render.teff_k} />
      <div>
        <h3>
          {link ? <Link href={href}>{name}</Link> : name}{" "}
          <span className="swatch" style={{ color: teffToCss(star.render.teff_k), background: teffToCss(star.render.teff_k) }} />
        </h3>
        {aliases.length > 0 && <div className="muted small">{aliases.join(" · ")}</div>}
        <dl className="params">
          <dt>Distance</dt>
          <dd>{fmtDistance(star.distance_pc, star.distance_ly)}</dd>
          <dt>Spectral type</dt>
          <dd>
            {star.spectral_type ?? "—"}{" "}
            {star.spectral_type && <span className="muted small">({provenance(star.source_of_spectral_type)})</span>}
          </dd>
          <dt>T<sub>eff</sub></dt>
          <dd>
            {fmt(star.render.teff_k, 0, "K")} <span className="muted small">({provenance(star.render.teff_source)})</span>
          </dd>
          {!compact && (
            <>
              <dt>Magnitudes</dt>
              <dd>
                V {fmt(star.v_mag, 2)} · G {fmt(star.phot_g_mean_mag, 3)} · BP−RP {fmt(star.bp_rp, 3)}
              </dd>
              <dt>Parallax</dt>
              <dd>
                {fmt(star.parallax_mas, 3, "mas")}
                {star.parallax_error_mas !== null && ` ± ${fmt(star.parallax_error_mas, 3)}`}{" "}
                <span className="muted small">({provenance(star.source_of_parallax)})</span>
              </dd>
              <dt>Gaia source_id</dt>
              <dd className="mono">{star.gaia_source_id ?? "— (not in Gaia DR3 subset)"}</dd>
              <dt>RECONS name</dt>
              <dd>
                {star.recons_name ? (
                  star.recons_slug ? <Link href={`/nearest/${star.recons_slug}`}>{star.recons_name}</Link> : star.recons_name
                ) : (
                  "—"
                )}
              </dd>
            </>
          )}
        </dl>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          {(star.source_catalogs ?? "").split(/\s*[+,;]\s*/).filter(Boolean).map((s) => (
            <span key={s} className="badge accent">{provenance(s)}</span>
          ))}
          {star.render.variable && <span className="badge warm">variable</span>}
        </div>
      </div>
    </article>
  );
}
