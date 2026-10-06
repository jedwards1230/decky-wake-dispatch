# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

**Wake Dispatch** is a Decky Loader plugin that sends Wake-on-LAN magic packets from the
Steam Quick Access menu, by hand or automatically on boot and resume. A Python backend
(`main.py` adapting the `wake_dispatch` package in `py_modules/`) does all networking,
storage and automation; the React panel (`src/`) only calls it. It ships as
`wake-dispatch.zip` on GitHub Releases, not through the Decky plugin store.

Build, test, and lint commands live in [CONTRIBUTING.md](CONTRIBUTING.md).

- Backend callables, on-disk files and behaviour rules:
  [`docs/CONTRACT.md`](docs/CONTRACT.md). Read it before changing `main.py`, `src/api.ts`
  or anything a callable returns.
- Test layers, the on-device check and what tests must avoid:
  [`docs/TESTING.md`](docs/TESTING.md).
- What users are told (install, PC setup, privacy): [`README.md`](README.md).

## Gotchas

- **"sent" only means the packet left this device.** Wake-on-LAN broadcasts don't cross
  subnets or VLANs, and guest Wi-Fi or client isolation drops them; no test can see that.
  Never report or display a "sent" as "woken" — only a status check can say the PC is up,
  and `unknown` must never be shown as a failure.
- **URL installs never auto-update.** Decky doesn't track plugins installed from a URL,
  so users only get a fix by reinstalling from
  `releases/latest/download/wake-dispatch.zip`. The asset name `wake-dispatch.zip` is
  therefore as frozen as the folder name, and every release must be marked latest.
- **Steam client updates break `@decky/ui`, not the backend.** A Steam update can break
  panel components overnight; automation keeps working because it lives in the backend.
  Keep automation logic, timers and retries in Python — never in `src/`, which only runs
  while the panel is open and only in Game Mode.
- **Resume detection is a clock gap, not an event.** A 5 s ticker on `CLOCK_BOOTTIME`
  fires when more than 20 s pass between ticks, so suspends shorter than about 20 s are
  missed. Don't "simplify" it to wall time (NTP steps fake resumes) or `CLOCK_MONOTONIC`
  (on some kernels it advances through s2idle and hides every suspend).
- **TypeScript stays on 5.x.** `@decky/rollup` depends on `typescript ^5`; a 6.x bump
  breaks the build. Decline such Dependabot updates. `@decky/api` (exact) and
  `@decky/ui` (`~4.12`) are pinned to the loader's runtime and bumped by hand only.
- **React is not a dependency.** `@decky/rollup` maps `react`, `react-dom` and
  `@decky/ui` to the Steam client's globals (`SP_REACT`, …); that's why `package.json`
  tells pnpm to ignore the missing React peers. Adding React to `dependencies` bundles a
  second copy.
- **`Plugin` keeps state on class attributes, created lazily.** Legacy loaders call the
  methods with the class itself as `self`, and Decky's directory constants are only
  valid at call time. Don't add `__init__` state or read `decky.DECKY_PLUGIN_*` at import.
- **Adding a backend module touches three places**: `wake_dispatch.MODULES`, `_IMPORTED`
  in `main.py`, and the module count asserted in `tests/test_plugin.py`.
- **`pytest` fails on anything but Python 3.11 by design** (`test_python_version_guard`).
  Use a 3.11 virtual environment rather than editing the guard.
- **Automatic and manual wakes order their work differently.** Automatic waits for a
  route first, because the boot gate may only record the boot id once the network is up
  (otherwise a boot without network never wakes); manual selects devices first so
  "nothing to wake" returns instantly. Keep the order when refactoring `Dispatcher._run`.
- **The home-network gate is the router's IP address, checked once per wake.** Another
  network with the same gateway address counts as home, and a network change during the
  burst isn't re-checked. Document it, don't pretend otherwise.
- **`README.md` ships inside the zip.** `scripts/package.sh` requires it, and the CI zip
  check fails without it; it is also what users see, so keep it free of contributor
  detail.

## Architecture invariants (violations are bugs)

1. **Frozen identity.** `plugin.json` `"name"` (`Wake Dispatch`) and the zip's single
   top-level folder `wake-dispatch/` never change. Decky extracts the zip into its plugins
   directory, keys the plugin's settings, data and log directories to that folder name,
   and finds an installed plugin by its `plugin.json` name; renaming either strands
   every user's saved devices.
2. **Stdlib-only Python 3.11 backend.** Decky runs it on its bundled interpreter with
   `py_modules/` appended to `sys.path`; there is no way to install packages on a user's
   device. Only `requirements-dev.txt` may add packages, for tests and lint.
3. **No root.** `plugin.json` keeps `"flags": []`.
4. **The contract is frozen.** Callables, argument order and return shapes in
   [`docs/CONTRACT.md`](docs/CONTRACT.md) change only compatibly, and `src/api.ts`
   mirrors them in the same PR.
5. **Automation is opt-in per device; manual wakes always send.** No device wakes
   automatically unless its `auto` list says so, and neither the home-gateway check nor
   the automation lock ever blocks a wake the user pressed (a manual wake still needs a
   default route within 5 s).
6. **Writes are atomic.** Settings and state are written only through
   `storage.atomic_write_json` (temp file, fsync, `os.replace`); a corrupt or newer file
   is backed up or quarantined, never overwritten blind.
7. **No network traffic beyond what the README's Privacy section lists**: the wakes the
   user triggers or enabled, status checks (and their name lookups) to configured
   hosts, and reverse lookups for the network picker.

## Design discipline

- **Errors are data.** Callables return `ok: false` with a plain-language `error` (and
  `field` / `index` for the editor) instead of raising; user-facing copy lives in
  `src/strings.ts` and the backend's message constants.
- **Everything is injectable.** Paths, readers, clocks, sleeps and senders are
  parameters or module constants read at call time, so tests never touch the real
  system.
- **Placeholders only.** Examples, fixtures and docs use `aa:bb:cc:dd:ee:01`-style MACs
  and `192.0.2.x` / `198.51.100.x` / `192.168.1.x` addresses.

## Commands

```bash
scripts/package.sh --no-build                # re-zip the existing dist/ after a backend-only change
scripts/package.sh --version 1.2.3           # stamp a version into the packaged package.json
pytest -q tests/test_dispatch.py -k gateway  # one backend test file or test
```

On a device the backend log is `~/homebrew/logs/wake-dispatch/`.

## What belongs where

Facts about one person's machine or setup don't belong here. Anything a contributor
needs to work in this repo — gotchas, invariants, requirements — goes in this file or
`docs/`, in the same PR as the change that makes it true.
