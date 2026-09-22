FROM python:3.14-slim
# Версия синхронизирована со стеком проекта: все ключевые пакеты (rasterio,
# geopandas, lightgbm и т.д.) имеют колёса под 3.14, даунгрейд не требуется.

# GDAL/GEOS/PROJ нужны rasterio/geopandas/shapely/pyproj.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gdal-bin libgdal-dev libgeos-dev libproj-dev g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY configs ./configs
COPY src ./src
COPY static ./static

# data/ и predictions/ монтируются как volume'ы (см. docker-compose.yml) —
# набор данных соревнования не входит в образ.
RUN mkdir -p /app/data /app/predictions

ENV HYDROMONITOR_CONFIG=/app/configs/config.yaml
EXPOSE 8000

CMD ["uvicorn", "src.service.main:app", "--host", "0.0.0.0", "--port", "8000"]
