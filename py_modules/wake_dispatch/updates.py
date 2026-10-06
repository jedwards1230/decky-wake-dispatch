"""Update check: ask GitHub for this plugin's latest release, never install anything.

One HTTPS GET to ``API_URL`` at most once a day (plus backoff after failures and
the user's "Check now"), parsed strictly. The result is cached in
``<runtime dir>/update.json``; the on/off setting lives in
``<settings dir>/options.json``. Installing is left to Decky's own confirmation
prompt, which the panel opens with the release's URL and sha256.

TLS always verifies the certificate and hostname, using the system CA bundle
or, failing that, ``certifi`` (bundled with Decky's interpreter). With neither,
the check fails closed. Every constant is read at call time so tests can patch
it, and the fetch, clock and paths are injected so tests never touch the network.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from wake_dispatch import storage
from wake_dispatch.log import get_logger

API_URL = "https://api.github.com/repos/jedwards1230/decky-wake-dispatch/releases/latest"
API_HOST = "api.github.com"
ASSET_NAME = "wake-dispatch.zip"
DOWNLOAD_URL_FMT = (
    "https://github.com/jedwards1230/decky-wake-dispatch/releases/download/"
    "v{version}/wake-dispatch.zip"
)
MANUAL_URL = (
    "https://github.com/jedwards1230/decky-wake-dispatch/releases/latest/download/wake-dispatch.zip"
)
CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem")

TIMEOUT = 5.0  # urllib socket timeout
OVERALL_TIMEOUT_EXTRA = 2.0  # the asyncio wait is TIMEOUT plus this
MAX_BODY = 512 * 1024
MAX_ASSET_SIZE = 5 * 1024 * 1024
READ_CHUNK = 16 * 1024

CHECK_INTERVAL = 24 * 3600
MANUAL_MIN_INTERVAL = 60
BACKOFF_BASE = 3600
BACKOFF_MAX = 24 * 3600
FUTURE_SKEW = 300  # a cached timestamp further ahead than this discards the cache

OPTIONS_FILE = "options.json"
CACHE_FILE = "update.json"
OPTIONS_VERSION = 1
CACHE_VERSION = 1

ERR_UNREACHABLE = "Couldn't reach GitHub"
ERR_CERT = "Couldn't verify GitHub's certificate"
ERR_ANSWER = "GitHub returned an unexpected answer"
ERR_INSTALLED = "Couldn't read the installed version"
ERR_NO_TLS = "Update check unavailable: no trusted certificates on this device"
ERR_SETTING = "Choose on or off."
ERR_SAVE = "Couldn't save the setting"

_TAG_RE = re.compile(r"^v(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$", re.ASCII)
_VERSION_RE = re.compile(r"^(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$", re.ASCII)
_INSTALLED_RE = re.compile(r"^\d+\.\d+\.\d+$", re.ASCII)
_DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)

Fetch = Callable[[str, dict[str, str], float, int, ssl.SSLContext], tuple[int, bytes]]


class CheckError(Exception):
    """A failed check: ``message`` is shown to the user, ``reason`` goes to the log."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(reason)
        self.message = message
        self.reason = reason


class RedirectRefused(urllib.error.URLError):
    """A redirect pointed somewhere other than ``https://api.github.com/``."""


# --- TLS and HTTP -----------------------------------------------------------------


def _certifi_where() -> str | None:
    try:
        import certifi
    except ImportError:
        return None
    try:
        return certifi.where()
    except Exception:  # a broken certifi install must not escape
        return None


