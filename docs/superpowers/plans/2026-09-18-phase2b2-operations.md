# 2단계-B-2 "운영" 구현 계획 — 크롤러 이미지·refresh CronJob·Dockerfile 보강·매니페스트·평가 30문항·런북

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사람 손 없이 굴러가는 내부 서비스로 만든다 — 크롤러가 클러스터 안에서 월 1회 돌고(CronJob: crawl → ingest → UI 재시작), 컨테이너가 비root로 뜨며, 매니페스트가 저장소에 전부 있고, 평가 30문항으로 품질을 숫자로 확인하며, README 런북으로 운영한다.

**Architecture:** 크롤러는 chromium 이 든 별도 이미지(`nhn-docs-crawler`)로, `build_driver()`가 환경변수 `CHROME_BIN`/`CHROMEDRIVER`를 보면 로컬 드라이버를 쓴다. refresh CronJob 은 initContainer 둘(crawl, ingest) + 본 컨테이너(kubectl rollout restart)로 순서를 보장한다. ingest 는 일부 문서 실패를 exit 0 으로 바꿔 Job 이 쓸데없이 Failed 가 되지 않게 한다. 평가는 순수 채점 모듈(`eval/scoring.py`) + 파드 안에서 실제 파이프라인을 도는 러너(`eval/run_eval.py`)로 나눈다.

**Tech Stack:** Python 3.12, Selenium 4 + Debian chromium/chromium-driver, Kubernetes CronJob/RBAC/HTTPRoute(Gateway API, Traefik), Docker(비root), pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-09-18-console-guide-bot-production-design.md` 5절·6절·7절 (기본 스펙 `2026-09-17-console-guide-bot-design.md` 8-2 평가 기준).

## Global Constraints

- 브랜치 `feature/phase2b2` (2B-1 브랜치 `feature/phase2b` 위에서 시작). 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` (Windows 에서는 메시지를 임시 파일에 쓰고 `git commit -F`).
- 테스트는 저장소 루트에서 `python -m pytest -q` (pytest.ini `testpaths = app/tests crawlling/tests`, 기본 `-m "not integration"`). 루트 `conftest.py` 가 `app/` 과 루트를 `sys.path` 에 넣는다. **실데이터 DB `ragdb` 에 `--rebuild`/DELETE 금지.**
- 크롤러 이미지: `python:3.12-slim` + apt `chromium chromium-driver` + `crawlling/requirements.txt`. 환경변수 `CHROME_BIN`·`CHROMEDRIVER` 가 있으면 `Options.binary_location` 과 `Service(CHROMEDRIVER)`, 없으면 webdriver-manager (스펙 5-1). Harbor `harbor.114-110-181-178.nip.io/nnd/nhn-docs-crawler:<tag>`.
- CronJob: `schedule: "0 3 1 * *"`, `timeZone: Asia/Seoul`, `concurrencyPolicy: Forbid`, `backoffLimit: 0`, `successfulJobsHistoryLimit: 3`, `failedJobsHistoryLimit: 3`, `enableServiceLinks: false`, `imagePullSecrets: regcred`. initContainer `crawl`(메모리 요청 1Gi/제한 3Gi, CPU 500m/2) → initContainer `ingest` → 컨테이너 `restart`(`bitnami/kubectl`, `kubectl -n nhn-docs-bot rollout restart deploy/ui`). ServiceAccount `refresh` + Role(`apps` `deployments` `get,patch`) + RoleBinding (스펙 5-2).
- ingest 종료 코드: 문서 일부 실패 → 실패 목록 출력 후 exit 0. exit 1 은 DB 연결 실패, 임베딩 API 인증 실패, manifest 없음, 전체 실행에서 처리 대상 0건일 때만 (스펙 5-3).
- 앱 Dockerfile: `useradd -u 1000 app`, `USER app`, `HEALTHCHECK` 가 `/_stcore/health` 를 urllib 으로 확인. k8s `securityContext.runAsNonRoot: true`, `runAsUser: 1000`; `readOnlyRootFilesystem` 은 쓰지 않는다. 크롤러도 uid 1000 (스펙 5-4).
- 매니페스트 `deploy/k8s/`: `httproute.yaml`(인증 예시 주석 포함), `refresh-cronjob.yaml`, `rbac.yaml` 신규; 기존 두 파일 유지. 시크릿은 수동, 키 값은 어디에도 쓰지 않는다 (스펙 5-5).
- 평가: `eval/questions.yaml` 항목 `{id, question, kind: console|general|outside, expect_path, expect_menu}`; 콘솔 20·일반 5·문서 밖 5. 측정: 상위 5 적중, 메뉴 경로 포함(첫 줄), 스크린샷 1장 이상(유효 마커), 문서 밖 고정 문구, 지연 중앙값·최대, 예외 수. 기준: 적중 ≥80%(24/30), 콘솔 메뉴 경로 ≥90%(18/20), 콘솔 스크린샷 ≥80%(16/20), 문서 밖 5/5, 중앙값 ≤15초·최대 ≤30초, 예외 0 (스펙 5-6, 기본 스펙 8-2).
- 파일 UTF-8, 한국어 주석·문구는 기존 코드 톤.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `crawlling/crawl.py` (수정) | `build_driver()` 환경변수 분기 |
| `crawlling/Dockerfile` (신규) | 크롤러 이미지 |
| `crawlling/tests/test_build_driver.py` (신규) | 분기 단위 테스트(드라이버 생성은 mock) |
| `app/ingest.py` (수정) | `run()` 종료 코드 |
| `app/tests/test_ingest_exit.py` (신규) | DB 없이 `run()` 종료 코드 검증(전부 monkeypatch) |
| `app/Dockerfile` (수정) | 비root, HEALTHCHECK |
| `deploy/k8s/nhn-docs-bot.yaml`, `ingest-job.yaml` (수정) | securityContext |
| `deploy/k8s/httproute.yaml`, `rbac.yaml`, `refresh-cronjob.yaml` (신규) | 라우트·권한·재수집 |
| `app/tests/test_k8s_manifests.py` (신규) | 매니페스트 파싱·핵심 필드 검사 |
| `eval/questions.yaml` (신규) | 30문항 |
| `eval/scoring.py` (신규) | 순수 채점 함수 |
| `eval/run_eval.py` (신규) | 파드 안 실행 러너, markdown 표 출력 |
| `app/tests/test_eval_scoring.py` (신규) | 채점 단위 테스트 |
| `README.md` (수정) | 운영 런북·평가 결과 |

---

### Task 1: 크롤러 `build_driver` 환경변수 분기와 크롤러 이미지

**Files:**
- Modify: `crawlling/crawl.py:46-50` (`build_driver`)
- Create: `crawlling/Dockerfile`
- Test: `crawlling/tests/test_build_driver.py`

**Interfaces:**
- Consumes: 기존 `build_driver() -> webdriver.Chrome`, `Options`, `Service`, `ChromeDriverManager`.
- Produces: `build_driver()` 가 `CHROME_BIN`/`CHROMEDRIVER` 를 읽음. 환경변수 `CRAWL_DRIVER_FLAGS` 는 만들지 않는다(YAGNI).

- [ ] **Step 1: 실패하는 테스트 작성** — `crawlling/tests/test_build_driver.py`

