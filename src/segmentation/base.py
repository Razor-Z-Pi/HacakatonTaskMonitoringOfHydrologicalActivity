"""Контракт между backend-сервисом и модулем сегментации (Модуль 1 из постановки кейса).

ML-модель разрабатывается отдельно и должна реализовать класс Segmenter ниже —
тогда backend подключит её без изменений в остальном коде (см. registry.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
from rasterio.profiles import Profile


@dataclass
class PairFeatureStack:
    """Все признаки одной пары "до/пик", уже выровненные на единую сетку 10 м."""

    # SAR, дБ
    vv_pre: np.ndarray
    vh_pre: np.ndarray
    vv_peak: np.ndarray
    vh_peak: np.ndarray

    # Оптика (может отсутствовать — 4 из 8 паводковых пар и все контрольные без оптики)
    ndwi_pre: Optional[np.ndarray]
    mndwi_pre: Optional[np.ndarray]
    ndvi_pre: Optional[np.ndarray]
    aweish_pre: Optional[np.ndarray]
    ndwi_peak: Optional[np.ndarray]
    mndwi_peak: Optional[np.ndarray]
    ndvi_peak: Optional[np.ndarray]
    aweish_peak: Optional[np.ndarray]

    # AUX, выровненные на эталонную сетку
    slope: np.ndarray
    hand: np.ndarray
    occurrence: np.ndarray  # %, встречаемость воды JRC GSW
    seasonality: np.ndarray
    max_extent: np.ndarray
    builtup: np.ndarray

    profile: Profile  # геопривязка канонической сетки

    @property
    def has_optical(self) -> bool:
        return self.ndwi_peak is not None

    @property
    def permanent_water_mask(self) -> np.ndarray:
        """Постоянная вода — occurrence >= порога, задаётся сегментатором/конфигом снаружи."""
        raise NotImplementedError("Используйте occurrence напрямую с порогом из конфига")


@dataclass
class SegmentationResult:
    water_pre: np.ndarray   # bool-маска, водная поверхность на дату "до"
    water_peak: np.ndarray  # bool-маска, водная поверхность на дату пика
    meta: dict              # диагностика: пороги, доли пропусков и т.п.


class Segmenter(ABC):
    """Интерфейс, который обязана реализовать ML-модель (Модуль 1: сегментация)."""

    name: str = "base"

    @abstractmethod
    def segment_pair(self, features: PairFeatureStack) -> SegmentationResult:
        """Возвращает бинарные маски воды на "до" и на "пик" по всему AOI."""
        raise NotImplementedError
