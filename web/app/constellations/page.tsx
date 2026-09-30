import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Constellations (coming soon)" };

export default function ConstellationsPage() {
  return (
    <main>
      <span className="badge warm">Coming soon</span>
      <h1>Constellations</h1>
      <div className="panel">
        <p>
          Constellation figures and boundaries are not part of this release. The nearest stars are spread across the
          whole sky and most are far too faint to belong to a traditional figure, so this view needs a separate
          bright-star dataset (IAU boundaries + stick figures), which is planned for a later phase.
        </p>
        <p className="muted">
          Meanwhile, explore the <Link href="/3d-map">3D map</Link> or the <Link href="/nearest">nearest systems</Link>.
        </p>
      </div>
    </main>
  );
}
