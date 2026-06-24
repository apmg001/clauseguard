# Minimal production image for the API. Phase 2+ (OCR, ML, vLLM client) will
# extend this; the core API runs lean.
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "clauseguard.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
