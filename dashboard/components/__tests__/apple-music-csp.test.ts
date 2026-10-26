// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const root = join(__dirname, '../..');
const require = createRequire(join(root, 'next.config.js'));
const nextConfig = require(join(root, 'next.config.js'));

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
