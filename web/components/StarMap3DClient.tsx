"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { PointsIndex, StarSummary } from "@/lib/types";
import { planckRgbLinear, teffToCss } from "@/lib/color";
import { fmtDistance } from "@/lib/format";

/** Flag bits written by scripts/prepare_web_data.py (manifest.points.flags). */
const FLAG_RECONS = 1;
const RINGS_PC = [5, 10, 15, 20, 25];

type Mode = "all" | "recons";

interface MapData {
  index: PointsIndex;
  values: Float32Array;
}

/**
 * Catalog XYZ is heliocentric equatorial (ICRS) parsecs. three.js is Y-up, so we map
 * (x, y, z)_eq -> (x, z, -y): the celestial equator becomes the horizontal plane and the
 * north celestial pole points up (a proper rotation, so handedness is preserved).
 */
const toScene = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);

/**
 * Point size in CSS pixels from bolometric luminosity (log scale, clamped); stars without
 * a luminosity estimate fall back to the radius-based scale.
 */
function pointSize(lum: number, radius: number): number {
  const l = Number.isFinite(lum) && lum > 0 ? lum : Math.max(radius, 0.01) ** 2 * 0.3;
  return Math.min(Math.max(5.2 + 1.8 * Math.log10(l), 2.6), 14);
}

const VERTEX = /* glsl */ `
  attribute vec3 color;
  attribute float size;
  attribute float flags;
  uniform float uPixelRatio;
  uniform float uMode;
  varying vec3 vColor;
  varying float vHidden;
  void main() {
    float recons = mod(flags, 2.0);
    vHidden = (uMode > 0.5 && recons < 0.5) ? 1.0 : 0.0;
    vColor = color;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    // Mild perspective attenuation so nearby stars read larger, clamped for legibility.
    float atten = clamp(18.0 / max(-mv.z, 0.1), 0.6, 2.2);
    gl_PointSize = vHidden > 0.5 ? 0.0 : size * atten * uPixelRatio;
    gl_Position = projectionMatrix * mv;
  }
`;

const FRAGMENT = /* glsl */ `
  varying vec3 vColor;
  varying float vHidden;
  void main() {
    if (vHidden > 0.5) discard;
    vec2 d = gl_PointCoord - 0.5;
    float r = length(d) * 2.0;
    if (r > 1.0) discard;
    float core = smoothstep(0.45, 0.0, r);
    float glow = pow(1.0 - r, 2.0) * 0.55;
    gl_FragColor = vec4(vColor * (core + glow) + vec3(core * 0.35), core + glow);
  }
`;

function label(text: string, className = "badge") {
  const el = document.createElement("span");
  el.className = className;
  el.textContent = text;
  el.style.pointerEvents = "none";
  return new CSS2DObject(el);
}

