"""Точка подключения ML-модели.

Модель разрабатывается отдельно и должна:
  1) лежать в src/segmentation/ml_model.py (или другом модуле — путь настраивается ниже);
  2) экспортировать класс, наследующий Segmenter из base.py, с методом segment_pair(...);
  3) конструктор класса должен принимать один позиционный аргумент — dict с секцией
     `segmentation` из configs/config.yaml (гиперпараметры модели удобно держать
     там же, в отдельной подсекции, например segmentation.lightgbm.*).

Backend-сервис не знает про внутренности модели — он вызывает только
Segmenter.segment_pair(). Сегментатор создаётся один раз при старте приложения
и переиспользуется между запросами (см. src/service/deps.py).
"""
from __future__ import annotations

import importlib
import logging

from .base import Segmenter
from .baseline import BaselineSegmenter

logger = logging.getLogger("hydromonitor.segmentation")

# backend_name -> "module.path:ClassName"
_KNOWN_BACKENDS: dict[str, str] = {
    # Пример подключения обученной модели (модуль и класс — из отдельной разработки):
    "lightgbm": "src.segmentation.ml_model:LightGBMSegmenter",
}


def build_segmenter_from_config(segmentation_cfg: dict) -> Segmenter:
    """Создаёт сегментатор согласно segmentation.backend из config.yaml.

    При отсутствии/ошибке загрузки указанного backend'а безопасно откатывается
    на классический baseline, чтобы сервис оставался воспроизводимым.
    """
    backend = segmentation_cfg.get("backend", "baseline")

    if backend == "baseline":
        return BaselineSegmenter(segmentation_cfg)

    target = _KNOWN_BACKENDS.get(backend)
    if target is None:
        logger.warning("Неизвестный backend сегментации '%s' — используется baseline.", backend)
        return BaselineSegmenter(segmentation_cfg)

    module_path, class_name = target.split(":")
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(segmentation_cfg)
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "Не удалось загрузить ML-модель '%s' (%s). Используется baseline как fallback.",
            backend, exc,
        )
        return BaselineSegmenter(segmentation_cfg)
