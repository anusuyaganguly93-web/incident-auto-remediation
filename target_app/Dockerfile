FROM python:3.12-slim

WORKDIR /app
COPY target_app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY target_app/ target_app/

CMD ["uvicorn", "target_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
