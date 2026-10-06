# Contributing to Wake Dispatch

Wake Dispatch is a Decky Loader plugin: a Python backend (`main.py` plus the
`wake_dispatch` package in `py_modules/`) and a React frontend (`src/`) bundled with
Rollup. All changes go through the workflow below.

## Prerequisites

- **Node.js** (current LTS) and **pnpm 9.15.9**. The pnpm version is pinned by
  `packageManager` in `package.json`; `corepack enable` picks it up, or run it through
  `npx -y pnpm@9.15.9`.
- **Python 3.11**, the version Decky Loader bundles. The backend uses the standard
  library only; `requirements-dev.txt` pins the test and lint tools (pytest,
  pytest-asyncio, ruff). Install them in a virtual environment:

  ```bash
  python3.11 -m venv .venv && . .venv/bin/activate
  ```

- `python3` and `node` on `PATH` for `scripts/package.sh`.

## Build, test & lint

These are the commands CI runs (`.github/workflows/ci.yml`), one block per job.

Frontend (`frontend` job):

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
```

Backend (`backend` job):

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
pytest -q
```

Plugin zip (`package` job):

```bash
scripts/package.sh
```

`scripts/package.sh` builds the frontend and writes `out/wake-dispatch.zip`, checking
that the archive holds a single `wake-dispatch/` folder with every file Decky needs.
`scripts/package.sh --help` lists its options. Without a global pnpm, run it as
`PNPM="npx -y pnpm@9.15.9" scripts/package.sh`. The `package` job also uploads the zip as
the `wake-dispatch-zip` workflow artifact on every run.

How to prove a change, beyond these commands, is in [docs/TESTING.md](docs/TESTING.md).

## Documentation

Keep documentation current as part of the change, not as a follow-up — update the
README and any affected docs in the same PR.

- A change to a backend callable, its arguments or its return shape →
  [docs/CONTRACT.md](docs/CONTRACT.md), `src/api.ts` and `CONTRACT_CALLABLES` in
  `tests/test_smoke.py` in the same PR.
- A change to what users see or need to set up → `README.md`.
- A change to the test layers or CI jobs → [docs/TESTING.md](docs/TESTING.md).

## Before you open a PR

- Make sure all CI checks pass locally first — run the formatter, linter, and tests
  above.
- If the change touches the panel, build the zip and try it on a device running Decky
  Loader (see [docs/TESTING.md](docs/TESTING.md)).

## Branching & commits

- Branch off `main`; never commit directly to `main`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) prefixes (`feat:`,
  `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, …).
- Sign your commits where possible (`git commit -S`).
- Keep each PR focused; delete dead code rather than commenting it out.

## Pull requests

- Open the PR against `main`.
- Every PR runs CI; the `frontend`, `backend` and `package` jobs are required checks.
  Resolve **all** review threads before the PR is merged.
- An automated code review runs on each PR; address and resolve its threads like any
  other review.
- A PR can be merged once CI is green and all review threads are resolved.

## Releases

Releases are opt-in. Before merging, add one of `semver:patch`, `semver:minor`, or
`semver:major` to the PR to cut a release on merge; with no label, merging does not
release. A release publishes a `vX.Y.Z` tag with auto-generated release
notes, and attaches `wake-dispatch.zip` (built from that tag by `scripts/package.sh`) as
the release asset. Every release is marked "latest", which is what the README's install
URL points at.

The git tag is the version's source of truth. CI never commits a version bump; it stamps
the tag's version into the packaged copy of `package.json` only.

A maintainer can also release manually by running the `Release` workflow from `main` with
an explicit version:

```bash
gh workflow run release.yml --repo jedwards1230/decky-wake-dispatch --ref main -f version=0.1.0
```

This tags the current `main` commit as `vX.Y.Z` (or reuses that tag if it already
exists) and publishes it with GitHub-generated notes. Cut the first release this way.
Only dispatch a version newer than the current latest release.

If a release run fails, use **Re-run failed jobs**, not "Re-run all jobs" (re-running
the version step after it pushed a tag cuts the next version), or dispatch the workflow
with the version of the tag that was already pushed.

Neither release path needs repository secrets. Optional secrets for the automated review
and for release notes are described in the header comments of the workflow files in
`.github/workflows/`; without them the review job is skipped and releases use
GitHub-generated notes.
