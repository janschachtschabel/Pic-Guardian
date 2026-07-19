# syntax=docker/dockerfile:1
#
# Pic-Guardian — Single-Container-Image:
#   Stage 1 baut das Angular-Frontend, Stage 2 ist die FastAPI-Runtime, die
#   sowohl /api als auch das statische Frontend (gleiche Origin) ausliefert.
# Bauen:   docker build -t pic-guardian .
# Starten: docker run -p 8000:8000 -v pic-guardian-data:/app/data pic-guardian
#          -> http://localhost:8000

# ============ Stage 1: Angular-Frontend bauen ============
FROM node:22-bookworm AS frontend
WORKDIR /build
# Nur die Manifeste zuerst -> npm-ci-Layer wird gecacht, solange sie gleich bleiben
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # -> /build/dist/frontend/browser

# ============ Stage 2: Python-Runtime ============
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BILDCHECK_STATIC_DIR=/app/static

WORKDIR /app

# Python-Abhängigkeiten zuerst (stabiler Layer-Cache, unabhängig vom App-Code)
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend-Code
COPY backend/app ./app

# Gebautes Frontend aus Stage 1 (wird von FastAPI unter "/" ausgeliefert)
COPY --from=frontend /build/dist/frontend/browser ./static

# Nicht-root + persistentes Datenverzeichnis (Risikospeicher, Batch-Historie)
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# Laufzeit-Status (risk_hub.json, batch_jobs/) persistent halten
VOLUME ["/app/data"]

# Health-Check nutzt das bereits installierte httpx
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/api/health', timeout=3).status_code==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
