# Contributing

Thank you for contributing to AlucardiosDataBase. Please read this guide, the
[README](README.md), and the [AGENTS](AGENTS.md) file before opening an issue
or a pull request.

## Code of Conduct

This project and everyone participating in it is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to
uphold this code.

## Reporting Issues

Use the issue templates. A good bug report includes:

- Environment: OS, Python/Node versions, Docker Compose version.
- Steps to reproduce, including the exact commands.
- Expected behavior and actual behavior.
- Relevant logs (sanitized, without secrets).
- If the issue involves IGDB or MEGA, the title/slug or node path used.

Never include real credentials, sessions, or MEGA account data in an issue.

## Development Workflow

1. Fork the repository and create a branch from `main` with a descriptive name
   (for example `fix/sync-empty-guard`).
2. Follow the repository layout and conventions described in `AGENTS.md`.
3. Write or update tests for the change.
4. Run the quality gates locally:
   - Backend: `cd backend && uv sync && uv run pytest`
   - Frontend: `cd frontend && pnpm install && pnpm build`
5. Open a pull request using the pull request template.

The `main` branch is protected: all changes must land through a pull request
that passes the continuous integration checks and is reviewed.

## Commit Conventions

This repository uses [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` a new capability
- `fix:` a bug fix
- `docs:` documentation only
- `test:` tests only
- `chore:` maintenance, tooling, dependencies
- `refactor:` code change that neither fixes a bug nor adds a feature
- `perf:`, `build:`, `ci:`, `style:` for their respective scopes

Example: `fix(sync): abort on empty dump instead of removing the catalog`.

Commit messages must not contain secrets. Do not commit generated artifacts:
database files, MEGA dumps, `data/*.json` exports, `.env` files, lockfile
dependencies you did not intend to change.

## Branch Protection

`main` requires:

- Status checks to pass (tests, build, dependency and security scans).
- At least one approving review for non-maintainer contributions.
- Conventional commit titles on pull requests.

## Licensing

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
