# NHN Cloud 콘솔 안내 챗봇

docs.nhncloud.com 의 콘솔 사용 가이드를 수집해 pgvector 에 임베딩으로 적재하고,
Streamlit UI에서 질문에 대해 근거 문서를 찾아 답하는 RAG 챗봇이다. 크게 세 단계로
나뉜다: (1) `crawlling/` 이 문서를 HTML로 받아 `manifest.json`에 기록하고,
(2) `app/ingest.py` 가 그 HTML을 섹션 단위로 쪼개(`app/chunker.py`) 임베딩해
`documents` 테이블에 넣고, (3) `app/ui.py`(Streamlit)가 검색·응답을 담당한다.

## 사전 준비

- Python 3.12
- Docker Desktop (pgvector 컨테이너 실행용)
- Chrome (크롤러가 Selenium + webdriver-manager 로 headless 구동) — 로컬/윈도우에서
  직접 돌릴 때만 필요하다. 크롤러 컨테이너(`crawlling/Dockerfile`)는 Chromium을
  이미지에 함께 설치하므로 클러스터(CronJob)에서 돌릴 때는 따로 준비할 게 없다.

## 설치

```
pip install -r requirements-dev.txt        # pytest
pip install -r crawlling/requirements.txt  # selenium, bs4, requests 등
pip install -r app/requirements.txt        # streamlit, openai, psycopg2 등 (버전 고정)
```

## .env

저장소 루트에 `.env` 를 만들고 다음 키를 채운다 (값은 커밋하지 않는다):

```
NVIDIA_API_KEY=
NVIDIA_BASE_URL=            # 비우면 https://integrate.api.nvidia.com/v1
NVIDIA_LLM_MODEL=
NVIDIA_EMBEDDING_MODEL=
```

