# HydroWatch Amur — backend сервиса

Backend для кейса «Оперативный мониторинг гидрологической динамики по совместным
данным Sentinel-1 (SAR) и Sentinel-2 (MSI)» (КосмоХакатон 2026). Реализует Модуль 1
(сегментация — интерфейс, baseline "из коробки", точка подключения ML-модели),
Модуль 2 (пространственно-временной анализ: flood/receded), REST API и статику карты.

**ML-модель сегментации разрабатывается отдельно** и подключается без изменения
остального кода — см. раздел «Подключение ML-модели» ниже.

## Схема пайплайна

```
GeoTIFF пары (S1_pre/peak, S2_pre/peak?, AUX)
        │
        ▼
 src/align  ── выравнивание AUX (30 м) на эталонную сетку S1/эталона (10 м)
        │
        ▼
 src/segmentation ── Segmenter.segment_pair() -> water_pre, water_peak
   (baseline: Otsu(VV) + индексы + HAND/уклон/застройка + MMU;
    ML-модель — подключается через registry.py)
        │
        ▼
 src/analysis/change ── flood = peak & !pre & !permanent; receded = pre & !peak & !permanent
        │
        ▼
 src/repository ── кэш GeoTIFF в predictions/, площади, GeoJSON, submission.csv
        │
        ▼
 src/service (FastAPI) ── REST API + статика (Bootstrap 5 + Leaflet)
```

## Требования к окружению

- Python 3.14 (см. `requirements.txt`; все ключевые пакеты имеют колёса под 3.14).
- Системные зависимости для rasterio/geopandas: GDAL, GEOS, PROJ (в Docker ставятся
  автоматически, см. `Dockerfile`).

Установка без Docker:

```bash
python -m venv .venv && source .venv/bin/activate      # или uv venv / conda
pip install -r requirements.txt
```

## Структура входных данных

См. `data/README.md`. Пути и имена файлов не хардкожены — настраиваются в
`configs/config.yaml` (`paths.*`, `raster_files.*`, `band_indices.*`).

## Запуск

### Docker (рекомендуемый способ)

```bash
docker compose up --build
```

Сервис поднимется на `http://localhost:8000`, карта — на `http://localhost:8000/`,
API — под `http://localhost:8000/api/*`.

### Без Docker

```bash
export HYDROMONITOR_CONFIG=configs/config.yaml   # по умолчанию и так этот путь
uvicorn src.service.main:app --host 0.0.0.0 --port 8000 --reload
```

Запускать из корня репозитория — относительные пути в конфиге разрешаются от него.

### Формирование submission.csv для всех пар реестра

```bash
curl -X POST http://localhost:8000/api/submission/build
# файл появится в predictions/submission.csv (путь задан в configs/config.yaml)
```

Маски `<pair_id>_flood.tif` при этом уже лежат в `predictions/` — они считаются
и кэшируются при первом обращении к любому эндпоинту конкретной пары.

## Контракт API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/pairs` | Список пар: `{pair_id, event_id, aoi_name, date_pre, date_peak}` |
| GET | `/api/pairs/{pair_id}/areas` | `{flood_ha, water_pre_ha, water_peak_ha, aoi_ha}` |
| GET | `/api/pairs/{pair_id}/contours?layer=pre\|peak\|flood` | GeoJSON FeatureCollection (EPSG:4326) |
| GET | `/api/pairs/{pair_id}/report` | Сводная статистика (площади, доли, разбивка по покрову) |
| GET | `/api/pairs/{pair_id}/mask?layer=flood\|pre\|peak\|receded` | GeoTIFF маски (скачивание) |
| GET | `/api/pairs/{pair_id}/download?format=geojson\|shp&layer=...` | Векторные контуры |
| POST | `/api/submission/build` | Прогнать все пары реестра и собрать `submission.csv` |
| GET | `/api/health` | Проверка живости сервиса |

Полная интерактивная документация — `http://localhost:8000/docs` (Swagger UI от FastAPI).

## Подключение ML-модели

Backend не знает про внутреннее устройство модели — только про интерфейс
`Segmenter` (`src/segmentation/base.py`):

```python
class Segmenter(ABC):
    @abstractmethod
    def segment_pair(self, features: PairFeatureStack) -> SegmentationResult:
        ...
```

Чтобы подключить обученную модель (LightGBM и т.п.):

1. Создайте `src/segmentation/ml_model.py` с классом, например `LightGBMSegmenter(Segmenter)`,
   принимающим в конструкторе секцию `segmentation` конфига (гиперпараметры удобно
   держать в `configs/config.yaml` под `segmentation.lightgbm.*`).
2. Внутри `segment_pair` используйте поля `PairFeatureStack` (VV/VH пре/пик, опциональные
   индексы оптики, AUX-признаки slope/hand/occurrence/seasonality/max_extent/builtup —
   всё уже выровнено на единую сетку 10 м) и верните `SegmentationResult(water_pre, water_peak, meta)`.
3. Зарегистрируйте класс в `src/segmentation/registry.py` (`_KNOWN_BACKENDS`) — там уже
   есть заготовка `"lightgbm": "src.segmentation.ml_model:LightGBMSegmenter"`.
4. Переключите backend в `configs/config.yaml`: `segmentation.backend: lightgbm`.

Если backend недоступен или загрузка не удалась — сервис автоматически откатывается
на `BaselineSegmenter` (классический пайплайн из постановки кейса), чтобы оставаться
воспроизводимым в любом случае.

## Воспроизводимость

- Пороги и пути — только в `configs/config.yaml`, не в коде.
- Инференс полностью офлайн: GEE используется исключительно на этапе подготовки данных,
  backend работает с уже скачанными локально GeoTIFF.
- Все JS/CSS-библиотеки фронтенда — локально в `static/vendor/` (см. `static/vendor/README.md`),
  без CDN.
- Кэш масок в `predictions/` детерминирован при фиксированном backend'е сегментации
  (baseline не содержит случайности; для ML-модели фиксация seed — ответственность
  её реализации).

## Известные ограничения текущей версии

- `src/repository.py::_load_pairs_table` рассчитан на CSV с колонками
  `pair_id, event_id, aoi_name, date_pre, date_peak, group, has_optical` — при
  использовании официального реестра организаторов может понадобиться маппинг колонок.
- Разбивка отчёта по типам земного покрова сейчас ограничена `built_up_ha` / `other_ha`
  (единственный категориальный слой в базовом AUX-наборе) — при добавлении слоя
  земного покрова (например, ESA WorldCover целиком) разбивку легко расширить в
  `src/analysis/change.py::compute_landcover_breakdown` без изменения контракта API.
- Инкрементальное обновление по новому SAR-наблюдению (без пересчёта всей пары) в этой
  версии не реализовано — текущий кэш в `predictions/` per-pair; см. раздел «Дополнительно
  оценивается» постановки кейса как направление развития.
