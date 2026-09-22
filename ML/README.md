# ML — пайплайн (обучение, инференс, выгрузка GEE)

Вся документация (данные, выгрузка GEE, обучение, метрика, подход) — в корневом
[`README.md`](../README.md).

Коротко:

```bash
cd ML
uv sync
uv run python download_gee.py --project <EE_PROJECT> --dry-run   # выгрузка снимков
uv run python train.py        # CV + модель + submission + отчёт
uv run python predict.py      # инференс
```

После переобучения скопируй веса в backend:

```bash
cp output/models/lgbm_water.txt ../backend/models/
cp output/models/lgbm_water.json ../backend/models/
```