```python
"""build_driver() 가 컨테이너(CHROME_BIN/CHROMEDRIVER)와 로컬(webdriver-manager)을 구분하는지 검증한다.
실제 브라우저는 띄우지 않는다 — webdriver.Chrome 과 ChromeDriverManager 를 가짜로 바꾼다."""

from crawlling import crawl


class FakeChrome:
    def __init__(self, service=None, options=None):
        self.service = service
        self.options = options


class FakeService:
    def __init__(self, path=None):
        self.path = path


class FakeManager:
    called = False

    def install(self):
        FakeManager.called = True
        return "/managed/chromedriver"


def _patch(monkeypatch):
    FakeManager.called = False
    monkeypatch.setattr(crawl.webdriver, "Chrome", FakeChrome)
    monkeypatch.setattr(crawl, "Service", FakeService)
    monkeypatch.setattr(crawl, "ChromeDriverManager", FakeManager)


def test_uses_env_binaries_when_set(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setenv("CHROME_BIN", "/usr/bin/chromium")
    monkeypatch.setenv("CHROMEDRIVER", "/usr/bin/chromedriver")

    d = crawl.build_driver()

    assert d.service.path == "/usr/bin/chromedriver"
    assert d.options.binary_location == "/usr/bin/chromium"
    assert FakeManager.called is False
    assert "--headless=new" in d.options.arguments and "--no-sandbox" in d.options.arguments


def test_falls_back_to_webdriver_manager(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.delenv("CHROMEDRIVER", raising=False)

    d = crawl.build_driver()

    assert d.service.path == "/managed/chromedriver"
    assert FakeManager.called is True
    assert not d.options.binary_location


def test_both_env_vars_required_for_container_mode(monkeypatch):
    """둘 중 하나만 있으면 로컬 모드로 본다 — 반쯤 설정된 컨테이너에서 엉뚱한 드라이버를 쓰지 않게."""
    _patch(monkeypatch)
    monkeypatch.setenv("CHROME_BIN", "/usr/bin/chromium")
    monkeypatch.delenv("CHROMEDRIVER", raising=False)

    d = crawl.build_driver()

    assert d.service.path == "/managed/chromedriver"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest crawlling/tests/test_build_driver.py -q`
Expected: FAIL — `test_uses_env_binaries_when_set` 에서 `service.path == "/managed/chromedriver"` (환경변수 무시).

- [ ] **Step 3: 구현** — `crawlling/crawl.py` 의 `build_driver` 교체

```python
def build_driver() -> webdriver.Chrome:
    """headless Chrome. 컨테이너에서는 CHROME_BIN/CHROMEDRIVER 가 가리키는 바이너리를,
    로컬에서는 webdriver-manager 가 받은 드라이버를 쓴다 (둘 다 있을 때만 컨테이너 모드)."""
    opts = Options()
    for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
        opts.add_argument(flag)

    chrome_bin = os.getenv("CHROME_BIN")
    chromedriver = os.getenv("CHROMEDRIVER")
    if chrome_bin and chromedriver:
        opts.binary_location = chrome_bin
        service = Service(chromedriver)
    else:
        service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest crawlling/tests/test_build_driver.py -q`
Expected: 3 passed

- [ ] **Step 5: 크롤러 Dockerfile** — `crawlling/Dockerfile`

```dockerfile
# NHN Cloud 문서 크롤러 이미지 — refresh CronJob 의 initContainer 로 돈다.
# 빌드 컨텍스트는 저장소 루트다:  docker build -f crawlling/Dockerfile -t <img> .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver

# chromium + chromedriver 는 Debian 패키지로 버전이 맞춰져 온다. 폰트는 한글 렌더링용.
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium chromium-driver fonts-nanum \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY crawlling/requirements.txt crawlling/requirements.txt
RUN pip install -r crawlling/requirements.txt

COPY crawlling/ crawlling/

# UI 파드와 같은 uid 로 /docs 에 쓴다 (스펙 5-4).
RUN useradd -u 1000 -m app
USER app

ENTRYPOINT ["python", "-u", "crawlling/crawl.py"]
CMD ["--changed", "--save-dir", "/docs"]
```

`crawlling/crawl.py` 는 `from crawlling import paths, manifest` 처럼 패키지 import 를 쓴다면 `WORKDIR /work` 에서 `python crawlling/crawl.py` 로 실행할 때 `sys.path` 에 `/work` 가 있어야 한다. `crawl.py` 상단의 import 방식을 확인해서(현재 `from crawlling.paths import …` 형태인지, `from paths import …` 형태인지) 맞지 않으면 `PYTHONPATH=/work` 를 `ENV` 에 추가한다. 로컬에서 `python crawlling/crawl.py` 가 동작하는 방식과 같아야 한다.

- [ ] **Step 6: 이미지 빌드 확인 (로컬 Docker)**

Run: `docker build -f crawlling/Dockerfile -t nhn-docs-crawler:dev .` 그리고
`docker run --rm nhn-docs-crawler:dev --help`
Expected: 빌드 성공, `--help` 가 argparse 도움말을 출력. (`docker run --rm --entrypoint python nhn-docs-crawler:dev -c "import selenium; from crawlling import crawl; print(crawl.build_driver().capabilities['browserVersion'])"` 로 headless chromium 이 실제로 뜨는지도 확인하고 출력 버전을 보고에 적는다.)

- [ ] **Step 7: 커밋**

```bash
git add crawlling/crawl.py crawlling/Dockerfile crawlling/tests/test_build_driver.py
git commit -m "feat(crawler): 컨테이너용 드라이버 분기와 크롤러 이미지

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: ingest 종료 코드 — 일부 실패는 exit 0

**Files:**
- Modify: `app/ingest.py:132-197` (`run`)
- Test: `app/tests/test_ingest_exit.py`

**Interfaces:**
- Consumes: `ingest.run(argv) -> int`, 모듈 함수 `iter_documents`, `load_manifest`, `file_hash`, `existing_hash`, `prune_missing`, `ingest_document`; `run()` 안에서 `from db import get_conn, init_schema`, `from llm import EMBEDDING_MODEL_NAME, embed_one` 을 지연 import.
- Produces: 종료 코드 규칙 — 처리 대상 0건(전체 실행, `--limit` 없음, 문서 폴더에 HTML 0개)이면 1; 일부 문서 실패는 0 + 실패 목록; DB 연결/임베딩 API 실패는 예외가 `run()` 안에서 잡혀 메시지 + 1.

- [ ] **Step 1: 실패하는 테스트 작성** — `app/tests/test_ingest_exit.py`

```python
"""ingest.run() 의 종료 코드 (스펙 5-3). DB·API 없이 전부 가짜다."""
import json

import pytest

import ingest


