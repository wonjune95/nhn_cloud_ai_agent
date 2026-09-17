import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
# app/ 안의 모듈(chunker, db, ingest …)은 패키지가 아니라 최상위 모듈로 import 한다.
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)
