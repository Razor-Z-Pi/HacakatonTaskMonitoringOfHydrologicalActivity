"""Постобработка бинарных масок: связные компоненты, минимальная единица, заливка."""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def remove_small_components(mask: np.ndarray, min_px: int = 25, connectivity: int = 8) -> np.ndarray:
    """Убрать связные компоненты меньше ``min_px`` пикселей.

    Минимальная картируемая единица 25 px задана в постановке; изолированные
    «озёра» посреди водораздела — типичные ложные срабатывания.
    """
    mask = np.asarray(mask, dtype=bool)
    if min_px <= 1:
        return mask
    structure = ndimage.generate_binary_structure(2, connectivity)
    labels, n = ndimage.label(mask, structure=structure)
    if n == 0:
        return mask
    sizes = ndimage.sum(mask, labels, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, dtype=bool)
    keep[np.where(sizes >= min_px)[0] + 1] = True
    return keep[labels]


def largest_components(mask: np.ndarray, k: int = 1, connectivity: int = 8) -> np.ndarray:
    """Оставить ``k`` крупнейших связных компонент (если ``k`` < 1 — без ограничения)."""
    mask = np.asarray(mask, dtype=bool)
    if k < 1:
        return mask
    structure = ndimage.generate_binary_structure(2, connectivity)
    labels, n = ndimage.label(mask, structure=structure)
    if n <= k:
        return mask
    sizes = ndimage.sum(mask, labels, index=np.arange(1, n + 1))
    top = np.argsort(sizes)[::-1][:k] + 1
    keep = np.zeros(n + 1, dtype=bool)
    keep[top] = True
    return keep[labels]


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Залить внутренние дыры в маске (опционально, для аккуратных контуров)."""
    return ndimage.binary_fill_holes(np.asarray(mask, dtype=bool))
