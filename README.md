# Гидрологический мониторинг Амурской области — КосмоХакатон 2026

Оперативный мониторинг паводков и гидрологической динамики по Sentinel-1 (SAR) и
Sentinel-2 (оптика): сегментация открытой воды и зон затопления, подсчёт площадей,
веб-сервис визуализации и формирование сабмита `submission.csv` + `predictions/*_flood.tif`.

Стек: **ML** — пиксельный классификатор LightGBM (SAR-first); **backend** — FastAPI;
**frontend** — Leaflet + Bootstrap (статический, отдаётся самим FastAPI).

---

## Структура репозитория и как части связаны

```
HacakatonTaskMonitoringOfHydrologicalActivity/
├── backend/            # ← запускаемый веб-сервис (самодостаточен)
│   ├── src/            #   FastAPI: репозиторий, сегментация, анализ, API
│   ├── configs/config.yaml
│   ├── frontend/       #   ← фронтенд, который реально отдаёт сервис
│   ├── models/         #   ← веса LightGBM (lgbm_water.txt/.json)
│   ├── data/           #   ← данные (растры, эталоны, реестр) — частично gitignored
│   ├── Dockerfile / docker-compose.yml / requirements.txt
├── frontend/           # отдельная копия UI (дубликат backend/frontend/, Docker её НЕ использует)
└── ML/                 # офлайн-пайплайн: выгрузка GEE, обучение, инференс, сабмит
    └── output/models/lgbm_water.txt/.json   # исходник весов, откуда они копируются в backend/models/
```

**Ключевое:** `docker compose up` в `backend/` собирает и использует **только `backend/`** —
внутри него уже есть свой фронтенд и веса модели. Папка `ML/` нужна только офлайн
(скачать снимки, обучить модель); папка `frontend/` на верхнем уровне — дубль.

**Поток данных и модели:**
1. `ML/download_gee.py` выгружает снимки из GEE в каталог датасета.
2. `ML/train.py` обучает LightGBM и сохраняет `lgbm_water.txt/.json` в `ML/output/models/`.
3. Веса копируются в `backend/models/` (два файла — и они уже идут в git).
4. Backend читает растры из `backend/data/`, гоняет сегментацию и отдаёт результат в web.

---

## Требование к данным (обязательно для работы)

Сервис **не стартует полноценно без данных**: для каждого запроса к паре ему нужны
исходные растры и эталонная маска. Проверь, что в `backend/data/` лежит:

```
backend/data/
├── pairs.csv                  # реестр 11 пар (даты, AOI, event_kind, пути к растрам) — в git
├── sample_submission.csv      # обязательный перечень пар — в git
├── vectors/
│   └── hydrography_osm.geojson  # русла рек (для признака dist_river) — в git
│   └── aoi.geojson, basins_hydrosheds.geojson, amur_oblast.geojson
├── tables/                    # scene_catalog.csv, events_catalog.* — в git
├── reference_masks/           # ← gitignored, НУЖНО положить вручную
│   └── reference_<pair_id>.tif/.json   # эталон: задаёт каноническую сетку 10 м EPSG:32652
└── rasters/<event>/<aoi>/     # ← gitignored, НУЖНО положить вручную
    ├── AUX_terrain_gsw.tif         # slope/hand/occurrence/seasonality/max_extent/builtup (30 м → варп)
    ├── S1_pre_<date>.tif           # Sentinel-1 «до»
    ├── S1_peak_<date>.tif          # Sentinel-1 «пик»
    ├── SENTINEL2_pre_<date>.tif    # Sentinel-2 «до» — опц.
    └── SENTINEL2_peak_<date>.tif   # Sentinel-2 «пик» — опц.
```

**Каналы файлов (порядок фиксирован):**

| Файл | Каналы (по порядку) |
|---|---|
| `S1_<window>_<date>.tif` | `VV`, `VH`, `VV_VH_ratio` (дБ) |
| `SENTINEL2_<window>_<date>.tif` | `B3`, `B4`, `B8`, `B11`, `NDWI`, `MNDWI`, `NDVI`, `AWEISH` |
| `reference_<pair_id>.tif` | `flood`, `water_pre`, `water_peak`, `permanent`, `receded` (uint8) |

`<window>` = `pre` или `peak`. AUX — 30 м и варпится на каноническую сетку эталона (10 м).

`rasters/` и `reference_masks/` намеренно в `.gitignore` (тяжёлые GeoTIFF): их не
коммитят и не зашивают в Docker-образ — кладут на машину, где сервис запускается.
Имена растров датированные и подставляются из `pairs.csv` (см. `raster_files` в
`configs/config.yaml`). Если пара без оптики — сервис работает только по SAR (оптические
каналы = NaN, LightGBM обрабатывает пропуски нативно).

---

## Быстрый старт (Docker)

Требуется Docker Desktop. Фронтенд отдаётся самим FastAPI, отдельный сервер не нужен.

```bash
# 1) положить данные (rasters + reference_masks) в backend/data/  — см. раздел выше
# 2) собрать и запустить
cd backend
docker compose up --build
# 3) открыть http://localhost:8000
```

