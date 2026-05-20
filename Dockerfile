FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/IntegrationProject-Groep1/infra"

# Upgrade OS packages to pick up latest security patches (fixes Trivy CRITICAL/HIGH CVEs).
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY consumer.py .
COPY producer.py .
COPY log_publisher.py .
COPY xml_models.py .
COPY xml_handlers.py .
COPY calendar_service.py .
COPY db_config.py .
COPY graph_service.py .
COPY graph_client.py .
COPY token_service.py .
COPY xsd_validator.py .
COPY ics_service.py .
COPY xsd/ xsd/

EXPOSE 30050

CMD ["python", "consumer.py"]
