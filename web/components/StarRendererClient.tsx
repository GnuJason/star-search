"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { RenderParams } from "@/lib/types";
import {
  STAR_FRAG_GLSL3,
  STAR_VERT_GLSL3,
  STAR_WGSL_HELPERS,
  STAR_WGSL_MAIN,
  uniformsFromParams,
} from "@/lib/shaders/starShader";

type Backend = "webgpu" | "webgl2" | "unavailable";

export interface StarRendererProps {
  params: RenderParams;
  /** Animate variability (only visible for variables) and slowly evolve nothing else. */
  animate?: boolean;
  /** Variability period on screen, seconds (purely presentational). */
  periodSeconds?: number;
  /** Static fallback image (the offline CPU portrait) if no GPU backend works. */
  fallbackSrc?: string | null;
  label?: string;
  /** Force a backend (debugging): "webgl2" skips WebGPU. */
  prefer?: "auto" | "webgl2";
}

interface Driver {
  backend: Backend;
  setSize(width: number, height: number): void;
  render(phase: number): void;
  dispose(): void;
}

/**
 * WebGL 2 driver: the canonical src/shaders/star.frag + star.vert run verbatim in a
 * THREE.RawShaderMaterial (GLSL ES 3.00). star.vert emits a full-screen triangle from
 * gl_VertexID, so we draw three dummy vertices.
 */
function createWebGLDriver(canvas: HTMLCanvasElement, params: RenderParams): Driver {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
  if (!renderer.capabilities.isWebGL2) {
    renderer.dispose();
    throw new Error("WebGL 2 is not available");
  }
  // star.frag writes sRGB-encoded values itself; a RawShaderMaterial gets no colour-space
  // or tone-mapping conversion from three.js, so the pixels match the CLI renderer.
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const u = uniformsFromParams(params);
  const uniforms = {
    u_resolution: { value: new THREE.Vector2(1, 1) },
    u_teff: { value: u.teff },
    u_disk_radius: { value: u.diskRadius },
    u_limb_darkening: { value: new THREE.Vector2(u.u1, u.u2) },
    u_gran_amplitude: { value: u.granAmplitude },
    u_gran_frequency: { value: u.granFrequency },
    u_var_amplitude: { value: u.varAmplitude },
    u_phase: { value: u.phase },
    u_seed: { value: u.seed },
  };
  const material = new THREE.RawShaderMaterial({
    glslVersion: THREE.GLSL3,
    vertexShader: STAR_VERT_GLSL3,
    fragmentShader: STAR_FRAG_GLSL3,
    uniforms,
    depthTest: false,
    depthWrite: false,
  });
  // three.js infers uniform types from GLSL; u_seed is declared `uint`, so it is uploaded
  // with uniform1ui. Seeds are < 2^32 and exactly representable as JS numbers.
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(9), 3));
  geometry.setDrawRange(0, 3);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false;
  const scene = new THREE.Scene();
  scene.add(mesh);
  const camera = new THREE.Camera();
  return {
    backend: "webgl2",
    setSize(width, height) {
      renderer.setSize(width, height, false);
      const buffer = renderer.getDrawingBufferSize(new THREE.Vector2());
      uniforms.u_resolution.value.copy(buffer);
    },
    render(phase) {
      uniforms.u_phase.value = phase;
      renderer.render(scene, camera);
    },
    dispose() {
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    },
  };
}

/**
 * WebGPU driver: three/webgpu WebGPURenderer with a node material whose fragment output
 * is STAR_WGSL_MAIN (a line-for-line WGSL transliteration of star.frag) evaluated at the
 * framebuffer coordinate. WebGPU cannot consume GLSL, hence the transliteration.
 */
