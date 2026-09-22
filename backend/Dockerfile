FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY configs ./configs
COPY src ./src
COPY frontend ./frontend
COPY models ./models

RUN mkdir -p /app/data /app/predictions

ENV HYDROMONITOR_CONFIG=/app/configs/config.yaml
EXPOSE 8000

CMD ["uvicorn", "src.service.main:app", "--host", "0.0.0.0", "--port", "8000"]