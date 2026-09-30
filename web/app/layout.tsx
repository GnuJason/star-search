import type { Metadata, Viewport } from "next";
import "./globals.css";
import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://starsearch.online"),
  title: { default: "star-search — the nearest stars, rendered", template: "%s · star-search" },
  description:
    "Explore the RECONS 100 nearest star systems cross-matched with Gaia DR3: physically parameterised star portraits, a 3D map of the solar neighbourhood and a searchable catalog.",
  applicationName: "star-search",
  openGraph: { title: "star-search", siteName: "star-search", url: "/", type: "website" },
};

export const viewport: Viewport = { themeColor: "#04050b", colorScheme: "dark" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
