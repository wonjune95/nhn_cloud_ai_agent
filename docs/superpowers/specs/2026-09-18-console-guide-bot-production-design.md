# NHN Cloud 콘솔 안내 챗봇 — 내부 운영 서비스화 설계 (2단계-B)

작성일: 2026-09-18. 기반 스펙: `2026-09-17-console-guide-bot-design.md` (이하 "기본 스펙").
이 문서는 기본 스펙을 대체하지 않는다. 바뀐 전제와 추가 요구만 적고, 나머지는 기본 스펙의 절 번호로 참조한다.

## 1. 목적과 결정

목표: 2단계-A까지 만든 검색·적재 위에 기본 스펙 5절(답변·UI)·6-3(로그·피드백·재수집)을 구현하고,
NKS 클러스터에서 사람 손 없이 굴러가는 내부 서비스로 만든다.

사용자와 합의한 결정:

| 항목 | 결정 |
|---|---|
| 접속 | Traefik Gateway HTTPRoute `https://nhn-docs-bot.180-210-89-135.nip.io` (이미 존재). 인증 없음, 나중에 추가 |
| LLM | NVIDIA NIM 무료 티어 유지. 노출된 키는 재발급해 Secret 교체 |
| 운영 가시성 | 앱 안 관리자 페이지만. Prometheus/Grafana 연동·알림·DB 백업은 범위 밖 |
| 계획 분할 | 2B-1 "제품"(답변·UI·로그·관리자) → 2B-2 "운영"(크롤러 이미지·CronJob·매니페스트·평가·런북). 브랜치·PR 각각 |

## 2. 전제 변경과 전체 구조

| 항목 | 기본 스펙 | 이번 |
|---|---|---|
| 실행 환경 | 사내망 리눅스 1대, docker compose | NKS `nd-wj-cicd-cluster`, 네임스페이스 `nhn-docs-bot` |
| 접속 | `http://<서버>:8501` | HTTPRoute (Gateway `traefik/traefik-gateway`, 와일드카드 TLS) |
| 인증 | 없음 | 없음. Traefik `Middleware`(basicAuth) + HTTPRoute `ExtensionRef` 필터 자리만 주석으로 예약 |
| 재수집 | 서버에서 `refresh.sh` 수동 | 클러스터 안 CronJob. 크롤러 전용 이미지(chromium 내장) |
| 운영 가시성 | 주 1회 SQL | 앱 내 관리자 페이지 |

구성 요소(네임스페이스 `nhn-docs-bot`):

- `ui` Deployment — Streamlit `st.navigation` 두 페이지: 챗(기본), 관리자. 이미지 `nhn-docs-bot`.
- `pgvector` StatefulSet — `documents`, `questions`. 변경 없음(컬럼 추가만).
- `docs` PVC(RWX, NFS) — CronJob의 크롤러가 쓰고 UI·ingest가 읽는다.
- `refresh` CronJob — 월 1회. initContainer `crawl` → initContainer `ingest` → 컨테이너 `restart`.
- `ingest` Job — 수동 전체 재적재용. 유지.
- HTTPRoute `nhn-docs-route` — 클러스터에 있는 것을 `deploy/k8s/httproute.yaml`로 편입.

질문 1건의 흐름: 질문 → 의도·서비스 판정(드롭다운 선택이 있으면 그것) → 하이브리드 검색 → 리랭킹(grounded) →
의도별 프롬프트 → 스트리밍 답변 → `{{img:N}}`을 스크린샷으로 치환 → `questions` 1행 INSERT → 👍/👎 시 `feedback` UPDATE.

## 3. 답변 생성과 스크린샷 (2B-1)

기본 스펙 5-1·5-2를 따른다. 현재 코드 기준 구체화:

### 3-1. 프롬프트 입력

- `rag.build_prompt(question, cands: list[Candidate], history) -> tuple[str, dict[int, ImageRef]]`.
  문자열 목록을 받던 시그니처는 제거한다.
- 문서 블록 헤더는 2A 형식 유지: `[문서 i] 서비스 · 문서명 · 섹션 · 출처URL`.
- 각 블록 본문 뒤에 그 청크의 이미지를 전체 순번으로 붙인다: `[그림 N] <caption 앞 60자>`.
  N은 후보 순서대로 1부터 연속. `missing=True`인 이미지는 순번을 주지 않고 프롬프트에도 넣지 않는다.
