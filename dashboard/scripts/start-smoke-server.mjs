import { cp } from 'node:fs/promises';

// Match the Docker image's standalone layout, including its static assets.
const dashboard = new URL('../', import.meta.url);
await cp(new URL('public/', dashboard), new URL('.next/standalone/public/', dashboard), {
  recursive: true,
});
await cp(new URL('.next/static/', dashboard), new URL('.next/standalone/.next/static/', dashboard), {
  recursive: true,
});
await import(new URL('.next/standalone/server.js', dashboard).href);
