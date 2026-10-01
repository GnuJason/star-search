import { getDataset, parseCatalogQuery, queryCatalog } from "@/lib/data";
import { json, notPrepared, paramsOf } from "@/lib/http";

export const dynamic = "force-dynamic";

/**
 * GET /api/stars — paginated, filterable catalog (same filters as /catalog).
 * Optional: ?sort=distance&limit=N returns the N nearest in one page (N ≤ 10000),
 * and ?full=1 returns full star records instead of summaries (used by the CLI).
 */
export function GET(request: Request) {
  const params = paramsOf(request.url);
  const limit = params.limit === undefined || params.limit === "" ? undefined : Number(params.limit);
  const result = queryCatalog({
    ...parseCatalogQuery(params),
    limit: limit !== undefined && Number.isFinite(limit) ? limit : undefined,
  });
  if (!result) return notPrepared();
  if (params.full !== "1") return json(result);
  const byKey = getDataset()?.byKey;
  return json({ ...result, rows: result.rows.map((row) => ({ ...(byKey?.get(row.key) ?? row), spectral_class: row.spectral_class })) });
}