- 반환하는 `image_map`은 `{N: ImageRef(path, caption)}`. `path`는 `DOCS_DIR` 기준 상대 경로.

### 3-2. 의도별 시스템 프롬프트

- `console`: ① 첫 줄에 문서에 적힌 콘솔 메뉴 경로(`콘솔 > Network > VPC > Subnet`). 문서에 없으면
  `메뉴 경로: 문서에 명시되지 않음`. ② 번호 목록 단계. 스크린샷이 있는 단계 끝에 `{{img:N}}`.
  ③ 문서에 "주의/참고"가 있을 때만 `주의` 항목. 그림 번호는 문서 블록에 나온 것만 쓴다.
- `general`: 현재 프롬프트 유지.
- 근거 제한·대화 맥락 해석 문구는 두 프롬프트에 공통.

### 3-3. grounded 처리

- `False`: LLM을 호출하지 않는다. 고정 문구 `제공된 문서에서 확인되지 않습니다.` + 추정 서비스(있으면). 출처 미표시.
  `questions.grounded = false`, `answer`는 고정 문구.
- `None`(리랭킹 실패): 검색 순서로 답변하되 출처 위에 `관련도 확인 실패` 캡션.
- `True`: 정상.

### 3-4. 렌더링

- `ui.render_answer(text, image_map)`: 정규식 `\{\{img:(\d+)\}\}`로 나눠 텍스트 조각은 `st.markdown`,
  마커는 `st.image(DOCS_DIR/path, caption=caption[:60])`. 범위 밖 번호는 제거하고 stderr에 남긴다.
  파일이 없으면 그 그림만 생략하고 stderr에 남긴다.
- 스트리밍 중에는 `st.empty()` 자리에 원문(마커 포함)을 그대로 보이고, 완료 즉시 같은 자리에 치환본을 그린다.
- 세션 메시지에 `image_map`을 함께 저장하고, 대화 기록을 다시 그릴 때도 `render_answer`를 쓴다.

### 3-5. 출처

- 문서명 칩을 `source_url` 링크로. 본문 미리보기 대신 `section_path`.
- `rag.rerank(query, docs: list[str])` 문자열 래퍼 제거. UI는 `rerank_candidates`를 직접 쓴다.

## 4. UI 변경, 질문 로그, 피드백, 관리자 페이지 (2B-1)

### 4-1. 챗 화면 (기본 스펙 5-3)

- 사이드바: "검색 후보 수" 슬라이더 제거(20 고정). "참고 문서 수" 슬라이더는 유지.
  **서비스 선택** 드롭다운 추가: 기본 `자동`, 항목은 `ALIASES` 키 정렬. 선택하면 자동 판정·`last_service` 대신 그 서비스를 쓴다.
- 답변 상단에 태그 `<서비스> · <콘솔 절차|일반>`. 서비스 미상이면 `서비스 미상`.
- 예시 질문 4개: `VPC에 서브넷을 추가하는 방법`, `로드 밸런서를 생성하는 절차`, `플로팅 IP를 인스턴스에 연결하는 방법`,
  `Object Storage에 컨테이너를 만드는 방법`.
- 답변 하단 👍 / 👎 버튼. 누르면 `feedback` UPDATE 후 버튼 자리에 `의견 감사합니다`. 실패하면 `저장 실패`.

### 4-2. `questions` 스키마 추가

`init_schema`에서 `ALTER TABLE questions ADD COLUMN IF NOT EXISTS …`. 재적재 없음.

| 컬럼 | 형 | 용도 |
|---|---|---|
| `session_id` | TEXT | 브라우저 세션당 랜덤 UUID. 사용자 수 추정. 신원 아님 |
| `answer` | TEXT | 👎 검토용 답변 전문 |
| `retrieval_query` | TEXT | 대화 맥락 합성 질의 |

`documents`에도 `ingested_at TIMESTAMPTZ DEFAULT now()`를 ADD COLUMN. 기존 행은 NULL.

기록 규칙: 답변 완료 또는 실패 직후 1행 INSERT(`RETURNING id` → 메시지에 저장).
`sources`는 `[{source_path, section_path, source_url, service}]`. `error`는 예외 문자열(성공 시 NULL).
INSERT/UPDATE 실패는 화면에 영향 없이 stderr. 사용자 식별 정보는 저장하지 않는다.

### 4-3. 관리자 페이지

`st.navigation([챗, 관리자])`. 모두 `questions` SQL 집계. 기간 선택 `7일 / 30일 / 전체`.

