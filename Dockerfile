FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

# 입고일 기본값 등 '오늘' 날짜가 한국 시간 기준이 되도록 tzdata 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Seoul \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    INVENTORY_DATA_DIR=/data \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app

RUN useradd --uid 1000 --no-create-home inventory \
    && mkdir /data && chown inventory /data
USER inventory
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4)"

# SQLite 를 쓰므로 워커는 1개로 둔다 (사용자 5명 규모에 충분).
# Tailscale Funnel 프록시를 거친 요청의 실제 접속 IP를 쓰도록 X-Forwarded-* 를 신뢰한다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
