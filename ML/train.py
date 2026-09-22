"""Обучение: датасет → кросс-валидация (out-of-AOI и out-of-event) → итоговая модель.

Выход (в ``output/``):
* ``models/lgbm_water.txt`` + ``.json`` — итоговая модель и её метаданные (порог);
* ``reports/validation.json`` — CV-оценки Score по обеим схемам и per-pair раскладка;
* ``submission.csv`` и ``predictions/<pair_id>_flood.tif`` — итоговый сабмит.

Снимки SAR/оптики выгружаются командой и кладутся в ``rasters/<event>/<aoi>/``;
пока их нет, пайплайн автоматически работает на вспомогательных (AUX) признаках.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

from hydromonitor.config import load_config
from hydromonitor.pairs import load_pairs
from hydromonitor.io import read_reference_stats
from hydromonitor.metric import compute_score, reference_areas_from_json, PairAreas
from hydromonitor.cv import leave_one_aoi_out, leave_one_event_out
from hydromonitor.segmentation.dataset import build_dataset
from hydromonitor.segmentation.model import (
    make_params, train_lgb, predict_prob, calibrate_threshold, save_model,
)
from hydromonitor.analysis import predict_pair, areas_from_masks


def _train_fold_model(X, y, params, seed):
    """Обучить модель с внутренним early-stop (стратифицированный holdout 10 %)."""
    X_fit, X_es, y_fit, y_es = train_test_split(
        X, y, test_size=0.1, stratify=y, random_state=seed
    )
    model = train_lgb(X_fit, y_fit, params, X_valid=X_es, y_valid=y_es)
    threshold = calibrate_threshold(y_es, predict_prob(model, X_es))
    return model, threshold


def _run_cv(cfg, pairs, X, y, pair_ids, scheme_name, folds, params, seed):
    """Out-of-группа CV: предсказать каждую пару моделью, обученной без неё."""
    id_to_pair = {p.pair_id: p for p in pairs}
    oof: dict[str, PairAreas] = {}

    for fi, (train_ids, val_ids) in enumerate(folds):
        tr = np.isin(pair_ids, train_ids)
        model, threshold = _train_fold_model(X[tr], y[tr], params, seed + fi)

        for pid in val_ids:
            masks, pixel_ha, _ = predict_pair(cfg, id_to_pair[pid], model, {"threshold": threshold})
            oof[pid] = areas_from_masks(masks, pixel_ha)
            print(f"    [{scheme_name} fold {fi + 1}/{len(folds)}] {pid}: "
                  f"flood={oof[pid].flood_ha:.1f} ha, pre={oof[pid].water_pre_ha:.1f}, "
                  f"peak={oof[pid].water_peak_ha:.1f}")

    return oof


def main() -> None:
    ap = argparse.ArgumentParser(description="Обучение + CV + итоговая модель")
    ap.add_argument("--skip-cv", action="store_true",
                    help="пропустить кросс-валидацию (только финальная модель и сабмит)")
    args = ap.parse_args()

    t0 = time.time()
    cfg = load_config()
    pairs = load_pairs(cfg)
    out_dir = Path(cfg.paths.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sample = cfg.model.sample
    params = make_params(cfg)
    seed = int(sample.seed)

    # --- эталонные площади (из reference_*.json) ---
    stats = {p.pair_id: read_reference_stats(cfg, p) for p in pairs}
    ref_areas = reference_areas_from_json(stats, pairs)

    # --- обучающая матрица ---
    print("Построение обучающей матрицы…")
    X, y, pair_ids, _ = build_dataset(
        cfg, pairs,
        pos_cap=int(sample.pos_cap), neg_ratio=float(sample.neg_ratio), seed=seed,
    )
    print(f"  X: {X.shape}, положительных: {int(y.sum())}")

    # --- кросс-валидация ---
    report = {"cv": {}, "n_samples": int(len(y))}

    if not args.skip_cv:
        for scheme_name, folds in (
            ("leave_one_event_out", leave_one_event_out(pairs)),
            ("leave_one_aoi_out", leave_one_aoi_out(pairs)),
        ):
            print(f"\nCV: {scheme_name} ({len(folds)} фолдов)")
            oof = _run_cv(cfg, pairs, X, y, pair_ids, scheme_name, folds, params, seed)
            breakdown = compute_score(oof, ref_areas, pairs)
            report["cv"][scheme_name] = breakdown.as_dict()
            report["cv"][scheme_name]["per_pair"] = {
                k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                    for kk, vv in v.items()}
                for k, v in breakdown.per_pair.items()
            }
            print(f"  Score = {breakdown.score:.4f}  "
                  f"(Q_flood={breakdown.q_flood:.3f}, Q_peak={breakdown.q_water_peak:.3f}, "
                  f"Q_pre={breakdown.q_water_pre:.3f}, Spec={breakdown.spec_base:.3f})")

    # --- итоговая модель на всех данных ---
    print("\nОбучение итоговой модели на всех парах…")
    X_fit, X_es, y_fit, y_es = train_test_split(
        X, y, test_size=0.1, stratify=y, random_state=seed,
    )
    final_model = train_lgb(X_fit, y_fit, params, X_valid=X_es, y_valid=y_es)
    final_threshold = calibrate_threshold(y_es, predict_prob(final_model, X_es))

    models_dir = out_dir / "models"
    save_model(final_model, [str(n) for n in _feature_names()], final_threshold,
               models_dir / "lgbm_water.txt")

    # --- итоговый сабмит ---
    from hydromonitor.analysis import predict_all
    meta = {"threshold": final_threshold}
    sub_areas = predict_all(cfg, pairs, final_model, meta, out_dir, write=True)
    final_breakdown = compute_score(sub_areas, ref_areas, pairs)
    report["final_train_score"] = final_breakdown.as_dict()
    report["threshold"] = final_threshold
    report["feature_names"] = list(_feature_names())
    report["runtime_sec"] = round(time.time() - t0, 1)

    print(f"\nИтоговый (train) Score = {final_breakdown.score:.4f}")
    print(f"Порог вероятности: {final_threshold:.3f}")

    report_path = out_dir / "reports" / "validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"Отчёт: {report_path}")
    print(f"Сабмит: {out_dir / 'submission.csv'}")
    print(f"Готово за {report['runtime_sec']:.1f} c.")


def _feature_names():
    from hydromonitor.features import FEATURE_NAMES
    return FEATURE_NAMES


if __name__ == "__main__":
    main()
