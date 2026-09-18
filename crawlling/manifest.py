"""수집 결과 목록(manifest.json).

문서마다 원본 URL, 저장 경로, 브레드크럼, 본문 해시를 기록한다.
재개(이미 받은 페이지 건너뛰기), 변경 감지(--changed), 적재 시 원본 URL 조회에 쓴다.
"""

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_NO_BREADCRUMB = "no_breadcrumb"

# os.replace 재시도 설정. OneDrive 동기화 폴더에서는 자주 다시 쓰는 파일(manifest.json)을
# OneDrive 가 한동안 열어두는 경우가 있어, 기존 10회/0.2초(약 2초)로는 부족했다.
REPLACE_RETRIES = 30
REPLACE_WAIT = 0.5


@dataclass
class Entry:
    url: str
    path: str
    breadcrumb: list[str]
    fetched_at: str
    content_hash: str
    image_count: int
    status: str
    error: str = ""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Manifest:
    def __init__(self, path: str):
        self.path = path
        self.entries: dict[str, Entry] = {}

    @classmethod
    def _read_into(cls, m: "Manifest", path: str) -> None:
        with open(path, encoding="utf-8") as f:
            for url, fields in json.load(f).items():
                m.entries[url] = Entry(**fields)

    @classmethod
    def load(cls, path: str) -> "Manifest":
        """manifest.json 을 읽는다. 깨져 있으면 manifest.json.bak 을, 그것도 깨졌으면 빈 목록을.

        제자리 덮어쓰기 폴백(아래 save 참고)은 원자적이지 않아 중간에 죽으면 파일이
        깨질 수 있다. 그때 빈 manifest 로 시작하면 850쪽을 통째로 다시 받게 되므로
        직전 사본(.bak)을 먼저 시도한다.
        """
        m = cls(path)
        if not os.path.exists(path):
            return m

        try:
            cls._read_into(m, path)
            return m
        except json.JSONDecodeError as e:
            print(f"  [경고] {os.path.basename(path)} 가 깨졌습니다 ({e}). 직전 사본(.bak)으로 시도합니다.")

        m.entries.clear()
        backup = path + ".bak"
        if os.path.exists(backup):
            try:
                cls._read_into(m, backup)
                print(f"  [복구] {os.path.basename(backup)} 에서 {len(m.entries)}건을 읽었습니다.")
                return m
            except json.JSONDecodeError as e:
                print(f"  [경고] 사본도 깨졌습니다 ({e}). 빈 목록으로 시작합니다.")

        m.entries.clear()
        return m

    def save(self) -> None:
        tmp = self.path + ".tmp"
        data = {url: asdict(e) for url, e in self.entries.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

        # Windows(특히 OneDrive 동기화 폴더)에서는 다른 프로세스가 잠깐
        # manifest.json 을 열어두면 os.replace 가 PermissionError 를 낸다.
        # 몇 번 재시도하면 대개 풀린다.
        for attempt in range(1, REPLACE_RETRIES + 1):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                if attempt < REPLACE_RETRIES:
                    time.sleep(REPLACE_WAIT)

        # REPLACE_RETRIES 번을 다 써도 여전히 잠겨 있으면(OneDrive 가 파일을
        # 오래 붙잡고 있는 경우), 삭제 없이 제자리에서 덮어쓰는 것으로 대신한다.
        # os.replace 는 대상을 삭제/치환할 권한이 필요하지만, 이미 열려 있는
        # 파일이라도 내용을 그대로 덮어쓰는 것(같은 핸들 교체 없이)은 대개 허용된다.
        # 이 경로는 더 이상 원자적이지 않다: 덮어쓰는 도중 프로세스가 죽으면
        # manifest.json 이 손상될 수 있다. 그래서 덮어쓰기 직전에 현재 파일을
        # manifest.json.bak 으로 복사해 둔다 (load 가 그걸로 복구한다).
        if os.path.exists(self.path):
            try:
                shutil.copyfile(self.path, self.path + ".bak")
            except OSError as e:
                print(f"  [경고] manifest 사본(.bak) 생성 실패: {e}")

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        try:
            os.remove(tmp)
        except OSError:
            pass

    def get(self, url: str) -> Entry | None:
        return self.entries.get(url)

    def put(self, entry: Entry) -> None:
        self.entries[entry.url] = entry

    def by_path(self) -> dict[str, Entry]:
        return {e.path: e for e in self.entries.values()}