- 상단 지표: 질문 수, 세션 수(`count(distinct session_id)`), 응답 시간 중앙값·최대(ms→초), LLM 오류율(`error is not null`),
  미확인 비율(`grounded = false`), 👍 수, 👎 수.
- 서비스별 표: 질문 수 · 👎 수 · 미확인 수. 👎 수 내림차순.
- 목록 셋(각 최근 20건): 👎 질문(시각·질문·서비스·answer 앞 200자), 미확인 질문(시각·질문·서비스),
  30초 초과 질문(시각·질문·elapsed).
- 인덱스 상태: `documents` 청크 수, `count(distinct service)`, `max(ingested_at)`.
- 인증이 없으므로 누구나 본다. 인증을 붙일 때 이 페이지부터 막는다.

## 5. 운영 자동화와 배포 (2B-2)

### 5-1. 크롤러 이미지 `crawlling/Dockerfile`

- `python:3.12-slim` + apt `chromium chromium-driver` + `crawlling/requirements.txt`(selenium, requests, bs4 등 현재 의존성).
- `build_driver()`: 환경변수 `CHROME_BIN`·`CHROMEDRIVER`가 있으면 `Options.binary_location`과 `Service(CHROMEDRIVER)`를 쓰고,
  없으면 지금처럼 webdriver-manager(로컬 개발).
- Harbor `harbor.114-110-181-178.nip.io/nnd/nhn-docs-crawler:<tag>`.

### 5-2. refresh CronJob `deploy/k8s/refresh-cronjob.yaml`

- `schedule: "0 3 1 * *"`, `timeZone: Asia/Seoul`, `concurrencyPolicy: Forbid`, `backoffLimit: 0`,
  `successfulJobsHistoryLimit: 3`, `failedJobsHistoryLimit: 3`.
- 파드: `enableServiceLinks: false`, `imagePullSecrets: regcred`, docs PVC를 쓰기 가능으로 마운트.
  1. initContainer `crawl`(크롤러 이미지): `python crawl.py --changed --save-dir /docs`. 요청 1Gi / 제한 3Gi 메모리, CPU 500m/2.
  2. initContainer `ingest`(앱 이미지): `python -u ingest.py --docs-dir /docs`. 환경변수는 `ingest-job.yaml`과 동일.
  3. 컨테이너 `restart`(`bitnami/kubectl`): `kubectl -n nhn-docs-bot rollout restart deploy/ui`.
- `deploy/k8s/rbac.yaml`: ServiceAccount `refresh`, Role(`apps/deployments` `get,patch`), RoleBinding.
- 수동 실행: `kubectl -n nhn-docs-bot create job --from=cronjob/refresh refresh-manual-<월일>`.

### 5-3. 적재 종료 코드

- 문서 일부 실패: 마지막에 실패 목록을 출력하고 exit 0.
- exit 1은 DB 연결 실패, 임베딩 API 인증 실패, manifest 없음, 처리 대상 0건(전체 실행에서 문서를 하나도 못 읽음)일 때만.

### 5-4. 앱 Dockerfile 보강

- `useradd -u 1000 app`, `USER app`. `HEALTHCHECK`는 `/_stcore/health`를 urllib으로 확인.
- k8s: `securityContext.runAsNonRoot: true`, `runAsUser: 1000`. `readOnlyRootFilesystem`은 Streamlit 캐시 때문에 쓰지 않는다.
- docs PVC 파일 소유권: 크롤러도 uid 1000으로 실행해 UI(읽기 전용)와 충돌하지 않게 한다.

### 5-5. 매니페스트와 배포 절차

- `deploy/k8s/`: `nhn-docs-bot.yaml`(기존), `ingest-job.yaml`(기존), `httproute.yaml`(신규), `refresh-cronjob.yaml`(신규), `rbac.yaml`(신규).
- `httproute.yaml`에 인증 추가 예시(Traefik `Middleware` basicAuth + `filters: [{type: ExtensionRef, …}]`)를 주석으로 둔다.
- 이미지 태그 `2b-<git 짧은 해시>`. 배포는 `kubectl set image` 또는 매니페스트 sed. CI 파이프라인은 범위 밖.
- 시크릿(`llm`, `db`, `regcred`)은 계속 수동. 키 교체는 `create secret --dry-run=client -o yaml | kubectl apply -f -`
  → `kubectl rollout restart deploy/ui`. 키 값은 저장소·문서 어디에도 쓰지 않는다.

