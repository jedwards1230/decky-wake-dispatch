import json
import os

import pytest

from wake_dispatch import storage


@pytest.fixture
def work(tmp_path):
    """A directory of its own (tmp_path also holds the decky stub dirs)."""
    path = tmp_path / "work"
    path.mkdir()
    return path


def test_atomic_write_creates_dirs_and_round_trips(work) -> None:
    path = work / "new" / "dir" / "file.json"
    storage.atomic_write_json(str(path), {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert os.listdir(path.parent) == ["file.json"]


@pytest.mark.parametrize("target", ["replace", "dump"])
def test_failed_write_keeps_old_file_and_no_temp(work, monkeypatch, target) -> None:
    path = work / "file.json"
    storage.atomic_write_json(str(path), {"old": True})

    def boom(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    if target == "replace":
        monkeypatch.setattr(storage.os, "replace", boom)
    else:
        monkeypatch.setattr(storage.json, "dump", boom)
    with pytest.raises(OSError):
        storage.atomic_write_json(str(path), {"new": True})
    assert json.loads(path.read_text()) == {"old": True}
    assert os.listdir(work) == ["file.json"]


def test_migrate_bare_list(work) -> None:
    (work / "devices.json").write_text(json.dumps([{"name": "Gaming PC"}]))
    assert storage.load_settings(str(work)) == {
        "version": 1,
        "devices": [{"name": "Gaming PC"}],
        "migrated": True,
        "future": False,
    }


def test_migrate_missing_version(work) -> None:
    (work / "devices.json").write_text(json.dumps({"devices": [{"name": "Office PC"}]}))
    doc = storage.load_settings(str(work))
    assert doc["devices"] == [{"name": "Office PC"}]
    assert doc["migrated"] is True


def test_current_version_not_migrated(work) -> None:
    (work / "devices.json").write_text(json.dumps({"version": 1, "devices": []}))
    assert storage.load_settings(str(work))["migrated"] is False


def test_future_version_read_best_effort_and_backed_up(work) -> None:
    original = json.dumps({"version": 7, "devices": [{"name": "Office PC"}], "extra": 1})
    (work / "devices.json").write_text(original)
    doc = storage.load_settings(str(work))
    assert doc["devices"] == [{"name": "Office PC"}]
    assert doc["future"] is True
    assert (work / "devices.json").read_text() == original
    assert (work / "devices.json.v7.bak").read_text() == original


def test_corrupt_settings_renamed_and_treated_empty(work) -> None:
    (work / "devices.json").write_text("{not json")
    doc = storage.load_settings(str(work), clock=lambda: 1700000000.5)
    assert doc["devices"] == []
    assert sorted(os.listdir(work)) == ["devices.json.corrupt-1700000000"]
    assert (work / "devices.json.corrupt-1700000000").read_text() == "{not json"


def test_wrong_shape_settings_quarantined(work) -> None:
    (work / "devices.json").write_text('"just a string"')
    assert storage.load_settings(str(work), clock=lambda: 5)["devices"] == []
    assert os.listdir(work) == ["devices.json.corrupt-5"]


def test_quarantine_does_not_overwrite_previous(work) -> None:
    for _ in range(2):
        (work / "state.json").write_text("garbage")
        assert storage.load_state(str(work), clock=lambda: 9) == storage.empty_state()
    assert sorted(os.listdir(work)) == ["state.json.corrupt-9", "state.json.corrupt-9-1"]


def test_missing_files_and_dirs(work) -> None:
    missing = str(work / "nope")
    assert storage.load_settings(missing)["devices"] == []
    assert storage.load_state(missing) == storage.empty_state()
    storage.save_state(missing, storage.empty_state())
    assert storage.load_state(missing) == storage.empty_state()


def test_state_fills_missing_keys(work) -> None:
    (work / "state.json").write_text(json.dumps({"boot_id": "abc", "automation": {}}))
    assert storage.load_state(str(work)) == {
        "boot_id": "abc",
        "last": None,
        "automation": {"boot": None, "resume": None},
    }


def test_atomic_write_temp_in_same_dir_and_fsync_before_replace(work, monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    real_mkstemp, real_fsync, real_replace = storage.tempfile.mkstemp, os.fsync, os.replace

    def mkstemp(*args, **kwargs):
        calls.append(("mkstemp", kwargs.get("dir")))
        return real_mkstemp(*args, **kwargs)

    def fsync(fd):
        calls.append(("fsync", fd))
        return real_fsync(fd)

    def replace(src, dst):
        calls.append(("replace", os.path.dirname(src)))
        return real_replace(src, dst)

    monkeypatch.setattr(storage.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(storage.os, "fsync", fsync)
    monkeypatch.setattr(storage.os, "replace", replace)
    storage.atomic_write_json(str(work / "file.json"), {"a": 1})
    names = [c[0] for c in calls]
    assert calls[0] == ("mkstemp", str(work))
    assert names.index("fsync") < names.index("replace")
    assert calls[names.index("replace")][1] == str(work)
    assert names.count("fsync") == 2  # the file, then the directory after the rename


def test_unreadable_file_returns_none_without_quarantine(work, monkeypatch) -> None:
    (work / "devices.json").mkdir()  # IsADirectoryError
    assert storage.read_json(str(work / "devices.json")) is None
    assert os.listdir(work) == ["devices.json"]

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", denied)
    assert storage.load_settings(str(work))["devices"] == []
    assert storage.load_state(str(work)) == storage.empty_state()
    assert os.listdir(work) == ["devices.json"]


def test_backup_file_never_overwrites(work) -> None:
    (work / "devices.json").write_text("v1")
    first = storage.backup_file(str(work / "devices.json"), "bak", clock=lambda: 7)
    second = storage.backup_file(str(work / "devices.json"), "bak", clock=lambda: 7)
    assert (first, second) == (
        str(work / "devices.json.bak-7"),
        str(work / "devices.json.bak-7-1"),
    )
    assert (work / "devices.json.bak-7").read_text() == "v1"
