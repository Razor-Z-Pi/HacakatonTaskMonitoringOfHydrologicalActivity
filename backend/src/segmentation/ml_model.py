"""Подключение обученной LightGBM-модели к backend (Модуль 1: сегментация).

Реализует ``Segmenter.segment_pair``: собирает ровно те же 27 признаков, что и
ML-часть (``src/hydromonitor/features``), грузит Booster из ``models/lgbm_water.txt``
(+ ``.json`` с порядком признаков и порогом) и возвращает ``water_pre``/``water_peak``.

Порог вероятности берётся из метаданных модели; постобработка (мин. картируемая
единица) — из ``configs/config.yaml`` (секция ``segmentation.lightgbm``), значения
дублируют ``configs/thresholds.yaml`` ML-части.

Если ``lightgbm`` не установлен или модель не найдена — ``__init__`` поднимает
``ImportError``, и ``registry.py`` откатывается на ``BaselineSegmenter``.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from scipy.ndimage import generate_binary_structure, label
from scipy.ndimage import sum as ndi_sum
from scipy.ndimage import uniform_filter

from .base import PairFeatureStack, SegmentationResult, Segmenter

# Корень backend-пакета (ml_model.py -> segmentation -> src -> backend).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _lee_filter(img: np.ndarray, window: int = 5, enl: float = 5.0) -> np.ndarray:
    """Фильтр Ли (адаптивный, для мультипликативного спекл-шума SAR)."""
    img = np.asarray(img, dtype="float32")
    mean = uniform_filter(img, window)
    mean_sq = uniform_filter(img * img, window)
    var = np.maximum(mean_sq - mean * mean, 0.0)
    sigma_u = 1.0 / np.sqrt(max(enl, 1.0))
    denom = var + sigma_u * sigma_u * mean * mean + 1e-12
    k = var / denom
    return (mean + k * (img - mean)).astype("float32")


def _remove_small_components(mask: np.ndarray, min_px: int = 25, connectivity: int = 8) -> np.ndarray:
    """Убрать связные компоненты меньше ``min_px`` пикселей (мин. картируемая единица)."""
    mask = np.asarray(mask, dtype=bool)
    if min_px <= 1:
        return mask
    structure = generate_binary_structure(2, connectivity)
    labels, n = label(mask, structure=structure)
    if n == 0:
        return mask
    sizes = ndi_sum(mask, labels, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, dtype=bool)
    keep[np.where(sizes >= min_px)[0] + 1] = True
    return keep[labels]


class LightGBMSegmenter(Segmenter):
    name = "lightgbm"

    def __init__(self, cfg: dict):
        self.cfg = cfg["lightgbm"]

        p = Path(self.cfg["model_path"])
        model_path = p if p.is_absolute() else (_BACKEND_ROOT / p)
        if not model_path.exists():
            raise ImportError(f"Модель LightGBM не найдена: {model_path}")

        self.model = lgb.Booster(model_str=model_path.read_text(encoding="utf-8"))
        with open(model_path.with_suffix(".json"), "r", encoding="utf-8") as fh:
            meta = json.load(fh)

        self.threshold = float(meta["threshold"])
        # Порядок признаков — канонический, из метаданных модели.
        self.feature_names = list(meta["feature_names"])
        self.num_iter = getattr(self.model, "best_iteration", None) or self.model.current_iteration()

        self.min_px = int(self.cfg.get("min_unit_px", 25))
        self.drop_db = float(self.cfg.get("drop_db", 3.0))
        self.speckle_window = int(self.cfg.get("speckle_window", 5))
        self.lee_enl = float(self.cfg.get("lee_enl", 5.0))

    # ------------------------------------------------------------------
    # Сборка признаков (повторяет src/hydromonitor/features/assemble_features)
    # ------------------------------------------------------------------
    def _window_features(self, f: PairFeatureStack, vv, vh, opt, is_peak: bool) -> dict:
        h, w = vv.shape
        nan = np.full((h, w), np.nan, dtype="float32")

        # Статика + гидроконтекст.
        slope = np.asarray(f.slope, dtype="float32")
        hand = np.asarray(f.hand, dtype="float32")
        occ = np.asarray(f.occurrence, dtype="float32")
        max_extent = (np.asarray(f.max_extent, dtype="float32") > 0.5).astype("float32")
        builtup = np.asarray(f.builtup, dtype="float32")  # bool -> 0/1
        dist_river = np.asarray(f.dist_river, dtype="float32")

        hand_le_25_b = hand <= 25.0
        slope_le_5_b = slope <= 5.0
        occ_ge_80_b = occ >= 80.0
        floodable_b = (max_extent > 0.5) | (hand_le_25_b & (builtup < 0.5))

        # SAR.
        vv = np.asarray(vv, dtype="float32")
        vh = np.asarray(vh, dtype="float32")
        ratio = vv - vh
        vv_lee = _lee_filter(vv, self.speckle_window, self.lee_enl)
        vh_lee = _lee_filter(vh, self.speckle_window, self.lee_enl)
        vv_vh_diff = vv - vh

        # Оптика (или NaN, если её нет).
        if opt is not None:
            b3, b4, b8, b11, ndwi, mndwi, ndvi, aweish = (
                np.asarray(x, dtype="float32") for x in opt
            )
        else:
            b3 = b4 = b8 = b11 = ndwi = mndwi = ndvi = aweish = nan

        return {
            "slope": slope,
            "hand": hand,
            "occurrence": occ,
            "seasonality": np.asarray(f.seasonality, dtype="float32"),
            "max_extent": max_extent,
            "builtup": builtup,
            "dist_river": dist_river,
            "hand_le_25": hand_le_25_b.astype("float32"),
            "slope_le_5": slope_le_5_b.astype("float32"),
            "occ_ge_80": occ_ge_80_b.astype("float32"),
            "floodable": floodable_b.astype("float32"),
            "vv": vv,
            "vh": vh,
            "vv_vh_ratio": ratio,
            "vv_lee": vv_lee,
            "vh_lee": vh_lee,
            "vv_vh_diff": vv_vh_diff,
            "b3": b3, "b4": b4, "b8": b8, "b11": b11,
            "ndwi": ndwi, "mndwi": mndwi, "ndvi": ndvi, "aweish": aweish,
            "has_optical": np.ones((h, w), dtype="float32") if opt is not None
                           else np.zeros((h, w), dtype="float32"),
            "is_peak": np.full((h, w), 1.0 if is_peak else 0.0, dtype="float32"),
        }

    def _probability(self, feats: dict, tile: int = 512) -> np.ndarray:
        """Вероятность воды на полной сетке тайлами (без материализации всего сразу)."""
        h, w = feats[self.feature_names[0]].shape
        prob = np.empty((h, w), dtype="float32")
        for r0 in range(0, h, tile):
            r1 = min(h, r0 + tile)
            for c0 in range(0, w, tile):
                c1 = min(w, c0 + tile)
                X = np.column_stack(
                    [feats[n][r0:r1, c0:c1].ravel() for n in self.feature_names]
                )
                prob[r0:r1, c0:c1] = self.model.predict(
                    X, num_iteration=self.num_iter
                ).reshape(r1 - r0, c1 - c0)
        return prob

    def segment_pair(self, features: PairFeatureStack) -> SegmentationResult:
        opt_pre = (
            features.b3_pre, features.b4_pre, features.b8_pre, features.b11_pre,
            features.ndwi_pre, features.mndwi_pre, features.ndvi_pre, features.aweish_pre,
        ) if features.has_optical else None
        opt_peak = (
            features.b3_peak, features.b4_peak, features.b8_peak, features.b11_peak,
            features.ndwi_peak, features.mndwi_peak, features.ndvi_peak, features.aweish_peak,
        ) if features.has_optical else None

        feats_pre = self._window_features(features, features.vv_pre, features.vh_pre, opt_pre, is_peak=False)
        feats_peak = self._window_features(features, features.vv_peak, features.vh_peak, opt_peak, is_peak=True)

        prob_pre = self._probability(feats_pre)
        prob_peak = self._probability(feats_peak)

        water_pre = _remove_small_components(prob_pre >= self.threshold, self.min_px)
        water_peak = _remove_small_components(prob_peak >= self.threshold, self.min_px)

        meta = {
            "segmenter": self.name,
            "has_optical": features.has_optical,
            "threshold": self.threshold,
        }
        return SegmentationResult(water_pre=water_pre, water_peak=water_peak, meta=meta)
