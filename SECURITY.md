# Security notes

Public ask and repository routes are rate limited where they consume resources.
Admin routes require `X-API-Key`, compared in constant time and never logged.
Metrics and query explorer data are admin-only.

Repository URLs are canonicalized to public GitHub HTTPS URLs. Repository
contents are never executed and are delimited as untrusted prompt data; citation
validation is structural, not a semantic proof. The webhook verifies HMAC-SHA256
over the raw body before parsing, deduplicates delivery IDs, and only enqueues
registered default-branch pushes.

Provider keys, database URLs, admin keys, and webhook secrets belong in the host
secret manager. Pipeline snapshots contain no secrets. The container runs as a
non-root user and excludes `.env` from the image.

Private repositories, user accounts, OAuth, distributed rate limiting, and
arbitrary URL fetching are out of scope. Review dependency updates with
`uv lock --upgrade` in a controlled branch and run lint, tests, and the image
build before release.
