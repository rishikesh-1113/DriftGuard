# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Final stage
FROM python:3.12-slim

WORKDIR /app

# non-root user — security best practice
RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /install /usr/local
COPY . .

RUN chown -R appuser:appuser /app

USER 1001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "driftguard.api.webhook:app", "--host", "0.0.0.0", "--port", "8000"]
