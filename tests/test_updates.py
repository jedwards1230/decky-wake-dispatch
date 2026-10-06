"""The update check: strict release parsing, TLS/HTTP guards, cadence and the setting.

Every fetch is injected and the clock is fake; nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import copy
import json
import ssl
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import main
from wake_dispatch import updates

DIGEST = "0123456789abcdef" * 4
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REAL_HTTPS_FETCH = updates.https_fetch  # conftest replaces it with a guard per test


def release(version: str = "0.2.0", **overrides: Any) -> dict[str, Any]:
    asset = {
        "name": "wake-dispatch.zip",
        "state": "uploaded",
        "size": 46000,
        "browser_download_url": updates.DOWNLOAD_URL_FMT.format(version=version),
        "digest": f"sha256:{DIGEST}",
    }
    asset.update(overrides.pop("asset", {}))
    doc = {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "assets": [{"name": "wake-dispatch.zip.sig", "size": 10}, asset],
    }
    doc.update(overrides)
    return doc


def body(doc: Any) -> bytes:
    return json.dumps(doc).encode()


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeFetch:
    """Records calls and returns (or raises) the queued responses in order."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], float, int]] = []

    def __call__(
        self, url: str, headers: dict[str, str], timeout: float, limit: int, context: Any
    ) -> tuple[int, bytes]:
        self.calls.append((url, headers, timeout, limit))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture
def dirs(tmp_path: Path) -> dict[str, Path]:
    out = {name: tmp_path / name for name in ("u-settings", "u-runtime", "u-plugin")}
    for path in out.values():
        path.mkdir()
    (out["u-plugin"] / "package.json").write_text(json.dumps({"version": "0.1.0"}))
    return out


def make(dirs: dict[str, Path], fetch: Any, clock: Clock | None = None, **kw: Any):
    return updates.Updater(
        settings_dir=lambda: str(dirs["u-settings"]),
        runtime_dir=lambda: str(dirs["u-runtime"]),
        plugin_dir=lambda: str(dirs["u-plugin"]),
        fetch=fetch,
        make_context=kw.pop("make_context", lambda: object()),
        clock=clock or Clock(),
        **kw,
    )


KEYS = {
    "enabled",
    "installed",
    "status",
    "latest",
    "release",
    "checked_at",
    "error",
    "throttled",
    "manual_url",
}


# --- strict parse ---------------------------------------------------------------------


