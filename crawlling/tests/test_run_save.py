"""run() 이 skip 된 페이지에서는 manifest.save() 를 호출하지 않는지,
manifest 저장 실패가 크롤을 중단시키지 않는지 검증한다.

run() 은 매 페이지 저장(skip 제외)과는 별도로, 루프가 끝난 뒤 요약을 찍기 전에
manifest.save() 를 한 번 더(무조건) 호출해 지속되는 저장 실패를 드러낸다.
"""

from crawlling import crawl


class DummyDriver:
    def quit(self):
        pass


FAKE_TASKS = [
    {"category": "A", "name": "a", "url": "https://docs.nhncloud.com/ko/a/"},
    {"category": "B", "name": "b", "url": "https://docs.nhncloud.com/ko/b/"},
]


def make_args(tmp_path):
    return crawl.parse_args([
        "--save-dir", str(tmp_path / "docs"),
    ])


def test_run_skips_save_when_all_tasks_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "build_driver", lambda: DummyDriver())
    monkeypatch.setattr(crawl, "discover", lambda driver: list(FAKE_TASKS))
    monkeypatch.setattr(crawl, "save_task", lambda task, driver, manifest, save_dir, args: "skip")

    save_calls = {"n": 0}
    real_save = crawl.Manifest.save

    def counting_save(self):
        save_calls["n"] += 1
        return real_save(self)

    monkeypatch.setattr(crawl.Manifest, "save", counting_save)

    args = make_args(tmp_path)
    crawl.run(args)

    # 페이지 저장은 0번이지만, 루프가 끝난 뒤의 무조건 저장이 1번 더 있다.
    assert save_calls["n"] == 1


def test_run_saves_when_tasks_are_not_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "build_driver", lambda: DummyDriver())
    monkeypatch.setattr(crawl, "discover", lambda driver: list(FAKE_TASKS))
    monkeypatch.setattr(crawl, "save_task", lambda task, driver, manifest, save_dir, args: "ok")

    save_calls = {"n": 0}
    real_save = crawl.Manifest.save

    def counting_save(self):
        save_calls["n"] += 1
        return real_save(self)

    monkeypatch.setattr(crawl.Manifest, "save", counting_save)

    args = make_args(tmp_path)
    crawl.run(args)

    # 페이지 저장 2번(각 태스크) + 루프가 끝난 뒤의 무조건 저장 1번.
    assert save_calls["n"] == 3


def test_run_continues_after_a_save_failure(tmp_path, monkeypatch, capsys):
    """manifest.save() 가 한 번 OSError 를 내도 나머지 태스크 처리와 최종 저장까지 이어진다."""
    monkeypatch.setattr(crawl, "build_driver", lambda: DummyDriver())
    monkeypatch.setattr(crawl, "discover", lambda driver: list(FAKE_TASKS))
    monkeypatch.setattr(crawl, "save_task", lambda task, driver, manifest, save_dir, args: "ok")

    calls = {"n": 0}
    real_save = crawl.Manifest.save

    def flaky_save(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("locked")
        return real_save(self)

    monkeypatch.setattr(crawl.Manifest, "save", flaky_save)

    args = make_args(tmp_path)
    crawl.run(args)

    # 첫 페이지 저장(실패) + 둘째 페이지 저장(성공) + 루프 뒤 무조건 저장 = 3.
    assert calls["n"] == 3
    out = capsys.readouterr().out
    assert "[1/2] A > a → ok" in out
    assert "[2/2] B > b → ok" in out
    assert "[경고] manifest 저장 실패" in out
