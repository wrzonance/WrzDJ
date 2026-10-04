# API locked runtime

The API Dockerfile at 3d178561 ignores uv.lock and installs floating version floors.
A comparison of its installed production dependencies with the lock found 44 mismatches
or missing packages. Scorecard finding 129 identifies the unhashed installation.

Install production dependencies from the committed lock with enforced artifact hashes.
Use a digest-pinned temporary uv binary; do not ship uv or pip. For the source-only pyaes and ratelimit packages, install a hash-verified locked setuptools
build group first and disable build isolation; remove the backend after installation.
This prevents source builds from downloading dependencies outside the lock. Run application source from /app;
no application code consumes installed wrzdj-server distribution metadata.
Keep the existing non-root entrypoint, migrations, bootstrap and health behavior.

Add a CI image smoke test that independently exports the source lock, checks installed
versions with environment markers, and exercises startup against disposable PostgreSQL.
No host ports or live databases; clean up containers, network and temp files on failures.
Retain the 85% backend coverage gate and existing security scans. Verify installation support for both amd64 and arm64. Track this build/dependency work through dashboard #588.

Research: https://docs.astral.sh/uv/guides/integration/docker/ and
https://docs.astral.sh/uv/reference/cli/ document temporary binary mounts, locked exports,
required hashes and wheel-only installation.
