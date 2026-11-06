import type { NextConfig } from "next";

/** The search server (`uv run curated serve`). The site and the API share one origin, so the page needs no CORS. */
const API = process.env.CURATED_API ?? "http://127.0.0.1:8790";

/** `scripts/build_site.py` builds static files for Vercel, where the search app answers `/api/*` itself. */
const nextConfig: NextConfig =
  process.env.CURATED_EXPORT === "1"
    ? { output: "export" }
    : {
        // Compression would hold back the search's event stream until a buffer fills.
        compress: false,
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
        },
      };

export default nextConfig;
