import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { findStar, findSystem, getDataset } from "@/lib/data";
import StarCard from "@/components/StarCard";
import Portrait from "@/components/Portrait";
import { DataMissing } from "@/components/States";
import { fmt, fmtDistance } from "@/lib/format";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ cns_name: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const system = findSystem((await params).cns_name);
  if (!system) notFound();
  return { title: `${system.common_name ?? system.cns_name} system`, description: `RECONS #${system.rank}: ${system.cns_name} at ${fmtDistance(system.distance_pc, system.distance_ly)}.` };
}

export default async function SystemPage({ params }: Props) {
  if (!getDataset()) return <main><DataMissing /></main>;
  const system = findSystem((await params).cns_name);
  if (!system) notFound();
  const linked = system.components.map((c) => ({ component: c, star: c.star_key ? findStar(c.star_key) : null }));

  return (
    <main>
      <div className="breadcrumbs"><Link href="/nearest">Nearest systems</Link> / #{system.rank}</div>
      <h1>{system.common_name ?? system.system_name ?? system.cns_name}</h1>
      <p className="muted">
        RECONS rank #{system.rank} · {system.cns_name}
        {system.system_name && system.system_name !== system.cns_name ? ` · ${system.system_name}` : ""} ·{" "}
        {fmtDistance(system.distance_pc, system.distance_ly)} · {system.components.length} component
        {system.components.length === 1 ? "" : "s"}
        {system.planet_count > 0 ? ` · ${system.planet_count} known planet${system.planet_count === 1 ? "" : "s"}` : ""}
      </p>

      <div className="grid" style={{ marginTop: 20 }}>
        {linked.map(({ component, star }) =>
          star ? (
            <StarCard key={component.id} star={star} />
          ) : (
            <article key={component.id} className="panel star-card">
              <Portrait src={component.portrait} alt={component.cns_name ?? component.id} teff={component.teff_k} />
              <div>
                <h3>{component.common_name ?? component.cns_name ?? component.id}</h3>
                <dl className="params">
                  <dt>Component</dt><dd>{component.component ?? "—"}</dd>
                  <dt>Spectral type</dt><dd>{component.spectral_type ?? "—"}</dd>
                  <dt>Parallax</dt><dd>{fmt(component.parallax_mas, 2, "mas")} ({component.parallax_reference ?? "RECONS"})</dd>
                  <dt>V</dt><dd>{fmt(component.v_mag, 2)}</dd>
                </dl>
                <p className="muted small">Not linked to a merged catalog row ({component.match_status ?? "unmatched"}).</p>
              </div>
            </article>
          ),
        )}
      </div>

      <h2>RECONS components</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Component</th><th>CNS name</th><th>LHS</th><th>RA (RECONS)</th><th>Dec (RECONS)</th>
              <th className="num">π (mas)</th><th>π ref.</th><th>SpT</th><th className="num">V</th><th className="num">M<sub>V</sub></th>
              <th className="num">Mass (M☉)</th><th>Gaia match</th>
            </tr>
          </thead>
          <tbody>
            {system.components.map((c) => (
              <tr key={c.id}>
                <td>{c.star_key ? <Link href={`/star/${encodeURIComponent(c.star_key)}`}>{c.component ?? "A"}</Link> : c.component ?? "A"}</td>
                <td>{c.cns_name ?? "—"}</td>
                <td>{c.lhs_id ?? "—"}</td>
                <td className="mono">{c.ra_hms ?? "—"}</td>
                <td className="mono">{c.dec_dms ?? "—"}</td>
                <td className="num">{c.parallax_mas !== null ? `${c.parallax_mas.toFixed(2)} ± ${fmt(c.parallax_error_mas, 2)}` : "—"}</td>
                <td>{c.parallax_reference ?? "—"}</td>
                <td>{c.spectral_type ?? "—"}</td>
                <td className="num">{fmt(c.v_mag, 2)}</td>
                <td className="num">{fmt(c.absolute_mag, 2)}</td>
                <td className="num">{fmt(c.mass_solar, 3)}</td>
                <td>{c.match_status ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {system.components.some((c) => c.notes) && (
        <p className="muted small">Notes: {system.components.map((c) => c.notes).filter(Boolean).join(" · ")}</p>
      )}
    </main>
  );
}