async def test_newer_release_is_available(dirs) -> None:
    fetch = FakeFetch((200, body(release("0.2.0"))))
    clock = Clock()
    info = await make(dirs, fetch, clock).info()
    assert set(info) == KEYS
    assert info == {
        "enabled": True,
        "installed": "0.1.0",
        "status": "available",
        "latest": "0.2.0",
        "release": {
            "version": "0.2.0",
            "url": "https://github.com/jedwards1230/decky-wake-dispatch/releases/download/v0.2.0/wake-dispatch.zip",
            "sha256": DIGEST,
            "size": 46000,
        },
        "checked_at": clock.now,
        "error": None,
        "throttled": False,
        "manual_url": updates.MANUAL_URL,
    }
    [(url, headers, timeout, limit)] = fetch.calls
    assert url == updates.API_URL
    assert headers == {
        "User-Agent": "wake-dispatch/0.1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    assert (timeout, limit) == (updates.TIMEOUT, updates.MAX_BODY)


@pytest.mark.parametrize("version", ["0.1.0", "0.0.9"])
async def test_equal_or_older_is_current(dirs, version) -> None:
    info = await make(dirs, FakeFetch((200, body(release(version))))).info()
    assert (info["status"], info["latest"], info["release"]) == ("current", version, None)


def test_real_shape_parses() -> None:
    parsed = updates.parse_release(body(release("0.1.0", asset={"size": 46771})))
    assert parsed["size"] == 46771 and parsed["sha256"] == DIGEST


BAD_DOCS = {
    "leading zero": release(tag_name="v0.01.0"),
    "five digits": release(tag_name="v10000.0.0"),
    "prerelease suffix": release(tag_name="v0.2.0-rc1"),
    "missing v": release(tag_name="0.2.0"),
    "trailing newline": release(tag_name="v0.2.0\n"),
    "unicode digit": release(tag_name="v0.٢.0"),
    "tag not str": release(tag_name=2),
    "prerelease true": release(prerelease=True),
    "draft true": release(draft=True),
    "draft missing": {k: v for k, v in release().items() if k != "draft"},
    "draft truthy int": release(draft=0),
    "asset missing": release(assets=[{"name": "other.zip"}]),
    "assets not list": release(assets={}),
    "asset duplicated": release(
        assets=[release()["assets"][1], release()["assets"][1]],
    ),
    "asset wrong name": release(asset={"name": "Wake-Dispatch.zip"}),
    "asset not uploaded": release(asset={"state": "new"}),
    "url other host": release(
        asset={
            "browser_download_url": "https://example.com/jedwards1230/decky-wake-dispatch/"
            "releases/download/v0.2.0/wake-dispatch.zip"
        }
    ),
    "url other tag": release(
        asset={"browser_download_url": updates.DOWNLOAD_URL_FMT.format(version="0.1.9")}
    ),
    "url http": release(
        asset={
            "browser_download_url": updates.DOWNLOAD_URL_FMT.format(version="0.2.0").replace(
                "https:", "http:"
            )
        }
    ),
    "digest uppercase": release(asset={"digest": "sha256:" + DIGEST.upper()}),
    "digest md5": release(asset={"digest": "md5:" + DIGEST[:32]}),
    "digest short": release(asset={"digest": "sha256:" + DIGEST[:63]}),
    "digest missing": release(asset={"digest": None}),
    "size zero": release(asset={"size": 0}),
    "size 5 MB": release(asset={"size": 5 * 1024 * 1024}),
    "size float": release(asset={"size": 46000.0}),
    "size bool": release(asset={"size": True}),
    "size str": release(asset={"size": "46000"}),
    "not a dict": [release()],
}


@pytest.mark.parametrize("doc", BAD_DOCS.values(), ids=BAD_DOCS.keys())
async def test_bad_release_is_unavailable(dirs, doc, caplog) -> None:
    with caplog.at_level("WARNING"):
        info = await make(dirs, FakeFetch((200, body(doc)))).info()
    assert info["status"] == "unavailable"
    assert info["error"] == updates.ERR_ANSWER
    assert info["release"] is None and info["latest"] is None
    assert any("Update check failed" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("raw", [b"{", b"\xff\xfe", b""])
async def test_invalid_json_is_unavailable(dirs, raw) -> None:
    info = await make(dirs, FakeFetch((200, raw))).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_ANSWER)


async def test_oversize_body_is_unavailable(dirs) -> None:
    raw = body(release()) + b" " * (updates.MAX_BODY + 1)
    info = await make(dirs, FakeFetch((200, raw))).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_ANSWER)


@pytest.mark.parametrize("status", [404, 403, 500, 304])
async def test_non_200_is_unavailable(dirs, status) -> None:
    info = await make(dirs, FakeFetch((status, body(release())))).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_ANSWER)


# --- TLS and HTTP guards ---------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        ssl.SSLCertVerificationError(1, "certificate verify failed"),
        urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")),
    ],
)
async def test_certificate_failure(dirs, exc) -> None:
    info = await make(dirs, FakeFetch(exc)).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_CERT)


@pytest.mark.parametrize(
    "exc", [urllib.error.URLError("Name or service not known"), TimeoutError(), OSError(101)]
)
async def test_network_failure(dirs, exc) -> None:
    info = await make(dirs, FakeFetch(exc)).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_UNREACHABLE)


