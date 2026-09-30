import { getDataset } from "@/lib/data";
import { json, notPrepared } from "@/lib/http";

export const dynamic = "force-dynamic";

/** GET /api/nearest — the RECONS 100 nearest systems with linked components (?q= filters by name). */
export function GET(request: Request) {
  const data = getDataset();
  if (!data) return notPrepared();
  const q = new URL(request.url).searchParams.get("q")?.trim().toLowerCase();
  const systems = q
    ? data.recons.filter((s) =>
        [s.cns_name, s.system_name, s.common_name, ...s.components.flatMap((c) => [c.cns_name, c.common_name, c.lhs_id])]
          .some((t) => t?.toLowerCase().includes(q)),
      )
    : data.recons;
  return json({ total: systems.length, systems, attribution: data.manifest.attribution });
}
