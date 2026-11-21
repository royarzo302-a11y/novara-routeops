FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
ENV VITE_NOVARA_HOSTED_DEMO=1
RUN npm run build

FROM python:3.12-slim-bookworm AS python-deps
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=0
RUN pip install --no-cache-dir uv==0.12.5
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

FROM python:3.12-slim-bookworm AS backend-local
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH="/app/backend:/app" \
    PATH="/opt/venv/bin:$PATH" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN useradd --create-home --user-group --uid 10001 appuser \
    && install -d -o appuser -g appuser /app/storage
COPY --from=python-deps /opt/venv /opt/venv
COPY backend/app ./backend/app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM backend-local AS render-demo
COPY --from=frontend-build /build/dist /app/web
COPY scripts/demo_data.py ./scripts/demo_data.py
COPY data/synthetic/santiago-road-demo.json ./data/synthetic/santiago-road-demo.json
ENV NOVARA_WEB_ROOT=/app/web
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.hosted:application --factory --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --limit-concurrency 24 --no-access-log"]
