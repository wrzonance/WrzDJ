/** @type {import('next').NextConfig} */

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  `connect-src 'self' ${apiUrl}`,
  "font-src 'self'",
  "frame-ancestors 'none'",
].join('; ');

const nextConfig = {
  output: 'standalone',
  // Hide the dev-only indicator (lower-left circle) so it doesn't appear in screenshots.
  devIndicators: false,
  allowedDevOrigins: ['192.168.*.*'],
  async redirects() {
    return [
      // DJ AI connector/model settings moved into the account page (#357).
      // Keep old bookmarks/links working with a permanent (308) redirect.
      { source: '/settings/ai', destination: '/account', permanent: true },
    ];
  },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          // X-XSS-Protection removed — deprecated per OWASP (see H-I8)
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=63072000; includeSubDomains; preload',
          },
          { key: 'Content-Security-Policy', value: csp },
        ],
      },
      {
        // Allow OBS/streaming tools to embed overlay pages.
        // SECURITY (M-F7): Next.js headers() arrays REPLACE (not merge) more-specific
        // rules. Must re-declare every other header from the general block so
        // the overlay route isn't left naked (no HSTS / nosniff / Referrer-Policy
        // / CSP script-src restrictions).
        source: '/e/:code/overlay',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=63072000; includeSubDomains; preload',
          },
          {
            key: 'Content-Security-Policy',
            // Same CSP as general block but with frame-ancestors * for embedding
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https:",
              `connect-src 'self' ${apiUrl}`,
              "font-src 'self'",
              "frame-ancestors *",
            ].join('; '),
          },
          // Remove X-Frame-Options for this route (CSP frame-ancestors takes precedence)
          { key: 'X-Frame-Options', value: '' },
        ],
      },
    ];
  },
}

module.exports = nextConfig
