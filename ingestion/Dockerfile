FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY ingestion/ ingestion/
COPY orchestrator/ orchestrator/
COPY diagnostics/ diagnostics/

ENV PYTHONPATH=/app
CMD ["uvicorn", "ingestion.main:app", "--host", "0.0.0.0", "--port", "8000"]
