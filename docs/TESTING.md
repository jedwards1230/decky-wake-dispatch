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
  (`helpers.FakeSocket`), `discovery.make_socket` raises so a test that would open a
  real scan or mDNS socket fails, and any real name lookup fails the test unless it is
  marked `real_dns`.
- `test_mac_packet.py`: MAC and SecureOn normalisation, magic packet bytes (102 / 108),
  socket options.
- `test_storage.py`: atomic writes, migration of old settings shapes, corrupt-file
  quarantine (including JSON nested too deeply and over-long numbers), files from a
  newer schema.
- `test_devices.py`: device validation (id alphabet, name cleaning of bidi,
  zero-width, surrogate and private-use characters and NFC, host syntax), repairing
  stored devices whose id or status host fails the rules, id generation, the 64-device and
  256 KiB import limits, export, import merge and replace.
- `test_netinfo.py`: route and ARP parsing, interface state, the daemon-thread name
  lookups (timeouts, queueing beyond the thread limit, stuck threads, a thread that
  can't start, late answers and answers after the loop closed, cache limits, shutdown,
  a subprocess whose lookup hangs still exits at once), and the status mapping
  (refused -> awake, no route or slow lookup -> unknown, timeout -> asleep,
  `EHOSTUNREACH` depending on the default route, connecting to the numeric address).
- `test_discovery.py`: scan targets (prefix sizes, refused networks, VPN interfaces),
  probe pacing and route-change aborts with fake sockets and sleeps, find-by-address
  (input checks, off-link refusal with zero sends, ARP hits, the single probe and its
  ARP polling, names, busy and cancel), the mDNS packet
  parser's bounds, name preference, the busy lock, cooldown, cancel and time budget,
  and that `_unload` never yields while a scan or find is pending.
- `test_dispatch.py`: device selection, the home-gateway gate, bursts, outcomes and
  reasons, per-device error isolation.
- `test_automation.py`: the boot gate and the resume watcher, driven by injected clocks
  and sleeps, and the synchronous `cancel`.
- `test_updates.py`: the update check with an injected fetch and clock: strict release
  parsing, TLS context and fail-closed CA lookup, the HTTPS-only opener and redirect
  guard, the thread helper, cadence (daily cache, backoff, the 60 s "Check for updates"
  throttle, invalid or future caches), the setting, and that `_uninstall` keeps its
  files. `conftest.py` replaces the real fetch with one that fails the test.
- `test_plugin.py`: end to end through `main.Plugin` with fake network files, including
  a guard that the interpreter is Python 3.11, an import of every module under plain
  Python the way Decky loads them, callables given stray or wrong-typed arguments,
  backing up a dropped device only once, and `_unload` finishing without suspending
  (`coro.send(None)` must raise `StopIteration` while automation tasks are pending).
- `test_smoke.py`: every callable in [CONTRACT.md](CONTRACT.md) exists on `Plugin` and is
  async.

Run one file or test with `pytest -q tests/test_dispatch.py -k gateway`.

## Unload under Decky

`_unload` and process exit can't be fully proven inside pytest, because the failure
depends on how Decky's sandboxed plugin process shuts down: the loader sends SIGTERM
and closes the plugin's socket, after which Decky 3.2's socket listener can spin the
event loop, and Decky SIGKILLs the process if it is still alive 5 s later. To check a
change to shutdown, lookups or background tasks, use a small throwaway script (not part
of the repo) that mimics that runner: in a child `multiprocessing.Process`, import
`main.py` with a stub `decky` module, run `Plugin._main()` on a fresh event loop with
SIGTERM wired to "await `_unload()`, stop the loop, `sys.exit(0)`", and serve a copy of
the loader's Unix-socket listener. The parent connects to the socket, calls
`terminate()`, closes the socket and checks that the child exits with code 0 well
inside 5 s. Repeat with `socket.gethostbyaddr` and `socket.getaddrinfo` patched to
sleep for 30 s and `neighbours` / `status` called just before the stop. On a device,
restart `plugin_loader` and check that its journal shows "Wake Dispatch backend
unloading" and no kill of the plugin process.

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
4. For the update check, install a build whose packaged version is older than the
   latest release (`scripts/package.sh --version 0.0.1`). Open the panel with the daily
   check still off (the default) and confirm the backend log shows no update request;
   press **Check for updates** and check it shows the newer version; press **Update**
   and check Decky's own confirmation names Wake Dispatch and the new version
   (cancelling leaves the plugin installed).
5. Read the backend log at `~/homebrew/logs/wake-dispatch/` for errors.

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