async function createWebGPUDriver(canvas: HTMLCanvasElement, params: RenderParams): Promise<Driver> {
  const gpu = (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  if (!gpu) throw new Error("navigator.gpu missing");
  const adapter = await gpu.requestAdapter();
  if (!adapter) throw new Error("no WebGPU adapter");
  const WEBGPU = await import("three/webgpu");
  const TSL = await import("three/tsl");
  const renderer = new WEBGPU.WebGPURenderer({ canvas, antialias: false });
  await renderer.init();
  const backendName = (renderer.backend as { isWebGPUBackend?: boolean }).isWebGPUBackend;
  if (!backendName) {
    renderer.dispose();
    throw new Error("WebGPURenderer fell back to WebGL; using the verbatim GLSL path instead");
  }
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // shader already sRGB-encodes
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const u = uniformsFromParams(params);
  const uResolution = TSL.uniform(new THREE.Vector2(1, 1));
  const uPhase = TSL.uniform(u.phase);
  const helpers = TSL.wgsl(STAR_WGSL_HELPERS);
  const starPixel = TSL.wgslFn(STAR_WGSL_MAIN, [helpers]);
  const color = starPixel({
    coord: TSL.screenCoordinate,
    resolution: uResolution,
    teff: TSL.float(u.teff),
    disk_radius: TSL.float(u.diskRadius),
    ld_coeffs: TSL.vec2(u.u1, u.u2),
    gran: TSL.vec2(u.granAmplitude, u.granFrequency),
    variability: TSL.vec2(u.varAmplitude, uPhase),
    seed_parts: TSL.vec2(Math.floor(u.seed / 65536), u.seed % 65536),
  });
  const material = new WEBGPU.MeshBasicNodeMaterial();
  // wgslFn call nodes are untyped in @types/three; star_pixel returns vec3<f32>.
  material.fragmentNode = TSL.vec4(color as unknown as ReturnType<typeof TSL.vec3>, 1.0);
  material.depthTest = false;
  material.depthWrite = false;
  const geometry = new THREE.PlaneGeometry(2, 2);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false;
  const scene = new THREE.Scene();
  scene.add(mesh);
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 2);
  camera.position.z = 1;

  // Compile eagerly so WGSL errors surface here (and trigger the WebGL fallback).
  await renderer.compileAsync(scene, camera);
  return {
    backend: "webgpu",
    setSize(width, height) {
      renderer.setSize(width, height, false);
      const buffer = renderer.getDrawingBufferSize(new THREE.Vector2());
      uResolution.value.copy(buffer);
    },
    render(phase) {
      uPhase.value = phase;
      renderer.render(scene, camera);
    },
    dispose() {
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    },
  };
}

export default function StarRendererClient({
  params,
  animate = true,
  periodSeconds = 6,
  fallbackSrc,
  label,
  prefer = "auto",
}: StarRendererProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [backend, setBackend] = useState<Backend | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let driver: Driver | null = null;
    let frame = 0;
    let observer: ResizeObserver | null = null;
    let canvas = null as HTMLCanvasElement | null;

    const makeCanvas = () => {
      canvas?.remove();
      canvas = document.createElement("canvas");
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", label ?? "Rendered star portrait");
      host.prepend(canvas);
      return canvas;
    };

    (async () => {
      const attempts: Array<() => Promise<Driver> | Driver> = [];
      if (prefer === "auto" && "gpu" in navigator) attempts.push(() => createWebGPUDriver(makeCanvas(), params));
      attempts.push(() => createWebGLDriver(makeCanvas(), params));
      for (const attempt of attempts) {
        try {
          driver = await attempt();
          break;
        } catch (error) {
          console.info("star-search renderer: backend unavailable, trying next:", (error as Error).message);
        }
      }
      if (disposed) {
        driver?.dispose();
        return;
      }
      if (!driver) {
        canvas?.remove();
        setBackend("unavailable");
        return;
      }
      setBackend(driver.backend);
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const animated = animate && params.variable && params.variability_amplitude > 0 && !reduceMotion;
      const start = performance.now();
      const tick = () => {
        const phase = animated ? (params.phase + (performance.now() - start) / 1000 / periodSeconds) % 1 : params.phase;
        driver!.render(phase);
        if (animated) frame = requestAnimationFrame(tick);
      };
      const resize = () => {
        const rect = host.getBoundingClientRect();
        const side = Math.max(1, Math.round(Math.min(rect.width, rect.height || rect.width)));
        driver!.setSize(side, side);
        if (!animated) driver!.render(params.phase); // static stars only redraw on resize
      };
      resize();
      observer = new ResizeObserver(resize);
      observer.observe(host);
      tick();
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      driver?.dispose();
      canvas?.remove();
    };
  }, [params, animate, periodSeconds, label, prefer]);

  return (
    <div className="renderer" ref={hostRef}>
      {backend === "unavailable" &&
        (fallbackSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="fallback-img" src={fallbackSrc} alt={label ?? "Star portrait"} />
        ) : (
          <div className="state">No WebGPU or WebGL 2 support in this browser.</div>
        ))}
      {backend === null && <div className="map-status"><div><div className="spinner" />Initialising renderer…</div></div>}
      {backend && backend !== "unavailable" && (
        <span className="badge backend" title="Active GPU backend">
          {backend === "webgpu" ? "WebGPU · WGSL port of star.frag" : "WebGL 2 · star.frag (verbatim GLSL)"}
        </span>
      )}
    </div>
  );
}