async def test_redirect_refusal_maps_to_unexpected_answer(dirs) -> None:
    info = await make(dirs, FakeFetch(updates.RedirectRefused("nope"))).info()
    assert info["error"] == updates.ERR_ANSWER


async def test_overall_timeout(dirs, monkeypatch) -> None:
    release_thread = threading.Event()
    monkeypatch.setattr(updates, "TIMEOUT", 0.01)
    monkeypatch.setattr(updates, "OVERALL_TIMEOUT_EXTRA", 0.05)

    def hang(*_args: Any) -> tuple[int, bytes]:
        release_thread.wait(5)
        return 200, b""

    try:
        info = await make(dirs, hang).info()
    finally:
        release_thread.set()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_UNREACHABLE)


async def test_no_ca_bundle_fails_closed(dirs, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(updates, "CA_FILES", (str(tmp_path / "missing.pem"),))
    monkeypatch.setitem(sys.modules, "certifi", None)  # import certifi -> ImportError
    with pytest.raises(updates.CheckError) as excinfo:
        updates.make_ssl_context()
    assert excinfo.value.message == updates.ERR_NO_TLS
    fetch = FakeFetch((200, body(release())))
    updater = updates.Updater(
        settings_dir=lambda: str(dirs["u-settings"]),
        runtime_dir=lambda: str(dirs["u-runtime"]),
        plugin_dir=lambda: str(dirs["u-plugin"]),
        fetch=fetch,
        clock=Clock(),
    )
    info = await updater.info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_NO_TLS)
    assert fetch.calls == []


def _a_ca_file() -> str:
    paths = ssl.get_default_verify_paths()
    for candidate in (*updates.CA_FILES, paths.cafile or "", paths.openssl_cafile or ""):
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("no CA bundle on this machine")


def test_ssl_context_verifies() -> None:
    context = updates.make_ssl_context((_a_ca_file(),))
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_ssl_context_falls_back_to_certifi(tmp_path, monkeypatch) -> None:
    import types

    fake = types.ModuleType("certifi")
    fake.where = _a_ca_file  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "certifi", fake)
    context = updates.make_ssl_context((str(tmp_path / "missing.pem"),))
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_unreadable_ca_file_fails_closed(tmp_path) -> None:
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate")
    with pytest.raises(updates.CheckError):
        updates.make_ssl_context((str(bad),))


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://api.github.com/repositories/1/releases/latest", True),
        ("http://api.github.com/repos/x", False),
        ("https://api.github.com:8443/repos/x", False),
        ("https://user@api.github.com/repos/x", False),
        ("https://api.github.com.example.com/repos/x", False),
        ("https://objects.githubusercontent.com/x", False),
        ("https://github.com/x", False),
        ("ftp://api.github.com/x", False),
        ("https://api.github.com:bad/x", False),
    ],
)
def test_is_api_url(url, ok) -> None:
    assert updates.is_api_url(url) is ok


def _redirect(newurl: str) -> Any:
    handler = updates.ApiOnlyRedirectHandler()
    request = urllib.request.Request(updates.API_URL)
    return handler.redirect_request(request, None, 302, "Found", {}, newurl)


def test_redirect_off_api_host_is_refused() -> None:
    for target in (
        "https://example.com/latest",
        "http://api.github.com/repos/x",
        "https://api.github.com.example.com/x",
    ):
        with pytest.raises(updates.RedirectRefused):
            _redirect(target)


def test_redirect_on_api_host_is_followed() -> None:
    new = _redirect("https://api.github.com/repositories/123/releases/latest")
    assert new.full_url == "https://api.github.com/repositories/123/releases/latest"


def test_opener_is_https_only() -> None:
    context = ssl.create_default_context()
    opener = updates.build_opener(context)
    kinds = {type(h) for h in opener.handlers}
    assert urllib.request.HTTPHandler not in kinds
    assert urllib.request.FTPHandler not in kinds
    assert urllib.request.FileHandler not in kinds
    assert urllib.request.DataHandler not in kinds
    with pytest.raises(urllib.error.URLError):
        opener.open("http://api.github.com/repos/x", timeout=0.1)
    with pytest.raises(urllib.error.URLError):
        opener.open("file:///etc/hostname", timeout=0.1)


