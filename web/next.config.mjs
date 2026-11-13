// The interface talks to the Python API (sysrev serve) through this proxy: no CORS, one origin.
const api = process.env.SYSREV_API || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const config = {
  devIndicators: false,
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default config;
