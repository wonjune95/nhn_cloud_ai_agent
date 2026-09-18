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


def test_save_falls_back_to_in_place_write_when_replace_stays_locked(tmp_path, monkeypatch):
    import crawlling.manifest as mod
    monkeypatch.setattr(mod.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "locked")))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    path = str(tmp_path / "manifest.json")
    m = Manifest.load(path)
    m.put(make_entry())

    m.save()  # os.replace 가 영원히 실패해도 예외를 내지 않아야 한다.

    assert Manifest.load(path).get(make_entry().url) == make_entry()


def test_save_raises_when_in_place_write_also_fails(tmp_path, monkeypatch):
    import builtins

    import crawlling.manifest as mod

    path = str(tmp_path / "manifest.json")
    monkeypatch.setattr(mod.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "locked")))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    real_open = builtins.open

    def flaky_open(file, mode="r", *args, **kwargs):
        if str(file) == path and "w" in mode:
            raise PermissionError(5, "locked (in-place)")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)

    m = Manifest.load(path)
    m.put(make_entry())
    with pytest.raises(PermissionError):
        m.save()


def test_content_hash_is_deterministic_and_distinct():
    assert content_hash("가") == content_hash("가")
    assert content_hash("가") != content_hash("나")
    assert len(content_hash("x")) == 64


def test_now_iso_has_timezone():
    assert now_iso().endswith("+00:00")


def test_load_recovers_from_backup_when_main_file_is_corrupt(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    m = Manifest.load(str(path))
    m.put(make_entry())
    m.save()

    # save() 는 제자리 쓰기 폴백에서만 .bak 을 남기므로 여기서는 직접 만든다.
    (tmp_path / "manifest.json.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text('{"broken": ', encoding="utf-8")

    recovered = Manifest.load(str(path))
    assert recovered.get(make_entry().url) == make_entry()
    out = capsys.readouterr().out
    assert "깨졌습니다" in out and "복구" in out


def test_load_starts_empty_when_both_main_and_backup_are_corrupt(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text('{"broken": ', encoding="utf-8")
    (tmp_path / "manifest.json.bak").write_text("not json at all", encoding="utf-8")

    m = Manifest.load(str(path))
    assert m.entries == {}
    assert "빈 목록으로 시작합니다" in capsys.readouterr().out


def test_load_starts_empty_when_corrupt_and_no_backup(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{{{", encoding="utf-8")
    assert Manifest.load(str(path)).entries == {}


def test_in_place_fallback_writes_a_backup_first(tmp_path, monkeypatch):
    """os.replace 가 계속 막혀 제자리로 덮어쓸 때, 직전 내용이 .bak 에 남는다."""
    import crawlling.manifest as mod

    path = tmp_path / "manifest.json"
    m = Manifest.load(str(path))
    m.put(make_entry())
    m.save()                       # 정상 경로(os.replace)

    monkeypatch.setattr(mod.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "locked")))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    m.put(make_entry(url="https://docs.nhncloud.com/ko/c/", path="C/D/e.html"))
    m.save()                       # 제자리 쓰기 폴백

    backup = tmp_path / "manifest.json.bak"
    assert backup.exists()
    # .bak 은 덮어쓰기 직전 내용 = 항목 1건
    import json
    assert len(json.loads(backup.read_text(encoding="utf-8"))) == 1
    assert len(Manifest.load(str(path)).entries) == 2
