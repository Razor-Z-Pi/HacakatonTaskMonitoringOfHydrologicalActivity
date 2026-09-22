# HydroMonitor — ML-часть (КосмоХакатон 2026)

Оперативный мониторинг гидрологической динамики Амурской области по
Sentinel-1 (SAR) и Sentinel-2 (оптика): сегментация открытой воды и затоплений,
подсчёт площадей и формирование сабмита `submission.csv` + `predictions/*_flood.tif`.

Мой скоуп — **вся ML-часть**: признаки (features), сегментация, обучение, инференс,
сабмит и скрипт выгрузки снимков `download_gee.py`. Веб-сервис делают сокомандники.

---

## Данные

Каталог `../hydrowatch_amur` (переопределяется переменной `HYDRO_DATA_DIR`):

```
hydrowatch_amur/
├── pairs.csv                       # 11 пар: 8 событийных + 3 контрольных (межень)
├── reference_masks/                # эталон (10 м, EPSG:32652): 5 каналов uint8
│   └── reference_<pair>.tif/.json  # flood, water_pre, water_peak, permanent, receded
├── rasters/<event>/<aoi>/
│   ├── AUX_terrain_gsw.tif         # slope/hand/occurrence/seasonality/max_extent/builtup (30 м)
│   ├── S1_<pre|peak>_<date>.tif    # Sentinel-1 (выгружается из GEE)
│   └── SENTINEL2_<pre|peak>_<date>.tif  # Sentinel-2 L2A (выгружается из GEE)
├── vectors/                        # hydrography_osm.geojson, aoi, basins, область
├── tables/                         # scene_catalog.csv, events_catalog.*
└── sample_submission.csv
```

**Каноническая сетка** — растр эталонной маски (10 м, EPSG:32652). AUX (30 м)
варпится на неё; всё обучение и предсказание идут на этой сетке.

### Соглашение об именах снимков (для команды выгрузки)

`io.read_sar` / `io.read_optical` ищут файлы в `rasters/<event>/<aoi>/`:

| Файл | Каналы (порядок фиксирован) |
|---|---|
| `S1_<window>_<date>.tif` | `VV`, `VH`, `VV_VH_ratio` (дБ) |
| `SENTINEL2_<window>_<date>.tif` | `B3`, `B4`, `B8`, `B11`, `NDWI`, `MNDWI`, `NDVI`, `AWEISH` |

`<window>` = `pre` или `peak`. Если файла нет — пайплайн не падает, а работает на
вспомогательных (AUX) признаках (оптические каналы заполняются NaN, LightGBM
обрабатывает пропуски нативно).

---

## Выгрузка снимков из GEE

Снимки Sentinel-1/2 в архив не входят — в `rasters/<event>/<aoi>/` лежат только
паспорта сцен (`S1_*.json`, `SENTINEL2_*.json`) и `AUX_terrain_gsw.tif`. Выгрузку
делает `download_gee.py` (нужна авторизация Earth Engine; с российских IP геопортал
может требовать VPN):

```bash
earthengine authenticate                                   # один раз, интерактивно
uv run python download_gee.py --project <EE_PROJECT> --dry-run   # план, без GEE
uv run python download_gee.py --project <EE_PROJECT>             # экспорт + скачивание
uv run python download_gee.py --project <EE_PROJECT> --download-only --workers 6  # докачать готовое
```

По умолчанию экспорт идёт в GEE-ассеты и скачивается автоматически; с
`--backend drive` — в Google Drive (скачивание вручную или через geemap).
Скрипт берёт даты и орбиты из `pairs.csv` (точные `scene_id` — в
`tables/scene_catalog.csv`) и накладывает сцену на каноническую сетку эталонной
маски пары (10 м, EPSG:32652). После выгрузки — перезапустить `train.py`.

---

## Установка и запуск

```bash
uv sync                      # venv + зависимости (editable-установка пакета)
uv run python train.py       # CV + итоговая модель + submission + отчёт
uv run python predict.py     # инференс по сохранённой модели
```

Выход — в `output/`:

```
output/
├── submission.csv                  # pair_id, flood_ha, water_pre_ha, water_peak_ha
├── predictions/<pair_id>_flood.tif # uint8 0/1 на канонической сетке
├── models/lgbm_water.txt/.json     # модель + метаданные (порядок признаков, порог)
└── reports/validation.json         # CV-оценки Score
```

---

## Метрика

```
Score = 0.45·Q_flood + 0.25·Q_water_peak + 0.15·Q_water_pre + 0.15·Spec_base
q = max(0, 1 − |X_sub − X_ref| / max(X_ref, порог))
    порог: затопление 50 га, вода 200 га
Spec_base — контроль ложных срабатываний на контрольных парах межени (допуск 0.5 % площади).
```

`Q_*` усредняются по 8 событийным парам, `Spec_base` — по 3 контрольным.

---

## Подход (SAR-first, одна модель)

* **Один пиксельный классификатор LightGBM** воды для обоих окон (`pre`/`peak`);
  `is_peak` — индикатор окна.
* **Признаки** (см. `src/hydromonitor/features/`):
  * статические — AUX (`slope`, `hand`, `occurrence`, `seasonality`, `max_extent`,
    `builtup`), расстояние до русла (`dist_river`), производные гидроподсказки;
  * SAR — `vv`, `vh`, `vv_vh_ratio` + фильтр Ли (`vv_lee`, `vh_lee`) и разность;
  * оптика — `b3/b4/b8/b11` + индексы `ndwi/mndwi/ndvi/aweish`;
  * `has_optical` — индикатор модальности (пары без оптики → NaN в оптических каналах).
* **Вывод масок**: порог по вероятности (калибруется по F1) → мин. картируемая
  единица (25 px) → `flood = water_peak & ~water_pre & ~permanent` (+ падение VV ≥ 3 дБ).
* **Валидация** — две схемы: `leave-one-AOI-out` (пространственная обобщаемость) и
  `leave-one-event-out` (временная, ближе к тесту 2026 г.). Эталон построен
  автоматически, поэтому out-of-группа CV обязателен.

---

## Структура

```
configs/            paths.yaml · thresholds.yaml · model.yaml  (все пороги и пути — не в коде)
src/hydromonitor/
  config.py         загрузка YAML + разрешение путей (HYDRO_DATA_DIR)
  pairs.py          реестр пар (pairs.csv)
  io.py             чтение/варп растров, эталон, AUX, SAR, оптика, запись масок
  metric.py         точная реализация Score
  cv.py             leave-one-AOI/event-out
  features/         sar.py · optical.py · context.py · сборка признаков
  segmentation/     baseline.py · postprocess.py · dataset.py · model.py
  analysis/         маски → площади, flood-вывод, submission, predictions
train.py · predict.py
```

## Замечания

* В эталоне `reference_*.json` площади `aoi_ha` точнее, чем `aoi_km2` из `pairs.csv`
  (для `blagoveshchensk` 1649 vs 1586 км²) — в метрике используется `aoi_ha` из JSON.
* `max_extent`/`builtup` после варпа округляются к 0/1; пиксели вне футпринта AUX
  помечаются NaN, а не 0.
* Расстояние до реки кэшируется в `cache/dist_river_<pair_id>.npy`; при смене
  сетки или `hydrography_osm.geojson` кэш удалить вручную.
