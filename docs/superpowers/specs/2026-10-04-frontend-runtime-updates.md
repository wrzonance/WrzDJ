# Frontend runtime dependency updates

Tracked by #588 and privacy bug #730; reuse Renovate PR #726 and supersede #729.
Base: `58dc3dd15d2a96a79c5422e1c805d5d80aafdb1b`.

Update Next to 16.3.8, simple-keyboard to 3.8.192 and Thumbmark to 1.12.0.
Preserve guest fingerprint reconciliation, keyboard behavior and production builds.
The published Thumbmark package enables sampled upstream logging even without an
API key. A real browser probe of installed 1.11.0, with sampling forced and all
network requests intercepted, observed experimental and logging requests.

Use the public `getThumbmark` API with per-call `logging: false` and
`collect_beacon: false`. Map its `thumbmark`/`components` result to the existing
WrzDJ `fingerprint_hash`/`fingerprint_components` request. This uses the same
underlying fingerprint function as the legacy adapter, without mutable global
options. No API key or proxy mode is configured. Test the actual library with
sampling forced: fingerprint generation must make no external requests, while
WrzDJ identification and refresh still receive nonempty hashes and components.

The published 1.11.0 and 1.12.0 component sources, component filter, hash and stable
serialization implementations compare byte-for-byte identical. The backend
still checks the canonical cookie before fingerprint reconciliation. The network
regression observes fetch, beacon, XHR, image and script transports; an actual
Chromium check of both built guest pages also intercepts every outbound request.

js-yaml 5 is blocked by the current openapi-typescript 7.13.0 integration.
An isolated normal install with js-yaml 5.4.2 fails importing Redocly 1's removed
`types.merge` API. A second probe with Redocly 2.57.0 (which supports js-yaml 5)
fails because openapi-typescript imports the unexported `lib/ref-utils.js` path.
Keep the working YAML 4 parser and report both reproductions on #588. Do not
patch third-party internals or replace the schema generator solely to clear a
dependency dashboard entry. Dashboard TypeScript 7 has a separate documented
ESLint peer compatibility blocker.

Sources: published npm package source/manifests for these exact versions and
https://github.com/thumbmarkjs/thumbmarkjs/releases/tag/v1.12.0.