`app/llm.py` 는 키 없이도 import 된다(테스트가 이 모듈을 거쳐 들어온다). 키 확인은
`chat`/`chat_stream`/`embed` 를 실제로 부를 때 한다.

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
DB_HOST=localhost python -m pytest -m integration app/tests/test_qlog_db.py
DB_HOST=localhost python -m pytest -m integration app/tests/test_admin_stats_db.py
```

통합 테스트는 `.env` 의 `NVIDIA_API_KEY` 와, `docker compose up -d db` 로 띄운
pgvector 가 필요하다. 실데이터 DB(`ragdb`)를 지우지 않도록 `ragdb_test` 데이터베이스를
따로 만들어 쓴다(`app/tests/conftest.py` 의 `test_db` 픽스처가 없으면 만들고
`db.DB_NAME` 을 그쪽으로 돌린다) — 통합 테스트를 실행해도 `ragdb` 의 실데이터는
그대로 남는다. `app/tests/test_qlog_db.py`(질문 로그 기록·조회)와
`app/tests/test_admin_stats_db.py`(관리자 지표 집계 SQL)도 같은 `test_db` 픽스처를
쓰는 통합 테스트다.

`.env` 를 셸에 실제로 로드하지 않으면 `test_ingest_db.py` 등에서 `NVIDIA_API_KEY`
가 비어 실패한다 — Git Bash 에서는 `set -a && . ./.env && set +a` 로 먼저 값을
환경변수로 내보낸 뒤 pytest 를 돌린다(파이썬이 `.env` 를 자동으로 읽어오지 않는다).

`app/tests/test_ui_apptest.py` 는 Streamlit 의 `AppTest` 로 챗/관리자 페이지를
구동하는 단위 테스트다(DB 없이 DB 접근 함수를 가짜로 바꿔 넣는다) — `python -m pytest`
에 포함되며 DB 나 API 키가 필요 없다.

## 코퍼스 현황

측정일 2026-09-17, 전체 재수집 기준(`nhn_cloud_docs/`).

- 문서 850개, 29개 카테고리 폴더. 크롤러의 GNB 탐색이 찾아낸 문서 링크가 전부
  850개다 — 계획서의 "1,000쪽 이상"은 추정치였고, 850이 실제 전수다(누락이 아니다).
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

25,757개 청크 중 본문이 서로 다른 것은 24,675개다 — 문서가 다른데 본문이 똑같은
청크가 1,051개 그룹(전체의 4.2%)이나 된다(공통 안내 문단, 같은 서비스의 v2/v3 API
가이드 등). 그래서 검색 결과의 출처·서비스는 본문을 키로 한 사전이 아니라 후보
객체(`rag.Candidate`)가 직접 들고 다닌다. 본문을 키로 쓰면 같은 본문을 가진 마지막
문서가 출처와 서비스 부스트를 가로챈다.

청킹 로직이나 프롬프트에 넣는 청크 형식(`app/chunker.py`)이 바뀌면
`python ingest.py --rebuild` 로 전부 다시 적재해야 한다. 증분 적재는 **HTML 해시만**
비교하므로, HTML 이 그대로면 청킹이 바뀌어도 건너뛴다.

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
   남긴다. BM25 인덱스는 프로세스당 한 번 메모리에 만든다: 2-gram 토큰 273만 개,
   약 130MB, 질의당 30~80ms. 검색 단계에 걸리는 2.1초는 BM25 가 아니라 질의 임베딩
   왕복(NIM 호출 1회)이 대부분이다.
4. **리랭킹**: 추론(thinking)을 끈 LLM 호출 한 번으로 12건을 한꺼번에 채점한다
   (문서당 900자, 0~10 점수와 "이 문서만으로 답 가능한가"(1/0) 근거 판정을 함께
   받는다). 점수 상위 5건(`TOP_K`)만 답변 프롬프트에 넣는다.
5. 질문당 LLM 호출은 총 2회(리랭킹 1 + 답변 1)다.

## UI

`app/ui.py` 는 `st.navigation` 으로 두 페이지를 띄운다: 챗(`/`, `app/chat_page.py`)과
관리자(`/admin`, `app/admin_page.py`). 관리자 페이지는 별도 인증이 없다 — 링크를 아는
사람은 누구나 지표를 볼 수 있다.

| 구분 | 내용 |
| --- | --- |
| 답변 형식(콘솔 절차 질문) | 첫 줄에 메뉴 경로, 이어서 번호가 매겨진 단계. 각 단계 끝에 해당 스크린샷을 인라인으로 붙인다(`{{img:N}}` 마커). 문서에 스크린샷이 실제로 있을 때만 붙이고, 없으면 생략한다. |
| 사이드바 | 서비스 선택(`자동` 또는 목록에서 고정 선택), "참고 문서 수" 슬라이더(리랭킹 후 프롬프트에 넣을 문서 수). |
| 피드백 | 답변마다 👍/👎 버튼이 있고 누르면 `questions.feedback` 에 기록된다. |
| 질문 로그 | 질문 1건당 `questions` 테이블에 1행이 쌓인다(세션 id·질문·답변·검색 질의·근거·피드백 등, 사용자를 식별할 수 있는 정보는 남기지 않는다). 새로 추가된 컬럼(`questions.session_id`/`answer`/`retrieval_query`, `documents.ingested_at`)은 `db.migrate` 가 UI 기동 시점에 멱등하게 추가한다 — 재적재 없이 스키마만 갱신된다. |
| 스크린샷 경로 | `DOCS_DIR` 환경변수(기본값: 저장소 루트의 `nhn_cloud_docs`, 컨테이너 안에서는 `/docs`) 아래에서 `Candidate.images` 의 상대 경로를 읽어 보여준다. |

관리자 페이지(`/admin`)는 기간(7일/30일/전체)을 고를 수 있고, 전체 지표·서비스별 표,
최근 👎/미확인/응답 30초 초과 질문 목록, 인덱스 상태를 보여준다.

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
- 시크릿 세 개는 매니페스트 밖에서 미리 만들어 둔다(git 에 넣지 않는다):
  `db`(`POSTGRES_USER`/`POSTGRES_PASSWORD` — pgvector 와 앱이 함께 쓴다),
  `llm`(`NVIDIA_API_KEY`), `regcred`(이미지 레지스트리 인증).
- `pgdata` PVC 는 NFS(`sc-nas-cicd`) 위에 있다. NFS 위의 Postgres 는 잠금·fsync
  의미 차이로 알려진 위험이 있어, 블록 StorageClass 가 생기면 옮겨야 한다.
  지금은 코퍼스 재적재로 복구할 수 있어 감수한 선택이다(매니페스트에 주석).
- UI Deployment 는 `enableServiceLinks: false` 를 준다 — 이름이 `db` 인 Service 가
  있으면 쿠버네티스가 `DB_PORT=tcp://…` 환경변수를 자동 주입해 앱이 쓰는 `DB_PORT`
  와 충돌하기 때문이다.