def test_https_fetch_refuses_other_urls() -> None:
    with pytest.raises(ValueError):
        REAL_HTTPS_FETCH("https://example.com/", {}, 0.1, 10, ssl.create_default_context())


# --- thread helper -------------------------------------------------------------------


async def test_run_in_thread_delivers_result_and_error() -> None:
    caller = threading.get_ident()
    seen: list[int] = []

    def work(x: int) -> int:
        seen.append(threading.get_ident())
        return x * 2

    assert await updates.run_in_thread(work, 21, timeout=2) == 42
    assert seen and seen[0] != caller

    def fail() -> None:
        raise OSError("boom")

    with pytest.raises(OSError, match="boom"):
        await updates.run_in_thread(fail, timeout=2)


def test_run_in_thread_tolerates_closed_loop() -> None:
    errors: list[Any] = []
    original_hook = threading.excepthook
    threading.excepthook = errors.append
    gate = threading.Event()

    def slow() -> str:
        gate.wait(5)
        return "late"

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(TimeoutError):
            loop.run_until_complete(updates.run_in_thread(slow, timeout=0.01))
    finally:
        loop.close()
        gate.set()
    try:
        for thread in threading.enumerate():
            if thread.name == "wake-dispatch-update":
                assert thread.daemon
                thread.join(5)
    finally:
        threading.excepthook = original_hook
    assert errors == []


# --- cadence -------------------------------------------------------------------------


async def test_daily_cache(dirs) -> None:
    fetch = FakeFetch((200, body(release())))
    clock = Clock()
    updater = make(dirs, fetch, clock)
    await updater.info()
    clock.now += updates.CHECK_INTERVAL - 1
    info = await updater.info()
    assert len(fetch.calls) == 1 and info["status"] == "available"
    clock.now += 1
    await updater.info()
    assert len(fetch.calls) == 2


async def test_cache_survives_a_new_updater(dirs) -> None:
    fetch = FakeFetch((200, body(release())))
    clock = Clock()
    await make(dirs, fetch, clock).info()
    info = await make(dirs, fetch, clock).info()
    assert len(fetch.calls) == 1 and info["status"] == "available"
    on_disk = json.loads((dirs["u-runtime"] / "update.json").read_text())
    assert on_disk == {
        "version": 1,
        "attempt_at": clock.now,
        "success_at": clock.now,
        "failures": 0,
        "latest": info["release"],
        "error": None,
    }


async def test_backoff_after_failures(dirs) -> None:
    fetch = FakeFetch(OSError("down"))
    clock = Clock()
    updater = make(dirs, fetch, clock)
    await updater.info()  # failure 1 -> wait 1 h
    clock.now += 3599
    await updater.info()
    assert len(fetch.calls) == 1
    clock.now += 1
    await updater.info()  # failure 2 -> wait 2 h
    assert len(fetch.calls) == 2
    clock.now += 2 * 3600 - 1
    await updater.info()
    assert len(fetch.calls) == 2
    clock.now += 1
    await updater.info()
    assert len(fetch.calls) == 3
    assert updates.backoff(1) == 3600 and updates.backoff(3) == 4 * 3600
    assert updates.backoff(6) == updates.BACKOFF_MAX == updates.backoff(10_000)


async def test_failure_after_success_reports_success_until_stale(dirs) -> None:
    fetch = FakeFetch((200, body(release())), OSError("down"))
    clock = Clock()
    updater = make(dirs, fetch, clock)
    first = await updater.info()
    clock.now += updates.CHECK_INTERVAL
    info = await updater.info()  # fails, but the success is < 48 h old
    assert len(fetch.calls) == 2
    assert (info["status"], info["error"]) == ("available", None)
    assert info["checked_at"] == first["checked_at"]
    clock.now += updates.CHECK_INTERVAL  # 48 h since the success: the retry fails too
    info = await updater.info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_UNREACHABLE)
    assert info["latest"] == "0.2.0" and info["release"] is None