### 5-6. 평가 30문항

- `eval/questions.yaml`: 항목 `{id, question, kind: console|general|outside, expect_path, expect_menu}`.
  콘솔 20(카테고리 고루), 일반 5, 문서 밖 5. `expect_path`는 `카테고리/서비스/문서명.html`, `expect_menu`는 콘솔 문항만.
- `eval/run_eval.py`: 파드 안에서 실행(`kubectl exec`). 문항마다 검색 → 리랭킹 → 답변을 실제 경로로 돌리고 측정:
  상위 5 적중(`expect_path`가 후보 `source_path`에 포함), 메뉴 경로 포함(`expect_menu`가 답변 첫 줄에 포함),
  스크린샷 1장 이상(`{{img:N}}`이 유효 범위로 1개 이상), 문서 밖 문항 고정 문구, 지연(중앙값·최대), 예외 수.
  결과를 markdown 표로 stdout에 출력하고 README에 붙인다.
- 기준: 기본 스펙 8-2. 미달 시 이관 문서의 튜닝 후보(`"api"` 오버라이드 예외, BM25 정규화)로 1회 튜닝 후 재측정.

### 5-7. 런북 (README 운영 절)

접속 URL, 관리자 페이지 주 1회 체크리스트(👎 상위 서비스 → 문서·별칭 보강, 미확인 질문 → 별칭 누락 확인, 30초 초과 → NIM 상태),
수동 재수집, 전체 재적재, 키 교체, 배포, 인증 추가 방법, "DB 백업 없음 — 질문 로그는 재적재로 복구되지 않음" 명시.

## 6. 오류 처리 (기본 스펙 7절에 추가)

| 단계 | 실패 | 처리 |
|---|---|---|
| 답변 | 콘솔 의도인데 메뉴 경로가 문서에 없음 | 첫 줄 `메뉴 경로: 문서에 명시되지 않음`, 단계는 그대로 |
| 답변 | 이미지 파일이 PVC에 없음(`missing` 아님) | 그 그림만 생략, stderr |
| 로그 | `questions` INSERT/UPDATE 실패 | 화면 정상, stderr. 피드백 버튼은 `저장 실패` |
| 관리자 | DB 연결 실패 | 배너 + 빈 페이지 |
| 재수집 | `crawl` 실패 | 파드 Failed, ingest 미실행, UI 무영향. 다음 달 또는 수동 |
| 재수집 | `ingest` 일부 문서 실패 | 경고 목록, exit 0, UI 재시작 진행 |
| 재수집 | `restart` 권한 오류 | 파드 Failed. 적재 결과는 DB에 남고 다음 UI 재시작 때 반영 |

## 7. 테스트와 완료 기준

### 7-1. 자동 테스트

- 단위(`app/tests/`): 마커 분할·범위 밖 제거·파일 없음 생략(`render_answer`의 순수 분할 함수), `build_prompt`의 그림 순번 연속성·missing 제외·의도별 프롬프트 선택, 관리자 집계 SQL 문자열 생성.
- 통합(`ragdb_test`, `-m integration`): `questions` INSERT/feedback UPDATE, ADD COLUMN 멱등성, 관리자 지표 집계(행 5개 넣고 검증).
- AppTest 1건: 서비스 드롭다운 선택이 검색 인자로 전달되고 👍 버튼이 UPDATE를 호출.
- 크롤러: `build_driver`의 환경변수 분기 단위 테스트(드라이버 생성은 mock).

### 7-2. 완료 기준

- 2B-1: 테스트 전부 통과. 클러스터 배포 후 콘솔 질문 3건에서 메뉴 경로·스크린샷·서비스 태그·👍/👎·관리자 지표가 화면에 보임.
- 2B-2: CronJob 수동 실행이 crawl → ingest → restart를 완주. 평가 30문항이 기본 스펙 8-2 기준 통과
  (적중 ≥80%, 메뉴 경로 ≥90%, 스크린샷 ≥80%, 문서 밖 5/5, 중앙값 ≤15초, 화면 오류 0). 미달 시 튜닝 1회 후 결과를 README에 기록.

## 8. 범위 밖 (이번 버전)

- 인증·사용자별 이력 (다음 단계: Traefik basic auth 또는 앱 로그인)
- Prometheus/Grafana 연동, 알림
- DB 백업 (질문 로그 보존은 후속 결정)
- CI 파이프라인, 블록 스토리지 이전, LLM 유료 전환
