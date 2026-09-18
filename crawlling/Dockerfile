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
