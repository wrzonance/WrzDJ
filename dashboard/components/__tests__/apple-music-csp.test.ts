import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { afterEach, describe, expect, it, vi } from 'vitest';

const root = join(__dirname, '../..');
const require = createRequire(join(root, 'next.config.js'));
const nextConfig = require(join(root, 'next.config.js'));

afterEach(() => vi.unstubAllEnvs());

async function configuredConnectSources(apiUrl: string | undefined) {
  vi.stubEnv('NEXT_PUBLIC_API_URL', apiUrl);
  const configPath = require.resolve(join(root, 'next.config.js'));
  delete require.cache[configPath];
  const headers = await require(configPath).headers();
  return headers.map((entry: { headers: { key: string; value: string }[] }) => {
    const policy = entry.headers.find(({ key }) => key === 'Content-Security-Policy');
    return directives(policy?.value ?? '')['connect-src'];
  });
}

function cspFromNginxTemplate(path: string, overlay: boolean) {
  const template = readFileSync(join(root, '..', path), 'utf8');
  const policies = [...template.matchAll(/add_header Content-Security-Policy "([^"]+)"/g)];
  const policy = policies.find(([, value]) =>
    overlay ? value.includes('frame-ancestors *') : value.includes("frame-ancestors 'none'"),
  )?.[1];
  if (!policy) throw new Error(`Could not find ${overlay ? 'overlay' : 'page'} CSP in ${path}`);
  return policy;
}

function directives(policy: string) {
  return Object.fromEntries(
    policy.split(';').map((directive) => {
      const [name, ...values] = directive.trim().split(/\s+/);
      return [name, values];
    }),
  ) as Record<string, string[]>;
}

describe('Apple Music account-link CSP', () => {
  // Regression for baseline 57cfcdc6867f: the client resolves 127.0.0.1:8000
  // when opened on that loopback host, which the default CSP used to block.
  it('allows both local API loopback names when no API URL is configured', async () => {
    for (const sources of await configuredConnectSources(undefined)) {
      expect(sources).toContain('http://localhost:8000');
      expect(sources).toContain('http://127.0.0.1:8000');
      expect(sources).not.toContain('*');
    }
  });

  it('uses only the configured API origin when an API URL is provided', async () => {
    for (const sources of await configuredConnectSources('https://api.example.test')) {
      expect(sources).toContain('https://api.example.test');
      expect(sources).not.toContain('http://localhost:8000');
      expect(sources).not.toContain('http://127.0.0.1:8000');
    }
  });

  it('allows MusicKit script and API only on normal Next.js pages', async () => {
    const headers = await nextConfig.headers();
    const page = headers.find(({ source }: { source: string }) => source === '/(.*)');
    const overlay = headers.find(({ source }: { source: string }) => source === '/e/:code/overlay');
    const pagePolicy = directives(
      page.headers.find(({ key }: { key: string }) => key === 'Content-Security-Policy').value,
    );
    const overlayPolicy = directives(
      overlay.headers.find(({ key }: { key: string }) => key === 'Content-Security-Policy').value,
    );

    expect(pagePolicy['script-src']).toContain('https://js-cdn.music.apple.com');
    expect(pagePolicy['connect-src']).toContain('https://api.music.apple.com');
    expect(pagePolicy['frame-src'] ?? []).not.toContain('https://authorize.music.apple.com');
    expect(overlayPolicy['script-src']).not.toContain('https://js-cdn.music.apple.com');
    expect(overlayPolicy['connect-src']).not.toContain('https://api.music.apple.com');
  });

  it.each([
    ['deploy/nginx/app.conf.template', false],
    ['deploy/nginx/app.conf.template', true],
    ['deploy/dev-proxy/nginx/app.conf.template', false],
    ['deploy/dev-proxy/nginx/app.conf.template', true],
  ] as const)('%s overlay=%s keeps Apple origins scoped to normal pages', (path, overlay) => {
    const policy = directives(cspFromNginxTemplate(path, overlay));

    if (overlay) {
      expect(policy['script-src']).not.toContain('https://js-cdn.music.apple.com');
      expect(policy['connect-src']).not.toContain('https://api.music.apple.com');
    } else {
      expect(policy['script-src']).toContain('https://js-cdn.music.apple.com');
      expect(policy['connect-src']).toContain('https://api.music.apple.com');
      expect(policy['frame-src'] ?? []).not.toContain('https://authorize.music.apple.com');
    }
  });
});
