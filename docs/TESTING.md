# Testing Wake Dispatch

How to prove a change works. The commands themselves are in
[CONTRIBUTING.md](../CONTRIBUTING.md#build-test--lint); this file says what each layer
covers and what it can't.

## What CI runs

Every pull request and every push to `main` runs `.github/workflows/ci.yml`. All three
jobs are required checks.

| Job | Runs | Proves |
| --- | --- | --- |
| `frontend` | `pnpm typecheck`, `pnpm build` | the panel type-checks against `@decky/ui` / `@decky/api` and bundles to `dist/index.js` |
| `backend` | `ruff check .`, `ruff format --check .`, `pytest -q` on Python 3.11 | lint, formatting, and the backend test suite |
| `package` | `scripts/package.sh` plus a zip layout check | the release zip has one `wake-dispatch/` folder with `plugin.json`, `package.json`, `main.py`, `LICENSE`, `README.md`, `dist/index.js` and `py_modules/`, and no caches or source maps |

The `PR Review` workflow is an advisory automated review, not a test.

## Backend tests (`tests/`)

pytest with `asyncio_mode = "auto"`; `pyproject.toml` puts `.` and `py_modules` on the
path the same way Decky does.

- `conftest.py` installs a stub `decky` module before `main` is imported, points the
  plugin settings, runtime and log directories at a fresh temp directory per test, and
  sandboxes every test: `/proc/net/route`, `/proc/net/arp`, `/sys/class/net` and the boot
  id are redirected to empty fake files, the UDP socket is replaced by a recorder
  (`helpers.FakeSocket`), and any real name lookup fails the test unless it is marked
  `real_dns`.
- `test_mac_packet.py`: MAC and SecureOn normalisation, magic packet bytes (102 / 108),
  socket options.
- `test_storage.py`: atomic writes, migration of old settings shapes, corrupt-file
  quarantine, files from a newer schema.
- `test_devices.py`: device validation, id generation, export, import merge and replace.
- `test_netinfo.py`: route and ARP parsing, interface state, reverse lookups, status
  checks.
- `test_dispatch.py`: device selection, the home-gateway gate, bursts, outcomes and
  reasons, per-device error isolation.
- `test_automation.py`: the boot gate and the resume watcher, driven by injected clocks
  and sleeps.
- `test_plugin.py`: end to end through `main.Plugin` with fake network files, including
  a guard that the interpreter is Python 3.11 and an import of every module under plain
  Python the way Decky loads them.
- `test_smoke.py`: every callable in [CONTRACT.md](CONTRACT.md) exists on `Plugin` and is
  async.

Run one file or test with `pytest -q tests/test_dispatch.py -k gateway`.

## Frontend

There are no frontend unit tests. `pnpm typecheck` and `pnpm build` are the automated
checks; anything visual or interactive is verified on a device.

## On a device

The automated layers can't show the panel inside Steam or a real packet waking a PC.
For a change to the panel, or to how packets are sent, check it on a device running
Decky Loader:

1. Build the zip with `scripts/package.sh`, or download the `wake-dispatch-zip` artifact
   from the PR's `package` job.
2. Copy the zip to the device and, with Decky's Developer mode on, choose Decky
   settings → Developer → **Install Plugin from ZIP File**. Saved devices are kept
   across reinstalls.
3. Exercise the change: add a device, wake it, and check the status and notifications.
   For automation, enable it on a device, then reboot or suspend for longer than 20
   seconds and check the "Last automatic wake" line.
4. Read the backend log at `~/homebrew/logs/wake-dispatch/` for errors.

## Avoid

- Tests that touch the real `/proc`, `/sys`, network or DNS. Use the `conftest.py`
  fixtures and the injectable paths, readers, clocks and senders the modules accept.
- Real sleeps in tests. The `Dispatcher` and `Automation` take `sleep` and clock
  callables for this.
- Real MAC addresses, hostnames or LAN addresses in fixtures. Use placeholders such as
  `aa:bb:cc:dd:ee:01` and documentation ranges (`192.0.2.x`, `198.51.100.x`).
- Third-party Python packages in the backend. Decky runs it on its bundled Python with
  no way to install dependencies, so only `requirements-dev.txt` may add packages, and
  only for tests and linting.
