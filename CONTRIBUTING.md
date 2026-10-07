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

## Installing a release on a device over CDP (dev only)

`scripts/install-over-cdp.mjs` opens Decky Loader's install prompt for a published
release on a device, so you don't have to type the URL on the device. It needs Node 22 or
newer and no dependencies.

On the device, turn on Steam's CEF remote debugging: Decky settings → Developer →
**Allow Remote CEF Debugging**. Then, from your computer:

```bash
scripts/install-over-cdp.mjs 192.0.2.10 --dry-run          # latest release: show what would be installed
scripts/install-over-cdp.mjs 192.0.2.10 v0.1.0             # open the prompt for v0.1.0
scripts/install-over-cdp.mjs 192.0.2.10 --port 8081        # CEF port (8081 is the default)
```

The script resolves the release through the GitHub API and checks it the same way the
plugin's update check does (tag format, not a draft or prerelease, exactly one
`wake-dispatch.zip` asset, its download URL, size and sha256 digest). It then connects to
the device's `SharedJSContext` target, checks whether Wake Dispatch is already installed,
and asks Decky to install it with the release's sha256: as an install, a reinstall (same
version already installed) or an update (any other installed version). `--dry-run` stops
before that last step. The script never confirms anything: Decky shows its usual confirm
dialog on the device, and nothing is installed until someone taps Install, Reinstall or Update there.

**Security:** remote CEF debugging is unauthenticated. While it is on, anyone on your
network can control the Steam client on port 8081 — including Decky's backend and its
install route, which runs as root. Turn it off when you are not developing.

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
