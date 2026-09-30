"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { teffToCss } from "@/lib/color";

interface Hit {
  key: string;
  name: string;
  matched: string;
  spectral_type: string | null;
  distance_pc: number;
  teff_k: number;
}

/** Global search over names, aliases, stable IDs and Gaia source_ids (GET /api/search). */
export default function SearchBar() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits([]);
      setTotal(0);
      setStatus("idle");
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setStatus("loading");
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=8`, { signal: controller.signal });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as { total: number; results: Hit[] };
        setHits(body.results);
        setTotal(body.total);
        setActive(-1);
        setStatus("idle");
      } catch (error) {
        if ((error as Error).name !== "AbortError") setStatus("error");
      }
    }, 160);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const go = (href: string) => {
    setOpen(false);
    setQuery("");
    router.push(href);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0 && hits[active]) go(`/star/${encodeURIComponent(hits[active].key)}`);
      else if (query.trim()) go(`/catalog?q=${encodeURIComponent(query.trim())}`);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  const q = query.trim();
  return (
    <div className="search" ref={boxRef}>
      <input
        type="search"
        placeholder="Search stars: Proxima, Sirius, Gaia source_id…"
        aria-label="Search stars"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-expanded={open && q.length > 0}
        aria-controls="search-results"
      />
      {open && q && (
        <ul className="search-results" id="search-results" role="listbox">
          {status === "error" && <li><span className="empty">Search is unavailable right now.</span></li>}
          {status !== "error" && hits.length === 0 && (
            <li><span className="empty muted">{status === "loading" ? "Searching…" : "No stars match."}</span></li>
          )}
          {hits.map((hit, i) => (
            <li key={hit.key}>
              <Link
                href={`/star/${encodeURIComponent(hit.key)}`}
                aria-selected={i === active}
                onClick={(e) => {
                  e.preventDefault();
                  go(`/star/${encodeURIComponent(hit.key)}`);
                }}
              >
                <span className="swatch" style={{ color: teffToCss(hit.teff_k), background: teffToCss(hit.teff_k) }} />
                <span>
                  {hit.name}
                  <br />
                  <span className="meta">
                    {hit.matched !== hit.name ? `${hit.matched} · ` : ""}
                    {hit.spectral_type ?? "—"} · {hit.distance_pc.toFixed(2)} pc
                  </span>
                </span>
              </Link>
            </li>
          ))}
          {total > hits.length && (
            <li>
              <Link href={`/catalog?q=${encodeURIComponent(q)}`} onClick={(e) => { e.preventDefault(); go(`/catalog?q=${encodeURIComponent(q)}`); }}>
                <span className="meta">All {total} matches in the catalog →</span>
              </Link>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
