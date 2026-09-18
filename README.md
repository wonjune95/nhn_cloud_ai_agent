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
python crawlling/crawl.py --changed                 # 전부 다시 받되 본문 해시가 바뀐 것만 저장
python crawlling/crawl.py --force                   # manifest 를 무시하고 전부 다시 저장

cd app
DB_HOST=localhost python ingest.py                  # 바뀐 문서만 적재. --limit 없이 전체를 돌면 디스크에서 사라진 문서의 행도 함께 지운다
DB_HOST=localhost python ingest.py --rebuild         # 스키마/임베딩 모델이 바뀌었을 때 전부 다시
DB_HOST=localhost python ingest.py --docs-dir ../nhn_cloud_docs_pilot
DB_HOST=localhost python ingest.py --limit 20        # 앞 N개 문서만 (시범용). 이때는 정리(prune)를 하지 않는다
DB_HOST=localhost python ingest.py --allow-no-manifest --docs-dir ../어떤_폴더  # manifest.json 없는 폴더도 적재(옛 형식 주의)

python aliases.py                                    # documents 의 서비스 목록으로 별칭 사전(services.generated.yaml) 재생성
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
pgvector 가 필요하다. 실데이터 DB(`ragdb`)를 지우지 않도록 `ragdb_test` 데이터베이스를
따로 만들어 쓴다(`app/tests/test_ingest_db.py` 의 `test_db` 픽스처가 없으면 만들고
`db.DB_NAME` 을 그쪽으로 돌린다) — 통합 테스트를 실행해도 `ragdb` 의 실데이터는
그대로 남는다.

## 코퍼스 현황

측정일 2026-09-17, 전체 재수집 기준(`nhn_cloud_docs/`).

- 문서 850개, 29개 카테고리 폴더
- manifest 상태: `ok` 724 / `no_breadcrumb` 126 / `error` 0
- `콘솔 사용 가이드` 문서 104개 (1단계 36개 → 크게 증가)
- 이미지 2,574장, 전체 용량 535MB
- 브레드크럼 h2 가 없는 페이지(Quickstarts, NHN Cloud 공통 문서, 일부 서비스 개요 등,
  위 `no_breadcrumb` 126개)는 URL에서 유추한 서비스 폴더에 저장한다. 예:
  `Security/Cloud Access/개요.html`
- 서로 다른 URL 두 개가 같은 경로로 매핑될 때(버전별 API 가이드가 브레드크럼을 공유하는
  경우) 파일명 끝에 URL slug 를 붙여 구분한다. 예:
  `Database/RDS for MySQL/API 가이드 (api-guide-v3.0).html`
- manifest 는 `.tmp` 파일에 먼저 쓰고 원본으로 교체(rename)한다. 실패하면 재시도하고,
  그래도 안 되면 파일을 직접 덮어쓴다(in-place fallback) — Windows/OneDrive 의 파일
  잠금 때문에 rename 이 실패하는 경우를 대비한 것이다.

적재 결과(전체 재적재, Kubernetes Job 으로 실행): 850개 문서 → 25,757개 청크,
167개 서비스. `doc_type` 분포: `other` 12,495 / `api` 10,478 / `console` 2,015 /
`overview` 769. 벡터 인덱스는 `documents_embedding_hnsw`
(`(embedding::halfvec(2048)) halfvec_cosine_ops`). 별칭 사전은 158개 서비스 /
566개 별칭으로 재생성됐다(`app/services.generated.yaml`, `python aliases.py`).

## 검색 동작

1. **의도 판정** (`app/intent.py`): `console | general`, LLM 없이 규칙으로 정한다.
   `intent.CONSOLE_HINTS`(콘솔 절차 신호: "어디서", "만들", "설정" 등)가 있으면
   `console`, 다만 `intent.GENERAL_OVERRIDES`(요금·API·차이 등)가 있으면 `general` 로
   되돌린다.
