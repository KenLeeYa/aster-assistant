# Publication verification

This public source snapshot contains only reviewed project files and starts with a new Git root commit. It excludes the original repository history, reports, private prompt specifications, local runtime data, model files, and credential files. Personal examples have been replaced with synthetic examples.

Local verification before publication:

- Python tests: 118 passed, 2 skipped. The skipped checks need a live PostgreSQL URL and symlink support.
- Mypy: 46 source files passed.
- Web TypeScript typecheck and lint of changed components passed.
- Gitleaks scans of the worktree and Git history found zero findings.

The GitHub CI production dependency audit is a required gate. The development dependency audit runs as a visible advisory step because upstream `braces@3.0.3`, pulled in by the ESLint toolchain, has a high-severity advisory with no patched release. It is not a passing security result. Review or replace that toolchain dependency before treating the full dependency audit as clean.

These checks do not establish production readiness. Live PostgreSQL migration, full CI, browser rendering and end-to-end tests, voice hardware, Windows/WSL deployment, and mobile integrations still require verification on the target host.
