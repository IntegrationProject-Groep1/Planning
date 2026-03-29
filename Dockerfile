FROM python:3.12.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY heartbeat.py .
COPY producer.py .

EXPOSE 8080

CMD ["python", "heartbeat.py"]