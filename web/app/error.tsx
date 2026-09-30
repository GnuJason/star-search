"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main>
      <div className="panel state error">
        <h1>Something went wrong</h1>
        <p>{error.digest ? `Reference: ${error.digest}` : "An unexpected error occurred while loading this page."}</p>
        <button className="btn" onClick={reset}>Try again</button>
      </div>
    </main>
  );
}
