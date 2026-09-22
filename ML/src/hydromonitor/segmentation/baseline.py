"""Классический baseline — физически осмысленный пайплайн (без обучения).

Повторяет рецепт разметки из постановки кейса и служит нижней границей,
от которой отталкивается LightGBM:

* SAR: порог по VV методом Оцу с ограничением диапазона −22…−12 дБ (после фильтра Ли);
* оптика (где есть): MNDWI > 0.1, NDWI > 0.15, NDVI ≤ 0.2, AWEIsh > 0;
* гидрофильтры: уклон ≤ 5°, HAND ≤ 25 м, исключение застройки;
* мин. картируемая единица 25 пикселей (связные компоненты);
* flood = water_peak & ~water_pre & ~permanent (плюс падение VV ≥ 3 дБ на пике).

Все пороги берутся из ``configs/thresholds.yaml``.
"""

from __future__ import annotations

import numpy as np
from skimage.filters import threshold_otsu

from ..io import Raster
from ..features.sar import lee_filter
from .postprocess import remove_small_components


def _otsu_water_vv(vv: np.ndarray, vv_min: float, vv_max: float) -> np.ndarray:
    """Вода = пиксели ниже порога Оцу, вычисленного по VV, ограниченному диапазоном."""
    vv = np.asarray(vv, dtype="float32")
    clipped = np.clip(vv, vv_min, vv_max)
    valid = np.isfinite(clipped)
    if valid.sum() < 100:
        return np.zeros(vv.shape, dtype=bool)
    thresh = threshold_otsu(clipped[valid])
    return vv < thresh


def baseline_water(cfg, sar: Raster | None, optical: Raster | None, aux: Raster,
                   window: str) -> np.ndarray:
    """Бинарная маска открытой воды для одного окна (pre/peak).

    Возвращает bool-массив на сетке эталона. Если SAR нет (не выгружен) — пустая маска.
    """
    t = cfg.thresholds
    aux_b = aux.named()

    if sar is None:
        return np.zeros(aux.array.shape[1:], dtype=bool)

    vv = lee_filter(sar.band("VV"), window=int(t.get("speckle.window", 5)))
    water = _otsu_water_vv(vv, float(t.sar.vv_min), float(t.sar.vv_max))

    # оптика — уточнение (объединение с SAR), только если пригодна
    if optical is not None:
        b = optical.named()
        opt_water = (
            (b["MNDWI"] > float(t.optical.mndwi)) &
            (b["NDWI"] > float(t.optical.ndwi)) &
            (b["NDVI"] <= float(t.optical.ndvi)) &
            (b["AWEISH"] > float(t.optical.aweish))
        )
        water = water | opt_water

    # гидрофильтры
    slope_ok = aux_b["slope"] <= float(t.hydro.slope_max)
    hand_ok = aux_b["hand"] <= float(t.hydro.hand_max)
    not_builtup = aux_b["builtup"] < 0.5
    water = water & slope_ok & hand_ok & not_builtup

    water = remove_small_components(water, min_px=int(t.hydro.min_unit_px))
    return water


def baseline_masks(cfg, pair, sar_pre, sar_peak, optical_pre, optical_peak, aux) -> dict[str, np.ndarray]:
    """Полный набор масок пары: water_pre, water_peak, permanent, flood, receded."""
    aux_b = aux.named()
    permanent = aux_b["occurrence"] >= float(cfg.thresholds.hydro.permanent_occ)

    water_pre = baseline_water(cfg, sar_pre, optical_pre, aux, "pre")
    water_peak = baseline_water(cfg, sar_peak, optical_peak, aux, "peak")

    # падение обратного рассеяния на пике ≥ 3 дБ (физический признак затопления)
    drop_ok = np.ones(water_peak.shape, dtype=bool)
    if sar_pre is not None and sar_peak is not None:
        drop = lee_filter(sar_pre.band("VV"), int(cfg.thresholds.get("speckle.window", 5))) \
               - lee_filter(sar_peak.band("VV"), int(cfg.thresholds.get("speckle.window", 5)))
        drop_ok = drop >= float(cfg.thresholds.sar.drop_db)

    flood = water_peak & ~water_pre & ~permanent & drop_ok
    flood = remove_small_components(flood, min_px=int(cfg.thresholds.hydro.min_unit_px))
    receded = water_pre & ~water_peak

    return {
        "water_pre": water_pre,
        "water_peak": water_peak,
        "permanent": permanent,
        "flood": flood,
        "receded": receded,
    }
