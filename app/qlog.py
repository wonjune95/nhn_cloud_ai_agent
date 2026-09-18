"""질문 로그(questions)와 👍/👎 피드백 (스펙 4-2).

실패해도 화면을 깨뜨리지 않는다: 예외는 stderr 에만 남기고 None/False 를 돌려준다.
사용자 식별 정보는 저장하지 않는다.
"""
import json
import sys

from db import get_conn


def sources_of(cands) -> list[dict]:
    """questions.sources 에 넣을 모양. Candidate 목록에서 출처 네 항목만 뽑는다."""
    return [
        {"source_path": c.source_path, "section_path": c.section_path,
         "source_url": c.source_url, "service": c.service}
        for c in cands
    ]


def log_question(*, session_id, question, retrieval_query, service, intent, grounded,
                 elapsed_ms, sources, answer, error=None) -> int | None:
    """한 행을 넣고 id 를 돌려준다. 실패하면 None."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO questions (session_id, question, retrieval_query, service, intent, grounded, "
            "elapsed_ms, sources, answer, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (session_id, question, retrieval_query, service, intent, grounded, int(elapsed_ms),
             json.dumps(sources, ensure_ascii=False), answer, error),
        )
        qid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return qid
    except Exception as e:
        print(f"  [질문 로그 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def set_feedback(question_id: int, value: int) -> bool:
    """feedback 을 +1/-1 로 갱신한다. 실패하면 False."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE questions SET feedback = %s WHERE id = %s", (value, question_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  [질문 로그 실패] 피드백 저장: {type(e).__name__}: {e}", file=sys.stderr)
        return False
