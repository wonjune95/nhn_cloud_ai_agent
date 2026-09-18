"""documents 의 서비스 목록으로 별칭 사전 초안을 만든다.

    python aliases.py                      # app/services.generated.yaml
    python aliases.py --out 다른경로.yaml

여기서 만든 파일은 자동 생성분이다. "NKS", "L7 LB" 같은 약칭은 services.yaml 에
손으로 적고, 검색 단계에서 두 파일을 합쳐 읽는다.
"""

import argparse
import os
import sys

import yaml

from db import get_conn

NO_SERVICE = "_"
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.generated.yaml")


def alias_variants(service: str) -> list[str]:
    name = service.strip()
    if not name or name == NO_SERVICE:
        return []
    compact = name.replace(" ", "")
    return sorted({name, name.lower(), compact, compact.lower()})


def generate(conn) -> dict[str, list[str]]:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category, service FROM documents ORDER BY category, service")
    rows = cur.fetchall()
    cur.close()

    return {
        f"{category}/{service}": alias_variants(service)
        for category, service in rows
        if service != NO_SERVICE
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=DEFAULT_OUT)
    args = p.parse_args(argv)

    conn = get_conn()
    mapping = generate(conn)
    conn.close()

    # 적재 전이거나 적재가 실패한 DB 로 실행하면 사전이 통째로 비워진다.
    # 기존 파일을 지우지 않고 그대로 둔다 (Dockerfile 이 기동 때마다 이걸 부른다).
    if not mapping:
        print("documents 가 비어 있어 별칭 사전을 갱신하지 않습니다")
        return 0

    with open(args.out, "w", encoding="utf-8") as f:
        yaml.safe_dump(mapping, f, allow_unicode=True, sort_keys=True)

    print(f"서비스 {len(mapping)}개 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
