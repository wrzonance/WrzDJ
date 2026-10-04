# Container image refresh

Tracked by security issue #733 and dependency dashboard #588. Reuse Renovate #721, superseding #722
only after its PostgreSQL 16 update is included and verified.

Update the bridge Node 26 image, all three PostgreSQL 16 Compose images, and
the development proxy nginx image. Preserve database major, volume mount paths,
application dependencies, proxy configuration and network exposure. Build the
proxy locally from its pinned upstream image to apply available Alpine fixes;
setup must rebuild it on invocation. Separate bridge build/runtime stages, use
the committed npm lock, prune development dependencies, and remove global npm
from the runtime. Both custom images apply `apk upgrade --no-cache`, matching
the existing dashboard policy. Layers remain cached until the base digest changes.
PostgreSQL 18 is a separate queued change requiring migration validation.

Verified registry index digests:

- node:26-alpine: `sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80`
- postgres:16-alpine: `sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`
- nginx:1.31-alpine: `sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2`

All three indexes include amd64 and arm64. Native execution here is amd64.
The bridge baseline builds and its actual SQLite native module performs a query
under Node 26 on Alpine. npm warnings alone do not establish a runtime failure.
No application dependency change is needed. A runtime regression must reject
npm, the compiler and the test runner while retaining real protocol imports and
SQLite operations. Add bridge/proxy builds and smoke tests to the existing CI
Docker job, plus both images to the existing Trivy matrix and path filters.

Invariants: bridge compilation, protocol imports and native SQLite access work
inside the new image; PostgreSQL can reopen an existing PostgreSQL 16 volume
without losing a sentinel row; the application's Alembic migration/drift check
passes against the new database; nginx accepts the actual rendered templates and
retains redirects, proxy routing and security headers. Tests use only isolated,
owned containers, volumes and networks. Never run live deployment scripts.

Validate existing bridge types/tests/coverage/audit, all Compose structures,
container scans, PR CI and post-merge main checks. No gate is weakened.

Sources:
- https://hub.docker.com/_/node (official Alpine image)
- https://www.postgresql.org/docs/16/upgrading.html (minor upgrade storage compatibility)
- https://nginx.org/en/CHANGES (1.31 behavior and security fixes)

Security evidence: the unmodified bridge image had 13 fixable HIGH findings
in npm and the TypeScript compiler; the upstream nginx image had two in
libexpat/pcre2. The hardened images both scan with zero fixable HIGH/CRITICAL.
The bridge absence-of-build-tools test fails on the old image and passes on the
new image. Proxy checks cover real templates, TLS routing, redirects, security
headers, embeddable overlays, uploads and sanitized upstream-error responses.

The PostgreSQL image reports 22 Go-stdlib findings exclusively in gosu 1.19,
compiled with Go 1.24.6. Its official source at
`6456aaa0f3c854d199d0f037f068eb97515b7513` only resolves local passwd/group entries,
switches groups/uid/gid and execs the entrypoint. The container calls it with the
literal user `postgres` before the server starts. It does not use the affected
HTTP/TLS/certificate, URL/DNS, mail/MIME, HTML/XML/ASN.1 parsers or `os.Root` API;
the Windows-specific finding also does not apply to this Linux image. These are
non-reachable scanner matches, not a clean scan claim. No suppression was added.
Reassess on the separately queued PostgreSQL 18 upgrade or a changed gosu invocation.
Source: https://github.com/tianon/gosu/tree/1.19
