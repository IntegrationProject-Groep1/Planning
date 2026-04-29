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
COPY db_config.py .
COPY graph_service.py .
COPY graph_client.py .
COPY token_service.py .
COPY xsd_validator.py .
COPY ics_service.py .
COPY schemas/ schemas/

EXPOSE 30050

CMD ["python", "consumer.py"]
