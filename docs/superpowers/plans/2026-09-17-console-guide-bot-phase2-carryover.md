# 1단계(데이터 파이프라인) → 2단계 이관 항목

1단계 구현(`feature/data-pipeline`, fa7fdfe..3f5ef8e) 리뷰에서 나온 항목 중 2단계 계획에 반영해야 할 것.
2단계 계획을 쓸 때 이 목록을 그대로 입력으로 쓴다.

## 전체 적재 전에 처리 (재임베딩 비용이 없는 시점)

- **중첩 표/코드 블록** — `li`/`blockquote` 안의 `<table>`은 `table_to_text`(헤더: 값)를, `<pre>`는 `[코드]` 형식을 잃고 평문으로 평탄화된다. 파일럿 60문서 중 3문서(표)·1문서(pre 7개)에서 실재. `app/chunker.py`의 조상 소비 방식에서 table/pre 만 예외로 방문하도록 수정.
- **표 블록 길이** — 1,500자 상한이 단일 블록에는 적용되지 않아 파일럿 최대 4,543자(39행 표). 표를 행 단위로 나누고 헤더 행을 반복; 헤더 줄·마커 줄 길이도 `length`에 계상.
- **`Image.missing`** — 크롤러의 `data-missing="true"`를 청커가 버린다. `Image`에 `missing: bool` 추가(스펙 7절 "해당 스크린샷만 생략"의 계약).
- **`has_breadcrumb` 전달** — `chunk_html`이 "첫 h2에 `>`가 있으면 브레드크럼" 휴리스틱으로 판단. `no_breadcrumb` 문서에서 진짜 제목을 삭제할 수 있으므로 manifest 값을 인자로 넘긴다.
- **HNSW 2000차원 상한** — 임베딩 2048차원이라 벡터 인덱스 없이 순차 스캔 중. 제공자 확정 후 `halfvec` 표현식 인덱스(재적재 불필요) 또는 차원 변경.
- **중복 청크 측정** — 구 ingest의 바이트 동일 청크 제거가 사라짐. `rag.doc_meta`가 content 키라 동일 청크는 메타데이터를 잃는다. 전체 적재 후 중복률을 재고 필요하면 문서 내 dedup.

## refresh(월 1회 재수집) 설계에 포함

- **삭제/이동 문서 정리** — ingest는 디스크에서 사라진 `source_path` 행을 지우지 않고, `--changed`에서 브레드크럼이 바뀐 문서는 옛 파일이 고아로 남는다. 전체 실행(`--limit` 없음)에서만 `DELETE ... WHERE source_path <> ALL(seen)`.
- **재수집 실패 시 ok 항목 보존** — 실패하면 기존 ok 항목을 error로 덮어써 마지막 정상 해시가 사라진다. 이전 상태를 유지하고 error 메모만 추가.
- **manifest 손상 JSON** — `Manifest.load()`가 손상 파일에서 예외로 죽어 재개 상태 전체를 잃는다. 경고 후 빈 manifest 로 시작.
- **경로 충돌 경고** — 두 URL이 같은 브레드크럼 경로를 내면 한쪽이 덮어쓴다. `Manifest.by_path()`(현재 미사용)로 크롤러에서 경고.
- **별칭 사전** — `aliases.py`를 refresh 스크립트에서 체인. 전체 적재 후 `services.generated.yaml` 재생성(현재 파일은 파일럿 20개 서비스뿐). 문서 제목 기반 별칭은 실코퍼스 제목을 보고 설계(스펙 3-2 문구는 이 시점에 충족).

## 그 외

- `init_schema`의 `RuntimeError` 경로에서 cursor 미닫힘. README에 `NVIDIA_BASE_URL` 미기재(기본값 있음).
- 구 수집본 `nhn_cloud_docs/`(431개 구 형식 파일)는 전체 재수집 시 삭제 또는 `nhn_cloud_docs_old/`로 이름 변경. ingest는 `manifest.json` 없는 폴더를 거부하므로 실수로 적재되지는 않는다.
- LLM/임베딩 제공자 확정(스펙 6-1)은 전체 재수집 전에.

---

# 2단계-A 완료 후 추가 이관 항목 (2026-09-18, 최종 리뷰 기준)

2단계-A(`feature/phase2a-search`)에서 처리한 것: 중첩 표/코드, 표 행 분할, `Image.missing`, `has_breadcrumb`, halfvec 인덱스, 삭제 문서 정리, 재수집 실패 시 ok 항목 보존, manifest 손상 복구, 경로 충돌 방지, 중복 청크 오귀속(후보에 메타 직접 전달), 별칭 사전 재생성·한글 시드. 아래는 2단계-B 로 넘긴다.

## 2단계-B 설계에 반영
- **`Candidate`가 `section_path`·`images`·`source_url`을 들고 온다** (스펙 4-4 완료). 답변·스크린샷 렌더링·`questions.sources` 로그는 이 객체를 그대로 쓴다. `rerank(query, docs: list[str])` 문자열 래퍼는 UI 전환 후 제거.
- **DB `pgdata`가 NFS(`sc-nas-cicd`)에 있음** — Postgres에 권장되지 않음. 블록 스토리지 StorageClass가 생기면 이전(재적재 ~15분).
- **`ingest.py`는 문서 하나라도 실패하면 exit 1** → Job이 Failed로 표시되고 backoff 재시도를 소모. 부분 실패는 경고로 두고 exit 0, 실패 목록만 남기는 편이 운영에 맞음.
- **`--changed` 재수집 시 `unchanged` 페이지에도 manifest 저장** — 쓰기 횟수 축소.
- **Dockerfile**: root 실행, `HEALTHCHECK` 없음.
- **`init_schema`의 RuntimeError 경로에서 cursor 미닫힘**.

## 검색 품질 튜닝 후보 (평가 30문항 결과를 보고)
- `GENERAL_OVERRIDES`의 `"api"`가 서비스명(API Gateway)에 반응해 콘솔 의도를 놓침 — 별칭에 걸린 구간은 오버라이드에서 제외.
- BM25 점수를 배치 최댓값으로 정규화해 BM25 1위가 항상 1.0 — 벡터 유사도(0.4~0.7)보다 항상 앞섬. 스케일 재조정 검토.
- 표 안 표는 `table_to_text`가 평탄화; 분할된 표의 2번째 조각부터 caption 줄만 반복되고 열 이름은 반복되지 않음.
- 텍스트 없는 표 셀의 이미지 캡션이 표 전체 텍스트(216건이 200자 초과, 표시엔 60자만 씀).
- 단일 줄이 1,500자를 넘는 청크 16건(최대 10,839자) — 임베딩은 `truncate: END`, 리랭킹은 900자만 봄.
- 한글 별칭은 부분 문자열 매칭이라 일반어 별칭 추가 시 오탐 주의(일반어 4개는 제거함).

## 측정치 (2026-09-18, 클러스터 전체 코퍼스)
- 코퍼스 850문서/25,757청크/167서비스, 중복 청크 4.2%(교차 문서 그룹 1,051).
- BM25: 2.73M 토큰, 메모리 ~130MB, 질의당 30~80ms. 검색 단계 2.1초의 대부분은 질의 임베딩 API 왕복 → `embed_query` LRU 캐시 후보.
- 지연: 동시 1 → 12.8초(검색 2.1/리랭킹 1.1/답변 9.6), 동시 6 평균 11.9초, 재시도 0.
