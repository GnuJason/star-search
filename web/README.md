# star-search web (starsearch.online)

Next.js (App Router) + React + TypeScript + Three.js site for star-search: live\
GPU star portraits rendered with the canonical `src/shaders/star.frag`, the\
RECONS 100 nearest systems, a filterable catalog explorer and a 3D map of every\
star within 25 pc.

## Prerequisites

* Node.js ≥ 20.9 (tested with 22.x) and npm

* The repository Python venv (`.venv`, with `pyarrow`) for the data prep step

* The data warehouse built by the pipeline in the root README:\
  `gaia_datasets/merged_catalog.parquet`, `recons_nearest.parquet`,\
  `gaia_dr3_subset.parquet`, plus portraits in `assets/stars/*.png`\
  (`tools/render_all.py`). Portraits are optional: stars without one get a\
  Teff-coloured placeholder.

## Quick start

```bash
# 1. Prepare web data (from the repository root; ~2 s for 5k stars)
.venv/bin/python web/scripts/prepare_web_data.py

# 2. Install and run
cd web
npm install
npm run dev                  # http://localhost:3100 (dev server, hot reload)

# Production
npm run build
npm start                    # next start on $PORT (default 3100)
PORT=8080 npm start          # any other port
```

`predev`/`prebuild` run `scripts/sync_shaders.mjs`, which copies\
`../src/shaders/star.frag` and `star.vert` into `lib/shaders/star.generated.ts`\
(git-ignored, with the SHA-256 of `star.frag`), so the site always ships the\
current canonical shader.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `3100` | Port for `npm run dev` / `npm start` |
| `STAR_SEARCH_WEB_DATA_DIR` | `web/public/data` | Where the server reads the prepared JSON |
| `NEXT_PUBLIC_SITE_URL` | `https://starsearch.online` | Canonical URL used in metadata |