- 공개 접속: `https://nhn-docs-bot.180-210-89-135.nip.io` (`deploy/k8s/httproute.yaml`, Traefik
  Gateway 를 통한 HTTPRoute). 인증은 없다 — 링크를 아는 사람은 누구나 챗·관리자 페이지에
  접속할 수 있다. 인증을 붙이는 방법(Traefik `basicAuth` Middleware)은 `httproute.yaml`
  주석에 있다.
- 이미지는 두 개다: 앱 `nhn-docs-bot`(`app/Dockerfile`, 비root uid 1000 — UI·ingest·refresh
  CronJob 의 ingest 단계가 공용)와 크롤러 `nhn-docs-crawler`(`crawlling/Dockerfile`, 빌드
  컨텍스트는 저장소 루트). 태그는 이번 단계에서 `2b2-<git 짧은 해시>` 형식을 쓴다
  (스펙의 `2b-` 접두사를 단계별로 일반화한 것이다).
- 배포 순서: 이미지 빌드·푸시 → `kubectl apply -f deploy/k8s/rbac.yaml -f
  deploy/k8s/httproute.yaml -f deploy/k8s/refresh-cronjob.yaml`(CronJob 은 apply 전에 이미지
  태그를 sed 로 바꾼다) → `kubectl -n nhn-docs-bot set image deploy/ui ui=<이미지>:<태그>` →
  `kubectl -n nhn-docs-bot rollout status deploy/ui`. UI 이미지를 올릴 때 refresh CronJob 도
  같은 태그로 다시 apply 한다 — CronJob 의 ingest 컨테이너가 UI 와 같은 청커를 써야 한다.

### 운영 런북

**시크릿 만들기** (네임스페이스를 만든 직후 한 번):

```
kubectl -n nhn-docs-bot create secret generic db \
    --from-literal=POSTGRES_USER=devops \
    --from-literal=POSTGRES_PASSWORD='<강한 비밀번호>'
kubectl -n nhn-docs-bot create secret generic llm --from-literal=NVIDIA_API_KEY=...
kubectl -n nhn-docs-bot create secret docker-registry regcred \
    --docker-server=harbor.114-110-181-178.nip.io --docker-username=... --docker-password=...
```

`db` 시크릿은 pgvector(`POSTGRES_USER`/`POSTGRES_PASSWORD`)와 앱
(`DB_USER`/`DB_PASSWORD`)이 같은 값을 공유한다. 비밀번호를 나중에 바꾸려면 시크릿만
고쳐서는 안 되고 DB 안에서 `ALTER ROLE` 도 함께 해야 한다 — pgvector 는 이미
초기화된 `PGDATA` 의 계정을 그대로 쓰기 때문이다.

**문서 코퍼스(`docs` PVC) 채우기.** 크롤러는 클러스터 안에서 돌리지 않는다. 윈도우에서
받은 `nhn_cloud_docs/` 를 헬퍼 파드를 통해 밀어 넣는다:

```
kubectl -n nhn-docs-bot run docs-helper --image=busybox --restart=Never \
    --overrides='{"spec":{"containers":[{"name":"docs-helper","image":"busybox","command":["sleep","3600"],
    "volumeMounts":[{"name":"docs","mountPath":"/docs"}]}],
    "volumes":[{"name":"docs","persistentVolumeClaim":{"claimName":"docs"}}]}}'
kubectl -n nhn-docs-bot wait --for=condition=Ready pod/docs-helper

tar -C nhn_cloud_docs -cf - . | kubectl -n nhn-docs-bot exec -i docs-helper -- tar -C /docs -xf -

kubectl -n nhn-docs-bot exec docs-helper -- sh -c 'ls /docs | head; ls /docs/manifest.json'
kubectl -n nhn-docs-bot delete pod docs-helper
```

**적재와 반영.** 적재 Job 을 돌린 뒤 UI 를 다시 띄워야 한다 — UI 는 BM25 인덱스를
프로세스 시작 때 한 번만 만들기 때문에, 재시작 없이는 새 문서가 검색되지 않는다:

