import { findStar, getDataset, summarize } from "@/lib/data";
import { json, notFound, notPrepared } from "@/lib/http";

export const dynamic = "force-dynamic";

/** GET /api/star/:id — full record by key, Gaia source_id, stable ID or exact alias (?summary=1 for the compact row). */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!getDataset()) return notPrepared();
  const { id } = await ctx.params;
  const star = findStar(id);
  if (!star) return notFound(`no star matches "${decodeURIComponent(id)}"`);
  const summaryOnly = new URL(request.url).searchParams.get("summary") === "1";
  return json(summaryOnly ? { summary: summarize(star) } : { star, summary: summarize(star) });
}