Prep script options: `--warehouse DIR` (default `gaia_datasets/`), `--assets DIR`\
(default `assets/stars/`), `--out DIR`, `--portraits-out DIR`, and\
`--strict-parity` (fail if any parameter differs from the CLI's `index.json`).

## Data flow

```
gaia_datasets/*.parquet ──┐
assets/stars/*.png ───────┼─> web/scripts/prepare_web_data.py
assets/stars/index.json ──┘        │  (star_params.py = Python port of src/star_params.c,
                                   │   parity-checked against index.json)
                                   ├─> public/data/stars.json     full merged rows + aliases + render params
                                   ├─> public/data/points.bin     float32 LE, stride 7: x,y,z pc, Teff, R, L, flags
                                   ├─> public/data/points.json    keys / names / types / distances for points.bin
                                   ├─> public/data/recons.json    100 RECONS systems with linked components
                                   ├─> public/data/manifest.json  row counts, sha256 of inputs, parity, attribution
                                   └─> public/stars/<key>.png     portraits (stale files removed first)
```

* A star's URL key is its Gaia DR3 `source_id` (as a string: it exceeds 2^53)\
  or, for RECONS-only stars, the sanitised stable ID (`recons-gj-244-a`), which\
  is also the portrait file stem.

* The server (`lib/data.ts`) loads the JSON once and reloads it when\
  `manifest.json` changes, so re-running the prep step on a larger merged\
  catalog only needs a page reload. Restart `npm start` if **new** portrait\
  files were added, because Next.js indexes `public/` at startup.

* Everything under `public/data/` and `public/stars/` is generated and\
  git-ignored.

## Routes

| Route | Content |
| --- | --- |
| `/` | Hero, live star renderer showcase (Sirius, α Cen A, Proxima, …), links |
| `/nearest` | RECONS 100 nearest systems: distances, components, portraits, instant filter |
| `/nearest/[cns_name]` | One system (slug of the RECONS system name, e.g. `gj-551`, or its rank) |
| `/star/[source_id]` | Star page: live render, star card, every catalog column with provenance, render parameters |
| `/catalog` | Paginated catalog with All / RECONS explorer / Gaia DR3 explorer tabs, filters for text, source, spectral class, distance and sort |
| `/3d-map` | Three.js point cloud (`?focus=<key>` preselects a star) |
| `/constellations` | "Coming soon" stub |
| `GET /api/stars` | Catalog query: `q, source (all/recons/gaia/recons-gaia/gaia-only/recons-only), spectral, min, max, sort (distance/name/teff/gmag), order, page, pageSize` |
| `GET /api/star/[id]` | Full record by key, source_id, stable ID or exact alias (`?summary=1` for the compact row) |
| `GET /api/nearest` | RECONS systems (`?q=` filter) |
| `GET /api/catalog` | Dataset manifest |
| `GET /api/search?q=&limit=` | Global search (header search bar) |

API routes return `503 {"error":"data_not_prepared"}` before the prep step and\
`404` for unknown ids.

## Star renderer (GLSL reuse)

`components/StarRendererClient.tsx` (loaded with `next/dynamic`, `ssr: false`):

1. **WebGPU** (when `navigator.gpu` returns an adapter): `three/webgpu`\
  `WebGPURenderer` with a node material whose fragment output is\
  `star_pixel()` from `lib/shaders/starShader.ts`, a line-for-line WGSL\
  transliteration of `star.frag` (WebGPU cannot consume GLSL). The 32-bit seed\
  is passed as two exact 16-bit halves.

2. **WebGL 2 fallback**: `star.frag` and `star.vert` run **verbatim** (only the\
  `#version` line is removed because three.js prepends it) in a\
  `THREE.RawShaderMaterial` with `glslVersion: GLSL3`; `star.vert`'s\
  `gl_VertexID` full-screen triangle is drawn from three dummy vertices.

3. If neither works, the offline CPU portrait PNG is shown.

The shader writes sRGB-encoded values itself, so three.js output colour-space\
conversion is disabled (`LinearSRGBColorSpace`). Variable stars animate their\
phase; non-variables render once per resize. The badge on each canvas shows the\
active backend.

## 3D map

`components/StarMap3DClient.tsx`: classic `THREE.WebGLRenderer` + `THREE.Points`\
with a custom point shader for broad compatibility. Positions are heliocentric\
equatorial (ICRS) parsecs mapped to three.js Y-up as `(x, z, −y)`, so the\
celestial equator is the horizontal plane. Colour = Planckian-locus RGB of Teff\
(same Kim et al. 2002 fit as `star.frag`), size = log bolometric luminosity.\
Also: a Sun marker, 5–25 pc rings, OrbitControls, a RECONS-only vs full Gaia toggle\
(one uniform, no buffer rebuild), screen-space picking with a hover tooltip and a\
card panel linking to `/star/<key>`, and on-demand rendering (it draws only\
when the view changes).

## Headers

`next.config.ts` sets `Content-Security-Policy: frame-ancestors 'self' https://*.abacus.ai` (no `X-Frame-Options`), `X-Content-Type-Options: nosniff`,\
`Referrer-Policy`, `Permissions-Policy` and no `X-Powered-By`. `/data/*` and\
`/stars/*` get `Cache-Control: public, max-age=0, s-maxage=60, must-revalidate`.

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm run build
PORT=3100 npm start &
curl -s localhost:3100/api/star/Sirius | head -c 300
curl -s 'localhost:3100/api/search?q=proxima'
```


## Deployment (SuperComputer VM)

Live at https://starsearch.abacusai.cloud. The Next.js production server runs under
systemd on `127.0.0.1:3100`; nginx (port 80) is the only public entry point. Both
configs live in `web/deploy/` and are symlinked into `/etc`:

| File | Symlink |
| --- | --- |
| `deploy/starsearch.service` | `/etc/systemd/system/starsearch.service` |
| `deploy/starsearch.conf` | `/etc/nginx/conf.d/starsearch.conf` (`server_name starsearch.vm.internal`) |

Install / redeploy:

```bash
.venv/bin/python web/scripts/prepare_web_data.py        # from repo root; data hot-reloads
cd web && npm ci && npm run build
sudo ln -sf "$PWD/deploy/starsearch.service" /etc/systemd/system/starsearch.service
sudo ln -sf "$PWD/deploy/starsearch.conf"    /etc/nginx/conf.d/starsearch.conf
sudo systemctl daemon-reload && sudo systemctl enable --now starsearch
sudo systemctl restart starsearch                       # after a rebuild
sudo nginx -t && sudo systemctl reload nginx
journalctl -u starsearch -n 50 --no-pager
```

Tear down:

```bash
sudo systemctl disable --now starsearch
sudo rm /etc/systemd/system/starsearch.service && sudo systemctl daemon-reload
sudo rm /etc/nginx/conf.d/starsearch.conf && sudo nginx -t && sudo systemctl reload nginx
```

To serve `starsearch.online` once it is routed to this VM (Cloud Settings → Custom
Domains → Destination: Your SuperComputer), add it to `server_name` in
`deploy/starsearch.conf` and reload nginx.
