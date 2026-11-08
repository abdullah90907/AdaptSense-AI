FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    ADAPTSENSE_DB=/state/adaptsense.db HF_HOME=/state/huggingface \
    ADAPTSENSE_ENABLE_INVESTIGATION=0
WORKDIR /app
COPY requirements-lock.txt ./
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu' \
    && python -m pip install --no-cache-dir -r requirements-lock.txt \
    && python -m pip check
COPY app/ app/
COPY scripts/seed_demo.py scripts/seed_demo.py
COPY data/victoria-demo.json.gz data/victoria-demo-manifest.json data/elecdaily-source.csv data/
COPY --from=frontend /build/dist frontend/dist
RUN groupadd --gid 10001 adaptsense && useradd --uid 10001 --gid 10001 --create-home adaptsense \
    && mkdir /state && chown 10001:10001 /state
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=4s --start-period=15s \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8765/health/ready', timeout=3).close()"
CMD ["sh", "-c", "python -m scripts.seed_demo && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --workers 1"]
