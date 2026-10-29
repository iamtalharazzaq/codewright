import type { NextConfig } from "next";

// The browser talks to this app only; /api/* is forwarded to the backend (set BACKEND_URL when building).
const backend = process.env.BACKEND_URL ?? "http://localhost:{{port}}";

const config: NextConfig = {
  poweredByHeader: false,
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default config;
