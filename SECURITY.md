# Security Policy

## Supported Versions

Only the latest release on the `main` branch is actively supported. Patch
releases are published from `main`; older releases are not maintained unless a
vulnerability is severe and backporting is explicitly announced.

## Reporting a Vulnerability

This repository is public and may expose sensitive information if secrets are
committed. If you find a vulnerability or a potential secret leak:

1. Do **not** open a public issue.
2. Send a private report through the repository "Security" tab
   (GitHub Security Advisories), or email the maintainers using the address
   listed in the commit metadata / project contact.
3. Include: affected version or commit, a minimal reproduction, impact, and a
   suggested fix when possible.

You will receive an acknowledgement within **72 hours**. After triage, we aim
to publish a fix and an advisory within **30 days** for confirmed issues.

## Reporting secrets

If you accidentally commit a credential or token:

1. Revoke the secret immediately on the provider side.
2. Open a private Security Advisory so the token can be scrubbed from history
   and `git push` protection can be configured.

## Security Practices

- Secret material is never committed. Environment variables are loaded from
  `.env` files that are git-ignored.
- External credentials (IGDB OAuth, MEGA sessions) are only used inside the
  runtime environment and are not part of the source tree.
- SQLite files, MEGA dumps and generated JSON exports are git-ignored.
- Dependencies are kept up to date with automated scanning and Dependabot.
- CodeQL static analysis runs on pull requests and the default branch.

## Supply Chain

The backend pins dependencies through `uv.lock` and the frontend through
`pnpm-lock.yaml`. Lockfiles must be committed and updated together with any
dependency change so builds are reproducible.
