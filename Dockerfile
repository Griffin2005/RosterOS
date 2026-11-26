# syntax=docker/dockerfile:1
# Single-container build for hosted demos (Render, Fly, any container host):
# FastAPI serves the API, the built React app and the embedded Google mock on
# one port. The full multi-service stack is docker-compose.yml.

FROM node:22-alpine AS web
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/mocks ./mocks
COPY --from=web /app/dist ./static

RUN useradd --uid 10001 --no-create-home appuser && mkdir -p /srv/data && chown appuser /srv/data
USER appuser

ENV STATIC_DIR=/srv/static \
    DATABASE_URL=sqlite:////srv/data/rosteros.db \
    SHEETS_MODE=embedded

# Seed at build time (rules import, holidays, December solve + publish) so a
# cold start on a small instance serves immediately instead of re-solving.
# Accounts are created WITHOUT passwords here: secrets never enter an image
# layer. app/bootstrap.py sets them from ADMIN_PASSWORD / DEMO_PASSWORD when
# the container starts.
RUN python -m app.seed

# This image is for public hosts, so it is production unless told otherwise:
# secure cookies, HSTS, no API docs, and start-up refuses a missing
# ADMIN_PASSWORD. It does not rely on the host's dashboard to set ENV.
ENV ENV=production

EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