def make_ssl_context(ca_files: tuple[str, ...] | None = None) -> ssl.SSLContext:
    """A verifying TLS 1.2+ client context from the system CA bundle, else certifi.

    Raises ``CheckError`` when no CA bundle can be loaded; never falls back to an
    unverified context.
    """
    cafile = next(
        (p for p in (CA_FILES if ca_files is None else ca_files) if os.path.isfile(p)), None
    )
    if cafile is None:
        cafile = _certifi_where()
    if cafile is None:
        raise CheckError(ERR_NO_TLS, "no CA bundle found (system files or certifi)")
    try:
        context = ssl.create_default_context(cafile=cafile)
    except (OSError, ssl.SSLError) as exc:
        raise CheckError(ERR_NO_TLS, f"could not load CA bundle {cafile}: {exc}") from exc
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def is_api_url(url: str) -> bool:
    """True only for ``https://api.github.com/...`` (default port, no credentials)."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname == API_HOST
        and port is None
        and parts.username is None
        and parts.password is None
        and parts.netloc == API_HOST
        and parts.path.startswith("/")
    )


class ApiOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only when it stays on ``https://api.github.com/``."""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_api_url(newurl):
            raise RedirectRefused(f"redirect to {newurl!r} refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(context: ssl.SSLContext) -> urllib.request.OpenerDirector:
    """An opener that speaks HTTPS only: no http, ftp, file or data handlers."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.UnknownHandler(),
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPDefaultErrorHandler(),
        ApiOnlyRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def https_fetch(
    url: str,
    headers: dict[str, str],
    timeout: float,
    limit: int,
    context: ssl.SSLContext,
    *,
    opener_factory: Callable[[ssl.SSLContext], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, bytes]:
    """Blocking GET; returns ``(status, up to limit + 1 bytes of body)``. Runs on a thread.

    urllib's ``timeout`` applies to each socket operation, so the body is read in
    chunks against an overall ``timeout`` deadline: a server dripping bytes can't
    keep this thread reading. Past the deadline the response is closed and
    ``TimeoutError`` raised.
    """
    if not is_api_url(url):
        raise ValueError(f"refusing to fetch {url!r}")
    deadline = clock() + timeout
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        response = (opener_factory or build_opener)(context).open(request, timeout=timeout)
    except RedirectRefused:
        raise
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, b""
    with contextlib.closing(response):
        # read1 returns after at most one underlying read, so the deadline is checked often.
        read = getattr(response, "read1", None) or response.read
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            if clock() > deadline:
                raise TimeoutError(f"response not finished within {timeout} s")
            chunk = read(min(READ_CHUNK, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return response.status, b"".join(chunks)


async def run_in_thread(func: Callable[..., Any], *args: Any, timeout: float) -> Any:
    """Run blocking ``func(*args)`` on a daemon thread and await its result.

    A daemon thread (not an executor) so a hung request can never keep the
    process alive at exit. The result comes back through
    ``loop.call_soon_threadsafe``; it is dropped if the caller already gave up
    or the loop has closed.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def deliver(ok: bool, value: Any) -> None:
        if future.done():
            return
        if ok:
            future.set_result(value)
        else:
            future.set_exception(value)

    def worker() -> None:
        try:
            outcome: tuple[bool, Any] = (True, func(*args))
        except Exception as exc:
            outcome = (False, exc)
        if loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # the loop closed after the check above
            loop.call_soon_threadsafe(deliver, *outcome)

    threading.Thread(target=worker, name="wake-dispatch-update", daemon=True).start()
    return await asyncio.wait_for(future, timeout)


def classify(exc: BaseException) -> CheckError:
    """Map a fetch failure to a plain-language CheckError."""
    if isinstance(exc, CheckError):
        return exc
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(exc, RedirectRefused):
        return CheckError(ERR_ANSWER, str(exc.reason))
    if isinstance(reason, ssl.SSLCertVerificationError):
        return CheckError(ERR_CERT, f"certificate verification failed: {reason}")
    if isinstance(exc, ValueError):
        return CheckError(ERR_ANSWER, f"bad request: {exc}")
    return CheckError(ERR_UNREACHABLE, f"{type(exc).__name__}: {exc}")


# --- Parsing ------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_time(value: Any) -> bool:
    return (_is_int(value) or isinstance(value, float)) and math.isfinite(value) and value >= 0


def version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def parse_release(body: bytes) -> dict[str, Any]:
    """Validate GitHub's ``releases/latest`` JSON; return ``{version, url, sha256, size}``.

    Raises ``CheckError`` (with the reason for the log) on anything unexpected.
    """

    def bad(reason: str) -> CheckError:
        return CheckError(ERR_ANSWER, reason)

    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise bad(f"invalid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise bad("top level is not an object")
    if doc.get("draft") is not False or doc.get("prerelease") is not False:
        raise bad("release is a draft or prerelease, or the flags are missing")
    tag = doc.get("tag_name")
    if not isinstance(tag, str) or not _TAG_RE.fullmatch(tag):
        raise bad(f"unexpected tag {tag!r}")
    version = tag[1:]
    assets = doc.get("assets")
    if not isinstance(assets, list):
        raise bad("assets is not a list")
    matches = [a for a in assets if isinstance(a, dict) and a.get("name") == ASSET_NAME]
    if len(matches) != 1:
        raise bad(f"expected exactly one {ASSET_NAME} asset, found {len(matches)}")
    asset = matches[0]
    if "state" in asset and asset["state"] != "uploaded":
        raise bad(f"asset state is {asset['state']!r}")
    size = asset.get("size")
    if not _is_int(size) or not 0 < size < MAX_ASSET_SIZE:
        raise bad(f"unexpected asset size {size!r}")
    url = asset.get("browser_download_url")
    if url != DOWNLOAD_URL_FMT.format(version=version):
        raise bad(f"unexpected download URL {url!r}")
    digest = asset.get("digest")
    match = _DIGEST_RE.fullmatch(digest) if isinstance(digest, str) else None
    if match is None:
        raise bad(f"unexpected digest {digest!r}")
    return {"version": version, "url": url, "sha256": match.group(1), "size": size}


def read_installed_version(plugin_dir: str) -> str | None:
    """The ``version`` from the packaged ``package.json``, or ``None`` if unreadable."""
    path = os.path.join(plugin_dir, "package.json")
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        get_logger().warning("Update check: could not read %s: %s", path, exc)
        return None
    version = doc.get("version") if isinstance(doc, dict) else None
    if not isinstance(version, str) or not _INSTALLED_RE.fullmatch(version):
        get_logger().warning("Update check: unexpected installed version %r", version)
        return None
    try:
        version_tuple(version)
    except ValueError:
        return None
    return version


# --- Options and cache files ----------------------------------------------------------


def options_path(settings_dir: str) -> str:
    return os.path.join(settings_dir, OPTIONS_FILE)


def cache_path(runtime_dir: str) -> str:
    return os.path.join(runtime_dir, CACHE_FILE)


def load_update_check(settings_dir: str) -> bool:
    """The update-check setting; on by default, and when the stored value isn't a bool."""
    raw = storage.read_json(options_path(settings_dir))
    value = raw.get("update_check") if isinstance(raw, dict) else None
    return value if isinstance(value, bool) else True


def save_update_check(settings_dir: str, enabled: bool) -> None:
    """Write the setting atomically, keeping any other keys already in options.json."""
    path = options_path(settings_dir)
    raw = storage.read_json(path)
    doc = dict(raw) if isinstance(raw, dict) else {}
    version = doc.get("version")
    if not _is_int(version) or version < OPTIONS_VERSION:
        doc["version"] = OPTIONS_VERSION
    doc["update_check"] = enabled
    storage.atomic_write_json(path, doc)


def _valid_release(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"version", "url", "sha256", "size"}:
        return False
    version = value["version"]
    return (
        isinstance(version, str)
        and _VERSION_RE.fullmatch(version) is not None
        and value["url"] == DOWNLOAD_URL_FMT.format(version=version)
        and isinstance(value["sha256"], str)
        and _SHA256_RE.fullmatch(value["sha256"]) is not None
        and _is_int(value["size"])
        and 0 < value["size"] < MAX_ASSET_SIZE
    )


def validate_cache(raw: Any, now: float) -> dict[str, Any] | None:
    """Return the cache if every field is valid and consistent, else ``None``."""
    if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
        return None
    attempt_at = raw.get("attempt_at")
    success_at = raw.get("success_at")
    failures = raw.get("failures")
    latest = raw.get("latest")
    error = raw.get("error")
    limit = now + FUTURE_SKEW
    if not _is_time(attempt_at) or attempt_at > limit:
        return None
    if success_at is not None and (
        not _is_time(success_at) or success_at > limit or success_at > attempt_at
    ):
        return None
    if not _is_int(failures) or failures < 0:
        return None
    if latest is not None and not _valid_release(latest):
        return None
    if (success_at is None) != (latest is None):
        return None
    if error is not None and not (isinstance(error, str) and 0 < len(error) <= 200):
        return None
    if (failures == 0) != (error is None) or (failures == 0 and success_at != attempt_at):
        return None
    return {
        "version": CACHE_VERSION,
        "attempt_at": float(attempt_at),
        "success_at": None if success_at is None else float(success_at),
        "failures": failures,
        "latest": None if latest is None else dict(latest),
        "error": error,
    }


def backoff(failures: int) -> float:
    """Seconds to wait after ``failures`` consecutive failed checks: 1 h doubling, max 24 h."""
    return min(BACKOFF_BASE * 2 ** (min(max(failures, 1), 16) - 1), BACKOFF_MAX)


# --- The checker ----------------------------------------------------------------------


class Updater:
    """Owns the in-flight lock and the cadence; see docs/CONTRACT.md §4."""

    def __init__(
        self,
        *,
        settings_dir: Callable[[], str],
        runtime_dir: Callable[[], str],
        plugin_dir: Callable[[], str],
        fetch: Fetch | None = None,
        make_context: Callable[[], ssl.SSLContext] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings_dir = settings_dir
        self._runtime_dir = runtime_dir
        self._plugin_dir = plugin_dir
        self._fetch = fetch
        self._make_context = make_context
        self._clock = clock
        self._lock = asyncio.Lock()
        self._memory: dict[str, Any] | None = None  # used when update.json can't be written

    def _load_cache(self, now: float) -> dict[str, Any] | None:
        """The newer of update.json and this process's last result (kept when writes fail)."""
        disk = validate_cache(storage.read_json(cache_path(self._runtime_dir())), now)
        memory = validate_cache(self._memory, now) if self._memory is not None else None
        if memory is not None and (disk is None or memory["attempt_at"] > disk["attempt_at"]):
            return memory
        return disk

    def _store_cache(self, cache: dict[str, Any]) -> None:
        self._memory = cache
        try:
            storage.atomic_write_json(cache_path(self._runtime_dir()), cache)
        except OSError as exc:
            get_logger().error("Could not save the update check result: %s", exc)

    async def info(self, force: bool = False) -> dict[str, Any]:
        started = self._clock()
        async with self._lock:
            enabled = load_update_check(self._settings_dir())
            installed = read_installed_version(self._plugin_dir())
            now = self._clock()
            cache = self._load_cache(now)
            throttled = False
            checked = False
            if installed is not None and (force or enabled):
                if force:
                    recent = cache is not None and now - cache["attempt_at"] < MANUAL_MIN_INTERVAL
                    # A check that finished while this call waited for the lock counts.
                    throttled = recent and cache is not None and cache["attempt_at"] < started
                    due = not recent
                else:
                    due = self._due(cache, now)
                if due:
                    cache = await self._check(cache, installed, now)
                    checked = True
            return self._result(
                enabled,
                installed,
                cache,
                self._clock(),
                shown=force or enabled or checked,
                throttled=throttled,
            )

    @staticmethod
    def _due(cache: dict[str, Any] | None, now: float) -> bool:
        if cache is None:
            return True
        if cache["failures"] > 0:
            return now - cache["attempt_at"] >= backoff(cache["failures"])
        return now - cache["attempt_at"] >= CHECK_INTERVAL

    async def _check(
        self, previous: dict[str, Any] | None, installed: str, now: float
    ) -> dict[str, Any]:
        headers = {
            "User-Agent": f"wake-dispatch/{installed}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        fetch = self._fetch or https_fetch
        try:
            context = (self._make_context or make_ssl_context)()
            try:
                status, body = await run_in_thread(
                    fetch,
                    API_URL,
                    headers,
                    TIMEOUT,
                    MAX_BODY,
                    context,
                    timeout=TIMEOUT + OVERALL_TIMEOUT_EXTRA,
                )
            except Exception as exc:
                raise classify(exc) from exc
            if status != 200:
                raise CheckError(ERR_ANSWER, f"HTTP status {status}")
            if len(body) > MAX_BODY:
                raise CheckError(ERR_ANSWER, f"response larger than {MAX_BODY} bytes")
            try:
                release = parse_release(body)
            except CheckError:
                raise
            except Exception as exc:  # backstop: a parser bug must not reach the panel
                raise CheckError(ERR_ANSWER, f"could not parse the release: {exc!r}") from exc
        except CheckError as exc:
            get_logger().warning("Update check failed: %s", exc.reason)
            cache = {
                "version": CACHE_VERSION,
                "attempt_at": now,
                "success_at": previous["success_at"] if previous else None,
                "failures": (previous["failures"] if previous else 0) + 1,
                "latest": previous["latest"] if previous else None,
                "error": exc.message,
            }
        else:
            get_logger().info("Update check: latest release is v%s", release["version"])
            cache = {
                "version": CACHE_VERSION,
                "attempt_at": now,
                "success_at": now,
                "failures": 0,
                "latest": release,
                "error": None,
            }
        self._store_cache(cache)
        return cache

    @staticmethod
    def _result(
        enabled: bool,
        installed: str | None,
        cache: dict[str, Any] | None,
        now: float,
        *,
        shown: bool,
        throttled: bool,
    ) -> dict[str, Any]:
        latest = cache["latest"] if cache else None
        info: dict[str, Any] = {
            "enabled": enabled,
            "installed": installed,
            "status": "unchecked",
            "latest": latest["version"] if latest else None,
            "release": None,
            "checked_at": cache["success_at"] if cache else None,
            "error": None,
            "throttled": throttled,
            "manual_url": MANUAL_URL,
        }
        if not shown:
            info["status"] = "disabled"
            return info
        if installed is None:
            info.update(status="unavailable", error=ERR_INSTALLED)
            return info
        if cache is None:
            return info
        fresh = cache["success_at"] is not None and now - cache["success_at"] < 2 * CHECK_INTERVAL
        if cache["failures"] > 0 and not fresh:
            info.update(status="unavailable", error=cache["error"])
            return info
        if latest is None:  # unreachable: a success always records a release
            return info
        if version_tuple(latest["version"]) > version_tuple(installed):
            info.update(status="available", release=dict(latest))
        else:
            info["status"] = "current"
        return info


def set_update_check(settings_dir: str, enabled: Any) -> dict[str, Any]:
    """Validate and persist the setting; errors come back as ``ok: false``."""
    if not isinstance(enabled, bool):
        return {"ok": False, "error": ERR_SETTING}
    try:
        save_update_check(settings_dir, enabled)
    except OSError as exc:
        get_logger().error("Could not save the update check setting: %s", exc)
        return {"ok": False, "error": f"{ERR_SAVE}: {exc.strerror or exc}"}
    return {"ok": True, "enabled": enabled}
