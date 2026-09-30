"use client";

import dynamic from "next/dynamic";
import type { StarRendererProps } from "./StarRendererClient";

/** Browser-only wrapper: three.js / WebGPU never run during SSR. */
const StarRenderer = dynamic<StarRendererProps>(() => import("./StarRendererClient"), {
  ssr: false,
  loading: () => (
    <div className="renderer">
      <div className="map-status"><div><div className="spinner" />Loading renderer…</div></div>
    </div>
  ),
});

export default StarRenderer;
