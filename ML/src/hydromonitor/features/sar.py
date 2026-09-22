"""Фичи радиолокационного канала (Sentinel-1).

SAR — ядро решения (всепогодный канал). Здесь: фильтрация спекла (фильтр Ли),
исходные каналы VV/VH/VV_VH_ratio и сглаженные версии.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter


def lee_filter(img: np.ndarray, window: int = 5, enl: float = 5.0) -> np.ndarray:
    """Фильтр Ли для мультипликативного спекл-шума (адаптивный).

    Сглаживает однородные участки и сохраняет границы. Применяется к каналам
    обратного рассеяния в дБ — стандартное приближение для GRD-продуктов.
    ``enl`` — эффективное число взглядов (зависит от числа усреднений в GRD).
    """
    img = np.asarray(img, dtype="float32")
    mean = uniform_filter(img, window)
    mean_sq = uniform_filter(img * img, window)
    var = np.maximum(mean_sq - mean * mean, 0.0)
    sigma_u = 1.0 / np.sqrt(max(enl, 1.0))
    denom = var + sigma_u * sigma_u * mean * mean + 1e-12
    k = var / denom
    return (mean + k * (img - mean)).astype("float32")


def sar_features(sar) -> dict[str, np.ndarray]:
    """Нормализованный набор SAR-фич из стека (VV, VH, VV_VH_ratio).

    ``sar`` — объект Raster с полями VV/VH/VV_VH_ratio в дБ, либо словарь каналов.
    """
    if hasattr(sar, "named"):
        b = sar.named()
    else:
        b = sar
    vv = np.asarray(b["VV"], dtype="float32")
    vh = np.asarray(b["VH"], dtype="float32")
    ratio = np.asarray(b["VV_VH_ratio"], dtype="float32")
    return {
        "vv": vv,
        "vh": vh,
        "vv_vh_ratio": ratio,
        "vv_lee": lee_filter(vv),
        "vh_lee": lee_filter(vh),
        "vv_vh_diff": vv - vh,
    }
