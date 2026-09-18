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
