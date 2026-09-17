"""run() 이 skip 된 페이지에서는 manifest.save() 를 호출하지 않는지 검증한다."""

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

    assert save_calls["n"] == 0


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

    assert save_calls["n"] == 2
