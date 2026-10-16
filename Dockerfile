FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY ledgerlens ./ledgerlens
COPY static ./static
COPY seed.py app.py ./
COPY scripts/seed_if_needed.py ./scripts/seed_if_needed.py

RUN pip install --no-cache-dir .

ENV FALKORDB_HOST=falkordb \
    FALKORDB_PORT=6379 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
