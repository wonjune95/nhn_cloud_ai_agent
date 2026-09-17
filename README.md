# NHN Cloud 콘솔 안내 챗봇

docs.nhncloud.com 의 콘솔 사용 가이드를 수집해 pgvector 에 임베딩으로 적재하고,
Streamlit UI에서 질문에 대해 근거 문서를 찾아 답하는 RAG 챗봇이다. 크게 세 단계로
나뉜다: (1) `crawlling/` 이 문서를 HTML로 받아 `manifest.json`에 기록하고,
(2) `app/ingest.py` 가 그 HTML을 섹션 단위로 쪼개(`app/chunker.py`) 임베딩해
`documents` 테이블에 넣고, (3) `app/ui.py`(Streamlit)가 검색·응답을 담당한다.

## 사전 준비

- Python 3.12
- Docker Desktop (pgvector 컨테이너 실행용)
- Chrome (크롤러가 Selenium + webdriver-manager 로 headless 구동)

## 설치

```
pip install -r requirements-dev.txt        # pytest
pip install -r crawlling/requirements.txt  # selenium, bs4, requests 등
pip install -r app/requirements.txt        # streamlit, langchain, psycopg2 등
```

## .env

저장소 루트에 `.env` 를 만들고 다음 키를 채운다 (값은 커밋하지 않는다):

```
NVIDIA_API_KEY=
NVIDIA_LLM_MODEL=
NVIDIA_EMBEDDING_MODEL=
```

## 파이프라인 실행 순서

```
docker compose up -d db

python crawlling/crawl.py                          # 전체 수집 (이미 ok 인 페이지는 건너뜀)
python crawlling/crawl.py --categories Network,Bill # 카테고리만
python crawlling/crawl.py --changed                 # 본문이 바뀐 것만 다시 저장

cd app
DB_HOST=localhost python ingest.py                  # 바뀐 문서만 적재
DB_HOST=localhost python ingest.py --rebuild         # 스키마/임베딩 모델이 바뀌었을 때 전부 다시
DB_HOST=localhost python ingest.py --docs-dir ../nhn_cloud_docs_pilot

python aliases.py                                    # 서비스 별칭 사전 초안 생성
python -m streamlit run ui.py
```

## 호스트 vs 컨테이너

`app/db.py` 의 `DB_HOST` 기본값은 `db`(compose 서비스명)다. 윈도우 호스트에서
직접 `ingest.py`/`ui.py` 를 돌릴 때는 `DB_HOST=localhost` 로 덮어써야 한다.
`docker-compose.yaml` 의 `app` 컨테이너 안에서는 `DB_HOST=db` 가 그대로 맞고,
문서 폴더는 `/docs` 에 읽기 전용으로 마운트돼 있다(`DOCS_DIR=/docs`).

## 옛 스키마 / manifest 없는 폴더

`documents` 테이블이 예전 형식(예: `content_hash` 컬럼 없음)이거나 임베딩
차원이 바뀌었으면 `ingest.py` 가 멈추고 `--rebuild` 를 요구한다. 한 번
`--rebuild` 로 다시 적재하면 된다. 또한 `--docs-dir` 에 `manifest.json` 이
없으면(옛 크롤러로 받았거나 크롤러가 아닌 다른 방법으로 만든 폴더일 수 있음)
기본적으로 적재를 거절한다 — 확인 후에도 넣으려면 `--allow-no-manifest` 를 붙인다.

## 테스트

```
python -m pytest                                          # 단위 테스트 (DB/API 불필요)
DB_HOST=localhost python -m pytest -m integration app/tests/test_ingest_db.py
```

통합 테스트는 `.env` 의 `NVIDIA_API_KEY` 와, `docker compose up -d db` 로 띄운
pgvector 가 필요하다.
