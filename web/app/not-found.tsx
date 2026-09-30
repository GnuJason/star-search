import Link from "next/link";

export default function NotFound() {
  return (
    <main>
      <div className="panel state">
        <h1>Not found</h1>
        <p>No star or system matches that address. Try the search bar, or browse the <Link href="/catalog">catalog</Link>.</p>
      </div>
    </main>
  );
}
