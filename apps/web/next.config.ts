import type { NextConfig } from "next";

// The browser only ever talks to the web app; `/api/*` is proxied to the FastAPI backend.
// next.config is read at build time, so MONOSHIFT_API_URL must be set when running `next build`
// (the Docker image sets it to the compose service name).
const apiUrl = process.env.MONOSHIFT_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
