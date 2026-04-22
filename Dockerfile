FROM python:3.12.10-slim

LABEL org.opencontainers.image.source="https://github.com/IntegrationProject-Groep1/infra"


WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY consumer.py .
COPY producer.py .
COPY xml_models.py .
COPY xml_handlers.py .
COPY calendar_service.py .

EXPOSE 30050

CMD ["python", "consumer.py"]