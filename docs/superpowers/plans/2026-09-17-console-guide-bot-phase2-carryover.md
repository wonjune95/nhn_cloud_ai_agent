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
