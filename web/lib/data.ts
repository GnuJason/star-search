import "server-only";
import { readFileSync, statSync } from "node:fs";
import path from "node:path";
import type { Manifest, ReconsSystem, Star, StarSummary } from "./types";

/**
 * Server-side access to the data prepared by scripts/prepare_web_data.py.
 * Files are read once and re-read automatically when manifest.json changes,
 * so re-running the prep step on a larger merged_catalog.parquet only needs
 * a page reload, not a rebuild or restart.
 */
export const DATA_DIR = process.env.STAR_SEARCH_WEB_DATA_DIR ?? path.join(/*turbopackIgnore: true*/ process.cwd(), "public", "data");

interface Dataset {
  manifest: Manifest;
  stars: Star[];
  recons: ReconsSystem[];
  byKey: Map<string, Star>;
  byLookup: Map<string, Star[]>;
  loadedFrom: number;
}

let cache: Dataset | null = null;

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(path.join(/*turbopackIgnore: true*/ DATA_DIR, file), "utf8")) as T;
}

const norm = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");

function load(): Dataset | null {
  let mtime: number;
  try {
    mtime = statSync(path.join(/*turbopackIgnore: true*/ DATA_DIR, "manifest.json")).mtimeMs;
  } catch {
    return null;
  }
  if (cache && cache.loadedFrom === mtime) return cache;
  const manifest = readJson<Manifest>("manifest.json");
  const stars = readJson<Star[]>("stars.json");
  const recons = readJson<ReconsSystem[]>("recons.json");
  const byKey = new Map<string, Star>();
  const byLookup = new Map<string, Star[]>();
  const add = (term: string | null | undefined, star: Star) => {
    if (!term) return;
    const k = norm(term);
    const list = byLookup.get(k);
    if (!list) byLookup.set(k, [star]);
    else if (!list.includes(star)) list.push(star);
  };
  for (const star of stars) {
    byKey.set(star.key, star);
    [star.key, star.id, star.primary_name, star.gaia_designation, ...star.aliases].forEach((t) => add(t, star));
  }
  cache = { manifest, stars, recons, byKey, byLookup, loadedFrom: mtime };
  return cache;
}

export function getDataset(): Dataset | null {
  try {
    return load();
  } catch (error) {
    console.error("star-search: failed to load prepared data from", DATA_DIR, error);
    return null;
  }
}

export function summarize(star: Star): StarSummary {
  return {
    key: star.key,
    id: star.id,
    name: star.primary_name ?? star.gaia_designation ?? star.id,
    spectral_type: star.spectral_type,
    distance_pc: star.distance_pc,
    distance_ly: star.distance_ly,
    teff_k: star.render.teff_k,
    teff_source: star.render.teff_source,
    phot_g_mean_mag: star.phot_g_mean_mag,
    v_mag: star.v_mag,
    source_catalogs: star.source_catalogs,
    recons_slug: star.recons_slug,
    portrait: star.portrait,
  };
}

/** Resolve a URL key, stable ID, Gaia designation/source_id or exact alias. */
export function findStar(term: string): Star | null {
  const data = getDataset();
  if (!data) return null;
  const decoded = decodeURIComponent(term);
  return data.byKey.get(decoded) ?? data.byLookup.get(norm(decoded))?.[0] ?? null;
}

export function findSystem(term: string): ReconsSystem | null {
  const data = getDataset();
  if (!data) return null;
  const decoded = decodeURIComponent(term);
  const slug = decoded.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const rank = /^\d+$/.test(decoded) ? Number(decoded) : NaN;
  return data.recons.find((s) => s.slug === slug || s.rank === rank) ?? null;
}

export interface SearchHit extends StarSummary {
  matched: string;
  score: number;
}

/** Global search over names, aliases, stable IDs and Gaia source_ids. */
export function searchStars(query: string, limit = 12): { total: number; results: SearchHit[] } {
  const data = getDataset();
  const q = norm(query);
  if (!data || q.length === 0) return { total: 0, results: [] };
  const hits: SearchHit[] = [];
  for (const star of data.stars) {
    const terms = [star.primary_name, star.key, star.id, star.gaia_designation, ...star.aliases].filter(Boolean) as string[];
    let best = 0;
    let matched = "";
    for (const term of terms) {
      const t = norm(term);
      const score = t === q ? 3 : t.startsWith(q) ? 2 : t.includes(q) ? 1 : 0;
      if (score > best) {
        best = score;
        matched = term;
      }
    }
    if (best > 0) hits.push({ ...summarize(star), matched, score: best });
  }
  hits.sort((a, b) => b.score - a.score || a.distance_pc - b.distance_pc || a.id.localeCompare(b.id));
  return { total: hits.length, results: hits.slice(0, limit) };
}

