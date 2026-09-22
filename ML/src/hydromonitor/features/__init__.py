"""Сборка признаков для пиксельного классификатора.

Схема — SAR-first, оптика как уточнение где есть:

* статические (AUX + гидроконтекст) — есть всегда;
* SAR (VV/VH/отношение + фильтр Ли) — есть всегда (все пары сняты Sentinel-1);
* оптические индексы — только там, где есть пригодная оптика; для пар без оптики
  каналы заполняются NaN, и LightGBM использует встроенную обработку пропусков
  (признак ``has_optical`` сообщает модели о модальности).

Тем самым одна модель корректно обслуживает и пары с оптикой, и без неё.
``is_peak`` — индикатор окна (pre=0 / peak=1): модель учится отличать межень от пика.
"""

from __future__ import annotations

import numpy as np

from ..io import Raster
from .sar import sar_features
from .optical import optical_features

STATIC_FEATURES = [
    "slope", "hand", "occurrence", "seasonality", "max_extent", "builtup",
    "dist_river", "hand_le_25", "slope_le_5", "occ_ge_80", "floodable",
]
SAR_FEATURES = ["vv", "vh", "vv_vh_ratio", "vv_lee", "vh_lee", "vv_vh_diff"]
OPTICAL_FEATURES = ["b3", "b4", "b8", "b11", "ndwi", "mndwi", "ndvi", "aweish"]

ALL_FEATURES = STATIC_FEATURES + SAR_FEATURES + OPTICAL_FEATURES + ["has_optical"]
FEATURE_NAMES = ALL_FEATURES + ["is_peak"]


def static_features(aux: Raster, dist_river: np.ndarray) -> dict[str, np.ndarray]:
    """Статические фичи из AUX + расстояние до русла + производные гидроподсказки.

    ``np.asarray`` без копии (вход уже float32) — экономим память на полных сетках.
    """
    b = aux.named()
    slope = b["slope"]
    hand = b["hand"]
    occ = b["occurrence"]
    max_extent = b["max_extent"]
    builtup = b["builtup"]
    seasonality = b["seasonality"]

    hand_le_25_b = hand <= 25.0
    slope_le_5_b = slope <= 5.0
    occ_ge_80_b = occ >= 80.0
    floodable_b = (max_extent > 0.5) | (hand_le_25_b & (builtup < 0.5))

    return {
        "slope": np.asarray(slope, dtype="float32"),
        "hand": np.asarray(hand, dtype="float32"),
        "occurrence": np.asarray(occ, dtype="float32"),
        "seasonality": np.asarray(seasonality, dtype="float32"),
        "max_extent": np.asarray(max_extent, dtype="float32"),
        "builtup": np.asarray(builtup, dtype="float32"),
        "dist_river": np.asarray(dist_river, dtype="float32"),
        "hand_le_25": hand_le_25_b.astype("float32"),
        "slope_le_5": slope_le_5_b.astype("float32"),
        "occ_ge_80": occ_ge_80_b.astype("float32"),
        "floodable": floodable_b.astype("float32"),
    }


def assemble_features(aux: Raster, dist_river: np.ndarray, sar: Raster | None,
                      optical: Raster | None, is_peak: bool = False) -> dict[str, np.ndarray]:
    """Полный вектор признаков для одного окна (pre/peak) одной пары.

    Пропущенные модальности (SAR/оптика) заполняются ОДНИМ общим NaN-массивом —
    колонки ссылаются на один и тот же буфер, что заметно экономит память.
    """
    feats = static_features(aux, dist_river)
    shape = aux.array.shape[1:]

    if sar is not None:
        feats.update(sar_features(sar))
    else:
        nan_arr = np.full(shape, np.nan, dtype="float32")
        for k in SAR_FEATURES:
            feats[k] = nan_arr

    if optical is not None:
        feats.update(optical_features(optical))
        feats["has_optical"] = np.ones(shape, dtype="float32")
    else:
        nan_arr = np.full(shape, np.nan, dtype="float32")
        for k in OPTICAL_FEATURES:
            feats[k] = nan_arr
        feats["has_optical"] = np.zeros(shape, dtype="float32")

    feats["is_peak"] = np.full(shape, 1.0 if is_peak else 0.0, dtype="float32")
    return feats
