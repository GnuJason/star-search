/** Shared empty / not-prepared states for server pages. */
export function DataMissing() {
  return (
    <div className="panel state error">
      <h2 style={{ marginTop: 0 }}>Catalog data not prepared</h2>
      <p>
        Run <code>.venv/bin/python web/scripts/prepare_web_data.py</code> from the repository root to generate{" "}
        <code>web/public/data/</code>, then reload.
      </p>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="panel state">{children}</div>;
}
