# ─── Multi-stage Dockerfile for Agents-in-the-air ──────────────────────
# Build frontend → bundle static assets → serve from Python backend.

# --- Build the frontend ---------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build || npx esbuild src/main.jsx --bundle --platform=browser \
      --format=iife --jsx=automatic --jsx-import-source=react \
      --minify --outfile=../backend/static/bundle.js

# --- Python runtime -------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

# Install system deps (curl for healthcheck, no build tools to keep image small)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy backend source
COPY backend/ ./

# Copy static UI from frontend stage
COPY --from=frontend /fe/../backend/static /app/static

# Create data directories
RUN mkdir -p /data/workspace

# ─── Security: run as non-root user ─────────────────────────────────
RUN useradd -m -u 1000 aita && chown -R aita:aita /app /data
USER aita

# ─── Environment ─────────────────────────────────────────────────────
ENV AITA_ENV=production
ENV AITA_DATA=/data
ENV AITA_WORKSPACE=/data/workspace
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Health check (hits /api/health; auth must allow it or be disabled)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run with production uvicorn settings (2 workers, no reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--no-access-log"]
