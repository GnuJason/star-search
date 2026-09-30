import type { NextConfig } from "next";

// Static security headers. X-Frame-Options is deliberately NOT sent: the site
// must be embeddable in the https://apps.abacus.ai preview iframe, so framing
// is restricted with CSP frame-ancestors instead.
const securityHeaders = [
  { key: "Content-Security-Policy", value: "frame-ancestors 'self' https://*.abacus.ai" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      {
        // Prepared data and portraits change only when prepare_web_data.py re-runs.
        source: "/(data|stars)/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=0, s-maxage=60, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
