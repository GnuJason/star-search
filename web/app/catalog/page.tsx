import type { Metadata } from "next";
import Link from "next/link";
import { parseCatalogQuery, queryCatalog } from "@/lib/data";
import { DataMissing } from "@/components/States";
import { teffToCss } from "@/lib/color";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Catalog",
  description: "Search and filter the merged RECONS + Gaia DR3 catalog of stars within 25 pc.",
};

type SP = Record<string, string | string[] | undefined>;

const TABS = [
  { source: "all", label: "All stars" },
  { source: "recons", label: "RECONS explorer" },
  { source: "gaia", label: "Gaia DR3 explorer" },
];
const SOURCES = [
  ["all", "All sources"], ["recons", "RECONS"], ["gaia", "Gaia DR3"], ["recons-gaia", "RECONS ∩ Gaia"],
  ["gaia-only", "Gaia only"], ["recons-only", "RECONS only"],
];
const CLASSES = ["O", "B", "A", "F", "G", "K", "M", "L", "T", "D"];
const SORTS = [["distance", "Distance"], ["name", "Name"], ["teff", "Teff"], ["gmag", "G mag"]];

function href(base: SP, patch: SP) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...base, ...patch })) {
    const value = Array.isArray(v) ? v[0] : v;
    if (value !== undefined && value !== "" && !(k === "page" && value === "1")) p.set(k, value);
  }
  const s = p.toString();
  return s ? `/catalog?${s}` : "/catalog";
}

export default async function CatalogPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const query = parseCatalogQuery(sp);
  const result = queryCatalog(query);
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k]?.[0] : (sp[k] as string | undefined)) ?? "";

  return (
    <main>
      <h1>Catalog</h1>
      <p className="muted">
        The merged RECONS + Gaia DR3 catalog (parallax &gt; 40 mas). Spectral class uses the catalog type where
        available, otherwise the class implied by T<sub>eff</sub>.
      </p>
      <nav className="tabs" aria-label="Explorer">
        {TABS.map((t) => (
          <Link key={t.source} href={href({ ...sp, page: undefined }, { source: t.source })} className={query.source === t.source ? "active" : ""}>
            {t.label}
          </Link>
        ))}
      </nav>
      <form className="filters" action="/catalog" method="get">
        <label style={{ flex: "1 1 220px" }}>Search<input className="input" name="q" defaultValue={one("q")} placeholder="Name, alias, source_id, type" /></label>
        <label>Source
          <select className="input" name="source" defaultValue={query.source}>
            {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>Spectral class
          <select className="input" name="spectral" defaultValue={one("spectral").toUpperCase()}>
            <option value="">Any</option>
            {CLASSES.map((c) => <option key={c} value={c}>{c === "D" ? "D (white dwarf)" : c}</option>)}
          </select>
        </label>
        <label>Min pc<input className="input" name="min" type="number" step="0.1" min="0" defaultValue={one("min")} style={{ width: 100 }} /></label>
        <label>Max pc<input className="input" name="max" type="number" step="0.1" min="0" defaultValue={one("max")} style={{ width: 100 }} /></label>
        <label>Sort
          <select className="input" name="sort" defaultValue={query.sort}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>Order
          <select className="input" name="order" defaultValue={query.order}>
            <option value="asc">Ascending</option><option value="desc">Descending</option>
          </select>
        </label>
        <button className="btn primary" type="submit">Apply</button>
        <Link className="btn" href="/catalog">Reset</Link>
      </form>

      {!result ? (
        <DataMissing />
      ) : result.total === 0 ? (
        <div className="panel state">No stars match these filters.</div>
      ) : (
        <>
          <p className="muted small">
            {result.total.toLocaleString()} stars · page {result.page} of {result.pages} ·{" "}
            <a href={`/api/stars?${new URLSearchParams(Object.entries(sp).flatMap(([k, v]) => (typeof v === "string" ? [[k, v]] : []))).toString()}`}>JSON</a>
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th></th><th>Name</th><th>Type</th><th className="num">Class</th><th className="num">Distance (pc)</th>
                  <th className="num">ly</th><th className="num">T<sub>eff</sub> (K)</th><th className="num">G</th><th className="num">V</th><th>Sources</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row) => (
                  <tr key={row.key}>
                    <td>
                      {row.portrait
                        // eslint-disable-next-line @next/next/no-img-element
                        ? <img className="thumb" src={row.portrait} alt="" loading="lazy" />
                        : <span className="swatch" style={{ color: teffToCss(row.teff_k), background: teffToCss(row.teff_k), marginLeft: 11 }} />}
                    </td>
                    <td><Link href={`/star/${encodeURIComponent(row.key)}`}>{row.name}</Link></td>
                    <td>{row.spectral_type ?? "—"}</td>
                    <td className="num">{row.spectral_class}</td>
                    <td className="num">{row.distance_pc.toFixed(3)}</td>
                    <td className="num">{row.distance_ly?.toFixed(2) ?? "—"}</td>
                    <td className="num">{Math.round(row.teff_k)}</td>
                    <td className="num">{row.phot_g_mean_mag?.toFixed(2) ?? "—"}</td>
                    <td className="num">{row.v_mag?.toFixed(2) ?? "—"}</td>
                    <td className="small muted">{row.source_catalogs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pagination" aria-label="Pagination">
            {result.page > 1 ? <Link href={href(sp, { page: "1" })}>« First</Link> : <span className="disabled">« First</span>}
            {result.page > 1 ? <Link href={href(sp, { page: String(result.page - 1) })}>‹ Prev</Link> : <span className="disabled">‹ Prev</span>}
            <span>{result.page} / {result.pages}</span>
            {result.page < result.pages ? <Link href={href(sp, { page: String(result.page + 1) })}>Next ›</Link> : <span className="disabled">Next ›</span>}
            {result.page < result.pages ? <Link href={href(sp, { page: String(result.pages) })}>Last »</Link> : <span className="disabled">Last »</span>}
          </nav>
        </>
      )}
    </main>
  );
}
