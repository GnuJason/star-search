import { NextResponse } from "next/server";

/** JSON response helpers shared by the route handlers. */
export const json = (body: unknown, status = 200, cache = "public, max-age=0, s-maxage=60") =>
  NextResponse.json(body, { status, headers: { "Cache-Control": cache } });

export const notPrepared = () =>
  json(
    { error: "data_not_prepared", detail: "Run `.venv/bin/python web/scripts/prepare_web_data.py` to generate web/public/data/." },
    503,
    "no-store",
  );

export const notFound = (what: string) => json({ error: "not_found", detail: what }, 404, "no-store");

export const paramsOf = (url: string) => Object.fromEntries(new URL(url).searchParams.entries());
