"""수집 결과 목록(manifest.json).

문서마다 원본 URL, 저장 경로, 브레드크럼, 본문 해시를 기록한다.
재개(이미 받은 페이지 건너뛰기), 변경 감지(--changed), 적재 시 원본 URL 조회에 쓴다.
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_NO_BREADCRUMB = "no_breadcrumb"


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
    def load(cls, path: str) -> "Manifest":
        m = cls(path)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for url, fields in json.load(f).items():
                    m.entries[url] = Entry(**fields)
        return m

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {url: asdict(e) for url, e in self.entries.items()},
                f, ensure_ascii=False, indent=1,
            )
        os.replace(tmp, self.path)

    def get(self, url: str) -> Entry | None:
        return self.entries.get(url)

    def put(self, entry: Entry) -> None:
        self.entries[entry.url] = entry

    def by_path(self) -> dict[str, Entry]:
        return {e.path: e for e in self.entries.values()}