async def test_force_throttle(dirs) -> None:
    fetch = FakeFetch((200, body(release())))
    clock = Clock()
    updater = make(dirs, fetch, clock)
    await updater.info()
    clock.now += updates.MANUAL_MIN_INTERVAL - 1
    info = await updater.info(force=True)
    assert len(fetch.calls) == 1 and info["throttled"] is True
    assert info["status"] == "available"
    clock.now += 1
    info = await updater.info(force=True)
    assert len(fetch.calls) == 2 and info["throttled"] is False


async def test_force_ignores_backoff(dirs) -> None:
    fetch = FakeFetch(OSError("down"), (200, body(release())))
    clock = Clock()
    updater = make(dirs, fetch, clock)
    await updater.info()
    clock.now += updates.MANUAL_MIN_INTERVAL
    info = await updater.info(force=True)
    assert len(fetch.calls) == 2 and info["status"] == "available"


async def test_future_timestamp_discards_cache(dirs) -> None:
    clock = Clock()
    cache = {
        "version": 1,
        "attempt_at": clock.now + updates.FUTURE_SKEW + 1,
        "success_at": clock.now + updates.FUTURE_SKEW + 1,
        "failures": 0,
        "latest": updates.parse_release(body(release())),
        "error": None,
    }
    (dirs["u-runtime"] / "update.json").write_text(json.dumps(cache))
    fetch = FakeFetch((200, body(release("0.1.0"))))
    info = await make(dirs, fetch, clock).info()
    assert len(fetch.calls) == 1 and info["status"] == "current"


GOOD_CACHE = {
    "version": 1,
    "attempt_at": 999_000.0,
    "success_at": 999_000.0,
    "failures": 0,
    "latest": {
        "version": "0.2.0",
        "url": updates.DOWNLOAD_URL_FMT.format(version="0.2.0"),
        "sha256": DIGEST,
        "size": 46000,
    },
    "error": None,
}


def _broken(**changes: Any) -> dict[str, Any]:
    doc = copy.deepcopy(GOOD_CACHE)
    for key, value in changes.items():
        if key.startswith("latest_"):
            doc["latest"][key[7:]] = value
        else:
            doc[key] = value
    return doc


BAD_CACHES = {
    "not json": "{",
    "list": [],
    "version 2": _broken(version=2),
    "attempt str": _broken(attempt_at="999000"),
    "attempt bool": _broken(attempt_at=True),
    "attempt negative": _broken(attempt_at=-1),
    "success after attempt": _broken(success_at=999_001.0),
    "failures negative": _broken(failures=-1),
    "failures float": _broken(failures=1.0),
    "failures without error": _broken(failures=1),
    "error without failures": _broken(error="x"),
    "latest without success": _broken(success_at=None),
    "latest bad url": _broken(latest_url="https://example.com/x.zip"),
    "latest bad sha": _broken(latest_sha256="A" * 64),
    "latest bad size": _broken(latest_size=0),
    "latest bad version": _broken(latest_version="0.02.0"),
    "latest extra key": _broken(latest_extra=1),
}


@pytest.mark.parametrize("cache", BAD_CACHES.values(), ids=BAD_CACHES.keys())
async def test_invalid_cache_is_ignored(dirs, cache) -> None:
    path = dirs["u-runtime"] / "update.json"
    path.write_text(cache if isinstance(cache, str) else json.dumps(cache))
    fetch = FakeFetch((200, body(release("0.1.0"))))
    info = await make(dirs, fetch).info()
    assert len(fetch.calls) == 1 and info["status"] == "current"