export default function StarMap3DClient({ initialFocus }: { initialFocus?: string }) {
  const shellRef = useRef<HTMLDivElement>(null);
  const modeRef = useRef<Mode>("all");
  const uniformsRef = useRef<{ uMode: { value: number } } | null>(null);
  const requestRenderRef = useRef<() => void>(() => {});
  const [mode, setMode] = useState<Mode>("all");
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "nogl">("loading");
  const [error, setError] = useState<string>("");
  const [counts, setCounts] = useState({ all: 0, recons: 0 });
  const [hover, setHover] = useState<{ x: number; y: number; name: string; dist: number } | null>(null);
  const [selected, setSelected] = useState<{ key: string; summary: StarSummary | null; failed?: boolean } | null>(null);

  // Toggle RECONS-only vs full Gaia without rebuilding buffers: a single uniform.
  useEffect(() => {
    modeRef.current = mode;
    if (uniformsRef.current) uniformsRef.current.uMode.value = mode === "recons" ? 1 : 0;
    requestRenderRef.current();
  }, [mode]);

  // Fetch the summary for the selected star (card panel).
  useEffect(() => {
    if (!selected || selected.summary || selected.failed) return;
    const controller = new AbortController();
    fetch(`/api/star/${encodeURIComponent(selected.key)}?summary=1`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: { summary: StarSummary }) => setSelected((s) => (s && s.key === selected.key ? { ...s, summary: body.summary } : s)))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setSelected((s) => (s && s.key === selected.key ? { ...s, failed: true } : s));
      });
    return () => controller.abort();
  }, [selected]);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    let disposed = false;
    let frame = 0;
    const cleanups: Array<() => void> = [];

    (async () => {
      let data: MapData;
      try {
        const [indexRes, binRes] = await Promise.all([fetch("/data/points.json"), fetch("/data/points.bin")]);
        if (!indexRes.ok || !binRes.ok) throw new Error(`point data unavailable (HTTP ${indexRes.status}/${binRes.status}) — run the prep step`);
        const index = (await indexRes.json()) as PointsIndex;
        const values = new Float32Array(await binRes.arrayBuffer()); // little-endian, as written
        if (values.length !== index.count * index.stride) throw new Error("points.bin does not match points.json");
        data = { index, values };
      } catch (e) {
        if (!disposed) {
          setError((e as Error).message);
          setStatus("error");
        }
        return;
      }
      if (disposed) return;

      let renderer: THREE.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
      } catch {
        setStatus("nogl");
        return;
      }
      const { index, values } = data;
      const stride = index.stride;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setClearColor(0x000000, 1);
      shell.prepend(renderer.domElement);
      const labels = new CSS2DRenderer();
      labels.domElement.style.position = "absolute";
      labels.domElement.style.inset = "0";
      labels.domElement.style.pointerEvents = "none";
      shell.appendChild(labels.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 500);
      camera.position.set(18, 14, 26);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.minDistance = 0.5;
      controls.maxDistance = 120;

      // Stars
      const n = index.count;
      const positions = new Float32Array(n * 3);
      const colors = new Float32Array(n * 3);
      const sizes = new Float32Array(n);
      const flags = new Float32Array(n);
      const scenePos: THREE.Vector3[] = new Array(n);
      let reconsCount = 0;
      for (let i = 0; i < n; i++) {
        const o = i * stride;
        const p = toScene(values[o], values[o + 1], values[o + 2]);
        scenePos[i] = p;
        positions.set([p.x, p.y, p.z], i * 3);
        colors.set(planckRgbLinear(values[o + 3]), i * 3);
        sizes[i] = pointSize(values[o + 5], values[o + 4]);
        flags[i] = values[o + 6];
        if ((values[o + 6] | 0) & FLAG_RECONS) reconsCount++;
      }
      setCounts({ all: n, recons: reconsCount });
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      geometry.setAttribute("size", new THREE.BufferAttribute(sizes, 1));
      geometry.setAttribute("flags", new THREE.BufferAttribute(flags, 1));
      const uniforms = {
        uPixelRatio: { value: renderer.getPixelRatio() },
        uMode: { value: modeRef.current === "recons" ? 1 : 0 },
      };
      uniformsRef.current = uniforms;
      const material = new THREE.ShaderMaterial({
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        uniforms,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const points = new THREE.Points(geometry, material);
      points.frustumCulled = false;
      scene.add(points);

      // Sun at the origin
      const sun = new THREE.Mesh(new THREE.SphereGeometry(0.18, 24, 16), new THREE.MeshBasicMaterial({ color: 0xffd27a }));
      scene.add(sun);
      const sunLabel = label("Sun", "badge warm");
      sunLabel.position.set(0, 0.5, 0);
      scene.add(sunLabel);

      // Distance rings in the celestial-equator plane + polar axis
      const ringMaterial = new THREE.LineBasicMaterial({ color: 0x5b6aa8, transparent: true, opacity: 0.35 });
      for (const radius of RINGS_PC) {
        const pts: THREE.Vector3[] = [];
        for (let k = 0; k <= 128; k++) {
          const a = (k / 128) * Math.PI * 2;
          pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
        }
        scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), ringMaterial));
        const ringLabel = label(`${radius} pc · ${(radius * 3.26156).toFixed(0)} ly`, "badge");
        ringLabel.position.set(radius, 0, 0);
        scene.add(ringLabel);
      }
      const axisMaterial = new THREE.LineBasicMaterial({ color: 0x3b4575, transparent: true, opacity: 0.5 });
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, -25, 0), new THREE.Vector3(0, 25, 0)]), axisMaterial));
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-25, 0, 0), new THREE.Vector3(25, 0, 0)]), axisMaterial));
      const ncp = label("NCP (+δ)", "badge");
      ncp.position.set(0, 25.8, 0);
      scene.add(ncp);
      const vernal = label("α = 0h", "badge");
      vernal.position.set(26.5, 0, 0);
      scene.add(vernal);

      // Selection marker
      const marker = new THREE.Mesh(
        new THREE.RingGeometry(0.28, 0.36, 32),
        new THREE.MeshBasicMaterial({ color: 0x8fb4ff, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }),
      );
      marker.visible = false;
      scene.add(marker);

      // On-demand rendering: only draw when something changed (or damping is settling).
      let needsRender = true;
      const requestRender = () => {
        needsRender = true;
      };
      requestRenderRef.current = requestRender;
      controls.addEventListener("change", requestRender);

      const resize = () => {
        const rect = shell.getBoundingClientRect();
        renderer.setSize(rect.width, rect.height, false);
        renderer.domElement.style.width = `${rect.width}px`;
        renderer.domElement.style.height = `${rect.height}px`;
        labels.setSize(rect.width, rect.height);
        camera.aspect = rect.width / Math.max(rect.height, 1);
        camera.updateProjectionMatrix();
        requestRender();
      };
      resize();
      const observer = new ResizeObserver(resize);
      observer.observe(shell);

      // Screen-space picking: project visible stars, take the nearest within a radius.
      // 5k points is well under a millisecond; scales linearly for larger catalogs.
      const projected = new THREE.Vector3();
      const pick = (clientX: number, clientY: number, radiusPx = 12): number => {
        const rect = renderer.domElement.getBoundingClientRect();
        const mx = clientX - rect.left;
        const my = clientY - rect.top;
        let best = -1;
        let bestD = radiusPx * radiusPx;
        const reconsOnly = modeRef.current === "recons";
        for (let i = 0; i < n; i++) {
          if (reconsOnly && !((flags[i] | 0) & FLAG_RECONS)) continue;
          projected.copy(scenePos[i]).project(camera);
          if (projected.z < -1 || projected.z > 1) continue;
          const sx = (projected.x * 0.5 + 0.5) * rect.width;
          const sy = (-projected.y * 0.5 + 0.5) * rect.height;
          const d = (sx - mx) ** 2 + (sy - my) ** 2;
          if (d < bestD) {
            bestD = d;
            best = i;
          }
        }
        return best;
      };

      const select = (i: number) => {
        marker.position.copy(scenePos[i]);
        marker.visible = true;
        setSelected({ key: index.keys[i], summary: null });
        requestRender();
      };

      let pending: PointerEvent | null = null;
      const onMove = (event: PointerEvent) => {
        pending = event;
      };
      let downAt: { x: number; y: number } | null = null;
      const onDown = (event: PointerEvent) => {
        downAt = { x: event.clientX, y: event.clientY };
      };
      const onUp = (event: PointerEvent) => {
        if (!downAt || Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 5) return; // drag, not click
        const i = pick(event.clientX, event.clientY);
        if (i >= 0) select(i);
      };
      const onLeave = () => setHover(null);
      renderer.domElement.addEventListener("pointermove", onMove);
      renderer.domElement.addEventListener("pointerdown", onDown);
      renderer.domElement.addEventListener("pointerup", onUp);
      renderer.domElement.addEventListener("pointerleave", onLeave);

      if (initialFocus) {
        const i = index.keys.indexOf(initialFocus);
        if (i >= 0) {
          select(i);
          controls.target.copy(scenePos[i]);
          camera.position.copy(scenePos[i]).add(new THREE.Vector3(4, 3, 6));
        }
      }

      const loop = () => {
        frame = requestAnimationFrame(loop);
        if (controls.update()) needsRender = true;
        if (pending) {
          const event = pending;
          pending = null;
          const i = pick(event.clientX, event.clientY);
          if (i >= 0) {
            const rect = shell.getBoundingClientRect();
            setHover({
              x: event.clientX - rect.left,
              y: event.clientY - rect.top,
              name: index.names[i] ?? index.keys[i],
              dist: index.distances_pc[i],
            });
            renderer.domElement.style.cursor = "pointer";
          } else {
            setHover(null);
            renderer.domElement.style.cursor = "grab";
          }
        }
        if (needsRender) {
          needsRender = false;
          marker.quaternion.copy(camera.quaternion);
          renderer.render(scene, camera);
          labels.render(scene, camera);
        }
      };
      loop();
      setStatus("ready");

      cleanups.push(() => {
        observer.disconnect();
        controls.dispose();
        renderer.domElement.removeEventListener("pointermove", onMove);
        renderer.domElement.removeEventListener("pointerdown", onDown);
        renderer.domElement.removeEventListener("pointerup", onUp);
        renderer.domElement.removeEventListener("pointerleave", onLeave);
        scene.traverse((obj) => {
          const mesh = obj as THREE.Mesh;
          mesh.geometry?.dispose();
          const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
          if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
          else mat?.dispose();
        });
        renderer.dispose();
        renderer.domElement.remove();
        labels.domElement.remove();
      });
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      cleanups.forEach((fn) => fn());
      uniformsRef.current = null;
      requestRenderRef.current = () => {};
    };
  }, [initialFocus]);

  const s = selected?.summary;
  return (
    <div className="map-shell" ref={shellRef}>
      {status === "loading" && (
        <div className="map-status"><div><div className="spinner" />Loading the solar neighbourhood…</div></div>
      )}
      {status === "error" && <div className="map-status state error">Could not load the 3D map: {error}</div>}
      {status === "nogl" && <div className="map-status state error">WebGL is not available in this browser.</div>}
      {status === "ready" && (
        <div className="map-ui">
          <div className="panel">
            <strong>Solar neighbourhood · 25 pc</strong>
            <div className="muted small" style={{ margin: "4px 0 10px" }}>
              {mode === "recons" ? `${counts.recons} RECONS stars` : `${counts.all.toLocaleString()} stars (Gaia DR3 + RECONS)`} ·
              equatorial frame, rings every 5 pc. Drag to orbit, scroll to zoom, click a star.
            </div>
            <div style={{ display: "flex", gap: 8 }} role="group" aria-label="Catalog">
              <button className="btn" aria-pressed={mode === "all"} onClick={() => setMode("all")}>Full Gaia</button>
              <button className="btn" aria-pressed={mode === "recons"} onClick={() => setMode("recons")}>RECONS only</button>
            </div>
            <div className="legend" style={{ marginTop: 10 }}>
              {[2800, 3800, 5200, 5800, 7000, 10000].map((t) => (
                <span key={t}><span className="swatch" style={{ color: teffToCss(t), background: teffToCss(t) }} /> {t} K</span>
              ))}
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>Colour: T<sub>eff</sub> (Planckian locus) · size: log luminosity</div>
          </div>
        </div>
      )}
      {hover && (
        <div className="map-tooltip" style={{ left: hover.x, top: hover.y }}>
          {hover.name} <span className="muted">· {hover.dist.toFixed(2)} pc</span>
        </div>
      )}
      {selected && (
        <div className="map-card panel">
          <button className="btn" style={{ float: "right", padding: "2px 10px" }} onClick={() => setSelected(null)} aria-label="Close">×</button>
          {!s && !selected.failed && <div className="muted"><div className="spinner" />Loading star…</div>}
          {selected.failed && <div className="state error">Could not load this star.</div>}
          {s && (
            <div className="star-card compact">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {s.portrait ? <img className="portrait" src={s.portrait} alt={`${s.name} portrait`} /> : <div className="portrait placeholder"><span style={{ background: `radial-gradient(circle, #fff 0%, ${teffToCss(s.teff_k)} 55%, transparent 72%)` }} /></div>}
              <div>
                <h3>{s.name}</h3>
                <div className="small">{fmtDistance(s.distance_pc, s.distance_ly)}</div>
                <div className="small muted">
                  {s.spectral_type ?? "—"} · {Math.round(s.teff_k)} K · {s.source_catalogs}
                </div>
                <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Link className="btn primary" href={`/star/${encodeURIComponent(s.key)}`}>Open star card →</Link>
                  {s.recons_slug && <Link className="btn" href={`/nearest/${s.recons_slug}`}>System</Link>}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      <noscript>The 3D map needs JavaScript and WebGL.</noscript>
    </div>
  );
}
