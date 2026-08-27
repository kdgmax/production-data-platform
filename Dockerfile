FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY data ./data

ENTRYPOINT ["run-data-pipeline"]
CMD ["--input", "data/sample_orders.csv"]
