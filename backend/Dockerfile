# syntax=docker/dockerfile:1
# One image for api, solver worker, scheduler and sheets-mock (different commands).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY requirements.txt .
# The cache mount keeps completed downloads between builds, so a flaky
# connection only re-fetches what failed (OR-Tools alone is ~25 MB).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY app ./app
COPY mocks ./mocks

RUN useradd --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
