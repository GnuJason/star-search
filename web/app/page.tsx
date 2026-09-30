import Link from "next/link";
import { findStar, getDataset } from "@/lib/data";
import Showcase, { type ShowcaseStar } from "@/components/Showcase";
import { DataMissing } from "@/components/States";

export const dynamic = "force-dynamic";

const SHOWCASE = ["Sirius", "alpha Centauri A", "Proxima Centauri", "Procyon", "Barnard's Star", "Sirius B"];

export default function HomePage() {
  const data = getDataset();
  const showcase: ShowcaseStar[] = SHOWCASE.map((name) => findStar(name))
    .filter((s): s is NonNullable<typeof s> => s !== null)
    .map((s) => ({
      key: s.key,
      name: s.primary_name ?? s.id,
      spectral_type: s.spectral_type,
      distance_ly: s.distance_ly,
      portrait: s.portrait,
      render: s.render,
    }));

  return (
    <main>
      <section className="hero">
        <div>
          <span className="badge accent">RECONS × Gaia DR3</span>
          <h1>The nearest stars, rendered from their physics.</h1>
          <p className="lead">
            star-search cross-matches the RECONS 100 nearest star systems with Gaia DR3 and renders every star from
            its catalog parameters — effective temperature, radius, limb darkening, granulation and variability — with
            the same shader the offline renderer uses.
          </p>
          <div className="actions">
            <Link className="btn primary" href="/nearest">The 100 nearest systems</Link>
            <Link className="btn" href="/3d-map">Fly the 3D map</Link>
            <Link className="btn" href="/catalog">Browse the catalog</Link>
          </div>
          {data && (
            <div className="grid cols-3" style={{ marginTop: 28, gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
              <div className="stat"><strong>{data.manifest.counts.stars.toLocaleString()}</strong><span className="muted small">stars within 25 pc</span></div>
              <div className="stat"><strong>{data.recons.length}</strong><span className="muted small">RECONS systems</span></div>
              <div className="stat"><strong>{data.manifest.counts.portraits}</strong><span className="muted small">rendered portraits</span></div>
            </div>
          )}
        </div>
        <div>{showcase.length > 0 ? <Showcase stars={showcase} /> : <DataMissing />}</div>
      </section>

      <section className="grid cols-3" style={{ marginTop: 40 }}>
        <Link href="/nearest" className="panel">
          <h3 style={{ marginTop: 0 }}>Nearest systems</h3>
          <p className="muted">RECONS ranking with distances, components and portraits — from Proxima Centauri outward.</p>
        </Link>
        <Link href="/catalog" className="panel">
          <h3 style={{ marginTop: 0 }}>Catalog explorer</h3>
          <p className="muted">Filter the merged RECONS + Gaia DR3 catalog by spectral class, distance and source.</p>
        </Link>
        <Link href="/3d-map" className="panel">
          <h3 style={{ marginTop: 0 }}>3D map</h3>
          <p className="muted">Every star within 25 pc, placed in parsecs, coloured by temperature and sized by luminosity.</p>
        </Link>
      </section>
    </main>
  );
}