async def test_valid_cache_is_used(dirs) -> None:
    (dirs["u-runtime"] / "update.json").write_text(json.dumps(GOOD_CACHE))
    fetch = FakeFetch((200, body(release("0.1.0"))))
    info = await make(dirs, fetch).info()
    assert fetch.calls == [] and info["status"] == "available"
    assert info["checked_at"] == GOOD_CACHE["success_at"]


async def test_cached_release_rechecked_against_installed(dirs) -> None:
    (dirs["u-runtime"] / "update.json").write_text(json.dumps(GOOD_CACHE))
    (dirs["u-plugin"] / "package.json").write_text(json.dumps({"version": "0.2.0"}))
    info = await make(dirs, FakeFetch((200, b""))).info()
    assert (info["status"], info["installed"], info["release"]) == ("current", "0.2.0", None)


async def test_cache_write_failure_keeps_result_in_memory(dirs, monkeypatch) -> None:
    def boom(*_a: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(updates.storage, "atomic_write_json", boom)
    fetch = FakeFetch((200, body(release())))
    updater = make(dirs, fetch)
    await updater.info()
    info = await updater.info()
    assert len(fetch.calls) == 1 and info["status"] == "available"


async def test_concurrent_calls_share_one_fetch(dirs) -> None:
    gate = threading.Event()
    fetch = FakeFetch((200, body(release())))

    def slow(*args: Any) -> tuple[int, bytes]:
        gate.wait(5)
        return fetch(*args)

    updater = make(dirs, slow)
    tasks = [asyncio.ensure_future(updater.info(force=i % 2 == 0)) for i in range(4)]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert len(fetch.calls) == 1
    assert all(r["status"] == "available" and r["throttled"] is False for r in results)


# --- the setting ---------------------------------------------------------------------


async def test_disabled_never_fetches(dirs) -> None:
    assert updates.set_update_check(str(dirs["u-settings"]), False) == {
        "ok": True,
        "enabled": False,
    }
    fetch = FakeFetch((200, body(release())))
    info = await make(dirs, fetch).info()
    assert fetch.calls == []
    assert (info["enabled"], info["status"], info["error"]) == (False, "disabled", None)


async def test_force_while_disabled_fetches(dirs) -> None:
    updates.set_update_check(str(dirs["u-settings"]), False)
    fetch = FakeFetch((200, body(release())))
    updater = make(dirs, fetch)
    info = await updater.info(force=True)
    assert len(fetch.calls) == 1
    assert (info["enabled"], info["status"]) == (False, "available")
    assert (await updater.info())["status"] == "disabled"


def test_setting_default_and_persistence(dirs) -> None:
    settings = str(dirs["u-settings"])
    assert updates.load_update_check(settings) is True
    assert updates.set_update_check(settings, False) == {"ok": True, "enabled": False}
    assert updates.load_update_check(settings) is False
    on_disk = json.loads((dirs["u-settings"] / "options.json").read_text())
    assert on_disk == {"version": 1, "update_check": False}


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_setting_rejects_non_bool(dirs, value) -> None:
    result = updates.set_update_check(str(dirs["u-settings"]), value)
    assert result == {"ok": False, "error": updates.ERR_SETTING}
    assert not (dirs["u-settings"] / "options.json").exists()


@pytest.mark.parametrize("stored", ["yes", 0, None])
def test_non_bool_stored_value_is_default(dirs, stored) -> None:
    (dirs["u-settings"] / "options.json").write_text(json.dumps({"update_check": stored}))
    assert updates.load_update_check(str(dirs["u-settings"])) is True


def test_corrupt_options_is_default_and_quarantined(dirs) -> None:
    (dirs["u-settings"] / "options.json").write_text("{")
    assert updates.load_update_check(str(dirs["u-settings"])) is True
    assert list(dirs["u-settings"].glob("options.json.corrupt-*"))


def test_unknown_option_keys_preserved(dirs) -> None:
    path = dirs["u-settings"] / "options.json"
    path.write_text(json.dumps({"version": 1, "update_check": True, "future": {"a": 1}}))
    updates.set_update_check(str(dirs["u-settings"]), False)
    assert json.loads(path.read_text()) == {
        "version": 1,
        "update_check": False,
        "future": {"a": 1},
    }


def test_setting_write_failure(dirs, monkeypatch) -> None:
    def boom(*_a: Any) -> None:
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(updates.storage, "atomic_write_json", boom)
    assert updates.set_update_check(str(dirs["u-settings"]), True) == {
        "ok": False,
        "error": "Couldn't save the setting: Read-only file system",
    }


# --- installed version -----------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [None, "{", "[]", json.dumps({}), json.dumps({"version": "dev"}), json.dumps({"version": 1})],
)
async def test_installed_version_unreadable(dirs, content, caplog) -> None:
    path = dirs["u-plugin"] / "package.json"
    if content is None:
        path.unlink()
    else:
        path.write_text(content)
    fetch = FakeFetch((200, body(release())))
    with caplog.at_level("WARNING"):
        info = await make(dirs, fetch).info(force=True)
    assert fetch.calls == []
    assert (info["installed"], info["status"], info["error"]) == (
        None,
        "unavailable",
        updates.ERR_INSTALLED,
    )


