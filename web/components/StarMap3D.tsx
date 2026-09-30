"use client";

import dynamic from "next/dynamic";

/** Browser-only wrapper around the three.js map (no WebGL during SSR). */
const StarMap3D = dynamic<{ initialFocus?: string }>(() => import("./StarMap3DClient"), {
  ssr: false,
  loading: () => (
    <div className="map-shell">
      <div className="map-status"><div><div className="spinner" />Loading 3D map…</div></div>
    </div>
  ),
});

export default StarMap3D;
