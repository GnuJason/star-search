import Link from "next/link";
import SearchBar from "./SearchBar";

const NAV = [
  { href: "/nearest", label: "Nearest" },
  { href: "/catalog", label: "Catalog" },
  { href: "/3d-map", label: "3D map" },
  { href: "/constellations", label: "Constellations" },
];

export default function SiteHeader() {
  return (
    <header className="site-header">
      <div className="inner">
        <Link href="/" className="brand" aria-label="star-search home">
          <span className="dot" aria-hidden />
          star-search
        </Link>
        <nav className="nav" aria-label="Primary">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <SearchBar />
      </div>
    </header>
  );
}
