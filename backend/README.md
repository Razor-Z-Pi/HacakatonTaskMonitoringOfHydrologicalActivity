# backend — веб-сервис (FastAPI)

Вся документация (запуск, данные, API, ML, метрика) — в корневом
[`README.md`](../README.md).

Коротко:

```bash
# 1) данные в backend/data/ (rasters + reference_masks — см. корневой README)
# 2) запуск
docker compose up --build      # → http://localhost:8000
```

Докер собирает и использует только эту папку (`src/`, `configs/`, `models/`,
`frontend/`); веса модели лежат в `models/lgbm_water.txt/.json`.
