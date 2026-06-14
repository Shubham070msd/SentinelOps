FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY ui ./ui

ENV PYTHONPATH=/app/src
EXPOSE 8080
# Shell form so ${PORT} (injected by Render/Cloud Run/etc.) is honored; falls back to 8080 locally.
CMD uvicorn sentinelops.main:app --host 0.0.0.0 --port ${PORT:-8080}
