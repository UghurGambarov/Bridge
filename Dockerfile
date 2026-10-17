# Bridge — one container: FastAPI serves the API (/api) and the built React frontend (/).

# ---- 1. build the frontend
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. runtime
FROM python:3.11-slim
ARG GIT_COMMIT=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    LLM_PROVIDER=mock \
    GIT_COMMIT=${GIT_COMMIT}
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY config config
COPY registry registry
COPY scenarios scenarios
COPY scripts/generate_samples.py scripts/generate_samples.py
COPY docs/known_risks.yaml docs/known_risks.yaml
COPY evidence/scenario_report.json evidence/scenario_report.md evidence/scenario_report.html evidence/
COPY --from=web /web/dist frontend/dist
RUN python scripts/generate_samples.py samples && useradd --create-home bridge && mkdir -p data && chown -R bridge /app/data /app/evidence
USER bridge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["python", "-m", "uvicorn", "--app-dir", "backend", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
