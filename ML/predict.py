"""Инференс: прогноз по сохранённой модели → submission.csv + predictions/<pair_id>_flood.tif.

Пример:
    uv run python predict.py
    uv run python predict.py --model output/models/lgbm_water.txt --out output
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromonitor.config import load_config
from hydromonitor.pairs import load_pairs
from hydromonitor.segmentation.model import load_model
from hydromonitor.analysis import predict_all


def main() -> None:
    ap = argparse.ArgumentParser(description="Инференс гидрологической модели")
    ap.add_argument("--model", type=str, default=None,
                    help="путь к модели (.txt); по умолчанию output/models/lgbm_water.txt")
    ap.add_argument("--out", type=str, default=None,
                    help="каталог вывода; по умолчанию output/")
    args = ap.parse_args()

    cfg = load_config()
    pairs = load_pairs(cfg)
    out_dir = Path(args.out) if args.out else Path(cfg.paths.output_dir)
    model_path = Path(args.model) if args.model else out_dir / "models" / "lgbm_water.txt"

    model, meta = load_model(model_path)
    areas = predict_all(cfg, pairs, model, meta, out_dir, write=True)

    print("Сабмит записан:", out_dir / "submission.csv")
    for p in pairs:
        a = areas[p.pair_id]
        print(f"  {p.pair_id}: flood={a.flood_ha:.1f} ha, "
              f"pre={a.water_pre_ha:.1f}, peak={a.water_peak_ha:.1f}")


if __name__ == "__main__":
    main()