export type SourceFilter = "all" | "recons" | "gaia" | "recons-gaia" | "gaia-only" | "recons-only";
export type SortKey = "distance" | "name" | "teff" | "gmag";

export interface CatalogQuery {
  q?: string;
  source?: SourceFilter;
  spectral?: string;   // spectral class letter(s) (Teff-derived for stars without a type)
  minDist?: number;
  maxDist?: number;
  sort?: SortKey;
  order?: "asc" | "desc";
  page?: number;
  pageSize?: number;
}

/** Spectral class from the catalog type, else from Teff (Pecaut & Mamajek 2013 boundaries). */
export function spectralClass(star: Star): string {
  const t = star.spectral_type?.replace(/^(usd|esd|sd|d)/, "").trim();
  if (t) {
    if (/^D[ABOQZCXP]/.test(t)) return "D";
    const letter = t[0];
    if ("OBAFGKMLTY".includes(letter)) return letter;
  }
  const teff = star.render.teff_k;
  if (teff >= 31400) return "O";
  if (teff >= 9700) return "B";
  if (teff >= 7220) return "A";
  if (teff >= 5920) return "F";
  if (teff >= 5280) return "G";
  if (teff >= 3850) return "K";
  if (teff >= 2250) return "M";
  return "L";
}

export function queryCatalog(query: CatalogQuery) {
  const data = getDataset();
  if (!data) return null;
  const pageSize = Math.min(Math.max(query.pageSize ?? 50, 1), 500);
  const q = query.q ? norm(query.q) : "";
  const classes = (query.spectral ?? "").toUpperCase().replace(/[^OBAFGKMLTYD]/g, "");
  let rows = data.stars.filter((star) => {
    const recons = Boolean(star.recons_id);
    const gaia = Boolean(star.gaia_source_id);
    switch (query.source ?? "all") {
      case "recons": if (!recons) return false; break;
      case "gaia": if (!gaia) return false; break;
      case "recons-gaia": if (!(recons && gaia)) return false; break;
      case "gaia-only": if (recons || !gaia) return false; break;
      case "recons-only": if (!recons || gaia) return false; break;
    }
    if (query.minDist !== undefined && star.distance_pc < query.minDist) return false;
    if (query.maxDist !== undefined && star.distance_pc > query.maxDist) return false;
    if (classes && !classes.includes(spectralClass(star))) return false;
    if (q) {
      const terms = [star.primary_name, star.key, star.id, star.gaia_designation, star.spectral_type, ...star.aliases];
      if (!terms.some((t) => t && norm(t).includes(q))) return false;
    }
    return true;
  });
  const dir = query.order === "desc" ? -1 : 1;
  const nullLast = (a: number | null, b: number | null) =>
    a === null ? (b === null ? 0 : 1) : b === null ? -1 : dir * (a - b);
  const sort = query.sort ?? "distance";
  rows = [...rows].sort((a, b) => {
    const primary =
      sort === "name" ? dir * (a.primary_name ?? a.gaia_designation ?? a.id).localeCompare(b.primary_name ?? b.gaia_designation ?? b.id)
      : sort === "teff" ? dir * (a.render.teff_k - b.render.teff_k)
      : sort === "gmag" ? nullLast(a.phot_g_mean_mag, b.phot_g_mean_mag)
      : dir * (a.distance_pc - b.distance_pc);
    return primary || a.id.localeCompare(b.id);
  });
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(query.page ?? 1, 1), pages);
  return {
    total,
    page,
    pages,
    pageSize,
    rows: rows.slice((page - 1) * pageSize, page * pageSize).map((s) => ({ ...summarize(s), spectral_class: spectralClass(s) })),
  };
}

/** Parse catalog filters from URL search params (shared by /catalog and /api/stars). */
export function parseCatalogQuery(params: Record<string, string | string[] | undefined>): CatalogQuery {
  const one = (k: string) => {
    const v = params[k];
    return Array.isArray(v) ? v[0] : v;
  };
  const num = (k: string) => {
    const v = one(k);
    if (v === undefined || v === "") return undefined;
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  };
  const sources: SourceFilter[] = ["all", "recons", "gaia", "recons-gaia", "gaia-only", "recons-only"];
  const sorts: SortKey[] = ["distance", "name", "teff", "gmag"];
  const source = one("source") as SourceFilter | undefined;
  const sort = one("sort") as SortKey | undefined;
  return {
    q: one("q")?.slice(0, 100),
    source: source && sources.includes(source) ? source : "all",
    spectral: one("spectral")?.slice(0, 12),
    minDist: num("min"),
    maxDist: num("max"),
    sort: sort && sorts.includes(sort) ? sort : "distance",
    order: one("order") === "desc" ? "desc" : "asc",
    page: num("page"),
    pageSize: num("pageSize"),
  };
}
