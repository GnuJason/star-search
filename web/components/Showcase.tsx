"use client";

import { useState } from "react";
import Link from "next/link";
import type { RenderParams } from "@/lib/types";
import { teffToCss } from "@/lib/color";
import StarRenderer from "./StarRenderer";

export interface ShowcaseStar {
  key: string;
  name: string;
  spectral_type: string | null;
  distance_ly: number | null;
  portrait: string | null;
  render: RenderParams;
}

/** Landing-page showcase: live GPU rendering of star.frag for a few well-known stars. */
export default function Showcase({ stars }: { stars: ShowcaseStar[] }) {
  const [active, setActive] = useState(0);
  const star = stars[active];
  if (!star) return null;
  return (
    <div>
      <StarRenderer key={star.key} params={star.render} fallbackSrc={star.portrait} label={`${star.name}, rendered live`} />
      <div className="tabs" role="tablist" aria-label="Showcase stars" style={{ marginTop: 12 }}>
        {stars.map((s, i) => (
          <a
            key={s.key}
            href={`/star/${encodeURIComponent(s.key)}`}
            role="tab"
            aria-selected={i === active}
            className={i === active ? "active" : ""}
            onClick={(e) => {
              e.preventDefault();
              setActive(i);
            }}
          >
            <span className="swatch" style={{ color: teffToCss(s.render.teff_k), background: teffToCss(s.render.teff_k) }} /> {s.name}
          </a>
        ))}
      </div>
      <p className="muted small" style={{ marginTop: 10 }}>
        {star.name} · {star.spectral_type ?? "—"} · {Math.round(star.render.teff_k)} K
        {star.distance_ly ? ` · ${star.distance_ly.toFixed(2)} ly` : ""} ·{" "}
        <Link href={`/star/${encodeURIComponent(star.key)}`}>star card →</Link>
      </p>
    </div>
  );
}