2. **서비스 추정**: `app/services.generated.yaml`(자동, `aliases.py` 로 재생성) 과
   `app/services.yaml`(수동)을 합친 별칭 사전에서 질문에 포함된 별칭을 찾는다. 영문
   별칭은 단어 경계로만 매칭하고("nat" 이 "nato" 안에서 안 잡히게), 여러 별칭이 걸리면
   가장 긴 별칭을 우선한다. 별칭을 더 넣으려면 `app/services.yaml` 에
   `카테고리/서비스:` 를 키로 별칭 목록을 추가하면 된다(수동 사전이 자동 생성분을
   덮어쓴다). 문서 제목은 '콘솔 사용 가이드'·'API 가이드'처럼 서비스와 무관한 일반
   명칭이라 스펙의 '문서 제목 기반 별칭'은 쓸모가 없어 수동 한글 별칭
   (`services.yaml`)으로 대신한다.
3. **하이브리드 검색** (`app/rag.py`): 벡터 20건 + 한글 2-gram BM25(`tokenize_ko.py`)
   20건을 후보로 가져와 `combine_scores` 로 점수를 보정한다 — 벡터·BM25 둘 다 등장
   ×1.2, 콘솔 의도이고 `doc_type == console` ×1.5, 서비스 일치 ×1.3 — 상위 12건을
   남긴다.
4. **리랭킹**: 추론(thinking)을 끈 LLM 호출 한 번으로 12건을 한꺼번에 채점한다
   (문서당 900자, 0~10 점수와 "이 문서만으로 답 가능한가"(1/0) 근거 판정을 함께
   받는다). 점수 상위 5건(`TOP_K`)만 답변 프롬프트에 넣는다.
5. 질문당 LLM 호출은 총 2회(리랭킹 1 + 답변 1)다.

## 지연 측정

```
cd app && DB_HOST=localhost python ../eval/bench_latency.py
```

동시 질문 1/3/6개를 실제 파이프라인(검색 → 리랭킹 → 답변)에 넣어 벽시계 시간,
성공/실패, 재시도 횟수, 단계별(검색/리랭킹/답변) 시간을 잰다. 아래는 전체 코퍼스,
UI pod 안(NVIDIA NIM 무료 티어, 리랭킹은 추론 끔)에서 측정한 결과다.

```
동시 | 벽시계 | 성공 | 재시도 | 최대   | 평균
   1 |  12.8초 | 1/1 |    0회 | 12.8초 | 12.8초
   3 |  28.1초 | 3/3 |    0회 | 28.1초 | 16.7초
   6 |  14.5초 | 6/6 |    0회 | 14.5초 | 11.9초
```

동시 1개일 때 단계별: 검색 2.1초 / 리랭킹 1.1초 / 답변 9.6초.

1단계(리랭킹에 추론을 켜둔 채, 구 코퍼스) 기준: 동시 1개 총 34.7초(리랭킹 19.5초),
동시 6개 평균 59.4초. 전체 출력은
`.superpowers/sdd/2026-09-17-console-guide-bot-phase2a-search/bench_cluster.txt` 에
있다(저장소에는 커밋하지 않는다).

## 쿠버네티스 배포

- `app/Dockerfile` 로 UI/ingest 공용 이미지를 빌드한다.
- `deploy/k8s/nhn-docs-bot.yaml`: `nhn-docs-bot` 네임스페이스에 pgvector
  StatefulSet(+ NFS PVC), 문서용 PVC, UI Deployment/Service 를 정의한다.
- `deploy/k8s/ingest-job.yaml`: 전체 재적재를 Kubernetes Job 으로 실행한다.
- 시크릿 `llm`(`NVIDIA_API_KEY`)과 `regcred`(이미지 레지스트리 인증)는 매니페스트
  밖에서 미리 만들어 둔다.
- UI Deployment 는 `enableServiceLinks: false` 를 준다 — 이름이 `db` 인 Service 가
  있으면 쿠버네티스가 `DB_PORT=tcp://…` 환경변수를 자동 주입해 앱이 쓰는 `DB_PORT`
  와 충돌하기 때문이다.
- 아직 공개 ingress 는 없다. UI 는 배스천을 통해 포트포워딩으로 접속한다:
  ```
  ssh POC-BASTION -L 8501:127.0.0.1:18501 "kubectl -n nhn-docs-bot port-forward svc/ui 18501:8501"
  ```
