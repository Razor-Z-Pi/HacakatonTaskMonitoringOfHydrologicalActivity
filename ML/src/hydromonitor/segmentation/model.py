"""LightGBM-классификатор пикселей воды: обучение, калибровка порога, инференс.

LightGBM выбран как быстрый табличный бустер, нативно работающий с пропусками
(оптика отсутствует у части пар) и масштабирующийся на полные 10-м сетки (миллионы
пикселей). Сохраняется саморазогнанный текстовый ``Booster`` + JSON с порядком
признаков и откалиброванным порогом вероятности.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np

from ..features import FEATURE_NAMES


def make_params(cfg) -> dict:
    """Параметры LightGBM из ``configs/model.yaml`` (секция ``lgbm``)."""
    return {k: v for k, v in cfg.model.lgbm.as_dict().items()}


def train_lgb(X: np.ndarray, y: np.ndarray, params: dict,
              X_valid: np.ndarray | None = None, y_valid: np.ndarray | None = None) -> lgb.Booster:
    p = dict(params)
    n_rounds = int(p.pop("num_boost_round", 500))
    es_rounds = int(p.pop("early_stopping_round", 50))
    dset = lgb.Dataset(X, label=y)
    valid_sets, callbacks = None, []
    if X_valid is not None:
        valid_sets = [lgb.Dataset(X_valid, label=y_valid, reference=dset)]
        callbacks = [lgb.early_stopping(es_rounds, verbose=False)]
    return lgb.train(p, dset, num_boost_round=n_rounds, valid_sets=valid_sets, callbacks=callbacks)


def predict_prob(model: lgb.Booster, X: np.ndarray) -> np.ndarray:
    n_iter = getattr(model, "best_iteration", None) or model.current_iteration()
    return model.predict(X, num_iteration=n_iter)


def calibrate_threshold(y_true: np.ndarray, y_prob: np.ndarray, n: int = 101) -> float:
    """Порог вероятности, максимизирующий F1 по разметке (вода — редкий класс)."""
    best_t, best_f1 = 0.5, -1.0
    for t in np.linspace(0.05, 0.95, n):
        pred = y_prob >= t
        tp = int(np.sum(pred & y_true))
        fp = int(np.sum(pred & ~y_true))
        fn = int(np.sum(~pred & y_true))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if f1 > best_f1:
            best_f1, best_t = f1, t
    return float(best_t)


def predict_probability_map(model: lgb.Booster, feats: dict[str, np.ndarray],
                            tile: int = 512) -> np.ndarray:
    """Вероятность воды на полной сетке, тайлами (чтобы не материализовать всё сразу)."""
    h, w = feats[FEATURE_NAMES[0]].shape
    prob = np.empty((h, w), dtype="float32")
    for r0 in range(0, h, tile):
        r1 = min(h, r0 + tile)
        for c0 in range(0, w, tile):
            c1 = min(w, c0 + tile)
            X = np.column_stack([feats[n][r0:r1, c0:c1].ravel() for n in FEATURE_NAMES])
            prob[r0:r1, c0:c1] = predict_prob(model, X).reshape(r1 - r0, c1 - c0)
    return prob


def save_model(model: lgb.Booster, feature_names: list[str], threshold: float, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Через Python file I/O: C++ fopen у LightGBM не открывает пути с кириллицей на Windows.
    path.write_text(model.model_to_string(), encoding="utf-8")
    meta = {"feature_names": feature_names, "threshold": threshold}
    with open(path.with_suffix(".json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def load_model(path: Path):
    model = lgb.Booster(model_str=path.read_text(encoding="utf-8"))
    with open(path.with_suffix(".json"), "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    return model, meta
