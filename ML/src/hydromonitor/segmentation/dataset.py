"""Построение обучающей матрицы — пиксельные сэмплы с балансировкой классов.

Отрицательных пикселей (суша) на порядки больше положительных (вода), поэтому
сэмплируем: берём до ``pos_cap`` положительных и ``neg_ratio``× отрицательных на
окно. Сэмплы помечаются парой и окном — это нужно для CV «out-of-AOI/event» и для
сбора out-of-fold предсказаний.
"""

from __future__ import annotations

import numpy as np

from ..config import Config
from ..pairs import Pair
from ..io import read_reference_mask, read_aux, read_sar, read_optical
from ..features import assemble_features, FEATURE_NAMES
from ..features.context import distance_to_river


def load_pair_rasters(cfg: Config, pair: Pair):
    """Загрузить все растры пары: эталон, AUX, расстояние до реки, SAR/оптика (или None)."""
    ref = read_reference_mask(cfg, pair)
    aux = read_aux(cfg, pair, ref.profile)
    dist = distance_to_river(cfg, pair, ref.profile)
    sar_pre = read_sar(cfg, pair, "pre", ref.profile)
    sar_peak = read_sar(cfg, pair, "peak", ref.profile)
    opt_pre = read_optical(cfg, pair, "pre", ref.profile)
    opt_peak = read_optical(cfg, pair, "peak", ref.profile)
    return ref, aux, dist, sar_pre, sar_peak, opt_pre, opt_peak


def _sample(mask: np.ndarray, valid: np.ndarray, pos_cap: int, neg_ratio: float, rng) -> tuple[np.ndarray, np.ndarray]:
    """Индексы (flat) положительных и отрицательных сэмплов внутри зоны valid."""
    pos = np.flatnonzero(mask & valid)
    if pos.size > pos_cap:
        pos = rng.choice(pos, pos_cap, replace=False)
    n_neg = int(len(pos) * neg_ratio)
    neg = np.flatnonzero((~mask) & valid)
    if neg.size > n_neg:
        neg = rng.choice(neg, n_neg, replace=False)
    return pos, neg


def build_dataset(cfg: Config, pairs: list[Pair], pos_cap: int = 50000,
                  neg_ratio: float = 2.0, seed: int = 42):
    """Обучающая матрица (X, y) + метки пар/окон для всех пар.

    Возвращает ``(X, y, pair_ids, windows)``; ``X`` — float32, ``y`` — uint8.
    """
    rng = np.random.default_rng(seed)
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    pair_ids: list[str] = []
    windows: list[str] = []

    for pair in pairs:
        ref, aux, dist, sar_pre, sar_peak, opt_pre, opt_peak = load_pair_rasters(cfg, pair)
        # учимся только там, где AUX реально есть (вне футпринта — NaN, не разметка)
        valid = np.isfinite(aux.band("slope")) & np.isfinite(aux.band("hand"))

        for window, sar, opt, label in (
            ("pre", sar_pre, opt_pre, "water_pre"),
            ("peak", sar_peak, opt_peak, "water_peak"),
        ):
            feats = assemble_features(aux, dist, sar, opt, is_peak=(window == "peak"))
            mask = ref.band(label).astype(bool)
            pos, neg = _sample(mask, valid, pos_cap, neg_ratio, rng)
            idx = np.concatenate([pos, neg])
            X = np.column_stack([feats[n].ravel()[idx] for n in FEATURE_NAMES])
            y = np.concatenate([np.ones(len(pos), dtype="uint8"),
                                np.zeros(len(neg), dtype="uint8")])
            xs.append(X)
            ys.append(y)
            pair_ids.extend([pair.pair_id] * len(idx))
            windows.extend([window] * len(idx))

    X = np.vstack(xs).astype("float32")
    y = np.concatenate(ys)
    return X, y, np.asarray(pair_ids, dtype=object), np.asarray(windows, dtype=object)
