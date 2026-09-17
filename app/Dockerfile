# NHN Cloud 콘솔 안내 챗봇 — 앱 이미지 (UI · 적재 · 별칭 생성 공용)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8501

# 기동할 때 DB 의 서비스 목록으로 별칭 사전을 갱신한다(실패해도 이미지에 든 사전으로 뜬다).
CMD ["sh", "-c", "python aliases.py || true; exec python -m streamlit run ui.py --server.address 0.0.0.0 --server.port 8501"]