```
kubectl -n nhn-docs-bot delete job ingest --ignore-not-found
kubectl -n nhn-docs-bot apply -f deploy/k8s/ingest-job.yaml
kubectl -n nhn-docs-bot logs -f job/ingest

kubectl -n nhn-docs-bot rollout restart deploy/ui
kubectl -n nhn-docs-bot rollout status deploy/ui
```

청킹 로직이나 프롬프트 형식이 바뀌었으면 Job 의 `args` 에 `"--rebuild"` 를 넣는다
(증분 적재는 HTML 해시만 본다). UI Deployment 는 `strategy: Recreate` 라 옛 파드가
먼저 내려간 뒤 새 파드가 올라온다(인덱싱이 겹치지 않게). 전체 재적재를 수동으로
다시 돌려야 하면 `deploy/k8s/ingest-job.yaml` 의 `args` 에 `--rebuild` 를 넣고 위
Job 을 그대로 재실행한다.

**정기 재수집** (`deploy/k8s/refresh-cronjob.yaml`, CronJob `refresh`). 매월 1일
03:00 KST 에 자동으로 돈다: initContainer `fix-perms`(NFS 는 `fsGroup` 을 적용하지
않아 uid 1000 이 쓸 수 있게 `chown` 한 번 맞춘다, 실패해도 계속 진행) → `crawl`
(`--changed`, 바뀐 페이지만 저장) → `ingest`(증분 적재) 순서로 실행되고, 마지막
컨테이너 `restart` 가 `kubectl rollout restart deploy/ui` 로 UI 를 재시작한다(RBAC은
`deploy/k8s/rbac.yaml` 의 `ServiceAccount refresh` — Deployment `get`/`patch` 만 허용).
UI 재시작 중 새벽 30~60초 정도 챗이 끊긴다. 수동 실행과 로그 확인:

```
kubectl -n nhn-docs-bot create job --from=cronjob/refresh refresh-manual-$(date +%m%d)
kubectl -n nhn-docs-bot logs -f job/refresh-manual-<월일> -c fix-perms
kubectl -n nhn-docs-bot logs -f job/refresh-manual-<월일> -c crawl
kubectl -n nhn-docs-bot logs -f job/refresh-manual-<월일> -c ingest
kubectl -n nhn-docs-bot logs -f job/refresh-manual-<월일> -c restart
```

크롤은 850페이지라 1시간 넘게 걸릴 수 있다. `crawl` 컨테이너가 실패하면
`backoffLimit: 0`/`restartPolicy: Never` 라 Job 은 그대로 Failed 로 남고 자동
재시도는 없다 — UI 는 옛 코퍼스로 계속 서비스된다(무영향). `ingest` 단계는 문서
일부가 실패해도 exit 0(전체 실패거나 DB/API 오류일 때만 실패로 끝난다). 전체
재적재가 필요하면 `deploy/k8s/ingest-job.yaml` 에 `--rebuild` 를 넣어 별도로 돌린다
(CronJob 의 `ingest` 는 증분만 한다).

**API 키 교체.** NVIDIA API 키를 바꿀 때는 시크릿을 갈아 끼우고 UI 를 재시작한다:

```
kubectl -n nhn-docs-bot create secret generic llm --from-literal=NVIDIA_API_KEY=<새 키> \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl -n nhn-docs-bot rollout restart deploy/ui
```

키 값은 저장소나 문서 어디에도 평문으로 남기지 않는다.

**주 1회 점검 체크리스트** (관리자 페이지 `/admin`):

| 확인 항목 | 조치 |
| --- | --- |
| 👎 피드백 상위 서비스 | 해당 서비스 문서·별칭(`app/services.yaml`) 보강 |
| 미확인(서비스 추정 실패) 질문 | 별칭 누락 확인 후 추가 |
| 응답 30초 초과 질문 | NVIDIA NIM 상태(무료 티어 레이트리밋 등) 확인 |

**평가.** 30문항 회귀 평가는 UI 파드 안에서 돌린다(로컬 검색·리랭킹·답변 경로를
그대로 쓰기 때문에 파드 밖에서 돌리면 DB/네트워크 설정을 따로 맞춰야 한다):

```
kubectl -n nhn-docs-bot cp eval <ui-pod>:/app/
kubectl -n nhn-docs-bot exec <ui-pod> -- python -u eval/run_eval.py
```

