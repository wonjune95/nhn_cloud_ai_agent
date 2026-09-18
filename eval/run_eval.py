"""평가 30문항 러너 (스펙 5-6). UI 파드 안에서 돌린다:
    kubectl -n nhn-docs-bot cp eval/ <ui-pod>:/app/eval/ && kubectl -n nhn-docs-bot exec <ui-pod> -- python -u eval/run_eval.py
로컬:  cd app && DB_HOST=localhost python ../eval/run_eval.py --questions ../eval/questions.yaml
결과는 markdown 표로 stdout 에 찍는다. 기준 미달이면 exit 1.
"""
import argparse
import os
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                   # scoring
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))  # rag 등 (파드에서는 /app 이 cwd)

import scoring  # noqa: E402


def run_one(rag, ar, item):
    q = item["question"]
    t0 = time.time()
    try:
        intent = rag.detect_intent(q)
        service = rag.detect_service(q, rag.ALIASES)
        found = rag.hybrid_search(q, intent=intent, service=service)
        cands, grounded = rag.rerank_candidates(q, found, top_k=5)
        cand_paths = [c.source_path for c in cands]
        if grounded is False:
            answer, image_map = ar.NOT_GROUNDED_MESSAGE, {}
            cand_paths = []
        else:
            stream, image_map = rag.answer_stream(q, cands, intent=intent)
            answer = "".join(stream)
        first_line = answer.strip().splitlines()[0] if answer.strip() else ""
        valid = len(ar.valid_markers(answer, image_map))
        return scoring.judge(item, cand_paths, first_line, valid, answer, time.time() - t0, None)
    except Exception as e:
        return scoring.judge(item, [], "", 0, "", time.time() - t0, f"{type(e).__name__}: {str(e)[:60]}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=os.path.join(HERE, "questions.yaml"))
    p.add_argument("--only", default="", help="쉼표로 구분한 id 목록 (디버깅용)")
    args = p.parse_args(argv)

    import rag
    import answer_render as ar

    items = yaml.safe_load(open(args.questions, encoding="utf-8"))
    if args.only:
        keep = {int(x) for x in args.only.split(",")}
        items = [i for i in items if i["id"] in keep]

    print("BM25:", rag.build_bm25(), "chunks", file=sys.stderr)
    results = []
    for item in items:
        r = run_one(rag, ar, item)
        results.append(r)
        print(f"[{r.id:2d}] {r.kind:7s} {r.elapsed_s:5.1f}s hit={r.hit5} menu={r.menu_ok} shots={r.shots_ok} "
              f"outside={r.outside_ok} {r.error or ''}", file=sys.stderr)
        time.sleep(1)  # 무료 티어 배려

    summary = scoring.summarize(results)
    print(scoring.render_table(results, summary))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
