"""Фичи оптического канала (Sentinel-2 L2A).

Оптика — уточнение там, где она есть и не закрыта облаками. Индексы уже
предрассчитаны в стеке (NDWI/MNDWI/NDVI/AWEISH); здесь они передаются как есть
вместе с отражательными каналами B3/B4/B8/B11.
"""

from __future__ import annotations

import numpy as np


def optical_features(opt) -> dict[str, np.ndarray]:
    """Нормализованный набор оптических фич.

    ``opt`` — объект Raster с каналами B3,B4,B8,B11,NDWI,MNDWI,NDVI,AWEISH
    (отражение 0..1, индексы безразмерные).
    """
    b = opt.named() if hasattr(opt, "named") else opt
    out: dict[str, np.ndarray] = {}
    for k, v in b.items():
        out[k.lower()] = np.asarray(v, dtype="float32")
    return out
