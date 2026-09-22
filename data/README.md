# Структура data/

Backend ожидает набор данных соревнования `hydrowatch_amur` в следующей раскладке
(имена файлов и путь к реестру пар настраиваются в `configs/config.yaml`):

```
data/
├── vectors/                          # границы, гидрография OSM, бассейны HydroSHEDS
├── tables/
│   └── pairs.csv                     # реестр пар — см. пример в этом каталоге
├── rasters/<event_id>/<aoi_name>/
│   ├── S1_pre.tif                    # VV, VH, VV_VH_ratio, дБ
│   ├── S1_peak.tif
│   ├── SENTINEL2_pre.tif             # B3,B4,B8,B11 + NDWI,MNDWI,NDVI,AWEIsh (не всегда есть)
│   ├── SENTINEL2_peak.tif
│   └── AUX_terrain_gsw.tif           # slope,hand,occurrence,seasonality,max_extent,builtup
└── reference_masks/                  # эталонные маски — только для обучения/самопроверки,
                                       # backend их не использует при формировании ответа
```

`data/tables/pairs.csv` в этом репозитории — **шаблон**, показывающий ожидаемые колонки
(`pair_id, event_id, aoi_name, date_pre, date_peak, group, has_optical`). Реальный реестр
поставляется вместе с набором данных соревнования — либо конвертируйте официальный
`tables/`-реестр в этот формат, либо адаптируйте `DataRepository._load_pairs_table`
под фактическую структуру CSV организаторов.

Спутниковые снимки в архив соревнования не входят и загружаются из Google Earth Engine
на этапе подготовки данных (см. `src/align/` и `src/segmentation/`) — сам backend
работает только с уже сохранёнными локально GeoTIFF, инференс полностью офлайн.
