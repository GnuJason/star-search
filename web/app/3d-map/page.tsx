import type { Metadata } from "next";
import StarMap3D from "@/components/StarMap3D";

export const metadata: Metadata = {
  title: "3D map of the solar neighbourhood",
  description: "Every star within 25 pc placed in parsecs, coloured by effective temperature and sized by luminosity.",
};

export default async function MapPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const focus = (await searchParams).focus;
  return (
    <main className="wide">
      <StarMap3D initialFocus={typeof focus === "string" ? focus : undefined} />
    </main>
  );
}