# --- through main.Plugin ---------------------------------------------------------------


async def test_plugin_callables(decky_env, monkeypatch) -> None:
    plugin_dir = Path(decky_env.DECKY_PLUGIN_DIR)
    (plugin_dir / "package.json").write_text(json.dumps({"version": "0.1.0"}))
    fetch = FakeFetch((200, body(release())))
    monkeypatch.setattr(updates, "https_fetch", fetch)
    monkeypatch.setattr(updates, "make_ssl_context", lambda: object())
    plugin = main.Plugin()
    assert await plugin.set_update_check(False) == {"ok": True, "enabled": False}
    assert (await plugin.update_info())["status"] == "disabled"
    assert (await plugin.update_info("yes"))["status"] == "disabled"  # only True forces
    info = await plugin.update_info(True, "extra")
    assert info["status"] == "available" and len(fetch.calls) == 1
    assert await plugin.set_update_check("on") == {"ok": False, "error": updates.ERR_SETTING}
    assert await plugin.set_update_check() == {"ok": False, "error": updates.ERR_SETTING}
    assert (await plugin.set_update_check(True, None))["ok"] is True
    settings = Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR, "options.json")
    assert json.loads(settings.read_text())["update_check"] is True


async def test_uninstall_keeps_update_files(decky_env, monkeypatch) -> None:
    (Path(decky_env.DECKY_PLUGIN_DIR) / "package.json").write_text('{"version": "0.1.0"}')
    monkeypatch.setattr(updates, "https_fetch", FakeFetch((200, body(release()))))
    monkeypatch.setattr(updates, "make_ssl_context", lambda: object())
    plugin = main.Plugin()
    await plugin.set_update_check(True)
    await plugin.update_info()
    options = Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR, "options.json")
    cache = Path(decky_env.DECKY_PLUGIN_RUNTIME_DIR, "update.json")
    assert options.exists() and cache.exists()
    await plugin._uninstall()
    assert options.exists() and cache.exists()


def test_frontend_constants_match() -> None:
    """src/update.ts must use plugin.json's name and the same release URL shape."""
    name = json.loads((PLUGIN_ROOT / "plugin.json").read_text())["name"]
    source = (PLUGIN_ROOT / "src" / "update.ts").read_text()
    assert f'export const PLUGIN_NAME = "{name}";' in source
    assert "github\\.com\\/jedwards1230\\/decky-wake-dispatch\\/releases\\/download" in source


# --- review fixes ----------------------------------------------------------------------


async def test_deeply_nested_json_is_unavailable(dirs) -> None:
    with pytest.raises(updates.CheckError):
        updates.parse_release(b"[" * 200_000)
    info = await make(dirs, FakeFetch((200, b"[" * 200_000))).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_ANSWER)


