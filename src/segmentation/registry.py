from __future__ import annotations

import importlib
import logging

from .base import Segmenter
from .baseline import BaselineSegmenter

logger = logging.getLogger("hydromonitor.segmentation")

# backend_name -> "module.path:ClassName"
_KNOWN_BACKENDS: dict[str, str] = {
    "lightgbm": "src.segmentation.ml_model:LightGBMSegmenter",
}


def build_segmenter_from_config(segmentation_cfg: dict) -> Segmenter:
    """Создаёт сегментатор согласно segmentation.backend из config.yaml. """
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
