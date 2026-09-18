"""BM25 용 토크나이저.

공백 분리는 "인스턴스를"과 "인스턴스"를 다른 토큰으로 봐서 조사만 붙어도 못 찾는다.
형태소 분석기 없이 한글은 2-gram 으로 쪼개고, 영숫자(버전·API 이름)는 통째로 소문자화한다.
"""

import re

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*|[가-힣]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in _TOKEN.findall(text):
        if "가" <= tok[0] <= "힣":
            if len(tok) == 1:
                tokens.append(tok)
            else:
                tokens.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            tok = tok.rstrip("._-").lower()
            if tok:
                tokens.append(tok)
    return tokens
