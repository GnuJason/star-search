"use client";

import { useState } from "react";
import { teffToCss } from "@/lib/color";

/**
 * Offline CPU-rendered portrait (star-search CLI output copied to /stars/<key>.png).
 * A missing or failing image degrades to a Teff-coloured placeholder disk.
 */
export default function Portrait({
  src,
  alt,
  teff,
  className = "portrait",
}: {
  src: string | null;
  alt: string;
  teff: number | null;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    const color = teffToCss(teff);
    return (
      <div className={`${className} placeholder`} role="img" aria-label={`${alt} (no portrait rendered yet)`} title="No portrait rendered yet">
        <span style={{ background: `radial-gradient(circle, #fff 0%, ${color} 55%, transparent 72%)` }} />
      </div>
    );
  }
  return (
    <div className={className}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />
    </div>
  );
}