Без Docker (venv):

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows (bash: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn src.service.main:app --host 0.0.0.0 --port 8000
```

Первый запрос к паре медленный (~1–2 мин: полная сегментация + векторизация), дальше
маски кэшируются в `predictions/` и открываются быстро.

---

## API веб-сервиса

| Метод | Эндпоинт | Описание |
|---|---|---|
| GET | `/api/pairs` | список пар (`pair_id, event_id, aoi_name, date_pre, date_peak, group, has_optical`) |
| GET | `/api/pairs/{id}/areas` | `{flood_ha, water_pre_ha, water_peak_ha, aoi_ha}` |
| GET | `/api/pairs/{id}/contours?layer=pre\|peak\|flood\|receded` | контуры слоя (GeoJSON) |
| GET | `/api/pairs/{id}/report` | полный отчёт (площади, разбивка застройки, warnings) |
| GET | `/api/pairs/{id}/mask?layer=...` | маска слоя (GeoTIFF) |
| GET | `/api/pairs/{id}/download?format=geojson\|shp&layer=...` | выгрузка контуров |
| GET | `/api/submission` / `POST /api/submission/build` | готовый `submission.csv` / пересобрать |
| GET | `/api/health` | статус |

---

## ML-часть: выгрузка, обучение, инференс

Каталог `ML/` — отдельный Python-пакет (uv). Каталог датасета задаётся переменной
`HYDRO_DATA_DIR` (по умолчанию `../hydrowatch_amur`).

```bash
cd ML
uv sync                      # venv + зависимости (editable-установка пакета)
```

### Выгрузка снимков из GEE

Снимки Sentinel-1/2 в архив не входят. Выгрузку делает `download_gee.py`
(нужна авторизация Earth Engine; с российских IP может требоваться VPN):

```bash
earthengine authenticate                                     # один раз, интерактивно
uv run python download_gee.py --project <EE_PROJECT> --dry-run        # план, без GEE
uv run python download_gee.py --project <EE_PROJECT>                  # экспорт + скачивание
uv run python download_gee.py --project <EE_PROJECT> --download-only --workers 6
```

### Обучение и инференс

```bash
uv run python train.py        # CV + итоговая модель + submission + отчёт
uv run python predict.py      # инференс по сохранённой модели
```

Выход — в `ML/output/`: `submission.csv`, `predictions/<pair_id>_flood.tif`,
`models/lgbm_water.txt/.json`, `reports/validation.json`.

### Передача модели в backend

После обучения перекопируй **два файла** весов в backend (они идут в git):

```bash
cp ML/output/models/lgbm_water.txt backend/models/
cp ML/output/models/lgbm_water.json backend/models/
```

Backend подхватывает модель автоматически: `configs/config.yaml` →
`segmentation.backend: lightgbm` → `src/segmentation/ml_model.py` (`LightGBMSegmenter`).
Если `lightgbm` не установлен или модель не найдена — сервис откатывается на
baseline-сегментацию (Otsu + индексы).

---

## Метрика

```
Score = 0.45·Q_flood + 0.25·Q_water_peak + 0.15·Q_water_pre + 0.15·Spec_base
q = max(0, 1 − |X_sub − X_ref| / max(X_ref, порог))
    порог: затопление 50 га, вода 200 га
Spec_base — контроль ложных срабатываний на контрольных парах межени (допуск 0.5 % площади).
```

`Q_*` усредняются по 8 событийным парам, `Spec_base` — по 3 контрольным.

## Подход (SAR-first, одна модель)

* **Один пиксельный классификатор LightGBM** воды для обоих окон (`pre`/`peak`),
  `is_peak` — индикатор окна.
* **Признаки** (27): статические AUX (`slope`, `hand`, `occurrence`, `seasonality`,
  `max_extent`, `builtup`) + `dist_river` + гидроподсказки; SAR (`vv`, `vh`,
  `vv_vh_ratio` + фильтр Ли); оптика (`b3/b4/b8/b11` + `ndwi/mndwi/ndvi/aweish`);
  `has_optical` — индикатор модальности.
* **Вывод масок**: порог по вероятности → мин. картируемая единица (25 px) →
  `flood = water_peak & ~water_pre & ~permanent` (+ падение VV ≥ 3 дБ).
* **Валидация**: leave-one-AOI-out и leave-one-event-out.

### Структура ML-пакета

```
configs/            paths.yaml · thresholds.yaml · model.yaml  (пороги и пути — не в коде)
src/hydromonitor/
  config.py · pairs.py · io.py · metric.py · cv.py
  features/         sar.py · optical.py · context.py · сборка признаков
  segmentation/     baseline.py · postprocess.py · dataset.py · model.py
  analysis/         маски → площади, flood-вывод, submission, predictions
train.py · predict.py · download_gee.py
```

---

## Замечания

* **Текущая модель может быть слабой** (если обучена только на AUX, без SAR) — после
  докачки GEE и переобучения с SAR замени веса в `backend/models/`.
* **`frontend/` на верхнем уровне — дубль** `backend/frontend/`; сервис отдаёт именно
  `backend/frontend/`. Держи их синхронными (или удали верхний, если он не нужен).
* `pydantic==2.9.*` из `requirements.txt` не собирается на Python 3.14 — Docker
  использует `python:3.13-slim`, там всё ок.
* `max_extent`/`builtup` после варпа округляются к 0/1; пиксели вне футпринта AUX — NaN.
* Расстояние до реки кэшируется (`predictions/<pair_id>_dist_river.npy`); при смене
  сетки или `hydrography_osm.geojson` кэш удалить вручную.
* В эталоне `reference_*.json` площадь `aoi_ha` точнее, чем `aoi_km2` из `pairs.csv` —
  в метрике используется `aoi_ha`.
