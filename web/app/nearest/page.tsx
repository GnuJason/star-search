import type { Metadata } from "next";
import { getDataset } from "@/lib/data";
import NearestList from "@/components/NearestList";
import { DataMissing } from "@/components/States";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "The 100 nearest star systems",
  description: "RECONS 100 nearest star systems with distances, components and rendered portraits.",
};

export default function NearestPage() {
  const data = getDataset();
  return (
    <main>
      <h1>The 100 nearest star systems</h1>
      <p className="muted">
        RECONS ranking by trigonometric parallax. Components link to their star cards; thumbnails are portraits
        rendered from catalog physics. Source: {data?.manifest.attribution ?? "RECONS"}
      </p>
      {data ? <NearestList systems={data.recons} /> : <DataMissing />}
    </main>
  );
}
