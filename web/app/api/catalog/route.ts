import { getDataset } from "@/lib/data";
import { json, notPrepared } from "@/lib/http";

export const dynamic = "force-dynamic";

/** GET /api/catalog — dataset manifest: sources, row counts, checksums, provenance. */
export function GET() {
  const data = getDataset();
  return data ? json(data.manifest) : notPrepared();
}
