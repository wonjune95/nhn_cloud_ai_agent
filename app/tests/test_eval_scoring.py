"""eval/scoring.py 의 채점 규칙. 파이프라인은 돌리지 않는다."""
import importlib.util
import os
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "scoring", pathlib.Path(__file__).resolve().parents[2] / "eval" / "scoring.py")
scoring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scoring)

CONSOLE = {"id": 1, "kind": "console", "question": "q", "expect_path": "Network/DNS Plus/콘솔 사용 가이드.html", "expect_menu": "DNS Plus"}
GENERAL = {"id": 21, "kind": "general", "question": "q", "expect_path": "Network/VPC/API v2 가이드.html"}
OUTSIDE = {"id": 26, "kind": "outside", "question": "q"}


def test_console_all_pass():
    r = scoring.judge(CONSOLE, ["Network/DNS Plus/콘솔 사용 가이드.html", "x"], "콘솔 > Network > DNS Plus > DNS Zone", 2, "본문", 8.0, None)
    assert (r.hit5, r.menu_ok, r.shots_ok, r.outside_ok) == (True, True, True, None)


def test_console_menu_fails_when_first_line_says_unspecified():
    r = scoring.judge(CONSOLE, ["Network/DNS Plus/콘솔 사용 가이드.html"], "메뉴 경로: 문서에 명시되지 않음", 0, "본문", 8.0, None)
    assert r.hit5 is True and r.menu_ok is False and r.shots_ok is False


def test_hit5_only_counts_first_five():
    paths = ["a", "b", "c", "d", "e", "Network/DNS Plus/콘솔 사용 가이드.html"]
    assert scoring.judge(CONSOLE, paths, "콘솔 > DNS Plus", 1, "", 1.0, None).hit5 is False


def test_general_only_scores_hit():
    r = scoring.judge(GENERAL, ["Network/VPC/API v2 가이드.html"], "아무 줄", 0, "본문", 3.0, None)
    assert r.hit5 is True and r.menu_ok is None and r.shots_ok is None and r.outside_ok is None


def test_outside_requires_fixed_message_and_no_sources():
    r = scoring.judge(OUTSIDE, [], "제공된 문서에서 확인되지 않습니다.", 0, "제공된 문서에서 확인되지 않습니다.", 2.0, None)
    assert r.outside_ok is True and r.hit5 is None
    bad = scoring.judge(OUTSIDE, ["x"], "서울 날씨는", 0, "서울 날씨는 맑음", 2.0, None)
    assert bad.outside_ok is False


def test_error_marks_everything_failed():
    r = scoring.judge(CONSOLE, [], "", 0, "", 0.5, "RateLimitError")
    assert r.error == "RateLimitError" and r.hit5 is False and r.menu_ok is False and r.shots_ok is False


def _res(kind, **kw):
    base = dict(id=0, kind=kind, question="q", hit5=None, menu_ok=None, shots_ok=None, outside_ok=None, elapsed_s=1.0, error=None)
    base.update(kw)
    return scoring.Result(**base)


def test_summarize_rates_and_pass():
    results = (
        [_res("console", hit5=True, menu_ok=True, shots_ok=True, elapsed_s=10.0)] * 19
        + [_res("console", hit5=False, menu_ok=False, shots_ok=False, elapsed_s=20.0)]
        + [_res("general", hit5=True, elapsed_s=5.0)] * 5
        + [_res("outside", outside_ok=True, elapsed_s=2.0)] * 5
    )
    s = scoring.summarize(results)
    assert s["hit5"] == (24, 25) and s["menu"] == (19, 20) and s["shots"] == (19, 20) and s["outside"] == (5, 5)
    assert s["max_s"] == 20.0 and s["errors"] == 0
    assert s["pass"] is True


def test_summarize_fails_on_threshold():
    results = [_res("console", hit5=False, menu_ok=True, shots_ok=True)] * 10 + [_res("console", hit5=True, menu_ok=True, shots_ok=True)] * 10
    assert scoring.summarize(results)["pass"] is False


def test_render_table_mentions_every_question_and_summary():
    results = [_res("console", id=1, hit5=True, menu_ok=True, shots_ok=False, elapsed_s=12.3)]
    text = scoring.render_table(results, scoring.summarize(results))
    assert "| 1 |" in text and "12.3" in text and "적중" in text


def test_run_eval_sys_path_finds_rag_and_skips_main(capsys):
    """run_eval.py 를 importlib 으로 로드만 해도(스크립트로 실행하지 않아도) rag.py 를
    찾을 수 있는 디렉터리가 sys.path 에 들어가야 한다 (로컬 저장소 레이아웃과
    파드 레이아웃 둘 다). import 시점에 main() 이 돌아가서는 안 된다."""
    spec = importlib.util.spec_from_file_location(
        "run_eval", pathlib.Path(__file__).resolve().parents[2] / "eval" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    assert any(os.path.isfile(os.path.join(p, "rag.py")) for p in sys.path)

    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_questions_file_shape():
    import yaml
    items = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    kinds = [i["kind"] for i in items]
    assert len(items) == 30 and sorted(i["id"] for i in items) == list(range(1, 31))
    assert kinds.count("console") == 20 and kinds.count("general") == 5 and kinds.count("outside") == 5
    for i in items:
        if i["kind"] == "console":
            assert i["expect_path"].endswith(".html") and i["expect_menu"]
        elif i["kind"] == "general":
            assert i["expect_path"].endswith(".html")
