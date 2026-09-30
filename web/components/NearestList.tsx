"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { ReconsSystem } from "@/lib/types";
import { teffToCss } from "@/lib/color";
import Portrait from "./Portrait";

/** RECONS 100 nearest systems with instant client-side filtering. */
export default function NearestList({ systems }: { systems: ReconsSystem[] }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return systems;
    return systems.filter((s) =>
      [s.cns_name, s.system_name, s.common_name, String(s.rank), ...s.components.flatMap((c) => [c.cns_name, c.common_name, c.lhs_id, c.spectral_type])]
        .some((t) => t?.toLowerCase().includes(q)),
    );
  }, [systems, query]);

  return (
    <>
      <div className="filters">
        <label style={{ flex: "1 1 320px" }}>
          Filter systems
          <input className="input" type="search" placeholder="Name, GJ/LHS number, spectral type…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <span className="muted small">{filtered.length} of {systems.length} systems</span>
      </div>
      {filtered.length === 0 ? (
        <div className="panel state">No systems match “{query}”.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>System</th>
                <th>Components</th>
                <th className="num">Distance (pc)</th>
                <th className="num">Distance (ly)</th>
                <th className="num">Planets</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.slug}>
                  <td className="num">{s.rank}</td>
                  <td>
                    <Link href={`/nearest/${s.slug}`}>{s.common_name ?? s.system_name ?? s.cns_name}</Link>
                    <div className="muted small">{s.cns_name}</div>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      {s.components.map((c) => {
                        const inner = (
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                            <Portrait src={c.portrait} alt={c.common_name ?? c.cns_name ?? c.id} teff={c.teff_k} className="portrait thumb" />
                            <span>
                              {c.component ?? "A"} <span className="muted small">{c.spectral_type ?? "—"}</span>
                            </span>
                            <span className="swatch" style={{ color: teffToCss(c.teff_k), background: teffToCss(c.teff_k) }} />
                          </span>
                        );
                        return c.star_key ? (
                          <Link key={c.id} href={`/star/${encodeURIComponent(c.star_key)}`} title={c.common_name ?? c.cns_name ?? ""}>{inner}</Link>
                        ) : (
                          <span key={c.id}>{inner}</span>
                        );
                      })}
                    </div>
                  </td>
                  <td className="num">{s.distance_pc?.toFixed(3) ?? "—"}</td>
                  <td className="num">{s.distance_ly?.toFixed(2) ?? "—"}</td>
                  <td className="num">{s.planet_count || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
