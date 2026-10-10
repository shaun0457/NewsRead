FROM python:3.12-slim

WORKDIR /opt/paperread

COPY pyproject.toml README.md LICENSE ./
COPY easyread ./easyread
COPY docker/entrypoint.sh /usr/local/bin/paperread-entrypoint

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && rm -rf /root/.cache

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    EASYREAD_HOME=/data/PaperRead \
    PAPERREAD_HOST=0.0.0.0 \
    PAPERREAD_PORT=8765

VOLUME ["/data/PaperRead"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3)"

ENTRYPOINT ["sh", "/usr/local/bin/paperread-entrypoint"]
