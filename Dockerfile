FROM python:3.12-slim
WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev libwebp-dev libz-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY video_server/requirements.txt video_server/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r video_server/requirements.txt gunicorn

COPY . .

RUN mkdir -p logs status uploads/images uploads/documents uploads/media uploads/avatars instance && \
    adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 5000 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=5)" 2>/dev/null || \
      python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/health', timeout=5)" 2>/dev/null || exit 1
