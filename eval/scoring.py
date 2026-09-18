"""평가 30문항 채점 규칙 (스펙 5-6, 기본 스펙 8-2). 파이프라인을 모른다 — 러너가 관측값을 넘긴다."""
from dataclasses import dataclass
from statistics import median

NOT_GROUNDED_MESSAGE = "제공된 문서에서 확인되지 않습니다."
THRESHOLDS = {"hit5": 0.8, "menu": 0.9, "shots": 0.8, "median_s": 15.0, "max_s": 30.0}


@dataclass
class Result:
    id: int
    kind: str                 # console | general | outside
    question: str
    hit5: bool | None         # console·general: 상위 5 에 정답 문서
    menu_ok: bool | None      # console: 첫 줄에 expect_menu 포함
    shots_ok: bool | None     # console: 유효 마커 1개 이상
    outside_ok: bool | None   # outside: 고정 문구 + 출처 없음
    elapsed_s: float
    error: str | None


def judge(item, cand_paths, first_line, valid_marker_count, answer, elapsed_s, error,
          sources_shown=True) -> Result:
    # cand_paths 는 언제나 실제 검색 결과다(적중 채점용). 화면에 출처를 보였는지는
    # sources_shown 으로 따로 받는다 — 거부 답변은 검색이 됐어도 출처를 보이지 않는다.
    kind = item["kind"]
    r = Result(id=item["id"], kind=kind, question=item["question"], hit5=None, menu_ok=None,
               shots_ok=None, outside_ok=None, elapsed_s=round(elapsed_s, 1), error=error)
    if error:
        if kind == "outside":
            r.outside_ok = False
        else:
            r.hit5 = False
            if kind == "console":
                r.menu_ok = False
                r.shots_ok = False
        return r

    if kind == "outside":
        r.outside_ok = answer.strip().startswith(NOT_GROUNDED_MESSAGE) and not sources_shown
        return r

    r.hit5 = item["expect_path"] in cand_paths[:5]
    if kind == "console":
        # 콘솔 프롬프트가 첫 줄에 언제나 '콘솔 > 카테고리 > 서비스' 를 쓰므로
        # '명시되지 않음' 예외는 더 없다 — 기대 서비스명이 들어 있는지만 본다.
        r.menu_ok = item["expect_menu"] in first_line
        r.shots_ok = valid_marker_count >= 1
    return r


def _rate(results, attr):
    scored = [getattr(r, attr) for r in results if getattr(r, attr) is not None]
    return (sum(1 for v in scored if v), len(scored))


def summarize(results) -> dict:
    hit5 = _rate(results, "hit5")
    menu = _rate(results, "menu_ok")
    shots = _rate(results, "shots_ok")
    outside = _rate(results, "outside_ok")
    times = [r.elapsed_s for r in results if r.error is None] or [0.0]
    s = {
        "hit5": hit5, "menu": menu, "shots": shots, "outside": outside,
        "median_s": round(median(times), 1), "max_s": round(max(times), 1),
        "errors": sum(1 for r in results if r.error),
    }

    def ok(pair, key):
        n, d = pair
        return d == 0 or n / d >= THRESHOLDS[key]

    s["pass"] = (
        ok(hit5, "hit5") and ok(menu, "menu") and ok(shots, "shots")
        and outside[0] == outside[1]
        and s["median_s"] <= THRESHOLDS["median_s"] and s["max_s"] <= THRESHOLDS["max_s"]
        and s["errors"] == 0
    )
    return s


def _mark(v):
    return "-" if v is None else ("O" if v else "X")


def render_table(results, summary) -> str:
    lines = ["| id | 종류 | 질문 | 적중 | 메뉴 | 스크린샷 | 문서밖 | 초 | 오류 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.id} | {r.kind} | {r.question[:30]} | {_mark(r.hit5)} | {_mark(r.menu_ok)} | "
                     f"{_mark(r.shots_ok)} | {_mark(r.outside_ok)} | {r.elapsed_s} | {r.error or ''} |")

    def pct(pair):
        n, d = pair
        return f"{n}/{d}" + (f" ({n / d * 100:.0f}%)" if d else "")

    lines += [
        "",
        f"- 적중(상위 5): {pct(summary['hit5'])} (기준 80%)",
        f"- 콘솔 메뉴 경로: {pct(summary['menu'])} (기준 90%)",
        f"- 콘솔 스크린샷: {pct(summary['shots'])} (기준 80%)",
        f"- 문서 밖 고정 문구: {pct(summary['outside'])} (기준 전부)",
        f"- 지연 중앙값/최대: {summary['median_s']}초 / {summary['max_s']}초 (기준 15초 / 30초)",
        f"- 예외: {summary['errors']}건",
        f"- **판정: {'통과' if summary['pass'] else '미달'}**",
    ]
    return "\n".join(lines)
