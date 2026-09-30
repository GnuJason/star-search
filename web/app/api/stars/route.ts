import { parseCatalogQuery, queryCatalog } from "@/lib/data";
import { json, notPrepared, paramsOf } from "@/lib/http";

export const dynamic = "force-dynamic";

/** GET /api/stars — paginated, filterable catalog (same filters as /catalog). */
export function GET(request: Request) {
  const result = queryCatalog(parseCatalogQuery(paramsOf(request.url)));
  return result ? json(result) : notPrepared();
}
