FROM python:3.12.10-slim

WORKDIR /app

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY heartbeat.py .
COPY .env .

# Ejecutar el servicio heartbeat
CMD ["python", "heartbeat.py"]