(`cp` 대상은 `/app/` 이다 — `/app/eval/` 로 주면 `/app/eval/eval/` 이 된다. `run_eval.py` 가
파드 배치에서도 `rag` 를 찾도록 `sys.path` 를 스스로 채우므로 `PYTHONPATH` 는 필요 없다.)

기준(모두 만족해야 통과, 미달이면 exit 1): hit@5 ≥ 80%, 메뉴 경로 정확도 ≥ 90%,
스크린샷 마커 정확도 ≥ 80%, 범위 밖 질문 거부 5/5, 응답 시간 중앙값 ≤ 15초·최댓값
≤ 30초, 오류 0건. 미달 항목은
`docs/superpowers/plans/2026-09-17-console-guide-bot-phase2-carryover.md` 의 튜닝
후보를 참고해 조정한 뒤 재측정한다.

#### 평가 결과

2026-09-18, 클러스터 UI 파드(전체 코퍼스, NVIDIA NIM 무료 티어)에서 `eval/run_eval.py` 실행.
1차는 `2b2-f5ad77a`, 2차는 `2b2-ceea5b7` 이미지로 돌렸다.

| 항목 | 1차 (튜닝 전) | 2차 (튜닝 후) | 기준 | 판정 |
|---|---|---|---|---|
| 검색 적중 (상위 5) | 25/25 | 24/25 (96%) | ≥ 80% | 통과 |
| 콘솔 메뉴 경로 | 9/20 (45%) | 19/20 (95%) | ≥ 90% | 통과 |
| 콘솔 스크린샷 | 9/20 (45%) | 14/20 (70%) | ≥ 80% | 미달 |
| 문서 밖 고정 문구 | 4/5 | 4/5 | 5/5 | 미달 |
| 지연 중앙값 / 최대 | 22.2초 / 61.7초 | 11.3초 / 42.4초 | ≤ 15초 / ≤ 30초 | 중앙값 통과, 최대 미달 |
| 예외 | 0 | 0 | 0 | 통과 |

메뉴 경로 95% 는 보이는 것만큼 강한 수치가 아니다: `expect_menu` 는 서비스 이름이고 첫 줄은 이제
문서 머리말(`서비스: 카테고리/서비스`)에서 만들어지므로, 사실상 올바른 문서를 찾았는지(검색 적중)를
다시 재는 셈이다. 그보다 아래 단계의 탭·메뉴 경로가 맞는지는 채점하지 않는다.

튜닝 1회(커밋 `ceea5b7`): 콘솔 답변 첫 줄을 문서 머리말의 카테고리/서비스로 만들고(`콘솔 > Network > DNS Plus`),
이미지가 없는 후보에 같은 문서·같은 최상위 섹션의 이웃 청크 스크린샷을 최대 3장 빌려온다(`rag.enrich_images`).

미달 항목의 원인과 후속:
- 스크린샷 70%: 미달 6문항 중 VPC·Object Storage 는 원문에 스크린샷이 0장이라 구조적으로 불가. 나머지(Image 복제,
  Load Balancer 리스너, Push APNS, Instance 키페어)는 해당 절에 이미지가 없거나 리랭킹 편차. 문항을 이미지 있는 절로
  다듬거나 이웃 범위를 문서 전체로 넓히는 것을 검토.
- 문서 밖 4/5: "AWS EC2 인스턴스 요금" 이 NHN 인스턴스 문서로 답변됨(리랭킹이 근거 있음으로 판정). 리랭킹 프롬프트에
  "다른 클라우드 제품 질문은 근거 없음" 규칙 추가 검토.
- 최대 지연 42초: NIM 무료 티어 503 재시도. 1차 실행에서는 재시도 30회, 2차는 2회 — 시간대에 따라 크게 흔들린다.
- 1차→2차에서 1번 문항 적중이 O→X 로 바뀐 것은 리랭킹 근거 판정 편차(grounded=false 로 답변 생략). 같은 질문을
  두 번 돌려 편차를 재는 것을 후속으로 둔다.

**백업은 없다.** `pgdata`(문서 벡터), `questions`(질문 로그·피드백) 모두 별도
백업을 두지 않는다. 문서 벡터는 재적재로 복구되지만, 질문 로그와 피드백은
재적재로 되살아나지 않는다 — 사라지면 그걸로 끝이다.
