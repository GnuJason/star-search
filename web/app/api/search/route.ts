import { getDataset, searchStars } from "@/lib/data";
import { json, notPrepared } from "@/lib/http";

export const dynamic = "force-dynamic";

/** GET /api/search?q=&limit= — global search over names, aliases and Gaia source_ids. */
export function GET(request: Request) {
  if (!getDataset()) return notPrepared();
  const params = new URL(request.url).searchParams;
  const q = (params.get("q") ?? "").slice(0, 100);
  const limit = Math.min(Math.max(Number(params.get("limit")) || 12, 1), 50);
  return json({ query: q, ...searchStars(q, limit) });
}