HTML = "<section><h2>A &gt; B &gt; C</h2><h3>절</h3><p>본문</p></section>"


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "A" / "B").mkdir(parents=True)
    (tmp_path / "A" / "B" / "C.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "A" / "B" / "D.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
    return str(tmp_path)


class FakeCursor:
    def execute(self, *a, **k): pass
    def fetchone(self): return None
    def fetchall(self): return []
    def close(self): pass


class FakeConn:
    def cursor(self): return FakeCursor()
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


def _fake_backend(monkeypatch, ingest_document):
    import db, llm
    monkeypatch.setattr(db, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(db, "init_schema", lambda conn, dim, rebuild=False: None)
    monkeypatch.setattr(llm, "embed_one", lambda text, **k: [0.0] * 8)
    monkeypatch.setattr(ingest, "existing_hash", lambda cur, rel: None)
    monkeypatch.setattr(ingest, "prune_missing", lambda conn, seen: 0)
    monkeypatch.setattr(ingest, "ingest_document", ingest_document)


def test_partial_failure_exits_zero_and_lists_failures(docs, monkeypatch, capsys):
    def flaky(conn, docs_dir, rel, url, has_crumb):
        if rel.endswith("D.html"):
            raise RuntimeError("임베딩 429")
        return 3
    _fake_backend(monkeypatch, flaky)

    assert ingest.run(["--docs-dir", docs]) == 0
    out = capsys.readouterr().out
    assert "1개 실패" in out and "D.html" in out and "RuntimeError: 임베딩 429" in out


def test_all_ok_exits_zero(docs, monkeypatch):
    _fake_backend(monkeypatch, lambda *a: 2)
    assert ingest.run(["--docs-dir", docs]) == 0


def test_no_documents_exits_one(tmp_path, monkeypatch, capsys):
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    _fake_backend(monkeypatch, lambda *a: 1)
    assert ingest.run(["--docs-dir", str(tmp_path)]) == 1
    assert "처리할 문서가 없습니다" in capsys.readouterr().out


def test_db_connection_failure_exits_one(docs, monkeypatch, capsys):
    import db, llm
    monkeypatch.setattr(llm, "embed_one", lambda text, **k: [0.0] * 8)

    def boom():
        raise OSError("connection refused")
    monkeypatch.setattr(db, "get_conn", boom)

    assert ingest.run(["--docs-dir", docs]) == 1
    assert "DB 연결 실패" in capsys.readouterr().out


def test_embedding_auth_failure_exits_one(docs, monkeypatch, capsys):
    import db, llm
    monkeypatch.setattr(db, "get_conn", lambda: FakeConn())

    def boom(text, **k):
        raise RuntimeError("NVIDIA_API_KEY 가 설정되지 않았습니다")
    monkeypatch.setattr(llm, "embed_one", boom)

    assert ingest.run(["--docs-dir", docs]) == 1
    assert "임베딩 API 실패" in capsys.readouterr().out


def test_missing_manifest_still_exits_one(tmp_path):
    (tmp_path / "x.html").write_text(HTML, encoding="utf-8")
    assert ingest.run(["--docs-dir", str(tmp_path)]) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_ingest_exit.py -q`
Expected: `test_partial_failure_exits_zero_and_lists_failures` FAIL (현재 1 반환), `test_no_documents_exits_one`·`test_db_connection_failure_exits_one`·`test_embedding_auth_failure_exits_one` FAIL (예외 전파 또는 0 반환).

- [ ] **Step 3: 구현** — `app/ingest.py` `run()` 의 해당 부분을 아래처럼 바꾼다

```python
    from db import get_conn, init_schema
    from llm import EMBEDDING_MODEL_NAME, embed_one

    manifest = load_manifest(docs_dir)

    # 연결·인증 실패는 문서 실패와 다르다 — Job 이 Failed 로 남아야 사람이 본다 (스펙 5-3).
    try:
        conn = get_conn()
    except Exception as e:
        print(f"DB 연결 실패: {type(e).__name__}: {e}")
        return 1
    try:
        dim = len(embed_one("test"))
    except Exception as e:
        print(f"임베딩 API 실패: {type(e).__name__}: {e}")
        conn.close()
        return 1
    print(f"임베딩 모델: {EMBEDDING_MODEL_NAME} (dim={dim}) / 문서 폴더: {docs_dir}")
    init_schema(conn, dim, rebuild=args.rebuild)
```

루프는 그대로 두고, 루프 뒤를 이렇게 바꾼다:

```python
    pruned = 0
    if not args.limit:
        pruned = prune_missing(conn, seen)

    cur.close()
    conn.close()

    if not seen:
        print(f"처리할 문서가 없습니다: {docs_dir}")
        return 1

    print(f"완료: 문서 {done}개 적재, {skipped}개 건너뜀, {len(failed)}개 실패, {pruned}개 정리 (청크 {total_chunks}개)")
    for rel, err in failed:
        print(f"  - {rel}: {err}")
    # 일부 문서 실패는 경고로 둔다. 다음 실행이 미적재 문서만 다시 처리한다 (스펙 5-3).
    return 0
```

`run()` 의 docstring 또는 상단 주석에 종료 코드 규칙을 한 줄로 적는다: `# 종료 코드: 0 = 완료(일부 문서 실패 포함), 1 = 폴더/manifest 없음, DB 연결 실패, 임베딩 API 실패, 처리 대상 0건`.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_ingest_exit.py -q` 그리고 `python -m pytest -q`
Expected: 6 passed, 전체 PASS. (통합 `DB_HOST=localhost python -m pytest -m integration app/tests/test_ingest_db.py -q -p no:cacheprovider` 도 `.env` export 후 돌려 4 passed 를 확인한다 — `run()` 반환값을 `== 0` 으로 검사하는 테스트가 있다.)

- [ ] **Step 5: 커밋**

```bash
git add app/ingest.py app/tests/test_ingest_exit.py
git commit -m "fix(ingest): 일부 문서 실패는 exit 0, 연결·인증·대상 0건만 exit 1

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: 앱 Dockerfile 비root·HEALTHCHECK 와 k8s securityContext

**Files:**
- Modify: `app/Dockerfile`
- Modify: `deploy/k8s/nhn-docs-bot.yaml` (UI Deployment pod spec), `deploy/k8s/ingest-job.yaml` (Job pod spec)

**Interfaces:** 없음 (인프라).

- [ ] **Step 1: Dockerfile**

```dockerfile
# NHN Cloud 콘솔 안내 챗봇 — 앱 이미지 (UI · 적재 · 별칭 생성 공용)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# 비root 로 실행한다 (스펙 5-4). Streamlit 이 홈 아래에 설정·캐시를 쓰므로 홈이 있어야 한다.
RUN useradd -u 1000 -m app && chown -R app:app /app
USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

# 기동할 때 DB 의 서비스 목록으로 별칭 사전을 갱신한다(실패해도 이미지에 든 사전으로 뜬다).
CMD ["sh", "-c", "python aliases.py || true; exec python -m streamlit run ui.py --server.address 0.0.0.0 --server.port 8501"]
```

`aliases.py` 가 `app/services.generated.yaml` 에 쓰므로 `/app` 소유권을 `app` 에게 준다(위 `chown`).

- [ ] **Step 2: 로컬 빌드·기동 확인**

Run: `docker build -t nhn-docs-bot:dev app/` 그리고
`docker run --rm nhn-docs-bot:dev id` → `uid=1000(app)` 확인.
`docker run --rm -d --name bot-dev -e DB_HOST=host.docker.internal -e DB_PORT=5432 nhn-docs-bot:dev` 로 띄운 뒤 `sleep 25; docker inspect --format '{{.State.Health.Status}}' bot-dev` 가 `healthy` 또는 `starting` 이고 `docker logs bot-dev | tail -3` 에 스트림릿 기동 로그가 있는지 확인, `docker rm -f bot-dev`. (DB 연결 실패 화면이어도 `/_stcore/health` 는 200 이다.)

- [ ] **Step 3: k8s securityContext** — `deploy/k8s/nhn-docs-bot.yaml` UI Deployment 의 `template.spec` 에, `enableServiceLinks: false` 바로 아래:

```yaml
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
```

`deploy/k8s/ingest-job.yaml` 의 `template.spec` 에도 같은 블록을 넣는다. 파일 상단 주석에 한 줄 추가: `# 컨테이너는 uid 1000(app) 으로 뜬다. docs PVC 의 파일은 refresh CronJob 이 같은 uid 로 쓴다.`

- [ ] **Step 4: 매니페스트 문법 확인**

Run: `python -c "import yaml,sys; [print(d['kind'], d['metadata']['name']) for d in yaml.safe_load_all(open('deploy/k8s/nhn-docs-bot.yaml', encoding='utf-8')) if d]"`
Expected: Namespace/PVC×2/Service×2/StatefulSet/Deployment 가 나열되고 예외 없음.

- [ ] **Step 5: 커밋**

```bash
git add app/Dockerfile deploy/k8s/nhn-docs-bot.yaml deploy/k8s/ingest-job.yaml
git commit -m "chore(deploy): 앱 컨테이너 비root 실행과 HEALTHCHECK, 파드 securityContext

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 매니페스트 — HTTPRoute·RBAC·refresh CronJob + 파싱 테스트

**Files:**
- Create: `deploy/k8s/httproute.yaml`, `deploy/k8s/rbac.yaml`, `deploy/k8s/refresh-cronjob.yaml`
- Test: `app/tests/test_k8s_manifests.py`

**Interfaces:**
- Consumes: Task 1 크롤러 이미지(`ENTRYPOINT python crawlling/crawl.py`, uid 1000), Task 2 ingest 종료 코드, Task 3 securityContext 블록.
- Produces: CronJob `refresh`, ServiceAccount `refresh`, HTTPRoute `nhn-docs-route` — 모두 네임스페이스 `nhn-docs-bot`.

- [ ] **Step 1: 실패하는 테스트 작성** — `app/tests/test_k8s_manifests.py`

```python
"""deploy/k8s 매니페스트의 문법과 스펙 5-2·5-5 의 핵심 값. kubectl 없이 YAML 만 읽는다."""
import pathlib

import yaml

K8S = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "k8s"


def load(name):
    return [d for d in yaml.safe_load_all((K8S / name).read_text(encoding="utf-8")) if d]


def test_httproute_targets_ui_on_traefik_gateway():
    (route,) = load("httproute.yaml")
    assert route["kind"] == "HTTPRoute" and route["metadata"]["namespace"] == "nhn-docs-bot"
    assert route["spec"]["hostnames"] == ["nhn-docs-bot.180-210-89-135.nip.io"]
    parent = route["spec"]["parentRefs"][0]
    assert (parent["name"], parent["namespace"]) == ("traefik-gateway", "traefik")
    backend = route["spec"]["rules"][0]["backendRefs"][0]
    assert (backend["name"], backend["port"]) == ("ui", 8501)


def test_httproute_file_documents_auth_hook():
    text = (K8S / "httproute.yaml").read_text(encoding="utf-8")
    assert "basicAuth" in text and "ExtensionRef" in text


def test_rbac_lets_refresh_restart_ui_only():
    docs = {d["kind"]: d for d in load("rbac.yaml")}
    assert docs["ServiceAccount"]["metadata"]["name"] == "refresh"
    rule = docs["Role"]["rules"][0]
    assert rule["apiGroups"] == ["apps"] and rule["resources"] == ["deployments"]
    assert sorted(rule["verbs"]) == ["get", "patch"]
    assert docs["RoleBinding"]["subjects"][0]["name"] == "refresh"
    assert docs["RoleBinding"]["roleRef"]["name"] == docs["Role"]["metadata"]["name"]


def test_cronjob_schedule_and_ordering():
    (cj,) = load("refresh-cronjob.yaml")
    spec = cj["spec"]
    assert cj["kind"] == "CronJob" and cj["metadata"]["name"] == "refresh"
    assert spec["schedule"] == "0 3 1 * *" and spec["timeZone"] == "Asia/Seoul"
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["successfulJobsHistoryLimit"] == 3 and spec["failedJobsHistoryLimit"] == 3
    job = spec["jobTemplate"]["spec"]
    assert job["backoffLimit"] == 0
    pod = job["template"]["spec"]
    assert pod["enableServiceLinks"] is False
    assert pod["serviceAccountName"] == "refresh"
    assert pod["imagePullSecrets"] == [{"name": "regcred"}]
    assert [c["name"] for c in pod["initContainers"]] == ["fix-perms", "crawl", "ingest"]
    assert [c["name"] for c in pod["containers"]] == ["restart"]


def test_cronjob_crawl_and_ingest_details():
    (cj,) = load("refresh-cronjob.yaml")
    pod = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    inits = {c["name"]: c for c in pod["initContainers"]}
    crawl = inits["crawl"]
    assert "nhn-docs-crawler" in crawl["image"]
    assert crawl["args"] == ["--changed", "--save-dir", "/docs"]
    assert crawl["resources"]["requests"]["memory"] == "1Gi" and crawl["resources"]["limits"]["memory"] == "3Gi"
    assert crawl["resources"]["requests"]["cpu"] == "500m" and crawl["resources"]["limits"]["cpu"] == "2"
    mount = crawl["volumeMounts"][0]
    assert mount["mountPath"] == "/docs" and not mount.get("readOnly", False)
    ingest = inits["ingest"]
    assert "nhn-docs-bot" in ingest["image"]
    assert ingest["command"] == ["python", "-u", "ingest.py"] and ingest["args"] == ["--docs-dir", "/docs"]
    env = {e["name"]: e for e in ingest["env"]}
    assert env["DB_PORT"]["value"] == "5432"
    assert env["NVIDIA_API_KEY"]["valueFrom"]["secretKeyRef"] == {"name": "llm", "key": "NVIDIA_API_KEY"}
    restart = pod["containers"][0]
    assert "kubectl" in restart["image"]
    assert "rollout" in " ".join(restart.get("args") or restart.get("command"))
    assert pod["securityContext"]["runAsUser"] == 1000
    assert inits["fix-perms"]["securityContext"]["runAsUser"] == 0


def test_no_secret_values_in_manifests():
    for f in K8S.glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "nvapi-" not in text, f
        assert "kind: Secret" not in text, f
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_k8s_manifests.py -q`
Expected: FAIL — `FileNotFoundError: httproute.yaml`.

- [ ] **Step 3: `deploy/k8s/httproute.yaml`**

```yaml
# UI 를 Traefik Gateway 로 노출한다. (클러스터에 이미 있는 라우트를 저장소에 편입, 스펙 5-5)
#
# 인증을 붙일 때(스펙 8절 "다음 단계"): Traefik Middleware(basicAuth)를 만들고 아래 rules[0] 에
# filters 를 추가한다. 예:
#
#   apiVersion: traefik.io/v1alpha1
#   kind: Middleware
#   metadata: { name: bot-auth, namespace: nhn-docs-bot }
#   spec:
#     basicAuth:
#       secret: bot-auth-users     # htpasswd 형식의 'users' 키를 가진 Secret (수동 생성)
#
#   rules:
#     - matches: [{ path: { type: PathPrefix, value: / } }]
#       filters:
#         - type: ExtensionRef
#           extensionRef: { group: traefik.io, kind: Middleware, name: bot-auth }
#       backendRefs: [...]
#
# /admin 만 먼저 막으려면 matches 를 path /admin 으로 한 rule 을 위에 두고 filters 를 붙인다.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: nhn-docs-route
  namespace: nhn-docs-bot
spec:
  hostnames:
    - nhn-docs-bot.180-210-89-135.nip.io
  parentRefs:
    - name: traefik-gateway
      namespace: traefik
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: ui
          port: 8501
```

- [ ] **Step 4: `deploy/k8s/rbac.yaml`**

```yaml
# refresh CronJob 이 적재 뒤 UI 를 재시작(rollout restart = deployment patch)할 최소 권한.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: refresh
  namespace: nhn-docs-bot
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: refresh-restart-ui
  namespace: nhn-docs-bot
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: refresh-restart-ui
  namespace: nhn-docs-bot
subjects:
  - kind: ServiceAccount
    name: refresh
    namespace: nhn-docs-bot
roleRef:
  kind: Role
  name: refresh-restart-ui
  apiGroup: rbac.authorization.k8s.io
```

- [ ] **Step 5: `deploy/k8s/refresh-cronjob.yaml`**

```yaml
# 월 1회 재수집: crawl(--changed) → ingest(증분) → UI 재시작 (스펙 5-2).
#   수동 실행:  kubectl -n nhn-docs-bot create job --from=cronjob/refresh refresh-manual-$(date +%m%d)
#   진행 확인:  kubectl -n nhn-docs-bot logs job/<이름> -c crawl -f   (ingest, restart 도 같은 방식)
# 이미지 태그는 배포 때 sed 로 바꾼다.
apiVersion: batch/v1
kind: CronJob
metadata:
  name: refresh
  namespace: nhn-docs-bot
spec:
  schedule: "0 3 1 * *"
  timeZone: Asia/Seoul
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      # 크롤이 실패하면 다음 달 또는 수동 실행으로 — 자동 재시도는 사이트에 부담만 준다.
      backoffLimit: 0
      template:
        spec:
          restartPolicy: Never
          serviceAccountName: refresh
          enableServiceLinks: false
          imagePullSecrets:
            - name: regcred
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            runAsGroup: 1000
            fsGroup: 1000
          initContainers:
            # NFS 는 fsGroup 을 무시하므로 예전에 root 로 복사된 파일을 uid 1000 이 쓸 수 있게 한 번 맞춘다.
            - name: fix-perms
              image: busybox:1.36
              command: ["sh", "-c", "chown -R 1000:1000 /docs || true"]
              securityContext:
                runAsUser: 0
                runAsNonRoot: false
              volumeMounts:
                - name: docs
                  mountPath: /docs
            - name: crawl
              image: harbor.114-110-181-178.nip.io/nnd/nhn-docs-crawler:latest
              args: ["--changed", "--save-dir", "/docs"]
              resources:
                requests: { cpu: 500m, memory: 1Gi }
                limits: { cpu: "2", memory: 3Gi }
              volumeMounts:
                - name: docs
                  mountPath: /docs
            - name: ingest
              image: harbor.114-110-181-178.nip.io/nnd/nhn-docs-bot:latest
              command: ["python", "-u", "ingest.py"]
              args: ["--docs-dir", "/docs"]
              env:
                - { name: DB_HOST, value: db }
                - { name: DB_PORT, value: "5432" }
                - name: DB_USER
                  valueFrom:
                    secretKeyRef: { name: db, key: POSTGRES_USER }
                - name: DB_PASSWORD
                  valueFrom:
                    secretKeyRef: { name: db, key: POSTGRES_PASSWORD }
                - name: NVIDIA_API_KEY
                  valueFrom:
                    secretKeyRef: { name: llm, key: NVIDIA_API_KEY }
              resources:
                requests: { cpu: 250m, memory: 512Mi }
                limits: { cpu: "1", memory: 2Gi }
              volumeMounts:
                - name: docs
                  mountPath: /docs
                  readOnly: true
          containers:
            # BM25 는 프로세스 메모리에 있어 재적재 뒤 UI 를 다시 띄워야 한다.
            - name: restart
              image: bitnami/kubectl:1.31
              command: ["kubectl"]
              args: ["-n", "nhn-docs-bot", "rollout", "restart", "deploy/ui"]
              resources:
                requests: { cpu: 50m, memory: 64Mi }
                limits: { cpu: 200m, memory: 128Mi }
          volumes:
            - name: docs
              persistentVolumeClaim:
                claimName: docs
```

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest app/tests/test_k8s_manifests.py -q` 그리고 `python -m pytest -q`
Expected: 6 passed, 전체 PASS.

- [ ] **Step 7: 커밋**

```bash
git add deploy/k8s/httproute.yaml deploy/k8s/rbac.yaml deploy/k8s/refresh-cronjob.yaml app/tests/test_k8s_manifests.py
git commit -m "feat(deploy): HTTPRoute·RBAC·월 1회 refresh CronJob 매니페스트

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 평가 30문항 — 문항 파일, 채점 모듈, 러너

**Files:**
- Create: `eval/questions.yaml`, `eval/scoring.py`, `eval/run_eval.py`
- Test: `app/tests/test_eval_scoring.py`

**Interfaces:**
- Consumes: `rag.build_bm25/detect_intent/detect_service/hybrid_search/rerank_candidates/answer_stream`, `answer_render.valid_markers/NOT_GROUNDED_MESSAGE`, `Candidate.source_path`.
- Produces:
  - `scoring.Result` dataclass: `id, kind, question, hit5: bool, menu_ok: bool | None, shots_ok: bool | None, outside_ok: bool | None, elapsed_s: float, error: str | None`
  - `scoring.judge(item: dict, cand_paths: list[str], first_line: str, valid_marker_count: int, answer: str, elapsed_s: float, error: str | None) -> Result`
  - `scoring.summarize(results: list[Result]) -> dict` — 키 `hit5, menu, shots, outside, median_s, max_s, errors, pass: bool`
  - `scoring.THRESHOLDS = {"hit5": 0.8, "menu": 0.9, "shots": 0.8, "median_s": 15.0, "max_s": 30.0}`
  - `scoring.render_table(results, summary) -> str` (markdown)

- [ ] **Step 1: 실패하는 테스트 작성** — `app/tests/test_eval_scoring.py`

```python
"""eval/scoring.py 의 채점 규칙. 파이프라인은 돌리지 않는다."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "scoring", pathlib.Path(__file__).resolve().parents[2] / "eval" / "scoring.py")
scoring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scoring)

CONSOLE = {"id": 1, "kind": "console", "question": "q", "expect_path": "Network/DNS Plus/콘솔 사용 가이드.html", "expect_menu": "DNS Plus"}
GENERAL = {"id": 21, "kind": "general", "question": "q", "expect_path": "Network/VPC/API v2 가이드.html"}
OUTSIDE = {"id": 26, "kind": "outside", "question": "q"}


def test_console_all_pass():
    r = scoring.judge(CONSOLE, ["Network/DNS Plus/콘솔 사용 가이드.html", "x"], "콘솔 > Network > DNS Plus > DNS Zone", 2, "본문", 8.0, None)
    assert (r.hit5, r.menu_ok, r.shots_ok, r.outside_ok) == (True, True, True, None)


def test_console_menu_fails_when_first_line_says_unspecified():
    r = scoring.judge(CONSOLE, ["Network/DNS Plus/콘솔 사용 가이드.html"], "메뉴 경로: 문서에 명시되지 않음", 0, "본문", 8.0, None)
    assert r.hit5 is True and r.menu_ok is False and r.shots_ok is False


def test_hit5_only_counts_first_five():
    paths = ["a", "b", "c", "d", "e", "Network/DNS Plus/콘솔 사용 가이드.html"]
    assert scoring.judge(CONSOLE, paths, "콘솔 > DNS Plus", 1, "", 1.0, None).hit5 is False


def test_general_only_scores_hit():
    r = scoring.judge(GENERAL, ["Network/VPC/API v2 가이드.html"], "아무 줄", 0, "본문", 3.0, None)
    assert r.hit5 is True and r.menu_ok is None and r.shots_ok is None and r.outside_ok is None


def test_outside_requires_fixed_message_and_no_sources():
    r = scoring.judge(OUTSIDE, [], "제공된 문서에서 확인되지 않습니다.", 0, "제공된 문서에서 확인되지 않습니다.", 2.0, None)
    assert r.outside_ok is True and r.hit5 is None
    bad = scoring.judge(OUTSIDE, ["x"], "서울 날씨는", 0, "서울 날씨는 맑음", 2.0, None)
    assert bad.outside_ok is False


def test_error_marks_everything_failed():
    r = scoring.judge(CONSOLE, [], "", 0, "", 0.5, "RateLimitError")
    assert r.error == "RateLimitError" and r.hit5 is False and r.menu_ok is False and r.shots_ok is False


def _res(kind, **kw):
    base = dict(id=0, kind=kind, question="q", hit5=None, menu_ok=None, shots_ok=None, outside_ok=None, elapsed_s=1.0, error=None)
    base.update(kw)
    return scoring.Result(**base)


def test_summarize_rates_and_pass():
    results = (
        [_res("console", hit5=True, menu_ok=True, shots_ok=True, elapsed_s=10.0)] * 19
        + [_res("console", hit5=False, menu_ok=False, shots_ok=False, elapsed_s=20.0)]
        + [_res("general", hit5=True, elapsed_s=5.0)] * 5
        + [_res("outside", outside_ok=True, elapsed_s=2.0)] * 5
    )
    s = scoring.summarize(results)
    assert s["hit5"] == (24, 25) and s["menu"] == (19, 20) and s["shots"] == (19, 20) and s["outside"] == (5, 5)
    assert s["max_s"] == 20.0 and s["errors"] == 0
    assert s["pass"] is True


def test_summarize_fails_on_threshold():
    results = [_res("console", hit5=False, menu_ok=True, shots_ok=True)] * 10 + [_res("console", hit5=True, menu_ok=True, shots_ok=True)] * 10
    assert scoring.summarize(results)["pass"] is False


def test_render_table_mentions_every_question_and_summary():
    results = [_res("console", id=1, hit5=True, menu_ok=True, shots_ok=False, elapsed_s=12.3)]
    text = scoring.render_table(results, scoring.summarize(results))
    assert "| 1 |" in text and "12.3" in text and "적중" in text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_eval_scoring.py -q`
Expected: FAIL — `FileNotFoundError` (scoring.py 없음).

- [ ] **Step 3: `eval/scoring.py`**

```python
"""평가 30문항 채점 규칙 (스펙 5-6, 기본 스펙 8-2). 파이프라인을 모른다 — 러너가 관측값을 넘긴다."""
from dataclasses import dataclass
from statistics import median

NOT_GROUNDED_MESSAGE = "제공된 문서에서 확인되지 않습니다."
THRESHOLDS = {"hit5": 0.8, "menu": 0.9, "shots": 0.8, "median_s": 15.0, "max_s": 30.0}


@dataclass
class Result:
    id: int
    kind: str                 # console | general | outside
    question: str
    hit5: bool | None         # console·general: 상위 5 에 정답 문서
    menu_ok: bool | None      # console: 첫 줄에 expect_menu 포함
    shots_ok: bool | None     # console: 유효 마커 1개 이상
    outside_ok: bool | None   # outside: 고정 문구 + 출처 없음
    elapsed_s: float
    error: str | None


def judge(item, cand_paths, first_line, valid_marker_count, answer, elapsed_s, error) -> Result:
    kind = item["kind"]
    r = Result(id=item["id"], kind=kind, question=item["question"], hit5=None, menu_ok=None,
               shots_ok=None, outside_ok=None, elapsed_s=round(elapsed_s, 1), error=error)
    if error:
        if kind == "outside":
            r.outside_ok = False
        else:
            r.hit5 = False
            if kind == "console":
                r.menu_ok = False
                r.shots_ok = False
        return r

    if kind == "outside":
        r.outside_ok = answer.strip().startswith(NOT_GROUNDED_MESSAGE) and not cand_paths
        return r

    r.hit5 = item["expect_path"] in cand_paths[:5]
    if kind == "console":
        r.menu_ok = item["expect_menu"] in first_line and "명시되지 않음" not in first_line
        r.shots_ok = valid_marker_count >= 1
    return r


def _rate(results, attr):
    scored = [getattr(r, attr) for r in results if getattr(r, attr) is not None]
    return (sum(1 for v in scored if v), len(scored))


def summarize(results) -> dict:
    hit5 = _rate(results, "hit5")
    menu = _rate(results, "menu_ok")
    shots = _rate(results, "shots_ok")
    outside = _rate(results, "outside_ok")
    times = [r.elapsed_s for r in results if r.error is None] or [0.0]
    s = {
        "hit5": hit5, "menu": menu, "shots": shots, "outside": outside,
        "median_s": round(median(times), 1), "max_s": round(max(times), 1),
        "errors": sum(1 for r in results if r.error),
    }

    def ok(pair, key):
        n, d = pair
        return d == 0 or n / d >= THRESHOLDS[key]

    s["pass"] = (
        ok(hit5, "hit5") and ok(menu, "menu") and ok(shots, "shots")
        and outside[0] == outside[1]
        and s["median_s"] <= THRESHOLDS["median_s"] and s["max_s"] <= THRESHOLDS["max_s"]
        and s["errors"] == 0
    )
    return s


def _mark(v):
    return "-" if v is None else ("O" if v else "X")


def render_table(results, summary) -> str:
    lines = ["| id | 종류 | 질문 | 적중 | 메뉴 | 스크린샷 | 문서밖 | 초 | 오류 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.id} | {r.kind} | {r.question[:30]} | {_mark(r.hit5)} | {_mark(r.menu_ok)} | "
                     f"{_mark(r.shots_ok)} | {_mark(r.outside_ok)} | {r.elapsed_s} | {r.error or ''} |")

    def pct(pair):
        n, d = pair
        return f"{n}/{d}" + (f" ({n / d * 100:.0f}%)" if d else "")

    lines += [
        "",
        f"- 적중(상위 5): {pct(summary['hit5'])} (기준 80%)",
        f"- 콘솔 메뉴 경로: {pct(summary['menu'])} (기준 90%)",
        f"- 콘솔 스크린샷: {pct(summary['shots'])} (기준 80%)",
        f"- 문서 밖 고정 문구: {pct(summary['outside'])} (기준 전부)",
        f"- 지연 중앙값/최대: {summary['median_s']}초 / {summary['max_s']}초 (기준 15초 / 30초)",
        f"- 예외: {summary['errors']}건",
        f"- **판정: {'통과' if summary['pass'] else '미달'}**",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_eval_scoring.py -q`
Expected: 9 passed

- [ ] **Step 5: `eval/questions.yaml`** (정답 경로는 코퍼스 실제 파일명 — `카테고리/서비스/문서명.html`)

```yaml
# 평가 30문항 (스펙 5-6). expect_path 는 documents.source_path 와 같은 상대 경로.
# expect_menu 는 답변 첫 줄(콘솔 메뉴 경로)에 들어 있어야 하는 문자열.
- {id: 1,  kind: console, question: "인스턴스를 생성할 때 키페어는 어떻게 설정해?", expect_path: "Compute/Instance/콘솔 사용 가이드.html", expect_menu: "Instance"}
- {id: 2,  kind: console, question: "이미지를 다른 리전으로 복제하는 방법", expect_path: "Compute/Image/콘솔 사용 가이드.html", expect_menu: "Image"}
- {id: 3,  kind: console, question: "Cloud Functions에서 함수 환경 변수를 설정하는 방법", expect_path: "Compute/Cloud Functions/콘솔 사용 가이드.html", expect_menu: "Cloud Functions"}
- {id: 4,  kind: console, question: "GPU 인스턴스 생성을 요청하려면 어떻게 해?", expect_path: "Compute/GPU Instance/콘솔 사용 가이드.html", expect_menu: "GPU"}
- {id: 5,  kind: console, question: "DNS Plus에서 레코드 세트를 생성하는 방법", expect_path: "Network/DNS Plus/콘솔 사용 가이드.html", expect_menu: "DNS Plus"}
- {id: 6,  kind: console, question: "로드 밸런서의 리스너를 변경하려면 어떻게 해?", expect_path: "Network/Load Balancer/콘솔 사용 가이드.html", expect_menu: "Load Balancer"}
- {id: 7,  kind: console, question: "인터넷 게이트웨이를 연결하는 방법", expect_path: "Network/Internet Gateway/콘솔 사용 가이드.html", expect_menu: "Internet Gateway"}
- {id: 8,  kind: console, question: "서브넷에 라우팅 테이블을 연결하는 절차", expect_path: "Network/VPC/콘솔 사용 가이드.html", expect_menu: "VPC"}
- {id: 9,  kind: console, question: "블록 스토리지 크기를 변경하는 방법", expect_path: "Storage/Block Storage/콘솔 사용 가이드.html", expect_menu: "Block Storage"}
- {id: 10, kind: console, question: "오브젝트 스토리지에서 폴더를 만드는 방법", expect_path: "Storage/Object Storage/콘솔 사용 가이드.html", expect_menu: "Object Storage"}
- {id: 11, kind: console, question: "RDS for MS-SQL 백업을 오브젝트 스토리지로 내보내는 방법", expect_path: "Database/RDS for MS-SQL/콘솔 사용 가이드.html", expect_menu: "RDS"}
- {id: 12, kind: console, question: "Cloud Monitoring에서 대시보드를 생성하는 방법", expect_path: "Monitoring/Cloud Monitoring/콘솔 사용 가이드.html", expect_menu: "Cloud Monitoring"}
- {id: 13, kind: console, question: "Cloud Search에서 필드를 설정하는 방법", expect_path: "Search/Cloud Search/콘솔 사용 가이드.html", expect_menu: "Cloud Search"}
- {id: 14, kind: console, question: "SMS 발신 번호를 등록하는 절차", expect_path: "Notification/SMS/콘솔 사용 가이드.html", expect_menu: "SMS"}
- {id: 15, kind: console, question: "Email 서비스에서 수신 거부 주소를 파일 업로드로 등록하는 방법", expect_path: "Notification/Email/콘솔 사용 가이드.html", expect_menu: "Email"}
- {id: 16, kind: console, question: "Push에서 APNS 인증서를 등록하는 방법", expect_path: "Notification/Push/콘솔 사용 가이드.html", expect_menu: "Push"}
- {id: 17, kind: console, question: "Certificate Manager에서 알림 그룹을 생성하는 방법", expect_path: "Management/Certificate Manager/콘솔 사용 가이드.html", expect_menu: "Certificate Manager"}
- {id: 18, kind: console, question: "Private CA에 발급자를 추가하는 방법", expect_path: "Management/Private CA/콘솔 사용 가이드.html", expect_menu: "Private CA"}
- {id: 19, kind: console, question: "Log & Crash Search에서 로그 알람을 설정하는 방법", expect_path: "Data & Analytics/Log & Crash Search/콘솔 사용 가이드.html", expect_menu: "Log & Crash"}
- {id: 20, kind: console, question: "CDN 서비스를 일시 정지하는 방법", expect_path: "Content Delivery/CDN/콘솔 사용 가이드.html", expect_menu: "CDN"}
- {id: 21, kind: general, question: "VPC 서브넷 생성 API의 요청 파라미터를 알려줘", expect_path: "Network/VPC/API v2 가이드.html"}
- {id: 22, kind: general, question: "로드 밸런서가 지원하는 SSL/TLS 버전은?", expect_path: "Network/Load Balancer/개요.html"}
- {id: 23, kind: general, question: "Object Storage의 스토리지 클래스에는 어떤 것이 있어?", expect_path: "Storage/Object Storage/콘솔 사용 가이드.html"}
- {id: 24, kind: general, question: "Appkey는 무엇이고 어디에 쓰여?", expect_path: "NHN Cloud/_/Appkey.html"}
- {id: 25, kind: general, question: "인스턴스 이미지 생성 API 호출 방법", expect_path: "Compute/Image/API v2 가이드.html"}
- {id: 26, kind: outside, question: "오늘 서울 날씨 알려줘"}
- {id: 27, kind: outside, question: "AWS EC2 인스턴스 요금은 얼마야?"}
- {id: 28, kind: outside, question: "파이썬에서 리스트를 정렬하는 방법"}
- {id: 29, kind: outside, question: "NHN 주가는 지금 얼마야?"}
- {id: 30, kind: outside, question: "구글 클라우드에서 GKE 클러스터를 만드는 방법"}
```

- [ ] **Step 6: `eval/run_eval.py`**

```python
"""평가 30문항 러너 (스펙 5-6). UI 파드 안에서 돌린다:
    kubectl -n nhn-docs-bot cp eval/ <ui-pod>:/app/eval/ && kubectl -n nhn-docs-bot exec <ui-pod> -- python -u eval/run_eval.py
로컬:  cd app && DB_HOST=localhost python ../eval/run_eval.py --questions ../eval/questions.yaml
결과는 markdown 표로 stdout 에 찍는다. 기준 미달이면 exit 1.
"""
import argparse
import os
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                   # scoring
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))  # rag 등 (파드에서는 /app 이 cwd)

import scoring  # noqa: E402


def run_one(rag, ar, item):
    q = item["question"]
    t0 = time.time()
    try:
        intent = rag.detect_intent(q)
        service = rag.detect_service(q, rag.ALIASES)
        found = rag.hybrid_search(q, intent=intent, service=service)
        cands, grounded = rag.rerank_candidates(q, found, top_k=5)
        cand_paths = [c.source_path for c in cands]
        if grounded is False:
            answer, image_map = ar.NOT_GROUNDED_MESSAGE, {}
            cand_paths = []
        else:
            stream, image_map = rag.answer_stream(q, cands, intent=intent)
            answer = "".join(stream)
        first_line = answer.strip().splitlines()[0] if answer.strip() else ""
        valid = len(ar.valid_markers(answer, image_map))
        return scoring.judge(item, cand_paths, first_line, valid, answer, time.time() - t0, None)
    except Exception as e:
        return scoring.judge(item, [], "", 0, "", time.time() - t0, f"{type(e).__name__}: {str(e)[:60]}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=os.path.join(HERE, "questions.yaml"))
    p.add_argument("--only", default="", help="쉼표로 구분한 id 목록 (디버깅용)")
    args = p.parse_args(argv)

    import rag
    import answer_render as ar

    items = yaml.safe_load(open(args.questions, encoding="utf-8"))
    if args.only:
        keep = {int(x) for x in args.only.split(",")}
        items = [i for i in items if i["id"] in keep]

    print("BM25:", rag.build_bm25(), "chunks", file=sys.stderr)
    results = []
    for item in items:
        r = run_one(rag, ar, item)
        results.append(r)
        print(f"[{r.id:2d}] {r.kind:7s} {r.elapsed_s:5.1f}s hit={r.hit5} menu={r.menu_ok} shots={r.shots_ok} "
              f"outside={r.outside_ok} {r.error or ''}", file=sys.stderr)
        time.sleep(1)  # 무료 티어 배려

    summary = scoring.summarize(results)
    print(scoring.render_table(results, summary))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: 문항 파일 검증 테스트 추가** — `app/tests/test_eval_scoring.py` 끝에

```python
def test_questions_file_shape():
    import yaml
    items = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    kinds = [i["kind"] for i in items]
    assert len(items) == 30 and sorted(i["id"] for i in items) == list(range(1, 31))
    assert kinds.count("console") == 20 and kinds.count("general") == 5 and kinds.count("outside") == 5
    for i in items:
        if i["kind"] == "console":
            assert i["expect_path"].endswith(".html") and i["expect_menu"]
        elif i["kind"] == "general":
            assert i["expect_path"].endswith(".html")
```

Run: `python -m pytest app/tests/test_eval_scoring.py -q` → 10 passed. `python -m pytest -q` 전체 PASS.
로컬 DB 가 있으면 러너 자체도 한 번 돈다: `cd app && DB_HOST=localhost python ../eval/run_eval.py --only 5,26` (`.env` export 필요) — 표가 출력되고 예외가 없으면 된다(로컬 DB 는 일부 코퍼스라 적중은 무시).

- [ ] **Step 8: 커밋**

```bash
git add eval/questions.yaml eval/scoring.py eval/run_eval.py app/tests/test_eval_scoring.py
git commit -m "feat(eval): 평가 30문항, 채점 모듈, 파드 안 러너

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 런북(README) 갱신, 배포와 평가 실행

**Files:**
- Modify: `README.md` (`## 쿠버네티스 배포`, `### 운영 런북` 절)
- Modify: `docs/superpowers/plans/2026-09-17-console-guide-bot-phase2-carryover.md` (처리 항목 표시)

- [ ] **Step 1: README 런북 갱신** — `## 쿠버네티스 배포` 절의 "아직 공개 ingress 는 없다" 항목과 터널 명령을 지우고 아래 내용을 문장으로 넣는다.
  - 접속: `https://nhn-docs-bot.180-210-89-135.nip.io` (HTTPRoute `deploy/k8s/httproute.yaml`, 인증 없음, 인증 추가 방법은 파일 주석).
  - 이미지 둘: 앱 `nhn-docs-bot`(`app/Dockerfile`, 비root uid 1000), 크롤러 `nhn-docs-crawler`(`crawlling/Dockerfile`, 빌드 컨텍스트 저장소 루트). 태그 `2b-<git 짧은 해시>`.
  - 배포 순서: 이미지 빌드·푸시 → `kubectl apply -f deploy/k8s/rbac.yaml -f deploy/k8s/httproute.yaml -f deploy/k8s/refresh-cronjob.yaml`(태그 sed) → `kubectl -n nhn-docs-bot set image deploy/ui ui=<이미지>` → `rollout status`.
  - 재수집: CronJob `refresh` 매월 1일 03:00 KST, crawl → ingest → UI 재시작(새벽 30~60초 중단). 수동 실행·로그 보기 명령. 전체 재적재는 `ingest-job.yaml` 에 `--rebuild`.
  - 키 교체: `kubectl -n nhn-docs-bot create secret generic llm --from-literal=NVIDIA_API_KEY=<새 키> --dry-run=client -o yaml | kubectl apply -f -` → `rollout restart deploy/ui`. 키 값은 저장소·문서에 쓰지 않는다.
  - 주 1회 체크리스트(관리자 페이지): 👎 상위 서비스 → 문서·별칭 보강, 미확인 질문 → 별칭 누락 확인, 30초 초과 → NIM 상태.
  - 평가: `eval/run_eval.py` 실행 방법과 기준, "결과" 소절(컨트롤러가 Step 3 결과 표를 붙인다).
  - 백업 없음 명시: 질문 로그·피드백은 재적재로 복구되지 않는다.

- [ ] **Step 2: 이관 문서** — `## 2단계-B 설계에 반영` 절의 `ingest.py는 문서 하나라도 실패하면 exit 1`, `Dockerfile: root 실행, HEALTHCHECK 없음` 항목에 ` — 2B-2 에서 처리` 를 붙인다.

Run: `python -m pytest -q` → 전부 PASS. 커밋:

```bash
git add README.md docs/superpowers/plans/2026-09-17-console-guide-bot-phase2-carryover.md
git commit -m "docs: 운영 런북 — 접속·배포·재수집·키 교체·평가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 3: 배포와 검증 (컨트롤러가 수행 — 서브에이전트는 Step 2 까지만)**

1. 배스천에서 두 이미지 빌드·푸시: `docker build -t …/nhn-docs-bot:2b2-<해시> src/app`, `docker build -f src/crawlling/Dockerfile -t …/nhn-docs-crawler:2b2-<해시> src`.
2. `kubectl apply -f rbac.yaml -f httproute.yaml`, CronJob 은 태그 sed 후 apply, `nhn-docs-bot.yaml`·`ingest-job.yaml` apply(securityContext), `set image deploy/ui`, `rollout status`, `/_stcore/health` 200.
3. 수동 refresh: `kubectl create job --from=cronjob/refresh refresh-manual-<월일>` → `fix-perms`·`crawl`·`ingest`·`restart` 순서 완주 확인(로그), UI 재시작 후 200. 크롤은 850 페이지라 1시간 이상 걸릴 수 있다 — `--changed` 라 저장은 바뀐 것만.
4. 평가: `kubectl cp eval/ <ui-pod>:/app/eval/` → `kubectl exec <ui-pod> -- python -u eval/run_eval.py` → 결과 표를 README "결과" 소절과 이관 문서에 기록. 미달 항목은 이관 문서의 튜닝 후보로 1회 튜닝 후 재측정(별도 커밋).

---

## Self-review

**Spec coverage** — 5-1 크롤러 이미지·드라이버 분기 → Task 1. 5-2 CronJob·RBAC·수동 실행 → Task 4(+ Task 6 런북). 5-3 종료 코드 → Task 2. 5-4 Dockerfile 비root·HEALTHCHECK·securityContext·uid 1000 → Task 3 (크롤러 uid 는 Task 1). 5-5 매니페스트·인증 주석·태그·키 교체 → Task 4 + Task 6. 5-6 평가 → Task 5 + Task 6 Step 3. 5-7 런북 → Task 6. 6절 오류 행(crawl 실패 → 파드 Failed·UI 무영향: `backoffLimit 0`, `restartPolicy Never`; ingest 일부 실패 → exit 0; restart 권한 오류 → 파드 Failed) → Task 2·4. 7-1 크롤러 `build_driver` 테스트 → Task 1. 7-2 완료 기준 → Task 6 Step 3.

**Placeholder scan** — 없음. Task 1 Step 5 의 import 방식 확인은 구현자가 파일을 열어 판단하는 구체 지시다.

**Type consistency** — `scoring.judge(item, cand_paths, first_line, valid_marker_count, answer, elapsed_s, error)` 를 테스트·러너가 같은 순서로 호출. `Result` 필드명이 테스트 `_res` 와 일치. `summarize` 반환 키(`hit5, menu, shots, outside, median_s, max_s, errors, pass`)가 `render_table`·테스트와 일치. CronJob 컨테이너 이름(`fix-perms, crawl, ingest` / `restart`)이 테스트와 일치.

**추가 판단** — NFS 는 `fsGroup` 을 적용하지 않으므로 `fix-perms` initContainer(root, `chown -R 1000:1000 /docs`)를 두었다. NFS root-squash 로 chown 이 실패하면 `|| true` 로 넘어가고 크롤러가 쓰기 실패로 Failed 가 된다 — 그 경우 컨트롤러가 크롤러 컨테이너만 root(`runAsUser: 0`)로 되돌리는 결정을 내린다(Task 6 Step 3 에서 확인).
