/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    CESIUM_BASE_URL: '/cesium',
  },
  webpack: (config, { isServer }) => {
    // Cesium references `require` at runtime for AMD-style loaders; disable that path.
    config.resolve = config.resolve || {};
    config.resolve.fallback = {
      ...(config.resolve.fallback || {}),
      fs: false,
      http: false,
      https: false,
      zlib: false,
    };
    return config;
  },
};

module.exports = nextConfig;
