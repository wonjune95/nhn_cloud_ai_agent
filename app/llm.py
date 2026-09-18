"""NVIDIA NIM (OpenAI 호환) 클라이언트 래퍼.

채팅·임베딩 호출을 한곳에 모으고, NIM에서 간헐적으로 나오는
503 Service temporarily overloaded 를 지수 백오프로 재시도한다.
"""

import os
import time

from openai import OpenAI, APIConnectionError, APIError, APIStatusError, APITimeoutError

BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL_NAME = os.getenv("NVIDIA_LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b")
EMBEDDING_MODEL_NAME = os.getenv("NVIDIA_EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b")

MAX_RETRIES = 5
BACKOFF_BASE = 2.0
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# 키가 없어도 import 는 되게 한다 (테스트·문서 도구가 이 모듈을 그냥 읽어 들인다).
# 실제 호출 직전에 _require_key() 로 확인한다.
client = OpenAI(base_url=BASE_URL, api_key=os.getenv("NVIDIA_API_KEY") or "missing", timeout=120.0)


def _require_key() -> None:
    if not os.getenv("NVIDIA_API_KEY"):
        raise RuntimeError(
            "NVIDIA_API_KEY 가 설정되지 않았습니다. 프로젝트 루트의 .env 를 확인하세요."
        )


def _retry(fn, **kwargs):
    last_err = None

    for attempt in range(MAX_RETRIES):
        try:
            return fn(**kwargs)
        except APIStatusError as e:
            if e.status_code not in RETRY_STATUS:
                raise
            last_err = e
            label = e.status_code
        except (APIConnectionError, APITimeoutError) as e:
            last_err = e
            label = type(e).__name__

        wait = BACKOFF_BASE ** attempt
        print(f"  [재시도 {attempt + 1}/{MAX_RETRIES}] {label} → {wait:.0f}초 대기")
        time.sleep(wait)

    raise last_err


def chat(prompt, system="You are a helpful assistant.", temperature=0.5, max_tokens=1024, think=True):
    """think=False 면 Nemotron 의 추론 토큰을 끈다. 리랭킹처럼 짧은 구조화 출력은 추론 없이도 정확하고 30배 빠르다(실측 34초→1.3초)."""
    _require_key()
    res = _retry(
        client.chat.completions.create,
        model=LLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        top_p=1,
        max_tokens=max_tokens,
        stream=False,
        extra_body=None if think else {"chat_template_kwargs": {"enable_thinking": False}},
    )

    # Nemotron 은 추론 과정을 reasoning_content 로 분리해서 내려준다. 본문만 쓴다.
    return res.choices[0].message.content or ""


def chat_stream(prompt, system="You are a helpful assistant.", temperature=0.5, max_tokens=2048):
    """토큰을 순차적으로 내보낸다. Streamlit 의 write_stream 에 그대로 넘길 수 있다.

    NIM 은 스트림을 연 뒤에도 "Service temporarily overloaded" 를 흘려보낼 수 있다.
    이 오류는 요청 생성이 아니라 스트림을 읽는 도중에 나므로 _retry 가 잡지 못한다.
    아직 한 토큰도 내보내지 않았다면 처음부터 다시 요청한다.
    """
    _require_key()
    last_err = None

    for attempt in range(MAX_RETRIES):
        stream = _retry(
            client.chat.completions.create,
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            top_p=1,
            max_tokens=max_tokens,
            stream=True,
        )

        started = False
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                # reasoning_content 는 추론 과정이라 화면에 내보내지 않는다.
                if getattr(delta, "content", None):
                    started = True
                    yield delta.content
            return
        except APIError as e:
            # 이미 일부를 화면에 내보냈으면 이어 붙일 수 없으니 그대로 올린다.
            if started:
                raise
            last_err = e
            wait = BACKOFF_BASE ** attempt
            print(f"  [스트림 재시도 {attempt + 1}/{MAX_RETRIES}] {e} → {wait:.0f}초 대기")
            time.sleep(wait)

    raise last_err


def embed(texts, input_type="passage"):
    """texts: list[str] -> list[list[float]]

    input_type 은 NIM 임베딩 전용 파라미터라 extra_body 로 넘긴다.
    적재 문서는 "passage", 검색 질의는 "query" 를 쓴다.
    """
    _require_key()
    res = _retry(
        client.embeddings.create,
        model=EMBEDDING_MODEL_NAME,
        input=texts,
        encoding_format="float",
        extra_body={"input_type": input_type, "truncate": "END"},
    )

    return [d.embedding for d in sorted(res.data, key=lambda d: d.index)]


def embed_one(text, input_type="passage"):
    return embed([text], input_type)[0]
