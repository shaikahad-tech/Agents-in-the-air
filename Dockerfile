# --- Build the frontend ---------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
# Vite/esbuild may OOM on very small instances; fall back to esbuild directly.
RUN npm run build || npx esbuild src/main.jsx --bundle --platform=browser \
      --format=iife --jsx=automatic --jsx-import-source=react \
      --minify --outfile=../backend/static/bundle.js

# --- Python runtime -------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY backend/ ./
# static UI produced by the frontend stage (or checked into repo)
COPY --from=frontend /fe/../backend/static /app/static
ENV AITA_DATA=/data
ENV AITA_WORKSPACE=/data/workspace
RUN mkdir -p /data/workspace
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
