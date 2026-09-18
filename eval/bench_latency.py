"""동시 질문 1/3/6 개를 실제 파이프라인에 넣어 단계별 지연과 재시도 횟수를 잰다.

    cd app && DB_HOST=localhost python ../eval/bench_latency.py
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import llm
import rag

QUESTIONS = [
    "VPC에 서브넷을 추가하는 방법을 알려줘",
    "로드 밸런서를 생성하는 절차는?",
    "플로팅 IP를 인스턴스에 연결하려면 어떻게 해?",
    "NAT 게이트웨이는 어떻게 만들어?",
    "시큐리티 그룹에 규칙을 추가하는 방법",
    "DNS Plus에서 도메인을 등록하는 방법",
    "전자세금계산서는 콘솔 어디서 확인해?",
    "VPN 게이트웨이 설정 방법 알려줘",
    "피어링 게이트웨이는 어떻게 생성해?",
    "트래픽 미러링은 어떻게 설정해?",
]

_lock = threading.Lock()
retries = {"n": 0}


def _count_retries(*args, **kwargs):
    if any("재시도" in str(a) for a in args):
        with _lock:
            retries["n"] += 1


llm.print = _count_retries
rag.print = _count_retries


def run_one(q):
    t0 = time.time()
    try:
        intent = rag.detect_intent(q)
        service = rag.detect_service(q, rag.ALIASES)
        cands = rag.hybrid_search(q, intent=intent, service=service)
        t1 = time.time()
        docs, grounded = rag.rerank_candidates(q, cands)
        t2 = time.time()
        prompt, _ = rag.build_prompt(q, docs, intent=intent)
        answer = llm.chat(prompt, system=rag.system_prompt(intent), max_tokens=2048)
        t3 = time.time()
        return dict(q=q, ok=True, search=t1 - t0, rerank=t2 - t1, answer=t3 - t2, total=t3 - t0,
                    grounded=grounded, chars=len(answer))
    except Exception as e:
        return dict(q=q, ok=False, total=time.time() - t0, err=f"{type(e).__name__}: {str(e)[:80]}")


def main():
    print("BM25 구축:", rag.build_bm25(), "chunks")
    summary = []
    for n, qs in ((1, QUESTIONS[0:1]), (3, QUESTIONS[1:4]), (6, QUESTIONS[4:10])):
        retries["n"] = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=n) as pool:
            results = list(pool.map(run_one, qs))
        wall = time.time() - t0
        oks = [r for r in results if r["ok"]]
        print(f"\n=== 동시 {n}개 === 벽시계 {wall:.1f}초, 성공 {len(oks)}/{n}, 재시도 {retries['n']}회")
        for r in results:
            if r["ok"]:
                print(f"  {r['total']:5.1f}초 (검색 {r['search']:4.1f} / 리랭킹 {r['rerank']:5.1f} / 답변 {r['answer']:5.1f}) "
                      f"grounded={r['grounded']} {r['chars']:4d}자  {r['q'][:22]}")
            else:
                print(f"  실패 {r['total']:5.1f}초  {r['err']}  {r['q'][:22]}")
        totals = [r["total"] for r in results]
        summary.append((n, wall, len(oks), retries["n"], max(totals), sum(r["total"] for r in oks) / max(len(oks), 1)))
        time.sleep(10)

    print("\n=== 요약 ===\n동시 | 벽시계 | 성공 | 재시도 | 최대 | 평균")
    for n, wall, ok, rt, mx, avg in summary:
        print(f"{n:>4} | {wall:6.1f}초 | {ok}/{n} | {rt:>4}회 | {mx:5.1f}초 | {avg:5.1f}초")


if __name__ == "__main__":
    main()
