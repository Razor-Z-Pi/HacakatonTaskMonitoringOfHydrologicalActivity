"""Классический (не-ML) baseline, повторяющий рецепт разметки эталона из постановки кейса.

Нужен как:
  1) точка отсчёта для сравнения с ML-моделью (критерий "Экспериментальная проверка");
  2) рабочий fallback, чтобы сервис был воспроизводим и запускался без обученной модели.

SAR-first: радиолокационный канал — обязательное ядро; оптика используется как уточнение
там, где она доступна (4 из 8 паводковых пар и все контрольные пары оптики не имеют).
"""
from __future__ import annotations

import numpy as np
from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_objects, binary_opening

from .base import PairFeatureStack, Segmenter, SegmentationResult


def _otsu_water_from_vv(vv_db: np.ndarray, vv_min_db: float, vv_max_db: float) -> tuple[np.ndarray, float]:
    """Порог Оцу по гистограмме VV, ограниченной диапазоном [vv_min_db, vv_max_db]."""
    clipped = np.clip(vv_db, vv_min_db, vv_max_db)
    valid = clipped[np.isfinite(clipped)]
    if valid.size == 0 or np.allclose(valid.min(), valid.max()):
        # Вырожденная сцена (нет контраста) — считаем, что воды нет.
        return np.zeros_like(vv_db, dtype=bool), vv_max_db
    try:
        thr = threshold_otsu(valid)
    except ValueError:
        thr = float(np.median(valid))
    return (clipped < thr), float(thr)


def _optical_water(
    ndwi: np.ndarray, mndwi: np.ndarray, ndvi: np.ndarray, aweish: np.ndarray,
    ndwi_min: float, mndwi_min: float, ndvi_max: float, aweish_min: float,
) -> np.ndarray:
    return (mndwi > mndwi_min) & (ndwi > ndwi_min) & (ndvi <= ndvi_max) & (aweish > aweish_min)


def _apply_hydro_filters(
    water: np.ndarray, slope: np.ndarray, hand: np.ndarray, builtup: np.ndarray,
    slope_max_deg: float, hand_max_m: float,
) -> np.ndarray:
    """Отсекает физически маловероятные срабатывания: крутые склоны, HAND, застройку."""
    out = water & (slope <= slope_max_deg) & (hand <= hand_max_m) & (~builtup.astype(bool))
    return out


def _apply_mmu(water: np.ndarray, min_size_px: int) -> np.ndarray:
    if min_size_px <= 1:
        return water
    cleaned = binary_opening(water)
    cleaned = remove_small_objects(cleaned, min_size=min_size_px)
    return cleaned


class BaselineSegmenter(Segmenter):
    """Классический пайплайн: Otsu(VV) [+ индексы, где есть оптика] + HAND/уклон/застройка + MMU."""

    name = "baseline"

    def __init__(self, cfg: dict):
        self.otsu_cfg = cfg["otsu"]
        self.optical_cfg = cfg["optical"]
        self.filters_cfg = cfg["filters"]

    def _segment_date(
        self,
        vv_db: np.ndarray,
        ndwi: np.ndarray | None,
        mndwi: np.ndarray | None,
        ndvi: np.ndarray | None,
        aweish: np.ndarray | None,
        slope: np.ndarray,
        hand: np.ndarray,
        builtup: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        water_sar, thr = _otsu_water_from_vv(
            vv_db, self.otsu_cfg["vv_min_db"], self.otsu_cfg["vv_max_db"]
        )

        if ndwi is not None:
            water_opt = _optical_water(
                ndwi, mndwi, ndvi, aweish,
                self.optical_cfg["ndwi_min"], self.optical_cfg["mndwi_min"],
                self.optical_cfg["ndvi_max"], self.optical_cfg["aweish_min"],
            )
            # SAR-first: SAR — обязательное ядро, оптика добавляет recall там, где доступна
            # (ошибки каналов по большей части независимы — см. постановку, раздел
            # "Почему требуется именно совместная обработка").
            water = water_sar | water_opt
        else:
            water = water_sar

        water = _apply_hydro_filters(
            water, slope, hand, builtup,
            self.filters_cfg["slope_max_deg"], self.filters_cfg["hand_max_m"],
        )
        water = _apply_mmu(water, self.filters_cfg["min_mapping_unit_px"])
        return water, thr

    def segment_pair(self, features: PairFeatureStack) -> SegmentationResult:
        water_pre, thr_pre = self._segment_date(
            features.vv_pre, features.ndwi_pre, features.mndwi_pre,
            features.ndvi_pre, features.aweish_pre,
            features.slope, features.hand, features.builtup,
        )
        water_peak, thr_peak = self._segment_date(
            features.vv_peak, features.ndwi_peak, features.mndwi_peak,
            features.ndvi_peak, features.aweish_peak,
            features.slope, features.hand, features.builtup,
        )
        meta = {
            "segmenter": self.name,
            "has_optical": features.has_optical,
            "otsu_threshold_pre_db": thr_pre,
            "otsu_threshold_peak_db": thr_peak,
        }
        return SegmentationResult(water_pre=water_pre, water_peak=water_peak, meta=meta)
