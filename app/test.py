"""NVIDIA NIM 연결 확인 스크립트.

    docker compose exec app python test.py
"""

from llm import EMBEDDING_MODEL_NAME, LLM_MODEL_NAME, chat, client, embed_one


def main():
    print("=== 1. 모델 목록 ===")
    models = [m.id for m in client.models.list()]
    print(f"접근 가능 모델 {len(models)}개")

    for name in (LLM_MODEL_NAME, EMBEDDING_MODEL_NAME):
        mark = "OK" if name in models else "목록에 없음"
        print(f"  - {name}: {mark}")

    print("\n=== 2. 채팅 호출 ===")
    print(chat("Which number is larger, 9.11 or 9.8?"))

    print("\n=== 3. 임베딩 호출 (한국어) ===")
    vec = embed_one("NHN Cloud 인스턴스를 생성하려면 콘솔에서 Compute 메뉴로 이동합니다.")
    print(f"dim = {len(vec)}")
    print(f"앞 5개 = {vec[:5]}")


if __name__ == "__main__":
    main()
