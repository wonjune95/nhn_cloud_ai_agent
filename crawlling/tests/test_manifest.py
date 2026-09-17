import pytest

from crawlling.manifest import Entry, Manifest, content_hash, now_iso


def make_entry(**over):
    base = dict(
        url="https://docs.nhncloud.com/ko/a/",
        path="A/_/b.html",
        breadcrumb=["A", "b"],
        fetched_at="2026-09-17T00:00:00+00:00",
        content_hash="abc",
        image_count=2,
        status="ok",
    )
    base.update(over)
    return Entry(**base)


def test_load_missing_file_gives_empty_manifest(tmp_path):
    m = Manifest.load(str(tmp_path / "manifest.json"))
    assert m.entries == {}


def test_roundtrip_preserves_entries(tmp_path):
    path = str(tmp_path / "manifest.json")
    m = Manifest.load(path)
    m.put(make_entry())
    m.put(make_entry(url="https://docs.nhncloud.com/ko/c/", path="C/D/e.html", status="error", error="timeout"))
    m.save()

    m2 = Manifest.load(path)
    assert m2.get("https://docs.nhncloud.com/ko/a/") == make_entry()
    assert m2.get("https://docs.nhncloud.com/ko/c/").error == "timeout"
    assert m2.get("https://docs.nhncloud.com/ko/zzz/") is None


def test_by_path_indexes_entries(tmp_path):
    m = Manifest.load(str(tmp_path / "m.json"))
    m.put(make_entry())
    assert m.by_path()["A/_/b.html"].content_hash == "abc"


def test_save_leaves_no_temp_file(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest.load(str(path))
    m.put(make_entry())
    m.save()
    assert path.exists()
    assert not (tmp_path / "manifest.json.tmp").exists()


def test_save_retries_when_replace_is_locked(tmp_path, monkeypatch):
    import crawlling.manifest as mod
    calls = {"n": 0}
    real_replace = mod.os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "locked")
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", flaky_replace)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    m = Manifest.load(str(tmp_path / "manifest.json"))
    m.put(make_entry())
    m.save()
    assert calls["n"] == 3
    assert Manifest.load(str(tmp_path / "manifest.json")).get(make_entry().url) == make_entry()


def test_save_gives_up_after_ten_locked_attempts(tmp_path, monkeypatch):
    import crawlling.manifest as mod
    monkeypatch.setattr(mod.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "locked")))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    m = Manifest.load(str(tmp_path / "manifest.json"))
    m.put(make_entry())
    with pytest.raises(PermissionError):
        m.save()


def test_content_hash_is_deterministic_and_distinct():
    assert content_hash("가") == content_hash("가")
    assert content_hash("가") != content_hash("나")
    assert len(content_hash("x")) == 64


def test_now_iso_has_timezone():
    assert now_iso().endswith("+00:00")