async def test_parser_bug_is_contained(dirs, monkeypatch) -> None:
    def broken(_body: bytes) -> dict[str, Any]:
        raise KeyError("bug")

    monkeypatch.setattr(updates, "parse_release", broken)
    info = await make(dirs, FakeFetch((200, body(release())))).info()
    assert (info["status"], info["error"]) == ("unavailable", updates.ERR_ANSWER)


class FakeResponse:
    def __init__(self, chunk: bytes, status: int = 200, clock: Clock | None = None) -> None:
        self.chunk = chunk
        self.status = status
        self.clock = clock
        self.closed = False
        self.reads: list[int] = []

    def read1(self, n: int) -> bytes:
        self.reads.append(n)
        if self.clock is not None:
            self.clock.now += 1.0  # each read takes a second
        return self.chunk[:n]

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.timeouts: list[float] = []

    def open(self, _request: Any, timeout: float) -> Any:
        self.timeouts.append(timeout)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _fetch_with(opener: FakeOpener, clock: Clock | None = None, timeout: float = 5.0):
    return REAL_HTTPS_FETCH(
        updates.API_URL,
        {},
        timeout,
        100,
        ssl.create_default_context(),
        opener_factory=lambda _ctx: opener,
        clock=clock or Clock(),
    )


def test_https_fetch_truncates_at_limit_plus_one() -> None:
    response = FakeResponse(b"x" * 64)
    status, data = _fetch_with(FakeOpener(response))
    assert status == 200 and data == b"x" * 101
    assert response.closed and all(n <= updates.READ_CHUNK for n in response.reads)


def test_https_fetch_reads_to_eof() -> None:
    class Short(FakeResponse):
        def read1(self, n: int) -> bytes:
            data, self.chunk = self.chunk[:n], self.chunk[n:]
            return data

    response = Short(b'{"a": 1}')
    assert _fetch_with(FakeOpener(response)) == (200, b'{"a": 1}')
    assert response.closed


def test_https_fetch_deadline_aborts_slow_drip() -> None:
    clock = Clock()
    response = FakeResponse(b"x", clock=clock)  # one byte per second, forever
    with pytest.raises(TimeoutError):
        _fetch_with(FakeOpener(response), clock, timeout=5.0)
    assert response.closed and len(response.reads) == 6  # reads at t=0..5, abort past 5 s


def test_https_fetch_http_error_returns_status() -> None:
    import io

    error = urllib.error.HTTPError(updates.API_URL, 404, "Not Found", {}, io.BytesIO(b"no"))
    assert _fetch_with(FakeOpener(error)) == (404, b"")


def test_https_fetch_redirect_refusal_propagates() -> None:
    with pytest.raises(updates.RedirectRefused):
        _fetch_with(FakeOpener(updates.RedirectRefused("off host")))


async def test_newer_memory_beats_stale_disk_cache(dirs, monkeypatch) -> None:
    clock = Clock()
    stale = dict(GOOD_CACHE, attempt_at=clock.now - 3 * 86400, success_at=clock.now - 3 * 86400)
    (dirs["u-runtime"] / "update.json").write_text(json.dumps(stale))

    def boom(*_a: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(updates.storage, "atomic_write_json", boom)
    fetch = FakeFetch((200, body(release("0.1.0"))))
    updater = make(dirs, fetch, clock)
    assert (await updater.info())["status"] == "current"
    clock.now += 10
    info = await updater.info()
    assert len(fetch.calls) == 1 and info["status"] == "current"


async def test_disabled_wins_over_unreadable_version(dirs) -> None:
    updates.set_update_check(str(dirs["u-settings"]), False)
    (dirs["u-plugin"] / "package.json").unlink()
    info = await make(dirs, FakeFetch((200, b""))).info()
    assert (info["status"], info["error"], info["installed"]) == ("disabled", None, None)
